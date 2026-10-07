# Architecture

The repository is a single FastAPI service backed by PostgreSQL. The API layer validates inputs and coordinates service calls; SQLAlchemy models and repositories own persistence; service modules implement PDF ingestion, metadata and clause extraction, risk and obligation analysis, semantic retrieval, and question answering.

## Request flow

Contract uploads are validated and parsed page by page. Cleaned page text is stored as contract chunks, preserving source page numbers. Analysis runs metadata extraction, obligation extraction, clause detection, and risk analysis, then persists the results and tracks the contract through `pending`, `processing`, `completed`, or `failed` states. Repeated analysis of completed contracts reuses stored results.

Search and question answering are scoped to one contract. Sentence Transformers creates normalized chunk vectors; FAISS stores an exact-search index per contract, while PostgreSQL retains the source chunks. Index metadata maps vector positions to chunk IDs and includes a content digest so changes to chunk text trigger a rebuild.

## Persistence and migrations

PostgreSQL is the production database. SQLAlchemy metadata defines contracts, chunks, obligations, risks, and clauses with cascading contract relationships. Alembic migrations are the schema source of truth. The development and production Compose stacks run a one-shot migration service after PostgreSQL becomes healthy and before starting the API. Apply migrations directly with `python -m alembic upgrade head` for a host-run deployment.

FAISS indexes and model downloads are generated local data. Compose stores both in named volumes; neither belongs in source control. Uploaded PDF files are processed through a temporary file and are not retained.

## Runtime boundaries

Ollama provides generation through the `LLMService` abstraction. Hugging Face Sentence Transformers provides embeddings. These services are isolated behind service interfaces so database, embedding, and language model behavior can be replaced or mocked in tests. Tests use SQLite, deterministic local embeddings, and mocked Ollama responses.

The API has no built-in user authentication or tenant authorization. Keep the production Compose bind address on loopback unless the deployment adds an authenticated, TLS-terminating access layer and appropriate tenant isolation.
