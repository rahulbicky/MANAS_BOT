# ManasBot — Automated Testing & Quality Assurance Guide

ManasBot contains a comprehensive automated regression, performance, RAG, and security test harness with **86 passing tests** across 6 specialized suites.

---

## 1. Test Suite Directory

| Suite File | Scope | Test Count | Key Invariants Verified |
|---|---|:---:|---|
| `test_phase2_rag.py` | RAG Ingestion & Embeddings | 23 | Document chunking, FastEmbed caching, cosine similarity, backfill |
| `test_async_chat_performance.py` | Asynchronous Throughput | 19 | Latency boundaries, async intent detection, threadpool concurrency |
| `test_langgraph_chat.py` | Multi-Turn State Graph | 12 | StateGraph compilation, intent routing, pure lead preservation |
| `test_phase3_production.py` | Reliability & Concurrency | 17 | Checkpoint persistence, session lock serialization, retention purge |
| `test_rag_benchmarking.py` | IR Metrics & Agent Tools | 9 | Hit Rate@K, MRR@K, Deduplication, Reranking, Agentic AI Tools |
| `test_security_hardening.py` | Security & Vulnerabilities | 6 | SSRF protection, cross-tenant isolation, RBAC, input sanitization |

---

## 2. Running Test Suites

All tests use Python's built-in `unittest` framework and require zero external test runner installations.

### Running Individual Suites:
```bash
python test_phase2_rag.py
python test_async_chat_performance.py
python test_langgraph_chat.py
python test_phase3_production.py
python test_rag_benchmarking.py
python test_security_hardening.py
```

### Running All 86 Tests in Batch:
```bash
python test_phase2_rag.py ; python test_async_chat_performance.py ; python test_langgraph_chat.py ; python test_phase3_production.py ; python test_rag_benchmarking.py ; python test_security_hardening.py
```

---

## 3. End-to-End Live Application Journey Verification

To test the entire application lifecycle (server startup, database creation, Super Admin login, client provisioning, document upload, RAG vector indexing, live conversational chat, lead capture, email notification, retention purge, and frontend static asset integrity):

```bash
python backend/scripts/verify_live_application.py
```

**Verification Journey Steps**:
1. Schema initialization & migrations
2. Super Admin creation & JWT login
3. Client tenant registration & credential validation
4. Chatbot widget branding & config API
5. Data retention policy & dry-run inspection
6. Document upload & FastEmbed vector indexing
7. Conversational RAG chat workflow execution
8. Lead capture & inquiry routing
9. Multi-turn session memory & chat log decryption
10. Frontend static asset file integrity (Admin, Client, Chatbot widget)
