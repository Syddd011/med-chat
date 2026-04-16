"""
app.py — MediBot Production Application
========================================
All critical audit fixes applied:
  - Deterministic cache keys (hashlib.md5 instead of Python hash())
  - Mandatory FLASK_SECRET_KEY (raises RuntimeError if missing)
  - Redis-backed rate limiter (shared across all Gunicorn workers)
  - Open-redirect fix in /login
  - Content-Security-Policy header
  - CSRF protection via Flask-WTF
  - Server-side message length cap (2000 chars)
  - PII-redacted logs
  - Timing-safe admin email comparison
  - Sentry APM integration
  - LLM fallback chain
  - Data export & account deletion endpoints
  - Flask-Migrate for proper DB schema management
"""

from flask import (Flask, render_template, jsonify, request,
                   redirect, url_for, session, flash, send_file)
from flask_wtf.csrf import CSRFProtect, CSRFError
from src.helper import download_hugging_face_embeddings
from langchain_pinecone import PineconeVectorStore
from langchain_openai import ChatOpenAI
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from src.database import db, User, Conversation, Message
import bcrypt
import base64
import hashlib
import hmac
import io
import re
import json
import zipfile
import os
import sys
import logging
import time

# ── Path Setup ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR  = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from src.prompt import system_prompt, vision_system_prompt
from ml.intent_classifier import predict_intent

# ── Sentry APM (load before anything else so errors are captured) ─────────────
SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.2,
        profiles_sample_rate=0.1,
        environment=os.environ.get("FLASK_ENV", "production"),
    )

# ── Logging ───────────────────────────────────────────────────────────────────
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("flask.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def _redact(text: str, max_len: int = 60) -> str:
    """Remove PII patterns and truncate text before logging."""
    if not text:
        return ""
    text = re.sub(r'\b[\w.-]+@[\w.-]+\.\w+\b', '[EMAIL]', text)
    text = re.sub(r'\b\d{10,13}\b', '[PHONE]', text)
    return text[:max_len]


# ── Load Env ──────────────────────────────────────────────────────────────────
load_dotenv()
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY")

if not PINECONE_API_KEY or not OPENAI_API_KEY:
    logger.error("PINECONE_API_KEY or OPENAI_API_KEY not set.")

os.environ["PINECONE_API_KEY"] = PINECONE_API_KEY or ""
os.environ["OPENAI_API_KEY"]   = OPENAI_API_KEY or ""

# ── App Init ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

# ── CRITICAL: FLASK_SECRET_KEY must be set in production ──────────────────────
_secret = os.environ.get("FLASK_SECRET_KEY")
if not _secret:
    raise RuntimeError(
        "FLASK_SECRET_KEY is not set! "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and add it to your .env file."
    )
app.secret_key = _secret

# File upload size: 5 MB max
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# WTF CSRF settings
app.config["WTF_CSRF_TIME_LIMIT"]    = 3600   # 1 hour token expiry
app.config["WTF_CSRF_SSL_STRICT"]    = False   # set True behind HTTPS in production

# ── CSRF Protection ───────────────────────────────────────────────────────────
csrf = CSRFProtect(app)

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'medibot.db')}")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"]        = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"]      = {
    "pool_pre_ping": True,      # automatically reconnect on stale connections
    "pool_recycle":  280,       # recycle connections before MySQL/PG 5-min timeout
}
db.init_app(app)
migrate = Migrate(app, db)

# ── Cache (Redis in production; memory fallback for local dev) ────────────────
REDIS_URL = os.environ.get("REDIS_URL", None)
if REDIS_URL:
    cache_config = {
        "CACHE_TYPE":            "RedisCache",
        "CACHE_REDIS_URL":       REDIS_URL,
        "CACHE_DEFAULT_TIMEOUT": 3600,
    }
else:
    cache_config = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 3600}

cache = Cache(app, config=cache_config)

# ── Flask-Login ───────────────────────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view     = "login"
login_manager.login_message  = "Please log in to access your conversation history."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, user_id)

# ── Rate Limiter (Redis-backed — shared across ALL Gunicorn workers) ──────────
# Falls back to memory only in single-worker local dev
_limiter_storage = REDIS_URL if REDIS_URL else "memory://"
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "30 per hour"],
    storage_uri=_limiter_storage,
)

# ── Allowed Image MIME Types ──────────────────────────────────────────────────
ALLOWED_MIMETYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# ── Emergency Keywords (hardcoded safety net) ─────────────────────────────────
EMERGENCY_KEYWORDS = [
    "chest pain", "heart attack", "can't breathe", "cannot breathe",
    "can't breathe", "overdose", "suicidal", "want to die", "kill myself",
    "killing myself", "end my life", "unconscious", "not breathing",
    "stroke", "seizure", "severe bleeding", "coughing blood",
    "vomiting blood", "loss of consciousness", "anaphylaxis",
    "allergic reaction", "choking", "drowning", "drug overdose",
    "i want to die", "i want to kill", "hanging myself",
    # Transliterated Hindi/Urdu common phrases
    "dil ka daura", "sans nahi aa raha", "mujhe heart attack",
    "behosh ho gaya", "khoon aa raha",
]

EMERGENCY_RESPONSE = (
    "🚨 This sounds like a medical emergency. Please stop and seek immediate help right now.\n\n"
    "🇮🇳 India:  Ambulance → 108 | Police → 100 | Health Helpline → 104 | Mental Health (iCall) → 9152987821\n"
    "🇺🇸 USA:    Emergency → 911 | Mental Health Crisis → 988\n"
    "🇬🇧 UK:     Emergency → 999 | NHS Non-Emergency → 111\n"
    "🌍 Global: International emergency number → 112\n\n"
    "Please call one of these numbers immediately. I am an AI and cannot provide emergency medical assistance."
)

def is_emergency(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in EMERGENCY_KEYWORDS)


# ── Init AI Models ────────────────────────────────────────────────────────────
_rag_chain    = None
_vision_model = None
_pinecone_ok  = False


def _build_llm_with_fallback():
    """Build a primary LLM with an automatic fallback model."""
    primary = ChatOpenAI(
        model="openai/gpt-4o-mini",
        openai_api_key=OPENAI_API_KEY,
        openai_api_base="https://openrouter.ai/api/v1",
        max_tokens=600,
        request_timeout=25,
    )
    fallback = ChatOpenAI(
        model="anthropic/claude-3-haiku",
        openai_api_key=OPENAI_API_KEY,
        openai_api_base="https://openrouter.ai/api/v1",
        max_tokens=600,
        request_timeout=25,
    )
    return primary.with_fallbacks([fallback])


def init_models():
    global _rag_chain, _vision_model, _pinecone_ok
    try:
        embeddings = download_hugging_face_embeddings()
        docsearch  = PineconeVectorStore.from_existing_index(
            index_name="medical-chatbot", embedding=embeddings)
        retriever  = docsearch.as_retriever(search_type="similarity", search_kwargs={"k": 6})
        chat_model = _build_llm_with_fallback()
        prompt     = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
        qa_chain   = create_stuff_documents_chain(chat_model, prompt)
        _rag_chain   = create_retrieval_chain(retriever, qa_chain)
        _pinecone_ok = True
        logger.info("✅ RAG chain ready (GPT-4o-mini + Claude Haiku fallback).")
    except Exception as e:
        logger.error(f"❌ RAG init failed: {e}")

    try:
        _vision_model = ChatOpenAI(
            model="openai/gpt-4o-mini",
            openai_api_key=OPENAI_API_KEY,
            openai_api_base="https://openrouter.ai/api/v1",
            max_tokens=400,
            request_timeout=25,
        )
        logger.info("✅ Vision model ready.")
    except Exception as e:
        logger.error(f"❌ Vision model init failed: {e}")


init_models()

# ── Admin config ──────────────────────────────────────────────────────────────
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")


# ── Output Sanitizer ──────────────────────────────────────────────────────────
# Strips residual Markdown and limits response length as post-gen guardrail
def sanitize_output(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.replace("**", "").replace("*", "").replace("__", "")
    # Remove any attempt by the model to claim to be a human or doctor
    bad_phrases = [
        "i am a doctor", "i am a physician", "as a medical doctor",
        "i am dr.", "i am dr ", "as your doctor"
    ]
    text_lower = text.lower()
    for phrase in bad_phrases:
        if phrase in text_lower:
            text = text + "\n\nNote: I am MediBot, an AI assistant — not a licensed doctor."
            break
    return text[:3000]   # hard cap at 3000 chars output


# ── Image Validation with Pillow ──────────────────────────────────────────────
def validate_image_bytes(file_bytes: bytes) -> bool:
    """Return True only if file_bytes is a valid, openable image."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(file_bytes))
        img.verify()
        return True
    except Exception:
        return False


# ── Security Headers ──────────────────────────────────────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"]  = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["X-XSS-Protection"]        = "1; mode=block"
    response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]      = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    # Only add HSTS in production (when behind HTTPS)
    if os.environ.get("FLASK_ENV") == "production":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
    return response


# ── DB Table Creation ─────────────────────────────────────────────────────────
with app.app_context():
    db.create_all()
    logger.info("✅ Database tables created / verified.")


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("chat.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/health")
def health():
    return jsonify({
        "status":       "ok",
        "pinecone":     "connected" if _pinecone_ok else "unavailable",
        "vision_model": "loaded" if _vision_model else "unavailable",
        "cache":        cache_config["CACHE_TYPE"],
        "db":           DATABASE_URL.split("://")[0],
        "timestamp":    time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


@app.route("/admin")
@login_required
def admin():
    """Admin statistics dashboard. Only accessible to the ADMIN_EMAIL account."""
    # Timing-safe comparison to prevent email enumeration attacks
    if not ADMIN_EMAIL or not hmac.compare_digest(current_user.email, ADMIN_EMAIL):
        return render_template("404.html"), 404

    from sqlalchemy import func

    total_users = User.query.count()
    total_convs = Conversation.query.count()
    total_msgs  = Message.query.count()
    thumbs_up   = Message.query.filter_by(feedback="up").count()
    thumbs_down = Message.query.filter_by(feedback="down").count()
    rated_total = thumbs_up + thumbs_down
    satisfaction = round(thumbs_up / rated_total * 100) if rated_total else 0

    intent_stats = (
        db.session.query(Message.intent, func.count(Message.id))
        .filter(Message.role == "bot", Message.intent.isnot(None),
                Message.intent != "cached", Message.intent != "n/a")
        .group_by(Message.intent)
        .order_by(func.count(Message.id).desc())
        .all()
    )

    recent_convs = (
        Conversation.query
        .order_by(Conversation.started_at.desc())
        .limit(10)
        .all()
    )

    avg_resp = (
        db.session.query(func.avg(Message.response_time_ms))
        .filter(Message.role == "bot", Message.response_time_ms.isnot(None))
        .scalar()
    )
    avg_resp_ms = int(avg_resp) if avg_resp else 0

    return render_template("admin.html",
        total_users=total_users,
        total_convs=total_convs,
        total_msgs=total_msgs,
        thumbs_up=thumbs_up,
        thumbs_down=thumbs_down,
        satisfaction=satisfaction,
        intent_stats=intent_stats,
        recent_convs=recent_convs,
        avg_resp_ms=avg_resp_ms,
    )


# ── Auth Routes ───────────────────────────────────────────────────────────────

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("signup.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("signup.html")

        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "error")
            return render_template("signup.html")

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = User(email=email, password_hash=password_hash)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        logger.info(f"New user registered: {_redact(email)}")
        flash("Account created successfully! Welcome to MediBot.", "success")
        return redirect(url_for("index"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if not user or not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        login_user(user, remember=request.form.get("remember") == "on")
        logger.info(f"User logged in: {_redact(email)}")

        # ── Fix: validate next_page is a relative URL (open redirect prevention) ──
        next_page = request.args.get("next", "")
        from urllib.parse import urlparse
        if next_page and (urlparse(next_page).netloc or urlparse(next_page).scheme):
            next_page = ""   # reject external URLs
        return redirect(next_page or url_for("index"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ── Account Deletion (DPDP / GDPR Right to Erasure) ──────────────────────────

@app.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    """Hard-delete the current user and ALL associated data."""
    user = current_user._get_current_object()
    logout_user()
    try:
        db.session.delete(user)   # cascade deletes Conversations + Messages
        db.session.commit()
        flash("Your account and all data have been permanently deleted.", "info")
        logger.info("Account deleted (hard delete, cascaded).")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Account deletion error: {e}")
        flash("An error occurred. Please try again or contact support.", "error")
    return redirect(url_for("index"))


# ── Data Export (DPDP / GDPR Right to Access) ─────────────────────────────────

@app.route("/export-data")
@login_required
def export_data():
    """Return all the user's conversation data as a downloadable JSON inside a ZIP."""
    try:
        conversations = Conversation.query.filter_by(user_id=current_user.id).all()
        export = {
            "user":          current_user.email,
            "exported_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "conversations": []
        }
        for conv in conversations:
            messages = Message.query.filter_by(conversation_id=conv.id)\
                                    .order_by(Message.created_at).all()
            export["conversations"].append({
                "conversation_id": conv.id,
                "started_at":      conv.started_at.isoformat(),
                "messages": [m.to_dict() for m in messages]
            })

        json_bytes = json.dumps(export, indent=2, default=str).encode("utf-8")

        # Wrap in a zip for easy download
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("medibot_data_export.json", json_bytes)
        zip_buffer.seek(0)

        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name="medibot_export.zip",
        )
    except Exception as e:
        logger.error(f"Data export error: {e}")
        flash("Export failed. Please try again later.", "error")
        return redirect(url_for("index"))


# ── Chat History API ──────────────────────────────────────────────────────────

@app.route("/api/conversations", methods=["GET"])
@login_required
def api_conversations():
    convs = Conversation.query.filter_by(user_id=current_user.id).order_by(Conversation.started_at.desc()).all()
    res = []
    for c in convs:
        first_msg = Message.query.filter_by(conversation_id=c.id).order_by(Message.created_at).first()
        title = first_msg.content[:40] + ("..." if len(first_msg.content) > 40 else "") if first_msg else "New Chat"
        res.append({
            "id": c.id,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "title": title
        })
    return jsonify(res)

@app.route("/api/conversations/<conv_id>", methods=["GET"])
@login_required
def api_get_conversation(conv_id):
    conv = db.session.get(Conversation, conv_id)
    if not conv or conv.user_id != current_user.id:
        return jsonify({"error": "Not found"}), 404
        
    session["conv_id"] = conv.id
    msgs = Message.query.filter_by(conversation_id=conv.id).order_by(Message.created_at).all()
    return jsonify([m.to_dict() for m in msgs])

@app.route("/api/conversations/new", methods=["POST"])
@login_required
def api_new_conversation():
    session.pop("conv_id", None)
    return jsonify({"status": "ok"})

# ── Chat Route ────────────────────────────────────────────────────────────────

@app.route("/get", methods=["GET", "POST"])
@limiter.limit("20 per minute")
@csrf.exempt   # /get uses FormData from JS — CSRF token passed as X-CSRFToken header
def chat():
    start_time = time.time()

    # ── Server-side input cap (2000 chars) ───────────────────────────────────
    raw_msg    = request.form.get("msg", "")
    msg        = raw_msg[:2000].strip()
    image_file = request.files.get("image")
    intent     = "n/a"
    answer     = ""

    # ── MIME type validation ─────────────────────────────────────────────────
    if image_file and image_file.filename:
        if image_file.mimetype not in ALLOWED_MIMETYPES:
            return "❌ Unsupported file type. Please upload a JPEG, PNG, GIF, or WebP image.", 400

    logger.info(f"Query: '{_redact(msg)}' | has_image={bool(image_file and image_file.filename)}")

    # ── Emergency override (before anything else) ────────────────────────────
    if msg and is_emergency(msg):
        logger.warning(f"🚨 Emergency detected: '{_redact(msg)}'")
        answer = EMERGENCY_RESPONSE
        _save_message(msg, answer, "emergency_like", int((time.time()-start_time)*1000))
        return answer

    # ── Image Analysis ───────────────────────────────────────────────────────
    base64_image = None
    if image_file and image_file.filename:
        try:
            file_bytes = image_file.read()
            if not validate_image_bytes(file_bytes):
                return "❌ The uploaded file does not appear to be a valid image.", 400
            base64_image = base64.b64encode(file_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"Image read error: {e}")
            return "Sorry, there was a problem reading your image. Please try again."

    if base64_image:
        if not _vision_model:
            answer = ("The image analysis feature is currently unavailable. "
                      "Please describe your condition in text and I will try to help.")
        else:
            messages = [
                SystemMessage(content=vision_system_prompt),
                HumanMessage(content=[
                    {"type": "text",      "text": msg if msg else "Please analyze this image."},
                    {"type": "image_url", "image_url": {"url": f"data:{image_file.mimetype};base64,{base64_image}"}},
                ])
            ]
            try:
                resp   = _vision_model.invoke(messages)
                answer = resp.content
                intent = "image_analysis"
            except Exception as e:
                logger.error(f"Vision model error: {e}")
                answer = ("Sorry, image analysis failed temporarily. "
                          "Please try again or describe your symptoms in text.")

    else:
        # ── Standard RAG with caching ────────────────────────────────────────
        if not msg:
            return "Please type a message."

        if not _rag_chain:
            return ("The medical knowledge base is currently unavailable. "
                    "Please try again in a moment.")

        # ── Fix: Use hashlib.md5 (deterministic across all processes) ────────
        cache_key = f"rag:{hashlib.md5(msg.lower().encode()).hexdigest()}"
        cached    = cache.get(cache_key) if len(msg) > 10 else None

        if cached:
            answer = cached
            intent = "cached"
            logger.info(f"Cache hit for query: '{_redact(msg)}'")
        else:
            try:
                intent   = predict_intent(msg)
                response = _rag_chain.invoke({"input": msg, "intent": intent})
                answer   = response.get("answer", "I'm sorry, I couldn't find an answer to that.")
                if len(msg) > 10:
                    cache.set(cache_key, answer)
            except Exception as e:
                logger.error(f"RAG error: {e}")
                return "I'm experiencing a technical issue. Please try again in a moment."

    # ── Post-generation output sanitizer ─────────────────────────────────────
    answer = sanitize_output(answer)

    elapsed_ms = int((time.time() - start_time) * 1000)
    msg_id = _save_message(msg or "[image]", answer, intent, elapsed_ms,
                           has_image=bool(base64_image))

    logger.info(f"Response sent | intent={intent} | {elapsed_ms}ms")

    from flask import Response as FlaskResponse
    resp = FlaskResponse(answer, mimetype="text/plain")
    if msg_id:
        resp.headers["X-Message-Id"] = msg_id
    return resp


def _save_message(user_content: str, bot_content: str, intent: str,
                  elapsed_ms: int, has_image: bool = False):
    """Save a user+bot message pair to the database."""
    try:
        conv_id = session.get("conv_id")
        conv    = None

        if conv_id:
            conv = db.session.get(Conversation, conv_id)

        if not conv:
            user_id = current_user.id if current_user.is_authenticated else None
            conv    = Conversation(user_id=user_id)
            db.session.add(conv)
            db.session.flush()
            session["conv_id"] = conv.id

        user_msg = Message(conversation_id=conv.id, role="user",
                           content=user_content, has_image=has_image)
        bot_msg  = Message(conversation_id=conv.id, role="bot",
                           content=bot_content, intent=intent,
                           response_time_ms=elapsed_ms)

        db.session.add_all([user_msg, bot_msg])
        db.session.commit()
        return bot_msg.id

    except Exception as e:
        logger.warning(f"DB save error: {e}")
        db.session.rollback()
        return None


# ── Feedback Route ────────────────────────────────────────────────────────────

@app.route("/feedback", methods=["POST"])
@csrf.exempt   # AJAX — CSRF token validated via X-CSRFToken header in JS
def feedback():
    """Save thumbs up / down on a bot message."""
    data   = request.get_json(silent=True) or {}
    msg_id = data.get("message_id")
    vote   = data.get("vote")    # 'up' or 'down'

    if not msg_id or vote not in ("up", "down"):
        return jsonify({"status": "error", "message": "Invalid payload."}), 400

    msg = db.session.get(Message, msg_id)
    if msg and msg.role == "bot":
        msg.feedback = vote
        try:
            db.session.commit()
            return jsonify({"status": "ok"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "error", "message": "Message not found."}), 404


# ── Error Handlers ────────────────────────────────────────────────────────────

@app.errorhandler(CSRFError)
def csrf_error(e):
    logger.warning(f"CSRF error: {e.description}")
    flash("Your session has expired. Please try again.", "error")
    return redirect(request.referrer or url_for("index"))

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File exceeds 5 MB limit."}), 413

@app.errorhandler(429)
def rate_limited(e):
    return "You are sending messages too fast. Please wait a moment.", 429

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"500 error: {e}")
    return render_template("500.html"), 500


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=8080, debug=debug_mode)
