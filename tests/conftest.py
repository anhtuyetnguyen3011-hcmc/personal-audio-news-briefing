from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent1.config import Config

FEEDS = (
    "actionforex.jsonl",
    "ibtimes_uk.jsonl",
    "invezz_de.jsonl",
    "invezz_en.jsonl",
    "invezz_nl.jsonl",
    "zacks.jsonl",
)


def raw_record(original_id: str, published: str, title: str, excerpt: str, feed: str, author: str = "Reporter", tickers: list[str] | None = None, language: str = "en") -> dict:
    return {
        "$id": original_id,
        "date": published,
        "headline": title,
        "excerpt": excerpt,
        "text_content": f"{title} {excerpt} " + "Additional market context and trading details for readers." * 3,
        "permalink": f"https://example.com/{feed}/{original_id}",
        "language": language,
        "publication": {"name": "Invezz" if "invezz" in feed else "ActionForex"},
        "publisher": "Invezz" if "invezz" in feed else "ActionForex",
        "source": author,
        "received_at": published,
        "categories": ["markets"],
        "company_tickers": tickers or [],
    }


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "out"
    data_dir.mkdir()
    output_dir.mkdir()
    for feed in FEEDS:
        (data_dir / feed).write_text("", encoding="utf-8")
    return Config.from_env(
        {
            "data_dir": str(data_dir),
            "output_dir": str(output_dir),
            "mode": "daily",
            "window_hours": 24,
            "cluster_window_hours": 48,
            "embedding_provider": "local",
            "llm_provider": "none",
            "dry_run": True,
        }
    )


@pytest.fixture
def s0_articles(mock_config: Config) -> list[dict]:
    rows = [
        raw_record("EN-1", "2026-11-20T10:10:00+00:00", "US inflation rises to 3.2% as Nvidia shares fall", "Investors weigh the 3.2% inflation print and Nvidia market reaction across US markets.", "invezz_en.jsonl", "Shared Author", ["NVDA"]),
        raw_record("DE-1", "2026-11-20T10:05:00+00:00", "US-Inflation steigt auf 3.2%, Nvidia-Aktien fallen", "Investors weigh the 3.2% inflation print and Nvidia market reaction across US markets.", "invezz_de.jsonl", "Shared Author", ["NVDA"], "de"),
        raw_record("NL-1", "2026-11-20T10:00:00+00:00", "Amerikaanse inflatie stijgt naar 3.2%, Nvidia-aandelen dalen", "Investors weigh the 3.2% inflation print and Nvidia market reaction across US markets.", "invezz_nl.jsonl", "Shared Author", ["NVDA"], "nl"),
        raw_record("OLD-1", "2026-11-01T10:00:00+00:00", "Old market wrap", "Older archived article that must remain outside the daily briefing window.", "actionforex.jsonl"),
    ]
    (mock_config.data_dir / "invezz_en.jsonl").write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    (mock_config.data_dir / "invezz_de.jsonl").write_text(json.dumps(rows[1]) + "\n", encoding="utf-8")
    (mock_config.data_dir / "invezz_nl.jsonl").write_text(json.dumps(rows[2]) + "\n", encoding="utf-8")
    (mock_config.data_dir / "actionforex.jsonl").write_text(json.dumps(rows[3]) + "\n", encoding="utf-8")
    return rows
