# Evaluation

The repository includes a hand-labeled dataset of three fictional contracts in `data/evaluation/contracts.json`. The MSA, NDA, and SaaS examples contain 11 page-level chunks. `expected_outputs.json` supplies gold metadata, four obligations, three risks, and six questions. No customer contracts or credentials are included.

Run the reference prediction snapshot with `make evaluate`, or evaluate another prediction file:

```bash
python scripts/evaluate_extraction.py --predictions path/to/predictions.json --output path/to/results.json
```

The prediction file must contain every dataset `contract_id` and follow the collections shown in `reference_predictions.json`.

## Metrics

- **Metadata accuracy** is case-insensitive exact match across eight fields per contract. Whitespace is normalized, and party objects are order-independent.
- **Obligation precision and recall** use exact matches on title, responsible party, counterparty, due date, recurring frequency, and page number.
- **Risk classification accuracy** matches risks by category and page, then compares severity. Missing gold risks count as errors. Detection precision and recall are also reported.
- **Q&A answer accuracy** uses normalized exact match. Citation precision and recall compare cited chunk IDs with labeled support. A response is grounded when it declines an unanswerable question without citations, or answers with at least one citation and all citations are labeled support.

## Reference results

`reference_predictions.json` is intentionally imperfect so error paths remain covered. Running it produces `results.json`:

| Measure | Result |
| --- | ---: |
| Metadata accuracy | 91.67% (22/24) |
| Obligation precision | 75.00% |
| Obligation recall | 75.00% |
| Risk classification accuracy | 66.67% (2/3) |
| Q&A answer accuracy | 66.67% (4/6) |
| Q&A grounding rate | 66.67% (4/6) |
| Citation precision | 66.67% |
| Citation recall | 100.00% |

These figures validate the evaluator against a deterministic fixture. They are not measurements of a live Ollama model or evidence of production quality. The dataset is too small and synthetic for model selection; expand it with independently reviewed, representative contracts before drawing product conclusions.

## Live API evaluation

`expanded_contracts.json` and `expanded_expected_outputs.json` include the original three contracts plus support, payment-amendment, and data-processing examples: six contracts, 20 page chunks, and 12 questions. They add response-versus-resolution distinctions, superseded deadlines, missing metadata, absent insurance/availability terms, and breach notification. These additional labels are provisional synthetic annotations, not independently reviewed legal ground truth. Cases with an empty risk list assert no labeled risk under this small fixture rubric; they do not establish absence of real-world risk.

Start a configured stack, pull its Ollama model, set `CONTRACT_REVIEW_ACCESS_KEY` to a reviewer key for a dedicated evaluation tenant, and run:

```sh
python scripts/evaluate_live.py --output-dir data/evaluation/live_runs/local
```

The runner constructs real PDFs from fixture page text and sends them through the public API. It uses actual analysis results, verifies completed-result reuse and summary persistence, executes semantic search and grounded Q&A, and translates API chunk UUID citations back to fixture chunk IDs by source page. It saves `predictions.json` and `results.json`, with configured model names, timestamp, and dataset SHA-256. Service or schema failures exit unsuccessfully; saved reference predictions are never substituted. Uploaded evaluation contracts remain in the tenant. A `partial.json` checkpoint is saved after each fully completed fixture. If a run fails, repair the cause and rerun with the same output directory and `--resume`; the runner verifies the model, identity, dataset hashes, and stored contract status before skipping completed fixtures. Final results are written only after every fixture completes.

Use `--dataset`, `--expected`, `--base-url`, and `--timeout` for another dataset or stack. Each fixture page must have a unique positive page number, and each page's text must fit on one generated PDF page. The gold file supplies question text but never enters extraction prompts; only the contract text and individual questions are sent to the model.

The manual **Live stack verification** GitHub Actions workflow builds and runs the production Compose stack with real PostgreSQL, Ollama, and downloaded embeddings. It also verifies that recovery cannot bypass an active PostgreSQL row lock and succeeds after that transaction releases its lock. Its default small model keeps integration runs practical, but schema/evidence failures remain real failures. Model metrics are reported without an invented quality pass threshold. Run it with a deployment-sized model and independently reviewed contracts before a production quality decision.

Exact-match answer and obligation metrics can penalize equivalent wording. Grounding metrics check labeled citation support rather than full semantic entailment. Broader representative data, human adjudication, and an agreed acceptance threshold are still needed for product-quality claims.
