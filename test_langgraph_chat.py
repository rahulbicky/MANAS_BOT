"""
test_langgraph_chat.py
-----------------------
Comprehensive test suite for ManasBot Phase 1 & Phase 2:
  1. LangGraph StateGraph compilation and routing
  2. Multi-turn conversation memory retrieval, decryption, and prompt injection
  3. Lead capture workflow: pure contact submission vs combined lead + inquiry
  4. Decoupled 3-phase execution and zero DB connection retention during Phase B
  5. FAQ and semantic RAG retrieval nodes
  6. Groq LLM primary -> fallback model switching
  7. Tenant and Chat repositories with atomic persistence
  8. Centralized exception handling
"""
import os
import sys
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient
from langchain_core.runnables import RunnableLambda

import backend.database as db_mod
from backend.database import (
    Base,
    CentralBase,
    CentralTenant,
    BusinessProfile,
    FAQ,
    ChatLog,
    Lead,
    ChatFeedback,
    Plan,
    DocumentChunk,
    KnowledgeDocument,
)
from backend.encryption import encrypt_text, decrypt_text
from backend.rag.graph import (
    ConversationState,
    build_chat_graph,
    compiled_chat_graph,
    run_chat_graph,
    guard_and_intent_node,
    router_lead_or_inquiry,
    lead_capture_node,
    faq_matcher_node,
    rag_retriever_node,
    answer_generation_node,
    citation_formatter_node,
)
from backend.app.repositories.chat_repo import ChatRepository
from backend.app.repositories.tenant_repo import TenantRepository
from backend.app.services.chat_service import ChatService
from backend.app.schemas.models import ChatRequest, ChatResponse
from backend.app.main import app


class LangGraphChatTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Configure isolated SQLite test engine
        cls.test_db_url = "sqlite:///test_langgraph_dev.db"
        cls.engine = create_engine(cls.test_db_url, connect_args={"check_same_thread": False})

        # Monkeypatch central and tenant engine/sessionmaker
        db_mod._central_engine = cls.engine
        db_mod._CentralSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

        # Create all tables
        Base.metadata.drop_all(bind=cls.engine)
        CentralBase.metadata.drop_all(bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        CentralBase.metadata.create_all(bind=cls.engine)

        session = db_mod._get_central_session()
        try:
            # Seed test plan
            plan = Plan(
                id="plan_enterprise",
                name="Enterprise",
                price_inr=9999,
                messages_per_month=5000,
                docs_limit=50,
                faqs_limit=100,
                export_enabled=True,
                languages="all",
            )
            session.add(plan)

            # Seed test tenant
            cls.tenant_id = "tenant_test_langgraph_001"
            cls.api_key = "test_key_langgraph_999"
            tenant = CentralTenant(
                id=cls.tenant_id,
                name="LangGraph Test Corp",
                username="langgraph_admin",
                api_key=cls.api_key,
                current_plan_id="plan_enterprise",
                is_active=True,
                notification_email="leads@langgraph-test.com",
            )
            session.add(tenant)

            # Seed Business Profile
            profile = BusinessProfile(
                tenant_id=cls.tenant_id,
                company_name="LangGraph Test Corp",
                industry="Artificial Intelligence",
                business_description="Enterprise multi-tenant conversational AI solutions.",
                chatbot_system_prompt="You are an expert AI assistant for LangGraph Test Corp.",
            )
            session.add(profile)

            # Seed active FAQs
            faq1 = FAQ(
                tenant_id=cls.tenant_id,
                question="What is LangGraph Test Corp?",
                answer="We provide state-of-the-art conversational graph AI pipelines.",
                intent="information",
                is_active=True,
            )
            faq2 = FAQ(
                tenant_id=cls.tenant_id,
                question="How much does Enterprise cost?",
                answer="Enterprise plans start at 9,999 INR per month with unlimited custom graphs.",
                intent="pricing",
                is_active=True,
            )
            session.add_all([faq1, faq2])

            session.commit()
        finally:
            session.close()

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists("test_langgraph_dev.db"):
                os.remove("test_langgraph_dev.db")
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # 1. StateGraph Architecture & Compilation
    # ─────────────────────────────────────────────────────────────────────────
    def test_01_graph_compilation_and_nodes(self):
        """Verify StateGraph compiles successfully with checkpointer and expected nodes."""
        graph = build_chat_graph()
        self.assertIsNotNone(graph)
        # Graph nodes verification
        node_keys = graph.nodes.keys()
        for expected_node in [
            "guard_and_intent_node",
            "lead_capture_node",
            "faq_matcher_node",
            "rag_retriever_node",
            "answer_generation_node",
            "citation_formatter_node",
        ]:
            self.assertIn(expected_node, node_keys)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Pure Lead Capture vs Combined Lead + Inquiry
    # ─────────────────────────────────────────────────────────────────────────
    def test_02_pure_lead_capture_workflow(self):
        """Pure contact info submission routes directly to lead_capture_node without LLM inference."""
        state: ConversationState = {
            "question": "Rahul Sharma 9123456789 rahul@example.com please contact me regarding Enterprise",
            "session_id": "sess_lead_pure_01",
            "tenant_id": self.tenant_id,
            "company": "LangGraph Test Corp",
            "industry": "Artificial Intelligence",
        }

        # Run guard and intent node
        result = asyncio.run(guard_and_intent_node(state))
        self.assertTrue(result["is_pure_lead"])
        self.assertEqual(result["intent"], "lead_captured")
        self.assertIsNotNone(result["lead_data"])
        self.assertEqual(result["lead_data"]["phone"], "9123456789")
        self.assertEqual(result["lead_data"]["email"], "rahul@example.com")

        # Test router
        merged = {**state, **result}
        next_node = router_lead_or_inquiry(merged)
        self.assertEqual(next_node, "lead_capture_node")

        # Test lead capture node output
        lead_output = asyncio.run(lead_capture_node(merged))
        self.assertIn("support team has received your details", lead_output["answer"])
        self.assertTrue(lead_output["is_resolved"])

    def test_03_combined_lead_capture_and_inquiry_workflow(self):
        """User providing contact info AND an inquiry must NOT terminate early;

        it captures the lead AND proceeds to FAQ/RAG retrieval and answers the question.
        """
        state: ConversationState = {
            "question": "Rahul Sharma 9123456789 rahul@example.com what is your pricing policy?",
            "session_id": "sess_lead_comb_01",
            "tenant_id": self.tenant_id,
            "company": "LangGraph Test Corp",
            "industry": "Artificial Intelligence",
            "intent": "pricing",
            "faqs": [
                {"intent": "pricing", "question": "What is pricing?", "answer": "Plans start at 9,999 INR."}
            ],
        }

        # Guard and intent node
        result = asyncio.run(guard_and_intent_node(state))
        # Must detect contact info
        self.assertIsNotNone(result["lead_data"])
        self.assertEqual(result["lead_data"]["phone"], "9123456789")
        # Must NOT be marked as pure lead since inquiry is present
        self.assertFalse(result["is_pure_lead"])

        # Router must direct to knowledge processing (faq_matcher_node)
        merged = {**state, **result}
        next_node = router_lead_or_inquiry(merged)
        self.assertEqual(next_node, "faq_matcher_node")

        # Answer generation must answer inquiry and acknowledge lead capture
        with patch("backend.rag.graph.ChatGroq") as MockGroq:
            mock_llm_instance = MagicMock()
            mock_llm_instance.ainvoke = AsyncMock(
                return_value=MagicMock(content="Our Enterprise plan costs 9,999 INR per month.")
            )
            MockGroq.return_value = mock_llm_instance

            ans_output = asyncio.run(answer_generation_node(merged))
            # Must contain lead acknowledgement prefix
            self.assertIn("support team has received your contact details", ans_output["answer"])
            # Must also contain the actual answer to the inquiry
            self.assertIn("9,999 INR", ans_output["answer"])
            self.assertTrue(ans_output["is_resolved"])

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Multi-Turn Conversation Memory (Retrieval & Decryption)
    # ─────────────────────────────────────────────────────────────────────────
    def test_04_multiturn_memory_retrieval_and_decryption(self):
        """Test that ChatRepository retrieves and decrypts the last N turns chronologically."""
        session_id = "sess_history_test_01"
        session = db_mod._get_central_session()
        try:
            # Seed 3 sequential turns with encrypted question & answer
            for i in range(1, 4):
                turn = ChatLog(
                    tenant_id=self.tenant_id,
                    session_id=session_id,
                    encrypted_question=encrypt_text(f"Question turn {i}"),
                    encrypted_answer=encrypt_text(f"Answer turn {i}"),
                    detected_intent="information",
                    is_resolved=True,
                    created_at=db_mod.utc_now() + db_mod.datetime.timedelta(minutes=i),
                )
                session.add(turn)
            session.commit()
        finally:
            session.close()

        # Retrieve last 2 turns
        history = ChatRepository.get_recent_session_history(self.tenant_id, session_id, limit=2)
        self.assertEqual(len(history), 2)
        # Chronological ordering check: turn 2 comes before turn 3
        self.assertEqual(history[0]["question"], "Question turn 2")
        self.assertEqual(history[0]["answer"], "Answer turn 2")
        self.assertEqual(history[1]["question"], "Question turn 3")
        self.assertEqual(history[1]["answer"], "Answer turn 3")

    def test_05_multiturn_memory_injected_into_prompt(self):
        """Verify chat_history turns are structured into messages in answer_generation_node."""
        chat_history = [
            {"question": "Do you offer graph databases?", "answer": "Yes, we integrate with graph DBs."},
            {"question": "What is the setup time?", "answer": "Setup takes 5 minutes."},
        ]
        state: ConversationState = {
            "question": "Can I upgrade later?",
            "session_id": "sess_history_inject_01",
            "tenant_id": self.tenant_id,
            "company": "LangGraph Test Corp",
            "industry": "Artificial Intelligence",
            "chat_history": chat_history,
            "faq_context": "",
            "doc_context": "",
        }

        captured_messages = []

        async def capture_messages(msgs):
            nonlocal captured_messages
            captured_messages = msgs
            return MagicMock(content="Yes, you can upgrade at any time.")

        with patch("backend.rag.graph.ChatGroq") as MockGroq:
            mock_inst = MagicMock()
            mock_inst.ainvoke = capture_messages
            MockGroq.return_value = mock_inst

            ans_output = asyncio.run(answer_generation_node(state))
            self.assertEqual(ans_output["answer"], "Yes, you can upgrade at any time.")

            # Verify that captured messages include previous human and AI turns
            contents = [m.content for m in captured_messages]
            self.assertTrue(any("Do you offer graph databases?" in c for c in contents))
            self.assertTrue(any("Setup takes 5 minutes." in c for c in contents))
            self.assertEqual(captured_messages[-1].content, "Can I upgrade later?")

    # ─────────────────────────────────────────────────────────────────────────
    # 4. FAQ Matcher & Semantic RAG Retrieval Nodes
    # ─────────────────────────────────────────────────────────────────────────
    def test_06_faq_matcher_node(self):
        """Verify faq_matcher_node formats relevant FAQ context matching intent."""
        state: ConversationState = {
            "intent": "pricing",
            "faqs": [
                {"intent": "information", "question": "What is AI?", "answer": "Artificial Intelligence."},
                {"intent": "pricing", "question": "What is pricing?", "answer": "Starts at 9,999 INR."},
            ],
        }
        output = asyncio.run(faq_matcher_node(state))
        self.assertIn("Q: What is pricing?", output["faq_context"])
        self.assertIn("A: Starts at 9,999 INR.", output["faq_context"])
        self.assertNotIn("What is AI?", output["faq_context"])

    def test_07_rag_retriever_node_and_sources(self):
        """Verify rag_retriever_node returns structured chunks and formatted citations."""
        mock_chunk = MagicMock(
            chunk_id="chunk_test_01",
            document_id="doc_test_01",
            filename="pricing_guide.pdf",
            chunk_text="Enterprise pricing offers 99.9% uptime SLA.",
            similarity_score=0.88,
        )

        with patch("backend.rag.graph.aretrieve_relevant_chunks", new=AsyncMock(return_value=[mock_chunk])):
            state: ConversationState = {
                "tenant_id": self.tenant_id,
                "question": "What is the SLA for enterprise?",
            }
            output = asyncio.run(rag_retriever_node(state))
            self.assertEqual(len(output["sources"]), 1)
            self.assertEqual(output["sources"][0]["filename"], "pricing_guide.pdf")
            self.assertEqual(output["sources"][0]["relevance_score"], 0.88)
            self.assertIn("pricing_guide.pdf", output["doc_context"])

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Groq LLM Fallback Mechanism
    # ─────────────────────────────────────────────────────────────────────────
    def test_08_groq_model_fallback_execution(self):
        """Verify that when primary model fails, secondary fallback model is called."""
        call_count = 0
        models_invoked = []

        def mock_groq_factory(model, **kwargs):
            nonlocal call_count, models_invoked
            models_invoked.append(model)
            inst = MagicMock()
            if model == "qwen/qwen3.8-27b":
                # Primary model fails
                inst.ainvoke = AsyncMock(side_effect=RuntimeError("Primary model quota exceeded"))
            else:
                # Fallback model succeeds
                inst.ainvoke = AsyncMock(return_value=MagicMock(content="Fallback answer from secondary model."))
            return inst

        with patch("backend.rag.graph.ChatGroq", side_effect=mock_groq_factory):
            state: ConversationState = {
                "question": "Explain your security model",
                "tenant_id": self.tenant_id,
                "company": "LangGraph Test Corp",
                "industry": "Artificial Intelligence",
                "chat_history": [],
            }
            output = asyncio.run(answer_generation_node(state))
            self.assertEqual(output["answer"], "Fallback answer from secondary model.")
            self.assertIn("qwen/qwen3.8-27b", models_invoked)
            self.assertIn("openai/gpt-oss-20b", models_invoked)

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Zero Database Connections Held in Phase B
    # ─────────────────────────────────────────────────────────────────────────
    def test_09_zero_db_connections_in_phase_b(self):
        """Verify zero database sessions are held open during LangGraph AI inference."""
        active_sessions = 0
        max_active_during_inference = 0
        original_get_tenant_session = db_mod.get_tenant_session

        def tracked_get_tenant_session(t_id):
            nonlocal active_sessions
            sess = original_get_tenant_session(t_id)
            active_sessions += 1
            orig_close = sess.close

            def tracked_close():
                nonlocal active_sessions
                active_sessions -= 1
                return orig_close()

            sess.close = tracked_close
            return sess

        async def simulated_langgraph_call(x):
            nonlocal active_sessions, max_active_during_inference
            max_active_during_inference = max(max_active_during_inference, active_sessions)
            await asyncio.sleep(0.03)
            return MagicMock(content="Zero connection verified.")

        with patch("backend.app.api.routers.chat.get_tenant_session", side_effect=tracked_get_tenant_session), \
             patch("backend.intent_chain.ChatGroq") as MockIntentGroq, \
             patch("backend.faq_chain.ChatGroq") as MockFaqGroq, \
             patch("backend.rag.graph.ChatGroq") as MockGraphGroq:

            MockIntentGroq.return_value = RunnableLambda(simulated_langgraph_call)
            MockFaqGroq.return_value = RunnableLambda(simulated_langgraph_call)
            MockGraphGroq.return_value = RunnableLambda(simulated_langgraph_call)

            resp = self.client.post(
                "/chat",
                json={
                    "question": "What is LangGraph Test Corp?",
                    "session_id": "sess_zero_conn_langgraph",
                    "tenant_id": self.tenant_id,
                    "language": "en",
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                max_active_during_inference, 0,
                f"Expected 0 active DB connections during LLM, got {max_active_during_inference}"
            )
            self.assertEqual(active_sessions, 0, "DB connection leak detected!")

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Tenant & Chat Repositories Isolation & Persistence
    # ─────────────────────────────────────────────────────────────────────────
    def test_10_tenant_and_chat_repositories(self):
        """Verify TenantRepository read context and ChatRepository save_chat_turn."""
        # Test read context
        context = TenantRepository.get_chat_read_context(self.tenant_id)
        self.assertEqual(context["company"], "LangGraph Test Corp")
        self.assertEqual(context["industry"], "Artificial Intelligence")
        self.assertGreaterEqual(len(context["faqs"]), 2)

        # Test atomic save turn with lead data
        lead_data = {
            "name": "Jane Doe",
            "phone": "9876543210",
            "email": "jane@example.com",
            "raw_message": "Jane Doe 9876543210 jane@example.com test lead",
            "is_notified": False,
        }
        log_id = ChatRepository.save_chat_turn(
            tenant_id=self.tenant_id,
            session_id="sess_atomic_repo_test",
            encrypted_q=encrypt_text("Hi"),
            encrypted_a=encrypt_text("Hello"),
            intent="lead_captured",
            page_url="https://test.com",
            language="en",
            is_resolved=True,
            response_time_ms=120,
            user_ip="127.0.0.1",
            lead_data=lead_data,
        )
        self.assertIsNotNone(log_id)

        # Verify Lead table entry
        session = db_mod._get_central_session()
        try:
            saved_lead = session.query(Lead).filter(Lead.session_id == "sess_atomic_repo_test").first()
            self.assertIsNotNone(saved_lead)
            self.assertEqual(saved_lead.name, "Jane Doe")
            self.assertEqual(saved_lead.phone, "9876543210")
            self.assertEqual(saved_lead.email, "jane@example.com")
        finally:
            session.close()

    # ─────────────────────────────────────────────────────────────────────────
    # 8. End-to-End Chat API Backward Compatibility
    # ─────────────────────────────────────────────────────────────────────────
    def test_11_e2e_chat_api_contract_and_sources(self):
        """Verify end-to-end POST /chat returns exact ChatResponse contract with sources."""
        with patch("backend.app.api.routers.chat.adetect_intent", new=AsyncMock(return_value="pricing")), \
             patch("backend.app.api.routers.chat.aget_answer", new=AsyncMock(return_value="Enterprise starts at 9,999 INR [Source: enterprise_pricing.pdf]")):

            resp = self.client.post(
                "/chat",
                json={
                    "question": "What is the price of Enterprise?",
                    "session_id": "sess_e2e_contract_01",
                    "tenant_id": self.tenant_id,
                    "language": "en",
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("answer", data)
            self.assertIn("intent", data)
            self.assertIn("resolved", data)
            self.assertIn("sources", data)
            self.assertEqual(data["intent"], "pricing")
            self.assertIn("9,999 INR", data["answer"])

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Centralized Exception Handling
    # ─────────────────────────────────────────────────────────────────────────
    def test_12_centralized_exception_handling(self):
        """Verify centralized validation 422 error handling produces clean JSON."""
        # POST with missing required fields
        resp = self.client.post("/chat", json={})
        self.assertEqual(resp.status_code, 422)
        data = resp.json()
        self.assertIn("detail", data)


if __name__ == "__main__":
    unittest.main()
