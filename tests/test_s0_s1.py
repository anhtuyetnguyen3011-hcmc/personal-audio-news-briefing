from __future__ import annotations

from agent1.config import Config
from agent1.s0_ingest import ingest, load_articles, stable_id, write_outputs
from agent1.s1_cluster import cluster, load_stories, write_outputs as write_stories


def test_s0_normalizes_and_filters_window(mock_config: Config, s0_articles: list[dict]):
    articles, report = ingest(mock_config)

    assert report.total_input == 4
    assert report.valid_records == 4
    assert report.skipped_records == 0
    assert report.included_in_window == 3
    assert report.excluded_old == 1
    assert len(articles) == 3
    assert all(a.published_at_utc.tzinfo is not None for a in articles)
    assert all(a.original_id.startswith(("EN-", "DE-", "NL-")) for a in articles)
    assert {a.feed_file for a in articles} == {"invezz_en.jsonl", "invezz_de.jsonl", "invezz_nl.jsonl"}

    paths = write_outputs(mock_config, articles, report)
    reloaded = load_articles(paths["articles"])
    assert [a.article_id for a in reloaded] == [a.article_id for a in articles]
    assert reloaded[0].article_id == stable_id(reloaded[0].feed_file, reloaded[0].original_id)


def test_s0_detects_missing_critical_fields(mock_config: Config):
    good = {
        "$id": "OK-1",
        "date": "2026-11-20T10:00:00+00:00",
        "headline": "Valid market headline",
        "excerpt": "Valid excerpt",
        "text_content": "Valid long text content for normalization and downstream fact extraction.",
        "permalink": "https://example.com/ok-1",
        "language": "en",
        "publication": {"name": "Invezz"},
        "publisher": "Invezz",
        "source": "Reporter",
    }
    bad = {**good, "$id": "BAD-1", "permalink": ""}
    lines = "\n".join([__import__("json").dumps(good), __import__("json").dumps(bad)]) + "\n"
    (mock_config.data_dir / "invezz_en.jsonl").write_text(lines, encoding="utf-8")

    _, report = ingest(mock_config)
    feed = next(f for f in report.feeds if f.feed_file == "invezz_en.jsonl")

    assert feed.input_count == 2
    assert feed.valid_count == 1
    assert feed.skipped_count == 1
    assert any(error["code"] == "missing_permalink" for error in feed.errors)


def test_s1_merges_translation_duplicates_and_preserves_contract(mock_config: Config, s0_articles: list[dict]):
    articles, _ = ingest(mock_config)
    original_to_article = {a.original_id: a.article_id for a in articles}
    stories, report = cluster(mock_config, articles)

    assert report.input_articles == 3
    matched = next(
        s for s in stories
        if {original_to_article["EN-1"], original_to_article["DE-1"], original_to_article["NL-1"]} <= set(s.article_ids)
    )
    payload = matched.model_dump(mode="json")

    for field in (
        "article_id", "story_id", "original_language", "available_languages", "primary_topic",
        "secondary_topics", "primary_country", "related_countries", "affected_countries",
        "published_at_utc", "permalink", "publisher", "importance",
    ):
        assert field in payload

    assert len(matched.article_ids) == 3
    assert len(matched.permalinks) == 3
    assert set(matched.languages) == {"de", "en", "nl"}
    assert matched.independent_source_count >= 1
    assert write_stories(mock_config, stories, report)["stories"].exists()
    assert [s.story_id for s in load_stories(mock_config.output_dir / "stories.json")] == [s.story_id for s in stories]
