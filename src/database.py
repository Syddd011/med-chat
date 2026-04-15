"""
src/database.py
===============
SQLAlchemy models for MediBot — production-ready schema.

Tables:
  - User          : registered accounts
  - Conversation  : one chat session per user (or anonymous)
  - Message       : individual messages within a conversation

Indexes added:
  - messages.role + intent  (admin dashboard queries)
  - messages.conversation_id + created_at  (conversation load)
  - conversations.user_id  (user history queries)

Usage with Flask-Migrate:
  flask db init
  flask db migrate -m "description"
  flask db upgrade
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timezone
import uuid

db = SQLAlchemy()


# ── Helpers ───────────────────────────────────────────────────────────────────
def _new_uuid():
    return str(uuid.uuid4())

def _utcnow():
    """Timezone-aware UTC timestamp (avoids deprecation warning in Python 3.12+)."""
    return datetime.now(timezone.utc)


# ── Models ────────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id            = db.Column(db.String(36),  primary_key=True, default=_new_uuid)
    email         = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at    = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    is_active     = db.Column(db.Boolean, default=True, nullable=False)

    conversations = db.relationship(
        "Conversation", backref="user", lazy=True,
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<User {self.email}>"


class Conversation(db.Model):
    __tablename__ = "conversations"

    id             = db.Column(db.String(36),  primary_key=True, default=_new_uuid)
    user_id        = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    started_at     = db.Column(db.DateTime(timezone=True), default=_utcnow, index=True)
    last_active_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    messages = db.relationship(
        "Message", backref="conversation", lazy=True,
        order_by="Message.created_at",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Conversation {self.id[:8]}…>"


class Message(db.Model):
    __tablename__ = "messages"
    __table_args__ = (
        # Composite index for conversation history load (most common query)
        db.Index("ix_messages_conv_created", "conversation_id", "created_at"),
        # Index for admin intent breakdown queries
        db.Index("ix_messages_role_intent",  "role", "intent"),
    )

    id               = db.Column(db.String(36),  primary_key=True, default=_new_uuid)
    conversation_id  = db.Column(
        db.String(36),
        db.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role             = db.Column(db.String(10),  nullable=False)     # 'user' | 'bot'
    content          = db.Column(db.Text,        nullable=False)
    intent           = db.Column(db.String(30),  nullable=True)      # intent label
    has_image        = db.Column(db.Boolean,     default=False)
    response_time_ms = db.Column(db.Integer,     nullable=True)
    feedback         = db.Column(db.String(4),   nullable=True)      # 'up' | 'down'
    created_at       = db.Column(db.DateTime(timezone=True), default=_utcnow, index=True)

    def to_dict(self):
        return {
            "id":               self.id,
            "role":             self.role,
            "content":          self.content,
            "intent":           self.intent,
            "has_image":        self.has_image,
            "response_time_ms": self.response_time_ms,
            "feedback":         self.feedback,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Message {self.role} | {self.content[:40]}…>"
