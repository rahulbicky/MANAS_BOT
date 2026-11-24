# ManasBot — Operational Troubleshooting Guide

This guide covers common runtime errors, diagnostics, and recovery procedures.

---

## 1. Database & Connection Issues

### Issue: `could not translate host name "ep-*.neon.tech" to address: Name or service not known`
- **Cause**: Network sandbox or DNS resolution failure connecting to cloud Neon PostgreSQL.
- **Resolution**:
  - The application includes automatic fallback to `MemorySaver` / SQLite.
  - In production, ensure the container or host has outbound access on port 5432 to your database provider.

### Issue: `SQLite: Unsupported column type Vector`
- **Cause**: Attempting to use pgvector syntax on an SQLite database.
- **Resolution**:
  - ManasBot automatically detects SQLite and stores vector embeddings as JSON-encoded TEXT strings with Python-level cosine distance fallback. No action needed.

---

## 2. Authentication & Authorization Issues

### Issue: `403 Invalid token or unauthorized for this tenant`
- **Cause**: A client requested a tenant resource passing an API key belonging to another tenant, or the API key header was malformed.
- **Resolution**: Verify that the `X-Auth-Token` header matches the exact API key registered for that tenant in `GET /admin/tenants`.

### Issue: `401 Session invalidated. Please log in again.`
- **Cause**: The employee's role or status was modified in the database after their JWT was issued.
- **Resolution**: Re-authenticate via `POST /admin/employee-login` to acquire a newly minted JWT.

---

## 3. RAG Retrieval & AI Ingestion Issues

### Issue: `400 Access to private/internal hostname is forbidden (SSRF protection)`
- **Cause**: User attempted to scrape an internal network target (`localhost`, `127.0.0.1`, `169.254.169.254`, or RFC 1918 private IP) in `POST /admin/add-url`.
- **Resolution**: Ensure the submitted URL is a publicly reachable domain resolving to public IP addresses.

### Issue: `Primary model quota exceeded` or `Groq connection error`
- **Cause**: Outgoing API quota limit reached on primary Groq LLM model (`qwen/qwen3.8-27b`).
- **Resolution**:
  - The LangGraph workflow automatically cascades to secondary model `llama-3.3-70b-versatile` and tertiary fallback models.
  - If all external APIs are unreachable, the bot returns a graceful apologetic fallback message without crashing.

---

## 4. Concurrency & Session Locking

### Issue: `RuntimeError: <asyncio.locks.Lock object ...> is bound to a different event loop`
- **Cause**: In multithreaded test runners or multi-loop ASGI servers, an `asyncio.Lock` instance created on Thread A was accessed on Thread B.
- **Resolution**:
  - `LocalSessionLockRegistry` has been updated with `threading.Lock()` and loop validation. Stale locks from different loops are automatically refreshed.

### Issue: `429 Too Many Requests (Rate limit exceeded: 10 per 1 minute)`
- **Cause**: SlowAPI rate limiter on `/chat` triggered by excessive requests from the same client IP address.
- **Resolution**:
  - In production, configure reverse proxy `X-Forwarded-For` headers so each distinct client visitor has their own rate limit counter.
  - In automated load test harnesses, set `app.state.limiter.enabled = False` to evaluate pure pipeline throughput.

---

## 5. Docker & Container Deployment Diagnostics

### Issue: `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`
- **Cause**: Docker Desktop engine daemon is not started on the host machine.
- **Resolution**:
  - Launch Docker Desktop on Windows and ensure the engine status shows "Engine running" before executing `docker compose up`.
