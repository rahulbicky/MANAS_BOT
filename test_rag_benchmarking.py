"""
test_rag_benchmarking.py
------------------------
Automated evaluation test suite verifying RAG metrics and Agentic AI tools:
  - Hit Rate @ K (Recall @ K)
  - Mean Reciprocal Rank (MRR @ K)
  - Context Precision
  - Latency profiling
  - Deduplication & Reranker validation
  - Agentic AI Tool execution and tenant isolation
"""
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["CENTRAL_DB_URL"] = "sqlite:///./test_benchmarking.db"
os.environ["DATABASE_URL"] = "sqlite:///./test_benchmarking.db"
os.environ["DISABLE_FAST_EMBED"] = "true"
os.environ["DISABLE_GROQ_CALLS"] = "true"

from backend.rag.retriever import (
    RetrievedChunk,
    deduplicate_chunks,
    rerank_chunks,
    is_cross_lingual_or_non_ascii,
)
from backend.rag.evaluation import (
    BenchmarkItem,
    evaluate_retrieval,
)
from backend.rag.tools import (
    execute_knowledge_retrieval,
    execute_business_profile,
    execute_lead_capture,
    execute_support_incident,
    get_tenant_agent_tools,
)


class TestRagBenchmarking(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.sample_candidate_chunks = [
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                filename="pricing_policy.pdf",
                chunk_text="The standard enterprise plan costs $499 per month with unlimited seats and 24/7 dedicated support.",
                chunk_index=0,
                similarity_score=0.88,
            ),
            RetrievedChunk(
                chunk_id="c2",
                document_id="d1",
                filename="pricing_policy.pdf",
                chunk_text="The standard enterprise plan costs $499 per month with unlimited seats and 24/7 dedicated support.",  # Duplicate
                chunk_index=1,
                similarity_score=0.87,
            ),
            RetrievedChunk(
                chunk_id="c3",
                document_id="d2",
                filename="refund_policy.docx",
                chunk_text="Full refund requests are processed within 14 calendar days from the initial purchase date.",
                chunk_index=0,
                similarity_score=0.81,
            ),
            RetrievedChunk(
                chunk_id="c4",
                document_id="d3",
                filename="faq.txt",
                chunk_text="Our office headquarters is located in San Francisco, California. Hours are 9am to 6pm PST.",
                chunk_index=0,
                similarity_score=0.74,
            ),
        ]

    # ── RAG Metric Harness Tests ────────────────────────────────────────────

    async def test_01_evaluate_retrieval_metrics(self):
        dataset = [
            BenchmarkItem(
                query="How much is the enterprise plan?",
                relevant_keywords=["$499", "enterprise plan"],
                expected_doc_names=["pricing_policy.pdf"],
            ),
            BenchmarkItem(
                query="What is the refund time window?",
                relevant_keywords=["14 calendar days", "refund"],
                expected_doc_names=["refund_policy.docx"],
            ),
            BenchmarkItem(
                query="Something completely unrelated to this business",
                relevant_keywords=["quantum physics", "astronomy"],
            ),
        ]

        mock_retrieved_results = [
            [
                RetrievedChunk(
                    chunk_id="c1",
                    document_id="d1",
                    filename="pricing_policy.pdf",
                    chunk_text="The enterprise plan costs $499 per month.",
                    chunk_index=0,
                    similarity_score=0.92,
                )
            ],
            [
                RetrievedChunk(
                    chunk_id="c3",
                    document_id="d2",
                    filename="refund_policy.docx",
                    chunk_text="Refund requests are accepted within 14 calendar days.",
                    chunk_index=0,
                    similarity_score=0.89,
                )
            ],
            [],  # No relevant chunks retrieved
        ]

        with patch("backend.rag.evaluation.aretrieve_relevant_chunks", side_effect=mock_retrieved_results):
            metrics = await evaluate_retrieval(dataset=dataset, tenant_id="tenant_eval", top_k=3)

        self.assertEqual(metrics.total_queries, 3)
        self.assertAlmostEqual(metrics.hit_rate_at_k, 2 / 3, places=2)
        self.assertAlmostEqual(metrics.mrr_at_k, 2 / 3, places=2)
        self.assertAlmostEqual(metrics.context_precision_at_k, 2 / 3, places=2)
        self.assertGreaterEqual(metrics.avg_latency_ms, 0.0)

    # ── Deduplication & Reranking Benchmarks ──────────────────────────────────

    def test_02_deduplicate_chunks_removes_identical(self):
        deduped = deduplicate_chunks(self.sample_candidate_chunks, threshold=0.90)
        self.assertEqual(len(deduped), 3)
        self.assertEqual(deduped[0].chunk_id, "c1")
        chunk_ids = [c.chunk_id for c in deduped]
        self.assertNotIn("c2", chunk_ids)
        self.assertIn("c3", chunk_ids)
        self.assertIn("c4", chunk_ids)

    def test_03_rerank_chunks_promotes_exact_query_matches(self):
        reranked = rerank_chunks("14 calendar days refund", self.sample_candidate_chunks, top_n=2)
        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0].chunk_id, "c3")

    def test_04_cross_lingual_detection(self):
        self.assertTrue(is_cross_lingual_or_non_ascii("नमस्ते, मुझे सहायता चाहिए"))
        self.assertTrue(is_cross_lingual_or_non_ascii("こんにちは"))
        self.assertFalse(is_cross_lingual_or_non_ascii("What is your refund policy?"))

    # ── Agentic AI Tools Tests ──────────────────────────────────────────────

    async def test_05_agent_tool_knowledge_retrieval(self):
        with patch("backend.rag.tools.aretrieve_relevant_chunks", new_callable=AsyncMock) as mock_retriever:
            mock_retriever.return_value = [
                RetrievedChunk(
                    chunk_id="ch_1",
                    document_id="doc_1",
                    filename="manual.pdf",
                    chunk_text="Press power button to restart.",
                    chunk_index=0,
                    similarity_score=0.95,
                )
            ]
            result = await execute_knowledge_retrieval(tenant_id="t1", query="how to restart?")
            self.assertTrue(result.success)
            self.assertEqual(result.tool_name, "KnowledgeRetrievalTool")
            self.assertEqual(len(result.data["chunks"]), 1)
            self.assertEqual(result.data["chunks"][0]["filename"], "manual.pdf")

    async def test_06_agent_tool_business_profile(self):
        with patch("backend.rag.tools.get_tenant_session") as mock_session_factory:
            mock_session = mock_session_factory.return_value
            mock_profile = type("BP", (), {
                "company_name": "Acme Tools",
                "industry": "Hardware",
                "business_description": "We sell tools",
                "website": "https://acme.example.com",
                "support_email": "support@acme.example.com",
                "phone": "+1-555-0199",
                "business_hours": "9am-5pm",
                "address_street": "123 Main St",
                "city": "Austin",
                "state": "TX",
                "zip_code": "78701",
            })()
            mock_session.query.return_value.filter_by.return_value.first.return_value = mock_profile

            result = await execute_business_profile(tenant_id="t_acme")
            self.assertTrue(result.success)
            self.assertEqual(result.data["company_name"], "Acme Tools")
            self.assertEqual(result.data["industry"], "Hardware")

    async def test_07_agent_tool_lead_capture(self):
        with patch("backend.rag.tools.get_tenant_session") as mock_session_factory:
            mock_session = mock_session_factory.return_value
            result = await execute_lead_capture(
                tenant_id="t_lead",
                name="Alice Smith",
                email="alice@example.com",
                phone="+1234567890",
                raw_message="Interested in enterprise tier",
            )
            self.assertTrue(result.success)
            self.assertEqual(result.data["name"], "Alice Smith")
            self.assertTrue(result.data["created"])
            self.assertTrue(mock_session.commit.called)

    async def test_08_agent_tool_support_incident(self):
        with patch("backend.rag.tools.get_tenant_session") as mock_session_factory:
            mock_session = mock_session_factory.return_value
            result = await execute_support_incident(
                tenant_id="t_incident",
                title="Service Latency Spike",
                description="High latency on API endpoints",
                severity="high",
            )
            self.assertTrue(result.success)
            self.assertEqual(result.data["title"], "Service Latency Spike")
            self.assertEqual(result.data["severity"], "high")
            self.assertTrue(mock_session.commit.called)

    def test_09_get_tenant_agent_tools_structure(self):
        tools = get_tenant_agent_tools(tenant_id="tenant_sandbox_99")
        self.assertEqual(len(tools), 4)
        tool_names = [t.name for t in tools]
        self.assertIn("knowledge_retrieval", tool_names)
        self.assertIn("business_profile", tool_names)
        self.assertIn("lead_capture", tool_names)
        self.assertIn("support_incident", tool_names)


if __name__ == "__main__":
    unittest.main()
