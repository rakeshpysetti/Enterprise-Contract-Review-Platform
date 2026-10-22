"""Exercise a running API with real PDF ingestion, models, persistence and citations.

Set CONTRACT_REVIEW_ACCESS_KEY when authentication is enabled. No saved predictions
are used. Uploaded synthetic evaluation contracts remain in the selected tenant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_extraction import (  # noqa: E402
    METADATA_FIELDS,
    ROOT,
    evaluate_files,
)


def contract_pdf(chunks: list[dict[str, Any]]) -> bytes:
    pages = {chunk["page_number"]: chunk["text"] for chunk in chunks}
    if len(pages) != len(chunks) or not pages or min(pages) < 1:
        raise ValueError("Live fixtures require unique positive page numbers")
    with pymupdf.open() as document:
        for page_number in range(1, max(pages) + 1):
            page = document.new_page()
            remaining = page.insert_textbox(
                pymupdf.Rect(50, 50, 545, 790), pages.get(page_number, ""), fontsize=10
            )
            if remaining < 0:
                raise ValueError("Fixture text exceeds a PDF page")
        return document.tobytes()


def generate_predictions(
    client: httpx.Client,
    dataset: dict[str, Any],
    expected: dict[str, Any],
    *,
    completed_contracts: list[dict[str, Any]] | None = None,
    on_completed: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    def request(method: str, path: str, **kwargs: Any) -> Any:
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    request("GET", "/auth/me")
    request("GET", "/health/ready")
    gold = {item["contract_id"]: item for item in expected["contracts"]}
    if set(gold) != {item["contract_id"] for item in dataset["contracts"]}:
        raise ValueError("Dataset and expected contract IDs must match")
    predictions = list(completed_contracts or [])
    fixture_ids = [item["contract_id"] for item in dataset["contracts"]]
    if [item["contract_id"] for item in predictions] != fixture_ids[: len(predictions)]:
        raise ValueError("Completed predictions must be a dataset prefix")
    for prior in predictions:
        stored = request("GET", f"/contracts/{prior['api_contract_id']}")
        if stored["status"] != "completed":
            raise ValueError("A resumed contract is no longer completed")
    for fixture in dataset["contracts"][len(predictions) :]:
        identifier = fixture["contract_id"]
        uploaded = request(
            "POST",
            "/contracts",
            files={
                "file": (
                    f"evaluation-{identifier}.pdf",
                    contract_pdf(fixture["chunks"]),
                    "application/pdf",
                ),
            },
        )
        path = f"/contracts/{uploaded['id']}"
        analyzed = request("POST", path + "/analyze")
        if analyzed["status"] != "completed":
            raise ValueError(f"Analysis did not complete for {identifier}")
        reused = request("POST", path + "/analyze")
        if not reused["analysis_reused"]:
            raise ValueError("Completed analysis was not reused")
        summary = request("GET", path + "/summary")
        if summary["obligation_count"] != len(analyzed["obligations"]):
            raise ValueError("Stored summary does not match analysis")
        page_to_fixture = {
            chunk["page_number"]: chunk["chunk_id"] for chunk in fixture["chunks"]
        }
        chunk_ids = {
            chunk["id"]: page_to_fixture[chunk["page_number"]]
            for chunk in uploaded["chunks"]
        }
        qa = []
        for question in gold[identifier].get("qa", []):
            matches = request(
                "POST",
                path + "/search",
                json={
                    "query": question["question"],
                    "top_k": 5,
                },
            )
            if not matches["results"] or any(
                result["chunk_id"] not in chunk_ids for result in matches["results"]
            ):
                raise ValueError("Semantic retrieval returned invalid sources")
            answer = request(
                "POST",
                path + "/questions",
                json={
                    "question": question["question"],
                    "top_k": 5,
                },
            )
            qa.append(
                {
                    "question_id": question["question_id"],
                    "answer": answer["answer"],
                    "cited_chunk_ids": [
                        chunk_ids[source["chunk_id"]] for source in answer["sources"]
                    ],
                }
            )
        predictions.append(
            {
                "contract_id": identifier,
                "api_contract_id": uploaded["id"],
                "metadata": {key: analyzed[key] for key in METADATA_FIELDS},
                "obligations": analyzed["obligations"],
                "risks": analyzed["risks"],
                "qa": qa,
            }
        )
        if on_completed is not None:
            on_completed(predictions)
        print(f"Completed fixture {identifier}", flush=True)
    return {"version": dataset["version"], "contracts": predictions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--dataset", type=Path, default=ROOT / "data/evaluation/expanded_contracts.json"
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=ROOT / "data/evaluation/expanded_expected_outputs.json",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if any(
        (args.output_dir / name).exists()
        for name in ("predictions.json", "results.json")
    ):
        parser.error(
            "Choose a fresh output directory; existing reports are not overwritten"
        )
    headers = {}
    token = os.environ.get("CONTRACT_REVIEW_ACCESS_KEY")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    checkpoint_path = args.output_dir / "partial.json"
    if checkpoint_path.exists() and not args.resume:
        parser.error("Partial results exist; use --resume or a fresh output directory")
    if args.resume and not checkpoint_path.exists():
        parser.error("There are no partial results to resume")
    with httpx.Client(
        base_url=args.base_url, headers=headers, timeout=args.timeout
    ) as client:
        info_response = client.get("/system/info")
        info_response.raise_for_status()
        info = info_response.json()
        identity_response = client.get("/auth/me")
        identity_response.raise_for_status()
        identity = identity_response.json()
        checkpoint_header = {
            "system": info,
            "identity": identity,
            "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
            "expected_sha256": hashlib.sha256(args.expected.read_bytes()).hexdigest(),
        }
        completed: list[dict[str, Any]] = []
        if args.resume:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if any(
                checkpoint.get(key) != value for key, value in checkpoint_header.items()
            ):
                parser.error("Partial results belong to a different run configuration")
            completed = checkpoint["contracts"]

        def save_partial(items: list[dict[str, Any]]) -> None:
            temporary = checkpoint_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({**checkpoint_header, "contracts": items}, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(checkpoint_path)

        predictions = generate_predictions(
            client,
            dataset,
            expected,
            completed_contracts=completed,
            on_completed=save_partial,
        )
    prediction_path = args.output_dir / "predictions.json"
    prediction_path.write_text(
        json.dumps(predictions, indent=2) + "\n", encoding="utf-8"
    )
    metrics = evaluate_files(args.dataset, args.expected, prediction_path)
    report = {
        "run": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "live-api",
            "system": info,
            "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        },
        "metrics": metrics,
    }
    (args.output_dir / "results.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
