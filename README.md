# Enterprise Contract Review & Obligation Extraction Platform

A platform for reviewing enterprise contracts and extracting contractual obligations to support organized analysis and tracking. It provides a browser review workspace, a FastAPI application, provisioned user access with tenant isolation, PDF ingestion, PostgreSQL persistence, contract metadata, obligation and risk extraction, clause detection, contract-scoped semantic retrieval and question answering, tests, and local development containers.

## Local setup

Requires Python 3.11 or newer (Docker uses Python 3.12). Run commands from the repository root.

```sh
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead:
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

When using a PostgreSQL database outside Docker, apply the schema before using contract endpoints:

```sh
python -m alembic upgrade head
```

Copy `.env.example` to `.env` (`cp .env.example .env` on Linux/macOS or `Copy-Item .env.example .env` in PowerShell). Replace placeholder database credentials before using PostgreSQL. The API can start without external services or a database URL.

```sh
python -m uvicorn app.main:app --app-dir backend --reload
```

Open <http://localhost:8000/health> for `{"status":"ok"}` or <http://localhost:8000/docs> for interactive API documentation. `/health` checks process liveness only; it does not verify PostgreSQL or Ollama availability. Stop the server with Ctrl+C.

Open <http://localhost:8000/> for the review workspace. It supports PDF upload, party/type filters, paginated contract browsing, metadata, obligations, risks, clauses, source pages, grounded questions, semantic search, and interrupted review recovery. The interface is served by FastAPI and included in the Python package and Docker image; no separate frontend build is required.

## User access and tenants

Production always requires authentication. It returns `503` for protected endpoints until accounts are configured, and `401` for missing or invalid credentials. Development without accounts permits a local reviewer in the `legacy` tenant; set `REQUIRE_AUTH=true` to require credentials in development too. Configuring any account automatically enables authentication.

Generate a separate access key for each user:

```sh
python scripts/provision_access.py --user alice --tenant acme --role reviewer
```

Give the generated key to that user securely. Merge the printed account object into the `AUTH_ACCOUNTS` JSON array in `.env`. Only the SHA-256 digest is configured on the server; use the generated high-entropy keys rather than human passwords. An example configuration shape (replace the digest with the generated value) is:

```dotenv
AUTH_ACCOUNTS=[{"user_id":"alice","tenant_id":"acme","role":"reviewer","token_sha256":"<generated 64-character lowercase digest>"}]
REQUIRE_AUTH=true
```

Users enter their key in the workspace or send `Authorization: Bearer <key>` to the API. Swagger's **Authorize** button supports bearer keys. The browser retains the key in memory only; signing out or reloading clears it. `GET /auth/me` returns the authenticated user, tenant, and role. `GET /system/info` returns configured model names for evaluation provenance. Health endpoints and the sign-in page remain public.

`reader` users can browse, search, and ask questions. `reviewer` users can also upload, analyze, and recover reviews. Tenant membership comes from the server account configuration. Uploads inherit that tenant; contract listings and all contract routes enforce ownership, returning `404` for another tenant's IDs. Removing an account and restarting the service revokes its key; replace the digest to rotate a key. This is provisioned key authentication, without self-registration, password recovery, or SSO.

Existing contracts migrate into the reserved `legacy` tenant. Assign a user to that tenant to review them, or move ownership through a controlled database migration after verifying the intended owner. Do not assign different organizations the same tenant ID. Run behind HTTPS for remote use, keep `.env` private, and restart all API instances after changing accounts.

## Recovering interrupted analysis

An API process terminated during a review can leave a durable `processing` claim. A reviewer can call `POST /contracts/{contract_id}/recover` or use **Recover interrupted review** in the workspace. Recovery is allowed only after `ANALYSIS_RECOVERY_SECONDS` (default 3600), changes the abandoned attempt to `failed`, and enables a fresh analysis request. It does not invoke a model itself.

On PostgreSQL, an active worker holds the contract row lock until its analysis transaction commits or rolls back. Recovery uses a non-waiting row lock and returns `409` while that worker is active, even after the timeout. Attempt IDs fence workers superseded before the work transaction starts; an old worker cannot write results or mark a newer attempt as failed. Recovery is explicit rather than automatically retrying every old request. SQLite supports local testing but PostgreSQL is required for production concurrency guarantees.

Upload a PDF with `POST /contracts`, then run its complete review with `POST /contracts/{contract_id}/analyze`. Upload creates cleaned, page-aware chunks and leaves the contract in `pending`. Analysis moves it through `processing` to `completed`, or to `failed` when a step cannot finish. It creates or refreshes the semantic index when required, extracts and persists metadata, obligations, detected clauses, and risks, and returns the complete stored result. Repeating analysis for a completed contract returns the existing result with `analysis_reused: true` without calling the embedding or language models again.

Upload a PDF as multipart form data; `title` is optional and defaults to the filename:

```sh
curl -X POST http://localhost:8000/contracts \
  -F "file=@contract.pdf;type=application/pdf" \
  -F "title=Master Services Agreement"
curl http://localhost:8000/contracts
curl http://localhost:8000/contracts/CONTRACT_ID
curl "http://localhost:8000/contracts?contract_type=NDA&expiration_date_to=2027-12-31&party=Acme"
curl "http://localhost:8000/contracts/CONTRACT_ID/obligations?priority=high"
curl "http://localhost:8000/contracts/CONTRACT_ID/risks?severity=critical"
curl "http://localhost:8000/contracts/CONTRACT_ID/clauses"
curl "http://localhost:8000/contracts/CONTRACT_ID/summary"
curl -X POST http://localhost:8000/contracts/CONTRACT_ID/search \
  -H "Content-Type: application/json" \
  -d '{"query":"What are the termination notice requirements?","top_k":3}'
curl -X POST http://localhost:8000/contracts/CONTRACT_ID/questions \
  -H "Content-Type: application/json" \
  -d '{"question":"When are invoices due?","top_k":5}'
```

Uploads are validated by extension, media type, PDF signature, and PyMuPDF parsing. Text is cleaned and stored with its original page number. LlamaIndex's sentence splitter keeps short pages intact and divides longer pages into bounded, overlapping chunks for embedding and retrieval. Password-protected, damaged, empty, textless, and oversized PDFs are rejected. Uploaded binaries are not retained.

Contract listing supports `contract_type`, `party`, inclusive `expiration_date_from` and `expiration_date_to`, and inclusive `renewal_date_from` and `renewal_date_to` query filters. Party matching is case-insensitive against party names. Contract, obligation, risk, and clause listings support `offset` and `limit`. Obligation listings accept a `priority` filter, and risk listings accept a `severity` filter.

`GET /contracts/{contract_id}/summary` returns severity counts, the highest persisted risk level, obligation count, effective, expiration, and renewal dates, and detected key clauses with source excerpts, pages, and confidence.

## Configuration

Environment variables override the repository-root `.env` file. Blank values use defaults; unknown keys are ignored so Compose settings can share the same file.

| Variable | Default / purpose |
| --- | --- |
| `APP_NAME` | Project name displayed in API documentation |
| `APP_ENV` | `development`; also accepts `test` and `production` |
| `AUTH_ACCOUNTS` | JSON array of user ID, tenant ID, role, and token SHA-256 digest |
| `REQUIRE_AUTH` | `false` for local development; production always requires access accounts |
| `ANALYSIS_RECOVERY_SECONDS` | `3600`; minimum 60 seconds before abandoned review recovery |
| `DATABASE_URL` | SQLAlchemy PostgreSQL URL; defaults to the local Compose-compatible database |
| `OLLAMA_BASE_URL` | `http://localhost:11434`; Compose overrides it to `http://ollama:11434` |
| `OLLAMA_MODEL` | `gemma3` |
| `OLLAMA_TIMEOUT_SECONDS` | `120` seconds per request |
| `OLLAMA_MAX_RETRIES` | `2` retries after the initial request |
| `OLLAMA_RETRY_BACKOFF_SECONDS` | `0.5`, with exponential backoff |
| `OLLAMA_TEMPERATURE` | `0.0`; accepts values from 0 to 2 |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `EMBEDDING_DEVICE` | `cpu`; set to a supported accelerator when available |
| `VECTOR_INDEX_DIR` | `data/vector_indexes` |
| `RETRIEVAL_TOP_K` | `5`; accepts values from 1 to 100 |
| `UPLOAD_DIR` | `data/sample_contracts` |
| `PROCESSED_DIR` | `data/processed` |
| `MAX_PDF_SIZE_BYTES` | `26214400` (25 MiB) |
| `CORS_ORIGINS` | JSON array of allowed origins; empty disables cross-origin access |
| `CORS_ALLOW_CREDENTIALS` | `false`; wildcard origins cannot enable credentials |
| `POSTGRES_DB`, `POSTGRES_USER` | Compose defaults to `contracts` |
| `POSTGRES_PASSWORD` | Required for Compose; choose a local password in `.env` |

Keep `.env` out of Git. The application uses SQLAlchemy with the Psycopg driver. A database connection running inside Compose uses hostname `postgres`; one running on the host uses `localhost`.

Every response includes `X-Request-ID` and `X-Correlation-ID`. Callers may supply either header using letters, digits, `.`, `_`, or `-`, up to 128 characters. API errors use a centralized JSON shape containing `detail` and an `error` object with a stable code and request identifiers. Access logs are structured JSON and contain route templates and timing metadata only; request bodies, query strings, uploaded filenames, contract text, authorization values, and secrets are excluded or redacted. Uploads are streamed through an automatically deleted spooled temporary file and rejected as soon as `MAX_PDF_SIZE_BYTES` is exceeded.

The `LLMService` abstraction connects to Ollama through its non-streaming generation API. It supports plain text and Pydantic-validated structured JSON output, configured timeouts, retries for connection failures, HTTP 429 responses, and server errors, plus explicit errors for malformed model responses. LangChain Core templates assemble the five task prompts while preserving contract evidence verbatim. Packaged prompts drive contract metadata, obligation and risk extraction, and detection of termination, renewal, payment, confidentiality, indemnification, limitation of liability, SLA, data protection, and dispute resolution clauses. Risk extraction uses cautious review language and stores severity, category, why-it-matters context, recommended review action, exact source quote, page number, and confidence. Source quotes and page references are validated against the stored contract before prior results are replaced. Pull the configured model before use, for example `docker compose exec ollama ollama pull gemma3`. No model is downloaded automatically.

Semantic retrieval uses a Hugging Face Sentence Transformers model and normalized vectors stored in a contract-specific FAISS exact-search index. Each index has JSON metadata mapping FAISS positions to database chunk UUIDs. `POST /contracts/{contract_id}/search` returns relevant text, source page numbers, and cosine similarity scores. The index is created lazily and rebuilt when its model or contract chunks change. Index files under `data/vector_indexes` are local generated data and are excluded from Git; Compose persists them in the `vector_index_data` volume. The first real embedding request downloads the configured model from Hugging Face; tests use deterministic local embeddings and perform no model download. LlamaIndex Core is used for long-page sentence segmentation; FAISS and SQLAlchemy remain the index and storage layers.

`POST /contracts/{contract_id}/questions` retrieves context only from the selected contract and sends that context to Ollama. Answers include the supporting chunk excerpts, page citations, and a confidence score. Model citations are checked against the retrieved chunks. When the retrieved contract text does not answer a question, the response uses `answered: false`, a null answer, no sources, and zero confidence.

## Tests

```sh
python -m pytest
```

Tests cover health and OpenAPI behavior, environment settings, SQLAlchemy models and repositories, PDF ingestion, semantic retrieval, Ollama generation and retries, schema validation, and secret redaction. Database tests use isolated in-memory SQLite, embedding tests use deterministic local vectors, and Ollama tests use a mock HTTP transport. Tests do not require PostgreSQL, Ollama, or model downloads.

## Evaluation

Run the small synthetic contract benchmark and write deterministic metrics to `data/evaluation/results.json`:

```sh
python scripts/evaluate_extraction.py --output data/evaluation/results.json
```

See [docs/evaluation.md](docs/evaluation.md) for the dataset format, metric definitions, reference results, and limitations.

To measure actual model output against the expanded six-contract synthetic dataset on a running stack:

```sh
python scripts/evaluate_live.py --output-dir data/evaluation/live_runs/local
```

Set `CONTRACT_REVIEW_ACCESS_KEY` in your shell when authentication is enabled. The runner uses real PDF upload, analysis, stored-result reuse, summary, semantic search, and questions; it saves actual predictions, model names, dataset hash, and metrics. Evaluation uploads remain in the selected tenant, so use a dedicated evaluation tenant. It requires the configured Ollama model and embedding model to be available. It never substitutes saved predictions when services fail.

The manually triggered **Live stack verification** workflow builds the production Docker image, starts PostgreSQL and Ollama, applies migrations, downloads a selected model, checks PostgreSQL lock/recovery behavior, and runs this evaluation. It retains predictions and metrics as workflow artifacts. Small models may fail schema/evidence validation; a completed workflow verifies integration, not acceptable model quality. This workflow is not run by the ordinary mocked test suite.

## Docker development

Requires Docker Engine or Docker Desktop with Compose v2. Create `.env` and set `POSTGRES_PASSWORD` before running:

```sh
docker compose config --quiet
docker compose up --build -d --wait
docker compose logs -f api
docker compose down
```

FastAPI listens on localhost:8000 with source reload, PostgreSQL on localhost:5432, and Ollama on localhost:11434. PostgreSQL is checked with `pg_isready`, Ollama is checked with `ollama list`, and the API readiness check queries both dependencies. The API starts after both services are healthy. PostgreSQL, Ollama, and FAISS indexes use named volumes; `docker compose down` preserves them. Models are not downloaded automatically.

Use `/health` for process liveness and `/health/ready` for API-to-PostgreSQL and API-to-Ollama connectivity. The readiness endpoint returns HTTP 503 until both connections succeed.

For the production Compose stack, set `POSTGRES_PASSWORD` and optionally `API_BIND_ADDRESS`, `API_PORT`, `CORS_ORIGINS`, and `OLLAMA_IMAGE`, then run:

```sh
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml up --build -d --wait
docker compose -f docker-compose.prod.yml ps
curl http://127.0.0.1:8000/health/ready
```

The production stack omits source mounts and host ports for PostgreSQL and Ollama, runs the API filesystem read-only apart from its FAISS volume and `/tmp`, and restarts services unless stopped.

The Dockerfile runs the API as a non-root user, installs CPU-only PyTorch to match the default CPU embedding device without bundling CUDA libraries, and includes a liveness check. GitHub Actions runs linting, type checking, tests with mocked Ollama, and a Docker image build on pushes and pull requests to `main`. The production Compose stack is available in `docker-compose.prod.yml`.

## Make commands

With GNU Make installed and the virtual environment activated:

| Command | Action |
| --- | --- |
| `make install` | Install the project and test dependencies |
| `make run` | Start the local API with reload |
| `make db-upgrade` | Apply database schema migrations |
| `make test` | Run pytest |
| `make lint` | Check formatting and lint Python sources |
| `make typecheck` | Type-check application code, scripts, and migrations |
| `make check` | Run linting, type checking, and tests |
| `make evaluate` | Evaluate the reference prediction snapshot |
| `make docker-config` | Validate Compose configuration |
| `make docker-up` | Build and start development services |
| `make docker-down` | Stop services while preserving volumes |
| `make docker-logs` | Follow service logs |
| `make docker-prod-config` | Validate production Compose configuration |
| `make docker-prod-up` | Build and start the production stack and wait for health |
| `make docker-prod-down` | Stop the production stack |

On Windows without Make, use the equivalent Python and Docker commands above. Override the interpreter with `make test PYTHON=python3` when needed.
