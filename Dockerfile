# ── Production Dockerfile ─────────────────────────────────────────────────────
# Multi-stage build: keeps image small and secure.
#
# Build:  docker build -t medibot .
# Run:    docker run -p 8080:8080 --env-file .env medibot
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.10-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create non-root user for security
RUN addgroup --system medibot && adduser --system --ingroup medibot medibot
RUN chown -R medibot:medibot /app
USER medibot

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Start Gunicorn (4 workers; adjust based on CPU cores: 2 * cores + 1)
CMD ["gunicorn", \
     "--workers", "4", \
     "--worker-class", "sync", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "wsgi:app"]