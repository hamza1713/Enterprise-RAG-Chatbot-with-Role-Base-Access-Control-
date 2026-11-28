# Production Deployment Guide

FinSight runs as a stateless, horizontally scalable stack backed by PostgreSQL 17 (`pgvector` / `pgvectorscale`), Redis 7 + Taskiq async workers, S3-compatible object storage (RustFS container by default, or AWS S3), and a `docling-serve-cpu` PDF/OCR sidecar. Put an HTTPS reverse proxy in front of host port `8080`.

## Configure

Copy `deploy/production.env.example` to `deploy/production.env`. Set:
- `JWT_SECRET` (random string >= 32 characters)
- `ADMIN_PASSWORD` (unique initial administrator password >= 14 characters)
- `POSTGRES_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`
- `GOOGLE_API_KEY` (and optional `COHERE_API_KEY`)
- `CORS_ORIGINS` (exact public HTTPS origin)

The production environment seeds only the initial administrator (`C-Level`) and system roles (`C-Level`, `General`). Changing `ADMIN_PASSWORD` later does not reset an existing user password.

## Build, Migrate, and Start

```sh
docker compose --env-file deploy/production.env -f docker-compose.production.yml config --quiet
docker compose --env-file deploy/production.env -f docker-compose.production.yml up --build -d
```

The `migrate` service runs `alembic upgrade head` once before launching `backend` (`--workers ${UVICORN_WORKERS:-2}`) and `worker` (`taskiq worker app.workers.broker:broker --workers 2`), ensuring multi-worker startup does not race DDL migrations.

## Architecture Notes

- **Database & Vector Store**: PostgreSQL 17 stores users (including `is_active` and `token_version` for immediate JWT revocation), roles, documents, contextual chunks (`tsvector` + 1536-dim `vector`), CSV table metadata, durable `jobs`, and `evaluation_runs`.
- **Object Storage & Parquet SQL Sandbox**: Raw uploaded documents, Parquet conversions of uploaded CSVs, and evaluation HTML/CSV artifacts live in S3-compatible storage (`STORAGE_BACKEND=s3`). Natural-language SQL queries stream only referenced authorized Parquet datasets into an ephemeral `:memory:` DuckDB sandbox per request.
- **PDF/OCR Parsing**: The worker routes `.pdf` documents to `docling-serve-cpu` (`/v1/convert/file`) and automatically falls back to `pdfplumber` if the sidecar is unavailable.
- **Edge Gateway**: Nginx proxies `/api/` to the multi-worker backend with buffering disabled (`client_max_body_size 25m` matches FastAPI's 20 MB upload ceiling). Configure `TRUSTED_PROXY_IPS` to match your upstream TLS reverse proxy.

## Backup & Verification

Back up `pg-data`, `rustfs-data`, and `redis-data` consistently together. Do not use `docker compose down --volumes` on an environment whose data must be retained.
