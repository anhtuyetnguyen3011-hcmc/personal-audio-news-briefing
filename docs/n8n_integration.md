# Agent 1 → MAIN_flow_v1 n8n integration

Scope: Agent 1 S0–S2 only. S3–S7 are untouched. `MAIN_flow_v1` is not present in this repository, so this document defines a file-based handoff for n8n to read; it does not change team-owned workflow code.

No full-dataset rerun is required for integration. The existing `outputs/` artifacts are the handoff source and must be preserved.

## 1. Exact CLI commands

Global flags must precede the subcommand. From the project root:

```powershell
$Root = "C:\Users\ANH TUYET\OneDrive\Master of Management\Extracurricular Activities\MAIN Hackathon\liquid-briefing-agent"
$Data = "C:\Users\ANH TUYET\OneDrive\Master of Management\Extracurricular Activities\MAIN Hackathon\liquid-briefing-data"
$Out = "$Root\outputs"
$env:PYTHONPATH = $Root

python -m agent1.cli --data-dir $Data --output-dir $Out inspect
python -m agent1.cli --data-dir $Data --output-dir $Out s0 --mode full
python -m agent1.cli --data-dir $Data --output-dir $Out s1
python -m agent1.cli --data-dir $Data --output-dir $Out s2
python -m agent1.cli --data-dir $Data --output-dir $Out evaluate
python -m agent1.cli --data-dir $Data --output-dir $Out run --mode full
python -m agent1.cli --data-dir $Data --output-dir $Out run --mode daily --hours 24
python -m pytest -q "$Root\tests"
```

n8n should not call `run` during a normal briefing; it should read the already-generated `outputs/*.json`. Use `run` only when deliberately regenerating artifacts.

## 2. Input schema consumed by S0

S0 reads six JSONL files: `actionforex.jsonl`, `ibtimes_uk.jsonl`, `invezz_de.jsonl`, `invezz_en.jsonl`, `invezz_nl.jsonl`, `zacks.jsonl`.

Required per line: `$id`, `permalink`, `headline`, `date`, `text_content`. `permalink` must be HTTP(S); `text_content` must normalize to at least 40 characters.

Optional fields used by S0: `publication.name` or `publisher`, `source` (author), `excerpt`, `language`, `categories`, `company_tickers`, `received_at`. `article_id` is deterministic: `art_` + first 16 hex chars of `sha256(feed_file + "\0" + $id)`.

## 3. Output schemas produced by S0–S2

All outputs are UTF-8 JSON arrays of objects, not JSONL. `schema_version` is `1.1.0`. Pydantic models in `agent1/models.py` are the live contract.

| File | Model | Top-level type |
| --- | --- | --- |
| `outputs/articles.json` | `ArticleRecord` | array |
| `outputs/stories.json` | `StoryRecord` | array |
| `outputs/facts.json` | `FactRecord` | array |
| `outputs/s0_validation_report.json` | `S0Report` | object |
| `outputs/s1_validation_report.json` | `S1Report` | object |
| `outputs/s2_validation_report.json` | `S2Report` | object |
| `outputs/evaluation_report.json` | `EvaluationReport` | object |

`ArticleRecord`: `schema_version`, `article_id`, `$id`, `story_id`, `original_language`, `available_languages`, `primary_topic`, `secondary_topics`, `primary_country`, `related_countries`, `affected_countries`, `published_at_utc`, `permalink`, `publisher`, `importance`, `author`, `title`, `excerpt`, `provider`, `feed_file`, `text_char_count`, `text_sha256`, `received_at_utc`, `categories`, `company_tickers`, `quality_flags`, `window_status`.

`StoryRecord`: `schema_version`, `story_id`, `article_id`, `canonical_title`, `topic_key`, `primary_topic`, `secondary_topics`, `primary_country`, `related_countries`, `affected_countries`, `published_at_utc`, `last_published_at_utc`, `permalink`, `publisher`, `importance`, `article_ids`, `permalinks`, `publishers`, `authors`, `languages`, `translation_groups`, `independent_source_count`, `importance_breakdown`, `reporting_differences`, `cluster_evidence`, `selection_method`, `original_language`, `available_languages`.

`FactRecord`: `schema_version`, `fact_id`, `article_id`, `story_id`, `$id`, `source_article_id`, `claim_text`, `source_span`, `source_start_char`, `source_end_char`, `figures[]` (`raw`, `value`, `unit`, `currency`, `context`), `numerical_values`, `conflicts_with`, `verification_status`, `review_reasons`, `selection_method`, plus the shared metadata fields above.

Report and evaluation fields are defined by `S0Report`, `S1Report`, `S2Report`, and `EvaluationReport` in `agent1/models.py:69`, `:104`, `:149`, and `:164`.

## 4. JSON handoff contract for MAIN_flow_v1

Use the publishable projection defined by:

- Schema: `samples/n8n_handoff.schema.json`
- Verified example: `samples/n8n_handoff_sample.json`

Top level: `handoff_version`, `generated_from`, `selection`, `stories[]`.

Each story carries `story_id`, `topic_key`, `importance`, `published_at_utc`, `last_published_at_utc`, `article_ids`, `languages`, `publishers`, `independent_source_count`, `selection_method`, `translation_groups`, and `facts[]`.

Each fact carries `fact_id`, `verification_status`, `source`, `figures`, `numerical_values`, `conflicts_with`, `selection_method`. `source` carries `article_id`, `original_id`, `permalink`, `publisher`, `published_at_utc`, `language`, `feed_file`, `start_char`, `end_char`, `source_span_sha256`.

Omitted from the publishable projection because they contain licensed article text: `claim_text`, `source_span`, and `figures[].context`. Character offsets are 0-based indices into the normalized text produced by S0 (`agent1.text.normalize_ws`), not raw JSONL bytes. `source_span_sha256` lets the licensed-side verifier confirm the offset without exporting the text.

Filter used for the sample and required for publishable handoff:

```text
facts where verification_status != "review_needed"
       and review_reasons == []
       and conflicts_with == []
join fact.story_id -> story.story_id
join fact.source_article_id -> article.article_id
```

`verification_status` values in the current output are `candidate` and `review_needed`; Agent 2/Agent 3 must not treat `candidate` as verified.

## 5. Schema incompatibilities with `shared/api_contract.md`

| Area | Shared contract v1.0.0 | Agent 1 implementation v1.1.0 | Integration action |
| --- | --- | --- | --- |
| Transport | JSONL, one object per line | JSON arrays | Use n8n projection, not raw shared schemas |
| Filenames | `articles.jsonl`, `evidence.jsonl`, `stories.jsonl` | `articles.json`, `facts.json`, `stories.json` | Map paths explicitly |
| Version | `1.0.0` | `1.1.0` | Do not validate against v1 schemas until regenerated |
| Article fields | `run_id`, `source_feed`, `language`, `publication`, `published_at`, `headline_normalized`, `excerpt_normalized`, `content_hash`, `processing_metadata` | `feed_file`, `original_language`, `publisher`, `published_at_utc`, `title`, `excerpt`, `text_sha256`, no run metadata | Use mapping in section 6 |
| Story fields | `topic`, `primary_language`, `article_refs`, `fact_ids`, `importance_score`, `published_at_start/end`, `cluster_method`, `needs_review`, `generated_content`, `processing_metadata` | `canonical_title`, `languages`, `article_ids`, `importance`, `published_at_utc`, `last_published_at_utc`, `selection_method`, no `fact_ids` or `generated_content` | Derive `fact_ids` by grouping facts; treat generated content as Agent 2 output |
| Fact fields | `claim`, `claim_type`, `source_article_ids`, `source_permalinks`, `evidence_refs`, `confidence`, `is_model_generated`, `extraction_method`, `processing_metadata` | `claim_text`, one `source_article_id`, one `permalink`, char offsets, `figures`, `conflicts_with`, `selection_method` | Use projection; do not export `claim_text`/`source_span` |
| Conflict field | `conflict_with_fact_ids` | `conflicts_with` | Map name only if shared schema is regenerated |
| Extraction method enum | `deterministic`, `embedding_cluster`, `llm_structured`, `hybrid`, `human` | `deterministic_regex`, `llm_refined` | Treat as unmapped until shared schema is updated |
| Processing metadata | Required on every record | Not emitted by S0–S2 | Agent 2 must not require it yet |

The shared schemas remain useful as the Phase 1 design reference, but they are not the live Agent 1 output contract.

## 6. Minimal integration instructions

1. Point n8n at `$Out` and read `stories.json` and `facts.json` as JSON arrays.
2. Apply the fact filter in section 4; drop any story with fewer than 3 eligible facts.
3. Project each selected story/fact pair to `samples/n8n_handoff.schema.json`; never send `claim_text`, `source_span`, or `figures[].context` outside the licensed boundary.
4. Pass the resulting `stories[]` to Agent 2. If a legacy consumer needs shared-style names, map only these: `publisher → publication`, `original_language → language`, `published_at_utc → published_at`, `importance → importance_score`, `published_at_utc → published_at_start`, `last_published_at_utc → published_at_end`, `rule_1_translation|rule_2_semantic|rule_3_cross_publisher → deterministic_rule`, and derive `fact_ids` from grouped facts.
5. Validate with `samples/n8n_handoff.schema.json` in the n8n Code node or before emitting the handoff payload.

## 7. Verification evidence

- Sample: `samples/n8n_handoff_sample.json` contains 3 stories and 9 synthetic facts; every fact is `candidate` with no `review_reasons` and no `conflicts_with`.
- Every sample source uses synthetic IDs, `example.com` permalinks, and synthetic feed names; no licensed article text is included.
- The sample validates against `samples/n8n_handoff.schema.json`; real offsets and source hashes must still be verified when generating a production handoff.
- Full outputs remain unchanged: 1,740 articles, 1,227 stories, 6,135 facts.
- Test suite: `5 passed`.

## 8. Unresolved clustering limitations

- Event-target evaluation is 1/3 passed: US Producer Prices passed; Intel shareholder lawsuit split into 2 clusters; Jensen Huang/Nvidia event split into 25 clusters.
- Rule 3 cross-publisher merging produced 0 real-dataset merges.
- Cluster sizes include 258 and 73 articles, indicating over-merging risk for broad market-wrap events.
- OpenAI embeddings and LLM refinement were not exercised; no API key was available and the run used local deterministic embeddings with `dry_run=true`.
- 2,674 of 6,135 facts are `review_needed`; 3,461 are `candidate`; none are `verified`.
