from __future__ import annotations

import pytest

from agent1.shared_adapter import AdapterError, adapt_to_shared_v1


def _synthetic_batch() -> tuple[list[dict], list[dict], list[dict]]:
    articles: list[dict] = []
    stories: list[dict] = []
    facts: list[dict] = []
    for index in range(5):
        article_id = f"art_synthetic{index:08d}"
        story_id = f"story_synthetic{index:08d}"
        fact_id = f"fact_synthetic{index:08d}"
        articles.append(
            {
                "article_id": article_id,
                "$id": f"SYN-{index}",
                "original_language": "en",
                "available_languages": ["en"],
                "primary_topic": "synthetic-topic",
                "secondary_topics": ["markets"],
                "primary_country": None,
                "related_countries": None,
                "affected_countries": None,
                "published_at_utc": "2026-11-20T10:00:00Z",
                "permalink": f"https://example.com/synthetic-{index}",
                "publisher": "Synthetic Publisher",
                "importance": 0.5,
                "author": "Synthetic Reporter",
                "title": "Synthetic headline",
                "excerpt": "Synthetic excerpt",
                "feed_file": "synthetic.jsonl",
                "text_char_count": 80,
                "text_sha256": "0" * 64,
            }
        )
        stories.append(
            {
                "article_id": article_id,
                "story_id": story_id,
                "original_language": "en",
                "available_languages": ["en"],
                "primary_topic": "synthetic-topic",
                "secondary_topics": ["markets"],
                "primary_country": None,
                "related_countries": None,
                "affected_countries": None,
                "published_at_utc": "2026-11-20T10:00:00Z",
                "permalink": f"https://example.com/synthetic-{index}",
                "publisher": "Synthetic Publisher",
                "importance": 0.5,
                "canonical_title": "Synthetic story",
                "topic_key": "synthetic-topic",
                "last_published_at_utc": "2026-11-20T10:05:00Z",
                "article_ids": [article_id],
                "permalinks": [f"https://example.com/synthetic-{index}"],
                "publishers": ["Synthetic Publisher"],
                "authors": ["Synthetic Reporter"],
                "languages": ["en"],
                "translation_groups": [],
                "independent_source_count": 1,
                "importance_breakdown": {},
                "reporting_differences": [],
                "cluster_evidence": [],
                "selection_method": "rule_2_semantic",
            }
        )
        facts.append(
            {
                "article_id": article_id,
                "story_id": story_id,
                "original_language": "en",
                "available_languages": ["en"],
                "primary_topic": "synthetic-topic",
                "secondary_topics": ["markets"],
                "primary_country": None,
                "related_countries": None,
                "affected_countries": None,
                "published_at_utc": "2026-11-20T10:00:00Z",
                "permalink": f"https://example.com/synthetic-{index}",
                "publisher": "Synthetic Publisher",
                "importance": 0.5,
                "fact_id": fact_id,
                "claim_text": "Synthetic source sentence with 5%.",
                "$id": f"SYN-{index}",
                "source_article_id": article_id,
                "source_span": "Synthetic source sentence with 5%.",
                "source_start_char": 0,
                "source_end_char": 32,
                "figures": [],
                "numerical_values": ["5%"],
                "conflicts_with": [],
                "verification_status": "candidate",
                "review_reasons": [],
                "selection_method": "deterministic_regex",
            }
        )
    return articles, stories, facts


def test_shared_adapter_fails_closed_on_five_synthetic_stories() -> None:
    articles, stories, facts = _synthetic_batch()
    with pytest.raises(AdapterError) as exc_info:
        adapt_to_shared_v1(articles, stories, facts)
    message = str(exc_info.value)
    assert "run_id" in message
    assert "processing_metadata" in message
    assert "generated_content" in message
    assert "claim" in message
    assert "verification_status" in message
