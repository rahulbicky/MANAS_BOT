"""
backend/app/scheduler.py
-------------------------
Background APScheduler job that runs every 6 hours (4x/day).

Responsibilities:
  1. Re-scrapes all URL-type KnowledgeDocuments for every active tenant
     so the AI always has fresh content from linked web pages.
  2. Logs a timestamped summary of how many tenants/docs were refreshed.

Usage:
  Called from app/main.py on the startup event.
  The scheduler runs in a background thread (BackgroundScheduler), so it
  does NOT block any async FastAPI request handling.
"""
import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _refresh_all_tenants_urls():
    """
    For every active tenant, re-scrape URL-type knowledge documents and re-index
    their vector embeddings so the AI always retrieves current web content.
    """
    try:
        from ..database import get_all_tenants, get_tenant_session, KnowledgeDocument
        from .utils.security_validation import is_safe_public_url, safe_http_get_sync, clean_html_text
        from ..rag import reingest_document

        tenants = get_all_tenants(use_cache=False)
        total_refreshed = 0
        total_failed = 0

        for tenant in tenants:
            if not tenant.get("is_active"):
                continue

            tenant_id = tenant["id"]
            try:
                session = get_tenant_session(tenant_id)
                try:
                    url_docs = session.query(KnowledgeDocument).filter(
                        KnowledgeDocument.tenant_id == tenant_id,
                        KnowledgeDocument.file_type == "url",
                        KnowledgeDocument.is_active == True,
                    ).all()

                    for doc in url_docs:
                        try:
                            if not is_safe_public_url(doc.filename):
                                logger.warning(f"[Scheduler] Skipping unsafe URL for tenant {tenant_id}: {doc.filename}")
                                total_failed += 1
                                continue

                            response = safe_http_get_sync(doc.filename, timeout=15.0)
                            new_content = clean_html_text(response.text)

                            if new_content.strip():
                                doc.content = new_content
                                doc.file_size_bytes = len(new_content.encode("utf-8"))
                                session.commit()
                                reingest_document(
                                    document_id=doc.id,
                                    tenant_id=tenant_id,
                                    filename=doc.filename,
                                    file_type="url",
                                    new_content=new_content,
                                    db=session,
                                )
                                total_refreshed += 1
                        except Exception as e:
                            logger.warning(f"[Scheduler] URL refresh failed for {doc.filename}: {e}")
                            total_failed += 1

                    session.commit()
                finally:
                    session.close()

            except Exception as e:
                logger.warning(f"[Scheduler] Could not process tenant {tenant_id}: {e}")

        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.info(
            f"[Scheduler] Knowledge refresh complete at {now} — "
            f"{total_refreshed} URL doc(s) refreshed, {total_failed} failed, "
            f"across {len(tenants)} tenant(s)."
        )

    except Exception as e:
        logger.error(f"[Scheduler] Fatal error during knowledge refresh: {e}")


def _run_scheduled_retention_audit():
    """Daily scheduled dry-run retention audit across all active tenants."""
    try:
        from .services.retention_service import RetentionService
        reports = RetentionService.generate_cleanup_report()
        logger.info(f"[Scheduler] Retention dry-run audit completed for {len(reports)} tenant(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Retention audit encountered an error: {e}")


def start_scheduler():
    """Start the background scheduler (called on FastAPI startup)."""
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.info("[Scheduler] Scheduler already running — skipping duplicate start.")
        return
    _scheduler = BackgroundScheduler(timezone="UTC")

    # Run every 6 hours → 4 times per day
    _scheduler.add_job(
        _refresh_all_tenants_urls,
        trigger=IntervalTrigger(hours=6),
        id="knowledge_refresh",
        name="AI Knowledge URL Refresh",
        replace_existing=True,
        max_instances=1,  # Prevent overlapping runs
    )

    # Run daily retention dry-run audit
    _scheduler.add_job(
        _run_scheduled_retention_audit,
        trigger=IntervalTrigger(hours=24),
        id="retention_audit",
        name="Tenant Conversation Retention Audit",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    logger.info("[Scheduler] Started — Knowledge refresh (6h) and retention audit (24h) active.")


def stop_scheduler():
    """Stop the background scheduler (called on FastAPI shutdown)."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped.")
