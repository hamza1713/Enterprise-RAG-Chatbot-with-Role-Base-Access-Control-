# FinSight — Enterprise AI Workspace

FinSight is a staging candidate for a role-scoped AI workspace that combines document Q&A, natural-language SQL analytics, department isolation, and evaluation tooling.

**[Portfolio case study](https://personalportfolio-theta-gules-56.vercel.app/#work) · [Security regression tests](verification/test_security.py) · [Production readiness report](PRODUCTION_READINESS_REPORT.md) · [CI workflow](.github/workflows/ci.yml)**

## What it demonstrates

- **Scoped retrieval:** documents are indexed with role and department metadata; requests are filtered before generation.
- **Structured analytics:** natural-language questions can be routed to a restricted DuckDB SQL path.
- **Application delivery:** React/Vite frontend, FastAPI backend, streaming responses, document exploration, indexing controls, and Docker deployment candidates.
- **Evaluation:** RAGAS-style quality reports and RBAC security checks are included in `app/rag_evaluator/`.
- **Security work:** upload authorization, path validation, PDF access checks, stale-token handling, SQL sandboxing, bounded inputs, and safer stream parsing are covered by regression tests.

## Architecture

`React 19 + TypeScript` → `FastAPI` → `query classifier` → `ChromaDB RAG` or `DuckDB SQL` → grounded response

The application uses SQLite for users, roles, and document metadata; ChromaDB for role-filtered embeddings; and DuckDB for structured data queries. The SQL path is restricted to authorized in-memory tables and a single read-only statement.

## Current status

The [production-readiness report](PRODUCTION_READINESS_REPORT.md) records a strong staging shape and the remaining launch gates. Local verification included backend regression tests, security tests, frontend stream tests, a production build, and Python compilation. Deployment ownership, HTTPS, stable secret management, backups, observability, durable indexing jobs, representative evaluation data, dependency scanning, and data-governance decisions remain before a production claim is appropriate.

The saved RBAC evaluation reports an overall PASS with warnings: authorized access scored 100%, retriever filter precision scored 100%, and two checks require follow-up. Treat those results as test-fixture evidence rather than a security certification.

## Run locally

Use the example environment files and deployment notes to configure a local instance. Never publish real passwords, tokens, API keys, or copied production data. Replace any development-only credentials before sharing a deployment.

~~~bash
git clone https://github.com/hamza1713/Enterprise-RAG-Chatbot-with-Role-Base-Access-Control-.git
cd Enterprise-RAG-Chatbot-with-Role-Base-Access-Control-
python -m venv .venv
# Activate .venv using the command for your operating system.
pip install -r requirements.txt
# Configure a local .env from .env.example, then start the backend and frontend as documented.
~~~

## Stack

Python · FastAPI · React · TypeScript · LangChain · Gemini · ChromaDB · DuckDB · SQLite · RAGAS · Docker · Nginx

## Related work

- [AI Code Review Agent](https://github.com/hamza1713/AI-Code-Review-Agent) — deterministic-first code intelligence and multi-agent review.
- [Factscope AI](https://github.com/hamza1713/Factscope-AI) — claim extraction and source-grounded analysis.
- [Portfolio](https://github.com/hamza1713/Portfolio) — project walkthroughs and contact details.

## License

MIT
