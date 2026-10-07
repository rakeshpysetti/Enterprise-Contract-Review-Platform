# API reference

The FastAPI OpenAPI document is available at `/docs` while the service is running. All routes use JSON except PDF upload. Errors use a consistent response with `detail` and an `error` object containing a stable code and request identifiers. Responses include `X-Request-ID` and `X-Correlation-ID`.

## Health

- `GET /health` reports process liveness and does not contact dependencies.
- `GET /health/ready` checks PostgreSQL and Ollama and returns `503` until both are reachable.

## Contracts

- `POST /contracts` accepts multipart `file` and optional `title`. It validates and parses a PDF, creates the contract and page-aware chunks, and returns the new contract.
- `GET /contracts` lists contracts. Supports `offset`, `limit`, `contract_type`, `party`, inclusive expiration date bounds (`expiration_date_from`, `expiration_date_to`), and inclusive renewal date bounds (`renewal_date_from`, `renewal_date_to`).
- `GET /contracts/{contract_id}` returns contract detail.
- `POST /contracts/{contract_id}/analyze` runs extraction and risk/clause analysis. Completed analysis is reused unless the contract requires processing.
- `POST /contracts/{contract_id}/search` accepts `query` and optional `top_k`, returning relevant excerpts, page numbers, and similarity scores from that contract only.
- `POST /contracts/{contract_id}/questions` accepts `question` and optional `top_k`, returning a grounded answer, source excerpts, page citations, and confidence. If evidence is insufficient, it returns `answered: false` with a null answer.
- `GET /contracts/{contract_id}/summary` returns risk counts and overall level, obligation count, important dates, and key clauses.
- `GET /contracts/{contract_id}/obligations` lists obligations and supports `priority` filtering.
- `GET /contracts/{contract_id}/risks` lists risks and supports `severity` filtering.
- `GET /contracts/{contract_id}/clauses` lists detected clauses.

The four listing routes support `offset` and `limit`. Contract-scoped routes return `404` when the contract does not exist. Upload size is limited by `MAX_PDF_SIZE_BYTES`; invalid, encrypted, damaged, empty, or textless PDFs are rejected.

## Local example

```sh
curl -X POST http://localhost:8000/contracts \
  -F "file=@contract.pdf;type=application/pdf" \
  -F "title=Master Services Agreement"
curl -X POST http://localhost:8000/contracts/CONTRACT_ID/analyze
curl "http://localhost:8000/contracts/CONTRACT_ID/risks?severity=high"
```
