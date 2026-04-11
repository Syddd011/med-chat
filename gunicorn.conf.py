"""
gunicorn.conf.py
================
Production Gunicorn configuration for MediBot.

Usage:
    gunicorn -c gunicorn.conf.py wsgi:app
"""
import multiprocessing
import os

# ── Workers ───────────────────────────────────────────────────────────────────
# Recommended formula: 2 * CPU_CORES + 1
workers     = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"   # use "gevent" if you install gevent for async I/O
threads     = 1         # per worker thread count (sync class → 1)

# ── Binding ───────────────────────────────────────────────────────────────────
bind    = os.environ.get("GUNICORN_BIND", "0.0.0.0:8080")
backlog = 2048

# ── Timeout ───────────────────────────────────────────────────────────────────
# LLM calls can be slow — keep this generous
timeout     = int(os.environ.get("GUNICORN_TIMEOUT", 120))
keepalive   = 5          # seconds to keep idle connections open
graceful_timeout = 30    # time to finish in-flight requests on shutdown

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog  = "-"     # stdout — captured by Docker / systemd
errorlog   = "-"     # stderr
loglevel   = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sμs'

# ── Security ──────────────────────────────────────────────────────────────────
limit_request_line   = 4096   # max URL length
limit_request_fields = 100    # max headers
forwarded_allow_ips  = "*"    # trust X-Forwarded-For from Nginx

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = "medibot"

# ── Hooks ─────────────────────────────────────────────────────────────────────
def on_starting(server):
    server.log.info("🚀 MediBot Gunicorn starting…")

def worker_exit(server, worker):
    server.log.info(f"Worker {worker.pid} exited.")
