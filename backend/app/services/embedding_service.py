"""Hugging Face Sentence Transformers embedding generation."""

from collections.abc import Sequence
from functools import cached_property
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]: ...


class HuggingFaceEmbeddingService:
    def __init__(self, model_name: str, *, device: str = "cpu") -> None:
        if not model_name.strip():
            raise ValueError("An embedding model name is required")
        self._model_name = model_name
        self.device = device

    @property
    def model_name(self) -> str:
        return self._model_name

    @cached_property
    def model(self):
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.model_name, device=self.device)

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        if not texts:
            raise ValueError("At least one text is required for embedding")
        if any(not text.strip() for text in texts):
            raise ValueError("Embedding text cannot be blank")

        vectors = self.model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        result = np.ascontiguousarray(vectors, dtype=np.float32)
        if result.ndim != 2 or result.shape[0] != len(texts) or result.shape[1] == 0:
            raise ValueError("Embedding model returned an unexpected shape")
        if not np.isfinite(result).all():
            raise ValueError("Embedding model returned non-finite values")
        return result
