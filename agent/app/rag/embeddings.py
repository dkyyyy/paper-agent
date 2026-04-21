"""Embedding model factory for Analysis/RAG pipelines."""

import hashlib
import logging
import math
import os
import re
from functools import lru_cache

from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)
_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+")


class LocalHashEmbeddings(Embeddings):
    """Deterministic offline embeddings based on hashed lexical features."""

    def __init__(self, dimensions: int = 768):
        self.dimensions = dimensions

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for match in _TOKEN_PATTERN.findall(text.lower()):
            if any("\u4e00" <= char <= "\u9fff" for char in match):
                tokens.extend(match[index:index + 2] for index in range(max(1, len(match) - 1)))
            else:
                tokens.append(match)
        return tokens or ["__empty__"]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._tokenize(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] / 255.0)
            vector[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """Build the configured embedding client."""
    from app.config import config

    provider = config.effective_embedding_provider
    model_name = config.effective_embedding_model

    if provider == "dashscope":
        if not config.effective_embedding_api_key:
            raise ValueError("EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER=dashscope")
        from langchain_community.embeddings import DashScopeEmbeddings

        return DashScopeEmbeddings(
            model=model_name,
            dashscope_api_key=config.effective_embedding_api_key,
        )

    if provider == "openai":
        if not config.effective_embedding_api_key:
            raise ValueError("EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER=openai")
        base_url = config.effective_embedding_base_url
        if "deepseek.com" in base_url.lower():
            raise ValueError(
                "DeepSeek chat-compatible base URL does not provide a supported embeddings endpoint. "
                "Set EMBEDDING_PROVIDER to dashscope/openai/local explicitly."
            )
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=model_name,
            api_key=config.effective_embedding_api_key,
            base_url=base_url,
        )

    if provider in {"huggingface", "bge"}:
        from langchain_community.embeddings import HuggingFaceBgeEmbeddings

        model_kwargs = {}
        if os.getenv("HF_HUB_OFFLINE") == "1" or os.getenv("TRANSFORMERS_OFFLINE") == "1":
            model_kwargs["local_files_only"] = True

        return HuggingFaceBgeEmbeddings(
            model_name=model_name,
            model_kwargs=model_kwargs,
            encode_kwargs={"normalize_embeddings": True},
        )

    if provider in {"local", "hash", "localhash"}:
        logger.info(
            "Using offline local hash embeddings (%s dimensions). Retrieval quality is lexical rather than semantic.",
            config.local_embedding_dimensions,
        )
        return LocalHashEmbeddings(dimensions=config.local_embedding_dimensions)

    raise ValueError(f"Unsupported embedding provider: {provider}")