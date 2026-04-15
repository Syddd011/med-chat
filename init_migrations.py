"""
init_migrations.py
==================
One-time script to initialize Flask-Migrate and create the first migration.
Run ONCE from the project root:
    conda run -n medibot python init_migrations.py
"""
from dotenv import load_dotenv
load_dotenv()

from app import app
from src.database import db
from flask_migrate import init, migrate, upgrade
import os

migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")

with app.app_context():
    if not os.path.exists(migrations_dir):
        print("📁 Creating migrations folder...")
        init(directory=migrations_dir)
    else:
        print("📁 Migrations folder already exists — skipping init.")

    print("📝 Creating initial migration...")
    migrate(directory=migrations_dir, message="Initial schema - users, conversations, messages")

    print("⬆️  Applying migration to database...")
    upgrade(directory=migrations_dir)

    print("✅  Flask-Migrate initialized and first migration applied!")
    print("    Run 'flask db migrate -m <message>' for future schema changes.")
    print("    Run 'flask db upgrade' to apply pending migrations.")
