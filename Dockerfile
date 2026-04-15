# ── Production Dockerfile ─────────────────────────────────────────────────────
# Multi-stage build: small final image, no build tools in production layer.
#
# Build:  docker build -t medibot:latest .
# Run:    docker run -p 8080:8080 --env-file .env medibot:latest
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Builder (installs deps, can be discarded) ───────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build tools needed only for compiling Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Production image (lean and clean) ────────────────────────────────
FROM python:3.11-slim AS production

# Minimal runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Create a non-root user for security (never run as root)
RUN addgroup --system medibot \
    && adduser --system --ingroup medibot --no-create-home medibot \
    && chown -R medibot:medibot /app \
    && mkdir -p /app/logs && chown medibot:medibot /app/logs

USER medibot

# Expose application port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Start Gunicorn with gevent workers
# Workers: 2 * CPU_CORES + 1 (override with GUNICORN_WORKERS env var)
CMD ["gunicorn", \
     "--config", "gunicorn.conf.py", \
     "wsgi:app"]