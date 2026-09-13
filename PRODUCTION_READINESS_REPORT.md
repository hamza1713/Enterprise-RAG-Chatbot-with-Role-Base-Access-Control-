# FinSight production-readiness report

Reviewed: 12 September 2026  
Scope: React/Vite workspace, FastAPI API, SQLite/DuckDB/Chroma persistence, uploads, streaming chat, evaluation, and container deployment.

## Executive assessment

FinSight is a strong staging candidate with a useful product shape: role-scoped document Q&A, natural-language SQL, document exploration, indexing controls, and evaluation. It should not be described as production-ready until staging deployment, HTTPS, secret management, backup/restore, observability, and provider quota behavior are proven.

The highest-risk issues found during this review have been fixed: non-admin uploads, PDF access bypasses, untrusted SQL access to DuckDB files, unsafe upload paths and oversized files, stale JWT permissions, startup password resets, import-time index deletion, leaked URL tokens, unbounded chat input, and incomplete stream parsing.

## Implemented fixes

| Area | Finding | Resolution |
|---|---|---|
| Upload authorization | Any authenticated role could call `/upload-docs`. | Endpoint now requires C-Level authorization. |
| Upload safety | Filename traversal, empty files, duplicate overwrite, arbitrary role directories, and unlimited body size were possible. | Validated filenames and roles, 20 MB limit, empty-file check, duplicate protection, PDF signature check, and safe resolved paths. |
| PDF preview | A fallback path check could allow a file under an allowed directory even when it was not registered or authorized. | Preview now requires a registered document matching the user’s role and only serves PDFs; responses are `no-store`. |
| SQL execution | Generated SQL ran against the shared DuckDB connection, leaving a powerful external-file surface. | Authorized tables are copied into an in-memory read-only sandbox with external access disabled, one SELECT statement, 10-second interrupt, 1,000-row limit, and memory/thread limits. |
| JWT authorization | A token kept its old role after an administrator changed the account role. | Each request rechecks the current account role and rejects stale tokens. |
| Credentials | Login trimmed passwords; startup reseeded/overwrote existing hashes when env values changed. | Password bytes are preserved and existing hashes are never replaced at startup; new users require stronger passwords. |
| Search index | Importing the RAG module could erase Chroma when a migration marker was missing or dimensions changed. | Import-time destructive reset was removed; migrations now require an explicit maintenance operation and backup. |
| Chat streaming | Browser stop only hid updates; incomplete NDJSON and split UTF-8 records were fragile. | AbortController cancellation, bounded NDJSON reader, validation, malformed-record errors, and reader cleanup added. |
| URL security | PDF and evaluation report links placed bearer tokens in query strings. | Authenticated blob requests are used for PDF previews and report downloads. |
| Startup | Sample-data preload always ran, including production. | `PRELOAD_SAMPLE_DATA=false` is the production default. |
| Frontend | Fixed navigation, inconsistent copy, poor small-screen behavior, and a large initial bundle. | Responsive workspace shell, mobile nav, accessible labels, clearer copy, green/charcoal design system, lazy page loading, and branded favicon added. |

## Verification completed

- Backend regression suite: `60 passed, 8 deselected` with `-m "not slow"`.
- Security regression suite: `20 passed` in `verification/test_security.py`.
- Frontend stream tests: `5 passed` in `frontend/verification/ndjson.test.mjs`.
- Frontend production build: passes with page-level lazy chunks.
- Frontend lint: passes with `--deny-warnings` in the final CI command.
- Browser review: sign-in and authenticated Chat/Document Library pages rendered; desktop and phone-sized layouts checked.
- Python compilation: passes for `app`.

Docker was not installed on the review workstation, so image build, container permissions, and production startup remain staging gates.

## Remaining launch blockers

1. **HTTPS and deployment ownership.** Put an HTTPS gateway in front of the included Nginx candidate. Configure trusted proxy headers and verify the login rate limit sees the real client IP.
2. **Secret and account migration.** Set a stable JWT secret, strong initial admin password, exact CORS origin, and provider keys. Remove or rotate demo accounts before importing any development database.
3. **Backups and restore.** Back up SQLite, DuckDB, uploaded files, Chroma, and evaluation output as one consistent set. Test restore in a separate environment.
4. **Observability.** Add structured logs, request IDs, metrics for latency/provider errors/token cost, alerting, and audit events for login, upload, preview, query denial, role changes, and evaluation.
5. **Async job durability.** Indexing and evaluation state use in-process queues/locks. A restart can interrupt work; use a durable queue and persisted job state before horizontal scaling.
6. **Evaluation gates.** Run the full RAGAS and RBAC evaluations against representative, sanitized production-like data; set release thresholds and retain reports.
7. **Data governance.** Define document retention/deletion, source ownership, PII handling, provider data-processing terms, and who can access evaluation records.
8. **Dependency and image scanning.** Pin/upgrade dependencies under a scheduled review, scan images and packages, and add SBOM/license checks.

## Recommended feature roadmap

### Release 1: reliability and trust

- Durable indexing jobs with retry, pause, cancel, dead-letter state, and idempotent document versions.
- Conversation history with explicit user-controlled retention and export/delete actions.
- Answer feedback, citations that jump to the exact source section, and “I don’t know” confidence behavior.
- Admin audit log, user disable/enable, role change history, and session revocation.
- CSV schema validation, type inference preview, row/column privacy rules, and query cost/timeouts.
- Health/readiness endpoints that test database and index availability separately.

### Release 2: enterprise adoption

- OIDC/SAML SSO, SCIM provisioning, MFA through the identity provider, and group-to-role mapping.
- Object storage for documents, malware scanning, encryption at rest, retention policies, and versioned uploads.
- Hybrid retrieval (dense + BM25), reranker fallback, document freshness controls, and per-source quality analytics.
- Cross-source answers that clearly separate document evidence from computed data.
- Usage dashboard by role/team, token/cost budgets, quotas, and provider fallback policy.
- Exportable answer packets with citations, SQL, filters, timestamp, and access context.

### Release 3: scale and intelligence

- Postgres for shared metadata, a managed vector store, and a durable task broker when multiple replicas are needed.
- Semantic caching with permission-aware keys and invalidation on document version changes.
- Multimodal PDF/chart extraction with human review for low-confidence ingestion.
- Evaluation datasets and regression gates in CI, prompt/model versioning, and controlled A/B experiments.
- Localization, keyboard-first workflows, and a formal accessibility audit.

## Architecture notes

The current one-process deployment is deliberate. Chroma, the indexer queue, evaluation lock, and embedded databases have process-local state. Running multiple backend workers can produce duplicated startup work and inconsistent in-memory coordination; use one worker until those components move to shared services. The included production compose file reflects that constraint.

The SQL sandbox follows DuckDB’s security guidance for untrusted SQL by disabling external access and restricting what the connection can see. File-upload validation follows OWASP guidance to authorize upload actions and enforce size limits. FastAPI’s deployment guidance also highlights that each worker has its own memory, which is relevant to the current in-process vector/index state.

## Files added or updated

- UI: `frontend/src/workspace.css`, redesigned `LoginPage`, responsive `AppLayout`/`Sidebar`, lazy routes, authenticated document/report downloads.
- Security/runtime: `app/core/sql_sandbox.py`, safer `documents.py`, `admin.py`, `auth.py`, `users.py`, `config.py`, `main.py`, async AI calls, non-destructive index startup.
- Deployment: `Dockerfile.frontend.production`, `docker-compose.production.yml`, `deploy/nginx.conf`, `deploy/production.env.example`, `deploy/README.md`.
- Quality: `verification/test_security.py`, `frontend/verification/ndjson.test.mjs`, CI workflow, and updated test isolation.

