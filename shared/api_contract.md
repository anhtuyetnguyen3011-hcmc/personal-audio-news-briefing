# Shared API contract — Liquid Briefing v1

Status: **Phase 1 (proposed, frozen for review)**  
Contract version: `1.0.0`  
Schemas: [`shared/schemas/v1/`](schemas/v1/)  
Transport for v1: newline-delimited JSON files (JSONL). An HTTP layer may wrap these records later without changing the record shapes.

This document is model-agnostic. Provider names and model IDs appear only in configuration and in `processing_metadata`, never in contract field names.

---

## 1. Responsibilities

| Agent | Owns | Emits |
|---|---|---|
| Agent 1 — News Intelligence | ingestion, normalization, multilingual event clustering, candidate fact extraction, source mapping, story ranking | `Article`, `Evidence`, `Story` |
| Agent 2 — Personalization & Podcast | listener profiling, story selection, generated script, TTS | `ListenerProfile`, `Script` |
| Agent 3 — Quality Critic | factual verification, source traceability, personalization evaluation, audio QA | `CriticResult` |

Agents must not mutate another agent's records. Agent 3 writes a new `CriticResult`; it never edits `Evidence` in place.

---

## 2. Files and record streams

| File | Schema | Producer | Consumer |
|---|---|---|---|
| `articles.jsonl` | `article.schema.json` | Agent 1 | Agent 1 |
| `evidence.jsonl` | `evidence.schema.json` | Agent 1 | Agent 2, Agent 3 |
| `stories.jsonl` | `story.schema.json` | Agent 1 | Agent 2, Agent 3 |
| `listener_profiles.jsonl` | `listener_profile.schema.json` | Agent 2 | Agent 2, Agent 3 |
| `scripts.jsonl` | `script.schema.json` | Agent 2 | Agent 3 |
| `critic_results.jsonl` | `critic_result.schema.json` | Agent 3 | humans, Agent 2 (revision loop) |

Each line is one object. A record with a missing or unsupported `schema_version` must be rejected, not silently coerced.

### 2.1 Versioning rules

- `schema_version` is required on every record and follows `MAJOR.MINOR.PATCH`.
- `MAJOR`: breaking field removal/rename or changed semantics. Consumers must reject.
- `MINOR`: additive optional field. Consumers must ignore unknown fields defensively even though the schemas set `additionalProperties: false`.
- `PATCH`: documentation or constraint clarification.
- Schema `$id` values use `urn:liquid-briefing:schemas:v1:<name>`. A new major version gets a new directory `v2/` and new `$id`.
- IDs must remain stable across re-runs: derive `story_id` from sorted source `article_id`s + `topic_key`; derive `fact_id` from `story_id` + normalized claim + sorted source IDs. `run_id` changes per run; record IDs should not.

---

## 3. Invariants

1. Every `Story` has `story_id`, `topic`, `topic_key`, `article_ids`, `article_refs`, `fact_ids`, `importance_score`, and `schema_version`.
2. Every `Evidence` has `fact_id`, `source_article_ids`, `source_permalinks`, `verification_status`, and at least one `evidence_ref`.
3. `Evidence` contains source facts only. Generated prose lives exclusively in `Story.generated_content` and `Script.segments[].spoken_text`.
4. LLM-produced evidence has `is_model_generated: true`, `extraction_method: "llm_structured"` or `"hybrid"`, and `verification_status: "candidate"` until Agent 3 or a human verifies it.
5. `Story.generated_content.grounded_in_fact_ids` must reference IDs present in `Story.fact_ids`.
6. Every `Script` claim ref must reference `fact_ids` that exist in `evidence.jsonl`, and its `source_permalinks` must match the referenced facts.
7. All `article_refs` are immutable: never rewrite a permalink, publication, timestamp, language, or content hash.
8. No record contains an API key, credential, full article body, `html_content`, or cached embedding vector.
9. Every record carries `processing_metadata` with models, timestamp, token usage, estimated cost, extraction method, and verification status.

---

## 4. How Agent 2 selects stories without re-clustering

Agent 2 reads `stories.jsonl` once and filters in memory. No embedding, no similarity computation, and no source re-fetch is needed.

```text
candidate = stories
  | where topic_key in profile.topics_of_interest
  | where topic_key not in profile.excluded_topics
  | where profile.preferred_language in languages
  | where importance_score >= profile.importance_threshold
  | where published_at_end >= briefing_cutoff
  | sort by importance_score desc, published_at_end desc
  | take profile.max_stories
```

`languages` is the full set of languages represented in the cluster, so a Dutch listener can receive a Dutch-language rendering of an English-origin event without redoing cross-language matching. `primary_language` is only a tie-breaker for generated content.

---

## 5. How Agent 3 traces a spoken claim

```text
Script.segments[].claim_refs[].script_claim_id
  -> claim_refs[].fact_ids[]
  -> Evidence.fact_id
  -> Evidence.evidence_refs[].{article_id, permalink, locator, short_quote?}
  -> immutable SourceReference in Story.article_refs
```

A check of type `claim_evidence` fails when any of these links is missing. A check of type `number_match` compares every `numerical_values[].raw_value`, unit and currency spoken in the script against the linked `Evidence`. A `credential_leak` check fails on any string matching common API-key prefixes.

---

## 6. Processing metadata

Defined in `common.schema.json#/$defs/ProcessingMetadata`:

| Field | Meaning |
|---|---|
| `run_id` | Correlates all records from one pipeline run. |
| `created_at` | UTC timestamp of record creation. |
| `producer`, `producer_version` | Code that emitted the record. |
| `pipeline_stage` | Where in the flow the record was produced. |
| `embedding_model` | Configured embedding model ID, or `none`. |
| `llm_model` | Configured text model ID, or `none`. |
| `extraction_method` | `deterministic`, `embedding_cluster`, `llm_structured`, `hybrid`, or `human`. |
| `token_usage` | Input/output/cached/reasoning tokens, request count, retry count. |
| `estimated_cost_usd`, `cost_basis` | Estimated cost and the pricing mode used. Reconcile with the provider bill. |
| `verification_status` | Candidate → verified/rejected lifecycle. |
| `dry_run`, `budget_limit_usd` | Cost-gating context. |
| `source_hash`, `warning_codes` | Debugging aids; hashes and upper-case codes only, never raw text. |

---

## 7. Configuration

Environment variables only. No key may be committed, logged, or embedded in a record.

```env
OPENAI_API_KEY=
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_LLM_MODEL=gpt-6-luna
OPENAI_MAX_BUDGET_USD=5
OPENAI_DRY_RUN=true
```

Optional: `OPENAI_MAX_RETRIES`, `OPENAI_BATCH_SIZE`, `OPENAI_EMBEDDING_DIMENSIONS`, `RUN_ID_PREFIX`, `ARTIFACTS_DIR`, `CACHE_DIR`.

`OPENAI_DRY_RUN=true` means no paid call is made. Deterministic ingestion, hashing, clustering-on-synthetic-vectors, schema validation, and cost estimation may run; API clients must be replaced with recording stubs. `OPENAI_DRY_RUN` must be explicitly set to `false` for a live run.

---

## 8. Error model

Errors are reported as JSON objects, never as raw provider responses containing request bodies.

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message_code": "RATE_LIMIT_EXCEEDED",
    "retryable": true,
    "attempt": 2,
    "run_id": "run_20261120T090000Z_ab12cd34"
  }
}
```

- Retry: `408`, `409`, `429`, `5xx`; exponential backoff with jitter; honour `Retry-After`.
- Do not retry: `400`, `401`, `403`, schema validation failures.
- Budget exhausted: abort the run, write partial artifacts with `warning_codes: ["BUDGET_EXCEEDED"]`.
- Refusal or incomplete structured output: keep the fact as `candidate` with `uncertainty_codes: ["LOW_MODEL_CONFIDENCE"]` and flag for review; never synthesize a replacement value.

---

## 9. Cost accounting

Estimates are recorded per record and aggregated per `run_id`. A pre-flight estimate above `OPENAI_MAX_BUDGET_USD` aborts before any paid call.

Reference rates checked against official OpenAI documentation on 2026-11-20:

- `text-embedding-3-small`: **$0.02 / 1M input tokens**.
- `gpt-6-luna`: **$0.10 / 1M input**, **$0.50 / 1M output** (standard, short context). Batch and Flex are 50% of standard.

Planning assumptions and estimates (headline + excerpt embeddings only; LLM on ambiguous clusters only; no TTS):

| Volume | Embedding tokens | LLM input / output tokens | Est. cost |
|---|---:|---:|---:|
| 1x = 1,740 articles | ~0.52M | ~72k / ~24k | ~$0.03 |
| 10x = 17,400 articles | ~5.2M | ~720k / ~240k | ~$0.30 |

These are estimates, not quotes. Retries, TTS, data residency uplift, and price changes are excluded.

---

## 10. Privacy and licence

- The dataset licence forbids republishing article text. Contracts carry IDs, permalinks, hashes, short permitted quotes, and paraphrased claims only.
- Cached embeddings are derived from licensed text: store them in the local `cache/` directory, exclude them from version control, and never export vectors.
- Logs must contain IDs, counts, token totals, and status codes only. Never log `OPENAI_API_KEY` or article bodies.
