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
