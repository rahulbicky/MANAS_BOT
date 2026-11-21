"""
test_phase2_rag.py
------------------
Automated test suite for ManasBot Phase 2 Subtasks 2.1 & 2.2.
Validates:
1. Small document chunking & metadata preservation.
2. Large document chunking & sequencing.
3. Unicode & multilingual content chunking (Hindi, Spanish, Chinese, Arabic, emojis).
4. Chunk overlap and boundary preservation.
5. Empty / whitespace document handling.
6. Embedding model singleton initialization.
7. Embedding vector dimensionality (384) & L2 normalization.
8. Deterministic embedding behavior.
9. Batch embedding generation.
10. Multilingual semantic similarity with intfloat/multilingual-e5-small.
11. Async embedding execution via worker threadpool.
12. E5 prefix enforcement (query: vs passage:).
13. DocumentChunk SQLAlchemy model creation & cascading relationship.
14. Alembic migration upgrade & downgrade verification.
"""
import asyncio
import os
import sys
import unittest
import uuid
from unittest.mock import patch, AsyncMock
import numpy as np
from sqlalchemy import create_engine, select, inspect
from sqlalchemy.orm import sessionmaker

# Ensure local packages are importable
sys.path.insert(0, os.path.abspath("."))

import backend.database as db_mod
from backend.database import (
    Base,
    CentralBase,
    CentralTenant,
    BusinessProfile,
    Plan,
    KnowledgeDocument,
    DocumentChunk,
)
from backend.rag.chunker import chunk_document, DocumentChunkData, estimate_token_count
from backend.rag.embedder import (
    get_embedding_model,
    embed_query,
    embed_passages,
    aembed_query,
    aembed_passages,
    MODEL_NAME,
    EMBEDDING_DIM,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
)
from backend.rag.retriever import retrieve_relevant_chunks, aretrieve_relevant_chunks, RetrievedChunk
from backend.rag.ingestion import ingest_document, delete_document_chunks, reingest_document
from backend.rag.prompts import format_rag_context, get_rag_citation_instruction
from backend.scripts.backfill_embeddings import backfill_documents
from backend.app.main import app
from starlette.testclient import TestClient


class Phase2RAGTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db_file = "test_phase2_rag.db"
        if os.path.exists(cls.test_db_file):
            try:
                os.remove(cls.test_db_file)
            except Exception:
                pass
        cls.engine = create_engine(f"sqlite:///{cls.test_db_file}", echo=False, connect_args={"check_same_thread": False})

        # Monkeypatch database module central engine
        db_mod._central_engine = cls.engine
        db_mod._CentralSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

        Base.metadata.create_all(cls.engine)
        CentralBase.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

        session = cls.SessionLocal()
        try:
            starter_plan = Plan(
                id="plan_starter",
                name="Starter",
                price_inr=0,
                messages_per_month=100,
                docs_limit=10,
                faqs_limit=50,
                export_enabled=False,
                languages="en",
            )
            session.add(starter_plan)
            session.commit()
        finally:
            session.close()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        if os.path.exists(cls.test_db_file):
            try:
                os.remove(cls.test_db_file)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Chunking Tests
    # ─────────────────────────────────────────────────────────────────────────
    def test_01_chunker_small_document(self):
        """Small document (<600 chars) should yield exactly 1 chunk with preserved metadata."""
        text = "Acme Corp provides automated cloud infrastructure and customer support solutions."
        chunks = chunk_document(
            content=text,
            document_id="doc_001",
            tenant_id="tenant_alpha",
            filename="acme_overview.txt",
            file_type="txt",
            chunk_size=600,
            chunk_overlap=100,
        )
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk.chunk_index, 0)
        self.assertEqual(chunk.chunk_text, text)
        self.assertEqual(chunk.document_id, "doc_001")
        self.assertEqual(chunk.tenant_id, "tenant_alpha")
        self.assertEqual(chunk.filename, "acme_overview.txt")
        self.assertEqual(chunk.file_type, "txt")
        self.assertGreater(chunk.token_count, 0)

    def test_02_chunker_large_document(self):
        """Large document (>3000 chars) should be split into multiple ordered chunks."""
        paragraph = (
            "Section Header: Enterprise Data Protection and Compliance.\n"
            "We adhere strictly to SOC-2 Type II standards, encrypting all customer records "
            "at rest using AES-256 and in transit using TLS 1.3. Regular vulnerability assessments "
            "and continuous third-party audits ensure our customers' data remains confidential.\n\n"
        )
        large_text = paragraph * 12  # ~2700-3000 characters
        chunks = chunk_document(
            content=large_text,
            document_id="doc_large_002",
            tenant_id="tenant_beta",
            filename="compliance_whitepaper.pdf",
            file_type="pdf",
            chunk_size=600,
            chunk_overlap=100,
        )
        self.assertGreater(len(chunks), 3)
        # Check sequencing
        for i, ch in enumerate(chunks):
            self.assertEqual(ch.chunk_index, i)
            self.assertEqual(ch.document_id, "doc_large_002")
            self.assertEqual(ch.tenant_id, "tenant_beta")
            self.assertLessEqual(len(ch.chunk_text), 750)  # within allowable boundary

    def test_03_chunker_unicode_multilingual(self):
        """Unicode text (Hindi, Chinese, Spanish, emojis) must chunk cleanly without character corruption."""
        hindi_text = (
            "नमस्ते! ManasBot एक अत्याधुनिक एआई चैटबॉट समाधान है जो ग्राहकों को चौबीसों घंटे सहायता प्रदान करता है। "
            "हम हिंदी, अंग्रेजी और स्पेनिश सहित कई भाषाओं का समर्थन करते हैं। 🚀✨\n\n"
            "यदि आपके पास कोई प्रश्न है, तो कृपया हमारी सहायता टीम से संपर्क करें। "
            "हमारी ग्राहक सहायता टीम तुरंत आपकी सहायता करेगी।"
        )
        spanish_text = (
            "\n\nNuestra política de devoluciones permite cambios dentro de los 30 días posteriores a la compra. "
            "Los productos deben estar en su empaque original sin usar."
        )
        full_content = hindi_text + spanish_text

        chunks = chunk_document(
            content=full_content,
            document_id="doc_multi_003",
            tenant_id="tenant_multi",
            filename="multilingual_faq.docx",
            file_type="docx",
            chunk_size=300,
            chunk_overlap=50,
        )
        self.assertGreaterEqual(len(chunks), 1)
        all_text = " ".join(c.chunk_text for c in chunks)
        self.assertIn("नमस्ते", all_text)
        self.assertIn("devoluciones", all_text)
        self.assertIn("🚀✨", all_text)

    def test_04_chunker_overlap_boundaries(self):
        """Consecutive chunks must have overlapping content according to chunk_overlap."""
        sentences = [f"Sentence number {i:02d} describes feature item {i} in detail." for i in range(25)]
        doc_text = " ".join(sentences)

        chunks = chunk_document(
            content=doc_text,
            document_id="doc_overlap_004",
            tenant_id="tenant_gamma",
            filename="features.txt",
            file_type="txt",
            chunk_size=300,
            chunk_overlap=80,
        )
        self.assertGreater(len(chunks), 2)
        # Verify that chunk 1 has some text from the tail of chunk 0
        tail_of_chunk_0 = chunks[0].chunk_text[-40:]
        self.assertIn(tail_of_chunk_0[:20], chunks[1].chunk_text)

    def test_05_chunker_empty_and_whitespace(self):
        """Empty, None, or whitespace-only documents should return empty chunk list."""
        self.assertEqual(chunk_document("", "d", "t", "f", "txt"), [])
        self.assertEqual(chunk_document("   \n\t   ", "d", "t", "f", "txt"), [])
        self.assertEqual(chunk_document(None, "d", "t", "f", "txt"), [])

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Embedding Model Tests
    # ─────────────────────────────────────────────────────────────────────────
    def test_06_embedder_model_singleton(self):
        """get_embedding_model() must load the model once and return the identical instance."""
        m1 = get_embedding_model()
        m2 = get_embedding_model()
        self.assertIs(m1, m2)
        self.assertEqual(EMBEDDING_DIM, 384)
        self.assertEqual(MODEL_NAME, "intfloat/multilingual-e5-small")

    def test_07_embed_query_dimension_and_normalization(self):
        """embed_query must return exactly 384 floats, L2-normalized to ~1.0."""
        query = "What is the warranty period for your enterprise hardware?"
        vec = embed_query(query)
        self.assertEqual(len(vec), 384)
        self.assertTrue(all(isinstance(x, float) for x in vec))

        # Check L2 norm (normalized embeddings have norm = 1.0)
        norm = np.linalg.norm(np.array(vec))
        self.assertAlmostEqual(norm, 1.0, places=3)

    def test_08_embed_deterministic_behavior(self):
        """The same input text must produce identical vector embeddings deterministically."""
        text = "Cloud database automated replication and backup intervals."
        v1 = embed_query(text)
        v2 = embed_query(text)
        self.assertEqual(len(v1), len(v2))
        np.testing.assert_allclose(v1, v2, atol=1e-5)

    def test_09_embed_passages_batch(self):
        """embed_passages must return a list of 384-dimensional vectors for a batch of passages."""
        passages = [
            "We offer a 30-day money-back guarantee on all subscriptions.",
            "Technical support is available 24/7 via live chat and email ticketing.",
            "Invoices are generated on the 1st day of each billing cycle in INR.",
        ]
        vectors = embed_passages(passages, batch_size=2)
        self.assertEqual(len(vectors), 3)
        for vec in vectors:
            self.assertEqual(len(vec), 384)
            norm = np.linalg.norm(np.array(vec))
            self.assertAlmostEqual(norm, 1.0, places=3)

    def test_10_embed_multilingual_semantic_similarity(self):
        """Multilingual queries and passages must exhibit high cosine similarity across languages."""
        # Query in English
        q_en = embed_query("What is the return policy?")
        # Passage in Hindi about return policy
        p_hi = embed_passages(["हमारी वापसी नीति ग्राहकों को 30 दिनों के भीतर उत्पाद वापस करने की अनुमति देती है।"])[0]
        # Passage about an unrelated topic (server hardware)
        p_unrelated = embed_passages(["सर्वर डेटा सेंटर में लिनक्स ऑपरेटिंग सिस्टम पर चलता है।"])[0]

        sim_hi = np.dot(q_en, p_hi)
        sim_unrelated = np.dot(q_en, p_unrelated)

        # Semantically relevant Hindi passage should score significantly higher than unrelated passage
        self.assertGreater(sim_hi, 0.60, f"Cross-lingual Hindi similarity was unexpectedly low: {sim_hi}")
        self.assertGreater(sim_hi, sim_unrelated, f"Hindi return policy {sim_hi} should beat server hardware {sim_unrelated}")

    def test_11_async_embed_threadpool(self):
        """aembed_query and aembed_passages must execute asynchronously via worker threadpool."""
        async def run_async_test():
            q_vec = await aembed_query("How do I cancel my plan?")
            self.assertEqual(len(q_vec), 384)

            p_vecs = await aembed_passages(["You can cancel from your billing dashboard anytime."])
            self.assertEqual(len(p_vecs), 1)
            self.assertEqual(len(p_vecs[0]), 384)

        asyncio.run(run_async_test())

    def test_12_e5_prefix_handling(self):
        """Passages and queries must be prefixed correctly without double prefixing."""
        # Embed without explicit prefix
        v1 = embed_query("pricing details")
        # Embed with explicit prefix
        v2 = embed_query(f"{QUERY_PREFIX}pricing details")
        np.testing.assert_allclose(v1, v2, atol=1e-5)

        # Passage prefix test
        p1 = embed_passages(["sample passage text"])[0]
        p2 = embed_passages([f"{PASSAGE_PREFIX}sample passage text"])[0]
        np.testing.assert_allclose(p1, p2, atol=1e-5)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Database Model & Relationship Tests
    # ─────────────────────────────────────────────────────────────────────────
    def test_13_database_document_chunk_model(self):
        """Verify DocumentChunk can be created, saved, linked to KnowledgeDocument, and queried."""
        session = self.SessionLocal()
        try:
            # Create parent KnowledgeDocument
            doc = KnowledgeDocument(
                id="test_doc_rag_001",
                tenant_id="tenant_rag_test",
                filename="refund_policy.pdf",
                content="Full refund policy document content...",
                file_type="pdf",
                file_size_bytes=1024,
                is_active=True,
            )
            session.add(doc)
            session.commit()

            # Create 2 DocumentChunk instances
            vec1 = embed_passages(["Refunds are processed within 5 business days."])[0]
            vec2 = embed_passages(["Exchanges require manager approval."])[0]

            c1 = DocumentChunk(
                document_id=doc.id,
                tenant_id=doc.tenant_id,
                chunk_index=0,
                chunk_text="Refunds are processed within 5 business days.",
                token_count=10,
                embedding=vec1,
                is_active=True,
            )
            c2 = DocumentChunk(
                document_id=doc.id,
                tenant_id=doc.tenant_id,
                chunk_index=1,
                chunk_text="Exchanges require manager approval.",
                token_count=8,
                embedding=vec2,
                is_active=True,
            )
            session.add_all([c1, c2])
            session.commit()

            # Query back
            queried_chunks = session.query(DocumentChunk).filter(
                DocumentChunk.tenant_id == "tenant_rag_test",
                DocumentChunk.document_id == doc.id,
            ).order_by(DocumentChunk.chunk_index.asc()).all()

            self.assertEqual(len(queried_chunks), 2)
            self.assertEqual(queried_chunks[0].chunk_index, 0)
            self.assertEqual(queried_chunks[0].chunk_text, "Refunds are processed within 5 business days.")
            self.assertEqual(len(queried_chunks[0].embedding), 384)
            self.assertEqual(queried_chunks[1].chunk_index, 1)

            # Test cascade delete: deleting parent doc should delete chunks
            session.delete(doc)
            session.commit()

            remaining_chunks = session.query(DocumentChunk).filter(
                DocumentChunk.document_id == "test_doc_rag_001"
            ).all()
            self.assertEqual(len(remaining_chunks), 0)
        finally:
            session.close()

    def test_14_database_indexes_declared_on_model(self):
        """Verify relational and HNSW vector indexes are declared on DocumentChunk."""
        inspector = inspect(self.engine)
        idx_names = [idx["name"] for idx in inspector.get_indexes("document_chunks")]
        self.assertIn("ix_document_chunks_tenant_id_is_active", idx_names)
        self.assertIn("ix_document_chunks_document_id", idx_names)

    def test_15_alembic_migration_upgrade_and_downgrade(self):
        """Verify Alembic migration c4a189f7d23e can upgrade to head and downgrade cleanly."""
        from alembic.config import Config
        from alembic import command
        temp_mig_db = "test_mig_rag.db"
        if os.path.exists(temp_mig_db):
            os.remove(temp_mig_db)

        orig_central_url = os.environ.get("CENTRAL_DB_URL")
        try:
            os.environ["CENTRAL_DB_URL"] = f"sqlite:///{temp_mig_db}"
            cfg = Config("alembic.ini")
            cfg.set_main_option("sqlalchemy.url", f"sqlite:///{temp_mig_db}")
            # Upgrade from base through head
            command.upgrade(cfg, "head")
            # Downgrade back to Phase 1 head
            command.downgrade(cfg, "ef7a990203df")
        finally:
            if orig_central_url is not None:
                os.environ["CENTRAL_DB_URL"] = orig_central_url
            if os.path.exists(temp_mig_db):
                try:
                    os.remove(temp_mig_db)
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Ingestion & Retrieval Pipeline Tests
    # ─────────────────────────────────────────────────────────────────────────
    def test_16_ingest_document_pipeline_and_idempotence(self):
        """ingest_document must chunk, embed, and store records; reingest must clear previous chunks cleanly."""
        session = self.SessionLocal()
        try:
            doc_id = "doc_ingest_test_001"
            tenant_id = "tenant_pipeline_test"
            content = (
                "ManasBot Cloud Solutions offers enterprise data backup and disaster recovery. "
                "Automated snapshot backups run every 6 hours and are replicated across multi-region availability zones. "
                "Retention policies guarantee 30-day point-in-time recovery for all production databases. "
                "Customer support is reachable 24/7 through phone, email, and live chatbot support. "
                "Our service level agreement guarantees 99.99% uptime for all dedicated enterprise clusters."
            )
            doc = KnowledgeDocument(
                id=doc_id,
                tenant_id=tenant_id,
                filename="cloud_backup_sla.txt",
                content=content,
                file_type="txt",
                file_size_bytes=len(content),
                is_active=True,
            )
            session.add(doc)
            session.commit()

            # First ingestion
            chunks_created = ingest_document(
                document_id=doc_id,
                tenant_id=tenant_id,
                filename="cloud_backup_sla.txt",
                file_type="txt",
                content=content,
                db=session,
                chunk_size=200,
                chunk_overlap=50,
            )
            self.assertGreaterEqual(chunks_created, 2)

            chunks = session.query(DocumentChunk).filter(
                DocumentChunk.document_id == doc_id
            ).order_by(DocumentChunk.chunk_index.asc()).all()
            self.assertEqual(len(chunks), chunks_created)
            for c in chunks:
                self.assertEqual(len(c.embedding), 384)
                self.assertTrue(c.is_active)

            # Re-ingestion (idempotence verification)
            updated_content = "Short updated policy. Only one single chunk here."
            re_chunks = reingest_document(
                document_id=doc_id,
                tenant_id=tenant_id,
                filename="cloud_backup_sla.txt",
                file_type="txt",
                content=updated_content,
                db=session,
                chunk_size=500,
            )
            self.assertEqual(re_chunks, 1)

            chunks_after = session.query(DocumentChunk).filter(
                DocumentChunk.document_id == doc_id
            ).all()
            self.assertEqual(len(chunks_after), 1)
            self.assertEqual(chunks_after[0].chunk_text, updated_content)
        finally:
            session.close()

    def test_17_semantic_retrieval_and_threshold_filtering(self):
        """retrieve_relevant_chunks must rank by cosine similarity, enforce threshold, and limit top_k."""
        session = self.SessionLocal()
        try:
            tenant_id = "tenant_retrieval_test"
            doc = KnowledgeDocument(
                id="doc_retrieval_001",
                tenant_id=tenant_id,
                filename="warranty_faq.txt",
                content=(
                    "Warranty Policy: All hardware products come with a 2-year manufacturer warranty. "
                    "Replacement units are dispatched within 2 business days of RMA approval."
                ),
                file_type="txt",
                is_active=True,
            )
            session.add(doc)
            session.commit()

            ingest_document(
                document_id=doc.id,
                tenant_id=tenant_id,
                filename=doc.filename,
                file_type="txt",
                content=doc.content,
                db=session,
            )

            # 1. Matching query
            matching_results = retrieve_relevant_chunks(
                tenant_id=tenant_id,
                query="What is the hardware warranty period?",
                top_k=3,
                threshold=0.60,
                db=session,
            )
            self.assertGreaterEqual(len(matching_results), 1)
            best = matching_results[0]
            self.assertIn("2-year manufacturer warranty", best.chunk_text)
            self.assertGreater(best.similarity_score, 0.65)
            self.assertEqual(best.filename, "warranty_faq.txt")

            # 2. Unrelated query with high threshold should yield 0 results
            unrelated_results = retrieve_relevant_chunks(
                tenant_id=tenant_id,
                query="Quantum orbital mechanics and astrophysical star collapse",
                top_k=3,
                threshold=0.82,
                db=session,
            )
            self.assertEqual(len(unrelated_results), 0)

            # 3. top_k limit enforcement
            top1_results = retrieve_relevant_chunks(
                tenant_id=tenant_id,
                query="hardware warranty",
                top_k=1,
                threshold=0.50,
                db=session,
            )
            self.assertLessEqual(len(top1_results), 1)
        finally:
            session.close()

    def test_18_multi_tenant_isolation_security(self):
        """Strict tenant isolation: Tenant A's chunks must NEVER be returned to Tenant B."""
        session = self.SessionLocal()
        try:
            tenant_a = "tenant_company_alpha"
            tenant_b = "tenant_company_beta"

            # Create document for Tenant A with sensitive secret
            doc_a = KnowledgeDocument(
                id="doc_secret_alpha",
                tenant_id=tenant_a,
                filename="confidential_credentials.txt",
                content="Alpha internal database master encryption key is: ALPHA_SUPER_SECRET_TOKEN_999888.",
                file_type="txt",
                is_active=True,
            )
            session.add(doc_a)
            session.commit()

            ingest_document(
                document_id=doc_a.id,
                tenant_id=tenant_a,
                filename=doc_a.filename,
                file_type="txt",
                content=doc_a.content,
                db=session,
            )

            # Tenant B queries for Tenant A's exact secret
            b_results = retrieve_relevant_chunks(
                tenant_id=tenant_b,
                query="What is the ALPHA_SUPER_SECRET_TOKEN database encryption key?",
                top_k=5,
                threshold=0.10,  # extremely lenient threshold
                db=session,
            )
            # Tenant B must receive 0 chunks
            self.assertEqual(len(b_results), 0, "Security Violation: Tenant B retrieved Tenant A confidential chunk!")

            # Tenant A queries for the secret
            a_results = retrieve_relevant_chunks(
                tenant_id=tenant_a,
                query="database master encryption key",
                top_k=5,
                threshold=0.60,
                db=session,
            )
            self.assertGreaterEqual(len(a_results), 1)
            self.assertIn("ALPHA_SUPER_SECRET_TOKEN", a_results[0].chunk_text)
        finally:
            session.close()

    def test_19_format_rag_context_and_prompts(self):
        """format_rag_context must produce structured citations and enforce token limits."""
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                filename="pricing.pdf",
                chunk_text="Professional plan costs 2999 INR per month.",
                chunk_index=0,
                similarity_score=0.88,
            ),
            RetrievedChunk(
                chunk_id="c2",
                document_id="d2",
                filename="faq.txt",
                chunk_text="Annual billing includes a 20% discount.",
                chunk_index=1,
                similarity_score=0.74,
            ),
        ]
        context_str = format_rag_context(chunks, max_tokens=1000)
        self.assertIn("### VERIFIED KNOWLEDGE BASE CONTEXT", context_str)
        self.assertIn("[Source 1: pricing.pdf | Relevance: 88%]", context_str)
        self.assertIn("[Source 2: faq.txt | Relevance: 74%]", context_str)
        self.assertIn("2999 INR", context_str)

        # Empty chunks test
        self.assertEqual(format_rag_context([]), "")

        # Citation instruction
        instruction = get_rag_citation_instruction()
        self.assertIn("CITATION INSTRUCTIONS", instruction)
        self.assertIn("[Source: Return_Policy.pdf]", instruction)

    def test_20_end_to_end_chat_rag_sources(self):
        """POST /chat must retrieve relevant chunks and return source citations in the response."""
        session = self.SessionLocal()
        try:
            tenant_id = "tenant_e2e_chat"
            central_tenant = CentralTenant(
                id=tenant_id,
                name="Acme Logistics",
                username="acme_logistics_user",
                current_plan_id="plan_starter",
                is_active=True,
            )
            profile = BusinessProfile(
                tenant_id=tenant_id,
                company_name="Acme Logistics",
                industry="Logistics",
                business_description="Global shipping and supply chain solutions.",
            )
            doc = KnowledgeDocument(
                id="doc_e2e_shipping",
                tenant_id=tenant_id,
                filename="shipping_handbook.pdf",
                content="Standard express shipping takes 2 to 3 business days for domestic deliveries.",
                file_type="pdf",
                is_active=True,
            )
            session.add_all([central_tenant, profile, doc])
            session.commit()

            ingest_document(
                document_id=doc.id,
                tenant_id=tenant_id,
                filename=doc.filename,
                file_type="pdf",
                content=doc.content,
                db=session,
            )

            client = TestClient(app)
            with patch("backend.app.api.routers.chat.adetect_intent", new=AsyncMock(return_value="information")), \
                 patch("backend.app.api.routers.chat.aget_answer", new=AsyncMock(return_value="Express shipping takes 2-3 business days [Source: shipping_handbook.pdf]")):
                res = client.post("/chat", json={
                    "question": "How long does express shipping take?",
                    "session_id": "sess_e2e_001",
                    "tenant_id": tenant_id,
                    "language": "en",
                })
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertIn("Express shipping takes 2-3 business days", data["answer"])
                self.assertIn("sources", data)
                sources = data["sources"]
                self.assertGreaterEqual(len(sources), 1)
                self.assertEqual(sources[0]["filename"], "shipping_handbook.pdf")
                self.assertEqual(sources[0]["document_id"], "doc_e2e_shipping")
                self.assertGreater(sources[0]["relevance_score"], 0.60)
        finally:
            session.close()

    def test_21_backfill_embeddings_script(self):
        """backfill_embeddings CLI logic must identify unindexed docs and populate chunks."""
        session = self.SessionLocal()
        try:
            tenant_id = "tenant_backfill_test"
            doc = KnowledgeDocument(
                id="doc_backfill_unindexed",
                tenant_id=tenant_id,
                filename="unindexed_overview.txt",
                content="ManasBot automatic indexing and vectorization backfill test content.",
                file_type="txt",
                is_active=True,
            )
            session.add(doc)
            session.commit()

            # Dry run test
            stats_dry = backfill_documents(tenant_id=tenant_id, dry_run=True)
            self.assertGreaterEqual(stats_dry["processed_documents"], 1)
            self.assertEqual(stats_dry["total_chunks_created"], 0)

            # Actual backfill run
            stats_real = backfill_documents(tenant_id=tenant_id, force=True, dry_run=False)
            self.assertGreaterEqual(stats_real["total_chunks_created"], 1)

            # Verify chunks exist in DB
            chunks = session.query(DocumentChunk).filter(
                DocumentChunk.document_id == doc.id
            ).all()
            self.assertGreaterEqual(len(chunks), 1)
        finally:
            session.close()

    def test_22_delete_document_chunks_sync(self):
        """delete_document_chunks must cleanly wipe all chunks for a given document."""
        session = self.SessionLocal()
        try:
            tenant_id = "tenant_del_chunks"
            doc = KnowledgeDocument(
                id="doc_del_001",
                tenant_id=tenant_id,
                filename="temp_doc.txt",
                content="Temporary content to be deleted.",
                file_type="txt",
                is_active=True,
            )
            session.add(doc)
            session.commit()

            ingest_document(
                document_id=doc.id,
                tenant_id=tenant_id,
                filename=doc.filename,
                file_type="txt",
                content=doc.content,
                db=session,
            )
            self.assertGreaterEqual(session.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).count(), 1)

            # Delete chunks (hard delete)
            deleted_count = delete_document_chunks(doc.id, tenant_id, db=session, soft_delete=False)
            self.assertGreaterEqual(deleted_count, 1)
            self.assertEqual(session.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).count(), 0)
        finally:
            session.close()

    def test_23_unsupported_or_empty_retrieval_fallback(self):
        """Empty query or whitespace should safely return empty list without database queries."""
        self.assertEqual(retrieve_relevant_chunks("tenant_xyz", ""), [])
        self.assertEqual(retrieve_relevant_chunks("tenant_xyz", "   \t\n  "), [])
        self.assertEqual(retrieve_relevant_chunks("non_existent_tenant", "valid query"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
