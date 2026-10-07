# AI pipeline

The pipeline keeps source text and page references attached to each result so reviewers can trace extracted information to the contract.

## Analysis

PDF ingestion extracts text page by page, cleans it, and creates page-aware chunks. Analysis sends the relevant contract text to Ollama using task-specific prompts in `backend/app/ai/prompts`. Structured responses are validated with Pydantic before persistence. The pipeline extracts contract metadata, obligations, recognized clause types, and potential risks. It validates quoted source passages and page numbers against stored chunks before replacing previous analysis results.

Risk results use `LOW`, `MEDIUM`, `HIGH`, and `CRITICAL` levels and include category, description, why it matters, recommended review action, evidence, page, and confidence. Prompt instructions treat contract text as untrusted input and require cautious review language; generated findings are not legal advice.

## Retrieval and questions

Sentence Transformers generates normalized embeddings for chunks, and a per-contract FAISS index returns cosine-similarity-ranked results. PostgreSQL remains the source of truth for chunk text and page numbers. A JSON manifest maps FAISS positions to chunk UUIDs and records the embedding model and a digest of the ordered chunk IDs and text. The retrieval service checks this metadata and rebuilds stale or invalid indexes.

Question answering retrieves evidence only from the selected contract. Ollama receives the question and bounded retrieved excerpts, and returns an answer with chunk citations. The service verifies citations against retrieved evidence and returns excerpts, pages, and confidence. If the contract does not support an answer, the service returns an explicit no-answer response.

## Configuration and evaluation

`EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, `VECTOR_INDEX_DIR`, `RETRIEVAL_TOP_K`, and the `OLLAMA_*` settings control model and retrieval behavior. Tests use deterministic embeddings and mocked Ollama HTTP responses, so test runs need neither model downloads nor a running Ollama service.

The synthetic labeled dataset and evaluator are documented in [evaluation.md](evaluation.md). Its small reference metrics validate the evaluation code only; they do not represent live model quality.
