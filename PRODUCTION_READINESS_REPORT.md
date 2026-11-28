# FinSight production-readiness report

Reviewed: 27 November 2026 (supersedes the 12 September 2026 review of the v1 SQLite/Chroma stack)
Scope: FinSight v2 — FastAPI + LangGraph agent, PostgreSQL 17 + pgvector, OpenFGA, Redis + Taskiq, S3-compatible storage, React workspace, Compose deployment.

## Verdict

**Staging candidate, not production.** The v2 architecture closes most v1 launch blockers in code: durable jobs, Postgres instead of SQLite, token revocation, audit logging, metrics and tracing. It has not yet been run end to end in Docker on this release, deployed to a server, load-tested, or used with real customer data.

## v1 blockers and where they stand

| v1 blocker (Sep 2026) | v2 status |
| --- | --- |
| Async job durability (in-process queues) | Fixed: Taskiq workers on Redis with persisted `jobs` table, cancel and retry |
| Observability | Fixed in code: request IDs, JSON logs, Prometheus `/metrics`, OpenTelemetry traces |
| Audit events | Fixed: append-only `audit_logs` (DB trigger), admin view, CSV export |
| SQLite / Chroma at scale | Fixed: PostgreSQL 17 + pgvector, Alembic migrations |
| Session revocation | Fixed: `token_version` + `is_active` checked per request |
| Evaluation gates | Partial: OWASP/ReBAC red-team gates run in CI; quality scores still from 14 questions on v1 |
| HTTPS and deployment ownership | Open: Nginx candidate only; no TLS, domain or secrets manager configured |
| Backups and restore | Open: documented, never drilled (Postgres + object storage + OpenFGA) |
| Dependency and image scanning | Partial: images pinned to exact versions (27 Nov); no scanning or SBOM yet |
| Data governance | Partial: prompt previews off by default in production; retention and DPA not defined |

## Changes in this review (27 Nov 2026)

- **Object storage:** MinIO community images were withdrawn from Docker Hub and Quay, which broke `docker compose up`. Replaced with RustFS 1.0.1 (Apache-2.0, S3-compatible, same ports); verified with boto3 put/get/head. The app creates the bucket itself, so the `minio-init` job was removed.
- **Pinned images:** TimescaleDB `pg17.12-ts2.32.1`, Redis `7.4.12-alpine`, Postgres `17.12-alpine`, OpenFGA `v1.23.0`, docling-serve `v1.39.0`, Phoenix `version-22.1.0`, Python `3.12.16-slim`, Node `24.22.3-alpine` (dev was on end-of-life Node 20), Nginx `1.30.8-alpine`; CI uses `pgvector/pgvector:0.8.7-pg17`.
- **Privacy default:** `AUDIT_STORE_PROMPT_PREVIEW` now defaults to `false` when `APP_ENV=production`.
- **Tests:** tests marked `postgres` now skip instead of failing when no database is reachable; `verification/e2e_smoke.py` had JavaScript syntax in Python and could not be imported, and is now rewritten against the real UI labels.
- **Docs:** README rewritten for v2.

## Verification

| Check | Result |
| --- | --- |
| Backend suite, offline (`-m "not slow"`) | 106 passed, 45 skipped (need live Postgres), 0 failed |
| Frontend tests | 11 Node + 2 Vitest passed |
| Frontend lint (`--deny-warnings`) | Passed |
| RustFS S3 round trip | Passed |
| Full stack in Docker | **Not run** — blocked by host disk space; next step |
| Postgres integration tests | **Not run locally** — run in CI against pgvector service |
| Browser E2E (`verification/e2e_smoke.py`) | **Not run** — needs the running stack |

## Remaining launch blockers

1. Run `docker compose up --build` end to end and the Postgres-backed and E2E tests against it.
2. Commit the v2 work so the repository and CI reflect it.
3. Deploy to staging with TLS, real secrets and a trusted proxy configuration.
4. Re-run evaluation on v2 with 150–300 questions and enforce thresholds in CI.
5. Load test (p95 latency, cost per 1,000 queries).
6. Drill backup and restore across Postgres, object storage and OpenFGA.
7. Add image scanning and an SBOM to CI.
8. Define data retention, deletion and model-provider data-processing terms.
