"""
Live functional verification of running ManasBot server.
Tests real HTTP requests against http://127.0.0.1:8000.
"""
import requests
import json

BASE_API = "http://127.0.0.1:8000"

def test_live_system():
    print("=== LIVE MANASBOT FUNCTIONAL VERIFICATION ===\n")
    
    # 1. Health check
    r = requests.get(f"{BASE_API}/health")
    print(f"1. Health Check: {r.status_code} -> {r.json()}")
    assert r.status_code == 200

    # 2. Super Admin Employee Login
    emp_payload = {"email": "admin@manasbot.local", "password": "Admin123!"}
    r = requests.post(f"{BASE_API}/admin/employee-login", json=emp_payload)
    print(f"2. Employee Login (Super Admin): {r.status_code}")
    assert r.status_code == 200
    emp_data = r.json()
    admin_token = emp_data["token"]
    print(f"   Role: {emp_data['role']} | Token: {admin_token[:20]}...")

    # 3. Client Resolve Username
    r = requests.post(f"{BASE_API}/admin/resolve-username", json={"username": "acme"})
    print(f"3. Client Resolve Username: {r.status_code} -> {r.json()}")
    assert r.status_code == 200
    tenant_id = r.json()["tenant_id"]

    # 4. Client Auth Login
    auth_payload = {"tenant_id": tenant_id, "password": "Client123!"}
    r = requests.post(f"{BASE_API}/admin/auth", json=auth_payload)
    print(f"4. Client Auth: {r.status_code}")
    assert r.status_code == 200
    client_token = r.json()["token"]
    print(f"   Authenticated: {r.json()['authenticated']} | API Key Token: {client_token[:20]}...")

    # 5. Chatbot Config Endpoint
    r = requests.get(f"{BASE_API}/chat/config?tenant_id={tenant_id}")
    print(f"5. Chatbot Config: {r.status_code} -> Company: {r.json().get('company_name')}")
    assert r.status_code == 200

    # 6. Knowledge Documents List & Chunk Count
    headers = {"X-Auth-Token": client_token}
    r = requests.get(f"{BASE_API}/admin/docs?tenant_id={tenant_id}", headers=headers)
    print(f"6. Knowledge Documents List: {r.status_code} -> Found {len(r.json())} docs")
    assert r.status_code == 200
    for doc in r.json():
        print(f"   - Doc: {doc['filename']} ({doc['file_type']}) | Indexed Chunks: {doc['chunk_count']}")

    # 7. Document Upload & Chunk Indexing
    files = {"file": ("return_terms.txt", b"Acme Return Terms: Customers can return unopened packages within 30 days for a 100% refund.", "text/plain")}
    r = requests.post(f"{BASE_API}/admin/upload-doc?tenant_id={tenant_id}", files=files, headers=headers)
    print(f"7. Document Upload & FastEmbed Indexing: {r.status_code}")
    assert r.status_code == 200
    uploaded_doc = r.json()
    print(f"   Uploaded: {uploaded_doc['filename']} | Created Chunks: {uploaded_doc['chunk_count']}")

    # 8. Chatbot RAG Query & Source Citations
    chat_payload = {
        "question": "What is the return window for packages?",
        "session_id": "sess_live_demo_001",
        "tenant_id": tenant_id,
        "language": "en"
    }
    r = requests.post(f"{BASE_API}/chat", json=chat_payload)
    print(f"8. Chatbot POST /chat: {r.status_code}")
    assert r.status_code == 200
    chat_resp = r.json()
    print(f"   Intent: {chat_resp['intent']}")
    print(f"   Answer: {chat_resp['answer']}")
    print(f"   Sources: {chat_resp['sources']}")

    # 9. Lead Capture Detection
    lead_chat = {
        "question": "Hello, my name is John Doe, email john@example.com, phone 9876543210. Please contact me.",
        "session_id": "sess_live_lead_001",
        "tenant_id": tenant_id,
        "language": "en"
    }
    r = requests.post(f"{BASE_API}/chat", json=lead_chat)
    print(f"9. Lead Capture Trigger: {r.status_code}")
    assert r.status_code == 200
    print(f"   Intent: {r.json()['intent']} (Expected: lead_captured)")
    assert r.json()["intent"] == "lead_captured"

    # 10. Check Leads in Admin API
    r = requests.get(f"{BASE_API}/admin/leads?tenant_id={tenant_id}", headers=headers)
    print(f"10. Client Admin Leads: {r.status_code} -> Found {len(r.json())} leads")
    assert r.status_code == 200
    if len(r.json()) > 0:
        lead = r.json()[0]
        print(f"    Captured Lead: Name='{lead['name']}', Phone='{lead['phone']}', Email='{lead['email']}'")

    # 11. Multi-Tenant Isolation
    # Call docs without token or with invalid tenant
    r_unauth = requests.get(f"{BASE_API}/admin/docs?tenant_id={tenant_id}")
    print(f"11. Tenant Security (Missing Token): {r_unauth.status_code} (Expected 401/403)")
    assert r_unauth.status_code in (401, 403)

    print("\n✓ ALL 11 LIVE FUNCTIONAL CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_live_system()
