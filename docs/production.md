# Production checklist

`docker-compose.prod.yml` is designed for one Docker host and a modest workload. Passing `/health/ready` means the API can reach PostgreSQL, find the configured Ollama model, and load access accounts. It says nothing about model accuracy, backups, or available capacity.

## Before launch

1. Choose a strong `POSTGRES_PASSWORD`. Create a separate access key for every user and tenant, and keep `.env` outside source control.
2. Leave the API bound to loopback and place an HTTPS reverse proxy in front of it. Configure rate and request-size limits there. Add only the required HTTPS origins to `CORS_ORIGINS`.
3. Pin the Ollama image and model used for the release. Pull the model before starting the API. Confirm that the host has enough memory and disk for Ollama, embeddings, PostgreSQL, and FAISS indexes.
4. Check the Compose file and apply migrations:

   ```sh
   docker compose -f docker-compose.prod.yml config --quiet
   docker compose -f docker-compose.prod.yml up -d --wait
   ```

5. Confirm that `/health/ready` returns `200`. Run the live evaluation in an isolated tenant and inspect both the predictions and scores.
6. Test concurrent requests, abandoned-analysis recovery, and a complete backup restore on the target host.

The default limits are 200 PDF pages, 16,000 cleaned characters, and an Ollama context size of 8,192 tokens. Character count is only a rough proxy for tokens. Test the largest contract you plan to accept and adjust `MAX_PDF_PAGES`, `MAX_CONTRACT_TEXT_CHARS`, and `OLLAMA_NUM_CTX` together.

## Day-to-day operations

Watch `/health/ready`, response latency, API errors, Ollama failures, PostgreSQL capacity, free disk space, and contracts left in `failed` or stale `processing` states. Investigate a failed analysis before retrying it.

This deployment uses one API worker. `MAX_CONCURRENT_MODEL_REQUESTS` defaults to 1 per process. While Ollama is busy, another model request receives `503` with `Retry-After: 30`. Raise the limit only after measuring memory use and response time under load.

Back up PostgreSQL and the `vector_index_data` and `ollama_data` volumes. PostgreSQL is the critical copy because it contains the contract text and review results. FAISS indexes can be rebuilt. Encrypt backups, restrict access, keep a retention policy, and store a copy away from the Docker host.

Use the included restore check as a local smoke test:

```sh
python scripts/verify_postgres_backup.py
```

The script restores a dump into a temporary database and checks migrations and table counts. It does not replace an off-host recovery rehearsal.

If a release fails, stop new analyses, preserve the current database and volume snapshots, and roll back the application image. Restore an older database only when the migration cannot be recovered safely and there is a clear plan for data created after that backup.

## Current release limits

- Only text-based PDFs are supported. Scanned documents need OCR.
- Access keys are provisioned manually. There is no SSO, self-service account management, or automatic key rotation.
- Remote deployment still needs an HTTPS reverse proxy and operational monitoring.
- Backup and restore must be tested away from the application host.
- Model quality has not reached a production acceptance threshold.

The local live evaluation completed on October 22, 2026 with `gemma3:4b`. Exact-match scoring found 32 of 48 metadata fields, 3 of 12 answers, 0 of 7 obligations, and 0 of 3 risks. The strict obligation and risk keys penalize wording and classification differences, so the zero scores do not mean that every prediction was empty. The saved output contains some relevant, evidence-backed findings. It also contains extra risk claims and does not match the agreed labels closely enough for production use.

Before accepting customer contracts, review the predictions with qualified legal or procurement staff, build a representative labeled dataset, agree on acceptance thresholds, and improve or replace the model. The application should remain an assisted-review tool; a successful infrastructure check is not approval for autonomous legal decisions.
