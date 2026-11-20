from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .models import ArticleRecord, FeedReport, S0Report
from .text import country_mentions, normalize_ws, parse_timestamp, slugify

FEED_FILES = (
    "actionforex.jsonl",
    "ibtimes_uk.jsonl",
    "invezz_de.jsonl",
    "invezz_en.jsonl",
    "invezz_nl.jsonl",
    "zacks.jsonl",
)
CRITICAL = ("$id", "permalink", "headline", "date", "text_content")


def stable_id(feed_file: str, original_id: str) -> str:
    digest = hashlib.sha256(f"{feed_file}\0{original_id}".encode("utf-8")).hexdigest()[:16]
    return f"art_{digest}"


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        values = [normalize_ws(str(item)) for item in value if item not in (None, "")]
    elif isinstance(value, str) and value.strip():
        values = [normalize_ws(value)]
    else:
        return []
    return [value for value in values if value.lower() not in {"positive", "negative"}]


def _publisher(raw: dict[str, Any]) -> str | None:
    publication = raw.get("publication")
    if isinstance(publication, dict):
        name = normalize_ws(publication.get("name"))
        if name:
            return name
    return normalize_ws(raw.get("publisher"))


def ingest(config: Config) -> tuple[list[ArticleRecord], S0Report]:
    generated_at = datetime.now(timezone.utc)
    records: list[ArticleRecord] = []
    reports: list[FeedReport] = []
    errors: list[dict[str, Any]] = []
    total_input = 0
    valid_records = 0
    skipped_records = 0
    timestamps: list[datetime] = []

    for feed_file in FEED_FILES:
        path = config.data_dir / feed_file
        feed_input = 0
        feed_valid = 0
        feed_skipped = 0
        feed_errors: list[dict[str, Any]] = []
        if not path.exists():
            feed_errors.append({"file": feed_file, "line": 0, "code": "missing_feed", "message": "Feed file not found"})
            reports.append(FeedReport(feed_file=feed_file, input_count=0, valid_count=0, skipped_count=0, errors=feed_errors))
            continue
        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                feed_input += 1
                total_input += 1
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, dict):
                        raise ValueError("record is not an object")
                    missing = [key for key in CRITICAL if raw.get(key) in (None, "") or (isinstance(raw.get(key), str) and not raw[key].strip())]
                    if missing:
                        for key in missing:
                            feed_errors.append({"file": feed_file, "line": line_no, "code": f"missing_{key}", "message": f"Missing critical field {key}"})
                        feed_skipped += 1
                        skipped_records += 1
                        continue
                    permalink = normalize_ws(raw.get("permalink"))
                    if not permalink.startswith(("http://", "https://")):
                        raise ValueError("permalink is not a valid http(s) URL")
                    published = parse_timestamp(raw["date"])
                    text = normalize_ws(raw["text_content"])
                    title = normalize_ws(raw["headline"])
                    if len(text) < 40:
                        raise ValueError("text_content too short")
                    publication = _publisher(raw)
                    if not publication:
                        raise ValueError("missing publisher")
                    author = normalize_ws(raw.get("source")) or None
                    excerpt = normalize_ws(raw.get("excerpt")) or None
                    flags: list[str] = []
                    if not author:
                        flags.append("missing_author")
                    if not excerpt:
                        flags.append("missing_excerpt")
                    language = normalize_ws(raw.get("language")).lower()[:2] or None
                    if not language:
                        flags.append("missing_language")
                    countries = country_mentions(f"{title} {excerpt or ''}")
                    categories = _clean_list(raw.get("categories"))
                    tickers = _clean_list(raw.get("company_tickers"))
                    received = raw.get("received_at")
                    received_at = None
                    if received:
                        try:
                            received_at = parse_timestamp(received)
                        except (ValueError, TypeError):
                            flags.append("bad_received_at")
                    record = ArticleRecord(
                        article_id=stable_id(feed_file, normalize_ws(raw["$id"])),
                        **{"$id": normalize_ws(raw["$id"])},
                        original_language=language,
                        available_languages=[language] if language else None,
                        primary_topic=slugify(title),
                        secondary_topics=[slugify(c) for c in categories[:6]] or None,
                        primary_country=countries[0] if countries else None,
                        related_countries=countries[1:] or None,
                        affected_countries=None,
                        published_at_utc=published,
                        permalink=permalink,
                        publisher=publication,
                        importance=None,
                        author=author,
                        title=title,
                        excerpt=excerpt,
                        provider=normalize_ws(raw.get("publisher")) or None,
                        feed_file=feed_file,
                        text_char_count=len(text),
                        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        received_at_utc=received_at,
                        categories=categories,
                        company_tickers=tickers,
                        quality_flags=flags,
                    )
                    records.append(record)
                    timestamps.append(published)
                    feed_valid += 1
                    valid_records += 1
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    error = {"file": feed_file, "line": line_no, "code": "invalid_record", "message": str(exc)}
                    feed_errors.append(error)
                    errors.append(error)
                    feed_skipped += 1
                    skipped_records += 1

        reports.append(
            FeedReport(
                feed_file=feed_file,
                input_count=feed_input,
                valid_count=feed_valid,
                skipped_count=feed_skipped,
                errors=feed_errors,
            )
        )

    window_start: datetime | None = None
    window_end: datetime | None = None
    if config.mode == "daily":
        reference = max(timestamps) if timestamps else generated_at
        window_end = reference
        window_start = reference - timedelta(hours=config.window_hours)
        included: list[ArticleRecord] = []
        for record in records:
            if window_start <= record.published_at_utc <= window_end:
                included.append(record)
            else:
                report = next(r for r in reports if r.feed_file == record.feed_file)
                report.excluded_old_count += 1
                report.included_count += 0
        for report in reports:
            report.included_count = sum(1 for r in included if r.feed_file == report.feed_file)
        records = included
    else:
        for report in reports:
            report.included_count = report.valid_count

    report = S0Report(
        generated_at_utc=generated_at,
        mode=config.mode,
        window_start_utc=window_start,
        window_end_utc=window_end,
        total_input=total_input,
        valid_records=valid_records,
        skipped_records=skipped_records,
        included_in_window=len(records),
        excluded_old=sum(r.excluded_old_count for r in reports),
        feeds=reports,
    )
    return records, report


def write_outputs(config: Config, records: list[ArticleRecord], report: S0Report) -> dict[str, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    articles_path = config.output_dir / "articles.json"
    report_path = config.output_dir / "s0_validation_report.json"
    articles_path.write_text(json.dumps([r.model_dump(mode="json", by_alias=True) for r in records], indent=2, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return {"articles": articles_path, "report": report_path}


def load_articles(path: Path) -> list[ArticleRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ArticleRecord.model_validate(item) for item in payload]


def input_counts(config: Config) -> dict[str, int]:
    counts = {}
    for feed_file in FEED_FILES:
        path = config.data_dir / feed_file
        counts[feed_file] = sum(1 for line in path.open(encoding="utf-8") if line.strip()) if path.exists() else 0
    return counts
