import os
import logging
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

from .database import get_tenant_session, BusinessProfile

load_dotenv()
logger = logging.getLogger(__name__)

VALID_INTENTS = {"pricing", "service_inquiry", "support", "contact", "information", "eligibility"}
INTENT_MODELS = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "gemma2-9b-it"]


def _build_intent_prompt(company: str, industry: str) -> ChatPromptTemplate:
    system_prompt = (
        f"You are an intent detection bot for {company}, a business in the {industry} industry. "
        "Classify the following user question into exactly one of these categories: "
        "pricing, service_inquiry, support, contact, information, eligibility. "
        "If the question is in Hindi or Hinglish, still classify it into one of these categories. "
        "Return only the category name in lowercase."
    )
    return ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{question}")
    ])


def detect_intent(question: str, tenant_id: str = None, db=None) -> str:
    """Detect intent from user question (synchronous). Preserved for backwards compatibility."""
    company = "the company"
    industry = "general services"

    if tenant_id:
        try:
            should_close = False
            if db is None:
                db = get_tenant_session(tenant_id)
                should_close = True

            try:
                with db.begin_nested():
                    profile = db.query(BusinessProfile.company_name, BusinessProfile.industry).filter(BusinessProfile.tenant_id == tenant_id).first()
            except Exception as profile_err:
                logger.warning(f"[intent_chain] Failed to load profile for tenant {tenant_id}: {profile_err}")
                profile = None

            if should_close:
                db.close()

            if profile:
                company = profile[0] or company
                industry = profile[1] or industry
        except Exception as e:
            logger.warning(f"[intent_chain] Could not fetch tenant profile for {tenant_id}: {e}")

    prompt = _build_intent_prompt(company, industry)

    for model_name in INTENT_MODELS:
        try:
            llm = ChatGroq(model=model_name, temperature=0)
            chain = prompt | llm
            response = chain.invoke({"question": question})
            result = response.content.strip().lower()
            if result not in VALID_INTENTS:
                result = "information"
            logger.info(f"[intent_chain] Model '{model_name}' detected intent='{result}' for tenant={tenant_id}")
            return result
        except Exception as e:
            logger.warning(f"[intent_chain] Model '{model_name}' failed: {e}")
            continue

    logger.error("[intent_chain] All models failed for intent detection. Defaulting to 'information'.")
    return "information"


async def adetect_intent(
    question: str,
    tenant_id: str = None,
    db=None,
    company: str = None,
    industry: str = None,
) -> str:
    """Detect intent from user question asynchronously using ChatGroq.ainvoke.

    If company and industry are provided, database access is completely bypassed,
    ensuring zero database connections are held during LLM execution.
    """
    comp = company or "the company"
    ind = industry or "general services"

    if (not company or not industry) and tenant_id:
        try:
            should_close = False
            if db is None:
                db = get_tenant_session(tenant_id)
                should_close = True

            try:
                with db.begin_nested():
                    profile = db.query(BusinessProfile.company_name, BusinessProfile.industry).filter(BusinessProfile.tenant_id == tenant_id).first()
            except Exception as profile_err:
                logger.warning(f"[intent_chain] Failed to load profile for tenant {tenant_id}: {profile_err}")
                profile = None

            if should_close:
                db.close()

            if profile:
                comp = profile[0] or comp
                ind = profile[1] or ind
        except Exception as e:
            logger.warning(f"[intent_chain] Could not fetch tenant profile for {tenant_id}: {e}")

    prompt = _build_intent_prompt(comp, ind)

    for model_name in INTENT_MODELS:
        try:
            llm = ChatGroq(model=model_name, temperature=0)
            chain = prompt | llm
            response = await chain.ainvoke({"question": question})
            result = response.content.strip().lower()
            if result not in VALID_INTENTS:
                result = "information"
            logger.info(f"[intent_chain] Async model '{model_name}' detected intent='{result}' for tenant={tenant_id}")
            return result
        except Exception as e:
            logger.warning(f"[intent_chain] Async model '{model_name}' failed: {e}")
            continue

    logger.error("[intent_chain] All async models failed for intent detection. Defaulting to 'information'.")
    return "information"


if __name__ == "__main__":
    test_q = "what is your price?"
    print(f"Question: {test_q}")
    print(f"Intent: {detect_intent(test_q)}")
