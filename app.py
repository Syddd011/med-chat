from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash
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
from src.database import db, User, Conversation, Message
import bcrypt
import base64
import io
from src.prompt import *
import os
import sys
import logging
import time

# ── Path Setup ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR  = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ml.intent_classifier import predict_intent

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("flask.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ── App Init ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))

# File upload size: 5 MB max
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'medibot.db')}")
# Fix for Heroku/Render postgres:// → postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"]        = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# ── Cache (memory by default; swap to Redis in production) ───────────────────
REDIS_URL = os.environ.get("REDIS_URL", None)
if REDIS_URL:
    cache_config = {"CACHE_TYPE": "RedisCache", "CACHE_REDIS_URL": REDIS_URL,
                    "CACHE_DEFAULT_TIMEOUT": 3600}
else:
    cache_config = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 3600}

cache = Cache(app, config=cache_config)

# ── Flask-Login ───────────────────────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access your conversation history."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(get_remote_address, app=app,
                  default_limits=["200 per day", "30 per hour"],
                  storage_uri="memory://")

# ── Load Env ──────────────────────────────────────────────────────────────────
load_dotenv()
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY")

if not PINECONE_API_KEY or not OPENAI_API_KEY:
    logger.error("PINECONE_API_KEY or OPENAI_API_KEY not set.")

os.environ["PINECONE_API_KEY"] = PINECONE_API_KEY or ""
os.environ["OPENAI_API_KEY"]   = OPENAI_API_KEY or ""

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
    "i want to die", "i want to kill", "hanging myself"
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
_rag_chain     = None
_vision_model  = None
_pinecone_ok   = False

def init_models():
    global _rag_chain, _vision_model, _pinecone_ok
    try:
        embeddings = download_hugging_face_embeddings()
        docsearch  = PineconeVectorStore.from_existing_index(
            index_name="medical-chatbot", embedding=embeddings)
        retriever  = docsearch.as_retriever(search_type="similarity", search_kwargs={"k": 6})
        chat_model = ChatOpenAI(
            model="openai/gpt-3.5-turbo",
            openai_api_key=OPENAI_API_KEY,
            openai_api_base="https://openrouter.ai/api/v1")
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
        qa_chain   = create_stuff_documents_chain(chat_model, prompt)
        _rag_chain   = create_retrieval_chain(retriever, qa_chain)
        _pinecone_ok = True
        logger.info("✅ RAG chain ready.")
    except Exception as e:
        logger.error(f"❌ RAG init failed: {e}")

    try:
        _vision_model = ChatOpenAI(
            model="nvidia/nemotron-nano-12b-v2-vl:free",
            openai_api_key=OPENAI_API_KEY,
            openai_api_base="https://openrouter.ai/api/v1",
            max_tokens=800)
        logger.info("✅ Vision model ready.")
    except Exception as e:
        logger.error(f"❌ Vision model init failed: {e}")

init_models()

# ── Admin config ──────────────────────────────────────────────────────────────
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")



# ── Image Validation with Pillow ──────────────────────────────────────────────
def validate_image_bytes(file_bytes: bytes) -> bool:
    """Return True only if file_bytes is a valid, openable image."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(file_bytes))
        img.verify()   # raises if corrupted / fake image
        return True
    except Exception:
        return False


# ── Security Headers ──────────────────────────────────────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]        = "DENY"
    response.headers["X-XSS-Protection"]       = "1; mode=block"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]     = "geolocation=(), microphone=(), camera=()"
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
    if not ADMIN_EMAIL or current_user.email != ADMIN_EMAIL:
        return render_template("404.html"), 404

    from sqlalchemy import func

    total_users  = User.query.count()
    total_convs  = Conversation.query.count()
    total_msgs   = Message.query.count()
    thumbs_up    = Message.query.filter_by(feedback="up").count()
    thumbs_down  = Message.query.filter_by(feedback="down").count()
    rated_total  = thumbs_up + thumbs_down
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
        .filter(Message.role == "bot",
                Message.response_time_ms.isnot(None))
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
        logger.info(f"New user registered: {email}")
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
        logger.info(f"User logged in: {email}")
        next_page = request.args.get("next")
        return redirect(next_page or url_for("index"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ── Chat Route ────────────────────────────────────────────────────────────────

@app.route("/get", methods=["GET", "POST"])
@limiter.limit("20 per minute")
def chat():
    start_time = time.time()
    msg        = request.form.get("msg", "").strip()
    image_file = request.files.get("image")
    intent     = "n/a"
    answer     = ""

    # ── MIME type validation ─────────────────────────────────────────────────
    if image_file and image_file.filename:
        if image_file.mimetype not in ALLOWED_MIMETYPES:
            return "❌ Unsupported file type. Please upload a JPEG, PNG, GIF, or WebP image.", 400

    logger.info(f"Query: '{msg[:60]}' | has_image={bool(image_file and image_file.filename)}")

    # ── Emergency override (before anything else) ────────────────────────────
    if msg and is_emergency(msg):
        logger.warning(f"🚨 Emergency detected: '{msg[:50]}'")
        answer = EMERGENCY_RESPONSE
        _save_message(msg, answer, "emergency_like", int((time.time()-start_time)*1000))
        return answer

    # ── Image Analysis ───────────────────────────────────────────────────────
    base64_image = None
    if image_file and image_file.filename:
        try:
            file_bytes = image_file.read()
            # Deep validation with Pillow
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
                    {"type": "text",      "text": msg if msg else "Please analyze this skin condition."},
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

        # Cache check (skip cache for very short queries)
        cache_key = f"rag:{hash(msg.lower())}"
        cached    = cache.get(cache_key) if len(msg) > 10 else None

        if cached:
            answer = cached
            intent = "cached"
            logger.info(f"Cache hit for query: '{msg[:40]}'")
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

    # Clean markdown
    if isinstance(answer, str):
        answer = answer.replace("**", "").replace("*", "")

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
        # Use session-scoped conversation ID
        conv_id = session.get("conv_id")
        conv    = None

        if conv_id:
            conv = Conversation.query.get(conv_id)

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


# ── Feedback Route (thumbs up/down) ──────────────────────────────────────────

@app.route("/feedback", methods=["POST"])
def feedback():
    """Save thumbs up / down on a bot message."""
    data       = request.get_json(silent=True) or {}
    msg_id     = data.get("message_id")
    vote       = data.get("vote")   # 'up' or 'down'

    if not msg_id or vote not in ("up", "down"):
        return jsonify({"status": "error", "message": "Invalid payload."}), 400

    msg = Message.query.get(msg_id)
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
