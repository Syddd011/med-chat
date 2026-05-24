# MediBot 🩺  AI Medical Information Assistant

[![Python](https://img.shields.io/badge/Python-3.10-3776ab?style=flat&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-black?style=flat&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![LangChain](https://img.shields.io/badge/LangChain-RAG-1db87a?style=flat)](https://langchain.com)
[![Pinecone](https://img.shields.io/badge/Pinecone-Vector%20DB-5849be?style=flat)](https://pinecone.io)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

> **⚕️ MediBot is an AI-powered medical information assistant**, not a licensed medical professional. Always consult a certified doctor for medical decisions.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **RAG Chatbot** | LangChain + Pinecone vector search over 13 curated medical knowledge files |
| 🔍 **Intent Classifier** | 12-category ML model (symptoms, medications, mental health, first aid, etc.) |
| 🖼️ **Skin Image Analysis** | Vision model integration for skin condition identification |
| 🚨 **Emergency Detection** | Hardcoded keyword override that fires before any ML model — includes emergency hotlines |
| 🔐 **User Auth** | Email/password registration with bcrypt hashing and Flask-Login |
| ⚡ **Response Caching** | Flask-Caching (memory → Redis) — repeated queries answered instantly |
| 📊 **Admin Dashboard** | Live stats: users, conversations, satisfaction rate, intent distribution |
| 🛡️ **Security** | Rate limiting, Pillow image validation, security headers, no debug mode in production |
| 🏥 **Legal Compliance** | Terms of Service, Privacy Policy (GDPR / India DPDP Act), mandatory disclaimer modal |
| 🐳 **Docker Ready** | Multi-stage Dockerfile + docker-compose with Nginx, PostgreSQL, Redis |

---

## 🏗️ Tech Stack

```
Frontend   : HTML5 · Vanilla CSS · Vanilla JavaScript
Backend    : Flask 3 · Gunicorn · Python 3.10
AI / LLM   : LangChain · OpenRouter API (GPT-3.5-turbo + Vision model)
Vector DB  : Pinecone (sentence-transformers/all-MiniLM-L6-v2)
ML Model   : TF-IDF + LinearSVC (12-class intent classifier)
Database   : SQLite (dev) → PostgreSQL (production)
Cache      : Flask-Caching → Redis (production)
Deployment : Docker · Nginx · GitHub Actions CI/CD
```

---

## 🚀 Quick Start (Local Development)

### 1. Clone and set up environment
```bash
git clone https://github.com/your-username/med-chat.git
cd med-chat
conda create -n medibot python=3.10
conda activate medibot
pip install -r requirements.txt
```

### 2. Configure environment variables
```bash
cp .env.example .env
# Edit .env and fill in your API keys:
# - PINECONE_API_KEY
# - OPENAI_API_KEY  (OpenRouter key)
# - FLASK_SECRET_KEY
```

### 3. Build the knowledge base (first run only)
```bash
python store_index.py
```
This loads all PDFs and TXT files from `data/` and stores embeddings in Pinecone. Takes ~10–15 minutes.

### 4. Train the intent classifier (first run only)
```bash
python src/ml/train_intent_classifier.py
```

### 5. Run the app
```bash
python app.py
```
Open `http://localhost:8080`

---

## 📁 Project Structure

```
med-chat/
├── app.py                    # Main Flask application
├── wsgi.py                   # Gunicorn entry point
├── gunicorn.conf.py          # Gunicorn production config
├── store_index.py            # Rebuild Pinecone index
├── download_medical_pdfs.py  # Download free medical PDFs
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
│
├── src/
│   ├── helper.py             # PDF/TXT loader, text splitter, embeddings
│   ├── prompt.py             # System prompts for all 12 intent categories
│   ├── database.py           # SQLAlchemy models (User, Conversation, Message)
│   └── ml/
│       ├── intent_classifier.py      # Runtime intent prediction
│       ├── train_intent_classifier.py # Training script
│       └── config.py
│
├── data/
│   ├── Medical_book.pdf      # Primary medical textbook
│   ├── intent_dataset.csv    # 793 training rows × 12 categories
│   ├── diabetes_reference.txt
│   ├── hypertension_reference.txt
│   ├── mental_health_reference.txt
│   ├── first_aid_reference.txt
│   ├── medications_reference.txt
│   ├── nutrition_reference.txt
│   ├── womens_health_reference.txt
│   ├── pediatric_health_reference.txt
│   ├── common_diseases_reference.txt
│   ├── skin_conditions_reference.txt
│   ├── symptoms_guide_reference.txt
│   └── lifestyle_wellness_reference.txt
│
├── models/
│   ├── intent_classifier.joblib
│   └── intent_vectorizer.joblib
│
├── static/
│   └── style.css
│
├── templates/
│   ├── chat.html             # Main chatbot UI
│   ├── login.html            # Auth — login
│   ├── signup.html           # Auth — registration
│   ├── admin.html            # Admin dashboard
│   ├── terms.html            # Terms of Service
│   ├── privacy.html          # Privacy Policy
│   ├── 404.html
│   └── 500.html
│
└── tests/
    └── test_app.py           # 25 automated pytest tests
```

---

## 🔑 Key URLs

| URL | Description |
|---|---|
| `/` | Main chat interface |
| `/admin` | Admin stats dashboard (ADMIN_EMAIL only) |
| `/health` | JSON health check endpoint |
| `/login` | User login |
| `/signup` | New account registration |
| `/terms` | Terms of Service |
| `/privacy` | Privacy Policy |

---

## 🧠 Knowledge Base (13 Medical Topics)

The chatbot answers questions using a curated knowledge base of **13 medical reference files**:

Diabetes · Hypertension · Mental Health · First Aid · Medications · Nutrition · Women's Health · Pediatric Health · Common Diseases (Asthma, TB, Thyroid, Kidney, Heart) · Skin Conditions · Symptoms Guide · Lifestyle & Wellness · Medical Book (16MB PDF)

**To add more medical PDFs:** Drop them into `data/` and re-run `python store_index.py`.

---

## 🏥 Medical Disclaimer

MediBot is intended for **general health information only** and is **not a substitute for professional medical advice, diagnosis, or treatment**.

- Always consult a qualified, licensed physician for medical concerns
- Do not use this tool in a medical emergency — call **108** (India), **911** (USA), or **112** (Global)
- Information provided may contain errors — verify with healthcare professionals

---

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Run tests: `pytest tests/ -v`
4. Submit a pull request

---

*Built with ❤️ to make health information accessible to everyone.*
