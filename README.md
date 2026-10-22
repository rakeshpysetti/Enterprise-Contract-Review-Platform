# Enterprise Contract Review Platform

This application helps legal and procurement teams review business contracts. Upload a PDF and it extracts important dates, payment terms, parties, obligations, common clauses, and potential risks. It also supports contract search and evidence-backed questions.

The project includes a browser workspace, FastAPI API, PostgreSQL storage, Ollama generation, Hugging Face embeddings, FAISS search, Docker deployment, and GitHub Actions checks.

## What it does

- Uploads and validates text-based PDF contracts.
- Extracts metadata, obligations, clauses, and risks.
- Links findings to the original text and page number.
- Searches within one contract using semantic similarity.
- Answers questions from retrieved contract evidence.
- Separates tenant data and supports reader and reviewer roles.
- Recovers analysis jobs interrupted by a process failure.
- Runs locally or as a single-host Docker deployment.

The model output is intended to support a human reviewer. It should not be treated as legal advice or an automatic final decision.

## Quick start with Docker

Docker Engine or Docker Desktop with Compose v2 is required. Copy `.env.example` to `.env`, then set `POSTGRES_PASSWORD` and `AUTH_ACCOUNTS`.

Generate an access key and account entry:

```sh
python scripts/provision_access.py --user alice --tenant acme --role reviewer
```

Keep the generated key for sign-in. Put the printed account object in the `AUTH_ACCOUNTS` JSON array. The server stores the key digest, not the plain key.

Start the production-style stack:

```sh
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml up -d --wait postgres ollama
docker compose -f docker-compose.prod.yml exec -T ollama ollama pull gemma3
docker compose -f docker-compose.prod.yml up --build -d --wait api
```

Open <http://127.0.0.1:8000>. API documentation is at <http://127.0.0.1:8000/docs>, and readiness is available at <http://127.0.0.1:8000/health/ready>.

Stop the stack without deleting its named volumes:

```sh
docker compose -f docker-compose.prod.yml down
```

## Local Python setup

Python 3.11 or newer is required. Docker uses Python 3.12.

```sh
python -m venv .venv
```

Activate the environment:

```sh
# Linux or macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the project and development tools:

```sh
python -m pip install -e ".[dev]"
```

When using PostgreSQL outside Docker, apply migrations before calling contract endpoints:

```sh
python -m alembic upgrade head
```

Start the API:

```sh
python -m uvicorn app.main:app --app-dir backend --reload
```

The API can start without PostgreSQL or Ollama, but `/health/ready` and model-backed features will not be ready until those services are available.

## Access keys, roles, and tenants

Production always requires configured accounts. Each account contains a user ID, tenant ID, role, and SHA-256 access-key digest.

```dotenv
AUTH_ACCOUNTS=[{"user_id":"alice","tenant_id":"acme","role":"reviewer","token_sha256":"<64-character digest>"}]
REQUIRE_AUTH=true
```

Enter the plain access key in the browser workspace or send it with API requests:

```http
Authorization: Bearer YOUR_ACCESS_KEY
```

Readers can browse contracts, search, and ask questions. Reviewers can also upload, analyze, and recover contracts. The tenant comes from the server-side account configuration; users cannot choose a tenant during upload. Requests for another tenant's contract return `404`.

The browser keeps the key in memory and clears it when the page reloads or the user signs out. Remove an account and restart the API to revoke a key. Replace its digest to rotate the key. The current system does not provide self-registration, password recovery, or SSO.

Development permits a local reviewer in the `legacy` tenant when no accounts are configured. Set `REQUIRE_AUTH=true` to require a key during local development.

## Contract workflow

Uploading a PDF creates the contract and page-aware text chunks with status `pending`. Analysis changes it to `processing`, then either `completed` or `failed`. A successful run stores metadata, obligations, clauses, risks, and the semantic index. Running analysis again on a completed contract returns the existing data with `analysis_reused: true`.

Uploads are checked by extension, media type, PDF signature, and PyMuPDF parsing. Encrypted, damaged, empty, textless, oversized, or over-limit PDFs are rejected. The application stores extracted text but does not keep the uploaded binary.

Long pages are divided into overlapping sentence chunks. Page numbers stay attached to every chunk. Source quotes and pages returned by the model are checked against those stored chunks before results are saved.

### Interrupted analysis

A stopped worker can leave a contract marked `processing`. A reviewer can use **Recover interrupted review** in the workspace or call:

```http
POST /contracts/{contract_id}/recover
```

Recovery is allowed after `ANALYSIS_RECOVERY_SECONDS`, which defaults to one hour. PostgreSQL row locking prevents recovery while a real worker is still active. Attempt IDs stop an older worker from writing over a newer retry.

## Search and questions

Sentence Transformers creates normalized chunk embeddings. FAISS stores one index per contract, while PostgreSQL keeps the source text and page numbers. The service rebuilds an index when the embedding model or contract content changes.

Search returns relevant excerpts, pages, and similarity scores. Question answering uses only retrieved text from the selected contract. Answers include supporting excerpts and page citations. When the evidence is insufficient, the API returns `answered: false` instead of inventing an answer.

## Useful API calls

Add an `Authorization` header to these examples when authentication is enabled.

```sh
curl -X POST http://localhost:8000/contracts \
  -F "file=@contract.pdf;type=application/pdf" \
  -F "title=Master Services Agreement"

curl http://localhost:8000/contracts
curl http://localhost:8000/contracts/CONTRACT_ID
curl -X POST http://localhost:8000/contracts/CONTRACT_ID/analyze
curl http://localhost:8000/contracts/CONTRACT_ID/summary

curl -X POST http://localhost:8000/contracts/CONTRACT_ID/search \
  -H "Content-Type: application/json" \
  -d '{"query":"termination notice","top_k":3}'

curl -X POST http://localhost:8000/contracts/CONTRACT_ID/questions \
  -H "Content-Type: application/json" \
  -d '{"question":"When are invoices due?","top_k":5}'
```

Contract listing supports `contract_type`, `party`, expiration-date ranges, and renewal-date ranges. Obligation listing accepts `priority`; risk listing accepts `severity`. Listing routes support `offset` and `limit`.

See [docs/api.md](docs/api.md) for the route summary.

## Configuration

Environment variables override the repository-root `.env`. Blank values use defaults.

| Variable | Default or purpose |
| --- | --- |
| `APP_ENV` | `development`; also accepts `test` and `production` |
| `AUTH_ACCOUNTS` | JSON array of users, tenants, roles, and key digests |
| `REQUIRE_AUTH` | `false` in development; production always requires accounts |
| `ANALYSIS_RECOVERY_SECONDS` | `3600` |
| `DATABASE_URL` | SQLAlchemy PostgreSQL connection URL |
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `gemma3` |
| `OLLAMA_TIMEOUT_SECONDS` | `120` |
| `OLLAMA_MAX_RETRIES` | `2` |
| `OLLAMA_RETRY_BACKOFF_SECONDS` | `0.5` |
| `OLLAMA_TEMPERATURE` | `0.0` |
| `OLLAMA_NUM_CTX` | `8192` |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `EMBEDDING_DEVICE` | `cpu` |
| `VECTOR_INDEX_DIR` | `data/vector_indexes` |
| `RETRIEVAL_TOP_K` | `5` |
| `MAX_PDF_SIZE_BYTES` | `26214400` (25 MiB) |
| `MAX_REQUEST_BODY_BYTES` | `65536`, plus the PDF allowance for uploads |
| `MAX_PDF_PAGES` | `200` |
| `MAX_CONTRACT_TEXT_CHARS` | `16000` |
| `MAX_CONCURRENT_MODEL_REQUESTS` | `1` per API process |
| `CORS_ORIGINS` | JSON array; empty disables cross-origin access |
| `CORS_ALLOW_CREDENTIALS` | `false` |
| `POSTGRES_DB`, `POSTGRES_USER` | `contracts` in Compose |
| `POSTGRES_PASSWORD` | Required by Compose |

Keep `.env` out of Git. Use hostname `postgres` from a Compose container and `localhost` from the host. Production CORS origins must be explicit HTTPS URLs, except for loopback development addresses.

## Logging and request limits

Every response includes request and correlation IDs. Structured access logs record route templates, status, and timing. They leave out request bodies, query strings, contract text, filenames, authorization values, and secrets.

Body limits are enforced before multipart or JSON parsing, including streamed requests without `Content-Length`. PDF parsing and persistence run in a worker thread so the async request loop remains responsive. Model concurrency is limited separately; when capacity is busy, the API returns `503` with `Retry-After`.

## Tests and checks

```sh
python -m pytest
python -m ruff check backend scripts
python -m mypy backend/app
```

The unit suite uses SQLite, deterministic embeddings, and mocked Ollama responses. It does not need a model download or live Ollama service. PostgreSQL locking, backup restoration, and live model behavior have separate integration checks.

Run the saved synthetic benchmark:

```sh
python scripts/evaluate_extraction.py --output data/evaluation/results.json
```

Run a real model through the API:

```sh
python scripts/evaluate_live.py --output-dir data/evaluation/live_runs/local
```

Set `CONTRACT_REVIEW_ACCESS_KEY` when authentication is enabled. Use a dedicated evaluation tenant because the runner uploads its generated contracts. See [docs/evaluation.md](docs/evaluation.md) for the scoring rules and limitations.

## Docker notes

The development stack publishes FastAPI, PostgreSQL, and Ollama ports. The production stack publishes only the API on loopback. PostgreSQL, Ollama, model cache, and FAISS indexes use named volumes.

The runtime image uses a non-root user, a read-only filesystem apart from the required volumes and `/tmp`, CPU-only PyTorch, pinned Linux dependencies, and pinned base/service image digests. Models are not downloaded automatically; pull the model named by `OLLAMA_MODEL` before expecting readiness to pass.

GitHub Actions runs formatting, linting, type checking, unit tests, and a Docker build. The manual **Live stack verification** workflow also starts PostgreSQL and Ollama, pulls a model, checks analysis recovery, and runs the live evaluation.

See [docs/production.md](docs/production.md) before using the application outside local development.

## Make targets

| Command | What it does |
| --- | --- |
| `make install` | Installs the project and development dependencies |
| `make run` | Starts the local API with reload |
| `make db-upgrade` | Applies Alembic migrations |
| `make test` | Runs pytest |
| `make lint` | Checks Python formatting and lint rules |
| `make typecheck` | Runs mypy |
| `make check` | Runs linting, type checking, and tests |
| `make evaluate` | Scores the saved reference predictions |
| `make docker-up` | Starts the development Compose stack |
| `make docker-down` | Stops it and keeps named volumes |
| `make docker-logs` | Follows service logs |
| `make docker-prod-up` | Starts the production Compose stack |
| `make docker-prod-down` | Stops the production stack |

On Windows without GNU Make, run the equivalent Python and Docker commands shown above.

## More documentation

- [Architecture](docs/architecture.md)
- [AI pipeline](docs/ai-pipeline.md)
- [API reference](docs/api.md)
- [Evaluation](docs/evaluation.md)
- [Production checklist](docs/production.md)
