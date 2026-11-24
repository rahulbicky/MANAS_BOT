"""
backend/app/services/retention_service.py
-----------------------------------------
Production-grade tenant-specific conversation retention and cleanup service.

Key Features:
  - Configurable retention periods per tenant (e.g., 7, 30, 90, custom days, or indefinite/0).
  - Dry-run capability: generates audit reports without deleting any data.
  - Strict tenant isolation: prevents cross-tenant data leakage or inadvertent deletions.
  - Safe defaults: dry_run=True by default; destructive execution requires explicit opt-in.
  - LangGraph checkpoint cleanup: purges expired checkpoint state for the specific tenant.
"""
import logging
import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import text

from ...database import (
    _get_central_session,
    _get_central_engine,
    _invalidate_tenant_cache,
    CentralTenant,
    ChatLog,
    ChatFeedback,
    utc_now,
    ensure_utc,
)

logger = logging.getLogger(__name__)


class RetentionService:
    """Service managing tenant-specific data retention policies and audit/cleanup lifecycles."""

    @staticmethod
    def get_tenant_policy(tenant_id: str) -> Dict[str, Any]:
        """Retrieve the configured retention policy for a specific tenant."""
        session = _get_central_session()
        try:
            tenant = session.query(CentralTenant).filter(CentralTenant.id == tenant_id).first()
            if not tenant:
                raise ValueError(f"Tenant '{tenant_id}' not found.")
            days = tenant.conversation_retention_days or 0
            return {
                "tenant_id": tenant_id,
                "retention_days": days,
                "is_indefinite": (days <= 0),
            }
        finally:
            session.close()

    @staticmethod
    def set_tenant_policy(tenant_id: str, retention_days: int) -> Dict[str, Any]:
        """Configure retention policy days for a tenant (0 or None means indefinite retention)."""
        if retention_days < 0:
            raise ValueError("retention_days must be non-negative (use 0 for indefinite retention).")

        session = _get_central_session()
        try:
            tenant = session.query(CentralTenant).filter(CentralTenant.id == tenant_id).first()
            if not tenant:
                raise ValueError(f"Tenant '{tenant_id}' not found.")
            tenant.conversation_retention_days = retention_days
            session.commit()
            _invalidate_tenant_cache()
            logger.info(
                f"[RetentionService] Updated retention policy for tenant={tenant_id} to {retention_days} days."
            )
            return {
                "tenant_id": tenant_id,
                "retention_days": retention_days,
                "is_indefinite": (retention_days == 0),
            }
        finally:
            session.close()

    @staticmethod
    def generate_cleanup_report(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generate a dry-run audit report of expired records across one or all active tenants.

        Does NOT delete any records.
        """
        session = _get_central_session()
        try:
            if tenant_id:
                tenants = session.query(CentralTenant).filter(CentralTenant.id == tenant_id).all()
                if not tenants:
                    raise ValueError(f"Tenant '{tenant_id}' not found.")
            else:
                tenants = session.query(CentralTenant).filter(CentralTenant.is_active == True).all()

            reports = []
            now = utc_now()
            for t in tenants:
                days = t.conversation_retention_days or 0
                if days <= 0:
                    reports.append({
                        "tenant_id": t.id,
                        "tenant_name": t.name,
                        "retention_days": days,
                        "policy": "indefinite",
                        "cutoff_date": None,
                        "expired_chat_logs": 0,
                        "oldest_record_date": None,
                        "dry_run": True,
                    })
                    continue

                cutoff = now - datetime.timedelta(days=days)
                expired_count = (
                    session.query(ChatLog.id)
                    .filter(
                        ChatLog.tenant_id == t.id,
                        ChatLog.created_at < cutoff,
                    )
                    .count()
                )

                oldest_rec = (
                    session.query(ChatLog.created_at)
                    .filter(
                        ChatLog.tenant_id == t.id,
                        ChatLog.created_at < cutoff,
                    )
                    .order_by(ChatLog.created_at.asc())
                    .first()
                )
                oldest_str = oldest_rec[0].isoformat() if oldest_rec and oldest_rec[0] else None

                reports.append({
                    "tenant_id": t.id,
                    "tenant_name": t.name,
                    "retention_days": days,
                    "policy": f"{days}_days",
                    "cutoff_date": cutoff.isoformat(),
                    "expired_chat_logs": expired_count,
                    "oldest_record_date": oldest_str,
                    "dry_run": True,
                })

            return reports
        finally:
            session.close()

    @staticmethod
    def execute_retention_cleanup(tenant_id: str, dry_run: bool = True) -> Dict[str, Any]:
        """Execute conversation retention cleanup for a single tenant.

        Strictly tenant-isolated. Defaults to dry_run=True.
        """
        if dry_run:
            reports = RetentionService.generate_cleanup_report(tenant_id=tenant_id)
            rep = reports[0] if reports else {}
            return {
                **rep,
                "executed": False,
                "dry_run": True,
                "message": "Dry-run report generated. Explicitly pass dry_run=False to delete data.",
            }

        session = _get_central_session()
        try:
            tenant = session.query(CentralTenant).filter(CentralTenant.id == tenant_id).first()
            if not tenant:
                raise ValueError(f"Tenant '{tenant_id}' not found.")

            days = tenant.conversation_retention_days or 0
            if days <= 0:
                return {
                    "tenant_id": tenant_id,
                    "retention_days": days,
                    "policy": "indefinite",
                    "deleted_chat_logs": 0,
                    "deleted_checkpoints": 0,
                    "executed": True,
                    "dry_run": False,
                    "status": "skipped_indefinite",
                }

            now = utc_now()
            cutoff = now - datetime.timedelta(days=days)

            # 1. Fetch expired chat log IDs and sessions for this tenant only
            expired_logs = (
                session.query(ChatLog.id, ChatLog.session_id)
                .filter(
                    ChatLog.tenant_id == tenant_id,
                    ChatLog.created_at < cutoff,
                )
                .all()
            )

            deleted_logs_count = len(expired_logs)
            if deleted_logs_count > 0:
                log_ids = [l[0] for l in expired_logs]
                session_ids = list({l[1] for l in expired_logs if l[1]})

                # Delete associated chat feedback strictly for this tenant
                session.query(ChatFeedback).filter(
                    ChatFeedback.tenant_id == tenant_id,
                    ChatFeedback.session_id.in_(session_ids),
                ).delete(synchronize_session=False)

                # Delete expired chat logs strictly for this tenant
                session.query(ChatLog).filter(
                    ChatLog.tenant_id == tenant_id,
                    ChatLog.id.in_(log_ids),
                ).delete(synchronize_session=False)

            session.commit()

            # 2. Prune expired LangGraph checkpoints for this tenant
            deleted_cps = 0
            engine = _get_central_engine()
            try:
                with engine.begin() as conn:
                    dialect = engine.dialect.name
                    # Thread ID format: f"{tenant_id}:{session_id}"
                    res = conn.execute(
                        text("""
                        DELETE FROM langgraph_checkpoints
                        WHERE thread_id LIKE :thread_prefix AND created_at < :cutoff
                        """),
                        {"thread_prefix": f"{tenant_id}:%", "cutoff": cutoff},
                    )
                    deleted_cps = getattr(res, "rowcount", 0) or 0

                    # Also prune orphaned blobs and writes for sessions that were completely pruned
                    conn.execute(
                        text("""
                        DELETE FROM langgraph_checkpoint_blobs
                        WHERE thread_id LIKE :thread_prefix
                          AND thread_id NOT IN (SELECT DISTINCT thread_id FROM langgraph_checkpoints WHERE thread_id LIKE :thread_prefix)
                        """),
                        {"thread_prefix": f"{tenant_id}:%"},
                    )
                    conn.execute(
                        text("""
                        DELETE FROM langgraph_checkpoint_writes
                        WHERE thread_id LIKE :thread_prefix
                          AND thread_id NOT IN (SELECT DISTINCT thread_id FROM langgraph_checkpoints WHERE thread_id LIKE :thread_prefix)
                        """),
                        {"thread_prefix": f"{tenant_id}:%"},
                    )
            except Exception as e:
                logger.warning(f"[RetentionService] Checkpoint pruning skipped or failed for {tenant_id}: {e}")

            logger.info(
                f"[RetentionService] Cleanup completed for tenant={tenant_id}: "
                f"purged {deleted_logs_count} chat logs, {deleted_cps} checkpoints older than {cutoff.isoformat()}."
            )

            return {
                "tenant_id": tenant_id,
                "retention_days": days,
                "cutoff_date": cutoff.isoformat(),
                "deleted_chat_logs": deleted_logs_count,
                "deleted_checkpoints": deleted_cps,
                "executed": True,
                "dry_run": False,
                "status": "success",
            }
        finally:
            session.close()

    @staticmethod
    def run_all_retention_jobs(dry_run: bool = True) -> List[Dict[str, Any]]:
        """Run retention job for all active tenants."""
        reports = RetentionService.generate_cleanup_report()
        results = []
        for r in reports:
            t_id = r["tenant_id"]
            res = RetentionService.execute_retention_cleanup(tenant_id=t_id, dry_run=dry_run)
            results.append(res)
        return results
