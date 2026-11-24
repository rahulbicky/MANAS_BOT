"""
backend/app/repositories/tenant_repo.py
---------------------------------------
Data access repository for tenant metadata, business profiles, FAQs, and limits.
Enforces short-lived database sessions and safe nested transactions.
"""
import datetime
import logging
from typing import Dict, Any, Optional, List

from ...database import (
    get_tenant_session,
    get_tenant_by_id,
    get_tenant_limits,
    ChatLog,
    BusinessProfile,
    FAQ,
)

logger = logging.getLogger(__name__)


class TenantRepository:
    """Repository managing tenant lookups, limits, business profiles, and FAQ configurations."""

    @staticmethod
    def get_tenant(tenant_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve tenant configuration dict by tenant_id."""
        return get_tenant_by_id(tenant_id)

    @staticmethod
    def get_limits(tenant_id: str) -> Dict[str, Any]:
        """Retrieve plan limits for a tenant."""
        return get_tenant_limits(tenant_id)

    @staticmethod
    def get_chat_read_context(tenant_id: str) -> Dict[str, Any]:
        """Phase A: Short-lived database read to retrieve quota status, business profile,

        and active FAQs.
        Closes the session immediately so zero DB connections are held during inference.
        """
        db = None
        try:
            db = get_tenant_session(tenant_id)

            # 1. Monthly message quota count
            first_day_of_month = datetime.datetime.now(datetime.timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            monthly_messages = (
                db.query(ChatLog.id)
                .filter(
                    ChatLog.tenant_id == tenant_id,
                    ChatLog.created_at >= first_day_of_month,
                )
                .count()
            )

            # 2. Business profile
            try:
                with db.begin_nested():
                    profile = (
                        db.query(
                            BusinessProfile.company_name,
                            BusinessProfile.industry,
                            BusinessProfile.business_description,
                            BusinessProfile.chatbot_system_prompt,
                        )
                        .filter(BusinessProfile.tenant_id == tenant_id)
                        .first()
                    )
            except Exception as profile_err:
                logger.warning(
                    f"[tenant_repo] Failed to load BusinessProfile for tenant {tenant_id}: {profile_err}"
                )
                profile = None

            company = profile[0] if profile and profile[0] else "the company"
            industry = profile[1] if profile and profile[1] else "general services"
            desc = profile[2] if profile and profile[2] else ""
            custom_prompt = profile[3] if profile and profile[3] else ""

            # 3. Active FAQs
            faqs = (
                db.query(FAQ.intent, FAQ.question, FAQ.answer)
                .filter(FAQ.tenant_id == tenant_id, FAQ.is_active == True)
                .all()
            )
            faq_list = [
                {"intent": f.intent, "question": f.question, "answer": f.answer}
                for f in faqs
            ]

            return {
                "monthly_messages": monthly_messages,
                "company": company,
                "industry": industry,
                "desc": desc,
                "custom_prompt": custom_prompt,
                "faqs": faq_list,
            }
        finally:
            if db:
                db.close()

    @staticmethod
    def get_widget_config(tenant_id: str) -> Dict[str, Any]:
        """Fetch widget branding and greeting configuration for the tenant widget."""
        default_config = {
            "company_name": "MANAS BOT",
            "logo_url": "",
            "chatbot_greeting_message": "Hi! How can I help you today?",
            "brand_color_primary": "",
            "brand_color_secondary": "",
        }
        db = None
        try:
            db = get_tenant_session(tenant_id)
            profile = (
                db.query(BusinessProfile)
                .filter(BusinessProfile.tenant_id == tenant_id)
                .first()
            )
            if profile:
                return {
                    "company_name": profile.company_name or default_config["company_name"],
                    "logo_url": profile.logo_url or "",
                    "chatbot_greeting_message": profile.chatbot_greeting_message
                    or default_config["chatbot_greeting_message"],
                    "brand_color_primary": profile.brand_color_primary or "",
                    "brand_color_secondary": profile.brand_color_secondary or "",
                }
            return default_config
        except Exception as e:
            logger.warning(
                f"[tenant_repo] Could not load widget config for tenant {tenant_id}: {e}"
            )
            return default_config
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass
