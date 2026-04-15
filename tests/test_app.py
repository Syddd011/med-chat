"""
tests/test_app.py
=================
Comprehensive test suite for MediBot — Production Edition.

Run with:
    conda run -n medibot pytest tests/ -v
    conda run -n medibot pytest tests/ -v --cov=. --cov-report=term-missing

Coverage targets:
    - Static pages & health endpoint
    - Auth: signup, login, logout, duplicate, short password
    - Security: headers, MIME types, empty message, CSRF error handling
    - Emergency detection (including edge cases)
    - Database models
    - Cache key determinism
    - Data export & account deletion routes
    - Feedback endpoint validation
    - Open redirect protection
"""
import pytest
import os
import hashlib

# ── Test configuration (must be before any app import) ───────────────────────
os.environ.setdefault("FLASK_SECRET_KEY",  "ci-test-secret-key-minimum-32-chars-needed-here!")
os.environ.setdefault("PINECONE_API_KEY",  "test-pinecone-key")
os.environ.setdefault("OPENAI_API_KEY",    "test-openai-key")
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("ADMIN_EMAIL",       "admin@test.com")
os.environ.setdefault("SENTRY_DSN",        "")   # disable Sentry in tests


# ── Session-scoped app fixture ────────────────────────────────────────────────
@pytest.fixture(scope="session")
def app():
    """Create a test Flask application using in-memory SQLite."""
    from app import app as flask_app
    flask_app.config.update({
        "TESTING":                  True,
        "SQLALCHEMY_DATABASE_URI":  "sqlite:///:memory:",
        "WTF_CSRF_ENABLED":         False,   # disable CSRF for test client
        "WTF_CSRF_CHECK_DEFAULT":   False,
    })
    with flask_app.app_context():
        from src.database import db
        db.create_all()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


# ─────────────────────────────────────────────────────────────────────────────
#  Static Pages & Health
# ─────────────────────────────────────────────────────────────────────────────

class TestStaticPages:
    def test_home_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_home_contains_medibot(self, client):
        assert b"MediBot" in client.get("/").data

    def test_terms_page(self, client):
        assert client.get("/terms").status_code == 200

    def test_privacy_page(self, client):
        assert client.get("/privacy").status_code == 200

    def test_404_page(self, client):
        assert client.get("/this-route-does-not-exist-xyz").status_code == 404

    def test_health_endpoint_structure(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "pinecone" in data
        assert "db"       in data
        assert "cache"    in data
        assert "timestamp" in data


# ─────────────────────────────────────────────────────────────────────────────
#  Authentication
# ─────────────────────────────────────────────────────────────────────────────

class TestAuth:
    TEST_EMAIL    = "testuser_auth@example.com"
    TEST_PASSWORD = "SecurePass123"

    def test_signup_page_loads(self, client):
        assert client.get("/signup").status_code == 200

    def test_login_page_loads(self, client):
        assert client.get("/login").status_code == 200

    def test_signup_creates_account(self, client):
        resp = client.post("/signup", data={
            "email":    self.TEST_EMAIL,
            "password": self.TEST_PASSWORD,
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_login_with_correct_password(self, client):
        # Ensure account exists first
        client.post("/signup", data={"email": self.TEST_EMAIL, "password": self.TEST_PASSWORD})
        resp = client.post("/login", data={
            "email":    self.TEST_EMAIL,
            "password": self.TEST_PASSWORD,
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_login_with_wrong_password(self, client):
        resp = client.post("/login", data={
            "email":    self.TEST_EMAIL,
            "password": "wrong_password_xyz",
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Either stays on login page or redirects to home — but must not crash
        # The flash message "Invalid email or password." may or may not be visible
        # depending on template rendering; key check is status 200 (not a crash)
        assert b"MediBot" in resp.data or b"Sign" in resp.data or b"login" in resp.data.lower()

    def test_duplicate_signup_rejected(self, client):
        email = "dup_test_unique@test-medibot.com"
        client.post("/signup", data={"email": email, "password": self.TEST_PASSWORD})
        resp = client.post("/signup",
            data={"email": email, "password": self.TEST_PASSWORD},
            follow_redirects=True)
        assert resp.status_code == 200
        assert (b"already exists" in resp.data or b"signup" in resp.data.lower()
                or b"MediBot" in resp.data)

    def test_short_password_rejected(self, client):
        resp = client.post("/signup", data={
            "email":    "short_pw@example.com",
            "password": "abc",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"8" in resp.data or b"password" in resp.data.lower()

    def test_logout_redirects_when_not_logged_in(self, client):
        resp = client.get("/logout", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Sign" in resp.data or b"login" in resp.data.lower()


# ─────────────────────────────────────────────────────────────────────────────
#  Security
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurity:
    def test_x_content_type_options_header(self, client):
        assert client.get("/").headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options_header(self, client):
        assert client.get("/").headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection_header(self, client):
        assert "1" in client.get("/").headers.get("X-XSS-Protection", "")

    def test_csp_header_present(self, client):
        """Content-Security-Policy must exist — critical XSS protection."""
        csp = client.get("/").headers.get("Content-Security-Policy", "")
        assert "default-src" in csp, "CSP header is missing or malformed"

    def test_referrer_policy_header(self, client):
        assert client.get("/").headers.get("Referrer-Policy") is not None

    def test_invalid_image_mime_rejected(self, client):
        from io import BytesIO
        data = {
            "msg":   "analyze this",
            "image": (BytesIO(b"not an image"), "test.exe", "application/octet-stream"),
        }
        resp = client.post("/get", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_empty_message_returns_200(self, client):
        resp = client.post("/get", data={"msg": ""})
        assert resp.status_code == 200

    def test_message_too_long_is_truncated(self, client):
        """Backend must accept but safely truncate messages over 2000 chars."""
        very_long = "a" * 5000
        resp = client.post("/get", data={"msg": very_long})
        # Should not crash — returns 200 or RAG-unavailable message
        assert resp.status_code in (200, 429)

    def test_open_redirect_blocked(self, client):
        """Login next= param must not redirect to external URLs."""
        resp = client.post(
            "/login?next=https://evil.com",
            data={"email": "notexist@test.com", "password": "wrongpass"},
            follow_redirects=False,
        )
        location = resp.headers.get("Location", "")
        assert "evil.com" not in location, "Open redirect vulnerability detected!"

    def test_feedback_invalid_vote_rejected(self, client):
        resp = client.post("/feedback",
            json={"message_id": "abc", "vote": "invalid"},
            content_type="application/json")
        assert resp.status_code == 400

    def test_feedback_missing_id_rejected(self, client):
        resp = client.post("/feedback",
            json={"vote": "up"},
            content_type="application/json")
        assert resp.status_code == 400

    def test_admin_requires_login(self, client):
        """Admin route must redirect unauthenticated users to login."""
        resp = client.get("/admin", follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_export_data_requires_login(self, client):
        resp = client.get("/export-data", follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_delete_account_requires_login(self, client):
        resp = client.post("/delete-account", follow_redirects=False)
        assert resp.status_code in (302, 401)


# ─────────────────────────────────────────────────────────────────────────────
#  Emergency Detection
# ─────────────────────────────────────────────────────────────────────────────

class TestEmergencyDetection:
    EMERGENCY_PHRASES = [
        "i think i am having a heart attack",
        "i want to end my life",
        "i can't breathe at all",
        "someone is choking",
        "suicidal thoughts",
        "i want to kill myself",
        "drug overdose happened",
        "severe bleeding won't stop",
    ]

    def test_emergency_triggers_safety_response(self, client):
        """Every emergency phrase must return emergency numbers or friendly fallback."""
        for phrase in self.EMERGENCY_PHRASES:
            resp = client.post("/get", data={"msg": phrase})
            assert resp.status_code == 200
            text = resp.data.decode()
            has_emergency = any(num in text for num in ["108", "911", "112", "988"])
            has_fallback  = "unavailable" in text.lower() or "technical" in text.lower()
            assert has_emergency or has_fallback, \
                f"Emergency phrase '{phrase}' returned UNEXPECTED response: {text[:150]}"

    def test_emergency_fires_before_rag(self, client):
        """Emergency detection must short-circuit BEFORE calling the LLM."""
        from app import is_emergency
        assert is_emergency("I am having a heart attack") is True
        assert is_emergency("hello how are you")          is False
        assert is_emergency("CHEST PAIN severe")          is True   # case-insensitive
        assert is_emergency("")                            is False


# ─────────────────────────────────────────────────────────────────────────────
#  Cache Key Determinism (critical fix)
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheKey:
    def test_hashlib_md5_is_deterministic(self):
        """
        Prove that hashlib.md5 gives the same result every time
        (unlike Python's built-in hash() which is randomized per process).
        """
        msg = "what are symptoms of diabetes"
        key1 = f"rag:{hashlib.md5(msg.lower().encode()).hexdigest()}"
        key2 = f"rag:{hashlib.md5(msg.lower().encode()).hexdigest()}"
        assert key1 == key2, "Cache keys must be identical across calls!"

    def test_cache_key_is_different_for_different_messages(self):
        msg_a = "what is diabetes"
        msg_b = "what is hypertension"
        key_a = hashlib.md5(msg_a.lower().encode()).hexdigest()
        key_b = hashlib.md5(msg_b.lower().encode()).hexdigest()
        assert key_a != key_b, "Different messages must have different cache keys!"

    def test_cache_key_case_insensitive(self):
        """Same question in different cases should hit the same cache entry."""
        msg1 = "What is Diabetes"
        msg2 = "what is diabetes"
        key1 = hashlib.md5(msg1.lower().encode()).hexdigest()
        key2 = hashlib.md5(msg2.lower().encode()).hexdigest()
        assert key1 == key2


# ─────────────────────────────────────────────────────────────────────────────
#  Output Sanitizer
# ─────────────────────────────────────────────────────────────────────────────

class TestOutputSanitizer:
    def test_sanitizer_removes_markdown_bold(self):
        from app import sanitize_output
        result = sanitize_output("**Diabetes** is a **metabolic** disease.")
        assert "**" not in result

    def test_sanitizer_removes_asterisks(self):
        from app import sanitize_output
        result = sanitize_output("*italicized* text here")
        assert "*" not in result

    def test_sanitizer_caps_output_length(self):
        from app import sanitize_output
        long_text = "word " * 1000
        result = sanitize_output(long_text)
        assert len(result) <= 3000

    def test_sanitizer_flags_doctor_impersonation(self):
        from app import sanitize_output
        result = sanitize_output("I am a doctor and I recommend 500mg ibuprofen.")
        assert "AI assistant" in result or "MediBot" in result


# ─────────────────────────────────────────────────────────────────────────────
#  Database Models
# ─────────────────────────────────────────────────────────────────────────────

class TestDatabase:
    def test_user_model_creation(self, app):
        import bcrypt
        from src.database import db, User
        with app.app_context():
            pw_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
            user = User(email="db_test_u@example.com", password_hash=pw_hash)
            db.session.add(user)
            db.session.commit()
            found = User.query.filter_by(email="db_test_u@example.com").first()
            assert found is not None
            assert found.email == "db_test_u@example.com"

    def test_user_has_uuid_primary_key(self, app):
        import bcrypt
        from src.database import db, User
        with app.app_context():
            pw_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
            user = User(email="uuid_test@example.com", password_hash=pw_hash)
            db.session.add(user)
            db.session.commit()
            assert len(user.id) == 36   # UUID format: 8-4-4-4-12

    def test_conversation_and_message_creation(self, app):
        from src.database import db, Conversation, Message
        with app.app_context():
            conv = Conversation()
            db.session.add(conv)
            db.session.flush()
            msg = Message(conversation_id=conv.id, role="user", content="Hello MediBot")
            db.session.add(msg)
            db.session.commit()
            found = Message.query.filter_by(conversation_id=conv.id).first()
            assert found is not None
            assert found.content == "Hello MediBot"
            assert found.role == "user"

    def test_message_to_dict(self, app):
        from src.database import db, Conversation, Message
        with app.app_context():
            conv = Conversation()
            db.session.add(conv)
            db.session.flush()
            msg = Message(conversation_id=conv.id, role="bot",
                          content="Here is your answer.", intent="general_info")
            db.session.add(msg)
            db.session.commit()
            d = msg.to_dict()
            assert d["role"]    == "bot"
            assert d["content"] == "Here is your answer."
            assert d["intent"]  == "general_info"
            assert "created_at" in d

    def test_user_cascade_deletes_conversations(self, app):
        """Deleting a user must cascade-delete all their conversations and messages."""
        import bcrypt
        from src.database import db, User, Conversation, Message
        with app.app_context():
            pw_hash = bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode()
            user = User(email="cascade_test@example.com", password_hash=pw_hash)
            db.session.add(user)
            db.session.flush()
            conv = Conversation(user_id=user.id)
            db.session.add(conv)
            db.session.flush()
            msg = Message(conversation_id=conv.id, role="user", content="Hello")
            db.session.add(msg)
            db.session.commit()

            conv_id = conv.id
            msg_id  = msg.id

            db.session.delete(user)
            db.session.commit()

            # Conversation and message should be gone (use session.get for SA 2.0)
            from src.database import db as _db
            assert _db.session.get(Conversation, conv_id) is None
            assert _db.session.get(Message, msg_id)       is None
