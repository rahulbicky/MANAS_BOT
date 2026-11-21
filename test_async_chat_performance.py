"""
test_async_chat_performance.py
--------------------------------
Comprehensive test suite for Phase 1 Backend Stability & Performance:
1. Unit test: adetect_intent (async) with LangChain Runnable mock
2. Unit test: adetect_intent model fallback
3. Unit test: detect_intent (sync backward compatibility)
4. Unit test: aget_answer (async) with LangChain Runnable mock
5. Unit test: aget_answer model fallback
6. Unit test: get_answer (sync backward compatibility)
7. Integration: POST /chat standard flow (Phase A read -> Phase B async LLM -> Phase C write)
8. Integration: POST /chat lead capture (skips LLM, persists ChatLog & Lead)
9. Integration: POST /chat language gating (Starter plan)
10. Integration: POST /chat quota gating
11. Integration: POST /chat/feedback (threadpool offloaded)
12. Integration: GET /chat/config (threadpool offloaded)
13. Architecture Verification: Zero DB connections held during LLM execution
14. Concurrency & Event Loop Responsiveness: Concurrent /chat requests do NOT stall /health
15. Async Document Processing: Non-blocking URL scraping via httpx.AsyncClient
16. Threadpool Document Parsing: POST /admin/upload-doc
17. Chat Logs Pagination: GET /admin/chats with limit and offset
18. Leads Pagination: GET /admin/leads with limit and offset
19. Database Performance Indexes: Composite indexes verification in metadata
"""
import os
import sys
import time
import asyncio
import io
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Use isolated SQLite database for hermetic testing
os.environ["CENTRAL_DB_URL"] = "sqlite:///test_async_perf.db"
os.environ["DATABASE_URL"] = "sqlite:///test_async_perf.db"
os.environ["GROQ_API_KEY"] = "gsk_test_dummy_key_12345"

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from langchain_core.runnables import RunnableLambda

import backend.database as db_mod
from backend.database import (
    Base,
    CentralBase,
    CentralTenant,
    BusinessProfile,
    FAQ,
    KnowledgeDocument,
    ChatLog,
    Lead,
    ChatFeedback,
    Plan,
)
from backend.intent_chain import detect_intent, adetect_intent
from backend.faq_chain import get_answer, aget_answer
from backend.app.main import app
from backend.app.scheduler import stop_scheduler
from starlette.testclient import TestClient
import httpx


class AsyncPerformanceTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Configure isolated SQLite test engine
        cls.test_db_url = "sqlite:///test_async_perf.db"
        cls.engine = create_engine(cls.test_db_url, connect_args={"check_same_thread": False})
        
        # Monkeypatch central engine and sessionmaker in database module
        db_mod._central_engine = cls.engine
        db_mod._CentralSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        
        # Create all tables
        Base.metadata.drop_all(bind=cls.engine)
        CentralBase.metadata.drop_all(bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        CentralBase.metadata.create_all(bind=cls.engine)
        
        # Seed test plan
        session = db_mod._get_central_session()
        try:
            starter_plan = Plan(
                id="plan_starter",
                name="Starter",
                price_inr=0,
                messages_per_month=100,
                docs_limit=5,
                faqs_limit=20,
                export_enabled=False,
                languages="en",
            )
            session.add(starter_plan)
            
            # Seed test tenant
            cls.tenant_id = "test_tenant_async_001"
            cls.api_key = "test_api_key_12345"
            tenant = CentralTenant(
                id=cls.tenant_id,
                name="Acme Corp",
                username="acme_admin",
                api_key=cls.api_key,
                is_active=True,
                current_plan_id="plan_starter",
                notification_email="leads@acme.com",
            )
            session.add(tenant)
            
            # Seed profile
            profile = BusinessProfile(
                tenant_id=cls.tenant_id,
                company_name="Acme Corp",
                industry="Cloud Analytics",
                business_description="Enterprise cloud performance monitoring.",
                chatbot_system_prompt="Be concise and helpful.",
            )
            session.add(profile)
            
            # Seed FAQ
            faq = FAQ(
                tenant_id=cls.tenant_id,
                question="What is your pricing?",
                answer="Starter is free, Pro is INR 8,200/mo.",
                intent="pricing",
                is_active=True,
            )
            session.add(faq)
            
            session.commit()
        finally:
            session.close()
            
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        try:
            stop_scheduler()
        except Exception:
            pass
        cls.engine.dispose()
        if os.path.exists("test_async_perf.db"):
            try:
                os.remove("test_async_perf.db")
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Unit Tests for adetect_intent & detect_intent
    # ─────────────────────────────────────────────────────────────────────────
    def test_01_adetect_intent_success(self):
        """Verify async intent detection returns valid intent."""
        mock_response = MagicMock(content="pricing")

        with patch("backend.intent_chain.ChatGroq") as MockChatGroq:
            MockChatGroq.return_value = RunnableLambda(lambda x: mock_response)
            
            intent = asyncio.run(
                adetect_intent(
                    "how much does it cost?",
                    company="Acme Corp",
                    industry="Cloud Analytics",
                )
            )
            self.assertEqual(intent, "pricing")

    def test_02_adetect_intent_model_fallback(self):
        """Verify adetect_intent falls back to secondary model when primary fails."""
        call_count = 0
        def mock_groq_step(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Primary model timed out")
            return MagicMock(content="support")

        with patch("backend.intent_chain.ChatGroq") as MockChatGroq:
            MockChatGroq.side_effect = lambda *a, **k: RunnableLambda(mock_groq_step)
            
            intent = asyncio.run(
                adetect_intent(
                    "system is down",
                    company="Acme Corp",
                    industry="Cloud Analytics",
                )
            )
            self.assertEqual(intent, "support")
            self.assertEqual(call_count, 2)

    def test_03_detect_intent_sync_backward_compatibility(self):
        """Verify synchronous detect_intent still functions properly."""
        mock_response = MagicMock(content="pricing")

        with patch("backend.intent_chain.ChatGroq") as MockChatGroq:
            MockChatGroq.return_value = RunnableLambda(lambda x: mock_response)
            
            intent = detect_intent("what are your plans?", tenant_id=self.tenant_id)
            self.assertEqual(intent, "pricing")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Unit Tests for aget_answer & get_answer
    # ─────────────────────────────────────────────────────────────────────────
    def test_04_aget_answer_success(self):
        """Verify async FAQ answer generation returns LLM text."""
        mock_response = MagicMock(content="Our Starter plan is free, Pro is INR 8,200/month.")

        with patch("backend.faq_chain.ChatGroq") as MockChatGroq:
            MockChatGroq.return_value = RunnableLambda(lambda x: mock_response)
            
            ans = asyncio.run(
                aget_answer(
                    question="pricing details?",
                    intent="pricing",
                    tenant_id=self.tenant_id,
                    company="Acme Corp",
                    industry="Cloud Analytics",
                    faq_context="Q: What is pricing?\nA: Starter is free.",
                    doc_context="",
                )
            )
            self.assertIn("Starter plan is free", ans)

    def test_05_aget_answer_model_fallback(self):
        """Verify aget_answer falls back to secondary model on primary model failure."""
        call_count = 0
        def mock_groq_answer(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Groq 504 Gateway Timeout")
            return MagicMock(content="Fallback answer successfully generated.")

        with patch("backend.faq_chain.ChatGroq") as MockChatGroq:
            MockChatGroq.side_effect = lambda *a, **k: RunnableLambda(mock_groq_answer)
            
            ans = asyncio.run(
                aget_answer(
                    question="help me",
                    intent="support",
                    tenant_id=self.tenant_id,
                    company="Acme Corp",
                    industry="Cloud Analytics",
                    faq_context="",
                    doc_context="",
                )
            )
            self.assertEqual(ans, "Fallback answer successfully generated.")
            self.assertEqual(call_count, 2)

    def test_06_get_answer_sync_backward_compatibility(self):
        """Verify synchronous get_answer still functions properly."""
        mock_response = MagicMock(content="Sync response generated successfully.")

        with patch("backend.faq_chain.ChatGroq") as MockChatGroq:
            MockChatGroq.return_value = RunnableLambda(lambda x: mock_response)
            
            ans = get_answer("pricing", "pricing", self.tenant_id)
            self.assertEqual(ans, "Sync response generated successfully.")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Integration Tests for POST /chat & Decoupled Architecture
    # ─────────────────────────────────────────────────────────────────────────
    def test_07_post_chat_standard_flow(self):
        """Test complete POST /chat endpoint flow with async Groq chains."""
        mock_intent_res = MagicMock(content="pricing")
        mock_ans_res = MagicMock(content="We offer Starter and Pro tiers.")

        with patch("backend.intent_chain.ChatGroq") as MockIntentGroq, \
             patch("backend.faq_chain.ChatGroq") as MockFaqGroq:
            
            MockIntentGroq.return_value = RunnableLambda(lambda x: mock_intent_res)
            MockFaqGroq.return_value = RunnableLambda(lambda x: mock_ans_res)

            resp = self.client.post(
                "/chat",
                json={
                    "question": "What plans do you have?",
                    "session_id": "session_test_standard",
                    "tenant_id": self.tenant_id,
                    "language": "en",
                }
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["intent"], "pricing")
            self.assertIn("Starter and Pro", data["answer"])
            self.assertFalse(data["resolved"])

            # Verify ChatLog was recorded in DB
            session = db_mod._get_central_session()
            try:
                log = session.query(ChatLog).filter(
                    ChatLog.session_id == "session_test_standard"
                ).first()
                self.assertIsNotNone(log)
                self.assertEqual(log.detected_intent, "pricing")
            finally:
                session.close()

    def test_08_post_chat_lead_capture(self):
        """Test lead capture in POST /chat skips LLM and writes to Lead table."""
        with patch("backend.faq_chain.ChatGroq") as MockFaqGroq:
            resp = self.client.post(
                "/chat",
                json={
                    "question": "Rahul Kumar 9876543210 rahul@example.com please contact me regarding Enterprise",
                    "session_id": "session_test_lead",
                    "tenant_id": self.tenant_id,
                    "language": "en",
                }
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["intent"], "lead_captured")
            self.assertTrue(data["resolved"])
            self.assertIn("support team has received your details", data["answer"])
            # Ensure FAQ LLM chain was NOT invoked
            MockFaqGroq.assert_not_called()

            # Verify Lead table entry
            session = db_mod._get_central_session()
            try:
                lead = session.query(Lead).filter(Lead.session_id == "session_test_lead").first()
                self.assertIsNotNone(lead)
                self.assertEqual(lead.phone, "9876543210")
                self.assertEqual(lead.email, "rahul@example.com")
            finally:
                session.close()

    def test_09_post_chat_language_gating(self):
        """Test that non-English languages are blocked on Starter plan."""
        resp = self.client.post(
            "/chat",
            json={
                "question": "Bonjour",
                "session_id": "session_lang_gate",
                "tenant_id": self.tenant_id,
                "language": "fr",
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["intent"], "error_feature_gated")
        self.assertIn("Multi-language support is not available", data["answer"])

    def test_10_post_chat_quota_gating(self):
        """Test that requests are blocked when monthly quota is exceeded."""
        session = db_mod._get_central_session()
        try:
            now = db_mod.datetime.datetime.utcnow()
            for i in range(105):
                log = ChatLog(
                    tenant_id=self.tenant_id,
                    session_id=f"sess_quota_{i}",
                    encrypted_question="q",
                    encrypted_answer="a",
                    created_at=now,
                )
                session.add(log)
            session.commit()
        finally:
            session.close()

        resp = self.client.post(
            "/chat",
            json={
                "question": "Hello again",
                "session_id": "session_quota_test",
                "tenant_id": self.tenant_id,
                "language": "en",
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["intent"], "error_quota_exceeded")
        self.assertIn("Monthly message quota reached", data["answer"])

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Secondary Endpoints & Offloaded Execution
    # ─────────────────────────────────────────────────────────────────────────
    def test_11_chat_feedback_endpoint(self):
        """Test POST /chat/feedback upserts feedback record."""
        resp = self.client.post(
            "/chat/feedback",
            json={
                "tenant_id": self.tenant_id,
                "session_id": "session_test_standard",
                "rating": 5,
                "comment": "Outstanding quick assistance!",
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

        session = db_mod._get_central_session()
        try:
            fb = session.query(ChatFeedback).filter(
                ChatFeedback.session_id == "session_test_standard"
            ).first()
            self.assertIsNotNone(fb)
            self.assertEqual(fb.rating, 5)
        finally:
            session.close()

    def test_12_chat_config_endpoint(self):
        """Test GET /chat/config returns tenant configuration without auth."""
        resp = self.client.get(f"/chat/config?tenant_id={self.tenant_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["company_name"], "Acme Corp")
        self.assertIn("chatbot_greeting_message", data)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Architecture Verification: Zero DB Connections Held During Groq LLM
    # ─────────────────────────────────────────────────────────────────────────
    def test_13_zero_db_connections_held_during_llm(self):
        """Verify that ZERO database sessions/connections are checked out during LLM awaiting."""
        active_sessions = 0
        max_active_sessions_during_llm = 0
        original_get_tenant_session = db_mod.get_tenant_session

        def tracked_get_tenant_session(t_id):
            nonlocal active_sessions
            sess = original_get_tenant_session(t_id)
            active_sessions += 1
            original_close = sess.close
            def tracked_close():
                nonlocal active_sessions
                active_sessions -= 1
                return original_close()
            sess.close = tracked_close
            return sess

        async def simulated_slow_groq_llm(x):
            nonlocal active_sessions, max_active_sessions_during_llm
            max_active_sessions_during_llm = max(max_active_sessions_during_llm, active_sessions)
            await asyncio.sleep(0.05)
            return MagicMock(content="information")

        with patch("backend.app.api.routers.chat.get_tenant_session", side_effect=tracked_get_tenant_session), \
             patch("backend.intent_chain.ChatGroq") as MockIntentGroq, \
             patch("backend.faq_chain.ChatGroq") as MockFaqGroq:

            MockIntentGroq.return_value = RunnableLambda(simulated_slow_groq_llm)
            MockFaqGroq.return_value = RunnableLambda(simulated_slow_groq_llm)

            # Reset quota for this tenant
            session = db_mod._get_central_session()
            try:
                session.query(ChatLog).filter(ChatLog.tenant_id == self.tenant_id).delete()
                session.commit()
            finally:
                session.close()

            resp = self.client.post(
                "/chat",
                json={
                    "question": "Can you describe your service?",
                    "session_id": "session_zero_conn_test",
                    "tenant_id": self.tenant_id,
                    "language": "en",
                }
            )
            self.assertEqual(resp.status_code, 200)
            
            # CRITICAL ASSERTION: During LLM execution, active database sessions must be exactly 0
            self.assertEqual(
                max_active_sessions_during_llm, 0,
                f"Expected 0 active DB sessions during Groq call, but found {max_active_sessions_during_llm}!"
            )
            self.assertEqual(active_sessions, 0, "Leaked DB sessions detected!")

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Concurrency & Event Loop Responsiveness Verification
    # ─────────────────────────────────────────────────────────────────────────
    def test_14_concurrency_and_event_loop_responsiveness(self):
        """Verify that concurrent slow chat requests do NOT block /health or the event loop."""
        async def run_concurrent_load():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                async def slow_groq_mock(x):
                    await asyncio.sleep(0.2)
                    return MagicMock(content="Delayed response")

                with patch("backend.intent_chain.ChatGroq") as MockIntentGroq, \
                     patch("backend.faq_chain.ChatGroq") as MockFaqGroq:

                    MockIntentGroq.return_value = RunnableLambda(slow_groq_mock)
                    MockFaqGroq.return_value = RunnableLambda(slow_groq_mock)

                    # Fire 5 slow chat requests concurrently
                    chat_tasks = [
                        client.post(
                            "/chat",
                            json={
                                "question": f"Question {i}?",
                                "session_id": f"sess_conc_{i}",
                                "tenant_id": self.tenant_id,
                                "language": "en",
                            }
                        )
                        for i in range(5)
                    ]

                    # Ping /health while chat tasks are in flight
                    await asyncio.sleep(0.04)
                    t0 = time.time()
                    health_res = await client.get("/health")
                    health_duration = time.time() - t0

                    chat_responses = await asyncio.gather(*chat_tasks)
                    return health_res, health_duration, chat_responses

        health_res, health_duration, chat_responses = asyncio.run(run_concurrent_load())
        
        self.assertEqual(health_res.status_code, 200)
        self.assertLess(
            health_duration, 0.15,
            f"Event loop was blocked! /health took {health_duration:.3f}s while LLM was running."
        )
        for res in chat_responses:
            self.assertEqual(res.status_code, 200)

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Asynchronous Document Processing Tests (Phase 1)
    # ─────────────────────────────────────────────────────────────────────────
    def test_15_async_url_scraping_endpoint(self):
        """Verify POST /admin/add-url performs non-blocking async scraping."""
        mock_html = "<html><body><h1>Acme Features</h1><p>We provide real-time cloud metrics.</p></body></html>"

        # Mock httpx.AsyncClient.get
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            resp = self.client.post(
                f"/admin/add-url?tenant_id={self.tenant_id}",
                json={"url": "https://example.com/features"},
                headers={"X-Auth-Token": self.api_key},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["file_type"], "url")
            self.assertEqual(data["filename"], "https://example.com/features")

            # Check DB content
            session = db_mod._get_central_session()
            try:
                doc = session.query(KnowledgeDocument).filter(
                    KnowledgeDocument.filename == "https://example.com/features"
                ).first()
                self.assertIsNotNone(doc)
                self.assertIn("Acme Features", doc.content)
            finally:
                session.close()

    def test_16_threadpool_document_parsing(self):
        """Verify POST /admin/upload-doc parses uploaded document via worker threadpool."""
        sample_txt = b"Hello, this is a plain text knowledge document for Acme Corp."
        files = {
            "file": ("sample_info.txt", io.BytesIO(sample_txt), "text/plain")
        }
        resp = self.client.post(
            f"/admin/upload-doc?tenant_id={self.tenant_id}",
            files=files,
            headers={"X-Auth-Token": self.api_key},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["filename"], "sample_info.txt")
        self.assertEqual(data["file_type"], "txt")

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Pagination Tests (Phase 1)
    # ─────────────────────────────────────────────────────────────────────────
    def test_17_chat_logs_pagination(self):
        """Verify GET /admin/chats supports limit and offset and returns JSON array."""
        session = db_mod._get_central_session()
        try:
            from backend.encryption import encrypt_text
            # Seed 5 ordered chat logs
            for i in range(5):
                log = ChatLog(
                    tenant_id=self.tenant_id,
                    session_id=f"page_sess_{i}",
                    encrypted_question=encrypt_text(f"Question {i}"),
                    encrypted_answer=encrypt_text(f"Answer {i}"),
                    created_at=db_mod.datetime.datetime.utcnow() + db_mod.datetime.timedelta(minutes=i),
                )
                session.add(log)
            session.commit()
        finally:
            session.close()

        # Query first page of 2 items
        resp = self.client.get(
            f"/admin/chats?tenant_id={self.tenant_id}&limit=2&offset=0",
            headers={"X-Auth-Token": self.api_key},
        )
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        self.assertIsInstance(items, list)
        self.assertEqual(len(items), 2)
        # Most recent first
        first_session = items[0]["session_id"]

        # Query next page
        resp_p2 = self.client.get(
            f"/admin/chats?tenant_id={self.tenant_id}&limit=2&offset=2",
            headers={"X-Auth-Token": self.api_key},
        )
        self.assertEqual(resp_p2.status_code, 200)
        items_p2 = resp_p2.json()
        self.assertIsInstance(items_p2, list)
        self.assertEqual(len(items_p2), 2)
        self.assertNotEqual(first_session, items_p2[0]["session_id"])

    def test_18_leads_pagination(self):
        """Verify GET /admin/leads supports limit and offset and returns JSON array."""
        session = db_mod._get_central_session()
        try:
            for i in range(4):
                lead = Lead(
                    tenant_id=self.tenant_id,
                    session_id=f"lead_sess_{i}",
                    name=f"Lead User {i}",
                    phone="9000000000",
                    email=f"lead{i}@example.com",
                    created_at=db_mod.datetime.datetime.utcnow() + db_mod.datetime.timedelta(minutes=i),
                )
                session.add(lead)
            session.commit()
        finally:
            session.close()

        resp = self.client.get(
            f"/admin/leads?tenant_id={self.tenant_id}&limit=2&offset=0",
            headers={"X-Auth-Token": self.api_key},
        )
        self.assertEqual(resp.status_code, 200)
        leads = resp.json()
        self.assertIsInstance(leads, list)
        self.assertEqual(len(leads), 2)

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Database Performance Indexes Verification (Phase 1)
    # ─────────────────────────────────────────────────────────────────────────
    def test_19_database_composite_indexes_defined(self):
        """Verify composite performance indexes are defined in SQLAlchemy models."""
        inspector = inspect(self.engine)

        # Check chat_logs_v2 indexes
        chat_idx_names = [idx["name"] for idx in inspector.get_indexes("chat_logs_v2")]
        self.assertIn("ix_chat_logs_v2_tenant_id_created_at", chat_idx_names)

        # Check leads indexes
        leads_idx_names = [idx["name"] for idx in inspector.get_indexes("leads")]
        self.assertIn("ix_leads_tenant_id_created_at", leads_idx_names)

        # Check faqs indexes
        faq_idx_names = [idx["name"] for idx in inspector.get_indexes("faqs")]
        self.assertIn("ix_faqs_tenant_id_is_active", faq_idx_names)

        # Check knowledge_documents indexes
        doc_idx_names = [idx["name"] for idx in inspector.get_indexes("knowledge_documents")]
        self.assertIn("ix_knowledge_documents_tenant_id_is_active", doc_idx_names)

        # Check chat_feedback indexes
        fb_idx_names = [idx["name"] for idx in inspector.get_indexes("chat_feedback")]
        self.assertIn("ix_chat_feedback_tenant_id_session_id", fb_idx_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
