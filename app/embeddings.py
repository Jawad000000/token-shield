from __future__ import annotations

import hashlib
import math


class HashEmbeddingService:
    dimension = 384

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = [token.strip(".,!?;:()[]{}\"'").lower() for token in text.split()]
        for token in filter(None, tokens):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return normalize(vector)


class SentenceTransformerEmbeddingService:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.dimension = 384

    def embed_text(self, text: str) -> list[float]:
        vector = self.model.encode(text, normalize_embeddings=True)
        values = [float(value) for value in vector.tolist()]
        if len(values) != self.dimension:
            raise ValueError(f"embedding dimension mismatch: expected {self.dimension}, got {len(values)}")
        return values


def normalize(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0:
        return vector
    return [value / length for value in vector]


def build_embedding_service(backend: str):
    if backend == "sentence-transformers":
        return SentenceTransformerEmbeddingService()
    return HashEmbeddingService()
