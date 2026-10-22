# Architecture

This project runs as one FastAPI application backed by PostgreSQL. The API handles validation and authorization, repository classes handle database access, and service modules do the contract processing. Keeping those responsibilities separate makes the model, vector store, and database easier to test or replace.

## How a contract moves through the system

An upload starts as a PDF. The ingestion service checks the file, extracts text one page at a time, cleans it, and stores page-aware chunks. Short pages stay together. LlamaIndex splits longer pages into overlapping sentence chunks so retrieval does not lose the surrounding context.

Analysis has four main jobs: metadata extraction, obligation extraction, clause detection, and risk review. LangChain templates build the prompts, Ollama generates structured responses, and Pydantic validates them before anything is saved. A contract moves through `pending`, `processing`, `completed`, or `failed`. If a completed contract is analyzed again, the API returns the saved result instead of calling the models again.

Search and questions always stay inside one contract. Sentence Transformers creates normalized embeddings, and FAISS keeps one exact-search index per contract. PostgreSQL remains the source of truth for the chunk text and page numbers. The FAISS manifest maps vector positions back to chunk IDs and records a content digest; when the chunks change, the index is rebuilt.

## Data and migrations

PostgreSQL stores contracts, chunks, obligations, clauses, and risks. Child rows use cascading foreign keys, so removing a contract also removes its related analysis data. Alembic owns the schema history.

Both Compose files run migrations after PostgreSQL is healthy and before the API starts. For a host-run setup, apply them with:

```sh
python -m alembic upgrade head
```

FAISS indexes and downloaded models are generated data. Docker keeps them in named volumes, and Git ignores them. Uploaded PDF binaries are used during ingestion but are not retained.

## External services

Ollama sits behind the `LLMService` interface. Hugging Face Sentence Transformers provides embeddings. Tests replace these dependencies with deterministic embeddings and mocked HTTP responses, and use SQLite where PostgreSQL-specific locking is not being tested.

## Access control

Access keys map to a user ID, tenant ID, and either a `reader` or `reviewer` role. The server stores only a SHA-256 digest of each key. Production refuses protected requests until at least one account is configured.

Tenant checks happen before contract work begins, and repository queries also filter by tenant. Readers can view, search, and ask questions. Reviewers can also upload, analyze, and recover contracts. Records created before tenant support belong to the reserved `legacy` tenant.

The browser workspace is served from `/`. It keeps the access key in memory, avoids caching identity and contract responses, and renders contract content as text rather than HTML. Production Compose binds the API to loopback by default; remote deployments need an HTTPS reverse proxy.

## Analysis locking and recovery

Each analysis receives a unique attempt ID. The worker claims the contract, then performs the write inside a transaction while holding the PostgreSQL row lock. Results are committed together, so a failed worker does not leave half-written analysis data.

A reviewer can recover an abandoned `processing` contract after the configured timeout. Recovery uses a non-blocking row lock, which means it returns `409` while a real worker still owns the contract. Attempt IDs also prevent an old worker from overwriting a newer retry.
