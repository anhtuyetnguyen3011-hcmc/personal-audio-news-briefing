from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .config import Config
from .text import local_embedding


class Embedder:
    def __init__(self, config: Config):
        self.config = config
        self.cache_dir = config.output_dir / "cache" / "embeddings"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.provider_used = "local"
        self.calls = 0
        self.estimated_cost_usd = 0.0

    def _cache_path(self, text: str) -> Path:
        key = hashlib.sha256(f"{self.config.embedding_model}\0{text}".encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.json"

    def embed(self, texts: list[str]) -> list[dict[str, float]]:
        use_openai = (
            self.config.embedding_provider == "openai"
            and bool(os.getenv("OPENAI_API_KEY"))
            and not self.config.dry_run
        )
        if not use_openai:
            self.provider_used = "local"
            return [local_embedding(text) for text in texts]
        try:
            from openai import OpenAI
        except ImportError:
            self.provider_used = "local"
            return [local_embedding(text) for text in texts]

        client = OpenAI(timeout=self.config.request_timeout_seconds, max_retries=self.config.max_retries)
        self.provider_used = "openai"
        by_text: dict[str, dict[str, float]] = {}
        pending: list[str] = []
        for text in texts:
            cached = self._cache_path(text)
            if cached.exists():
                by_text[text] = json.loads(cached.read_text(encoding="utf-8"))
            else:
                pending.append(text)
        for index in range(0, len(pending), 64):
            batch = pending[index : index + 64]
            response = client.embeddings.create(model=self.config.embedding_model, input=batch)
            self.calls += 1
            tokens = sum(len(text) / 4 for text in batch)
            self.estimated_cost_usd += 0.02 * tokens / 1_000_000
            for item in response.data:
                vector = {str(i): float(value) for i, value in enumerate(item.embedding)}
                self._cache_path(batch[item.index]).write_text(json.dumps(vector), encoding="utf-8")
                by_text[batch[item.index]] = vector
        return [by_text[text] for text in texts]
