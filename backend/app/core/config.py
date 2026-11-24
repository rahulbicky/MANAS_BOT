"""
app/core/config.py
------------------
Central place for all environment-variable-backed settings.
Import these constants instead of calling os.getenv() inside routers.
"""
import os
import logging
import secrets

# ── Environment ─────────────────────────────────────────────────────────────
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()

# ── Auth ────────────────────────────────────────────────────────────────────
SELLER_PASSWORD: str = os.getenv("SELLER_PASSWORD", "")

# ── Employee JWT ─────────────────────────────────────────────────────────────
_raw_jwt_secret = os.getenv("JWT_SECRET", "").strip()
if not _raw_jwt_secret or _raw_jwt_secret == "change-me-in-production":
    if ENVIRONMENT == "production":
        raise ValueError("CRITICAL SECURITY ERROR: JWT_SECRET environment variable must be set in production.")
    logging.getLogger("chatbot").warning(
        "[SECURITY WARNING] JWT_SECRET is not configured or using insecure default. "
        "Generating a transient random key for this session. Set JWT_SECRET in your .env file."
    )
    JWT_SECRET: str = secrets.token_urlsafe(32)
else:
    JWT_SECRET: str = _raw_jwt_secret

JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "8"))

# ── CORS Origins ─────────────────────────────────────────────────────────────
ALLOWED_ORIGINS_RAW: str = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8080,http://127.0.0.1:8080,http://localhost:8000,http://127.0.0.1:8000,https://manasbot.onrender.com,https://manasbot-1.onrender.com,https://manasbot-chatbot-widget.onrender.com"
)
ALLOWED_ORIGINS: list = [origin.strip() for origin in ALLOWED_ORIGINS_RAW.split(",") if origin.strip()]

# ── Alerting thresholds ──────────────────────────────────────────────────────
ALERT_TRAFFIC_RPM: int = int(os.getenv("ALERT_TRAFFIC_RPM", "50"))
ALERT_ERROR_RATE_PCT: float = float(os.getenv("ALERT_ERROR_RATE_PCT", "20"))
ALERT_TOKENS_PER_MIN: int = int(os.getenv("ALERT_TOKENS_PER_MIN", "50000"))

# ── Conversational RAG & Memory Settings ────────────────────────────────────
HISTORY_WINDOW_TURNS: int = int(os.getenv("HISTORY_WINDOW_TURNS", "5"))
CHAT_TOP_K: int = int(os.getenv("CHAT_TOP_K", "5"))
CHAT_SIMILARITY_THRESHOLD: float = float(os.getenv("CHAT_SIMILARITY_THRESHOLD", "0.65"))
