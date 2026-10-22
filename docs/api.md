# API reference

Start the service and open `/docs` for the interactive OpenAPI page. PDF upload uses multipart form data; the other request bodies use JSON. Responses include `X-Request-ID` and `X-Correlation-ID`. Errors contain a readable `detail` plus an `error` object with a stable code and the request identifiers.

## Authentication

Send the access key as a bearer token:

```http
Authorization: Bearer YOUR_ACCESS_KEY
```

Production requires configured accounts. Contract IDs from another tenant return `404`, which avoids revealing that the record exists. Readers can use read, search, and question routes. Reviewers can also upload, analyze, and recover contracts.

- `GET /auth/me` returns the current user, tenant, and role.
- `GET /system/info` returns the configured language and embedding model names.

## Health

- `GET /health` checks that the API process is alive.
- `GET /health/ready` checks PostgreSQL, the configured Ollama model, and production access configuration. It returns `503` until the required services are ready.

## Contracts

- `POST /contracts` uploads a PDF. Form fields are `file` and optional `title`.
- `GET /contracts` lists contracts. Filters include `contract_type`, `party`, expiration-date bounds, and renewal-date bounds.
- `GET /contracts/{contract_id}` returns one contract and its stored metadata.
- `POST /contracts/{contract_id}/analyze` runs the full review. A completed result is reused.
- `POST /contracts/{contract_id}/recover` marks an abandoned analysis as failed so it can be retried. It returns `409` if a worker is active, the timeout has not passed, or the contract is not processing.
- `POST /contracts/{contract_id}/search` accepts `query` and optional `top_k`.
- `POST /contracts/{contract_id}/questions` accepts `question` and optional `top_k`. Unsupported questions return `answered: false`.
- `GET /contracts/{contract_id}/summary` returns important dates, obligation totals, key clauses, and risk counts.
- `GET /contracts/{contract_id}/obligations` lists obligations and accepts a `priority` filter.
- `GET /contracts/{contract_id}/risks` lists risks and accepts a `severity` filter.
- `GET /contracts/{contract_id}/clauses` lists detected clauses.

List routes accept `offset` and `limit`. Uploads are rejected when they are too large, encrypted, damaged, empty, textless, or not valid PDFs.

## Example

Add `-H "Authorization: Bearer $CONTRACT_REVIEW_ACCESS_KEY"` when authentication is enabled.

```sh
curl -X POST http://localhost:8000/contracts \
  -F "file=@contract.pdf;type=application/pdf" \
  -F "title=Master Services Agreement"

curl -X POST http://localhost:8000/contracts/CONTRACT_ID/analyze
curl "http://localhost:8000/contracts/CONTRACT_ID/risks?severity=high"
```
