# Deployment candidate

This configuration is a single-host staging candidate. Docker is unavailable in the reviewed workspace, so image builds and startup must be verified in staging before a public release. See the production-readiness report for unresolved release gates.

## Configure

Copy `deploy/production.env.example` to `deploy/production.env`. Set a randomly generated stable JWT secret (at least 32 characters), a unique initial administrator password (at least 14 characters), your Google API key, and the exact public HTTPS origin. The secret file is ignored by Git.

The production environment creates only the initial administrator. It does not seed department demo accounts or preload sample documents. Existing accounts are preserved, so review and remove/rotate any old demo accounts before migrating a development database. Changing ADMIN_PASSWORD does not reset an existing user's password.

## Build and start

```sh
docker compose --env-file deploy/production.env -f docker-compose.production.yml config --quiet
docker compose --env-file deploy/production.env -f docker-compose.production.yml up --build -d
```

The frontend listens on host loopback port 8080. Place an HTTPS reverse proxy on the host in front of `127.0.0.1:8080`. The backend is reachable only on the internal Compose network. Nginx serves built assets and sends `/api/` requests to FastAPI with buffering disabled for streaming. Login throttling is keyed to the connecting IP: configure trusted forwarding at your HTTPS gateway before relying on individual client limits, since a host proxy may otherwise make all users share one IP.

Use one backend worker. The current indexer and evaluation locks are process-local and the application uses embedded databases; adding workers is not a supported scaling strategy yet. The backend runs as UID 10001. Verify named-volume permissions on the target platform.

## Release verification

1. Confirm the fresh administrator can sign in through HTTPS; verify login throttling and generic error responses.
2. Create department users with unique passwords. Verify cross-role denial for document lists, previews, uploads, SQL, and indexing controls.
3. Upload small CSV, Markdown, and PDF fixtures. Verify indexing, sources, retrieval quality, safe SQL execution, and authenticated downloads.
4. Verify deep links, reconnect behavior, mobile navigation, and error states in supported browsers.
5. Restart services during indexing and evaluation. Resolve interrupted jobs and verify no source documents are lost.
6. Back up the SQLite database, DuckDB files, uploaded documents, Chroma index, and evaluation outputs together while writes are stopped. Restore into a separate environment and verify role permissions and answers.
7. Measure memory, p95 request latency, provider errors, and cost under realistic concurrent load. Establish alerts and rollback ownership.

Named volumes hold application data and the search index. Do not use `down --volumes` on an environment whose data must be retained. This repository has not been deployed by the review task.
