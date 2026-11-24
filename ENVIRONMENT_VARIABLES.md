# ManasBot — Environment Variables Reference

All environment variables used by the ManasBot platform, categorized by system domain:

## 1. Core & Infrastructure

| Variable | Required | Default | Description |
|---|---|---|---|
| `ENVIRONMENT` | Yes | `development` | Set to `production` or `development`. Enforces strict secret length checks in production. |
| `CENTRAL_DB_URL` | Yes | `sqlite:///./manasbot.db` | Connection string for central database. In production, use `postgresql://user:pass@host:5432/db`. |
| `DATABASE_URL` | No | Fallback to `CENTRAL_DB_URL` | Legacy or per-tenant database connection fallback. |
| `PORT` | No | `8000` | Port on which the FastAPI application binds. |

---

## 2. AI & LLM Services

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | Yes (for live AI) | `""` | API key from Groq Cloud for LLaMA 3.1/3.3 and Qwen models. |
| `DISABLE_GROQ_CALLS` | No | `false` | When `true`, mocks or disables external Groq API calls (used in test suites). |
| `DISABLE_FAST_EMBED` | No | `false` | When `true`, uses lightweight embedding stub for unit test acceleration. |
| `CHAT_TOP_K` | No | `4` | Maximum document chunks retrieved per user question. |
| `CHAT_SIMILARITY_THRESHOLD` | No | `0.65` | Minimum cosine similarity score required for English queries. |
| `MULTILINGUAL_ADAPTED_THRESHOLD` | No | `0.58` | Cosine similarity threshold dynamically applied to Indic/CJK/Non-ASCII queries. |

---

## 3. Security & Authentication

| Variable | Required | Default | Description |
|---|---|---|---|
| `JWT_SECRET` | Yes (in prod) | Transient random | HMAC-SHA256 secret key for signing employee access JWTs (min 32 chars). |
| `JWT_EXPIRE_HOURS` | No | `8` | Token lifetime before expiration (hours). |
| `ENCRYPTION_KEY` | Yes (in prod) | Transient fallback | 32-byte URL-safe base64 Fernet key for encrypting chat logs and tenant API keys. |
| `ALLOWED_ORIGINS` | No | `*` | Comma-separated list of allowed CORS origins. |

---

## 4. Notifications & Alerting

| Variable | Required | Default | Description |
|---|---|---|---|
| `SMTP_HOST` | No | `smtp.gmail.com` | Outgoing SMTP server address. |
| `SMTP_PORT` | No | `587` | SMTP server port (usually 587 for STARTTLS). |
| `SMTP_EMAIL` | No | `""` | Sender email address for lead notifications. |
| `SMTP_PASSWORD` | No | `""` | App-specific password or SMTP token. |
| `ALERT_EMAIL` | No | `""` | Recipient address for operational threshold alert notifications. |
| `ALERT_TRAFFIC_RPM` | No | `50` | Traffic spike alert threshold (requests per minute). |
| `ALERT_ERROR_RATE_PCT`| No | `20` | Error percentage threshold triggering alert. |
| `ALERT_COOLDOWN_MINUTES`| No | `15` | Minimum cooldown between consecutive alert emails. |
