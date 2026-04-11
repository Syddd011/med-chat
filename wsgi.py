"""
wsgi.py — Production entry point for Gunicorn.

Usage (Linux/Mac):
    gunicorn -w 4 -b 0.0.0.0:8080 wsgi:app

Usage (Windows dev — waitress):
    waitress-serve --port=8080 wsgi:app
"""
from app import app

if __name__ == "__main__":
    app.run()
