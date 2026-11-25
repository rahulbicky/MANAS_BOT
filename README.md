# MANAS_BOT

<p align="center">
  <img src="docs/screenshots/chatbot-interface.png" alt="ManasBot Chatbot Widget" width="380" />
</p>

<p align="center">
  <strong>Production-Ready Multi-Tenant AI Knowledge Assistant & Customer Support Platform</strong>
</p>

<p align="center">
  <a href="#key-features"><img src="https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="#key-features"><img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" /></a>
  <a href="#key-features"><img src="https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" /></a>
  <a href="#key-features"><img src="https://img.shields.io/badge/FastEmbed-Multilingual%20E5-FF6F00?style=flat-square" alt="FastEmbed" /></a>
  <a href="#key-features"><img src="https://img.shields.io/badge/Groq%20Cloud-Ultra--Fast%20LLM-F55036?style=flat-square" alt="Groq" /></a>
  <a href="#key-features"><img src="https://img.shields.io/badge/LangChain-Orchestration-1C3C3C?style=flat-square" alt="LangChain" /></a>
  <a href="#langgraph-integration--multi-agent-workflow"><img src="https://img.shields.io/badge/LangGraph-Stateful%20Workflow-7C3AED?style=flat-square" alt="LangGraph" /></a>
  <a href="#license"><img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License" /></a>
</p>

---

## Table of Contents

- [What is ManasBot?](#what-is-manasbot)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [LangGraph Integration – Multi-Agent Workflow](#langgraph-integration--multi-agent-workflow)
- [How ManasBot Works](#how-manasbot-works)
- [Application Screenshots](#application-screenshots)
- [Technology Stack](#technology-stack)
- [Project Directory Structure](#project-directory-structure)
- [Installation and Setup](#installation-and-setup)
- [Environment Variables](#environment-variables)
- [Running the Application Locally](#running-the-application-locally)
- [Docker Compose Deployment](#docker-compose-deployment)
- [API Overview](#api-overview)
- [Automated Testing & Quality Assurance](#automated-testing--quality-assurance)
- [Enterprise Documentation Links](#enterprise-documentation-links)
- [Future Improvements](#future-improvements)
- [License](#license)

---

## What is ManasBot?

**ManasBot** is an AI-powered B2B Software-as-a-Service (SaaS) platform that allows businesses to upload their private documentation and deploy an intelligent, accurate customer support chatbot on their website in minutes.

### The Problem It Solves
- **Repetitive Customer Questions:** Support teams spend hours answering the exact same questions regarding policies, pricing, returns, and services.
- **AI Hallucinations:** Generic AI chatbots frequently invent false answers, fabricate non-existent discounts, and provide inaccurate business information.
- **Lost Sales Leads:** Website visitors leave without contacting sales because existing contact forms are slow, passive, and impersonal.
- **Complex Setups:** Most custom AI solutions require expensive cloud infrastructure, ongoing vector database subscriptions, and complicated engineering work.

### Who Can Use It?
- **Online Stores & E-Commerce:** Deliver instant answers for shipping timelines, returns, warranties, and order policies.
- **SaaS & Technology Companies:** Provide automated 24/7 technical documentation lookup and onboarding support.
- **Logistics & Service Companies:** Handle booking queries, operational hours, and service quotes automatically.
- **Agencies & Enterprise Sellers:** Host multiple separate business clients on a single multi-tenant installation.

### How It Helps Businesses
1. **Accurate, Factual Answers:** Uses **Retrieval-Augmented Generation (RAG)** to answer queries strictly using the company's verified documents.
2. **Transparent Source Citations:** Every response displays clickable source badges with percentage match scores so visitors know where the answer came from.
3. **Automated Lead Capture:** Detects customer contact details (name, phone, email) within natural chat conversations and alerts sales teams via instant email.
4. **Single-Script Website Embed:** Embed the custom-branded chat widget into any website, Shopify store, or WordPress site with a single `<script>` tag.

---

## Key Features

### Multi-Tenant System
- **Row-Level Tenant Isolation:** Every document, vector chunk, chat history log, and lead is scoped strictly by `tenant_id`.
- **Zero Cross-Tenant Leakage:** One tenant can never access or search across another tenant's vector embeddings or private data.
- **Subscription Tier Enforcement:** Built-in plan quotas (Starter, Pro, Enterprise, Custom) enforce monthly message limits, document limits, FAQ limits, and export permissions.

### AI Chatbot & Conversational Intelligence
- **Floating Chat Widget:** Fully responsive, modern widget with typing indicator, audio alerts, and markdown formatting.
- **Anti-Hallucination Guardrails:** Prompt engineering ensures the model politely declines to answer if factual context is missing, rather than guessing.
- **Intent Classification:** Automatically classifies user messages into intents (`pricing`, `support`, `service_inquiry`, `contact`, `eligibility`, `information`).
- **Resilient Fallback LLM Chain:** Seamlessly falls back across high-speed Groq cloud models (`qwen/qwen3.8-27b`, `openai/gpt-oss-20b`) to guarantee high uptime.

### Document Management & Multi-Format Ingestion
- **Broad File Support:** Ingests **PDF**, **DOCX**, **XLSX**, **XLS**, **CSV**, and plain **TXT** files.
- **Web URL Scraping:** Automatically extracts clean text from public website pages, stripping away unnecessary HTML, scripts, and styling.
- **Automated Re-Scraping:** Built-in APScheduler periodically refreshes website URLs every 6 hours to keep knowledge up to date.

### Advanced RAG & Semantic Vector Search
- **Intelligent Text Chunking:** Splits documents into 600-character chunks with a 100-character overlap using recursive character text splitting.
- **Local FastEmbed ONNX Engine:** Embeddings are generated locally on CPU using `intfloat/multilingual-e5-small` (384 dimensions) with zero external embedding API costs or network latency.
- **High-Performance Vector Storage:** Uses PostgreSQL `pgvector` with an **HNSW cosine distance index** (`vector_cosine_ops`) for lightning-fast sub-second retrieval.

### Dual Administration Portals
- **Super Admin Portal (`/admin/`):**
  - Register new client tenants and generate unique access credentials.
  - Manage subscription tiers, pricing, and system-wide limits.
  - Review platform analytics and customer support incidents.
  - Manage employee accounts with Role-Based Access Control (`super_admin`, `admin`, `support`, `viewer`).
- **Client Admin Portal (`/client/`):**
  - Customize company profile, greeting message, tone, and brand colors.
  - Manage FAQs and upload knowledge base documents.
  - Inspect individual indexed document chunks and vector token counts.
  - Review and export customer chat history to CSV or Excel.
  - Track qualified customer leads with one-click status updates.

### Lead Capture & Email Notifications
- **Smart Contact Detection:** Detects when a customer provides their name, 10-digit phone number, or email address during a chat session.
- **Lead Pipeline:** Captured leads appear immediately in the client dashboard with timestamps and initial user messages.
- **Instant SMTP Alerts:** Sends automated email notifications to business owners whenever a new lead is captured or an incident ticket is submitted.

### Security & Data Protection
- **JWT Employee Authentication:** Secure JSON Web Tokens with strict role verification for administrative employees.
- **Client API Tokens:** Dedicated API tokens (`X-Auth-Token`) for client dashboard access.
- **Data Encryption:** Customer questions and answers are encrypted at rest in the database using Fernet AES-128 encryption.
- **Rate Limiting:** Protects login and chat endpoints against abuse using SlowAPI rate limiting.

---

## System Architecture

The following modern, colour-coded architecture diagram illustrates the complete end-to-end design of ManasBot, from user interaction and security to document vectorization, RAG retrieval, and cloud LLM generation:

```mermaid
flowchart TD
    %% ==========================================
    %% 1. FRONTEND & USER INTERFACES (BLUE)
    %% ==========================================
    subgraph LayerFrontend [" 🌐 1. Frontend and User Interfaces (Blue) "]
        UserWidget("<b>🌐 Chatbot Widget</b><br/>Embeddable Floating Web UI")
        ClientPortal("<b>💻 Client Admin Portal</b><br/>Dashboard, KB and Analytics")
        SuperPortal("<b>🏢 Super Admin Portal</b><br/>Tenants, Plans and System Ops")
    end

    %% ==========================================
    %% 2. AUTHENTICATION & SECURITY (RED)
    %% ==========================================
    subgraph LayerSecurity [" 🛡️ 2. Authentication and Security Layer (Red) "]
        RateLimiter("<b>🛡️ SlowAPI Rate Limiter</b><br/>Endpoint Throttling and DDoS Defense")
        AuthManager("<b>🔐 Auth and RBAC Manager</b><br/>JWT Employee Tokens and Client API Keys")
        DataEncryptor("<b>🔒 Fernet AES-128 Engine</b><br/>Encrypted Chat History at Rest")
    end

    %% ==========================================
    %% 3. BACKEND & APIS (PURPLE)
    %% ==========================================
    subgraph LayerBackend [" ⚙️ 3. FastAPI Backend and API Services (Purple) "]
        FastAPICore("<b>⚙️ FastAPI Application</b><br/>Async ASGI Server and Middleware")
        ChatRouter("<b>💬 /chat Router</b><br/>Decoupled 3-Phase Execution Lifecycle")
        DocsRouter("<b>📁 /admin/documents Router</b><br/>File Parsing and Web Scraper Pipeline")
        LeadsRouter("<b>👥 /admin/leads Router</b><br/>Lead Pipeline and Excel/CSV Export")
        Scheduler("<b>⏱️ APScheduler Service</b><br/>Periodic 6-Hour Website Re-Scraper")
    end

    %% ==========================================
    %% 4. AI, LANGGRAPH & RAG ENGINE (GREEN)
    %% ==========================================
    subgraph LayerAI [" 🧠 4. LangGraph Workflow and Advanced RAG Pipeline (Green) "]
        DocExtractor("<b>📄 Multi-Format Text Extractor</b><br/>PyPDF2, DOCX, XLSX, CSV and Web HTML")
        TextChunker("<b>✂️ Recursive Text Chunker</b><br/>600-Char Segments with 100-Char Overlap")
        FastEmbedEngine("<b>🧠 FastEmbed ONNX Engine (CPU)</b><br/>multilingual-e5-small, 384 Dimensions")
        LangGraphEngine("<b>🕸️ LangGraph StateGraph Workflow</b><br/>guard_and_intent → router_lead_or_inquiry → RAG/Lead Nodes")
        VectorRetriever("<b>🔍 Semantic Vector Retriever</b><br/>Cosine Distance Matching and Reranking")
        PromptBuilder("<b>🎯 Anti-Hallucination Prompt Engine</b><br/>Shared Context Assembly and Citation Guardrails")
    end

    %% ==========================================
    %% 5. DATABASE & VECTOR STORAGE (ORANGE)
    %% ==========================================
    subgraph LayerDatabase [" 🗄️ 5. Database and Vector Storage (Orange) "]
        PgVectorTable[("<b>📦 document_chunks Table</b><br/>pgvector HNSW Cosine Index")]
        CheckpointDB[("<b>💾 LangGraph Checkpointer</b><br/>PostgreSQL Saver / MemorySaver Fallback")]
        RelationalDB[("<b>🗄️ Relational Database Tables</b><br/>tenants, plans, leads, faqs, chat_logs_v2")]
    end

    %% ==========================================
    %% 6. EXTERNAL SERVICES (TEAL)
    %% ==========================================
    subgraph LayerExternal [" ☁️ 6. External Cloud Services (Teal) "]
        GroqLLM("<b>☁️ Groq Cloud LLM Inference</b><br/>qwen/qwen3.8-27b and gpt-oss-20b Fallback")
        SMTPService("<b>📧 SMTP Notification Service</b><br/>Instant Sales Lead and Incident Alerts")
    end

    %% ==========================================
    %% COMPLETE DIRECTIONAL DATA FLOWS
    %% ==========================================

    %% User Inquiries & Protection
    UserWidget -->|1. POST /chat request| RateLimiter
    RateLimiter --> FastAPICore
    FastAPICore --> ChatRouter

    %% Administration & Auth
    ClientPortal -->|Upload docs and manage KB| AuthManager
    SuperPortal -->|Manage tenants and subscriptions| AuthManager
    AuthManager --> FastAPICore
    FastAPICore --> DocsRouter
    FastAPICore --> LeadsRouter
    Scheduler -.->|Periodic URL re-scrape & re-embed| DocsRouter

    %% Document Processing & Vector Storage
    DocsRouter --> DocExtractor
    DocExtractor --> TextChunker
    TextChunker --> FastEmbedEngine
    FastEmbedEngine -->|Store passage vectors| PgVectorTable

    %% Decoupled Chat RAG & LangGraph Flow
    ChatRouter -->|Phase A: Verify quotas, profile, history| RelationalDB
    ChatRouter -->|Phase B: Invoke ConversationState| LangGraphEngine
    LangGraphEngine <-->|Persist/Load thread checkpoints| CheckpointDB
    LangGraphEngine -->|Compute query vector| FastEmbedEngine
    FastEmbedEngine -->|384d query vector| VectorRetriever
    PgVectorTable -->|Top-K matching chunks| VectorRetriever
    VectorRetriever --> PromptBuilder
    PromptBuilder -->|Strict prompt + context| GroqLLM

    %% Response Delivery & Log Persistence
    GroqLLM -->|Grounded response| LangGraphEngine
    LangGraphEngine -->|Answer, intent & sources| ChatRouter
    ChatRouter -->|Phase C: Encrypt and persist logs/leads| DataEncryptor
    DataEncryptor --> RelationalDB
    ChatRouter -.->|Customer lead captured event| SMTPService
    ChatRouter -->|Grounded answer + source citations| UserWidget
    LeadsRouter -->|Query leads and chat history| RelationalDB

    %% ==========================================
    %% COMPONENT STYLING (MODERN SAAS PALETTE)
    %% ==========================================
    classDef frontend fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1;
    classDef security fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b;
    classDef backend fill:#f3e8ff,stroke:#9333ea,stroke-width:2px,color:#6b21a8;
    classDef ai fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#15803d;
    classDef database fill:#ffedd5,stroke:#ea580c,stroke-width:2px,color:#c2410c;
    classDef external fill:#ccfbf1,stroke:#0d9488,stroke-width:2px,color:#0f766e;

    class UserWidget,ClientPortal,SuperPortal frontend;
    class RateLimiter,AuthManager,DataEncryptor security;
    class FastAPICore,ChatRouter,DocsRouter,LeadsRouter,Scheduler backend;
    class DocExtractor,TextChunker,FastEmbedEngine,LangGraphEngine,VectorRetriever,PromptBuilder ai;
    class PgVectorTable,CheckpointDB,RelationalDB database;
    class GroqLLM,SMTPService external;
```

### Architectural Layer Breakdown

| Layer | Color Code | Component Responsibilities |
| :--- | :---: | :--- |
| **1. Frontend & Interfaces** | 🟦 **Blue** | **Chatbot Widget:** Embeddable floating JavaScript UI with markdown and audio alerts.<br/>**Client Admin Portal:** Self-service portal for business profiles, FAQs, documents, and leads.<br/>**Super Admin Portal:** Central management console for tenants, subscription plans, and team RBAC. |
| **2. Auth & Security** | 🟥 **Red** | **Rate Limiter:** SlowAPI middleware to prevent abuse and DDoS attacks.<br/>**Auth & RBAC Manager:** Signs and validates JWT employee access tokens and tenant API keys.<br/>**Fernet Encryption:** Encrypts user questions and answers at rest in the database with AES-128. |
| **3. Backend & APIs** | 🟪 **Purple** | **FastAPI Core Engine:** High-throughput asynchronous routing and dependency injection.<br/>**Modular Routers:** Dedicated handlers for `/chat`, `/admin/documents`, `/admin/leads`, etc.<br/>**APScheduler:** Background timer that automatically re-scrapes website URLs every 6 hours. |
| **4. AI & RAG Pipeline** | 🟩 **Green** | **Text Extractor:** Cleans and normalizes text from PDF, DOCX, CSV, Excel, and URLs.<br/>**Recursive Chunker:** Creates semantically cohesive 600-character chunks with 100-character overlap.<br/>**FastEmbed ONNX:** Generates 384-dimensional vector embeddings on CPU with zero API costs.<br/>**Prompt Builder:** Injects strict anti-hallucination guardrails and verified context excerpts. |
| **5. Database & Storage** | 🟧 **Orange** | **PostgreSQL (pgvector):** High-speed vector similarity search using HNSW indexing.<br/>**Relational Tables:** Strict tenant isolation (`tenant_id`) across plans, faqs, leads, and chat logs.<br/>*(SQLite fallback is natively supported for rapid local testing).* |
| **6. External Services** | 🟨 **Teal** | **Groq Cloud LLM:** Low-latency generative responses (`qwen/qwen3.8-27b`, `openai/gpt-oss-20b`).<br/>**SMTP Email Service:** Dispatches real-time sales lead alerts and system incident notifications. |

### Architectural Highlights
- **Decoupled 3-Phase Chat Lifecycle:**
  1. *Phase A (Read):* Validates tenant subscription limits and fetches profile settings, immediately closing the database session.
  2. *Phase B (Inference):* Computes query embeddings, runs vector similarity search, and calls the Groq LLM without holding any database connections open.
  3. *Phase C (Write):* Saves encrypted chat logs, updates monthly token usage, and persists captured customer leads.
- **Local Embedding Computation:** Embeddings run in-process on CPU via ONNX Runtime, eliminating recurring vector API costs.
- **Resilient Multi-Model Groq Fallback:** Automatically tries fast secondary LLMs if the primary model encounters rate limits or service interruptions.

---

## LangGraph Integration – Multi-Agent Workflow

ManasBot uses **LangGraph** (`backend/rag/graph.py` and `backend/rag/checkpointer.py`) inside Phase B of the chat pipeline to run a structured, stateful, multi-turn conversational workflow while holding zero database connections open during LLM inference.

### 1. Why LangGraph Was Added
Before LangGraph, chat execution ran as sequential procedural steps inside the API layer. Adding LangGraph provides:
- **Explicit workflow orchestration:** Every stage (sanitization, lead detection, intent routing, FAQ lookup, semantic RAG retrieval, answer generation, and citation formatting) is an isolated graph node.
- **Conditional branching:** Pure lead submissions bypass expensive RAG and LLM calls, while combined lead + inquiry messages capture the lead *and* continue to knowledge retrieval.
- **Persistent thread state:** Conversations can persist checkpoints across requests and server restarts via PostgreSQL, with safe per-turn reset of transient fields so prior turns never leak into new questions.

### 2. How the Workflow Works
1. **Phase A (Database Read):** `ChatService._process_chat_inner` validates quotas/language gates, loads tenant FAQs and business profile via `TenantRepository`, and decrypts recent turn history (`HISTORY_WINDOW_TURNS`) via `ChatRepository`.
2. **Phase B (LangGraph Execution):** `run_chat_graph` invokes `compiled_chat_graph` using composite thread ID `{tenant_id}:{session_id}`. All nodes operate without holding open ORM connections.
3. **Phase C (Database Write):** `ChatService` encrypts the user question and generated answer with Fernet, saves `ChatLog` (and any captured `Lead`) atomically, and schedules background email/alert tasks.

### 3. Workflow Diagram & Nodes and Edges

```mermaid
flowchart LR
    START([START]) --> Guard["guard_and_intent_node"]
    Guard -->|"router_lead_or_inquiry:<br/>is_pure_lead == True"| Lead["lead_capture_node"]
    Guard -->|"router_lead_or_inquiry:<br/>Inquiry present"| FAQ["faq_matcher_node"]
    Lead --> Cite["citation_formatter_node"]
    FAQ --> RAG["rag_retriever_node"]
    RAG --> Answer["answer_generation_node"]
    Answer --> Cite
    Cite --> ENDNode([END])
```

Verified nodes in `build_chat_graph()` (`backend/rag/graph.py`):
- **`guard_and_intent_node`**: HTML-escapes the incoming question, extracts contact details (`Name`, `Phone`, `Email`) via regex, classifies whether the message is a pure lead or also contains an inquiry, and runs async intent detection (`adetect_intent`).
- **`lead_capture_node`**: Returns an immediate confirmation response (`intent="lead_captured"`) when no extra question was asked, avoiding unnecessary RAG/LLM latency.
- **`faq_matcher_node`**: Filters tenant FAQs loaded in Phase A by the detected intent.
- **`rag_retriever_node`**: Resolves ambiguous multi-turn follow-ups via `resolve_conversational_query`, runs semantic search (`aretrieve_relevant_chunks`) with E5 embeddings and reranking, and prepares `doc_context` and `sources`.
- **`answer_generation_node`**: Builds the grounded system prompt (`build_rag_system_prompt`), injects decrypted multi-turn history, calls Groq models (`qwen/qwen3.8-27b` with fallback to `openai/gpt-oss-20b`), and prepends a lead acknowledgment when contact info accompanied a question.
- **`citation_formatter_node`**: Finalizes `sources` and computes `is_resolved` before returning to `END`.

*Note on Agentic Tools (`backend/rag/tools.py`):* ManasBot also defines four standalone tenant-scoped LangChain `StructuredTool` wrappers (`knowledge_retrieval`, `business_profile`, `lead_capture`, `support_incident`) exported via `get_tenant_agent_tools(tenant_id)`. These tools are modular and tested independently, while the production `/chat` endpoint executes the deterministic 6-node graph above.

### 4. Supervisor Architecture vs Deterministic Conditional Routing
ManasBot **does not use an LLM-driven Supervisor agent loop** inside the live `/chat` path. Instead, it uses a **deterministic conditional-routing Directed Acyclic Graph (DAG)** controlled by `router_lead_or_inquiry(state)`:
- Prevents infinite agent loops, unpredictable tool recursion, and wasted LLM tokens.
- Keeps response latency predictable for customer-facing web widgets.
- Guarantees every request terminates cleanly at `END` after `citation_formatter_node`.

### 5. StateGraph & State Management
The workflow is built on `StateGraph(ConversationState)` (`TypedDict`, `total=False`) carrying:
- **Inputs:** `question`, `session_id`, `tenant_id`, `language`, `page_url`
- **Phase A Context:** `chat_history`, `monthly_messages`, `company`, `industry`, `desc`, `custom_prompt`, `faqs`
- **Pipeline State:** `intent`, `lead_data`, `is_pure_lead`, `faq_context`, `retrieved_chunks` (serialized dicts), `doc_context`
- **Outputs:** `sources`, `answer`, `is_resolved`, `error`

Before every turn executes, `ChatService` and `run_chat_graph` explicitly reset per-turn transient keys (`intent`, `lead_data`, `is_pure_lead`, `faq_context`, `retrieved_chunks`, `doc_context`, `sources`, `answer`, `is_resolved`, `error`) so cached state from Turn 1 never leaks into Turn 2 on the same `thread_id`.

### 6. Checkpointing Architecture
Checkpointing is implemented in `backend/rag/checkpointer.py`:
- **`PostgresCheckpointSaver` (aliased as `AsyncPostgresSaver`)**: Extends LangGraph's `BaseCheckpointSaver[str]` using SQLAlchemy tables (`langgraph_checkpoints`, `langgraph_checkpoint_blobs`, `langgraph_checkpoint_writes`) scoped strictly by `thread_id = f"{tenant_id}:{session_id}"`.
- **Resilient Fallback (`get_checkpointer`)**: Supports `CHAT_CHECKPOINTER_BACKEND` (`auto`, `postgres`, `memory`), using `PostgresCheckpointSaver` for PostgreSQL and automatically falling back to `MemorySaver` in local SQLite/offline mode or if DB connectivity fails.
- **Retention Pruning**: `RetentionService.execute_retention_cleanup` cleans expired tenant checkpoints, blobs, and writes matching `{tenant_id}:%`.

### 7. LangChain vs LangGraph in ManasBot

| Framework | Role in ManasBot | Actual Modules |
|---|---|---|
| **LangChain** | LLM wrappers (`ChatGroq`), message types (`SystemMessage`, `HumanMessage`, `AIMessage`), prompt templates, text splitters, and `StructuredTool` schemas | `backend/intent_chain.py`, `backend/faq_chain.py`, `backend/rag/chunker.py`, `backend/rag/tools.py` |
| **LangGraph** | Stateful graph orchestration (`StateGraph`), conditional routing (`router_lead_or_inquiry`), multi-node execution flow, and PostgreSQL/`MemorySaver` thread checkpointing | `backend/rag/graph.py`, `backend/rag/checkpointer.py` |

---

## How ManasBot Works

### 1. Document Ingestion & Indexing Workflow
```
[User Uploads File / URL]
         │
         ▼
[Text Extraction] ──────────► Parses PDF, DOCX, XLSX, CSV, TXT, or web HTML
         │
         ▼
[Intelligent Chunking] ────► Splits text into 600-character segments (100 overlap)
         │
         ▼
[FastEmbed Inference] ─────► Converts chunks into 384-dimensional vectors with 'passage: ' prefix
         │
         ▼
[PostgreSQL + pgvector] ───► Stores chunks & vectors linked to tenant_id with HNSW index
```

1. **Upload:** A business client uploads a document (e.g., `return_policy.pdf`) or enters a website URL in their Client Admin Portal.
2. **Text Extraction:** Specialized extractors clean formatting, strip HTML tags, and convert the content into structured raw text.
3. **Chunking:** The document is split into overlapping chunks to preserve sentences and conversational context across boundaries.
4. **Vector Embedding:** FastEmbed computes a normalized 384-dimensional numerical embedding vector for each chunk.
5. **Database Storage:** The text chunks and their corresponding embedding vectors are saved into the `document_chunks` table, isolated under the client's `tenant_id`.

---

### 2. Customer Query & Answering Workflow
```
[Customer Types Question]
         │
         ▼
[Tenant Validation] ───────► Verifies active subscription, language settings & quotas
         │
         ▼
[FastEmbed Query Vector] ──► Converts question to 384-d vector with 'query: ' prefix
         │
         ▼
[pgvector Search] ─────────► Finds top-5 matching document chunks (cosine similarity >= 60%)
         │
         ▼
[Prompt Construction] ─────► Combines FAQ rules, verified chunks, and anti-hallucination prompt
         │
         ▼
[Groq LLM Generation] ─────► Generates factual answer with bracketed source citations
         │
         ▼
[Lead Check & Delivery] ───► Detects contact info, saves lead, encrypts log & returns response
```

1. **Question Submission:** A customer asks a question in the floating website chat widget.
2. **Validation:** The backend verifies that the tenant account is active, has not exceeded its monthly message quota, and confirms allowed languages.
3. **Semantic Search:** FastEmbed creates an embedding vector for the question, and PostgreSQL retrieves the most relevant document chunks for that specific tenant.
4. **LLM Generation:** The retrieved excerpts and strict business rules are sent to the Groq LLM to compose a direct, helpful answer.
5. **Source Citation:** The generated answer includes verified document citations (e.g., `[Source: return_policy.pdf]`), which the widget renders as clickable source badges.
6. **Lead Detection:** If the customer provides contact details, ManasBot automatically saves the lead and triggers an email alert.

---

## Application Screenshots

### Client Admin Dashboard & Analytics
> Monitor daily conversation volume, view top customer intents, and check real-time usage statistics.

![Client Dashboard](docs/screenshots/client-dashboard.png)

---

### Knowledge Base & Indexed Chunk Management
> Upload files, ingest live website URLs, and inspect individual semantic document chunks.

![Knowledge Base](docs/screenshots/knowledge-base.png)

---

### Embeddable Chatbot Interface
> Clean, responsive customer chat widget customizable with tenant branding, custom greetings, and sound alerts.

![Chatbot Interface](docs/screenshots/chatbot-interface.png)

---

### Factual Grounding & Source Citations
> Every response is backed by document citations displaying exact filenames and relevance match percentages.

![Chatbot Sources](docs/screenshots/chatbot-sources.png)

---

### Super Admin Management Portal
> Oversee all registered business clients, configure subscription plans, monitor incidents, and manage team permissions.

![Super Admin Dashboard](docs/screenshots/super-admin-dashboard.png)

---

## Technology Stack

| Layer | Technology | Purpose in Project |
| :--- | :--- | :--- |
| **Backend Framework** | **FastAPI** (Python 3.10+) | High-performance asynchronous REST API backend |
| **Web Server** | **Uvicorn** | Production-grade ASGI web server |
| **AI / LLM Cloud** | **Groq API** | Ultra-fast inference (`qwen/qwen3.8-27b`, `openai/gpt-oss-20b`) |
| **Graph Orchestration** | **LangGraph (`langgraph`)** | Stateful multi-node workflow (`StateGraph`), conditional routing, and checkpoint persistence |
| **LLM & Tool Layer** | **LangChain & LangChain-Groq** | `ChatGroq` model chains, message types, text splitters, and `StructuredTool` wrappers |
| **Embedding Engine** | **FastEmbed** (ONNX Runtime) | Local CPU embeddings using `intfloat/multilingual-e5-small` |
| **Vector Database** | **PostgreSQL + pgvector** | Vector similarity search with HNSW cosine distance indexing |
| **ORM & Migrations** | **SQLAlchemy & Alembic** | Relational data models, session management, and schema migrations |
| **Document Processing** | **PyPDF2, python-docx, openpyxl, pandas** | Text extraction from PDF, DOCX, Excel spreadsheets, and CSVs |
| **Web Scraping** | **HTTPX & BeautifulSoup4** | Async web page fetching (SSRF-validated) and HTML text extraction |
| **Security & Auth** | **PyJWT & bcrypt** | Role-based JWT authentication and salted password hashing |
| **Data Encryption** | **Cryptography (Fernet)** | Authenticated symmetric encryption of stored conversation logs |
| **Task Scheduling** | **APScheduler** | Background automated URL re-scraping |
| **Frontend UI** | **Vanilla JavaScript, HTML5, CSS3** | Lightweight portals and floating chat widget with zero heavy framework bloat |

---

## Project Directory Structure

```text
MANAS_BOT/
├── alembic/                         # Database schema migration scripts
│   └── versions/                    # Versioned database migration files
├── backend/                         # Core backend application package
│   ├── app/                         # FastAPI modular application
│   │   ├── api/                     # REST API route handlers
│   │   │   └── routers/             # auth, chat, documents, leads, tenants, etc.
│   │   ├── core/                    # Security, JWT tokens, config, rate limiter, session_lock
│   │   ├── repositories/            # Data access layer (chat_repo, tenant_repo)
│   │   ├── schemas/                 # Pydantic request and response models
│   │   ├── services/                # ChatService (3-phase lifecycle) & RetentionService
│   │   ├── utils/                   # Formatters & SSRF URL validation helpers
│   │   └── scheduler.py             # Scheduled background URL re-scraper & re-indexer
│   ├── rag/                         # LangGraph & Advanced RAG module
│   │   ├── checkpointer.py          # PostgresCheckpointSaver & MemorySaver fallback
│   │   ├── chunker.py               # Recursive text chunking with overlap
│   │   ├── embedder.py              # FastEmbed CPU embedding engine (multilingual-e5)
│   │   ├── evaluation.py            # Retrieval benchmarking harness (Hit@K, MRR@K)
│   │   ├── graph.py                 # LangGraph StateGraph & 6-node conversational workflow
│   │   ├── ingestion.py             # Transactional document chunk/embedding ingestion
│   │   ├── prompts.py               # Shared anti-hallucination prompt & context builders
│   │   ├── retriever.py             # pgvector similarity search, reranking & SQLite fallback
│   │   └── tools.py                 # Tenant-scoped LangChain StructuredTool wrappers
│   ├── database.py                  # SQLAlchemy models and database sessions
│   ├── encryption.py                # Fernet encryption utilities
│   ├── email_notifier.py            # SMTP email alert dispatcher
│   ├── faq_chain.py                 # Groq LLM answering chain
│   ├── intent_chain.py              # Intent classification chain
│   └── main.py                      # Main backend application entry point
├── docs/                            # Documentation assets
│   └── screenshots/                 # Application preview images
├── frontend/                        # Frontend web applications
│   ├── admin/                       # Super Admin Management Portal
│   ├── client/                      # Client Admin Dashboard & Knowledge Base
│   └── chatbot/                     # Embeddable customer-facing chat widget
├── requirements.txt                 # Python package dependencies
├── run_server.py                    # Combined local server launcher (Backend + Frontend)
├── test_async_chat_performance.py   # Phase 1 backend stability test suite (19 tests)
├── test_langgraph_chat.py           # LangGraph workflow & 3-phase lifecycle tests (16 tests)
├── test_phase2_rag.py               # Phase 2 advanced RAG test suite (23 tests)
├── test_phase3_production.py        # Production reliability, locks & retention tests (17 tests)
├── test_rag_benchmarking.py         # RAG evaluation & agentic tools tests (9 tests)
├── test_security_hardening.py       # SSRF, RBAC, isolation & XSS tests (8 tests)
└── README.md                        # Project documentation
```

---

## Installation and Setup

### Prerequisites
- **Python 3.10+** installed on your system
- **Git** installed on your system
- *(Optional for Production)* **PostgreSQL with pgvector** extension (e.g., Neon Serverless PostgreSQL)

### 1. Clone the Repository
```bash
git clone https://github.com/rahulbicky/MANAS_BOT.git
cd MANAS_BOT
```

### 2. Create and Activate a Virtual Environment
```bash
# On Windows
python -m venv venv
venv\Scripts\activate

# On macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Environment Variables

Copy the provided `.env.example` file to create your local `.env` file:

```bash
cp .env.example .env
```

Open `.env` and fill in your configuration:

```ini
# Environment mode
ENVIRONMENT=development

# Groq API Key (Get a free key at https://console.groq.com)
GROQ_API_KEY=your_groq_api_key_here

# Central Database Connection URL
# For local SQLite development (zero setup):
CENTRAL_DB_URL=sqlite:///local_dev.db

# For production PostgreSQL with pgvector:
# CENTRAL_DB_URL=postgresql://user:password@localhost:5432/manasbot

# Fernet 32-byte encryption key for data encryption
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=your_base64_fernet_encryption_key_here

# JWT Secret for employee authentication
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET=your_super_secret_jwt_key_minimum_32_characters
JWT_EXPIRE_HOURS=8

# Allowed CORS Origins
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://localhost:8000,http://127.0.0.1:8000

# Optional SMTP Email Notifications
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your_email@gmail.com
SMTP_PASSWORD=your_gmail_app_password_here
```

> [!IMPORTANT]
> Never commit your real `.env` file into version control. It is already included in `.gitignore`.

---

## Running the Application Locally

### 1. Run Database Migrations
Initialize your database tables and indexes using Alembic:

```bash
python -m alembic upgrade head
```

### 2. Launch the Application
Start both the FastAPI backend and the static frontend server with a single command:

```bash
python run_server.py
```

The terminal will confirm that both servers are active:
- **Backend API:** `http://127.0.0.1:8000`
- **Interactive Swagger Docs:** `http://127.0.0.1:8000/docs`
- **Frontend Server:** `http://127.0.0.1:8080`

### 3. Access the Dashboards
Open your browser and navigate to the application URLs:
- **Super Admin Portal:** [http://127.0.0.1:8080/admin/](http://127.0.0.1:8080/admin/)
- **Client Admin Portal:** [http://127.0.0.1:8080/client/](http://127.0.0.1:8080/client/)
- **Live Chatbot Widget Preview:** [http://127.0.0.1:8080/chatbot/](http://127.0.0.1:8080/chatbot/)

### 4. Running Automated Tests
Run the complete automated regression and production test suite (**92 tests** passing across 6 test suites):

```bash
python test_phase2_rag.py ; python test_async_chat_performance.py ; python test_langgraph_chat.py ; python test_phase3_production.py ; python test_rag_benchmarking.py ; python test_security_hardening.py
```

To run the complete 10-step live application journey integration test:
```bash
python backend/scripts/verify_live_application.py
```

---

## Docker Compose Deployment

ManasBot includes a multi-container `docker-compose.yml` pre-configured with PostgreSQL and pgvector:

```bash
# 1. Clone repository & configure environment variables
cp .env.example .env

# 2. Build and launch all services
docker compose up -d --build

# 3. Check container logs
docker compose logs -f backend
```

Services started:
- **`manasbot-postgres`**: PostgreSQL 16 with `pgvector` extension enabled on port `5432`.
- **`manasbot-api`**: FastAPI application on port `8000`.

---

## API Overview

The FastAPI backend exposes clean, documented REST endpoints. Key endpoints include:

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :---: |
| `POST` | `/chat` | Customer chat query with RAG retrieval and citation generation | No |
| `GET` | `/chat/config` | Fetch public tenant branding and greeting message | No |
| `POST` | `/chat/feedback` | Submit star rating and comment for a conversation | No |
| `POST` | `/admin/employee-login` | Super Admin employee login returning JWT token | No |
| `POST` | `/admin/resolve-username` | Resolves client login username to internal `tenant_id` | No |
| `POST` | `/admin/auth` | Client admin authentication returning client API token | No |
| `POST` | `/admin/tenant` | Register a new client tenant workspace | Super Admin JWT |
| `POST` | `/admin/upload-doc` | Upload and chunk knowledge base file (PDF, DOCX, CSV, etc.) | Client API Token |
| `POST` | `/admin/add-url` | Scrape, chunk, and index a web URL (with SSRF protection) | Client API Token |
| `GET` | `/admin/docs` | List all documents and chunk count for a tenant | Client API Token |
| `GET` | `/admin/leads` | Retrieve captured leads for a tenant with pagination | Client API Token |
| `GET` | `/admin/chats` | Retrieve conversation logs with export capabilities | Client API Token |
| `GET` | `/admin/retention-policy` | View chat log and lead data retention policies | Client API Token |
| `POST` | `/admin/retention-cleanup` | Trigger dry-run or live data retention cleanup | Client API Token |
| `GET` | `/health` | Application health and database readiness check | No |

Complete interactive API documentation is available at `/docs` (Swagger UI) and `/redoc` (ReDoc).

---

## Enterprise Documentation Links

For deep architectural, operational, security, and developer specifications, consult our enterprise guides:

- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture, three-phase chat lifecycle, and concurrency locking.
- [API_DOCUMENTATION.md](API_DOCUMENTATION.md) — Complete REST API reference, request/response schemas, and error codes.
- [DATABASE_DOCUMENTATION.md](DATABASE_DOCUMENTATION.md) — Central & tenant database schemas, HNSW vector indexing, and connection pooling.
- [RAG_ARCHITECTURE.md](RAG_ARCHITECTURE.md) — FastEmbed ONNX multilingual embeddings, chunking, deduplication, and cross-encoder reranking.
- [AGENTIC_AI_ARCHITECTURE.md](AGENTIC_AI_ARCHITECTURE.md) — LangGraph state graphs, Agentic AI tools, and checkpointer persistence.
- [SECURITY.md](SECURITY.md) — Authentication, RBAC, SSRF defense, AES-GCM Fernet encryption, and rate limiting.
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) — Docker Compose, Cloud Run, Render, and database seeding procedures.
- [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) — Full environment variable dictionary and defaults.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Runtime error resolution, database recovery, and model fallbacks.
- [TESTING_GUIDE.md](TESTING_GUIDE.md) — Automated testing matrix, benchmark metrics, and CI/CD verification.
- [CHANGELOG.md](CHANGELOG.md) — Project release history and upgrade logs.

---

## Future Improvements

- [ ] **Voice Support:** Voice-to-text input and natural text-to-speech voice responses for the chatbot widget.
- [ ] **Omnichannel Integrations:** Direct connectors for WhatsApp Business API, Telegram, and Slack channels.
- [ ] **Multi-Modal Image Querying:** Allow customers to upload photos of products or error screens for troubleshooting.
- [ ] **Advanced Agentic Tools:** Optional function calling for order status lookups and live inventory checks against external APIs.
- [ ] **Detailed Analytics Dashboard:** Deeper analytics covering deflection rate, average resolution time, and sentiment analysis.

---

## License

This project is licensed under the **MIT License**. Feel free to use, modify, and distribute it in your personal and commercial projects.
