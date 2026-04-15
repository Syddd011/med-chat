"""
gunicorn.conf.py
================
Production Gunicorn configuration for MediBot.

Usage:
    gunicorn -c gunicorn.conf.py wsgi:app

Key change: worker_class = "gevent" (async I/O)
  - Each worker handles ~1000 concurrent greenthreads
  - LLM wait time (~5-15s) no longer blocks the entire worker
  - 4 gevent workers ≈ 4000 concurrent connections capacity
"""
import multiprocessing
import os

# ── Workers ───────────────────────────────────────────────────────────────────
# Formula: 2 * CPU_CORES + 1  (same as before)
workers      = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "gevent"          # ← CRITICAL: async I/O handles LLM latency
threads      = 1                 # gevent is single-threaded per worker
worker_connections = 1000        # max simultaneous greenthreads per worker

# ── Binding ───────────────────────────────────────────────────────────────────
bind    = os.environ.get("GUNICORN_BIND", "0.0.0.0:8080")
backlog = 2048

# ── Timeout ───────────────────────────────────────────────────────────────────
# LLM calls can be slow — generous timeout; gevent won't block other requests
timeout          = int(os.environ.get("GUNICORN_TIMEOUT", 120))
keepalive        = 5
graceful_timeout = 30

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog  = "-"     # stdout — captured by Docker / systemd
errorlog   = "-"     # stderr
loglevel   = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sμs'

# ── Security ──────────────────────────────────────────────────────────────────
limit_request_line   = 4096
limit_request_fields = 100
forwarded_allow_ips  = "*"    # trust X-Forwarded-For from Nginx

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = "medibot"

# ── Hooks ─────────────────────────────────────────────────────────────────────
def on_starting(server):
    server.log.info("🚀 MediBot Gunicorn starting with gevent workers…")

def worker_exit(server, worker):
    server.log.info(f"Worker {worker.pid} exited.")

def post_fork(server, worker):
    """Patch gevent after fork (required for proper greenlet operation)."""
    from gevent import monkey
    monkey.patch_all()
