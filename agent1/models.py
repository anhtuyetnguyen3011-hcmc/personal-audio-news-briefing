from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.1.0"

VerificationStatus = Literal["candidate", "unverified", "review_needed", "verified"]
WindowStatus = Literal["included", "excluded_old"]


class BaseRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SharedMetadata(BaseRecord):
    article_id: str
    story_id: str | None = None
    original_language: str | None = None
    available_languages: list[str] | None = None
    primary_topic: str | None = None
    secondary_topics: list[str] | None = None
    primary_country: str | None = None
    related_countries: list[str] | None = None
    affected_countries: list[str] | None = None
    published_at_utc: datetime
    permalink: str
    publisher: str
    importance: float | None = None


class ArticleRecord(SharedMetadata):
    schema_version: str = SCHEMA_VERSION
    original_id: str = Field(alias="$id")
    author: str | None = None
    title: str
    excerpt: str | None = None
    provider: str | None = None
    feed_file: str
    text_char_count: int
    text_sha256: str
    received_at_utc: datetime | None = None
    categories: list[str] = Field(default_factory=list)
    company_tickers: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    window_status: WindowStatus = "included"

    @field_validator("original_language", mode="before")
    @classmethod
    def _language(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text[:2] if text else None


class FeedReport(BaseRecord):
    feed_file: str
    input_count: int
    valid_count: int
    skipped_count: int
    included_count: int = 0
    excluded_old_count: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class S0Report(BaseRecord):
    schema_version: str = SCHEMA_VERSION
    stage: Literal["S0"] = "S0"
    generated_at_utc: datetime
    mode: str
    window_start_utc: datetime | None = None
    window_end_utc: datetime | None = None
    total_input: int
    valid_records: int
    skipped_records: int
    included_in_window: int
    excluded_old: int
    feeds: list[FeedReport]


class StoryRecord(SharedMetadata):
    schema_version: str = SCHEMA_VERSION
    canonical_title: str
    topic_key: str
    published_at_utc: datetime
    last_published_at_utc: datetime
    article_ids: list[str]
    permalinks: list[str]
    publishers: list[str]
    authors: list[str]
    languages: list[str]
    translation_groups: list[list[str]] = Field(default_factory=list)
    independent_source_count: int
    importance: float
    importance_breakdown: dict[str, float] = Field(default_factory=dict)
    reporting_differences: list[str] = Field(default_factory=list)
    cluster_evidence: list[dict[str, Any]] = Field(default_factory=list)
    selection_method: Literal["rule_1_translation", "rule_2_semantic", "rule_3_cross_publisher"] = "rule_2_semantic"


class S1Report(BaseRecord):
    schema_version: str = SCHEMA_VERSION
    stage: Literal["S1"] = "S1"
    generated_at_utc: datetime
    input_articles: int
    translation_pairs: int
    semantic_pairs: int
    cross_publisher_merges: int
    story_count: int
    cluster_size_histogram: dict[str, int]
    thresholds: dict[str, Any]


class NormalizedFigure(BaseRecord):
    raw: str
    value: float | None = None
    unit: str | None = None
    currency: str | None = None
    context: str | None = None


class FactRecord(SharedMetadata):
    schema_version: str = SCHEMA_VERSION
    fact_id: str
    claim_text: str
    source_article_id: str
    source_original_id: str = Field(alias="$id")
    source_span: str
    source_start_char: int
    source_end_char: int
    figures: list[NormalizedFigure] = Field(default_factory=list)
    numerical_values: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = "candidate"
    review_reasons: list[str] = Field(default_factory=list)
    selection_method: Literal["deterministic_regex", "llm_refined"] = "deterministic_regex"

    @field_validator("source_start_char", "source_end_char")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("character offsets must be non-negative")
        return value


class S2Report(BaseRecord):
    schema_version: str = SCHEMA_VERSION
    stage: Literal["S2"] = "S2"
    generated_at_utc: datetime
    stories_processed: int
    facts_emitted: int
    facts_rejected: int
    span_validation_passed: int
    span_validation_failed: int
    conflicts_detected: int
    unverified_claims: int
    llm_calls: int
    estimated_cost_usd: float


class EvaluationReport(BaseRecord):
    schema_version: str = SCHEMA_VERSION
    generated_at_utc: datetime
    mode: str
    targets: list[dict[str, Any]]
    summary: dict[str, Any]
