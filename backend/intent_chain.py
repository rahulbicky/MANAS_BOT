import os
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

from .database import get_tenant_session, BusinessProfile

load_dotenv()


def detect_intent(question: str, tenant_id: str = None, db=None) -> str:
    """Detect intent from user question. If tenant_id is provided, uses tenant's business profile for context."""
    import logging
    logger = logging.getLogger(__name__)

    company = "the company"
    industry = "general services"

    if tenant_id:
        try:
            should_close = False
            if db is None:
                db = get_tenant_session(tenant_id)
                should_close = True

            # Query only needed columns to stay resilient to additive schema drift.
            # Using begin_nested() creates a SAVEPOINT. If the query fails (e.g. missing column),
            # only the savepoint is rolled back instead of aborting the entire transaction block.
            try:
                with db.begin_nested():
                    profile = db.query(BusinessProfile.company_name, BusinessProfile.industry).filter(BusinessProfile.tenant_id == tenant_id).first()
            except Exception as profile_err:
                logger.warning(f"[intent_chain] Failed to load profile for tenant {tenant_id}: {profile_err}")
                profile = None

            if should_close:
                db.close()

            if profile:
                company = profile[0]
                industry = profile[1]
        except Exception as e:
            logger.warning(f"[intent_chain] Could not fetch tenant profile for {tenant_id}: {e}")

    system_prompt = (
        f"You are an intent detection bot for {company}, a business in the {industry} industry. "
        "Classify the following user question into exactly one of these categories: "
        "pricing, service_inquiry, support, contact, information, eligibility. "
        "If the question is in Hindi or Hinglish, still classify it into one of these categories. "
        "Return only the category name in lowercase."
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{question}")
    ])

    # Try models in order — fallback if primary unavailable
    _models = ["openai/gpt-oss-20b", "llama3-8b-8192", "gemma2-9b-it"]
    for model_name in _models:
        try:
            llm = ChatGroq(model=model_name, temperature=0)
            chain = prompt | llm
            response = chain.invoke({"question": question})
            result = response.content.strip().lower()
            # Validate result is a known intent
            valid_intents = {"pricing", "service_inquiry", "support", "contact", "information", "eligibility"}
            if result not in valid_intents:
                result = "information"
            logger.info(f"[intent_chain] Model '{model_name}' detected intent='{result}' for tenant={tenant_id}")
            return result
        except Exception as e:
            logger.warning(f"[intent_chain] Model '{model_name}' failed: {e}")
            continue

    # All models failed — use safe default
    logger.error(f"[intent_chain] All models failed for intent detection. Defaulting to 'information'.")
    return "information"



if __name__ == "__main__":
    test_q = "what is your price?"
    print(f"Question: {test_q}")
    print(f"Intent: {detect_intent(test_q)}")
