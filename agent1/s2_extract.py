from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .models import FactRecord, NormalizedFigure, S2Report, StoryRecord
from .s0_ingest import FEED_FILES, stable_id
from .s1_cluster import load_stories
from .text import extract_entities, extract_figures, jaccard, normalize_ws, parse_timestamp, split_sentences, tokenize

BOILERPLATE = ("subscribe", "sign up", "newsletter", "advertisement", "follow us", "click here")
HEDGING = ("reportedly", "may", "could", "might", "allegedly", "expected", "possible")


def load_raw_texts(config: Config) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for feed_file in FEED_FILES:
        path = config.data_dir / feed_file
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw = json.loads(line)
                original_id = normalize_ws(raw.get("$id"))
                article_id = stable_id(feed_file, original_id)
                index[article_id] = {
                    "$id": original_id,
                    "permalink": normalize_ws(raw.get("permalink")),
                    "text_content": normalize_ws(raw.get("text_content")),
                    "publisher": normalize_ws((raw.get("publication") or {}).get("name")) or normalize_ws(raw.get("publisher")),
                    "language": normalize_ws(raw.get("language")).lower()[:2] or None,
                    "published_at_utc": parse_timestamp(raw.get("date")),
                }
    return index


def _sentence_score(sentence: str, story: StoryRecord, figures: list[dict[str, Any]]) -> float:
    score = float(len(figures)) * 2.0
    tokens = set(tokenize(sentence))
    topic_tokens = set(tokenize(story.primary_topic or "")) | set(tokenize(story.canonical_title))
    score += len(tokens & topic_tokens) * 0.5
    entities = {entity.lower() for entity in extract_entities(sentence)}
    story_entities = {entity.lower() for entity in extract_entities(story.canonical_title)}
    score += len(entities & story_entities) * 1.0
    if 60 <= len(sentence) <= 260:
        score += 1.0
    if any(word in sentence.lower() for word in BOILERPLATE):
        score -= 5.0
    return score


def _refine_with_llm(config: Config, story: StoryRecord, sentence: str, span: str) -> str:
    if config.llm_provider != "openai" or config.dry_run or not os.getenv("OPENAI_API_KEY"):
        return span
    try:
        from openai import OpenAI
    except ImportError:
        return span
    client = OpenAI(timeout=config.request_timeout_seconds, max_retries=config.max_retries)
    prompt = (
        "Select the most concise factual claim from the quoted source span. "
        "Return JSON with keys source_span and claim_text. Do not invent facts.\n"
        f"STORY: {story.canonical_title}\nSOURCE SPAN: {sentence}\n"
    )
    try:
        response = client.responses.create(model=config.llm_model, input=prompt)
        payload = json.loads(response.output_text)
        candidate_span = normalize_ws(payload.get("source_span", ""))
        claim = normalize_ws(payload.get("claim_text", ""))
        if candidate_span == span and claim and len(claim) <= len(span) + 40:
            return claim
    except (ValueError, AttributeError, TypeError):
        return span
    return span


def _build_fact(config: Config, story: StoryRecord, article_id: str, raw: dict[str, Any], sentence: str, start: int, end: int, selection_method: str) -> FactRecord | None:
    text = raw["text_content"]
    if text[start:end] != sentence:
        return None
    figures_raw = extract_figures(sentence)
    figures = [NormalizedFigure(**figure) for figure in figures_raw]
    numerical_values = [figure["raw"] for figure in figures_raw]
    claim_text = _refine_with_llm(config, story, sentence, sentence)
    reasons: list[str] = []
    if not figures:
        reasons.append("no_figure_found")
    if any(word in sentence.lower() for word in HEDGING):
        reasons.append("uncertain_language")
    status = "review_needed" if reasons else "candidate"
    fact_id = "fact_" + hashlib.sha256(f"{story.story_id}|{raw['$id']}|{start}|{sentence}".encode("utf-8")).hexdigest()[:16]
    return FactRecord(
        **{"$id": raw["$id"]},
        fact_id=fact_id,
        claim_text=claim_text,
        source_article_id=article_id,
        source_span=sentence,
        source_start_char=start,
        source_end_char=end,
        figures=figures,
        numerical_values=numerical_values,
        conflicts_with=[],
        verification_status=status,
        review_reasons=reasons,
        selection_method=selection_method,
        article_id=article_id,
        story_id=story.story_id,
        original_language=raw.get("language") or story.original_language,
        available_languages=story.available_languages,
        primary_topic=story.primary_topic,
        secondary_topics=story.secondary_topics,
        primary_country=story.primary_country,
        related_countries=story.related_countries,
        affected_countries=story.affected_countries,
        published_at_utc=raw["published_at_utc"],
        permalink=raw["permalink"],
        publisher=raw["publisher"],
        importance=story.importance,
    )


def extract_facts(config: Config, stories: list[StoryRecord] | None = None, raw_texts: dict[str, dict[str, Any]] | None = None) -> tuple[list[FactRecord], S2Report]:
    generated_at = datetime.now(timezone.utc)
    story_records = stories if stories is not None else load_stories(config.output_dir / "stories.json")
    raw = raw_texts if raw_texts is not None else load_raw_texts(config)
    facts: list[FactRecord] = []
    rejected = 0
    span_passed = 0
    span_failed = 0
    llm_calls = 0

    for story in story_records:
        candidates: list[tuple[float, str, dict[str, Any], str, int, int]] = []
        article_ids = story.article_ids[:12]
        for article_id in article_ids:
            source = raw.get(article_id)
            if not source or not source["text_content"]:
                continue
            for sentence, start, end in split_sentences(source["text_content"]):
                figures = extract_figures(sentence)
                score = _sentence_score(sentence, story, figures)
                candidates.append((score, article_id, source, sentence, start, end))
        candidates.sort(key=lambda item: (-item[0], item[2]["$id"], item[4]))
        selected = candidates[: config.fact_max]
        for score, source_id, source, sentence, start, end in selected:
            method = "llm_refined" if config.llm_provider == "openai" and not config.dry_run else "deterministic_regex"
            if method == "llm_refined":
                llm_calls += 1
            fact = _build_fact(config, story, source_id, source, sentence, start, end, method)
            if fact is None:
                rejected += 1
                span_failed += 1
                continue
            if fact.source_span not in source["text_content"]:
                rejected += 1
                span_failed += 1
                continue
            span_passed += 1
            facts.append(fact)

    publisher_by_article = {article_id: value["publisher"] for article_id, value in raw.items()}
    for index, fact in enumerate(facts):
        for other in facts[index + 1 :]:
            if fact.story_id != other.story_id:
                continue
            if publisher_by_article.get(fact.article_id) == publisher_by_article.get(other.article_id):
                continue
            for left in fact.figures:
                for right in other.figures:
                    if left.unit != right.unit or left.value == right.value:
                        continue
                    context_overlap = jaccard(tokenize(left.context or ""), tokenize(right.context or ""))
                    if context_overlap >= 0.30:
                        if other.fact_id not in fact.conflicts_with:
                            fact.conflicts_with.append(other.fact_id)
                        if fact.fact_id not in other.conflicts_with:
                            other.conflicts_with.append(fact.fact_id)
                        if "conflicting_values" not in fact.review_reasons:
                            fact.review_reasons.append("conflicting_values")
                        if "conflicting_values" not in other.review_reasons:
                            other.review_reasons.append("conflicting_values")
                        if fact.verification_status == "candidate":
                            fact.verification_status = "review_needed"
                        if other.verification_status == "candidate":
                            other.verification_status = "review_needed"

    token_estimate = sum(len(f.claim_text) / 4 for f in facts)
    estimated_cost = (0.10 * token_estimate + 0.50 * token_estimate / 4) / 1_000_000 if llm_calls else 0.0
    report = S2Report(
        generated_at_utc=generated_at,
        stories_processed=len(story_records),
        facts_emitted=len(facts),
        facts_rejected=rejected,
        span_validation_passed=span_passed,
        span_validation_failed=span_failed,
        conflicts_detected=sum(1 for f in facts if f.conflicts_with),
        unverified_claims=sum(1 for f in facts if f.verification_status != "candidate"),
        llm_calls=llm_calls,
        estimated_cost_usd=round(estimated_cost, 6),
    )
    return facts, report


def write_outputs(config: Config, facts: list[FactRecord], report: S2Report) -> dict[str, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    facts_path = config.output_dir / "facts.json"
    report_path = config.output_dir / "s2_validation_report.json"
    facts_path.write_text(json.dumps([f.model_dump(mode="json", by_alias=True) for f in facts], indent=2, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return {"facts": facts_path, "report": report_path}


def load_facts(path: Path) -> list[FactRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [FactRecord.model_validate(item) for item in payload]
