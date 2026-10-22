# Evaluation

The repository contains two synthetic evaluation sets. They are intended for regression checks and integration testing. They are not a substitute for a reviewed set of real contracts.

## Reference fixture

`data/evaluation/contracts.json` contains fictional MSA, NDA, and SaaS contracts split into 11 page-level chunks. `expected_outputs.json` labels eight metadata fields per contract, four obligations, three risks, and six questions. No customer data or credentials are included.

Run the saved reference predictions with `make evaluate`, or score another prediction file:

```sh
python scripts/evaluate_extraction.py \
  --predictions path/to/predictions.json \
  --output path/to/results.json
```

The prediction file must include every `contract_id` in the dataset and follow the structure in `reference_predictions.json`.

## Scoring rules

- Metadata uses case-insensitive exact matching across eight fields. Whitespace is normalized and party order does not matter.
- Obligations must match title, responsible party, counterparty, due date, recurring frequency, and page number.
- Risks match on category and page before severity is compared.
- Answers use normalized exact matching. Citation scores compare cited chunk IDs with the labeled supporting chunks.
- An answer counts as grounded when it either declines an unsupported question without citations or answers with citations drawn only from the labeled evidence.

The saved reference snapshot is deliberately imperfect:

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

These numbers prove that the evaluator behaves as expected. They do not measure a live model.

## Live API run

The expanded fixture adds support, payment-amendment, and data-processing contracts. In total it contains six contracts, 20 page chunks, and 12 questions. The cases cover superseded deadlines, response and resolution periods, missing metadata, absent insurance or availability terms, and breach notification.

Start the stack, pull the configured Ollama model, set `CONTRACT_REVIEW_ACCESS_KEY` to a reviewer key for a dedicated evaluation tenant, and run:

```sh
python scripts/evaluate_live.py --output-dir data/evaluation/live_runs/local
```

The script builds PDFs from the fixtures and sends them through the public API. It exercises upload, analysis, saved-result reuse, summary, search, and questions. The output directory receives `predictions.json` and `results.json`, including model names, a timestamp, and the dataset hash.

After each completed contract, the runner updates `partial.json`. If a run stops, fix the problem and resume it with:

```sh
python scripts/evaluate_live.py \
  --output-dir data/evaluation/live_runs/local \
  --resume
```

Resume checks the model, user identity, dataset hashes, and stored contract state before skipping finished cases. Uploaded evaluation contracts remain in the evaluation tenant.

The manual **Live stack verification** workflow performs the same exercise with Docker, PostgreSQL, Ollama, and real embeddings. It also checks PostgreSQL row-lock recovery. A green workflow means the stack works together; it does not mean that the selected model is accurate enough for legal work.

Exact matching can score reasonable paraphrases as wrong, while citation matching does not prove full semantic correctness. Production acceptance needs a larger, representative dataset, human adjudication, and agreed thresholds.
