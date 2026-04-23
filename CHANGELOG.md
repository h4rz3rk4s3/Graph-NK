# CHANGELOG.md

*Living record of what has been built, what is pending, and what decisions were
made during implementation. Updated at the end of every implementation session.*

*Format: newest entry at the top. Each entry references the BUILD_SPEC.md milestone
it closes or advances.*

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
