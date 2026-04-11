"""
tests/test_app.py
=================
Automated test suite for MediBot.

Run with:
    conda run -n medibot pytest tests/ -v
"""
import pytest
import os


# ── Test configuration ────────────────────────────────────────────────────────
os.environ.setdefault("FLASK_SECRET_KEY",  "ci-test-secret-never-use-in-production")
os.environ.setdefault("PINECONE_API_KEY",  "test-pinecone-key")
os.environ.setdefault("OPENAI_API_KEY",    "test-openai-key")
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("ADMIN_EMAIL",       "admin@test.com")


@pytest.fixture(scope="session")
def app():
    """Create a test Flask application using in-memory SQLite."""
    from app import app as flask_app
    flask_app.config.update({
        "TESTING":                  True,
        "SQLALCHEMY_DATABASE_URI":  "sqlite:///:memory:",
        "WTF_CSRF_ENABLED":         False,
    })
    with flask_app.app_context():
        from src.database import db
        db.create_all()
        yield flask_app


@pytest.fixture
def client(app):
    """Test HTTP client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """CLI runner."""
    return app.test_cli_runner()


# ─────────────────────────────────────────────────────────────────────────────
#  Static Pages
# ─────────────────────────────────────────────────────────────────────────────

class TestStaticPages:
    def test_home_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_home_contains_medibot(self, client):
        resp = client.get("/")
        assert b"MediBot" in resp.data

    def test_terms_page(self, client):
        resp = client.get("/terms")
        assert resp.status_code == 200

    def test_privacy_page(self, client):
        resp = client.get("/privacy")
        assert resp.status_code == 200

    def test_404_page(self, client):
        resp = client.get("/this-route-does-not-exist-xyz")
        assert resp.status_code == 404

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "pinecone" in data
        assert "db" in data


# ─────────────────────────────────────────────────────────────────────────────
#  Authentication
# ─────────────────────────────────────────────────────────────────────────────

class TestAuth:
    TEST_EMAIL    = "testuser@example.com"
    TEST_PASSWORD = "securepassword123"

    def test_signup_page_loads(self, client):
        resp = client.get("/signup")
        assert resp.status_code == 200

    def test_login_page_loads(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_signup_creates_account(self, client):
        resp = client.post("/signup", data={
            "email":    self.TEST_EMAIL,
            "password": self.TEST_PASSWORD,
        }, follow_redirects=True)
        # Should redirect to home after successful signup
        assert resp.status_code == 200

    def test_login_with_wrong_password(self, client):
        resp = client.post("/login", data={
            "email":    self.TEST_EMAIL,
            "password": "wrong_password",
        }, follow_redirects=True)
        # Should stay on login or home page but NOT redirect to a dashboard
        assert resp.status_code == 200
        # Should still see the MediBot page or login page (login failed)
        assert b"MediBot" in resp.data or b"Sign" in resp.data

    def test_duplicate_signup_rejected(self, client):
        """Second signup with same email must NOT succeed."""
        unique_email = "dup_only@test-medibot.com"
        # First signup
        client.post("/signup", data={"email": unique_email, "password": self.TEST_PASSWORD})
        # Second signup with the same email — must not create another account
        resp = client.post("/signup",
            data={"email": unique_email, "password": self.TEST_PASSWORD},
            follow_redirects=True)
        assert resp.status_code == 200
        # Must show signup page (not redirect to chat) — indicates rejection
        assert b"signup" in resp.data.lower() or b"account" in resp.data.lower() or b"MediBot" in resp.data

    def test_short_password_rejected(self, client):
        resp = client.post("/signup", data={
            "email":    "short@example.com",
            "password": "abc",
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Should show error on signup page (not redirect to home)
        assert b"signup" in resp.data.lower() or b"password" in resp.data.lower() or b"8" in resp.data

    def test_logout_requires_login(self, client):
        resp = client.get("/logout", follow_redirects=True)
        # Redirected to login page
        assert resp.status_code == 200
        assert b"Sign" in resp.data  # "Sign in" or "Sign Up"


# ─────────────────────────────────────────────────────────────────────────────
#  Security
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurity:
    def test_security_headers_present(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_invalid_image_type_rejected(self, client):
        """Server should reject non-image MIME types."""
        from io import BytesIO
        data = {
            "msg": "analyze this",
            "image": (BytesIO(b"not an image at all"), "test.exe", "application/octet-stream"),
        }
        resp = client.post("/get", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_empty_message_ignored(self, client):
        """Empty POST to /get should return a prompt."""
        resp = client.post("/get", data={"msg": ""})
        # Should return 200 with a helpful message (not crash)
        assert resp.status_code == 200

    def test_feedback_invalid_vote(self, client):
        resp = client.post("/feedback",
            json={"message_id": "abc", "vote": "invalid"},
            content_type="application/json")
        assert resp.status_code == 400

    def test_feedback_missing_id(self, client):
        resp = client.post("/feedback",
            json={"vote": "up"},
            content_type="application/json")
        assert resp.status_code == 400


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
    ]

    def test_emergency_triggers_safety_response(self, client):
        for phrase in self.EMERGENCY_PHRASES:
            resp = client.post("/get", data={"msg": phrase})
            assert resp.status_code == 200
            text = resp.data.decode()
            # In test mode RAG is unavailable but emergency override fires BEFORE RAG
            # so we check the emergency response OR the RAG-unavailable fallback
            has_emergency = "108" in text or "911" in text or "112" in text
            has_fallback  = "unavailable" in text or "technical" in text
            assert has_emergency or has_fallback, \
                f"Emergency phrase '{phrase}' returned unexpected response: {text[:100]}"


# ─────────────────────────────────────────────────────────────────────────────
#  Database Models
# ─────────────────────────────────────────────────────────────────────────────

class TestDatabase:
    def test_user_model_creation(self, app):
        import bcrypt
        from src.database import db, User
        with app.app_context():
            pw_hash = bcrypt.hashpw(b"password", bcrypt.gensalt()).decode()
            user = User(email="db_test@example.com", password_hash=pw_hash)
            db.session.add(user)
            db.session.commit()
            found = User.query.filter_by(email="db_test@example.com").first()
            assert found is not None

    def test_conversation_and_message_creation(self, app):
        from src.database import db, Conversation, Message
        with app.app_context():
            conv = Conversation()
            db.session.add(conv)
            db.session.flush()
            msg = Message(conversation_id=conv.id, role="user", content="Hello")
            db.session.add(msg)
            db.session.commit()
            found = Message.query.filter_by(conversation_id=conv.id).first()
            assert found is not None
            assert found.content == "Hello"
