# CHANGELOG.md

*Living record of what has been built, what is pending, and what decisions were
made during implementation. Updated at the end of every implementation session.*

*Format: newest entry at the top. Each entry references the BUILD_SPEC.md milestone
it closes or advances.*

---

## 2026-06-02 — Bugfix: Redis OOM ("used memory > 'maxmemory'") on large backlogs

### Symptom
Processing a large backlog failed at the extractor with:
`command not allowed when used memory > 'maxmemory'`.

### Root cause
Redis is in-memory, and `broker.read_all` used `XREAD` but **never deleted
consumed entries** — Redis Streams retain every message until trimmed. So
`stream_units` (one entry per TextUnit, carrying full text) and `stream_signals`
(one per signal) grew without bound and were never reclaimed. On a large repo
they filled Redis; with the default `noeviction` policy, the next `XADD`
(the extractor publishing to `stream_units`) was rejected. Not related to the
earlier Mongo fix or to aborting the miner.

A structural obstacle blocked the obvious fix (trim on consume): `stream_units`
had **two** consumers — the projector in stage 1 and the annotator in stage 2 —
so trimming it during stage 1 would starve the annotator.

### Fix
- `broker.py`: `read_all(..., trim=False)` gained a `trim` flag. When set, each
  batch's message ids are `XDEL`'d once the consumer has processed them,
  reclaiming memory as the stream drains. Verified: every message is delivered
  exactly once and the stream is fully reclaimed.
- `annotators/worker.py`: the annotator now reads TextUnits from **Neo4j**
  (keyset pagination on `u.id`) instead of `stream_units`. Annotators only use
  `text` and `text_unit_id`, both stored on the TextUnit node, so this is
  lossless. This makes `stream_units` a single-consumer stream.
- `projector/worker.py`: Phase 1 (`stream_units`) and Phase 2 (`stream_signals`)
  now consume with `trim=True`. `stream_raw` is left untrimmed (it is small —
  pointer events only — and has two consumers in stage 1).
- `docker-compose.yml`: Redis now starts with an explicit, tunable
  `--maxmemory ${REDIS_MAXMEMORY:-2gb}` and `--maxmemory-policy noeviction`
  (fail loudly rather than silently drop queued work).

### Effect on the framework
- Redis memory is now reclaimed during the run; `stream_units` and
  `stream_signals` no longer accumulate across the whole pipeline or across runs.
- Stage 2 no longer depends on Redis for TextUnits — it reads them from the
  graph, which is disk-backed and already populated by stage 1.
- **Remaining peak:** during stage 1, `stream_units` still fills while the
  extractor produces faster than Phase 1 drains (Phase 1 runs after Phase 0).
  Trimming reclaims it as Phase 1 drains, and it is empty before stage 2. For
  very large repos, raise `REDIS_MAXMEMORY`, or mine+process in chunks. A future
  optimisation (concurrent Phase 0/1 draining with a completion sentinel and
  MERGE-parent) would cap this peak; deferred as it adds coordination complexity.

### Immediate unblock for your current run
Redis is full from the prior failed attempts. The derived streams are safe to
delete — they are regenerated from MongoDB; only keep `stream_raw`:

```bash
redis-cli INFO memory | grep used_memory_human         # inspect
redis-cli DEL graphrag.units graphrag.signals          # safe: regenerated
# do NOT delete graphrag.raw — it is your work list
docker compose up -d                                    # picks up new Redis limits
python scripts/run_pipeline.py --enrich                 # re-run; writes are idempotent
```

If it OOMs again on stage 1, raise the ceiling (e.g. `REDIS_MAXMEMORY=6gb` in
`.env` / environment) and restart the Redis container, or process the repo in
chunks.

---



### Symptom
Running `run_pipeline.py` against a large backlog (~20k+ events from a partially
mined repo) failed immediately and repeatedly with:
`extractor.worker — Event processing failed: localhost:27017: connection pool
paused (configured timeouts: connectTimeoutMS: 20000.0ms)`.

### Root cause
Not related to aborting the miner. The miner writes each doc to MongoDB before
publishing its stream event, so a partial mine is just a smaller, fully-valid
backlog. The real cause was **unbounded concurrency**:

- `broker.read_all` yields batches of 100 events.
- Both `extractor.worker` and `projector.worker` Phase 0 did
  `asyncio.gather(*[_process_event(e) ...])` over the whole batch — 100
  concurrent `find_one` calls each.
- In Stage 1 both run concurrently and both consume `stream_raw`, so up to ~200
  simultaneous Mongo operations.
- The client was created with no pool config (`AsyncIOMotorClient(uri)`).

On a small test repo the backlog was tiny so concurrency never spiked. On a
20k-event backlog every batch saturates the pool; one hiccup pauses it; and the
saturated event loop then starves the driver's server-monitor coroutine, so the
pool never un-pauses. Every subsequent fetch fails identically. A *completed*
20k+ mine would fail the same way — it is backlog-size × concurrency, not abort.

### Fix
- New `storage.py`:
  - `make_mongo_client()` — client with `maxPoolSize`, `retryReads=True`, and
    generous server-selection / socket timeouts.
  - `gather_bounded(coros, limit)` — `asyncio.gather(return_exceptions=True)`
    that never runs more than `limit` coroutines at once (semaphore).
- `settings.py`: added `mongo_max_pool_size` (50),
  `mongo_server_selection_timeout_ms` (30000), `mongo_socket_timeout_ms`
  (120000), and `mongo_fetch_concurrency` (16).
- `extractor/worker.py` and `projector/worker.py`: now build the client via
  `make_mongo_client()` and process each batch with
  `gather_bounded(..., settings.mongo_fetch_concurrency)` instead of an
  unbounded gather.

### Effect on the framework
- Pipeline now processes arbitrarily large backlogs without exhausting the pool.
- Throughput is intentionally capped at 16 concurrent Mongo fetches per worker
  (tune `mongo_fetch_concurrency` if your MongoDB can take more). This is a
  deliberate stability-over-speed trade for research runs.
- **Resuming your aborted run:** nothing was corrupted. Just re-run
  `python scripts/run_pipeline.py --enrich`. All writes are idempotent
  (`MERGE` on stable keys), so re-processing the same events is safe.
- If you want a clean slate instead, stop the stack, `docker compose down -v`
  to wipe volumes, then re-mine — but that is not required.

---



### Symptom
`Neo.ClientError.Statement.TypeError: Property values can only be of primitive
types or arrays thereof. Encountered: Map{...}` raised during
`upsert_signals_batch` (Phase 2), once per batch, the whole 100-signal batch
aborting.

### Root cause
`projector/graph_projector.py` line ~267 wrote `sig.payload = s.payload`, where
`s.payload` is a nested dict. Neo4j property graphs cannot store nested maps as
property values. Because **every** Signal (lexical, morpho, affix, rhetorical,
and the classifier's non-verdict Signal) carries a `payload` dict, every batch
failed. The error message surfaced whichever map Neo4j happened to be evaluating
when the type check fired — in the reported case the classifier payload — but it
was never specific to `upsert_classifier_verdict` (which writes only primitives
and was always correct).

### Fix
- `projector/graph_projector.py`:
  - Added `import json`.
  - In `upsert_signals_batch`, the payload is now JSON-serialised (with internal
    `__`-prefixed sentinel keys stripped) and stored as the string property
    `sig.payload_json`, replacing `sig.payload`.
- `ontology/schema.yml`: `Signal.payload {type: map}` → `Signal.payload_json {type: string}`.
- `ontology/ontology.cypher`: §3.8 template updated to `sig.payload_json` with a
  note explaining the constraint.
- `notebooks/01_descriptive.ipynb`: added a markdown note on parsing payloads with
  `apoc.convert.fromJsonMap(sig.payload_json)`.

### Effect on the framework
- **No data is lost.** All provenance previously in `payload` is preserved
  verbatim inside `payload_json`.
- **Querying payload fields now requires parsing.** Use
  `apoc.convert.fromJsonMap(sig.payload_json).<key>` in Cypher, or
  `json.loads(row['payload_json'])` in pandas. The notebooks do not query payload
  fields, so they are unaffected.
- **The promoted provenance is unchanged.** The fields that matter most for
  analysis — `lemma`/`source_citation` (LexicalMarker), `figure_id`/`family`
  (RhetoricalFigure), `label`/`confidence`/`model_id` (ClassifierVerdict) — were
  always stored as first-class primitive properties on dedicated nodes, not in
  `payload`. So RQ1–RQ5 queries in the notebooks need no changes.
- **Re-ingestion:** if you already have a partial graph from a failed run, the
  Signal MERGEs are idempotent on `signal_id`, so simply re-running
  `python scripts/run_pipeline.py --stage 2` will complete the signal layer.

---

## 2026-04-23 — v0 implementation complete (all 10 milestones)

### ✅ Implemented

#### Foundation (Milestone 0)
- `pyproject.toml` — all dependencies per BUILD_SPEC §2
- `docker-compose.yml` — Neo4j 5, MongoDB 7, Redis 7 with health checks
- `.env.example` — all environment variables documented
- `settings.py` — Pydantic-settings configuration; extends env file
- `broker.py` — Redis Streams wrapper (`RedisBroker`): `publish`, `read_all`
- `scripts/setup_neo4j.sh` — applies `ontology/ontology.cypher` via `cypher-shell`
- `ontology/schema.yml` — human-readable ontology with cross-references to FRAMEWORK_DESIGN.md
- `rules/categories.yml` — master registry of all signal categories → layer mapping

#### Ontology artefacts (from prior session)
- `ontology/ontology.cypher` — DDL: constraints, indexes, MERGE templates
- `lexicons/en_core_v0.1.yml` — seed NK lexicon (~20 entries with provenance)
- `patterns/morpho_syntactic_v0.1.yml` — 18 spaCy Matcher patterns
- `patterns/rhetorical_v0.1.yml` — 11 rhetorical figure patterns
- `patterns/word_formation_v0.1.yml` — 4 prefix + 2 suffix rules with blocklists

#### Milestone 1 — Miner integration tweaks
- `miner/async_miner.py` — two surgical edits applied to the frozen original:
  1. `content_sha256` added to every `_meta` block in MongoDB
  2. `item_subtype` field added to every event published on `stream_raw`

#### Milestone 2 — TextUnitExtractor
- `extractor/text_unit_extractor.py` — pure functions: `strip_text`, `extract_from_issue`,
  `extract_from_pull_request`, `extract_from_commit`
- `extractor/worker.py` — async consumer of `stream_raw`, dispatches to extractors,
  publishes TextUnit events to `stream_units`

#### Milestone 3 — GraphProjector (SE-artefact layer)
- `projector/graph_projector.py` — all Cypher write functions keyed to `ontology.cypher`
  §3 templates: `upsert_repository`, `upsert_actor`, `upsert_issue`,
  `upsert_pull_request`, `upsert_commit`, `upsert_text_unit`
- `projector/worker.py` — async consumer of `stream_units` + `stream_signals`;
  batches up to 100 signals or 2 s before flushing

#### Milestone 4 — LexiconAnnotator
- `annotators/base.py` — `TextUnit`, `Signal`, `Annotator` protocol
- `annotators/lexical.py` — YAML-driven `PhraseMatcher`; emits one Signal per match
  with full provenance in `payload` (lexicon_version, lemma, source_citation)
- `annotators/worker.py` — fan-out consumer; lazy loads all annotators; batches
  ClassifierAnnotator separately

#### Milestone 5 — SpacyMorphoAnnotator
- `annotators/morpho_syntactic.py` — YAML-driven spaCy `Matcher`; 18 patterns
  covering negation, modality, hedging, tense, and syntactic patterns;
  separate `_detect_question_answer` for unit-level Q&A structure

#### Milestone 6 — ClassifierAnnotator
- `annotators/classifier.py` — `NKClassifier` protocol; `HFTransformersClassifier`
  with MPS → CPU fallback; `ClassifierAnnotator` with `batch_annotate()`; emits
  Signal + ClassifierVerdict sentinel per TextUnit

#### Milestone 7 — AffixAnnotator
- `annotators/word_formation.py` — prefix (un-, in-, non-, dis-) and suffix (-less,
  -able) detection with POS gating and YAML blocklists; intentionally noisy

#### Milestone 8 — RhetoricalAnnotator
- `annotators/rhetorical.py` — spaCy `Matcher` over 11 figure patterns; payload
  carries `figure_id` + `family` for the projector's `INSTANTIATES` MERGE

#### Milestone 9 — Reference enrichment
- `enrichment/reference_extractor.py` — post-annotation pass; `extract_references()`
  (pure, tested); `run_reference_enrichment()` writes `REFERENCES` edges with
  canonical mechanism labels (closes, fixes, resolves, refs, see, bare)

#### Milestone 10 — Descriptive notebook
- `notebooks/01_descriptive.ipynb` — 6 sections: node counts, signal heatmap,
  top lexical markers, RQ5 scatter plot, RQ5 false-negative table,
  layer co-occurrence matrix

#### Scripts
- `scripts/mine_one.py` — thin CLI over `AsyncGitHubMiner`; `--repo`, `--repo-file`,
  `--no-commits`
- `scripts/run_pipeline.py` — starts extractor + annotator + projector workers
  concurrently via `asyncio.gather`; `--enrich` triggers reference enrichment

#### Tests
- `tests/conftest.py` — `make_unit()` fixture factory
- `tests/test_annotators.py` — golden examples for all five annotators +
  TextUnitExtractor stripping + reference extractor; **no external services required**

---

### ❌ Not yet implemented (v1+)

These are explicitly deferred per BUILD_SPEC.md §8. Do not implement unless
the spec is updated.

| Item | Reason deferred |
| ---- | --------------- |
| Sentence-level TextUnit splitting | Requires granularity decision after first pilot results |
| ClassifierAnnotator — MLX backend | MPS is sufficient for pilot; interface is ready |
| Statistical metaphor identification (Shutova et al.) | Lexicon+patterns first; expand after first pass |
| Multilingual annotation | Non-EN units are persisted but not annotated |
| Source-code AST features | NK is in natural language; AST is a separate research track |
| Cross-repo comparative analysis | Requires stable ontology first |
| RQ4 taxonomy clustering notebook (`05_rq4_taxonomy.ipynb`) | After manual annotation pass |
| RQ3 rhetorical stance notebook (`04_rq3_rhetorical.ipynb`) | After first descriptive pass |
| `IgnoranceType` post-hoc assignment | Analyst-driven; not pipeline work |
| REST/GraphQL API over the KG | Out of scope; use Neo4j driver directly |
| PR → Commit `TOUCHES` edge | Requires PR→commit API call; deferred |

---

### ⚠️ Known limitations / open issues

1. ~~**`upsert_issue` / `upsert_pull_request` assume Actor exists**~~ — **FIXED**.
   `projector/worker.py` now runs three sequential phases:
   - Phase 0: reads `stream_raw`, fetches each raw doc from MongoDB, seeds
     Repository / Actor / Issue / PullRequest / Commit nodes via
     `upsert_artefact_from_raw` (new method in `graph_projector.py`).
   - Phase 1: reads `stream_units`, writes TextUnit nodes. Parent always exists.
   - Phase 2: reads `stream_signals`, writes Signal nodes. TextUnit always exists.

2. ~~**Race condition — signals arriving before their TextUnit**~~ — **FIXED**.
   `scripts/run_pipeline.py` now runs two sequential **stages**:
   - Stage 1: Extractor + Projector (Phases 0 + 1) concurrently → exhaustion.
   - Stage 2: Annotator + Projector (Phase 2) concurrently → exhaustion.
   Signals are never published until Stage 1 is fully complete.

3. **`AffixAnnotator` blocklists are not exhaustive**. Expect false positives
   in the first pilot run. Document them as `TODO(lexicon-review)` and add
   to the YAML blocklist after inspection. This is a research iteration item,
   not a code defect.

4. **`fasttext-langdetect` model** must be downloaded on first run.
   It will auto-download to `~/.fasttext` on first `_detect_lang` call.

5. **Classifier path**: if `settings.classifier_model_path` does not exist,
   the ClassifierAnnotator is skipped with a WARNING. The rest of the pipeline
   continues normally.

---

## 2026-04-22 — Design session (prior session)

- `FRAMEWORK_DESIGN.md` written — full research frame, ontology, module outlines,
  RQ→Cypher mapping, 10-day plan
- `ontology/ontology.cypher` written — DDL with MERGE templates
- `lexicons/en_core_v0.1.yml` written — seed lexicon with provenance
- `AGENTS.md` written — coding agent behavioural contract
- `BUILD_SPEC.md` written — 10 milestones with acceptance checks
