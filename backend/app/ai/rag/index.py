"""Contract-scoped FAISS index persistence and metadata validation."""

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import faiss
import numpy as np
from numpy.typing import NDArray


class VectorIndexError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VectorIndexMetadata:
    contract_id: str
    model_name: str
    dimension: int
    vector_count: int
    chunk_ids: list[str]
    metric: str
    normalized: bool
    created_at: str
    index_sha256: str


@dataclass(frozen=True, slots=True)
class VectorMatch:
    chunk_id: uuid.UUID
    score: float


class ContractVectorIndexStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _contract_dir(self, contract_id: uuid.UUID) -> Path:
        return self.root / str(contract_id)

    def write(
        self,
        *,
        contract_id: uuid.UUID,
        model_name: str,
        chunk_ids: list[uuid.UUID],
        vectors: NDArray[np.float32],
    ) -> VectorIndexMetadata:
        matrix = np.ascontiguousarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] == 0:
            raise ValueError("Vectors must be a non-empty two-dimensional matrix")
        if matrix.shape[0] != len(chunk_ids) or not chunk_ids:
            raise ValueError("Each vector must map to exactly one chunk")
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("Chunk identifiers must be unique")
        if not np.isfinite(matrix).all():
            raise ValueError("Vectors must contain only finite values")

        norms = np.linalg.norm(matrix, axis=1)
        if np.any(norms == 0):
            raise ValueError("Zero-length vectors cannot be indexed")
        matrix = matrix / norms[:, None]

        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        contract_dir = self._contract_dir(contract_id)
        contract_dir.mkdir(parents=True, exist_ok=True)
        index_path = contract_dir / "index.faiss"
        metadata_path = contract_dir / "metadata.json"
        temporary_index = contract_dir / "index.faiss.tmp"
        temporary_metadata = contract_dir / "metadata.json.tmp"

        faiss.write_index(index, str(temporary_index))
        index_bytes = temporary_index.read_bytes()
        metadata = VectorIndexMetadata(
            contract_id=str(contract_id),
            model_name=model_name,
            dimension=matrix.shape[1],
            vector_count=len(chunk_ids),
            chunk_ids=[str(chunk_id) for chunk_id in chunk_ids],
            metric="cosine",
            normalized=True,
            created_at=datetime.now(timezone.utc).isoformat(),
            index_sha256=hashlib.sha256(index_bytes).hexdigest(),
        )
        temporary_metadata.write_text(
            json.dumps(asdict(metadata), indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary_index, index_path)
        os.replace(temporary_metadata, metadata_path)
        return metadata

    def load(self, contract_id: uuid.UUID) -> tuple[object, VectorIndexMetadata]:
        contract_dir = self._contract_dir(contract_id)
        index_path = contract_dir / "index.faiss"
        metadata_path = contract_dir / "metadata.json"
        if not index_path.is_file() or not metadata_path.is_file():
            raise VectorIndexError(f"No vector index exists for contract {contract_id}")

        try:
            raw_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata = VectorIndexMetadata(**raw_metadata)
        except (OSError, json.JSONDecodeError, TypeError) as error:
            raise VectorIndexError("Vector index metadata is invalid") from error
        if metadata.contract_id != str(contract_id):
            raise VectorIndexError("Vector index belongs to a different contract")
        index_bytes = index_path.read_bytes()
        if hashlib.sha256(index_bytes).hexdigest() != metadata.index_sha256:
            raise VectorIndexError("Vector index checksum does not match its metadata")

        try:
            index = faiss.read_index(str(index_path))
        except RuntimeError as error:
            raise VectorIndexError("FAISS index could not be loaded") from error
        if (
            index.d != metadata.dimension
            or index.ntotal != metadata.vector_count
            or len(metadata.chunk_ids) != metadata.vector_count
        ):
            raise VectorIndexError("FAISS index and metadata are inconsistent")
        return index, metadata

    def search(
        self,
        *,
        contract_id: uuid.UUID,
        query_vector: NDArray[np.float32],
        top_k: int,
    ) -> tuple[list[VectorMatch], VectorIndexMetadata]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        index, metadata = self.load(contract_id)
        query = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
        if query.shape[1] != metadata.dimension or not np.isfinite(query).all():
            raise ValueError("Query embedding does not match the index dimension")
        norm = np.linalg.norm(query)
        if norm == 0:
            raise ValueError("Query embedding cannot be a zero vector")
        query = np.ascontiguousarray(query / norm, dtype=np.float32)
        result_count = min(top_k, metadata.vector_count)
        scores, positions = index.search(query, result_count)
        matches = [
            VectorMatch(
                chunk_id=uuid.UUID(metadata.chunk_ids[position]), score=float(score)
            )
            for score, position in zip(scores[0], positions[0], strict=True)
            if position >= 0
        ]
        return matches, metadata
