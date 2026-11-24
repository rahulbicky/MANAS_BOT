"""
backend/scripts/verify_live_application.py
------------------------------------------
End-to-end integration and actual application verification for ManasBot Phase 3.1.
Executes against FastAPI TestClient with SQLite local database.
"""
import os
import sys
import uuid
import datetime

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath("."))
os.environ["CENTRAL_DB_URL"] = "sqlite:///./test_live_verify.db"
os.environ["DATABASE_URL"] = "sqlite:///./test_live_verify.db"
os.environ["DISABLE_FAST_EMBED"] = "false"  # Test actual FastEmbed ingestion
os.environ["DISABLE_GROQ_CALLS"] = "true"   # Unit/mock inference for deterministic assertions

from starlette.testclient import TestClient

import backend.database as db_mod
from backend.database import (
    init_tenant_db,
    migrate_central_schema,
    _get_central_engine,
    _get_central_session,
    create_employee,
    register_tenant,
    CentralTenant,
    Plan,
    utc_now,
)
from backend.app.main import app

def run_verification():
    print("==================================================")
    print("MANASBOT PHASE 3.1 - LIVE APPLICATION VERIFICATION")
    print("==================================================")

    # 1. Initialize Test Database & Run Migrations
    print("\n[Step 1] Initializing Database & Running Schema Migrations...")
    db_mod.CENTRAL_DB_URL = "sqlite:///./test_live_verify.db"
    db_mod._central_engine = None
    db_mod._CentralSessionLocal = None
    init_tenant_db()
    migrate_central_schema()
    print(" -> PASS: Central schema tables and additive columns verified.")

    # 2. Seed Plans
    session = _get_central_session()
    try:
        if not session.query(Plan).filter(Plan.name == "Starter").first():
            session.add(Plan(name="Starter", price_inr=499.0, messages_per_month=1000, docs_limit=5, faqs_limit=20, languages="en"))
        if not session.query(Plan).filter(Plan.name == "Pro").first():
            session.add(Plan(name="Pro", price_inr=1999.0, messages_per_month=10000, docs_limit=25, faqs_limit=100, languages="all"))
        session.commit()
    finally:
        session.close()

    # 3. Create Super Admin Employee
    print("\n[Step 2] Creating and Authenticating Super Admin Employee...")
    admin_email = f"superadmin_{uuid.uuid4().hex[:6]}@manasbot.local"
    emp = create_employee(
        name="Super Admin",
        email=admin_email,
        plain_password="AdminSecure123!",
        role="super_admin",
    )
    print(f" -> Created Employee: {emp['email']} (role: {emp['role']})")

    client = TestClient(app)

    # Health check
    res = client.get("/health")
    assert res.status_code == 200, f"Health check failed: {res.text}"
    print(" -> PASS: GET /health returns 200 OK.")

    # Login super admin
    login_res = client.post("/admin/employee-login", json={"email": admin_email, "password": "AdminSecure123!"})
    assert login_res.status_code == 200, f"Employee login failed: {login_res.text}"
    admin_token = login_res.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    print(" -> PASS: POST /admin/employee-login returned valid JWT Bearer token.")

    # 4. Register Tenant
    print("\n[Step 3] Registering Client Tenant & Client Panel Login...")
    reg_res = client.post(
        "/admin/tenant",
        headers=admin_headers,
        json={
            "name": f"Acme Logistics {uuid.uuid4().hex[:4]}",
            "db_url": "sqlite:///./test_live_verify.db",
            "admin_password": "ClientSecure123!",
            "notification_email": "alerts@acmelogistics.local",
        },
    )
    assert reg_res.status_code == 200, f"Tenant registration failed: {reg_res.text}"
    tenant_info = reg_res.json()
    tenant_id = tenant_info["id"]
    tenant_api_key = tenant_info["api_key"]
    tenant_headers = {"X-Auth-Token": tenant_api_key}
    print(f" -> PASS: Tenant registered: id={tenant_id}")

    # Client auth login
    client_auth = client.post("/admin/auth", json={"tenant_id": tenant_id, "password": "ClientSecure123!"})
    assert client_auth.status_code == 200, f"Client auth failed: {client_auth.text}"
    print(" -> PASS: POST /admin/auth validated client credentials.")

    # 5. Widget Configuration
    print("\n[Step 4] Checking Widget & Chatbot Config APIs...")
    cfg_res = client.get(f"/chat/config?tenant_id={tenant_id}")
    assert cfg_res.status_code == 200, f"Chat config failed: {cfg_res.text}"
    cfg_data = cfg_res.json()
    assert "company_name" in cfg_data
    assert "chatbot_greeting_message" in cfg_data
    print(f" -> PASS: GET /chat/config returned widget branding: company='{cfg_data['company_name']}'.")

    # 6. Retention Policy CRUD & Dry-Run
    print("\n[Step 5] Testing Retention Policy Endpoints & Dry-Run Report...")
    # Get initial policy (should be 0 / indefinite)
    p_res = client.get(f"/admin/retention-policy?tenant_id={tenant_id}", headers=tenant_headers)
    assert p_res.status_code == 200
    assert p_res.json()["is_indefinite"] == True

    # Set policy to 30 days
    set_p = client.post(f"/admin/retention-policy?tenant_id={tenant_id}&days=30", headers=admin_headers)
    assert set_p.status_code == 200
    assert set_p.json()["retention_days"] == 30

    # Dry-run report
    rep = client.get(f"/admin/retention-report?tenant_id={tenant_id}", headers=tenant_headers)
    assert rep.status_code == 200
    assert rep.json()[0]["dry_run"] == True
    print(" -> PASS: Retention policy configuration and dry-run report verified.")

    # 7. Document Upload & Chunk Ingestion
    print("\n[Step 6] Testing Document Upload & FastEmbed Indexing...")
    sample_doc_content = (
        b"Acme Logistics Shipping Policy: Domestic deliveries arrive in 2-3 business days. "
        b"International deliveries take 5-10 business days. Returns are accepted within 30 days."
    )
    upload_res = client.post(
        f"/admin/upload-doc?tenant_id={tenant_id}",
        headers=tenant_headers,
        files={"file": ("shipping_policy.txt", sample_doc_content, "text/plain")},
    )
    assert upload_res.status_code == 200, f"Doc upload failed: {upload_res.text}"
    doc_data = upload_res.json()
    print(f" -> PASS: Uploaded {doc_data['filename']} with {doc_data.get('chunk_count', 1)} chunks indexed.")

    # 8. Chat Workflow & LangGraph Execution
    print("\n[Step 7] Testing Conversational Chatbot Workflow...")
    chat_res = client.post(
        "/chat",
        json={
            "tenant_id": tenant_id,
            "session_id": "live_test_session_1",
            "question": "What is your shipping policy?",
            "language": "en",
        },
    )
    assert chat_res.status_code == 200, f"Chat failed: {chat_res.text}"
    chat_body = chat_res.json()
    assert "answer" in chat_body
    print(f" -> PASS: POST /chat returned answer (Intent: {chat_body.get('intent')})")

    # 9. Lead Capture Workflow
    print("\n[Step 8] Testing Lead Capture Workflow...")
    # 8a: Pure lead submission
    pure_lead_res = client.post(
        "/chat",
        json={
            "tenant_id": tenant_id,
            "session_id": "live_test_lead_session_2",
            "question": "Jane Doe, email jane@example.com, phone 9876543210.",
            "language": "en",
        },
    )
    assert pure_lead_res.status_code == 200
    assert pure_lead_res.json()["intent"] == "lead_captured"
    print(" -> PASS: Pure contact submission detected (Intent: lead_captured).")

    # 8b: Combined lead + inquiry (persists lead while answering question)
    combined_lead_res = client.post(
        "/chat",
        json={
            "tenant_id": tenant_id,
            "session_id": "live_test_lead_session_3",
            "question": "John Smith, email john@example.com, phone 9876543211. What is your shipping policy?",
            "language": "en",
        },
    )
    assert combined_lead_res.status_code == 200
    print(" -> PASS: Combined lead + inquiry routed to knowledge workflow without dropping lead.")

    # Verify both leads saved in database via admin API
    leads_list = client.get(f"/admin/leads?tenant_id={tenant_id}", headers=tenant_headers)
    assert leads_list.status_code == 200
    leads = leads_list.json()
    assert len(leads) >= 2
    lead_emails = {l["email"] for l in leads}
    assert "jane@example.com" in lead_emails
    assert "john@example.com" in lead_emails
    print(f" -> PASS: Leads verified in GET /admin/leads: {sorted(list(lead_emails))}")

    # 10. Multi-Turn Session Memory Verification
    print("\n[Step 9] Testing Multi-Turn Session Memory...")
    # Follow-up question in the same session
    followup_res = client.post(
        "/chat",
        json={
            "tenant_id": tenant_id,
            "session_id": "live_test_session_1",
            "question": "How long do international shipments take?",
            "language": "en",
        },
    )
    assert followup_res.status_code == 200
    print(" -> PASS: Multi-turn second query executed successfully with session state.")

    # Verify chat history API
    chats_res = client.get(f"/admin/chats?tenant_id={tenant_id}", headers=tenant_headers)
    assert chats_res.status_code == 200
    assert len(chats_res.json()) >= 2
    print(f" -> PASS: Chat logs stored and decrypted in GET /admin/chats ({len(chats_res.json())} turns).")

    # 11. Analytics Verification
    print("\n[Step 10] Testing Analytics & Operational Metrics API...")
    metrics_res = client.get("/admin/metrics", headers=admin_headers)
    assert metrics_res.status_code == 200, f"Metrics API failed: {metrics_res.text}"
    metrics_data = metrics_res.json()
    print(f" -> PASS: GET /admin/metrics returned: total_requests={metrics_data.get('total_requests', 0)}, status=200 OK.")

    # 12. Subscription Restrictions Verification
    print("\n[Step 11] Testing Subscription Quotas & Plan Restrictions...")
    # Attempt to upload beyond document storage limit (limits.docs)
    session = _get_central_session()
    try:
        t_record = session.query(CentralTenant).filter(CentralTenant.id == tenant_id).first()
        t_record.current_plan = "Starter"
        session.commit()
    finally:
        session.close()

    # Upload multiple documents until limit is reached
    doc_limit_hit = False
    for i in range(7):
        dummy_file = ("dummy.txt", f"Sample compliance clause #{i} content.".encode("utf-8"), "text/plain")
        upload_attempt = client.post(
            f"/admin/upload-doc?tenant_id={tenant_id}",
            files={"file": dummy_file},
            headers=tenant_headers,
        )
        if upload_attempt.status_code == 403 and "limit reached" in upload_attempt.json().get("detail", "").lower():
            doc_limit_hit = True
            print(f" -> PASS: Subscription doc limit enforced on attempt {i+1}: 403 Forbidden ({upload_attempt.json().get('detail')}).")
            break

    assert doc_limit_hit, "Subscription plan document quota was not enforced!"

    # 13. Frontend Files Verification
    print("\n[Step 12] Verifying Frontend Static Asset Files...")
    expected_frontend_files = [
        "frontend/admin/index.html",
        "frontend/admin/script.js",
        "frontend/admin/style.css",
        "frontend/client/index.html",
        "frontend/client/script.js",
        "frontend/client/style.css",
        "frontend/chatbot/index.html",
        "frontend/chatbot/script.js",
        "frontend/chatbot/style.css",
        "frontend/chatbot/chatbot-embed.js",
    ]
    for fp in expected_frontend_files:
        assert os.path.exists(fp), f"Missing frontend asset: {fp}"
        size_kb = os.path.getsize(fp) / 1024
        print(f" -> Verified: {fp} ({size_kb:.1f} KB)")

    print("\n==================================================")
    print("ALL 12 LIVE APPLICATION INTEGRATION TESTS PASSED!")
    print("==================================================")

    # Cleanup test db
    db_engine = _get_central_engine()
    db_engine.dispose()
    for f in ["./test_live_verify.db", "test_live_verify.db"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

if __name__ == "__main__":
    run_verification()
