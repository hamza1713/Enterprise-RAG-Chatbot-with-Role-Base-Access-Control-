# FinSight Interview Preparation Report

## 1. What this project is

FinSight is a role-aware enterprise AI workspace. It gives employees one interface for:

1. Asking questions about unstructured documents with Retrieval-Augmented Generation (RAG).
2. Asking analytical questions about CSV data using natural-language-to-SQL.
3. Browsing documents that their role is allowed to see.
4. Managing users, roles, uploads, indexing, and evaluation as a C-Level administrator.

The important product idea is not simply "a chatbot." It is **an access-controlled information system with two answer engines**:

- RAG is appropriate for policies, reports, guides, and explanations.
- SQL is appropriate for rows, filters, counts, aggregations, and numeric analysis.
- RBAC is enforced at the backend so the model is not trusted to decide what a user may access.

The strongest one-sentence interview pitch is:

> "I built a multi-department enterprise AI workspace that routes questions between grounded document retrieval and structured SQL analytics, while enforcing department-scoped authorization before retrieval or query execution and measuring both answer quality and security behavior."

Do not describe this as a fully production-certified platform. The repository's own readiness review describes it as a strong staging candidate; HTTPS, durable jobs, observability, backups/restore, governance, dependency scanning, and real deployment verification remain release gates.

## 2. Business problem and value

### Problem

Department data is usually split across PDFs, Markdown files, spreadsheets, and internal reports. A conventional keyword search cannot answer both "What does our onboarding policy say?" and "How many employees joined Engineering last quarter?" safely. A general-purpose LLM can answer fluently but may hallucinate, expose information from the wrong department, or execute unsafe generated SQL.

### Solution

FinSight combines:

- A single React user experience.
- FastAPI APIs as the security and orchestration boundary.
- SQLite for identity, roles, document registry, and FTS5 chunks.
- DuckDB for local analytical tables.
- ChromaDB for vector retrieval.
- Gemini for classification, embeddings, answer generation, and SQL generation.
- Optional Cohere reranking.
- RAGAS and RBAC regression evaluation.

### Business value

- Less time spent manually searching documents.
- More consistent answers with source references.
- Department isolation for sensitive data.
- A path from prototype to enterprise controls such as SSO, audit logs, durable indexing, and cost governance.

## 3. Architecture at a glance

```text
Browser (React + TypeScript + Vite)
        |
        | HTTP Basic login; Bearer JWT for subsequent calls
        v
FastAPI application
  |-- auth dependency: verify JWT and re-check current role
  |-- chat router: history, cross-department guard, route selection
  |-- document router: list/content/PDF/upload
  |-- admin router: users, roles, indexing controls
  |-- evaluation router: quality and RBAC evaluation
        |
        +--> RAG path:
        |      query expansion/contextualization
        |      dense Chroma retrieval + SQLite FTS5 hybrid retrieval
        |      optional Cohere rerank
        |      Gemini answer with retrieved context
        |
        +--> SQL path:
               Gemini generates SELECT-only SQL from authorized schemas
               authorized-table snapshot in an in-memory DuckDB sandbox
               bounded result set and timeout

Persistence:
  SQLite: users, roles, document registry, indexing state, FTS5 chunks
  DuckDB: structured CSV tables and table metadata
  ChromaDB: persistent embeddings
  Filesystem/volumes: uploads, reports, database files
```

### Main implementation map

| Concern | Primary files | Responsibility |
|---|---|---|
| Application lifecycle | [app/main.py](app/main.py) | FastAPI factory, startup schema/seed/reconcile/preload lifecycle, routers, CORS |
| Configuration | [app/core/config.py](app/core/config.py) | Environment variables, paths, model fallback list, production checks |
| Authentication | [app/api/auth.py](app/api/auth.py), [app/core/security.py](app/core/security.py) | HTTP Basic login, bcrypt verification, JWT issue/decode, current-user dependency |
| Metadata and identity | [app/core/database.py](app/core/database.py), [app/core/users.py](app/core/users.py) | SQLite schema, WAL connections, role/user seeding, path healing |
| Authorization | [app/api/chat.py](app/api/chat.py), [app/api/admin.py](app/api/admin.py), [app/api/documents.py](app/api/documents.py) | Role checks, department checks, protected operations |
| Document ingestion | [app/rag/processors.py](app/rag/processors.py), [app/rag/module.py](app/rag/module.py) | CSV/Markdown/PDF loading, PDF table extraction, chunking, background indexing |
| RAG | [app/rag/module.py](app/rag/module.py), [app/rag/chain.py](app/rag/chain.py) | Embeddings, retries, hybrid retrieval, reranking, answer generation |
| Structured analytics | [app/rag/classifier.py](app/rag/classifier.py), [app/rag/csv_query.py](app/rag/csv_query.py), [app/core/sql_sandbox.py](app/core/sql_sandbox.py) | SQL/RAG classification, NL-to-SQL, role table selection, isolated execution |
| Frontend | [frontend/src/App.tsx](frontend/src/App.tsx), [frontend/src/api/client.ts](frontend/src/api/client.ts), [frontend/src/api/chat.ts](frontend/src/api/chat.ts) | Routes, role-aware UX, authenticated API client, NDJSON streaming |
| Evaluation | [app/rag_evaluator/](app/rag_evaluator/) | RAGAS answer metrics and RBAC security scenarios |
| Deployment | [docker-compose.production.yml](docker-compose.production.yml), [deploy/README.md](deploy/README.md) | Single-host candidate deployment and release verification checklist |

## 4. End-to-end request flows

### 4.1 Login

1. The React store sends `GET /login` with HTTP Basic credentials.
2. The backend looks up the username in SQLite and verifies the bcrypt hash.
3. The backend issues an HS256 JWT containing `sub`, `role`, and `exp`.
4. The frontend stores the session state in `sessionStorage`, not long-lived local storage.
5. Later requests send `Authorization: Bearer <token>`.
6. `get_current_user` decodes the token and performs a fresh SQLite role lookup. If the account was deleted or its role changed, the old token is rejected.

Why this matters: the token is an authentication credential, but the database is still the authority for current authorization state.

### 4.2 Chat

1. Pydantic validates the question and limits it to 8,000 characters. Conversation history is also accepted.
2. Recent history can be summarized into a standalone question to resolve "it", "their", or "last quarter."
3. A deterministic department phrase guard rejects obvious cross-department requests before model retrieval.
4. Greetings and small talk bypass expensive AI calls.
5. The LLM classifier chooses `SQL` or `RAG`.
6. SQL calls `ask_csv`; RAG calls `ask_rag`.
7. The response includes mode, answer, optional SQL, and source names.
8. `/chat-stream` sends NDJSON records such as `init`, `token`, `metadata`, and `error`; the frontend validates records and supports `AbortController` cancellation.

Important security explanation:

> "The phrase-based guard is a fast user-facing denial layer, not the only security control. The actual data paths independently scope documents, tables, and SQL execution by role."

### 4.3 Document upload and indexing

1. Only C-Level can call `POST /upload-docs`; the frontend guard is only a UX convenience.
2. The backend validates filename characters, role existence, extension, size (20 MB), non-empty content, and PDF signature.
3. CSV content is parsed and registered as a DuckDB table.
4. The document metadata is stored in SQLite.
5. A background task triggers the in-process indexer queue.
6. The loader reads CSV, Markdown, or PDF. PDF text and extracted tables are converted into searchable content.
7. Chunkers create role-tagged chunks.
8. Chunks are written to Chroma and SQLite FTS5; indexing progress is persisted in the document row.

### 4.4 Structured query

1. `get_allowed_tables_for_role` derives permitted tables from `tables_metadata`.
2. Gemini receives only the schemas available to that role and is instructed to produce a SELECT query.
3. The result is checked for one statement, SELECT-only behavior, valid table names, and role authorization.
4. `query_authorized_tables` opens the source DuckDB read-only, copies only authorized tables into an in-memory sandbox, disables external access, limits memory/threads, and interrupts after 10 seconds.
5. Results are capped at 1,000 rows and the UI displays a smaller preview.

The key design principle is **capability reduction**: even if generated SQL is wrong or malicious, it does not receive the shared database connection or unrestricted filesystem access.

### 4.5 Evaluation

C-Level users can trigger:

- RAGAS quality evaluation: faithfulness, answer relevancy, context precision, context recall, and related scores.
- RBAC security evaluation: cross-role access and leakage scenarios.
- HTML and JSON/CSV reports with persisted status.

The evaluation is deliberately treated as a product feature rather than a one-off notebook: it can be triggered through the API and viewed in the UI.

## 5. Why these choices?

### FastAPI

**Why:** typed request validation, dependency injection for authentication, good async support, easy streaming responses, OpenAPI generation, and a clean router structure.

**Alternative:** Flask is simpler but provides less built-in validation and dependency structure. Django would add an ORM/admin ecosystem that is heavier than needed for this focused service. A fully serverless API could scale differently but complicates local vector/index state and background work.

**Trade-off:** the application uses synchronous libraries behind `asyncio.to_thread` and an in-process worker, so it is not yet a horizontally scalable service.

### React + TypeScript + Vite

**Why:** a real product-like SPA with explicit routing, lazy-loaded pages, typed API contracts, responsive UI, and easy separation from the API.

**Alternative:** Streamlit would be faster for a demo but is less suitable for a multi-page enterprise workspace, fine-grained navigation, streaming control, and independent frontend deployment. Next.js could add server rendering and a larger ecosystem, but SSR is not required for an authenticated internal tool.

**Trade-off:** two applications mean separate builds, CORS/configuration, and frontend-backend contract maintenance.

### SQLite

**Why:** low operational overhead for metadata, users, roles, document records, and FTS5. WAL mode improves concurrent read/write behavior.

**Alternative:** PostgreSQL is the better shared production metadata store for multiple replicas, stronger operational tooling, and concurrent writes.

**Trade-off:** SQLite is not a good primary store for high write concurrency or multi-host deployment.

### DuckDB

**Why:** embedded columnar OLAP engine; excellent for analytical CSV queries without deploying a separate warehouse.

**Alternative:** PostgreSQL for operational scale, a warehouse such as BigQuery/Snowflake for large enterprise analytics, or pandas for very small datasets.

**Trade-off:** DuckDB is excellent for local/embedded analytics but must be protected carefully when executing generated SQL and is not the ideal shared multi-writer service.

### ChromaDB

**Why:** persistent local vector store, straightforward LangChain integration, and metadata filters.

**Alternative:** pgvector reduces the number of persistence technologies; Qdrant, Weaviate, Pinecone, or a managed cloud vector service provides better scale/operations.

**Trade-off:** the current local Chroma process and singleton are appropriate for one backend worker, not automatic horizontal scale.

### Gemini

**Why:** cost/speed/context balance, native generation and embedding integration, and model fallback handling.

**Alternative:** OpenAI, Anthropic, Azure OpenAI, self-hosted models, or an abstraction layer with provider routing.

**Trade-off:** provider quotas, latency, model drift, data-processing terms, and vendor lock-in require monitoring and a documented fallback policy.

### Separate SQL and RAG engines

**Why:** vector retrieval is not a reliable replacement for exact filters, counts, joins, or arithmetic. SQL is not a good replacement for semantic policy/document understanding.

**Alternative:** one tool-using agent with database and retrieval tools. That can be more flexible, but it increases prompt/tool complexity and makes authorization auditing harder. The explicit router is easier to explain and test.

### In-process indexing queue

**Why:** simple, non-blocking upload UX and no extra infrastructure for a single-host candidate.

**Alternative:** Celery/RQ with Redis, a cloud task queue, or a durable workflow engine.

**Trade-off:** jobs can be interrupted by process restart, queue state is not durable, and multiple workers do not share the same queue/locks. This is a known scale boundary.

## 6. Security model

### Controls currently present

- Bcrypt password hashes rather than plaintext passwords.
- JWT expiry and HS256 signature verification.
- Fresh role lookup on each authenticated request.
- C-Level-only admin, upload, indexing, and evaluation operations.
- Department-scoped document lists and content/PDF access.
- Filename/path traversal defenses and extension/size validation.
- No bearer token in PDF/evaluation URLs; authenticated headers are used.
- SQL sandbox with one SELECT statement, authorized tables only, external access disabled, memory/thread limits, timeout, and row cap.
- CORS is explicit in production configuration.
- Production requires a stable JWT secret and explicit CORS origins.
- Security regression tests cover upload, paths, role changes, password preservation, PDF authorization, and SQL escape attempts.

### Important limitations to explain honestly

1. The phrase-based cross-department guard is not a complete policy engine. It can miss synonyms or over-block ambiguous words. The deeper retrieval/table authorization is the real boundary.
2. JWT is stateless for clients, but logout/session revocation is limited. A compromised unexpired token remains usable until expiry or a role/account change invalidates it.
3. HTTP Basic is acceptable for the login exchange only over HTTPS. The public deployment must terminate TLS at a trusted reverse proxy.
4. Secrets and provider data governance are deployment responsibilities. Do not keep demo credentials in a production database.
5. There is no complete audit trail yet for every login, denial, upload, role change, preview, and query.
6. Uploaded files need malware scanning, content inspection, retention/deletion policy, and potentially encryption at rest for a real enterprise deployment.

### Strong answer to "How did you prevent prompt injection?"

> "I did not treat prompt instructions as a security boundary. Authorization happens before retrieval, and the SQL path validates and executes against an isolated snapshot containing only authorized tables. Prompt-injection defenses such as instruction hierarchy, source quoting, output validation, and model policies are still useful for answer quality, but they cannot replace backend authorization."

## 7. Testing and evidence

### Test layers

- [tests/test_chatbot.py](tests/test_chatbot.py): API behavior, routing, role propagation, denial behavior, upload and admin flows.
- [tests/test_nextgen_rag.py](tests/test_nextgen_rag.py): PDF table formatting, FTS5 retrieval, contextualization, idempotent chunk storage.
- [verification/test_security.py](verification/test_security.py): offline security regression tests, path traversal, upload limits, role invalidation, password preservation, SQL sandbox escape attempts.
- [frontend/verification/ndjson.test.mjs](frontend/verification/ndjson.test.mjs): streaming parser behavior.
- [app/rag_evaluator/ragas_evaluator.py](app/rag_evaluator/ragas_evaluator.py): quality metrics.
- [app/rag_evaluator/rbac_security_eval.py](app/rag_evaluator/rbac_security_eval.py): security evaluation scenarios.
- [.github/workflows/ci.yml](.github/workflows/ci.yml): frontend build/test/lint and backend pytest commands.

### What to say about quality

RAGAS metrics are useful signals, not proof of correctness. A good release gate should combine:

- Retrieval metrics: recall, context precision, citation coverage.
- Answer metrics: faithfulness, correctness, relevance, abstention quality.
- Security metrics: zero unauthorized retrieval/exposure in a representative test set.
- Operational metrics: p95 latency, provider error rate, indexing success rate, cost per answer.

## 8. Known gaps and prioritized roadmap

### Before calling it production-ready

1. Deploy behind HTTPS and verify reverse-proxy headers and rate-limit identity.
2. Use a secret manager; rotate JWT/provider credentials.
3. Remove demo accounts and define user lifecycle.
4. Add structured logs, request IDs, metrics, tracing, alerts, and cost telemetry.
5. Add backup/restore for SQLite, DuckDB, uploads, Chroma, and evaluation artifacts as a consistent set.
6. Replace in-process queues/locks with durable jobs and persisted job state.
7. Add dependency/image scanning, SBOM/license checks, and scheduled upgrades.
8. Define retention, deletion, PII, source ownership, provider processing, and audit policies.

### Product roadmap

**Release 1: trust and reliability**

- OIDC/SAML SSO, MFA through the identity provider, SCIM provisioning.
- Durable indexing with retries, pause/cancel, dead-letter state, and document versions.
- Audit log, disable/enable users, role history, session revocation.
- Exact citation navigation and an explicit "I do not know" answer state.
- CSV schema/type validation and query budgets.

**Release 2: enterprise adoption**

- Object storage with malware scanning, encryption, retention, and versioning.
- Hybrid dense + BM25 retrieval with source freshness controls.
- Permission-aware caching and invalidation on document changes.
- Usage/cost budgets by team and provider fallback policies.
- Answer packets containing citations, SQL, filters, timestamp, and access context.

**Release 3: scale**

- PostgreSQL for shared metadata.
- Managed vector storage or pgvector.
- Durable task broker and multiple API replicas.
- Prompt/model versioning, evaluation datasets in CI, A/B experiments.
- Multimodal/OCR pipeline for scanned PDFs with human review.

## 9. Interview questions and strong answers

### "Walk me through the architecture."

Start at the browser: React authenticates, stores a short-lived session token, and calls FastAPI. FastAPI validates the token and current role, applies the cross-department guard, and routes the request to either RAG or SQL. RAG uses role-scoped hybrid retrieval and Gemini generation. SQL uses Gemini only for query generation, then executes in a restricted DuckDB sandbox. SQLite stores identity/metadata, DuckDB stores structured data, and Chroma stores embeddings. Admins can index documents and run quality/security evaluations.

### "Why not just send every question to the LLM?"

Because the LLM is not a database and should not be the authorization layer. Exact arithmetic and filtering belong to SQL; policies and semantic explanations belong to retrieval. Separating the paths improves correctness, observability, cost control, and security reviewability.

### "Why not use vector search for CSVs?"

Embeddings can retrieve semantically similar rows, but they are unreliable for exact predicates, joins, counts, sorting, and arithmetic. CSVs are loaded into DuckDB so the answer is computed rather than guessed.

### "Why is role filtering in metadata not enough?"

Metadata filters reduce retrieval scope, but defense in depth is needed. The API checks roles, document endpoints check the registry, SQL derives allowed tables, and the sandbox copies only authorized tables. A bug in one layer should not automatically become data exfiltration.

### "What happens if the classifier chooses the wrong route?"

The classifier is a routing heuristic, not a source of truth. SQL output is validated and bounded; errors can be surfaced or fall back to RAG where appropriate. For a later version, I would add confidence/abstention, deterministic intent rules for high-risk cases, and route-level evaluation.

### "How would you scale this?"

First externalize shared state: PostgreSQL for metadata, object storage for files, managed vector storage or pgvector, Redis/Kafka/Celery or a cloud queue for indexing, and a distributed lock/job store. Then run stateless API replicas behind a load balancer. Keep tenant/role filters in every retrieval and query operation, and add idempotent document versions.

### "How would you improve authentication?"

Use OIDC/SAML with the company identity provider, MFA and conditional access there, SCIM for lifecycle provisioning, group-to-role mapping, refresh-token/session revocation strategy, and an audit log. Keep application-level authorization because identity provider authentication does not replace resource authorization.

### "How do you measure whether the system is good?"

Measure retrieval and answer quality separately from security. Use a curated, role-labeled evaluation set; track RAGAS metrics, citation correctness, SQL execution correctness, unauthorized-access pass rate, p95 latency, provider failures, index freshness, and cost. Set release thresholds and compare every prompt/model/index change against a baseline.

### "What is the biggest current architectural risk?"

The biggest operational risk is the in-process state: indexing and evaluation jobs, locks, Chroma, and embedded databases are designed for one backend worker. Restart or horizontal scaling can interrupt or duplicate work. The first serious production improvement is durable jobs plus shared persistence.

### "What would you change if you had another month?"

I would not start with a more complex model. I would add SSO/MFA integration, durable idempotent indexing, audit logs, observability/cost metrics, document versioning/deletion, restore testing, and a stronger evaluation gate. Those changes increase trust and operating reliability more than a marginal prompt improvement.

## 10. Stakeholder communication

### For a recruiter

Emphasize ownership across product and engineering concerns: a useful workflow, secure boundaries, two data modalities, tests, evaluation, and a realistic production roadmap.

### For an engineering manager

Emphasize separation of concerns, failure modes, operational constraints, explicit trade-offs, and how you would move from single-host staging to shared services.

### For a security stakeholder

Emphasize that authorization is enforced before retrieval and in the SQL executor, not delegated to the LLM; mention stale-token invalidation, upload controls, PDF authorization, SQL sandboxing, negative tests, and remaining needs such as SSO, audit, malware scanning, and governance.

### For a data/AI stakeholder

Explain why RAG and SQL are separate, how chunks and tables are scoped, how hybrid retrieval improves exact-term discovery, how citations are produced, and how RAGAS/security evaluation supports release decisions.

## 11. A five-minute demo narrative

1. Sign in as an HR user and ask an HR policy question. Show the grounded answer and source.
2. Ask for an HR count or filtered table. Show that the system uses SQL and exposes the generated query.
3. Ask for Finance data as HR. Show the denial and explain that the model is never given unauthorized context.
4. Sign in as C-Level. Show document upload, indexing progress, user/role management, and evaluation status.
5. Explain the production boundary: one worker today; durable queue, shared stores, SSO, audit, observability, and restore testing next.

## 12. Final positioning

FinSight is compelling because it demonstrates more than an LLM API call: it integrates a user-facing product, backend architecture, security controls, retrieval, structured analytics, asynchronous processing, evaluation, and deployment thinking. The most credible presentation is not "everything is production-ready." It is:

> "I made the important boundaries explicit, tested the security-critical paths, and understand exactly what must change before scale and enterprise operation."

