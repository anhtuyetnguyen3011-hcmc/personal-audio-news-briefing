from __future__ import annotations

from datetime import datetime, timezone

from agent1.config import Config
from agent1.models import StoryRecord
from agent1.s2_extract import extract_facts, load_facts, write_outputs


def _story(article_ids: list[str]) -> StoryRecord:
    published = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    return StoryRecord(
        article_id=article_ids[0],
        story_id="story_test",
        original_language="en",
        available_languages=["en", "de"],
        primary_topic="intel-lawsuit",
        secondary_topics=None,
        primary_country="United States",
        related_countries=None,
        affected_countries=None,
        published_at_utc=published,
        permalink="https://example.com/a",
        publisher="Publisher A",
        importance=0.8,
        canonical_title="Intel lawsuit over $23 billion share sale",
        topic_key="intel-lawsuit",
        last_published_at_utc=published,
        article_ids=article_ids,
        permalinks=["https://example.com/a", "https://example.com/b"],
        publishers=["Publisher A", "Publisher B"],
        authors=["Reporter"],
        languages=["en", "de"],
        independent_source_count=2,
        importance_breakdown={"recency": 1.0, "source_coverage": 0.4, "publisher_diversity": 0.5},
    )


def test_s2_spans_are_verbatim_and_conflicts_are_linked(mock_config: Config):
    text_a = "Intel faces a shareholder lawsuit over a $23 billion share sale after a 29% plunge. Investors allege executives hid weakening PC demand."
    text_b = "Intel sieht sich einer Klage wegen eines $24 billion share sale nach einem 28% plunge gegenüber. Analysts review the filing details carefully."
    raw_texts = {
        "art_a": {"$id": "A-1", "permalink": "https://example.com/a", "text_content": text_a, "publisher": "Publisher A", "language": "en", "published_at_utc": datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)},
        "art_b": {"$id": "B-1", "permalink": "https://example.com/b", "text_content": text_b, "publisher": "Publisher B", "language": "de", "published_at_utc": datetime(2026, 11, 20, 10, 5, tzinfo=timezone.utc)},
    }
    story = _story(["art_a", "art_b"])

    facts, report = extract_facts(mock_config, [story], raw_texts)

    assert report.facts_emitted >= 3
    assert report.span_validation_failed == 0
    assert report.llm_calls == 0
    for fact in facts:
        assert fact.source_span in raw_texts[fact.article_id]["text_content"]
        assert raw_texts[fact.article_id]["text_content"][fact.source_start_char : fact.source_end_char] == fact.source_span
        assert fact.verification_status in {"candidate", "review_needed", "unverified"}
        assert "positive" not in fact.claim_text.lower()
        assert "negative" not in fact.claim_text.lower()
    assert any(fact.conflicts_with for fact in facts)

    paths = write_outputs(mock_config, facts, report)
    assert [fact.fact_id for fact in load_facts(paths["facts"])] == [fact.fact_id for fact in facts]
