"""Evaluate structured contract-analysis predictions against labeled fixtures."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MISSING = object()
METADATA_FIELDS = (
    "title",
    "contract_type",
    "parties",
    "effective_date",
    "expiration_date",
    "renewal_date",
    "governing_law",
    "payment_terms",
)


class EvaluationDataError(ValueError):
    """Raised when an evaluation file is incomplete or inconsistent."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDataError(f"Unable to read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationDataError(f"{path} must contain a JSON object")
    return value


def _items(document: dict[str, Any], key: str, source: str) -> list[dict[str, Any]]:
    items = document.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise EvaluationDataError(f"{source}.{key} must be a list of objects")
    return items


def _index(items: list[dict[str, Any]], source: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        identifier = item.get("contract_id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise EvaluationDataError(f"{source} contains an invalid contract_id")
        if identifier in indexed:
            raise EvaluationDataError(
                f"{source} contains duplicate contract_id {identifier!r}"
            )
        indexed[identifier] = item
    return indexed


def _normal(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip().casefold()
    if isinstance(value, list):
        return tuple(sorted((_normal(item) for item in value), key=repr))
    if isinstance(value, dict):
        return tuple(sorted((key, _normal(item)) for key, item in value.items()))
    return value


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return (
        round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0.0
    )


def _metadata(
    expected: dict[str, dict[str, Any]], predicted: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    per_field: dict[str, dict[str, Any]] = {
        field: {"correct": 0, "total": 0} for field in METADATA_FIELDS
    }
    for contract_id, gold in expected.items():
        gold_metadata = gold.get("metadata", {})
        predicted_metadata = predicted[contract_id].get("metadata", {})
        if not isinstance(gold_metadata, dict) or not isinstance(
            predicted_metadata, dict
        ):
            raise EvaluationDataError(f"metadata for {contract_id!r} must be an object")
        for field in METADATA_FIELDS:
            per_field[field]["total"] += 1
            if field in predicted_metadata and _normal(
                gold_metadata.get(field)
            ) == _normal(predicted_metadata[field]):
                per_field[field]["correct"] += 1
    correct = sum(value["correct"] for value in per_field.values())
    total = sum(value["total"] for value in per_field.values())
    for value in per_field.values():
        value["accuracy"] = _ratio(value["correct"], value["total"])
    return {
        "correct": correct,
        "total": total,
        "accuracy": _ratio(correct, total),
        "per_field": per_field,
    }


def _obligation_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _normal(item.get(field))
        for field in (
            "title",
            "responsible_party",
            "counterparty",
            "due_date",
            "recurring_frequency",
            "page_number",
        )
    )


def _risk_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return _normal(item.get("category")), item.get("page_number")


def _obligations(
    expected: dict[str, dict[str, Any]], predicted: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    true_positive = false_positive = false_negative = 0
    for contract_id, gold in expected.items():
        gold_items = gold.get("obligations", [])
        predicted_items = predicted[contract_id].get("obligations", [])
        if not isinstance(gold_items, list) or not isinstance(predicted_items, list):
            raise EvaluationDataError(f"obligations for {contract_id!r} must be a list")
        gold_counts = Counter(_obligation_key(item) for item in gold_items)
        predicted_counts = Counter(_obligation_key(item) for item in predicted_items)
        matches = sum((gold_counts & predicted_counts).values())
        true_positive += matches
        false_positive += sum(predicted_counts.values()) - matches
        false_negative += sum(gold_counts.values()) - matches
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
    }


def _risks(
    expected: dict[str, dict[str, Any]], predicted: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    expected_count = predicted_count = matched = correct = 0
    for contract_id, gold in expected.items():
        gold_items = gold.get("risks", [])
        predicted_items = predicted[contract_id].get("risks", [])
        if not isinstance(gold_items, list) or not isinstance(predicted_items, list):
            raise EvaluationDataError(f"risks for {contract_id!r} must be a list")
        gold_by_key = {_risk_key(item): item for item in gold_items}
        predicted_by_key = {_risk_key(item): item for item in predicted_items}
        expected_count += len(gold_items)
        predicted_count += len(predicted_items)
        for key, gold_risk in gold_by_key.items():
            if key in predicted_by_key:
                matched += 1
                if _normal(gold_risk.get("level")) == _normal(
                    predicted_by_key[key].get("level")
                ):
                    correct += 1
    return {
        "correct": correct,
        "expected": expected_count,
        "predicted": predicted_count,
        "matched": matched,
        "classification_accuracy": _ratio(correct, expected_count),
        "detection_precision": _ratio(matched, predicted_count),
        "detection_recall": _ratio(matched, expected_count),
    }


def _qa(
    expected: dict[str, dict[str, Any]], predicted: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    total = answer_correct = grounded = citation_tp = citation_fp = citation_fn = 0
    for contract_id, gold in expected.items():
        gold_cases = gold.get("qa", [])
        predicted_cases = predicted[contract_id].get("qa", [])
        if not isinstance(gold_cases, list) or not isinstance(predicted_cases, list):
            raise EvaluationDataError(f"qa for {contract_id!r} must be a list")
        predicted_by_id = {item.get("question_id"): item for item in predicted_cases}
        for gold_case in gold_cases:
            question_id = gold_case.get("question_id")
            prediction = predicted_by_id.get(question_id)
            expected_answer = gold_case.get("answer")
            predicted_answer = (
                prediction.get("answer", MISSING) if prediction is not None else MISSING
            )
            expected_citations = set(gold_case.get("supporting_chunk_ids", []))
            predicted_citations = (
                set(prediction.get("cited_chunk_ids", []))
                if prediction is not None
                else set()
            )
            total += 1
            if _normal(expected_answer) == _normal(predicted_answer):
                answer_correct += 1
            if expected_answer is None:
                is_grounded = (
                    prediction is not None
                    and predicted_answer is None
                    and not predicted_citations
                )
            else:
                is_grounded = (
                    predicted_answer is not None
                    and bool(predicted_citations)
                    and predicted_citations <= expected_citations
                )
            grounded += int(is_grounded)
            citation_tp += len(expected_citations & predicted_citations)
            citation_fp += len(predicted_citations - expected_citations)
            citation_fn += len(expected_citations - predicted_citations)
    citation_precision = _ratio(citation_tp, citation_tp + citation_fp)
    citation_recall = _ratio(citation_tp, citation_tp + citation_fn)
    return {
        "answer_correct": answer_correct,
        "grounded": grounded,
        "total": total,
        "answer_accuracy": _ratio(answer_correct, total),
        "grounding_rate": _ratio(grounded, total),
        "citation_true_positive": citation_tp,
        "citation_false_positive": citation_fp,
        "citation_false_negative": citation_fn,
        "citation_precision": citation_precision,
        "citation_recall": citation_recall,
        "citation_f1": _f1(citation_precision, citation_recall),
    }


def evaluate_files(
    dataset_path: Path, expected_path: Path, predictions_path: Path
) -> dict[str, Any]:
    dataset_document = _load(dataset_path)
    expected_document = _load(expected_path)
    predictions_document = _load(predictions_path)
    datasets = _index(_items(dataset_document, "contracts", "dataset"), "dataset")
    expected = _index(_items(expected_document, "contracts", "expected"), "expected")
    predicted = _index(
        _items(predictions_document, "contracts", "predictions"), "predictions"
    )
    if set(datasets) != set(expected) or set(datasets) != set(predicted):
        raise EvaluationDataError(
            "dataset, expected outputs, and predictions must contain the same "
            "contract IDs"
        )
    for contract_id, contract in datasets.items():
        chunks = contract.get("chunks")
        if not isinstance(chunks, list):
            raise EvaluationDataError(f"chunks for {contract_id!r} must be a list")
        chunk_ids = [
            chunk.get("chunk_id") for chunk in chunks if isinstance(chunk, dict)
        ]
        if len(chunk_ids) != len(chunks) or any(
            not isinstance(value, str) for value in chunk_ids
        ):
            raise EvaluationDataError(
                f"chunks for {contract_id!r} must contain string chunk IDs"
            )
        if len(set(chunk_ids)) != len(chunk_ids):
            raise EvaluationDataError(
                f"chunks for {contract_id!r} contain duplicate chunk IDs"
            )
        for case in expected[contract_id].get("qa", []):
            citations = case.get("supporting_chunk_ids", [])
            if not isinstance(citations, list) or not set(citations) <= set(chunk_ids):
                raise EvaluationDataError(
                    f"gold citations for {contract_id!r} must reference dataset chunks"
                )
    return {
        "dataset_version": dataset_document.get("version"),
        "contracts_evaluated": len(datasets),
        "metadata": _metadata(expected, predicted),
        "obligations": _obligations(expected, predicted),
        "risks": _risks(expected, predicted),
        "qa": _qa(expected, predicted),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT / "data/evaluation/contracts.json"
    )
    parser.add_argument(
        "--expected", type=Path, default=ROOT / "data/evaluation/expected_outputs.json"
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=ROOT / "data/evaluation/reference_predictions.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = evaluate_files(args.dataset, args.expected, args.predictions)
    rendered = json.dumps(results, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
