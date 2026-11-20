# Agent 1 S0–S2 implementation

Scope: S0 Ingest & Normalise, S1 Cluster & Dedupe, S2 Fact Extraction only. S3–S7 remain untouched.

## Contracts

Pydantic models in `agent1/models.py` are the source of truth; each output record carries `schema_version: 1.1.0`.

| Stage | Input | Output | Main model |
| --- | --- | --- | --- |
| S0 | Six JSONL feeds | `outputs/articles.json`, `outputs/s0_validation_report.json` | `ArticleRecord`, `S0Report` |
| S1 | `articles.json` | `outputs/stories.json`, `outputs/s1_validation_report.json` | `StoryRecord`, `S1Report` |
| S2 | `stories.json` + raw `text_content` | `outputs/facts.json`, `outputs/s2_validation_report.json` | `FactRecord`, `S2Report` |
| Evaluation | `articles.json`, `stories.json` | `outputs/evaluation_report.json` | `EvaluationReport` |

Every S0–S2 record preserves: `article_id`, `story_id`, `original_language`, `available_languages`, `primary_topic`, `secondary_topics`, `primary_country`, `related_countries`, `affected_countries`, `published_at_utc`, `permalink`, `publisher`, `importance`. The original `$id` is preserved on articles and facts. Geographic fields are populated only from explicit text mentions; `null` is used otherwise.

Synthetic contract examples are in `samples/articles_sample.json`, `samples/stories_sample.json`, and `samples/facts_sample.json`. They contain no licensed article text.

## Commands

Run from the project root with `PYTHONPATH` set to the project root:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m agent1.cli inspect
python -m agent1.cli run --mode full
python -m agent1.cli run --mode daily --hours 24
python -m agent1.cli s0 --mode full
python -m agent1.cli s1
python -m agent1.cli s2
python -m agent1.cli evaluate
python -m pytest -q tests
```

## Dependencies and keys

Required: Python 3.11+, `pydantic>=2.7`, `pytest>=8.0` for tests. Optional: `openai>=1.40` when `OPENAI_EMBEDDING_PROVIDER=openai` or `LIQUID_BRIEFING_LLM_PROVIDER=openai`. Default execution uses deterministic local hash embeddings and no LLM, so no paid API key is needed. See `.env.example` for all thresholds and model settings.

## Error handling

S0 skips records with missing `$id`, `permalink`, `headline`, `date`, or `text_content`, invalid URLs, invalid timestamps, or too-short text, and records per-feed errors in the validation report. S1 never deletes source articles; it only groups IDs. S2 rejects any candidate whose `source_span` is not an exact substring of the referenced `text_content` and marks uncertain claims as `review_needed`. No POSITIVE/NEGATIVE labels are emitted by this stage code.

## Validation results (full dataset, local embeddings, no paid calls)

- S0 full: 1,740 input, 1,740 valid, 0 skipped; feed counts 36/298/120/166/120/1,000.
- S0 daily smoke test (24h window ending at latest article): 168 included, 1,572 excluded but retained in the archive; 981/1,000 older Zacks articles excluded.
- S1: 1,740 articles → 1,227 stories; 355 translation pairs, 1,468 semantic pairs, 0 rule-3 cross-publisher merges under the conservative configured thresholds.
- S2: 1,227 stories → 6,135 facts; 6,135 verbatim-span checks passed, 0 failed; 5 conflicts detected; 2,674 claims marked non-candidate for review; 0 LLM calls.
- Event targets: 1/3 passed. US Producer Prices → 1 cluster (4 matched articles, cluster size 73). Intel shareholder lawsuit → 2 clusters (IBTimes article separate from the larger Invezz/market-wrap cluster). Jensen Huang/Nvidia event → 25 clusters. These failures are reported honestly; the conservative anti-hub rules intentionally prevent cross-event merging, and no OpenAI API key was available for multilingual embedding refinement.
- Tests: 4 passed.

## Cost

The measured run cost `$0.00`: local embeddings, deterministic regex/context extraction, `llm_provider=none`, `dry_run=true`. With `text-embedding-3-small`, roughly 100 tokens per title+intro for 1,740 articles is about 174k tokens, approximately `$0.0035` per full run at `$0.02/1M`; 10× volume ≈ `$0.035`. Optional `gpt-6-luna` refinement would add tokens only when explicitly enabled with an API key and a budget cap.
