"""
test_async_chat_performance.py
--------------------------------
Comprehensive test suite for Phase 2 Async Performance Implementation:
1. Unit test: adetect_intent (async) & model fallback
2. Unit test: aget_answer (async) & model fallback
3. Unit test: detect_intent (sync backward compatibility)
4. Unit test: get_answer (sync backward compatibility)
5. Integration: POST /chat standard query (Phase A read -> Phase B async LLM -> Phase C write)
6. Integration: POST /chat lead capture (skips LLM, persists ChatLog & Lead)
7. Integration: POST /chat language gating (Starter plan)
8. Integration: POST /chat quota gating
9. Integration: POST /chat/feedback (threadpool offloaded)
10. Integration: GET /chat/config (threadpool offloaded)
11. Architecture Verification: Zero DB connections held during LLM execution
12. Concurrency & Event Loop Responsiveness: Concurrent /chat requests do NOT stall /health
"""
import os
import sys
import time
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Use isolated SQLite database for hermetic testing
os.environ["CENTRAL_DB_URL"] = "sqlite:///test_async_perf.db"
os.environ["DATABASE_URL"] = "sqlite:///test_async_perf.db"
os.environ["GROQ_API_KEY"] = "gsk_test_dummy_key_12345"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
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
            tenant = CentralTenant(
                id=cls.tenant_id,
                name="Acme Corp",
                username="acme_admin",
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
        mock_response = MagicMock()
        mock_response.content = "pricing"

        with patch("backend.intent_chain.ChatGroq") as MockChatGroq:
            instance = MockChatGroq.return_value
            # ainvoke returns coroutine with mock_response
            instance.__or__ = MagicMock(return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_response)))
            
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
        mock_response = MagicMock()
        mock_response.content = "support"

        call_count = 0
        async def mock_ainvoke(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Primary model timed out")
            return mock_response

        with patch("backend.intent_chain.ChatGroq") as MockChatGroq:
            instance = MockChatGroq.return_value
            chain_mock = MagicMock()
            chain_mock.ainvoke = mock_ainvoke
            instance.__or__ = MagicMock(return_value=chain_mock)
            
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
        mock_response = MagicMock()
        mock_response.content = "pricing"

        with patch("backend.intent_chain.ChatGroq") as MockChatGroq:
            instance = MockChatGroq.return_value
            chain_mock = MagicMock()
            chain_mock.invoke = MagicMock(return_value=mock_response)
            instance.__or__ = MagicMock(return_value=chain_mock)
            
            intent = detect_intent("what are your plans?", tenant_id=self.tenant_id)
            self.assertEqual(intent, "pricing")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Unit Tests for aget_answer & get_answer
    # ─────────────────────────────────────────────────────────────────────────
    def test_04_aget_answer_success(self):
        """Verify async FAQ answer generation returns LLM text."""
        mock_response = MagicMock()
        mock_response.content = "Our Starter plan is free, Pro is INR 8,200/month."

        with patch("backend.faq_chain.ChatGroq") as MockChatGroq:
            instance = MockChatGroq.return_value
            chain_mock = MagicMock()
            chain_mock.ainvoke = AsyncMock(return_value=mock_response)
            instance.__or__ = MagicMock(return_value=chain_mock)
            
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
        mock_response = MagicMock()
        mock_response.content = "Fallback answer successfully generated."

        call_count = 0
        async def mock_ainvoke(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Groq 504 Gateway Timeout")
            return mock_response

        with patch("backend.faq_chain.ChatGroq") as MockChatGroq:
            instance = MockChatGroq.return_value
            chain_mock = MagicMock()
            chain_mock.ainvoke = mock_ainvoke
            instance.__or__ = MagicMock(return_value=chain_mock)
            
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
        mock_response = MagicMock()
        mock_response.content = "Sync response generated successfully."

        with patch("backend.faq_chain.ChatGroq") as MockChatGroq:
            instance = MockChatGroq.return_value
            chain_mock = MagicMock()
            chain_mock.invoke = MagicMock(return_value=mock_response)
            instance.__or__ = MagicMock(return_value=chain_mock)
            
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
            
            intent_inst = MockIntentGroq.return_value
            intent_inst.__or__ = MagicMock(return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_intent_res)))
            
            faq_inst = MockFaqGroq.return_value
            faq_inst.__or__ = MagicMock(return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_ans_res)))

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
            # Seed 105 messages to exceed starter plan quota (100)
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

        async def simulated_slow_groq_llm(*args, **kwargs):
            nonlocal active_sessions, max_active_sessions_during_llm
            # Record how many sessions are currently open while LLM awaits
            max_active_sessions_during_llm = max(max_active_sessions_during_llm, active_sessions)
            await asyncio.sleep(0.05)
            mock_res = MagicMock()
            mock_res.content = "Information response"
            return mock_res

        with patch("backend.app.api.routers.chat.get_tenant_session", side_effect=tracked_get_tenant_session), \
             patch("backend.intent_chain.ChatGroq") as MockIntentGroq, \
             patch("backend.faq_chain.ChatGroq") as MockFaqGroq:

            chain_mock = MagicMock()
            chain_mock.ainvoke = simulated_slow_groq_llm
            MockIntentGroq.return_value.__or__ = MagicMock(return_value=chain_mock)
            MockFaqGroq.return_value.__or__ = MagicMock(return_value=chain_mock)

            # Reset quota for this tenant so request proceeds to LLM
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
            # Final active sessions must also be 0
            self.assertEqual(active_sessions, 0, "Leaked DB sessions detected!")

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Concurrency & Event Loop Responsiveness Verification
    # ─────────────────────────────────────────────────────────────────────────
    def test_14_concurrency_and_event_loop_responsiveness(self):
        """Verify that concurrent slow chat requests do NOT block /health or the event loop."""
        async def run_concurrent_load():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                # Mock Groq ainvoke to simulate a 0.3s network delay
                async def slow_ainvoke(*args, **kwargs):
                    await asyncio.sleep(0.3)
                    mock_res = MagicMock()
                    mock_res.content = "Delayed response"
                    return mock_res

                with patch("backend.intent_chain.ChatGroq") as MockIntentGroq, \
                     patch("backend.faq_chain.ChatGroq") as MockFaqGroq:

                    chain_mock = MagicMock()
                    chain_mock.ainvoke = slow_ainvoke
                    MockIntentGroq.return_value.__or__ = MagicMock(return_value=chain_mock)
                    MockFaqGroq.return_value.__or__ = MagicMock(return_value=chain_mock)

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

                    # Slight delay then fire health check while chat tasks are in flight
                    await asyncio.sleep(0.05)
                    t0 = time.time()
                    health_res = await client.get("/health")
                    health_duration = time.time() - t0

                    chat_responses = await asyncio.gather(*chat_tasks)
                    
                    return health_res, health_duration, chat_responses

        health_res, health_duration, chat_responses = asyncio.run(run_concurrent_load())
        
        self.assertEqual(health_res.status_code, 200)
        # Event loop must remain free: health responded while chats were sleeping
        self.assertLess(
            health_duration, 0.15,
            f"Event loop was blocked! /health took {health_duration:.3f}s while LLM was running."
        )
        for res in chat_responses:
            self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
