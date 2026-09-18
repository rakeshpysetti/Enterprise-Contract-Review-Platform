# Enterprise Contract Review & Obligation Extraction Platform

A platform for reviewing enterprise contracts and extracting contractual obligations to support organized analysis and tracking. It provides a FastAPI application, PDF ingestion, PostgreSQL persistence, contract-scoped semantic retrieval, tests, and local development containers. Obligation extraction, risk analysis, and question answering remain placeholders.

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

Copy `.env.example` to `.env` (`cp .env.example .env` on Linux/macOS or `Copy-Item .env.example .env` in PowerShell). All example values are intentionally blank. The API can start without external services or a database URL.

```sh
python -m uvicorn app.main:app --app-dir backend --reload
```

Open <http://localhost:8000/health> for `{"status":"ok"}` or <http://localhost:8000/docs> for interactive API documentation. `/health` checks process liveness only; it does not verify PostgreSQL or Ollama availability. Stop the server with Ctrl+C.

Upload a PDF as multipart form data; `title` is optional and defaults to the filename:

```sh
curl -X POST http://localhost:8000/contracts \
  -F "file=@contract.pdf;type=application/pdf" \
  -F "title=Master Services Agreement"
curl http://localhost:8000/contracts
curl http://localhost:8000/contracts/CONTRACT_ID
curl -X POST http://localhost:8000/contracts/CONTRACT_ID/search \
  -H "Content-Type: application/json" \
  -d '{"query":"What are the termination notice requirements?","top_k":3}'
```

Uploads are validated by extension, media type, PDF signature, and PyMuPDF parsing. Text is cleaned and stored as one chunk per non-empty page with its original page number. Password-protected, damaged, empty, textless, and oversized PDFs are rejected. Uploaded binaries are not retained.

## Configuration

Environment variables override the repository-root `.env` file. Blank values use defaults; unknown keys are ignored so Compose settings can share the same file.

| Variable | Default / purpose |
| --- | --- |
| `APP_NAME` | Project name displayed in API documentation |
| `APP_ENV` | `development`; also accepts `test` and `production` |
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
| `POSTGRES_DB`, `POSTGRES_USER` | Compose defaults to `contracts` |
| `POSTGRES_PASSWORD` | Required for Compose; choose a local password in `.env` |

Keep `.env` out of Git. The application uses SQLAlchemy with the Psycopg driver. A database connection running inside Compose uses hostname `postgres`; one running on the host uses `localhost`.

The `LLMService` abstraction connects to Ollama through its non-streaming generation API. It supports plain text and Pydantic-validated structured JSON output, configured timeouts, retries for connection failures, HTTP 429 responses, and server errors, plus explicit errors for malformed model responses. The contract extraction chain uses a packaged prompt to extract and store title, type, parties, effective, expiration and renewal dates, governing law, and payment terms. Missing or ambiguous facts remain null rather than being inferred. Pull the configured model before use, for example `docker compose exec ollama ollama pull gemma3`. No model is downloaded automatically.

Semantic retrieval uses a Hugging Face Sentence Transformers model and normalized vectors stored in a contract-specific FAISS exact-search index. Each index has JSON metadata mapping FAISS positions to database chunk UUIDs. `POST /contracts/{contract_id}/search` returns relevant text, source page numbers, and cosine similarity scores. The index is created lazily and rebuilt when its model or contract chunks change. Index files under `data/vector_indexes` are local generated data and are excluded from Git; Compose persists them in the `vector_index_data` volume. The first real embedding request downloads the configured model from Hugging Face; tests use deterministic local embeddings and perform no model download.

## Tests

```sh
python -m pytest
```

Tests cover health and OpenAPI behavior, environment settings, SQLAlchemy models and repositories, PDF ingestion, semantic retrieval, Ollama generation and retries, schema validation, and secret redaction. Database tests use isolated in-memory SQLite, embedding tests use deterministic local vectors, and Ollama tests use a mock HTTP transport. Tests do not require PostgreSQL, Ollama, or model downloads.

## Docker development

Requires Docker Engine or Docker Desktop with Compose v2. Create `.env` and set `POSTGRES_PASSWORD` before running:

```sh
docker compose config --quiet
docker compose up --build -d
docker compose logs -f api
docker compose down
```

FastAPI listens on localhost:8000 with source reload, PostgreSQL on localhost:5432, and Ollama on localhost:11434. API startup waits for PostgreSQL health and for the Ollama container to start. PostgreSQL and Ollama use named volumes; `docker compose down` preserves them. Models are not downloaded automatically.

The Dockerfile runs the API as a non-root user and includes a health check. `docker-compose.prod.yml` and GitHub workflows remain placeholders; this Compose configuration is for local development.

## Make commands

With GNU Make installed and the virtual environment activated:

| Command | Action |
| --- | --- |
| `make install` | Install the project and test dependencies |
| `make run` | Start the local API with reload |
| `make test` | Run pytest |
| `make docker-config` | Validate Compose configuration |
| `make docker-up` | Build and start development services |
| `make docker-down` | Stop services while preserving volumes |
| `make docker-logs` | Follow service logs |

On Windows without Make, use the equivalent Python and Docker commands above. Override the interpreter with `make test PYTHON=python3` when needed.
