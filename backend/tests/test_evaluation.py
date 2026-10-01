import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_extraction import EvaluationDataError, evaluate_files  # noqa: E402

DATASET = ROOT / "data/evaluation/contracts.json"
EXPECTED = ROOT / "data/evaluation/expected_outputs.json"
PREDICTIONS = ROOT / "data/evaluation/reference_predictions.json"


def test_reference_evaluation_metrics() -> None:
    results = evaluate_files(DATASET, EXPECTED, PREDICTIONS)
    assert results["metadata"]["accuracy"] == 0.9167
    assert results["obligations"]["precision"] == 0.75
    assert results["obligations"]["recall"] == 0.75
    assert results["risks"]["classification_accuracy"] == 0.6667
    assert results["qa"]["answer_accuracy"] == 0.6667
    assert results["qa"]["grounding_rate"] == 0.6667
    assert results["qa"]["citation_precision"] == 0.6667
    assert results["qa"]["citation_recall"] == 1.0


def test_cli_writes_reproducible_results(tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/evaluate_extraction.py"), "--output", str(output)],
        cwd=tmp_path, capture_output=True, check=True, text=True,
    )
    assert json.loads(completed.stdout) == json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(completed.stdout) == json.loads((ROOT / "data/evaluation/results.json").read_text(encoding="utf-8"))


def test_rejects_gold_citation_outside_contract(tmp_path: Path) -> None:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    expected["contracts"][0]["qa"][0]["supporting_chunk_ids"] = ["unknown-chunk"]
    invalid_expected = tmp_path / "expected.json"
    invalid_expected.write_text(json.dumps(expected), encoding="utf-8")
    with pytest.raises(EvaluationDataError, match="gold citations"):
        evaluate_files(DATASET, invalid_expected, PREDICTIONS)


def test_missing_nullable_values_and_no_answer_case_are_incorrect(tmp_path: Path) -> None:
    predictions = json.loads(PREDICTIONS.read_text(encoding="utf-8"))
    predictions["contracts"][1]["metadata"].pop("renewal_date")
    predictions["contracts"][1]["qa"] = [predictions["contracts"][1]["qa"][0]]
    incomplete = tmp_path / "predictions.json"
    incomplete.write_text(json.dumps(predictions), encoding="utf-8")

    results = evaluate_files(DATASET, EXPECTED, incomplete)

    assert results["metadata"]["correct"] == 21
    assert results["qa"]["answer_correct"] == 3
    assert results["qa"]["grounded"] == 3
