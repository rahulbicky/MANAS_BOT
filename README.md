
<h1 align="center">🤖 MANAS BOT</h1>

<p align="center">
  <strong>Production-Ready Multi-Tenant AI Chatbot Platform</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#api-reference">API Reference</a> •
  <a href="#deployment">Deployment</a> •
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-blue?logo=python&logoColor=white" alt="Python 3.9+" />
  <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/LLM-Groq%20%2F%20LLaMA-orange?logo=meta&logoColor=white" alt="Groq LLaMA" />
  <img src="https://img.shields.io/badge/DB-PostgreSQL-336791?logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white" alt="Docker" />
</p>

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Running the Server](#running-the-server)
- [Frontend Panels](#frontend-panels)
- [API Reference](#api-reference)
- [Authentication](#authentication)
- [Deployment](#deployment)
- [Testing](#testing)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

**MANAS BOT** is a domain-specific, multi-tenant AI chatbot platform built for businesses that need intelligent customer-facing chat support. It combines **LangChain** with **Groq-hosted LLaMA models** to deliver fast, context-aware responses grounded in each tenant's FAQ knowledge base and uploaded documents.

The platform supports multiple independent tenants (businesses), each with their own branding, FAQ data, knowledge documents, business profile, lead capture, and chat history — all powered by a single shared PostgreSQL database with tenant-level data isolation.

---

## Features

### 🧠 AI & Chat
- **LLM-Powered Responses** — Uses Groq's LLaMA 3.1 models via LangChain for high-speed inference
- **Intent Detection** — Automatic classification of user queries (pricing, support, service inquiry, contact, etc.)
- **FAQ-Grounded Answers** — Responses are grounded in tenant-specific FAQ data to reduce hallucination
- **Knowledge Documents** — Upload PDFs, DOCX, XLSX files or link URLs as additional AI context
- **Conversation History** — Full chat history per session with anonymous user tracking
- **Hindi / Hinglish Support** — Intent detection works across English, Hindi, and Hinglish queries

### 🏢 Multi-Tenancy
- **Tenant Isolation** — Each business gets its own data silo within a shared central database
- **Per-Tenant Branding** — Custom business profile (company name, industry, welcome messages)
- **API Key Auth** — Each tenant has a unique API key for chatbot widget authentication
- **Plan-Based Limits** — Configurable message quotas, document limits, and FAQ limits per plan

### 👥 Role-Based Access Control (RBAC)
- **Employee Management** — Super admins can create and manage employee accounts
- **Role Hierarchy** — `super_admin` → `admin` → `support` → `viewer` roles with cascading permissions
- **JWT Authentication** — Secure employee login with token-based sessions
- **Role-Specific Dashboards** — Different UI capabilities based on employee role

### 📊 Monitoring & Alerting
- **Real-Time Metrics** — Track requests/minute, error rates, and estimated token usage
- **Automated Email Alerts** — Configurable thresholds for traffic spikes, error rates, and token burn
- **Cooldown System** — Prevents alert spam with per-type cooldown windows
- **Incident Management** — Track, categorize, and resolve support incidents

### 🔧 Operations
- **Auto URL Scraping** — Background scheduler re-scrapes URL-sourced documents every 6 hours
- **Rate Limiting** — SlowAPI-based request throttling to prevent abuse
- **Structured Logging** — JSON-formatted request/error logs with rotation
- **Email Notifications** — Lead capture alerts and payment reminders via SMTP
- **Docker Support** — Production-ready Dockerfile for Cloud Run / container deployments

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     FRONTEND (Static)                   │
│  ┌──────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │  Admin   │   │   Client     │   │    Chatbot     │  │
│  │  Panel   │   │   Panel      │   │    Widget      │  │
│  └────┬─────┘   └──────┬───────┘   └───────┬────────┘  │
│       │                │                    │           │
│       └────────────────┼────────────────────┘           │
│                        │  HTTP / REST                   │
└────────────────────────┼────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│              BACKEND (FastAPI + Uvicorn)                 │
│                        │                                │
│  ┌─────────────────────▼──────────────────────────────┐ │
│  │              API Router Layer                       │ │
│  │  /auth  /chat  /faq  /leads  /tenants  /metrics    │ │
│  │  /documents  /profile  /billing  /incidents        │ │
│  │  /employees  /health                               │ │
│  └─────────┬──────────────────────────┬───────────────┘ │
│            │                          │                 │
│  ┌─────────▼─────────┐   ┌───────────▼──────────────┐  │
│  │   LLM Layer       │   │   Security Layer          │  │
│  │  - Intent Chain   │   │  - JWT Auth (Employees)   │  │
│  │  - FAQ Chain      │   │  - API Key Auth (Tenants) │  │
│  │  - LangChain/Groq │   │  - Rate Limiter (SlowAPI) │  │
│  └───────────────────┘   └──────────────────────────┘   │
│            │                          │                 │
│  ┌─────────▼──────────────────────────▼──────────────┐  │
│  │            Data Layer (SQLAlchemy ORM)             │  │
│  │  Tenants · FAQs · Leads · ChatHistory · Docs      │  │
│  │  Incidents · Plans · Employees · BusinessProfile   │  │
│  └─────────────────────┬────────────────────────────┘   │
│                        │                                │
│  ┌─────────────────────▼────────────────────────────┐   │
│  │   Background Services                             │  │
│  │  - APScheduler (URL re-scraping every 6h)         │  │
│  │  - Alert Engine (traffic/error/token monitoring)   │  │
│  │  - Email Notifier (leads + payment reminders)      │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         │
                ┌────────▼────────┐
                │   PostgreSQL    │
                │  (Central DB)   │
                └─────────────────┘
```

---

## Tech Stack

| Layer         | Technology                                              |
| ------------- | ------------------------------------------------------- |
| **Backend**   | Python 3.9+, FastAPI, Uvicorn, SQLAlchemy               |
| **AI / LLM**  | LangChain, Groq API (LLaMA 3.1 8B Instant)             |
| **Database**  | PostgreSQL (single central DB with tenant isolation)     |
| **Auth**      | JWT (PyJWT) for employees, API key for tenants, bcrypt   |
| **Frontend**  | Vanilla HTML / CSS / JavaScript (3 static panels)        |
| **Scheduler** | APScheduler (BackgroundScheduler)                        |
| **Rate Limit**| SlowAPI                                                  |
| **Email**     | SMTP (Gmail-compatible)                                  |
| **Scraping**  | httpx + BeautifulSoup4                                   |
| **Docs**      | PyPDF2, python-docx, openpyxl                            |
| **Container** | Docker (Python 3.11-slim)                                |

---

## Project Structure

```
ManasBot/
├── backend/
│   ├── __init__.py
│   ├── main.py                  # Legacy entry point
│   ├── database.py              # SQLAlchemy models, central DB engine, CRUD helpers
│   ├── faq_chain.py             # LangChain FAQ-grounded answer generation
│   ├── intent_chain.py          # LLM-based intent classification
│   ├── encryption.py            # Fernet encryption utilities
│   ├── logger.py                # Structured JSON logging with rotation
│   ├── metrics_store.py         # In-memory metrics (RPM, errors, tokens)
│   ├── alerting.py              # Threshold-based email alert engine
│   ├── email_notifier.py        # Lead capture email notifications
│   ├── notifications.py         # Payment reminder emails
│   └── app/
│       ├── __init__.py
│       ├── main.py              # FastAPI app factory (middleware, routers, startup)
│       ├── scheduler.py         # APScheduler: auto URL re-scraping every 6h
│       ├── api/
│       │   ├── deps.py          # Shared dependencies (DB sessions)
│       │   └── routers/
│       │       ├── auth.py      # Login, registration, password management
│       │       ├── chat.py      # Chat endpoint (LLM query + history)
│       │       ├── faq.py       # CRUD for FAQ entries
│       │       ├── leads.py     # Lead capture and management
│       │       ├── tenants.py   # Tenant CRUD (super_admin only)
│       │       ├── billing.py   # Plan management and billing
│       │       ├── documents.py # Knowledge document upload (PDF/DOCX/URL)
│       │       ├── profile.py   # Business profile management
│       │       ├── metrics.py   # Real-time metrics endpoint
│       │       ├── incidents.py # Incident tracking and resolution
│       │       ├── employees.py # Employee CRUD and role management
│       │       └── health.py    # Health check endpoint
│       ├── core/
│       │   ├── config.py        # Centralized env-var settings
│       │   ├── security.py      # JWT + API key auth, role guards
│       │   └── rate_limiter.py  # SlowAPI rate limiter setup
│       ├── models/              # Pydantic response models
│       ├── schemas/             # Request/response schemas
│       ├── services/            # Business logic services
│       └── utils/
│           └── formatters.py    # Output formatting helpers
│
├── frontend/
│   ├── admin/                   # Super Admin / Admin dashboard
│   │   ├── index.html
│   │   ├── script.js
│   │   ├── style.css
│   │   └── neuaitechnologies_logo.jpg
│   ├── client/                  # Client (tenant) management panel
│   │   ├── index.html
│   │   ├── script.js
│   │   └── style.css
│   └── chatbot/                 # End-user chatbot widget
│       ├── index.html
│       ├── script.js
│       ├── style.css
│       └── chatbot-embed.js     # Embeddable widget script for external sites
│
├── run_server.py                # Single-command launcher (backend + frontend)
├── setup_first_admin.py         # Interactive first super_admin account creation
├── setup.py                     # Package setup (pip install -e .)
├── clean_dbs.py                 # Cleanup script for test databases
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Production container image
├── .env.example                 # Environment variable template
├── .gitignore
├── test_employees.py            # Employee management tests
├── test_endpoints.py            # API endpoint tests
└── test_limits.py               # Rate limit / plan limit tests
```

---

## Quick Start

### Prerequisites

- **Python 3.9+** (3.11 recommended)
- **PostgreSQL** (local or cloud-hosted, e.g. Supabase, Neon, Railway)
- **Groq API Key** — [Get one free at groq.com](https://console.groq.com)
- **(Optional)** Docker for containerized deployment

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/rahulbicky/MANAS_BOT.git
cd MANAS_BOT

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
# ── Required ──────────────────────────────────────────────
GROQ_API_KEY=your_groq_api_key_here
CENTRAL_DB_URL=postgresql://user:password@host:5432/manasbot
ENCRYPTION_KEY=your_base64_encryption_key_here
SELLER_PASSWORD=your_secure_developer_password

# ── Email (SMTP) ──────────────────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your_email@gmail.com
SMTP_PASSWORD=your_app_password

# ── Alert Thresholds (Optional) ───────────────────────────
ALERT_EMAIL=your_alert_recipient@gmail.com
ALERT_TRAFFIC_RPM=50
ALERT_ERROR_RATE_PCT=20
ALERT_TOKENS_PER_MIN=50000
ALERT_COOLDOWN_MINUTES=15

# ── JWT (Optional, has sensible defaults) ─────────────────
JWT_SECRET=change-me-in-production
JWT_EXPIRE_HOURS=8
```

> **Tip:** To generate an encryption key, run:
> ```python
> from cryptography.fernet import Fernet
> print(Fernet.generate_key().decode())
> ```

### Running the Server

```bash
# Start both backend (port 8000) and frontend (port 8080) with one command
python run_server.py
```

On first run, create your super admin account:

```bash
python setup_first_admin.py
```

The server will print:

```
[Frontend] Serving on http://127.0.0.1:8080
  Admin Panel  : http://127.0.0.1:8080/admin/
  Client Panel : http://127.0.0.1:8080/client/
  Chatbot      : http://127.0.0.1:8080/chatbot/

[Backend] Starting FastAPI backend on http://127.0.0.1:8000 ...
```

---

## Frontend Panels

### 🛡️ Admin Panel (`/admin/`)

The super admin dashboard for platform-wide management:

- **Tenant Management** — Create, edit, activate/deactivate tenant businesses
- **Employee Management** — Add employees, assign roles (`super_admin`, `admin`, `support`, `viewer`)
- **Plan & Billing** — Configure subscription plans with message/document/FAQ limits
- **Incident Overview** — Monitor and respond to support incidents across all tenants
- **Metrics Dashboard** — Real-time RPM, error rates, and token usage

### 🏪 Client Panel (`/client/`)

Self-service dashboard for individual tenant (business) owners:

- **Business Profile** — Set company name, industry, welcome messages
- **FAQ Management** — Add, edit, and categorize FAQ entries by intent
- **Knowledge Base** — Upload documents (PDF, DOCX, XLSX) or link URLs for AI context
- **Lead Management** — View and export captured sales leads
- **Chat History** — Review all chatbot conversations and user interactions
- **Incident Reporting** — Create and track support incidents

### 💬 Chatbot Widget (`/chatbot/`)

The end-user facing AI chatbot:

- **Embeddable Widget** — Drop-in `<script>` tag for any website via `chatbot-embed.js`
- **Context-Aware** — Answers grounded in tenant's FAQs and uploaded knowledge documents
- **Lead Capture** — Collects visitor contact information during conversations
- **Session Tracking** — Anonymous session-based conversation history
- **Multi-Language** — Supports English, Hindi, and Hinglish queries

#### Embedding the Chatbot

Add the following snippet to any website to embed the chatbot widget:

```html
<script
  src="https://your-domain.com/chatbot/chatbot-embed.js"
  data-tenant-id="YOUR_TENANT_ID"
  data-api-url="https://your-backend-domain.com"
></script>
```

---

## API Reference

The backend exposes a RESTful API at `http://localhost:8000`. Interactive docs are available at:

- **Swagger UI** — [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc** — [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Key Endpoints

| Method   | Endpoint                          | Auth          | Description                                |
| -------- | --------------------------------- | ------------- | ------------------------------------------ |
| `GET`    | `/health`                         | —             | Health check                               |
| `POST`   | `/auth/login`                     | —             | Employee login (returns JWT)               |
| `POST`   | `/auth/register`                  | API Key       | Tenant registration                        |
| `POST`   | `/chat/`                          | API Key       | Send a message to the chatbot              |
| `GET`    | `/chat/history`                   | API Key       | Retrieve chat history                      |
| `GET`    | `/faq/`                           | API Key       | List tenant FAQs                           |
| `POST`   | `/faq/`                           | API Key       | Create a new FAQ entry                     |
| `GET`    | `/leads/`                         | API Key       | List captured leads                        |
| `POST`   | `/documents/upload`               | API Key       | Upload a knowledge document                |
| `GET`    | `/tenants/`                       | JWT (Admin)   | List all tenants                           |
| `POST`   | `/tenants/`                       | JWT (Admin)   | Create a new tenant                        |
| `GET`    | `/metrics/`                       | JWT (Admin)   | Real-time platform metrics                 |
| `GET`    | `/employees/`                     | JWT (Admin)   | List employees                             |
| `POST`   | `/employees/`                     | JWT (Admin)   | Create employee account                    |
| `GET`    | `/incidents/`                     | API Key / JWT | List incidents                             |
| `POST`   | `/incidents/`                     | API Key       | Report a new incident                      |
| `GET`    | `/profile/`                       | API Key       | Get business profile                       |
| `PUT`    | `/profile/`                       | API Key       | Update business profile                    |

---

## Authentication

The platform uses **two parallel auth systems**:

### 1. API Key Authentication (Tenant/Client Routes)

Used by the client panel and chatbot widget. Pass the tenant's API key via header:

```
X-Auth-Token: <tenant_api_key>
```

### 2. JWT Authentication (Employee/Admin Routes)

Used by the admin panel for employee-facing routes. Login to obtain a token:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "your_password"}'
```

Then pass the token in subsequent requests:

```
Authorization: Bearer <jwt_token>
```

### Role Hierarchy

| Role           | Permissions                                               |
| -------------- | --------------------------------------------------------- |
| `super_admin`  | Full platform access — tenant CRUD, employee management   |
| `admin`        | Tenant data management, incident handling                 |
| `support`      | View data, respond to incidents                           |
| `viewer`       | Read-only access to dashboards and reports                |

---

## Deployment

### Docker

```bash
# Build the image
docker build -t manasbot .

# Run the container
docker run -p 8000:8000 \
  -e GROQ_API_KEY=your_key \
  -e CENTRAL_DB_URL=your_postgres_url \
  -e ENCRYPTION_KEY=your_key \
  -e SELLER_PASSWORD=your_password \
  manasbot
```

### Google Cloud Run

```bash
# Build and push to Artifact Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT/manasbot

# Deploy
gcloud run deploy manasbot \
  --image gcr.io/YOUR_PROJECT/manasbot \
  --port 8000 \
  --allow-unauthenticated \
  --set-env-vars "GROQ_API_KEY=...,CENTRAL_DB_URL=...,ENCRYPTION_KEY=...,SELLER_PASSWORD=..."
```

> **Note:** The Docker image only includes the backend. For production, serve the `frontend/` directory via a CDN, Nginx, or a static hosting service like Firebase Hosting or Vercel.

---

## Testing

```bash
# Run employee management tests
python -m pytest test_employees.py -v

# Run API endpoint tests
python -m pytest test_endpoints.py -v

# Run rate limit / plan limit tests
python -m pytest test_limits.py -v

# Run all tests
python -m pytest -v
```

---

## Utility Scripts

| Script                 | Description                                                   |
| ---------------------- | ------------------------------------------------------------- |
| `run_server.py`        | Starts both backend (8000) and frontend (8080) servers        |
| `setup_first_admin.py` | Interactive CLI to create the first super admin account        |
| `clean_dbs.py`         | Removes test tenants and leftover test database files          |
| `setup.py`             | Package installation (`pip install -e .`)                      |

---

## Contributing

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/my-feature`
3. **Commit** your changes: `git commit -m 'feat: add my feature'`
4. **Push** to the branch: `git push origin feature/my-feature`
5. **Open** a Pull Request

Please follow the existing code style and include tests for new features.


