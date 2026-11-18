# AGENTS.md

*Behavioural contract for any coding agent (Claude Code, Cursor, Codex, etc.)
working on this repository. Read this file at the start of every session. This
file is the authoritative entry point; it overrides inferred conventions.*

---

## 1. What this project is

**GraphRAG-NK** — a research pipeline that mines GitHub repositories and mailing
lists, annotates the natural-language artefacts (issue/PR/commit/comment/email
text) with linguistic signals of *non-knowledge*, and stores everything in a
Neo4j knowledge graph for corpus-linguistic analysis.

**This is research code, not a product.** The quality bar is:

1. **Traceability of assumptions** — every rule, lexicon entry, and threshold
   must cite its source (paper, pilot observation, or `FRAMEWORK_DESIGN.md`
   section).
2. **Readability** — a researcher who is not the author should be able to read
   any module top-to-bottom and understand it in one sitting.
3. **Fast iteration** — changing a rule should be a YAML edit, not a refactor.

**Robustness, throughput, and operational polish are explicit non-goals.**

---

## 2. Start-of-session ritual

Before touching anything, in this order:

1. **Read the top (newest) entry of `CHANGELOG.md`.** It records the current
   state, recent decisions, and what is pending. About a third of the useful
   context about this codebase lives only here.
2. **Read the open-debt table in `BUILD_SPEC.md` "Open technical debt".** These
   are known issues agents routinely rediscover. If your task intersects one,
   you now know about it in advance.
3. **Then** look at code.

This ritual exists because the design docs were repeatedly discovered to be
stale relative to the implementation. When you find a discrepancy, follow the
flag-not-block rule in [When to proceed vs. ask](#when-to-proceed-vs-ask).

---

## 3. Canonical sources of truth (read before acting)

Treat these as authoritative. If what you are about to write disagrees with
them, **stop and flag the conflict** instead of silently diverging.

Configured,
listed in the order an agent most often needs them:

| File                              | Authority over                                           |
| --------------------------------- | -------------------------------------------------------- |
| `REFINED_RQS_v0.2.md`             | **Canonical research questions** (RQ1–RQ6, four layers of claim) |
| `FRAMEWORK_DESIGN.md`             | Research frame, architecture, ontology, rationale        |
| `BUILD_SPEC.md`                   | Implementation plan, milestone ordering, open technical debt, data-shape contracts |
| `MARKER_REVIEW.md`                | Linguistic grounding for every v0.2 marker/pattern decision (M-1…M-7, C-1…C-10) |
| `CODING_MANUAL.md`                | RQ4 decision tree, taxonomy priority, predictions P1–P6  |
| `TAXONOMY_CROSSWALK.md`           | Documented relations between the four taxonomies         |
| `SOURCES_AUDIT.md`                | Evidence basis for every codebook confidence rating      |
| `ontology/schema.yml`             | Human-readable source of truth for the ontology          |
| `ontology/ontology.cypher`        | Database schema (constraints, indexes, MERGE templates)  |
| `ontology/ignorance_codebook_v0.1.yml` | Pre-registered RQ4 taxonomy (28 categories + 3 Wehling dimensions) |
| `lexicons/*.yml`                  | Lexical markers — the ONLY place to add/edit markers     |
| `patterns/*.yml`                  | Morpho-syntactic and rhetorical patterns, word-formation rules |
| `rules/categories.yml`            | Mapping of `rule_id` → (layer, category, subcategory), **regenerated from the pattern/lexicon files themselves** |
| `CHANGELOG.md`                    | Living record of decisions and state — **append to it** (see [hard rule 3.9](#39-record-decisions-in-the-changelog)) |

**The existing `miner/async_miner.py` is frozen.** Do not refactor it. The only
allowed changes are the two small integration additions called out in
`BUILD_SPEC.md` Milestone 1. One accepted divergence is frozen with it:
`mine_repositories(include_commits=False)` by default (pilot observation —
commits are information-sparse relative to their text; see CHANGELOG 2026-08-09
and BUILD_SPEC open debt 11). `miner/gmane_ingester.py` is a normal
(non-frozen) module.

---

## 4. Spin-up & common commands

### 4.1 Environment

- `.env` at repo root with your `GITHUB_TOKEN` is **required**: `settings.py`
  instantiates a pydantic `Settings()` whose `github_token` field is mandatory,
  so importing anything that touches settings raises a `ValidationError`
  without it. There is no `.env.example` yet (BUILD_SPEC open debt 10) — model
  it on `settings.py`'s fields.
- There are two compose files and two settings files. **The *live* ones are
  `docker-compose.yml` and `settings.py`.** Their namesakes
  (`docker-compose_new.yml`, `settings_new.py`) are spec-conformant *reference
  variants*, kept so the intended config is on record; do not run from them or
  edit them unless that is explicitly the task.

### 4.2 Setup (once per machine)

```bash
pip install -e ".[dev,notebooks]"
python -m spacy download en_core_web_md     # whatever settings.spacy_model says
docker compose up -d
bash scripts/setup_neo4j.sh                 # applies ontology/ontology.cypher
```

### 4.3 Common loop

```bash
# mine one repo (no commits by default — see frozen-miner divergence)
python scripts/mine_one.py --repo python/cpython

# run the pipeline in its two stages (extractor+projector phase0/1, then annotator+phase2)
python scripts/run_pipeline.py
python scripts/run_pipeline.py --enrich     # + REFERENCES / REPLIES_TO enrichment

# Stage 2 is concurrent (annotator children + projector drain). Shard it across
# CPU cores (each shard owns a disjoint TextUnit id range; K=8 is a good start
# on a 28-core machine). --shard-index re-runs ONE shard (recovery).
python scripts/run_pipeline.py --stage 2 --annotate-shards 8
python scripts/run_pipeline.py --stage 2 --annotate-shards 8 --shard-index 3

# lint / format / test
ruff check . && ruff format .
pytest tests/test_word_formation_rules.py tests/test_gmane_ingester.py

# smoke-test one annotator on a string (fast annotation iteration)
python scripts/smoke_annotate.py --text "I'm not sure about the root cause."
```

### 4.4 The tests that actually run today

The full golden-example suite (`tests/test_annotators.py`) is currently
**un-runnable**: it imports a `run` helper and consumes an `nlp` fixture that
do not exist (BUILD_SPEC open debt 7). Do **not** chase this as a bug — it is
known. The self-contained suites are:

- `pytest tests/test_word_formation_rules.py` — pure-Python affix rules.
- `pytest tests/test_gmane_ingester.py` — ingester parsing, no services.
- `pytest tests/test_email_integration.py` — email extraction vs. stream shape.

Until debt 7 is fixed, verify a rule change with
`scripts/smoke_annotate.py` (§6) on the exact target string instead of the
golden suite.

---

## 5. Hard rules

These are non-negotiable. Violating them means your work will be reverted.

### 5.1 Rules live in YAML, not in Python

- **Never inline a lexical marker, regex, or spaCy pattern in Python code.**
- Annotators load their rules from the YAML files in `lexicons/` and `patterns/`.
- If a rule needs expressive power YAML cannot give, add a *mechanism* in Python
  and keep the *content* in YAML.
- All rule annotators share one signature: `annotate(unit: TextUnit, doc: Doc)`
  — the worker parses each unit once (`nlp.pipe`) and hands the same `Doc` to
  every annotator (v0.5 "parse once"; see `annotators/base.py`).

### 5.2 Every Signal carries provenance

- Every `Signal` emitted by an annotator must set `rule_id`, `rule_version`,
  and (for lexicon/pattern-based signals) the file version it came from.
- If you cannot produce a stable `rule_id`, you are not ready to emit a signal.
- Signals may carry `weight` (analysis-time confidence hint, **never** filtered
  at ingest) and `status` (`active` | `candidate`); see `annotators/base.py`.

### 5.3 Signals are never collapsed

- Do not combine multiple detections into a single signal "for efficiency."
- Do not filter out "likely false positive" signals at ingest. Let them through;
  analysis handles disagreement. This is the core research design commitment —
  see `FRAMEWORK_DESIGN.md` §1.
- **`blind spot` is intentionally double-counted** (lexical `fixed_phrase` +
  rhetorical `visibility` metaphor). They are different Signals with different
  meanings. Do not dedupe.

### 5.4 The classifier is one signal among many

- Never use the RoBERTa classifier's output to gate, filter, or weight other
  annotators' output.
- Never early-exit an annotator because the classifier already said 0 or 1.
- The classifier produces both a `Signal` (for consistency) *and* a
  `ClassifierVerdict` node. **Both records share the same derived `signal_id`**
  — that is safe only because the projector routes the verdict away before the
  Signal MERGE. Do not "fix" the id without de-colliding the verdict path.

### 5.5 Do not add infrastructure we did not ask for

Forbidden unless `BUILD_SPEC.md` explicitly requests them:

- Authentication, authorization, multi-tenancy
- Prometheus metrics, distributed tracing, structured logging frameworks
- Retry queues beyond what the existing miner has
- Abstract factories, dependency-injection containers, plugin registries for
  fewer than 5 items
- REST/GraphQL APIs over the graph (use the Neo4j driver directly from notebooks)
- Kubernetes manifests, Helm charts, Terraform
- Test suites for third-party libraries
- `try/except Exception` blocks that swallow without re-raising

### 5.6 Do not extend the ontology unilaterally

Adding a node label, relationship type, or signal category requires:

1. An update to `FRAMEWORK_DESIGN.md` §4 (prose + table).
2. An update to `ontology/schema.yml` and `ontology/ontology.cypher`.
3. A one-line entry in `rules/categories.yml` if it's a signal category.

If you cannot justify the addition against a cited source or an already-agreed
open decision, **do not add it.**

### 5.7 Python conventions

- Python 3.12+. Use modern typing: `list[str]`, `dict[str, Any]`, `str | None`,
  `Protocol`, `TypeAlias`, `@dataclass`.
- Type hints on **every** public function and method.
- `from __future__ import annotations` at the top of every module.
- Module-level logger: `logger = logging.getLogger(__name__)`. No `print`.
- Async where I/O is involved (HTTP, Mongo, Redis, Neo4j driver async);
  synchronous for pure compute (annotators).
- Line length 100. Format with `ruff format`. Lint with `ruff check`.

### 5.8 Writing style for code comments

Comments explain **why**, not what. If you feel the need to explain what,
the code is unclear — rewrite the code. A good comment cites a design doc
section or a paper.

### 5.10 Phase-0 memoization invariant (CHANGELOG 2026-08-16)

`GraphProjector._ensure_platform_venue_corpus`, `upsert_actor`, and the
Repository MERGE are memoized in Phase 0 to skip redundant idempotent upserts.
They must remain **pure idempotent upserts** — no non-deterministic `SET`
(`datetime()`, `randomUUID()`) — or the memo silently changes results. This is
the same discipline that keeps Phase 0 deterministic given its Mongo input.

### 5.11 No long-running terminal commands by the agent (2026-08-31)

The agent must not run shell commands that are expected to take **longer than
~3 minutes** (dumps, restores, ingests, pipeline stages, large merges,
multi-minute aggregations) — not synchronously, and not via `nohup`/background
in the agent's own shell. The user cannot see progress there, and silent
multi-minute waits look like a hang. Instead:

1. Prepare the exact command (and any scripts it needs).
2. Hand it to the user with the expected duration and the progress signal to
   watch (log file, document counts, stream lengths).
3. Let the **user** run it in their own terminal; verify results afterwards
   with bounded, read-only checks.

Agent-run commands must be fast and bounded (status checks, counts, `--census`,
single-document reads). This rule was added after the 2026-08-31 consolidation,
where a background `mongodump`/restore left the user blind to progress for
~40 minutes.

### 5.9 Record decisions in the CHANGELOG

- Any design decision, pilot observation, or accepted divergence you make
  **must** get a dated entry in `CHANGELOG.md` (newest at top) before the
  session ends. This is how the project keeps its traceability contract.
- If the task is a bugfix or implementation of a documented decision, a
  one-liner entry is enough. If you changed a rule or interpretation, say what
  and why, and cite the source if it came from outside `FRAMEWORK_DESIGN.md`.
- The CHANGELOG's "living record" promise is only true if agents write to it.
  Do not leave the drift this file was written to prevent.

---

## 6. How to verify your own work

**Golden rule:** a change you cannot run is a change that has not happened.
This is research code; you must be able to show the signal your change emits.

1. **Milestone acceptance checks** — run the relevant `BUILD_SPEC.md` one
   *if it is actually runnable*. Known non-runnable acceptances: M1
   `--max-items` (open debt 9, parsed but unused) and M2
   `python -m extractor.worker --once` (open debt 8, entrypoint missing). Skip
   those without "fixing" them — they are tracked.
2. **Golden examples** — the canonical file `tests/test_annotators.py` is
   **currently un-runnable** (missing `run`/`nlp` — open debt 7). Until that is
   fixed, verify rule behavior with the self-contained suites in §4.4 and with
   the smoke script below. Do not add broad integration tests; they rot.
3. **Smoke-test any new or changed lexicon/pattern entry** on the exact target
   string:

   ```bash
   python scripts/smoke_annotate.py --text "I can't reproduce this flaky failure."
   # one line per Signal: rule_id, layer, category, subcategory, span, form, weight, status
   ```

   A lexical or pattern change that does not appear in the smoke output is a
   bug — check the YAML, confirm `settings.pattern_set_version` selects the
   right file, and re-run.
4. **Run the sanity Cypher queries** at the bottom of `ontology.cypher` and
   check the numbers are plausible (needs a live Neo4j).

If any of these fail, do not move on.

---

## 7. When to proceed vs. when to ask

**Proceed without asking** when:

- The decision is aesthetic (variable naming, import order) — just follow the
  conventions in §5.7.
- The answer is in `FRAMEWORK_DESIGN.md` or `BUILD_SPEC.md` and you just need
  to read further.
- You need to add a lexicon entry or pattern that an earlier pilot observation
  justifies — add it with a `source: "pilot observation <date>"` field and move on.

**Stop and ask** when:

- You are about to violate one of the hard rules in §5.
- The `BUILD_SPEC.md` milestone is ambiguous about a data shape or interface.
- You find yourself wanting to change `async_miner.py` beyond the two listed
  integration tweaks (and the already-accepted `include_commits=False`
  divergence — BUILD_SPEC open debt 11).
- An annotator's rule would require NLP capability beyond spaCy + the
  RoBERTa classifier (e.g., you think you need a second ML model).
- You discover the ontology cannot express something the research requires.

**Flag but do not block** when:

- You notice a mistake or stale assumption in `FRAMEWORK_DESIGN.md` or
  `BUILD_SPEC.md`. Leave a `TODO(design-review)` comment with a one-sentence
  description and keep going against the current spec. The design docs get
  updated in a dedicated pass, not inline.
- Your task intersects one of the open-debt items or the known-but-not-yet-
  real things in this file (`present_nk` is documented in the taxonomy but has
  **no implemented rule**; `ocean_dataset/` is a disposable test corpus).

If you are stuck, produce: a concise description of the blocker, the exact
file/line where you stopped, two or three options with their trade-offs, and
your recommended option. **Never silently pick. Never add speculative
abstractions "to keep options open."**

---

## 8. Definition of done per module

A module is "done" when:

1. It implements the interface defined for it in `BUILD_SPEC.md`.
2. It reads its rules from YAML (never inline).
3. It has **at least one golden-example test per signal category it can emit**
   (recorded so once open debt 7 is fixed the suite passes).
4. Its module-level docstring names the `FRAMEWORK_DESIGN.md` section it
   realises.
5. Its changes are verifiable per §6 (smoke-testable) and its decisions are
   recorded in `CHANGELOG.md` per §5.9.

Anything beyond that is out of scope for v0.

---

## 9. Layout of the repository

This is the **only** canonical layout tree (FRAMEWORK_DESIGN.md and
BUILD_SPEC.md point here). If you move a file, update this tree — nothing else.

```
graphrag_nk/
├── AGENTS.md                     # this file
├── FRAMEWORK_DESIGN.md           # research frame + ontology rationale
├── BUILD_SPEC.md                 # agent-facing implementation plan
├── CHANGELOG.md                  # living build/decision log
├── REFINED_RQS_v0.2.md           # canonical research questions (v0.2)
├── REFINED_RQS_v0.3.md           # canonical research questions (v0.3 — curated-corpus scope)
├── MARKER_REVIEW.md              # marker/pattern audit (v0.1 → v0.2)
├── CODING_MANUAL.md              # RQ4 decision tree + predictions
├── CODING_MANUAL_v0.3.md         # v0.3 coding instrument (renumbered RQs + multi-actor flag)
├── TAXONOMY_CROSSWALK.md         # cross-taxonomy relations
├── SOURCES_AUDIT.md              # evidence basis for codebook confidences
├── pyproject.toml
├── docker-compose.yml            # Neo4j + MongoDB + Redis for local dev (AS SHIPPED / live)
├── docker-compose_new.yml        # spec-conformant compose reference variant
├── settings.py                   # (existing) LIVE config
├── settings_new.py               # reference variant (spec-conformant defaults)
├── broker.py                     # (existing)
├── progress.py                   # shared progress/ETA helpers
├── storage.py                    # Mongo client + bounded pool
├── miner/                        # Module 1 — async_miner.py FROZEN
│   ├── async_miner.py
│   ├── gmane_ingester.py         # mailing-list ingester (v0.6+)
│   ├── ocean_ingester.py         # OCEAN mailing-list ingester (v0.8)
│   ├── external_common.py        # shared helpers/ID construction for v0.8 ingesters
│   ├── openment_ingester.py      # GSoC mentor–mentee issues/PRs/comments (v0.8)
│   ├── numfocus_ingester.py      # NumFOCUS activity stream → issue/PR titles (v0.8)
│   ├── bugzilla_ingester.py      # BugsRepo Bugzilla bugs+comments (v0.8)
│   ├── jira_ingester.py          # Apache Jira (BSON) + Alternative Jira (Mongo) (v0.8)
│   ├── slack_ingester.py         # preethac Slack XML (v0.8)
│   ├── discord_ingester.py       # DISCO-A Discord XML (v0.8)
│   ├── gitter_ingester.py        # GitterCom CSV + LiveChatGitter ascii (v0.8)
│   ├── irc_ingester.py           # Kummerfeld Ubuntu IRC + new-domains (v0.8)
│   ├── stackoverflow_ingester.py # SO emotion gold workbook → posts (v0.8)
│   ├── sotorrent_ingester.py     # SOTorrent SO Q&A Posts.sql (v0.8)
│   └── curated_email_ingester.py # curated email code reviews (Patchwork .jl) (v0.8)
├── extractor/                    # Module 2
│   ├── text_unit_extractor.py
│   └── worker.py
├── annotators/                   # Module 3 (five sub-modules + worker)
│   ├── base.py                   # TextUnit, Signal, Annotator protocol
│   ├── lexical.py / morpho_syntactic.py / word_formation.py
│   ├── rhetorical.py / classifier.py
│   └── worker.py                 # reads TextUnits from Neo4j, annotates, publishes
├── projector/                    # Module 4 (phases 0/1/2; writes Cypher only)
├── enrichment/                   # post-ingest enrichments (REFERENCES, REPLIES_TO)
│   ├── email_threading.py
│   └── irc_threading.py          # IRC gold reply links → REPLIES_TO (v0.8)
├── ontology/
│   ├── schema.yml
│   ├── ontology.cypher
│   └── ignorance_codebook_v0.1.yml   # RQ4 pre-registered codebook
├── lexicons/
│   └── en_core_v0.2.yml          # (+ en_core_v0.1.yml baseline)
├── patterns/
│   ├── morpho_syntactic_v0.2.yml
│   ├── rhetorical_v0.2.yml
│   └── word_formation_v0.2.yml   # (+ v0.1 baselines)
├── rules/
│   └── categories.yml            # regenerated registry (v0.2)
├── notebooks/
│   ├── 01_descriptive.ipynb       # descriptive EDA (v0.1 scope)
│   ├── 02_rq_analysis.ipynb       # RQ1–RQ6 analysis (v0.2 scope)
│   ├── 02b_rq_analysis.ipynb      # RQ1–RQ6 analysis — v0.2 questions, v0.8 schema + 12 curated corpora
│   ├── 03_rq_analysis.ipynb       # RQ1–RQ5 analysis (v0.3 curated-corpus scope)
│   └── 03_rq3b_openment.ipynb     # RQ3b OpenMent mentor/mentee deep-dive (driver for scripts/openment_roles.py)
├── scripts/
│   ├── setup_neo4j.sh            # applies ontology.cypher
│   ├── run_pipeline.py           # starts all workers (+ --enrich, --census status dashboard)
│   ├── mine_one.py               # single-repo miner CLI
│   ├── republish_events.py       # rebuild stream_raw pointer events from Mongo (Redis is non-persistent)
│   ├── corpus_census.py          # shared corpus census helpers (curated corpus registry)
│   ├── smoke_annotate.py         # run one annotator on a string (§6)
│   ├── openment_roles.py         # RQ3b OpenMent mentor/mentee NK-gap analysis (P0–P5)
│   ├── export_threads_docx.py    # thread → Word export with NK spans shaded (DB-free)
│   ├── sample_units_by_genre.py  # 25/genre random NK-unit CSV+XLSX export + raw source text
│   ├── genre_composition.py      # RQ3.7 genre/dataset NK composition pull → cached CSV (v0.3.1)
│   ├── migrate_v0.8.cypher       # one-off backfill of pre-v0.8 nodes onto :Artefact (§4.7)
│   ├── eda_gmane_corpus.py       # pre-ingest mailing-list census/profile
│   └── diagnose_email_spans.py   # span-convention diagnostic
├── dataset_papers/               # curated MSR dataset papers (PDFs) — index in FRAMEWORK_DESIGN.md §12
├── ocean_dataset/                # TEST corpus — git-ignored, candidate for deletion
└── tests/
    ├── conftest.py
    ├── test_annotators.py        # golden-example tests (see BUILD_SPEC open debt 7)
    ├── test_word_formation_rules.py
    ├── test_gmane_ingester.py
    ├── test_email_integration.py
    ├── test_external_extractor.py   # v0.8 external extract_* functions
    ├── test_external_ingesters.py   # v0.8 curated-dataset parsers + dry-run engine
    ├── test_annotator_worker_batch.py  # batch fault tolerance + batched publishing
    ├── test_annotator_sharding.py      # _shard_where, backpressure, projector exit
    ├── test_openment_roles.py          # RQ3b OpenMent pure helpers (no DB)
    ├── test_sample_units_by_genre.py   # genre sampler pure helpers (DB-free)
    ├── test_genre_composition.py       # RQ3.7 composition pure helpers (DB-free)
    └── test_export_threads_docx.py     # thread → Word export (DB-free)
```

**External-drive corpora:** the curated MSR datasets live on an external drive at
`/Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets` (13 datasets, more may be
added), with their companion PDFs in `dataset_papers/` (repo root). The
dataset→paper index is in `FRAMEWORK_DESIGN.md` §12. These are research inputs,
distinct from the disposable `ocean_dataset/` test corpus.

---

*End of AGENTS.md.*