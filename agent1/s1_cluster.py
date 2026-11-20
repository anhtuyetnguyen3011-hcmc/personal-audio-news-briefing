from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .embeddings import Embedder
from .models import ArticleRecord, S1Report, StoryRecord
from .s0_ingest import load_articles
from .text import (
    build_gazetteer,
    cosine,
    country_mentions,
    extract_entities,
    fold,
    jaccard,
    normalize_ws,
    numeric_signature,
    slugify,
    tokenize,
)

INVEZZ_FEEDS = {"invezz_en.jsonl", "invezz_de.jsonl", "invezz_nl.jsonl"}


class UnionFind:
    def __init__(self, items: list[str]):
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> bool:
        a, b = self.find(left), self.find(right)
        if a == b:
            return False
        self.parent[b] = a
        return True


def _intro(article: ArticleRecord) -> str:
    return normalize_ws(f"{article.title} {article.excerpt or ''}")


def _article_features(article: ArticleRecord, vector: dict[str, float], gazetteer: set[str]) -> dict[str, Any]:
    intro = _intro(article)
    entities = {fold(e) for e in extract_entities(intro, gazetteer) + article.company_tickers}
    return {
        "vector": vector,
        "entities": entities,
        "numbers": set(numeric_signature(intro)),
        "tokens": set(tokenize(intro)),
        "countries": set(country_mentions(intro)),
    }


def _score(left: dict[str, Any], right: dict[str, Any], config: Config) -> tuple[float, set[str], int, float]:
    similarity = cosine(left["vector"], right["vector"])
    shared_entities = left["entities"] & right["entities"]
    entity_overlap = len(shared_entities)
    number_overlap = len(left["numbers"] & right["numbers"])
    token_overlap = jaccard(left["tokens"], right["tokens"])
    score = (
        similarity
        + min(entity_overlap, 4) * config.entity_boost
        + min(number_overlap, 3) * config.numeric_boost
    )
    return score, shared_entities, number_overlap, token_overlap


def _is_translation_pair(a: ArticleRecord, b: ArticleRecord, score: float, entities: int, numbers: int, tokens: float, config: Config) -> bool:
    if a.feed_file not in INVEZZ_FEEDS or b.feed_file not in INVEZZ_FEEDS:
        return False
    if a.feed_file == b.feed_file:
        return False
    if a.original_language == b.original_language:
        return False
    if not a.author or a.author != b.author:
        return False
    delta = abs((a.published_at_utc - b.published_at_utc).total_seconds())
    if delta > config.translation_window_minutes * 60:
        return False
    if score < config.translation_similarity_threshold:
        return False
    if entities < 1:
        return False
    return numbers >= 1 or tokens >= 0.10 or entities >= 2


def _is_semantic_pair(
    score: float,
    shared_entities: set[str],
    numbers: int,
    tokens: float,
    config: Config,
) -> bool:
    entities = len(shared_entities)
    multiword = any(" " in entity and len(entity) > 6 for entity in shared_entities)
    if score < config.semantic_similarity_threshold:
        return False
    if entities >= 3 and numbers >= 1 and tokens >= 0.03:
        return True
    if entities >= 3 and tokens >= 0.20 and score >= config.high_similarity_threshold:
        return True
    if entities >= 2 and multiword and numbers >= 1 and tokens >= 0.04:
        return True
    if entities == 1 and numbers >= 1 and tokens >= 0.12 and score >= config.high_similarity_threshold:
        return True
    return numbers >= 2 and tokens >= 0.22 and score >= config.high_similarity_threshold


def cluster(config: Config, articles: list[ArticleRecord] | None = None) -> tuple[list[StoryRecord], S1Report]:
    generated_at = datetime.now(timezone.utc)
    records = articles if articles is not None else load_articles(config.output_dir / "articles.json")
    embedder = Embedder(config)
    intros = [_intro(article) for article in records]
    vectors = embedder.embed(intros)
    gazetteer = build_gazetteer(intros)
    features = {
        article.article_id: _article_features(article, vector, gazetteer)
        for article, vector in zip(records, vectors)
    }
    ordered = sorted(records, key=lambda a: a.published_at_utc)
    uf = UnionFind([a.article_id for a in records])

    translation_pairs = 0
    semantic_pairs = 0
    cross_publisher_merges = 0
    cross_merges: list[dict[str, Any]] = []
    accepted: dict[tuple[str, str], dict[str, Any]] = {}
    window_seconds = config.cluster_window_hours * 3600

    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            delta = (right.published_at_utc - left.published_at_utc).total_seconds()
            if delta > window_seconds:
                break
            score, shared, numbers, tokens = _score(features[left.article_id], features[right.article_id], config)
            entities = len(shared)
            if _is_translation_pair(left, right, score, entities, numbers, tokens, config):
                rule = "rule_1_translation"
                translation_pairs += 1
            elif _is_semantic_pair(score, shared, numbers, tokens, config):
                rule = "rule_2_semantic"
                semantic_pairs += 1
            else:
                continue
            key = tuple(sorted((left.article_id, right.article_id)))
            accepted[key] = {
                "rule": rule,
                "score": round(score, 4),
                "entities": entities,
                "numbers": numbers,
                "token_jaccard": round(tokens, 4),
                "dual_anchor": entities >= 2 and any(" " in entity and len(entity) > 6 for entity in shared),
                "left": left.article_id,
                "right": right.article_id,
            }

    translation_uf = UnionFind([a.article_id for a in records])
    for pair in accepted.values():
        if pair["rule"] == "rule_1_translation":
            translation_uf.union(pair["left"], pair["right"])

    sizes = {article.article_id: 1 for article in records}
    changed = True
    while changed:
        changed = False
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for pair in accepted.values():
            left_root, right_root = uf.find(pair["left"]), uf.find(pair["right"])
            if left_root == right_root:
                continue
            groups[tuple(sorted((left_root, right_root)))].append(pair)
        for (left_root, right_root), pairs in groups.items():
            left_root, right_root = uf.find(left_root), uf.find(right_root)
            if left_root == right_root:
                continue
            combined_size = sizes[left_root] + sizes[right_root]
            best = max(pairs, key=lambda item: item["score"])
            has_translation = any(item["rule"] == "rule_1_translation" for item in pairs)
            has_dual_anchor = any(
                item["dual_anchor"]
                and item["score"] >= 0.68
                and item["numbers"] >= 1
                and item["token_jaccard"] >= 0.06
                for item in pairs
            )
            if has_translation:
                should_merge = combined_size <= 30 or (best["score"] >= 0.8 and best["numbers"] >= 1)
            elif has_dual_anchor and combined_size <= 40:
                should_merge = True
            elif combined_size > 8:
                should_merge = (
                    len(pairs) >= 2
                    and best["score"] >= config.high_similarity_threshold
                    and best["entities"] >= 3
                    and best["numbers"] >= 1
                ) or (
                    best["score"] >= 0.75
                    and best["numbers"] >= 2
                    and best["token_jaccard"] >= 0.12
                    and combined_size <= 60
                )
            else:
                should_merge = (
                    len(pairs) >= 2
                    or (best["score"] >= 0.85 and best["entities"] >= 3 and best["numbers"] >= 1)
                    or (best["score"] >= 0.75 and best["numbers"] >= 2 and best["token_jaccard"] >= 0.12)
                )
            if should_merge:
                sizes[left_root] += sizes[right_root]
                del sizes[right_root]
                uf.union(left_root, right_root)
                changed = True

    components: dict[str, list[ArticleRecord]] = defaultdict(list)
    for article in records:
        components[uf.find(article.article_id)].append(article)

    component_ids = list(components)
    for c_index, left_root in enumerate(component_ids):
        for right_root in component_ids[c_index + 1 :]:
            left_articles = components[left_root]
            right_articles = components[right_root]
            if not ({a.publisher for a in left_articles} & {a.publisher for a in right_articles}):
                best = None
                for left in left_articles:
                    for right in right_articles:
                        score, shared, numbers, tokens = _score(features[left.article_id], features[right.article_id], config)
                        entities = len(shared)
                        if entities < 3 or numbers < 1 or tokens < 0.08:
                            continue
                        if score >= 0.85:
                            if best is None or score > best[0]:
                                best = (score, left, right, entities, numbers)
                if best:
                    uf.union(left_root, right_root)
                    cross_publisher_merges += 1
                    cross_merges.append(
                        {
                            "rule": "rule_3_cross_publisher",
                            "score": round(best[0], 4),
                            "entities": best[3],
                            "numbers": best[4],
                            "left": best[1].article_id,
                            "right": best[2].article_id,
                        }
                    )

    merged: dict[str, list[ArticleRecord]] = defaultdict(list)
    for article in records:
        merged[uf.find(article.article_id)].append(article)

    pair_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in [*accepted.values(), *cross_merges]:
        pair_evidence[uf.find(pair["left"])].append(pair)

    reference = max((a.published_at_utc for a in records), default=generated_at)
    stories: list[StoryRecord] = []
    for members in merged.values():
        members = sorted(members, key=lambda a: (a.published_at_utc, a.article_id))
        degrees = Counter()
        for evidence in pair_evidence.get(uf.find(members[0].article_id), []):
            degrees[evidence["left"]] += 1
            degrees[evidence["right"]] += 1
        representative = max(members, key=lambda a: (degrees[a.article_id], a.text_char_count, a.published_at_utc))
        article_ids = [a.article_id for a in members]
        story_id = "story_" + hashlib.sha256("|".join(sorted(article_ids)).encode("utf-8")).hexdigest()[:16]
        publishers = sorted({a.publisher for a in members})
        languages = sorted({a.original_language or "unknown" for a in members})
        translation_groups: dict[str, list[str]] = defaultdict(list)
        for article in members:
            translation_groups[translation_uf.find(article.article_id)].append(article.article_id)
        independent_sources = {(a.publisher, translation_uf.find(a.article_id)) for a in members}
        age_hours = max(0.0, (reference - representative.published_at_utc).total_seconds() / 3600)
        recency = max(0.0, 1.0 - (age_hours / max(1, config.cluster_window_hours * 2)))
        source_coverage = min(len(independent_sources) / 5.0, 1.0)
        publisher_diversity = min(len(publishers) / 4.0, 1.0)
        importance = round(0.35 * recency + 0.45 * source_coverage + 0.20 * publisher_diversity, 4)
        countries: list[str] = []
        for article in members:
            for country in country_mentions(f"{article.title} {article.excerpt or ''}"):
                if country not in countries:
                    countries.append(country)
        categories: list[str] = []
        for article in members:
            for category in article.secondary_topics or []:
                if category not in categories:
                    categories.append(category)
        numbers_by_publisher: dict[str, set[str]] = defaultdict(set)
        for article in members:
            numbers_by_publisher[article.publisher].update(numeric_signature(_intro(article)))
        differences: list[str] = []
        all_numbers = set().union(*numbers_by_publisher.values()) if numbers_by_publisher else set()
        if len(publishers) > 1 and len(all_numbers) > 1:
            differences.append("Publishers report different numeric details for the same event")
        evidence = pair_evidence.get(uf.find(members[0].article_id), [])
        stories.append(
            StoryRecord(
                article_id=representative.article_id,
                story_id=story_id,
                original_language=representative.original_language,
                available_languages=languages,
                primary_topic=slugify(representative.title),
                secondary_topics=categories[:8] or None,
                primary_country=countries[0] if countries else None,
                related_countries=countries[1:] or None,
                affected_countries=None,
                published_at_utc=members[0].published_at_utc,
                permalink=representative.permalink,
                publisher=representative.publisher,
                importance=importance,
                canonical_title=representative.title,
                topic_key=slugify(representative.title),
                last_published_at_utc=members[-1].published_at_utc,
                article_ids=article_ids,
                permalinks=[a.permalink for a in members],
                publishers=publishers,
                authors=sorted({a.author for a in members if a.author}),
                languages=languages,
                translation_groups=[sorted(group) for group in translation_groups.values() if len(group) > 1],
                independent_source_count=len(independent_sources),
                importance_breakdown={
                    "recency": round(recency, 4),
                    "source_coverage": round(source_coverage, 4),
                    "publisher_diversity": round(publisher_diversity, 4),
                    "independent_sources": float(len(independent_sources)),
                },
                reporting_differences=differences,
                cluster_evidence=evidence[:6],
                selection_method=_selection_method(evidence),
            )
        )
    stories.sort(key=lambda s: (-s.importance, s.published_at_utc, s.story_id))

    histogram = Counter(str(len(s.article_ids)) for s in stories)
    report = S1Report(
        generated_at_utc=generated_at,
        input_articles=len(records),
        translation_pairs=translation_pairs,
        semantic_pairs=semantic_pairs,
        cross_publisher_merges=cross_publisher_merges,
        story_count=len(stories),
        cluster_size_histogram=dict(sorted(histogram.items())),
        thresholds={
            "cluster_window_hours": config.cluster_window_hours,
            "translation_window_minutes": config.translation_window_minutes,
            "translation_similarity_threshold": config.translation_similarity_threshold,
            "semantic_similarity_threshold": config.semantic_similarity_threshold,
            "min_shared_entities": config.min_shared_entities,
            "min_shared_signals": config.min_shared_signals,
            "high_similarity_threshold": config.high_similarity_threshold,
            "entity_boost": config.entity_boost,
            "numeric_boost": config.numeric_boost,
            "embedding_provider": embedder.provider_used,
        },
    )
    return stories, report


def _selection_method(evidence: list[dict[str, Any]]) -> str:
    rules = {item["rule"] for item in evidence}
    if "rule_3_cross_publisher" in rules:
        return "rule_3_cross_publisher"
    if "rule_1_translation" in rules:
        return "rule_1_translation"
    return "rule_2_semantic"


def write_outputs(config: Config, stories: list[StoryRecord], report: S1Report) -> dict[str, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    stories_path = config.output_dir / "stories.json"
    report_path = config.output_dir / "s1_validation_report.json"
    stories_path.write_text(json.dumps([s.model_dump(mode="json") for s in stories], indent=2, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return {"stories": stories_path, "report": report_path}


def load_stories(path: Path) -> list[StoryRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [StoryRecord.model_validate(item) for item in payload]


TARGETS = (
    {
        "name": "US Producer Prices",
        "all_of": (),
        "any_of": ("producer prices", "wholesale inflation", "großhandelsinflation", "groothandelsinflatie", "ppi slows"),
    },
    {
        "name": "Intel shareholder lawsuit",
        "all_of": ("intel",),
        "any_of": ("lawsuit", "klage"),
    },
    {
        "name": "Jensen Huang/Nvidia event",
        "all_of": (),
        "any_of": ("jensen huang", "huang's return", "colette kress", "rene haas", "war room", "nvidia exit"),
    },
)


def _matches_target(text: str, target: dict[str, Any]) -> bool:
    lowered = text.lower()
    for term in target["all_of"]:
        if not re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", lowered):
            return False
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", lowered) for term in target["any_of"])


def evaluate_targets(stories: list[StoryRecord], articles: list[ArticleRecord]) -> dict[str, Any]:
    article_ids = {a.article_id for a in articles}
    results = []
    for target in TARGETS:
        matched = []
        for article in articles:
            if _matches_target(f"{article.title} {article.excerpt or ''}", target):
                matched.append(article.article_id)
        story_ids = {next((s.story_id for s in stories if article_id in s.article_ids), None) for article_id in matched}
        story_ids.discard(None)
        clusters = [
            {
                "story_id": sid,
                "size": next(len(s.article_ids) for s in stories if s.story_id == sid),
                "title": next(s.canonical_title for s in stories if s.story_id == sid),
            }
            for sid in sorted(story_ids)
        ]
        results.append(
            {
                "target": target["name"],
                "matched_articles": len(matched),
                "matched_in_input": sum(1 for aid in matched if aid in article_ids),
                "cluster_count": len(clusters),
                "passed": len(clusters) == 1,
                "clusters": clusters,
            }
        )
    summary = {
        "targets": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
    }
    return {"targets": results, "summary": summary}
