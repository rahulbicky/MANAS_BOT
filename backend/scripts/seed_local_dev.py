"""
Seed local development database with test data for live verification.
Uses SQLite local_dev.db to avoid touching production database.
"""
import os
import sys
import uuid
import datetime
import bcrypt

# Ensure local packages and project root are importable
sys.path.insert(0, os.path.abspath("."))
os.environ["CENTRAL_DB_URL"] = "sqlite:///c:/Users/hp/OneDrive/Desktop/MANAS_BOT-master/local_dev.db"

import backend.database as db_mod
from backend.database import (
    Base,
    CentralTenant,
    Plan,
    Employee,
    BusinessProfile,
    FAQ,
    KnowledgeDocument,
    DocumentChunk,
    _get_central_engine,
    _get_central_session,
)
from backend.rag.ingestion import ingest_document

def seed():
    session = _get_central_session()
    try:
        # 1. Plans
        plans_data = [
            {"id": "plan_starter", "name": "Starter", "price_inr": 499.0, "messages_per_month": 1000, "docs_limit": 5, "faqs_limit": 20, "export_enabled": False, "languages": "en"},
            {"id": "plan_pro", "name": "Pro", "price_inr": 1999.0, "messages_per_month": 10000, "docs_limit": 25, "faqs_limit": 100, "export_enabled": True, "languages": "all"},
            {"id": "plan_enterprise", "name": "Enterprise", "price_inr": 4999.0, "messages_per_month": 999999, "docs_limit": 999, "faqs_limit": 9999, "export_enabled": True, "languages": "all"},
        ]
        for pdata in plans_data:
            existing = session.query(Plan).filter(Plan.id == pdata["id"]).first()
            if not existing:
                session.add(Plan(**pdata))
        session.commit()
        print("✓ Plans seeded.")

        # 2. Super Admin Employee
        admin_email = "admin@manasbot.local"
        existing_emp = session.query(Employee).filter(Employee.email == admin_email).first()
        if not existing_emp:
            hashed_pwd = bcrypt.hashpw("Admin123!".encode(), bcrypt.gensalt()).decode()
            emp = Employee(
                id=str(uuid.uuid4()),
                name="System Administrator",
                email=admin_email,
                password_hash=hashed_pwd,
                role="super_admin",
                is_active=True,
            )
            session.add(emp)
            session.commit()
            print("✓ Super Admin Employee seeded (admin@manasbot.local / Admin123!).")
        else:
            print("✓ Super Admin Employee already exists.")

        # 3. Client Tenant
        tenant_username = "acme"
        tenant_id = "tenant_acme_local_001"
        existing_tenant = session.query(CentralTenant).filter(CentralTenant.username == tenant_username).first()
        if not existing_tenant:
            hashed_client_pwd = bcrypt.hashpw("Client123!".encode(), bcrypt.gensalt()).decode()
            tenant = CentralTenant(
                id=tenant_id,
                name="Acme Logistics",
                username=tenant_username,
                api_key="api_key_acme_local_12345",
                admin_password_hash=hashed_client_pwd,
                is_active=True,
                current_plan_id="plan_starter",
            )
            session.add(tenant)
            session.commit()
            print(f"✓ Client Tenant seeded (Username: acme / Client123! | Tenant ID: {tenant_id}).")
        else:
            tenant_id = existing_tenant.id
            print(f"✓ Client Tenant already exists (Tenant ID: {tenant_id}).")

        # 4. Business Profile
        existing_profile = session.query(BusinessProfile).filter(BusinessProfile.tenant_id == tenant_id).first()
        if not existing_profile:
            profile = BusinessProfile(
                tenant_id=tenant_id,
                company_name="Acme Logistics",
                industry="Logistics & Supply Chain",
                business_description="Acme Logistics provides domestic express delivery and enterprise supply chain management.",
                support_email="support@acme-logistics.com",
                phone="+91 98765 43210",
                chatbot_greeting_message="Welcome to Acme Logistics support. How can we help you today?",
                chatbot_system_prompt="You are the official customer service assistant for Acme Logistics. Answer questions professionally and accurately.",
            )
            session.add(profile)
            session.commit()
            print("✓ Business Profile seeded.")
        else:
            print("✓ Business Profile already exists.")

        # 5. FAQ
        existing_faq = session.query(FAQ).filter(FAQ.tenant_id == tenant_id).first()
        if not existing_faq:
            faq = FAQ(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                question="What is your standard shipping delivery time?",
                answer="Our standard domestic express delivery window is 2 to 3 business days for tier-1 and metropolitan locations.",
                intent="information",
                is_active=True,
            )
            session.add(faq)
            session.commit()
            print("✓ FAQ seeded.")
        else:
            print("✓ FAQ already exists.")

        # 6. Knowledge Document & Chunks
        doc_id = "doc_shipping_policy_001"
        existing_doc = session.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        doc_content = (
            "Acme Logistics Express Shipping Policy: "
            "Our express courier service guarantees delivery within 2 to 3 business days nationwide. "
            "Return requests must be initiated within 30 days of package receipt. "
            "Full refunds are credited within 5 to 7 business days following item inspection at our distribution warehouse."
        )
        if not existing_doc:
            doc = KnowledgeDocument(
                id=doc_id,
                tenant_id=tenant_id,
                filename="Express_Shipping_Policy.txt",
                content=doc_content,
                file_type="txt",
                file_size_bytes=len(doc_content),
                is_active=True,
            )
            session.add(doc)
            session.commit()

            # Ingest chunks & embeddings
            chunks_count = ingest_document(
                document_id=doc_id,
                tenant_id=tenant_id,
                filename="Express_Shipping_Policy.txt",
                file_type="txt",
                content=doc_content,
                db=session,
            )
            print(f"✓ Knowledge Document seeded with {chunks_count} chunks indexed.")
        else:
            print("✓ Knowledge Document already exists.")

        print("\nAll local development data successfully seeded into local_dev.db!")
    finally:
        session.close()

if __name__ == "__main__":
    seed()
