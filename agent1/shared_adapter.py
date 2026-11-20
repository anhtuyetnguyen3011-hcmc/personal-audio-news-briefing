from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "shared" / "schemas" / "v1"
SHARED_SCHEMA_VERSION = "1.0.0"
COMMON_SCHEMA_ID = "urn:liquid-briefing:schemas:v1:common"


class AdapterError(RuntimeError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("shared v1.0.0 adapter refused to emit output:\n" + "\n".join(f"- {error}" for error in errors))


def _dump(record: Any) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json", by_alias=True)
    return dict(record)


def _fail(errors: list[str], scope: str, field: str, reason: str) -> None:
    errors.append(f"{scope}: missing required shared-v1 field '{field}' ({reason})")


def _map_article(article: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
    scope = f"article {article.get('article_id', '<unknown>')}"
    required = {
        "article_id": article.get("article_id"),
        "source_feed": article.get("feed_file"),
        "language": article.get("original_language"),
        "publication": article.get("publisher"),
        "author": article.get("author"),
        "published_at": article.get("published_at_utc"),
        "permalink": article.get("permalink"),
        "headline_normalized": article.get("title"),
        "excerpt_normalized": article.get("excerpt"),
        "text_char_count": article.get("text_char_count"),
    }
    for field, value in required.items():
        if value is None or value == "":
            _fail(errors, scope, field, "no equivalent Agent 1 value")
    if article.get("run_id") is None:
        _fail(errors, scope, "run_id", "not emitted by S0")
    if article.get("content_hash") is None:
        _fail(errors, scope, "content_hash", "text_sha256 hashes full normalized text, not headline+excerpt")
    if article.get("processing_metadata") is None:
        _fail(errors, scope, "processing_metadata", "not emitted by S0")
    if any(error.startswith(scope) for error in errors):
        return None
    output = {
        "schema_version": SHARED_SCHEMA_VERSION,
        "run_id": article["run_id"],
        "article_id": article["article_id"],
        "source_feed": article["feed_file"],
        "language": article["original_language"],
        "publication": article["publisher"],
        "author": article["author"],
        "published_at": article["published_at_utc"],
        "permalink": article["permalink"],
        "headline_normalized": article["title"],
        "excerpt_normalized": article["excerpt"],
        "content_hash": article["content_hash"],
        "text_char_count": article["text_char_count"],
        "processing_metadata": article["processing_metadata"],
    }
    if article.get("categories"):
        output["categories"] = article["categories"]
    if article.get("company_tickers"):
        output["company_tickers"] = article["company_tickers"]
    if article.get("translation_group_id"):
        output["is_translation_candidate"] = True
        output["translation_group_id"] = article["translation_group_id"]
    return output


def _cluster_method(selection_method: str | None) -> str | None:
    if selection_method in {"rule_1_translation", "rule_2_semantic", "rule_3_cross_publisher"}:
        return "deterministic_rule"
    return None


def _map_story(
    story: dict[str, Any],
    articles_by_id: dict[str, dict[str, Any]],
    fact_ids: list[str],
    errors: list[str],
) -> dict[str, Any] | None:
    scope = f"story {story.get('story_id', '<unknown>')}"
    required = {
        "topic": story.get("canonical_title"),
        "topic_key": story.get("topic_key"),
        "languages": story.get("languages"),
        "article_ids": story.get("article_ids"),
        "importance_score": story.get("importance"),
        "published_at_start": story.get("published_at_utc"),
        "published_at_end": story.get("last_published_at_utc"),
    }
    for field, value in required.items():
        if value is None or value == "":
            _fail(errors, scope, field, "no equivalent Agent 1 value")
    primary_language = story.get("original_language") or (story.get("languages") or [None])[0]
    if primary_language is None:
        _fail(errors, scope, "primary_language", "no language on story")
    if story.get("run_id") is None:
        _fail(errors, scope, "run_id", "not emitted by S1")
    if story.get("generated_content") is None:
        _fail(errors, scope, "generated_content", "Agent 2 owns generated content")
    if story.get("processing_metadata") is None:
        _fail(errors, scope, "processing_metadata", "not emitted by S1")
    if story.get("needs_review") is None:
        _fail(errors, scope, "needs_review", "not emitted by S1")
    cluster_method = _cluster_method(story.get("selection_method"))
    if cluster_method is None:
        _fail(errors, scope, "cluster_method", "selection_method has no shared-v1 mapping")
    article_refs: list[dict[str, Any]] = []
    for article_id in story.get("article_ids") or []:
        article = articles_by_id.get(article_id)
        if article is None:
            _fail(errors, scope, "article_refs", f"article {article_id} is not in articles input")
            continue
        ref_required = {
            "permalink": article.get("permalink"),
            "publication": article.get("publication"),
            "published_at": article.get("published_at"),
            "language": article.get("language"),
            "source_feed": article.get("source_feed"),
            "content_hash": article.get("content_hash"),
        }
        for field, value in ref_required.items():
            if value is None or value == "":
                _fail(errors, scope, f"article_refs[].{field}", "no equivalent Agent 1 value")
        article_refs.append(
            {
                "article_id": article_id,
                "permalink": article["permalink"],
                "publication": article["publication"],
                "published_at": article["published_at"],
                "language": article["language"],
                "source_feed": article["source_feed"],
                "content_hash": article["content_hash"],
            }
        )
    if any(error.startswith(scope) for error in errors):
        return None
    return {
        "schema_version": SHARED_SCHEMA_VERSION,
        "run_id": story["run_id"],
        "story_id": story["story_id"],
        "topic": story["canonical_title"],
        "topic_key": story["topic_key"],
        "primary_language": primary_language,
        "languages": story["languages"],
        "article_ids": story["article_ids"],
        "article_refs": article_refs,
        "fact_ids": fact_ids,
        "importance_score": story["importance"],
        "published_at_start": story["published_at_utc"],
        "published_at_end": story["last_published_at_utc"],
        "cluster_method": cluster_method,
        "needs_review": story["needs_review"],
        "generated_content": story["generated_content"],
        "processing_metadata": story["processing_metadata"],
    }


def _map_fact(fact: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
    scope = f"fact {fact.get('fact_id', '<unknown>')}"
    if fact.get("run_id") is None:
        _fail(errors, scope, "run_id", "not emitted by S2")
    if fact.get("claim") is None:
        _fail(errors, scope, "claim", "claim_text is a verbatim source span, not a paraphrased claim")
    if fact.get("claim_type") is None:
        _fail(errors, scope, "claim_type", "not emitted by S2")
    if fact.get("confidence") is None:
        _fail(errors, scope, "confidence", "not emitted by S2")
    if fact.get("processing_metadata") is None:
        _fail(errors, scope, "processing_metadata", "not emitted by S2")
    if fact.get("verification_status") != "verified":
        errors.append(
            f"{scope}: unverified fact has verification_status={fact.get('verification_status')!r}; "
            "shared v1.0.0 export requires verified facts"
        )
    source_article_id = fact.get("source_article_id")
    permalink = fact.get("permalink")
    if not source_article_id:
        _fail(errors, scope, "source_article_ids", "no source_article_id")
    if not permalink:
        _fail(errors, scope, "source_permalinks", "no permalink")
    extraction_method = {
        "deterministic_regex": "deterministic",
        "llm_refined": "llm_structured",
    }.get(fact.get("selection_method"))
    if extraction_method is None:
        _fail(errors, scope, "extraction_method", "selection_method has no shared-v1 mapping")
    if any(error.startswith(scope) for error in errors):
        return None
    return {
        "schema_version": SHARED_SCHEMA_VERSION,
        "run_id": fact["run_id"],
        "fact_id": fact["fact_id"],
        "story_id": fact["story_id"],
        "claim": fact["claim"],
        "claim_type": fact["claim_type"],
        "source_article_ids": [fact["source_article_id"]],
        "source_permalinks": [fact["permalink"]],
        "evidence_refs": [
            {
                "article_id": fact["source_article_id"],
                "permalink": fact["permalink"],
                "locator": f"chars:{fact['source_start_char']}-{fact['source_end_char']}",
            }
        ],
        "verification_status": "verified",
        "confidence": fact["confidence"],
        "is_model_generated": fact.get("selection_method") == "llm_refined",
        "extraction_method": extraction_method,
        "numerical_values": fact.get("numerical_values", []),
        "conflict_with_fact_ids": fact.get("conflicts_with", []),
        "processing_metadata": fact["processing_metadata"],
    }


def _load_schema(name: str, schema_dir: Path) -> dict[str, Any]:
    text = (schema_dir / name).read_text(encoding="utf-8")
    if name != "common.schema.json":
        text = text.replace("common.schema.json#/$defs/", f"{COMMON_SCHEMA_ID}#/$defs/")
    return json.loads(text)


def _validate(streams: dict[str, list[dict[str, Any]]], schema_dir: Path) -> None:
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError as exc:
        raise AdapterError(["jsonschema and referencing are required to validate shared v1.0.0 records"]) from exc
    common = _load_schema("common.schema.json", schema_dir)
    registry = Registry().with_resources([(COMMON_SCHEMA_ID, Resource.from_contents(common))])
    for stream, records in streams.items():
        validator = Draft202012Validator(_load_schema(stream, schema_dir), registry=registry)
        for index, record in enumerate(records):
            errors = sorted(validator.iter_errors(record), key=lambda error: list(error.path))
            if errors:
                raise AdapterError(
                    [f"{stream}[{index}][{list(error.path)}]: {error.message}" for error in errors[:50]]
                )


def adapt_to_shared_v1(
    articles: list[Any],
    stories: list[Any],
    facts: list[Any],
    *,
    schema_dir: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    effective_schema_dir = Path(schema_dir) if schema_dir is not None else SCHEMA_DIR
    article_records = [_dump(record) for record in articles]
    story_records = [_dump(record) for record in stories]
    fact_records = [_dump(record) for record in facts]
    errors: list[str] = []
    fact_ids_by_story: dict[str, list[str]] = {}
    for fact in fact_records:
        fact_ids_by_story.setdefault(fact.get("story_id", ""), []).append(fact.get("fact_id", ""))

    mapped_articles = [record for article in article_records if (record := _map_article(article, errors))]
    mapped_facts = [record for fact in fact_records if (record := _map_fact(fact, errors))]
    articles_by_id = {article["article_id"]: article for article in mapped_articles}
    mapped_stories = [
        record
        for story in story_records
        if (
            record := _map_story(
                story,
                articles_by_id,
                fact_ids_by_story.get(story.get("story_id", ""), []),
                errors,
            )
        )
    ]
    if errors:
        raise AdapterError(errors)
    streams = {
        "article.schema.json": mapped_articles,
        "story.schema.json": mapped_stories,
        "evidence.schema.json": mapped_facts,
    }
    _validate(streams, effective_schema_dir)
    return streams
