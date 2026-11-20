# Liquid Briefing — Phase 1 architecture

Date: 2026-11-20  
Scope: architecture and shared contracts only. No pipeline code is implemented in this phase.

## 1. Goal

Turn 1,740 licensed news articles (en/de/nl) into a small number of ranked, source-traceable events, then let two different listeners receive clearly different, verifiable audio briefings. Agent 1 does the expensive understanding work once; Agent 2 and Agent 3 consume its exported contracts.

## 2. Agent boundaries

```text
[licensed JSONL feeds]          local, git-ignored
        |
        v
  Agent 1  News Intelligence
  ingest -> normalize -> embed -> cluster -> rank -> extract facts -> export
        |                    \_________ OpenAI _________/
        |  articles.jsonl | evidence.jsonl | stories.jsonl
        v
  Agent 2  Personalization & Podcast
  profile -> filter stories -> script with claim refs -> TTS
        |  listener_profiles.jsonl | scripts.jsonl
        v
  Agent 3  Quality Critic
  verify claims/numbers -> check traceability -> score fit -> critic_results.jsonl
        |
        v  revision loop back to Agent 2 (never mutates Agent 1 facts)
```

Ownership is exactly as agreed: Agent 1 owns ingestion, multilingual topic/event clustering, fact extraction, source mapping and story ranking; Agent 2 owns listener profiling, story selection, script generation and TTS; Agent 3 owns factual verification, source traceability, personalization evaluation and audio quality checks.

## 3. Model selection (checked against official docs)

- Default embedding model: **`text-embedding-3-small`** (configurable via `OPENAI_EMBEDDING_MODEL`). Official rate: $0.02 / 1M input tokens.
- Default text model: **`gpt-6-luna`** (configurable via `OPENAI_LLM_MODEL`). OpenAI's docs describe it as the most efficient model for focused, high-volume workloads and list the Responses API, Structured Outputs, and $0.10 / 1M input + $0.50 / 1M output (standard, short context).
- Sources: <https://platform.openai.com/docs/models/gpt-6-luna>, <https://platform.openai.com/docs/pricing>, <https://platform.openai.com/docs/guides/structured-outputs>.

No model ID is baked into a schema field name. Swapping a model changes configuration and `processing_metadata`, not contracts.

## 4. OpenAI integration design

### 4.1 Embeddings

- Input is **normalized headline + normalized excerpt only**, never the full article.
- Cache key: `sha256(embedding_model_id + "\0" + content_hash)`, where `content_hash = sha256(normalized_headline + "\n" + normalized_excerpt)`.
- Similarity: cosine. Clustering: Python-only (connected components over a thresholded similarity graph, then deterministic refinement using publisher diversity, recency, and translation pairing).
- Multilingual evaluation: exploit the known en/de/nl counterpart pairs (same author, within 15 minutes) as a labelled set; report top-k cross-language retrieval recall and event-level purity on this dataset. BGE-M3 is not used.
- Only ambiguous clusters and selected fact-extraction windows go to the text model.

### 4.2 Fact extraction

- Official OpenAI Python SDK, Responses API, Structured Outputs via Pydantic models / strict JSON Schema.
- Required candidate fields: claim, dates, entities, numerical values, source references, uncertainty codes.
- Exact numeric strings, units, currencies and context are preserved; missing data stays `null`/absent. No invented values.
- Output is candidate evidence (`verification_status: "candidate"`), never standalone truth. Uncertain or conflicting claims get `review_needed` or `conflicting` and are routed to Agent 3.

### 4.3 Cost controls

- Deterministic rules and embeddings first; LLM only on ambiguous clusters and fact extraction.
- Batching, bounded concurrency, exponential backoff with jitter, `Retry-After` handling.
- Per-call and per-run accounting of input/output tokens, model names and estimated cost.
- 1x and 10x estimates are in `shared/api_contract.md` §9. Configurable `OPENAI_MAX_BUDGET_USD`; dry-run default.
- No paid full-dataset run until the small sample smoke test passes.

## 5. Contracts delivered in Phase 1

| Schema | Purpose |
|---|---|
| `common.schema.json` | IDs, model-agnostic metadata, source and evidence references, enums |
| `article.schema.json` | Normalized article view (no full text) |
| `evidence.schema.json` | Candidate facts with numbers, dates, entities, mandatory evidence refs |
| `story.schema.json` | Ranked event with immutable source refs and separated generated content |
| `listener_profile.schema.json` | Agent 2 selection criteria |
| `script.schema.json` | Spoken text with per-claim links back to facts |
| `critic_result.schema.json` | Verification, traceability, fit and audio checks |

`shared/api_contract.md` documents handoffs, versioning, filtering, traceability, errors, cost and privacy rules.

## 6. Planned implementation phases

1. **Phase 1 — contracts (this document).** Shared schemas + API contract. Review gate.
2. **Phase 2 — local, no paid calls.** Deterministic ingestion, normalization, hashing, embedding cache interface with mocked client, cosine clustering, ranking, JSONL exports, evaluation harness on the real dataset, cost estimator, tests with mocked API.
3. **Phase 3 — small live sample.** Explicit opt-in live smoke test: ~10 articles, 2 languages, verify structured output, traceability and token accounting against `OPENAI_MAX_BUDGET_USD`.
4. **Phase 4 — Agent 2 and Agent 3.** Profile-driven selection, grounded script generation, critic checks, revision loop.
5. **Phase 5 — production-sized run.** Only after Phases 2–4 pass. Dry-run remains the default.

## 7. Test plan

- Mocked OpenAI client for embeddings and Responses API: no paid calls in unit tests.
- Explicit opt-in live smoke test, gated by an environment flag plus a sample-size cap.
- Multilingual embedding evaluation on real en/de/nl counterpart pairs.
- Structured-output validation against `evidence.schema.json`.
- Source traceability checks from script claim → fact → permalink.
- Retry/backoff/rate-limit and budget-exceeded tests.
- Cost report for 1x and 10x volume from recorded token counts.

## 8. Security and licence

- Credentials come only from environment variables; `.env` and caches are git-ignored.
- Logs carry IDs and counts, not credentials or article text.
- Licensed data stays in the existing `liquid-briefing-data` folder; no copies are made into this project.
- Do not publish licensed data, cached article-derived embeddings, or credentials to GitHub.
- Delete local copies after the hackathon as required by the dataset licence.
