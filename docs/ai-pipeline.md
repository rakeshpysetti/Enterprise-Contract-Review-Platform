# AI pipeline

Every extracted finding keeps its source text and page number. A reviewer should be able to move from a result back to the contract evidence without guessing where it came from.

## Ingestion and analysis

PyMuPDF reads the PDF page by page. The service cleans the text and stores it in page-aware chunks. LlamaIndex splits long pages into overlapping sentence chunks while leaving short pages intact.

Prompt templates live in `backend/app/ai/prompts`. LangChain formats them without changing quoted contract text or the user's question. Ollama returns structured JSON, and Pydantic validates the shape before the database is updated.

The analysis extracts:

- contract type, parties, dates, governing law, and payment terms;
- obligations and the parties responsible for them;
- supported clause types, including termination, renewal, payment, confidentiality, indemnification, liability, SLA, data protection, and dispute resolution;
- possible risks with severity, evidence, page number, confidence, and a suggested review action.

Before replacing saved results, the service checks each quoted passage and page number against the stored chunks. Model output is treated as a review aid, not legal advice.

## Search and questions

Sentence Transformers creates normalized vectors for the contract chunks. FAISS ranks them by cosine similarity. A JSON manifest records the embedding model, chunk IDs, and a digest of the indexed content. If the manifest or index is missing, invalid, or stale, the service rebuilds it.

For a question, retrieval selects a bounded set of excerpts from that contract only. Ollama answers from those excerpts and cites chunk IDs. The service rejects citations that were not part of the retrieved evidence. A supported answer includes excerpts, pages, and confidence. If the contract does not answer the question, the API returns `answered: false`, a null answer, no sources, and zero confidence.

## Settings and testing

The main controls are `EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, `VECTOR_INDEX_DIR`, `RETRIEVAL_TOP_K`, and the `OLLAMA_*` variables. Unit tests use local deterministic vectors and mocked Ollama calls, so they do not download models.

See [evaluation.md](evaluation.md) for the labeled fixtures and scoring rules. Those fixtures are useful for regression testing, but they are too small to establish legal-review quality.
