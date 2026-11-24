# ManasBot — Production Deployment Guide

This guide describes how to deploy ManasBot to production using Docker Compose, Render, AWS, or Google Cloud Run.

---

## 1. Prerequisites

- Docker Engine 24+ & Docker Compose v2+ (or Python 3.11+ / 3.12+ / 3.13)
- PostgreSQL 16+ instance with `pgvector` extension enabled
- Groq API Key (from https://console.groq.com)
- SMTP Server credentials (e.g. Gmail App Password or SendGrid/SES)

---

## 2. Docker Compose Deployment (Recommended for Self-Hosting)

### Step 1: Clone Repository and Configure Environment
```bash
git clone https://github.com/rahulbicky/MANAS_BOT.git
cd MANAS_BOT

cp .env.example .env
```

### Step 2: Generate Production Secrets
Generate a Fernet encryption key and a JWT secret:
```bash
python -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(32))"
```
Paste the generated keys and your `GROQ_API_KEY` into `.env`.

### Step 3: Launch Containers
```bash
docker compose up -d --build
```
This starts:
1. `manasbot-postgres`: PostgreSQL 16 with `pgvector` extension on port 5432.
2. `manasbot-api`: FastAPI backend on port 8000.

### Step 4: Verify Health
```bash
curl http://localhost:8000/health
# Response: {"status":"healthy", "timestamp":"..."}
```

---

## 3. Cloud Deployment (Render / Cloud Run / ECS)

### Environment Configuration:
Set the following environment variables in your cloud hosting provider:
- `ENVIRONMENT=production`
- `CENTRAL_DB_URL=postgresql://user:pass@your-pg-instance:5432/manasbot?sslmode=require`
- `GROQ_API_KEY=gsk_...`
- `JWT_SECRET=<32+ char secret>`
- `ENCRYPTION_KEY=<32-byte Fernet key>`
- `ALLOWED_ORIGINS=https://your-frontend-domain.com,https://your-client-domain.com`

### Build & Run Commands:
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 4`

---

## 4. Database Migrations & Initial Seeding

Run central database table creation and seed default roles:
```bash
python backend/scripts/seed_local_dev.py
```
This provisions:
- Default plans (`free`, `starter`, `growth`, `enterprise`)
- Super admin user: `superadmin@manasbot.local` (password printed to console)
- Demo sandbox tenant with pre-populated FAQ and business profile
