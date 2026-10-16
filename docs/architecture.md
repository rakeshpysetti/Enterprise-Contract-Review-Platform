# Architecture

The repository is a single FastAPI service backed by PostgreSQL. The API layer validates inputs and coordinates service calls; SQLAlchemy models and repositories own persistence; service modules implement PDF ingestion, metadata and clause extraction, risk and obligation analysis, semantic retrieval, and question answering.

## Request flow

Contract uploads are validated and parsed page by page. Cleaned page text is stored as contract chunks, preserving source page numbers. LlamaIndex's sentence splitter divides long pages into overlapping chunks; short pages stay intact. LangChain Core formats task-specific prompts without altering exact contract quotes. Analysis runs metadata extraction, obligation extraction, clause detection, and risk analysis, then persists the results and tracks the contract through `pending`, `processing`, `completed`, or `failed` states. Repeated analysis of completed contracts reuses stored results.

Search and question answering are scoped to one contract. Sentence Transformers creates normalized chunk vectors; FAISS stores an exact-search index per contract, while PostgreSQL retains the source chunks. Index metadata maps vector positions to chunk IDs and includes a content digest so changes to chunk text trigger a rebuild.

## Persistence and migrations

PostgreSQL is the production database. SQLAlchemy metadata defines contracts, chunks, obligations, risks, and clauses with cascading contract relationships. Alembic migrations are the schema source of truth. The development and production Compose stacks run a one-shot migration service after PostgreSQL becomes healthy and before starting the API. Apply migrations directly with `python -m alembic upgrade head` for a host-run deployment.

FAISS indexes and model downloads are generated local data. Compose stores both in named volumes; neither belongs in source control. Uploaded PDF files are processed through a temporary file and are not retained.

## Runtime boundaries

Ollama provides generation through the `LLMService` abstraction. Hugging Face Sentence Transformers provides embeddings. These services are isolated behind service interfaces so database, embedding, and language model behavior can be replaced or mocked in tests. Tests use SQLite, deterministic local embeddings, and mocked Ollama responses.

The API supports provisioned bearer access keys mapped to user IDs, tenant IDs, and reader/reviewer roles. Server configuration stores key digests. Production fails closed without configured accounts. A request-scoped database dependency authenticates users, applies tenant scope, checks contract ownership before any contract operation, and restricts mutation routes to reviewers. Contract repository reads and listings also filter by tenant. Existing records migrate to the `legacy` tenant. This is application-level tenant isolation; database administrators and trusted local scripts retain database access.

FastAPI serves the packaged buildless browser workspace at `/`. Credentials stay in browser memory, and contract/API identity responses disable caching. The interface renders contract/model text as text nodes and uses a restrictive content security policy. Production Compose binds to loopback by default; add TLS termination for remote access.

Analysis uses a committed processing claim with a unique attempt ID, followed by a fenced work transaction holding the PostgreSQL contract row lock. Results commit atomically. An explicit reviewer-only recovery route can release an old processing claim after the configured timeout; a non-waiting row lock protects live workers. A terminated worker's uncommitted extraction results roll back, and a superseded attempt cannot change a newer attempt's state.
