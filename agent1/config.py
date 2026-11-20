from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT.parent / "liquid-briefing-data"
DEFAULT_OUTPUT_DIR = ROOT / "outputs"


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _as_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


@dataclass
class Config:
    data_dir: Path = DEFAULT_DATA_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    mode: str = "full"
    window_hours: int = 24
    cluster_window_hours: int = 48
    translation_window_minutes: int = 15
    translation_similarity_threshold: float = 0.52
    semantic_similarity_threshold: float = 0.58
    min_shared_entities: int = 2
    min_shared_signals: int = 2
    high_similarity_threshold: float = 0.75
    entity_boost: float = 0.12
    numeric_boost: float = 0.10
    embedding_provider: str = "local"
    embedding_model: str = "text-embedding-3-small"
    llm_provider: str = "none"
    llm_model: str = "gpt-6-luna"
    fact_min: int = 3
    fact_max: int = 5
    budget_usd: float = 5.0
    dry_run: bool = True
    request_timeout_seconds: float = 30.0
    max_retries: int = 3

    @classmethod
    def from_env(cls, overrides: dict[str, Any] | None = None) -> "Config":
        cfg = cls(
            data_dir=Path(os.getenv("LIQUID_BRIEFING_DATA_DIR", str(DEFAULT_DATA_DIR))),
            output_dir=Path(os.getenv("LIQUID_BRIEFING_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))),
            mode=os.getenv("LIQUID_BRIEFING_MODE", "full"),
            window_hours=_as_int("LIQUID_BRIEFING_WINDOW_HOURS", 24),
            cluster_window_hours=_as_int("LIQUID_BRIEFING_CLUSTER_WINDOW_HOURS", 48),
            translation_window_minutes=_as_int("LIQUID_BRIEFING_TRANSLATION_WINDOW_MINUTES", 15),
            translation_similarity_threshold=_as_float("LIQUID_BRIEFING_TRANSLATION_SIMILARITY_THRESHOLD", 0.52),
            semantic_similarity_threshold=_as_float("LIQUID_BRIEFING_SEMANTIC_SIMILARITY_THRESHOLD", 0.58),
            min_shared_entities=_as_int("LIQUID_BRIEFING_MIN_SHARED_ENTITIES", 2),
            min_shared_signals=_as_int("LIQUID_BRIEFING_MIN_SHARED_SIGNALS", 2),
            high_similarity_threshold=_as_float("LIQUID_BRIEFING_HIGH_SIMILARITY_THRESHOLD", 0.75),
            entity_boost=_as_float("LIQUID_BRIEFING_ENTITY_BOOST", 0.12),
            numeric_boost=_as_float("LIQUID_BRIEFING_NUMERIC_BOOST", 0.10),
            embedding_provider=os.getenv("OPENAI_EMBEDDING_PROVIDER", "local"),
            embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            llm_provider=os.getenv("LIQUID_BRIEFING_LLM_PROVIDER", "none"),
            llm_model=os.getenv("OPENAI_LLM_MODEL", "gpt-6-luna"),
            fact_min=_as_int("LIQUID_BRIEFING_FACT_MIN", 3),
            fact_max=_as_int("LIQUID_BRIEFING_FACT_MAX", 5),
            budget_usd=_as_float("OPENAI_MAX_BUDGET_USD", 5.0),
            dry_run=_as_bool("OPENAI_DRY_RUN", True),
            request_timeout_seconds=_as_float("LIQUID_BRIEFING_REQUEST_TIMEOUT_SECONDS", 30.0),
            max_retries=_as_int("LIQUID_BRIEFING_MAX_RETRIES", 3),
        )
        if overrides:
            for key, value in overrides.items():
                if key in {f.name for f in fields(cls)}:
                    setattr(cfg, key, Path(value) if isinstance(value, str) and key in {"data_dir", "output_dir"} else value)
        if cfg.mode not in {"full", "daily"}:
            raise ValueError("mode must be 'full' or 'daily'")
        if not 1 <= cfg.window_hours <= 48:
            raise ValueError("window_hours must be between 1 and 48")
        if cfg.fact_min < 1 or cfg.fact_max < cfg.fact_min:
            raise ValueError("fact_min/fact_max are invalid")
        return cfg

    @classmethod
    def from_file(cls, path: Path, overrides: dict[str, Any] | None = None) -> "Config":
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in ("data_dir", "output_dir"):
            if key in payload and payload[key]:
                payload[key] = str((path.parent / payload[key]).resolve())
        return cls.from_env({**payload, **(overrides or {})})

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["data_dir"] = str(self.data_dir)
        data["output_dir"] = str(self.output_dir)
        return data
