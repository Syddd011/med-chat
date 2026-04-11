# MediBot — Deployment Guide

## Overview

This guide covers deploying MediBot to three platforms:
1. **Railway** (recommended — easiest, ~$5/month)
2. **Render** (free tier available)
3. **VPS with Docker** (full control, any provider: DigitalOcean, Vultr, Hetzner)

---

## Prerequisites

Before deploying, ensure you have:
- [ ] `PINECONE_API_KEY` from [app.pinecone.io](https://app.pinecone.io)
- [ ] `OPENAI_API_KEY` (OpenRouter key) from [openrouter.ai](https://openrouter.ai)
- [ ] Pinecone index rebuilt: `python store_index.py`
- [ ] Intent classifier trained: `python src/ml/train_intent_classifier.py`
- [ ] A strong `FLASK_SECRET_KEY` generated: `python -c "import secrets; print(secrets.token_hex(32))"`

---

## Option 1: Railway (Recommended)

Railway is the easiest and most affordable way to deploy.

### Step 1: Push your code to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/your-username/med-chat.git
git push -u origin main
```

### Step 2: Create a Railway project
1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Select your `med-chat` repository
4. Railway will auto-detect the Dockerfile and build it

### Step 3: Set environment variables
In Railway dashboard → your service → **Variables**, add:
```
FLASK_SECRET_KEY     = (your secret key)
PINECONE_API_KEY     = (your Pinecone key)
OPENAI_API_KEY       = (your OpenRouter key)
FLASK_DEBUG          = false
ADMIN_EMAIL          = your@email.com
```

### Step 4: Add a custom domain (optional)
Railway dashboard → your service → **Settings → Custom Domain**

Done! Your chatbot is live. Railway will redeploy automatically on every `git push`.

---

## Option 2: Render (Free Tier)

### Step 1: Create a Web Service
1. Go to [render.com](https://render.com) → **New → Web Service**
2. Connect your GitHub repository
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn -c gunicorn.conf.py wsgi:app`

### Step 2: Set environment variables
Same variables as Railway above.

### Step 3: Add a PostgreSQL database (optional upgrade)
Render → **New → PostgreSQL** → copy the `DATABASE_URL` to your web service variables.

> ⚠️ Free tier on Render spins down after 15 minutes of inactivity. First request after idle will take 30–60 seconds to respond.

---

## Option 3: VPS with Docker (Full Control)

### Step 1: Provision a server
Recommended: DigitalOcean Droplet or Hetzner CX11 (~$5/month, Ubuntu 22.04)

### Step 2: Install Docker
```bash
# SSH into your server
ssh root@your_server_ip

# Install Docker
curl -fsSL https://get.docker.com | sh
apt-get install -y docker-compose-plugin
```

### Step 3: Clone and configure
```bash
git clone https://github.com/your-username/med-chat.git
cd med-chat
cp .env.example .env
nano .env   # Fill in your API keys
```

### Step 4: Set up SSL with Let's Encrypt
```bash
# Install Certbot
apt-get install -y certbot
certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com

# Certificates are saved to /etc/letsencrypt/live/yourdomain.com/
# Update nginx.conf ssl paths:
#   ssl_certificate  /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
#   ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
```

### Step 5: Update nginx.conf
Edit `nginx.conf` and replace `yourdomain.com` with your actual domain.
Create the ssl directory and copy/symlink your certs:
```bash
mkdir -p ssl
ln -s /etc/letsencrypt/live/yourdomain.com/fullchain.pem ssl/fullchain.pem
ln -s /etc/letsencrypt/live/yourdomain.com/privkey.pem ssl/privkey.pem
```

### Step 6: Launch the full stack
```bash
# Pull and build images
docker compose -f docker-compose.yml build

# Start everything (web + nginx + postgres + redis)
docker compose up -d

# Check all services are running
docker compose ps

# View logs
docker compose logs -f web
```

### Step 7: Auto-renewal for SSL
```bash
# Add to crontab (renew cert every 60 days)
crontab -e
# Add this line:
0 0 1 * * certbot renew --quiet && docker compose exec nginx nginx -s reload
```

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `FLASK_SECRET_KEY` | ✅ Yes | Long random string for session signing |
| `PINECONE_API_KEY` | ✅ Yes | Pinecone vector database API key |
| `OPENAI_API_KEY` | ✅ Yes | OpenRouter API key (used for LLM + Vision) |
| `FLASK_DEBUG` | No | Set to `false` in production |
| `DATABASE_URL` | No | PostgreSQL URL (default: SQLite) |
| `REDIS_URL` | No | Redis URL for caching (default: memory) |
| `ADMIN_EMAIL` | No | Email of admin user who can access `/admin` |
| `GUNICORN_WORKERS` | No | Number of workers (default: 2 × CPUs + 1) |
| `GUNICORN_TIMEOUT` | No | Request timeout in seconds (default: 120) |
| `POSTGRES_PASSWORD` | Docker only | PostgreSQL password for docker-compose |

---

## Health Check

After deployment, verify everything is working:
```bash
curl https://yourdomain.com/health
```

Expected response:
```json
{
  "status": "ok",
  "pinecone": "connected",
  "vision_model": "loaded",
  "cache": "SimpleCache",
  "db": "sqlite",
  "timestamp": "2026-04-09T10:00:00Z"
}
```

---

## Adding More Medical PDFs (Future Expansion)

1. Drop valid PDF files into the `data/` folder
2. Run `python store_index.py` (this deletes and rebuilds the Pinecone index)
3. Redeploy the app

> The script now loads PDFs individually — one corrupted file won't break the whole indexing.

---

## CI/CD with GitHub Actions

The `.github/workflows/ci.yml` pipeline:
1. **Runs on every push** to `main` or `develop`
2. **Tests**: `pytest tests/ -v`
3. **Lints**: `flake8` (syntax errors fail the build; style warnings are informational)
4. **Docker build + push**: On merges to `main` — builds and pushes to Docker Hub

### Required GitHub Secrets
Go to GitHub → your repo → **Settings → Secrets and variables → Actions** and add:
- `PINECONE_API_KEY`
- `OPENAI_API_KEY`
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- `RAILWAY_TOKEN` (optional — for auto-deploy)

---

## Monitoring

### Check logs
```bash
# Local
tail -f flask.log

# Docker
docker compose logs -f web

# Railway / Render
Check the Logs tab in the platform dashboard
```

### Admin dashboard
Go to `/admin` while logged in as the `ADMIN_EMAIL` account to see:
- Total users, conversations, messages
- Average response time
- Satisfaction rate (thumbs up/down)
- Intent distribution
- Recent conversation log

### Uptime monitoring (free)
- [UptimeRobot](https://uptimerobot.com) — monitor `/health` endpoint
- Set alerts for downtime via email/Slack

---

*Questions? Open an issue on GitHub.*
