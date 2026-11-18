# BUILD_SPEC.md

*Implementation plan for GraphRAG-NK, optimised for a coding agent to execute
end-to-end. Read `AGENTS.md` first; read `FRAMEWORK_DESIGN.md` for rationale
when this document tells you to or when you need context.*

---

## 0. Context in 15 lines

We are building a research pipeline that:

1. Ingests GitHub repositories via an existing async miner (`miner/async_miner.py`)
   which dumps raw JSON into MongoDB and publishes events to a Redis stream.
   Mailing lists are ingested by `miner/gmane_ingester.py` (Webis Gmane corpus)
   into the same pipeline with `item_type="email"`.
2. Splits every mined artefact into `TextUnit`s (one per title / body /
   commit-message / comment-body; one per corpus segment for emails).
3. Runs one annotator worker over each TextUnit batch (lexical, morpho-syntactic,
   word-formation, rhetorical, RoBERTa classifier) that emit typed `Signal`s.
4. Writes the SE-artefact layer and the NK-analytical layer to Neo4j
   following the ontology in `ontology/ontology.cypher`.
5. Supports downstream analysis via Cypher queries and notebooks
   (`01_descriptive.ipynb`, `02_rq_analysis.ipynb`).

> **v0.7 flow change (2026-08).** The projector writes TextUnit nodes in a first
> pass (phase 1), and the annotator worker reads TextUnits **from Neo4j** instead
> of consuming `stream_units`; Signals are then published to `stream_signals` and
> projected in phase 2. See `FRAMEWORK_DESIGN.md` §3.

The research motivation is studying how non-knowledge (NK) is *linguistically
articulated* in software engineering discourse, grounded in
Janich & Simmerling (2013), Roberts's *Organizational Ignorance*, Vincze et al.
(2008), Szarvas et al. (2012), Smithson (2008), and related work. Full research
frame in `FRAMEWORK_DESIGN.md` §§1–2 and the canonical RQ statement in
`REFINED_RQS_v0.2.md`.

---

## 1. Locked design decisions (v0)

These are fixed for v0. Do not reopen without a written justification.

| Decision                              | Value for v0                                                |
| ------------------------------------- | ----------------------------------------------------------- |
| TextUnit granularity                  | **One per (artefact, role)**. No sentence split. **(Amended:** emails = one per corpus segment, §11.2 of FRAMEWORK_DESIGN.) |
| Metaphor detection                    | **Lexicon + patterns only** (no Shutova-style statistical)  |
| spaCy model                           | **`en_core_web_md`** with parser enabled, NER disabled (moved from `lg` 2026-07; v0.2 scope rules need `dep_`/`head`) |
| Classifier backend                    | **HF Transformers with `device="mps"`** (CPU fallback)       |
| Pilot corpus                          | **One repo end-to-end first.** Default: `python/cpython` + a shortlist of developer mailing lists. |
| Roberts's taxonomy                    | **Post-hoc annotation only.** Never at ingest.              |
| PR ↔ Issue ↔ Commit link extraction   | **Separate `enrichment/` step**, run after annotation.      |

---

## 2. Tech stack

**Runtime.** Python 3.12+. macOS (Apple Silicon) is the primary target (MPS
backend for the classifier). Linux works, will fall back to CPU for torch.

**Services (all via `docker-compose.yml`):**
- Neo4j (community edition, with APOC plugin)
- MongoDB
- Redis

> **As shipped (2026-08), the active `docker-compose.yml` diverges from this
> file's M0 snippet:** Neo4j runs `2026.02.2` (not `neo4j:5`) with
> `NEO4J_AUTH: none`, Mongo `mongo:8.2` (service name `mongodb`), Redis
> `redis:latest`, and host-mounted absolute-path volumes. The
> spec-conformant variant (pinned images, auth, named volumes) is preserved
> as `docker-compose_new.yml`. Either is acceptable for local research; keep
> one file and delete the other.

**Python dependencies** (pin to major; latest compatible minor is fine):

```toml
# pyproject.toml — dependencies section
dependencies = [
  "aiohttp>=3.10",
  "motor>=3.6",
  "redis>=5.2",              # async client (redis.asyncio)
  "neo4j>=5.20",             # official driver, async API
  "spacy>=3.7,<4",
  "torch>=2.3",              # MPS-capable
  "transformers>=4.44",
  "pyyaml>=6.0",
  "pydantic>=2.8",           # for message schema validation
  "fasttext-langdetect>=1.0",
  "python-dateutil>=2.9",
]

[project.optional-dependencies]
notebooks = ["jupyterlab", "pandas", "matplotlib", "seaborn", "networkx", "python-igraph", "leidenalg"]
dev = ["ruff>=0.6", "pytest>=8", "pytest-asyncio>=0.24"]
```

**Required spaCy model** (install during setup):
```bash
python -m spacy download en_core_web_md
```

---

## 3. Repository layout (final v0)

**The canonical, complete repository layout lives in `AGENTS.md` §9** — it is
the only copy kept in the repo, so it cannot drift. If you move a file, update
that tree, not this document. The milestone-relevant markers below are the
parts this spec cares about and are recorded here so Milestones M1–M10 can be
read without opening AGENTS.md:

- `miner/async_miner.py` — **EXISTING — frozen except §M1 tweaks**
- `miner/gmane_ingester.py` — mailing-list ingester (M0 environment aside; v0.6)
- `extractor/text_unit_extractor.py` + `extractor/worker.py` — §M2
- `annotators/lexical.py` — §M4; `morpho_syntactic.py` — §M5;
  `classifier.py` — §M6; `word_formation.py` — §M7; `rhetorical.py` — §M8;
  `annotators/worker.py` — orchestrator (reads TextUnits from Neo4j, runs
  annotators, publishes Signals)
- `projector/graph_projector.py` + `projector/worker.py` — §M3, §M4+ (phases 0/1/2)
- `enrichment/reference_extractor.py` — §M9; `enrichment/email_threading.py` — REPLIES_TO
- `ontology/schema.yml`, `ontology/ontology.cypher` — **ALREADY PROVIDED**;
  `ontology/ignorance_codebook_v0.1.yml` — RQ4 instrument
- `lexicons/en_core_v0.2.yml` (+ `_v0.1` baseline), `patterns/*_v0.2.yml`
  (+ `_v0.1` baselines) — rule content; `rules/categories.yml` — regenerated registry
- `scripts/run_pipeline.py` — starts all workers (+ `--enrich`);
  `scripts/mine_one.py`; `scripts/setup_neo4j.sh`; `scripts/smoke_annotate.py`;
  `scripts/eda_gmane_corpus.py`; `scripts/diagnose_email_spans.py`
- `tests/` — `test_annotators.py` (golden, un-runnable — debt 7),
  `test_word_formation_rules.py`, `test_gmane_ingester.py`, `test_email_integration.py`
- `notebooks/01_descriptive.ipynb` (§M10) and `notebooks/02_rq_analysis.ipynb`
  (RQ1–RQ6, implements `REFINED_RQS_v0.2.md`)
- Two compose/settings variants exist: **live** `docker-compose.yml` +
  `settings.py`; **reference** `docker-compose_new.yml` + `settings_new.py`.

---

## 4. Data-shape contracts (authoritative)

These are the exact JSON shapes that flow between modules. Use Pydantic models
to validate on both send and receive. **Do not deviate.** If you think a field
is missing, add it here first, then in code.

### 4.1 Event on `stream_raw` (emitted by miner — already implemented)

```json
{
  "item_id":   "12345",
  "item_type": "issue | pull_request | commit | repository | email",
  "repo_name": "python/cpython",
  "mongo_id":  "65abc...",
  "item_subtype": "issue | pull_request"
}
```

**Tweak needed in miner** (see Milestone 1): add `item_subtype` for items
where `item_type == "issue"` may actually be a PR (the GitHub Issues endpoint
returns both). The miner already branches on `"pull_request" in issue`; expose
that decision in the event so downstream doesn't re-read Mongo just to check.

**Email events** (`item_type="email"`) are emitted by `miner/gmane_ingester.py`
with the same envelope: `item_id` = the Gmane `urn`, `repo_name` = `gmane:<group>`
(e.g. `gmane.comp.python.general`), and `item_subtype="email"`.

### 4.2 Event on `stream_units` (emitted by Module 2)

```json
{
  "text_unit_id":  "issue:python/cpython:12345:body",
  "parent_id":     "issue:python/cpython:12345",
  "parent_type":   "issue",
  "repo":          "python/cpython",
  "parent_number": 12345,
  "role":          "body",
  "position":      1,
  "text":          "I'm not entirely sure why this happens, but it seems flaky.",
  "lang":          "en",
  "token_count":   13,
  "sha256":        "4b3c...",
  "author_login":  "someuser",
  "created_at":    "2024-05-01T12:00:00Z"
}
```

**ID construction rules (stable, deterministic):**
- `text_unit_id` = `{parent_id}:{role}` when `position` uniquely identifies
  role (title, body, commit_message); otherwise `{parent_id}:{role}:{position}`
  for comments.
- `parent_id` format per parent type:
  - Issue:       `issue:{repo}:{number}`
  - PullRequest: `pr:{repo}:{number}`
  - Commit:      `commit:{sha}`
  - Comment:     `comment:{github_comment_id}`

**v0.8 external parent IDs (curated MSR corpora, FRAMEWORK_DESIGN §4.7):**
The `parent_id` for Jira/Bugzilla/chat/SO artefacts is the artefact's globally
namespaced `record_id` (Storage is keyed on it too, and the projector matches
the TextUnit's parent by `Artefact.record_id` — never by string-splitting):
- JiraIssue / BugzillaIssue: `jira_issue:<corpus>:<issue_key>` / `bugzilla_issue:<corpus>:<bug_id>`
- Chat/IRC message:          `chat_message:<corpus>:<…venue/ordinal…>`
- Stack Overflow post:       `so_post:<corpus>:<n>`
These use `parent_type` ∈ {`jira_issue`, `bugzilla_issue`, `chat_message`,
`so_post`}. OpenMent/NumFocus reuse the GitHub-shaped `issue`/`pull_request`
types under a namespaced `repo` (`openment:<project_id>` etc.) and are tagged
with their own platform labels (not `:GitHubIssue`).

### 4.3 Event on `stream_signals` (emitted by annotators)

```json
{
  "signal_id":     "issue:python/cpython:12345:body::lex.unclear::42",
  "text_unit_id":  "issue:python/cpython:12345:body",
  "layer":         "lexical | morpho_syntactic | word_formation | rhetorical | classifier",
  "category":      "prototype",
  "subcategory":   "epistemic_state",
  "surface_form":  "unsure",
  "span_start":    12,
  "span_end":      18,
  "rule_id":       "lex.uncertain",
  "rule_version":  "0.2",
  "confidence":    null,
  "weight":        0.8,
  "status":        "active",
  "payload": {
    "lexicon_version": "0.2",
    "lemma":           "uncertain",
    "source_citation": "Janich & Simon 2017"
  }
}
```

**`signal_id` construction** (stable so re-runs idempotent):
`{text_unit_id}::{rule_id}::{span_start}`. The double colon is a visual
separator and avoids collisions with single-colon IDs.

> **`weight` / `status` added v0.2.** `weight` is a float analysis-time
> confidence hint (never an ingest filter); `status` ∈ {"active", "candidate"}
> encodes rule calibration. Both are persisted on the Signal node and refreshed
> via `ON MATCH SET` on re-run. A later rule version may change these fields.

> **Classifier signal_id collision (known, keep explicit).** The classifier's
> `Signal` and its `ClassifierVerdict` share `rule_id` + `span_start`, so their
> derived `signal_id` strings collide. This is safe today because the projector
> routes the `__verdict__` record away before the Signal MERGE; do not "fix" the
> id without also de-colliding the verdict path.

### 4.4 Classifier-specific signal + verdict

The classifier emits **two** records per TextUnit, in sequence:

1. A `Signal` on `stream_signals` with `layer="classifier"`,
   `category="roberta_binary"`, `surface_form=""`, `span_start=0`,
   `span_end=len(text)`, `confidence=<float>`, and `payload.label=<0|1>`,
   `payload.model_id="..."`, `payload.model_version="..."`.
2. A second event on `stream_signals` with a sentinel key
   `"__verdict__": true` carrying the fields for the `ClassifierVerdict` node.
   The projector routes these to the verdict MERGE instead of the signal MERGE.

This keeps the stream schema uniform (one event type) while still populating
both nodes.

---

## 5. Core interfaces

### 5.1 `annotators/base.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, Any

@dataclass(slots=True)
class TextUnit:
    """Mirrors the stream_units shape. Fields documented in BUILD_SPEC §4.2."""
    text_unit_id: str
    parent_id: str
    parent_type: str
    repo: str
    parent_number: int | None
    role: str
    position: int
    text: str
    lang: str
    token_count: int
    sha256: str
    author_login: str | None
    created_at: str | None

@dataclass(slots=True)
class Signal:
    """Mirrors the stream_signals shape. Fields documented in BUILD_SPEC §4.3."""
    text_unit_id: str
    layer: str
    category: str
    subcategory: str | None
    surface_form: str
    span_start: int
    span_end: int
    rule_id: str
    rule_version: str
    confidence: float | None = None
    weight: float | None = None        # v0.2 — analysis-time hint, never filtered at ingest
    status: str = "active"             # v0.2 — "active" | "candidate"
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def signal_id(self) -> str:
        return f"{self.text_unit_id}::{self.rule_id}::{self.span_start}"

class Annotator(Protocol):
    """All annotators implement this. Synchronous — annotation is CPU-bound."""
    name: str
    version: str
    def annotate(self, unit: TextUnit, doc: Doc) -> list[Signal]: ...
```

> **v0.5 change:** `annotate` receives the shared spaCy `Doc` as a second
> argument. The annotator worker parses each batch once (`nlp.pipe`) and
> distributes the same `Doc` objects to every annotator. (The §4.3 loaders
> note `make_nlp` uses `disable=["ner"]` with the parser **enabled**.)

### 5.2 `annotators/classifier.py` — `NKClassifier` protocol

```python
from typing import Protocol

class NKClassifier(Protocol):
    model_id: str
    model_version: str
    def predict(self, texts: list[str]) -> list[tuple[int, float]]: ...
```

The MPS-backed HF implementation is the default v0 ships. A scaffolding for an
MLX backend (`backend="mlx"`) exists but is **disabled by default**; keep the
protocol so it can be enabled without changing `ClassifierAnnotator`.

---

## 6. Milestones

Each milestone is a self-contained unit of work with an acceptance check the
agent can run. **Do one at a time, in order.** Do not start N+1 before
acceptance on N passes.

---

### Milestone 0 — Environment & ontology

**Scope.** Stand up services, install Python deps, apply ontology.

**Files to create.**
- `pyproject.toml` (per §2)
- `docker-compose.yml` — services below with default ports; persisted volumes.
- `.env.example` — `GITHUB_TOKEN=`, `NEO4J_URI=bolt://localhost:7687`,
  `NEO4J_USER=neo4j`, `NEO4J_PASSWORD=...`, `MONGO_URI=mongodb://localhost:27017`,
  `MONGO_DB_NAME=graphrag_nk`, `REDIS_URL=redis://localhost:6379/0`,
  `STREAM_RAW=graphrag.raw`, `STREAM_UNITS=graphrag.units`,
  `STREAM_SIGNALS=graphrag.signals`.
- `scripts/setup_neo4j.sh` — applies `ontology/ontology.cypher` via `cypher-shell`.
- `ontology/schema.yml` — prose-readable mirror of the Cypher schema, with
  cross-references to `FRAMEWORK_DESIGN.md` §4.
- `rules/categories.yml` — the table in `FRAMEWORK_DESIGN.md` §4.3 rendered as YAML.

**docker-compose services:**
```yaml
services:
  neo4j:
    image: neo4j:5
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:-researchpw}
      NEO4J_PLUGINS: '["apoc"]'
    ports: ["7474:7474", "7687:7687"]
    volumes: ["neo4j_data:/data"]
  mongo:
    image: mongo:7
    ports: ["27017:27017"]
    volumes: ["mongo_data:/data/db"]
  redis:
    image: redis:7
    ports: ["6379:6379"]
volumes:
  neo4j_data:
  mongo_data:
```

> **As shipped, the active compose diverges** (see §2): the repo root's
> `docker-compose.yml` runs Neo4j `2026.02.2` with `NEO4J_AUTH: none`,
> `mongo:8.2` (service `mongodb`), `redis:latest`, host volumes. This snippet
> is the spec-conformant version, kept in `docker-compose_new.yml`. Milestone
> 0's acceptance check uses whatever compose file is active; expect either
> zero-driven output or the count of existing nodes.

**Acceptance check.**
```bash
docker compose up -d
bash scripts/setup_neo4j.sh
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN labels(n), count(*) UNION CALL db.constraints() YIELD name RETURN 'constraint' AS labels, count(*) FROM (CALL db.constraints() YIELD name)"
# Expect: 0 nodes, ≥10 constraints created.
```

---

### Milestone 1 — Miner integration tweaks

**Scope.** Two surgical edits to `miner/async_miner.py`. Do **not** refactor.

**Edits.**
1. In `_save_and_publish`, add to the `_meta` block:
   ```python
   "content_sha256": hashlib.sha256(
       json.dumps(data, sort_keys=True, default=str).encode()
   ).hexdigest()
   ```
2. In the event published on `stream_raw`, add:
   ```python
   "item_subtype": "pull_request" if "pull_request" in data else "issue"
                   if item_type == "issue" else item_type
   ```

**Acceptance check.**
```bash
python scripts/mine_one.py --repo python/cpython --max-items 20
# Expect: ≥20 documents in each of raw_issues / raw_pull_requests / raw_commits.
# Every event published should carry item_subtype and every Mongo doc _meta.content_sha256.
```

`scripts/mine_one.py` is a thin CLI wrapper — ~20 lines — that instantiates
`AsyncGitHubMiner` and calls `mine_repository(repo)`, then exits.

> **As shipped.** The miner now defaults to **no commits**
> (`mine_repositories(include_commits=False)` — pilot observation 2026-07:
> commits are information-sparse relative to the text they carry; see
> CHANGELOG 2026-08-09). `mine_one.py --no-commits` is therefore the default
> behaviour. Two known issues (both in the "open technical debt" section):
> - `mine_one.py --max-items` is parsed but **not wired through** to the miner;
> - `mine_one.py` calls `mine_repositories`, so the `--no-commits` flag toggles
>   the same default that is already `False` in code.

---

### Milestone 2 — TextUnitExtractor

**Scope.** Module 2. Consume `stream_raw`, fetch doc from Mongo, emit TextUnit
events on `stream_units`.

**Files.**
- `extractor/text_unit_extractor.py` — pure functions
  `extract_from_issue(doc) -> list[TextUnit]`, `extract_from_pr`,
  `extract_from_commit`. No I/O.
- `extractor/worker.py` — async consumer of `stream_raw`, Mongo fetch,
  extractor dispatch, publish to `stream_units`.

**Rules for extraction.**
- Strip `>` quoted blocks (GitHub reply quoting).
- Strip fenced code blocks (` ``` ... ``` `).
- Strip `@mentions` (`@\w+`) — replace with empty string.
- Strip image tags (`![...](...)`).
- Preserve typos, punctuation, casing.
- Skip TextUnits whose `text` is empty after stripping.
- Set `lang` via `fasttext-langdetect`; non-English units are still emitted.
- `token_count` = naive whitespace split length (do not load spaCy here; this
  is a pre-annotation estimate).

**Acceptance check.**
```bash
# After Milestone 1 has populated Mongo:
python -m extractor.worker --once  # process all backlog, then exit
# Then in redis-cli:
# XLEN graphrag.units  → should be roughly 2-5× the raw count
# XRANGE graphrag.units - + COUNT 1 → should show the shape in §4.2
```

> **As shipped.** `extractor/worker.py` has **no `--once` flag / entrypoint**
> (`if __name__ == "__main__"` is absent) — see "open technical debt" item 8.
> In practice extractor + projector run from `scripts/run_pipeline.py` (stage
> 1). TextUnit events are still produced on `stream_units` (the projector's
> phase 1 consumes them, and the annotator worker now reads TextUnits back from
> Neo4j — FRAMEWORK_DESIGN §3).

**Golden example.**
Input issue body:
```
Not sure what's going on here.
> previous comment
@octocat can you look?

```python
print("x")
```
```

Expected TextUnit `text` (after stripping): `"Not sure what's going on here."`

---

### Milestone 3 — GraphProjector (SE-artefact layer only)

**Scope.** Consume `stream_units` (signals come later), write `Repository`,
`Actor`, `Issue` / `PullRequest` / `Commit` / `Comment`, and `TextUnit` nodes
and their edges. Use the MERGE templates in `ontology/ontology.cypher` §3.

Also pull parent metadata from Mongo the first time we see a new
`parent_id` — cache in memory for the duration of the worker process.

**Files.**
- `projector/graph_projector.py` — Cypher write functions keyed by parent_type.
- `projector/worker.py` — async consumer, batches by 100 units, commits
  per-batch.

**Batching strategy.** Collect up to 100 TextUnit events or 2 seconds of
events, whichever first. Execute one `UNWIND`-based Cypher call per batch.
Do not parallelise writes within a process; Neo4j transactions serialise fine.

> **As shipped.** Phase 1 (SE-artefact + TextUnit nodes) writes **per event**,
> not UNWIND-batched — acceptable at pilot scale; phase 2 (Signals) batches
> with `UNWIND` + `ON CREATE SET`. The projector also seeds `MailingList` /
> `Actor` / `EmailMessage` nodes (phase 0) for `item_type="email"` parents.

**Acceptance check.**
```cypher
// In Neo4j browser:
MATCH (r:Repository {full_name: "python/cpython"}) RETURN r;
MATCH (u:TextUnit) RETURN count(u);
MATCH (i:Issue)-[:HAS_TEXT]->(u:TextUnit) RETURN count(DISTINCT i), count(u);
```
Counts should match: (issues + PRs + commits + comments) mined in M1, and
each parent should connect to ≥1 TextUnit.

---

### Milestone 4 — LexiconAnnotator (Module 3c)

**Scope.** Implement `annotators/lexical.py` and wire into
`annotators/worker.py` (which reads TextUnits from Neo4j in pages, runs the
registered annotators over each parsed batch, publishes each Signal to
`stream_signals`). Extend `projector/worker.py` to also consume `stream_signals`
and write Signals + LexicalMarker nodes (Cypher §3.8–3.9).

**Key points.**
- Load `lexicons/en_core_v0.2.yml` at worker startup (v0.2 since MARKER_REVIEW;
  `settings.pattern_set_version` selects it).
- Build a `PhraseMatcher` keyed by lemma, compiled via `nlp.pipe` with parser
  and NER disabled for speed. For multi-word phrases (e.g., `blind spot`,
  `lack of`), use `attr="LEMMA"` and multi-token patterns.
- For each match: emit one Signal with `rule_id = f"lex.{entry.id}"`,
  `rule_version = lexicon.version`, and payload `{lexicon_version, lemma,
  source_citation}`.
- Also emit the `LexicalMarker` MERGE data; simplest: include a second event
  type on `stream_signals` with a `"__marker__": true` sentinel.
  (Alternatively, derive marker data from the signal payload inside the
  projector — this is cleaner. Choose one; document the choice in the
  module docstring.)

**Golden examples** (`tests/test_annotators.py`):
```python
@pytest.mark.parametrize("text, expected_rule_ids", [
    ("I'm unsure what caused this.",              ["lex.uncertain"]),
    ("There is a knowledge gap here.",             ["lex.knowledge_gap"]),
    ("Totally clear to me.",                       []),
    ("This is a blind spot for the team.",         ["lex.blind_spot"]),
    ("An ambiguous, vague specification.",         ["lex.ambiguous", "lex.vague"]),
])
def test_lexical_annotator(text, expected_rule_ids):
    signals = LexicalAnnotator().annotate(make_unit(text))
    assert sorted(s.rule_id for s in signals) == sorted(expected_rule_ids)
```

**Acceptance check.**
```cypher
MATCH (s:Signal {layer:'lexical'})-[:MATCHES_MARKER]->(m:LexicalMarker)
RETURN m.lemma, count(s) AS n ORDER BY n DESC LIMIT 20;
```
Should show real counts for seed lexicon entries on a mined repo.

---

### Milestone 5 — SpacyMorphoAnnotator (Module 3a)

**Scope.** Morpho-syntactic features. Implement `negation` and `modality`
first; `hedging`, `tense`, `syntactic_pattern` after those pass golden tests.

**Files.**
- `annotators/morpho_syntactic.py`
- `patterns/morpho_syntactic_v0.1.yml` — spaCy Matcher/DependencyMatcher
  specs as YAML. Example:
  ```yaml
  version: "0.1"
  patterns:
    - id: "morph.neg.adverbial_not"
      category: "negation"
      subcategory: "adverbial_not"
      source: "Vincze et al. 2008"
      type: "Matcher"
      pattern: [{"LOWER": "not"}]
    - id: "morph.neg.temporal_never"
      category: "negation"
      subcategory: "temporal_never"
      source: "Vincze et al. 2008; Helmer et al. 2016"
      type: "Matcher"
      pattern: [{"LOWER": "never"}]
    - id: "morph.mod.epistemic_modal"
      category: "modality"
      subcategory: "epistemic"
      source: "Hyland 1998"
      type: "Matcher"
      pattern: [{"TAG": "MD", "LOWER": {"IN": ["can", "could", "may", "might"]}}]
  ```
- Load patterns at startup; register with a spaCy `Matcher`.
- For each match: emit Signal with `rule_id = pattern.id`.

**Load the spaCy model once per worker** (expensive). Use
`spacy.load("en_core_web_md", disable=["ner"])` — we need the parser for
v0.2's DependencyMatcher scope rules, but not NER.

**Golden examples.**
```python
@pytest.mark.parametrize("text, categories", [
    ("We can't reproduce this.",                 {"negation"}),
    ("Might be a race condition.",                {"modality"}),
    ("We never saw this before.",                 {"negation"}),
    ("It simply works.",                          set()),
])
```

**Acceptance check.** Same shape as M4 but filtered by `layer='morpho_syntactic'`.

---

### Milestone 6 — ClassifierAnnotator (Module 3e)

**Scope.** Integrate the trained RoBERTa classifier with MPS backend.

**Files.**
- `annotators/classifier.py` — `HFTransformersClassifier` implementing the
  `NKClassifier` protocol, plus a `ClassifierAnnotator` that batches
  TextUnits inside the annotator worker for throughput.

**Batching.** Unlike other annotators, this one benefits from batching. The
annotator worker must expose a `batch_annotate(units: list[TextUnit])`
path for annotators that implement it. Default falls back to single-call.

**Configuration.** Model path comes from `settings.classifier_model_path`.
Model version string defaults to `Path(model_path).name`.

**Device fallback.** If `torch.backends.mps.is_available()` is False,
fall back to CPU with a `logger.warning`. Do not crash.

**Max length.** Truncate to 512 tokens. Log (at DEBUG, not WARNING) when
truncation happens; it will happen often and is fine for v0.

**Acceptance check.**
```cypher
MATCH (u:TextUnit)-[:CLASSIFIED_AS]->(v:ClassifierVerdict)
RETURN v.label, count(*) AS n, avg(v.confidence) AS avg_conf;
```
Both labels should appear with plausible confidence averages (> 0.5 for
the majority class).

---

### Milestone 7 — AffixAnnotator (Module 3b)

**Scope.** Pure morphology. Detect `un-`, `in-`, `non-`, `dis-` prefixes and
`-less`, `-able` suffixes on tokens whose POS is ADJ or NOUN.

**Files.**
- `annotators/word_formation.py`
- `patterns/word_formation_v0.2.yml` — simple allowlist and blocklist of
  stems per prefix (v0.2 since MARKER_REVIEW C-2/C-8: matches against a
  stem after stripping rather than whole surface strings, `under-` NK
  compounds preserved, blanket `-able` scan replaced by an allowlist under
  `shared_feature/epistemic_potentiality`):
  ```yaml
  prefixes:
    un:
      rule_id: "affix.prefix.un"
      category: "affix_negation"
      blocklist: ["under", "until", "unit", "union", "unique", "university"]
    in:
      rule_id: "affix.prefix.in"
      category: "affix_negation"
      blocklist: ["income", "index", "initial", "input", "install", "integer",
                  "interface", "interior", "internal", "issue"]
  suffixes:
    less:
      rule_id: "affix.suffix.less"
      category: "affix_negation"
    free:
      rule_id: "affix.suffix.free"
      category: "affix_negation"          # privative (v0.2)
  epistemic_potentiality:            # replaces blanket affix_modality (C-2)
    rule_id: "affix.deverbal.epistemic"
    category: "shared_feature"
    subcategory: "epistemic_potentiality"
    allowlist: ["questionable", "debatable", "unpredictable", "undecidable",
                "unknowable", "unverifiable", "unfalsifiable"]
  ```

**Algorithm.**
1. Run spaCy on the text (share the pipeline with `SpacyMorphoAnnotator` by
   passing the parsed `Doc` via the annotator worker — optional optimisation;
   not required for v0).
2. For each ADJ/NOUN token: check prefix/suffix, check blocklist, emit Signal.

**Known noise.** This annotator is intentionally conservative since v0.2 — the
research question is still which affixed forms recur, but the blanket `-able`
scan is gone (C-2) and `under` no longer blocks genuine `under-` compounds (C-8).

**Golden examples.**
```python
("The behaviour is unclear and unreliable.", ["affix.prefix.un", "affix.prefix.un"])
("This is impossible.",                       ["affix.prefix.in"])
("The interface is stable.",                  [])   # blocklist works
("A helpless situation.",                     ["affix.suffix.less"])
("A questionable decision.",                  ["affix.deverbal.epistemic"])
```

---

### Milestone 8 — RhetoricalAnnotator (Module 3d)

**Scope.** Metaphor, comparison, personification detection via patterns.

**Files.**
- `annotators/rhetorical.py`
- `patterns/rhetorical_v0.2.yml` — seed with figures from Simmerling & Janich
  (2015) + SE-native families from MARKER_REVIEW (v0.2 ships `black box`,
  `rabbit hole`, `can of worms`, `fog`, `iceberg`; most SE-native metaphors
  start as `status: candidate`). Example:
  ```yaml
  version: "0.2"
  figures:
    - figure_id: "metaphor.spatial.journey"
      family: "metaphor"
      subtype: "opacity"
      description: "Journey/terrain metaphors for non-knowledge"
      source: "Simmerling & Janich 2015"
      patterns:
        - [{"LOWER": "uncharted"}]
        - [{"LOWER": "unmapped"}, {"POS": "NOUN"}]
        - [{"LOWER": "stepping"}, {"LOWER": "into"}, {"LOWER": {"IN": ["unknown", "new"]}}]
    - figure_id: "metaphor.visibility.blind_spot"
      family: "metaphor"
      subtype: "visibility"
      description: "Visibility metaphors (blind spot, overlook, miss)"
      source: "Simmerling & Janich 2015"
      patterns:
        - [{"LOWER": "blind"}, {"LOWER": "spot"}]
    # comparison.kind_of was REMOVED in v0.2 (MARKER_REVIEW C-5): kind-of/sort-of
    # now live in the hedging layer only; rhetor keeps comparison.something_like.
  ```

Produce one Signal per match plus the `INSTANTIATES` edge to the
`RhetoricalFigure` node (projector handles the node MERGE).

**Known double-counting.** `blind spot` will be matched by both the lexical
annotator (as `fixed_phrase`) and the rhetorical annotator (as `visibility`
metaphor). **This is intentional** — the two Signals have different
categorical meanings and distinct `rule_id`s. Do not dedupe.

---

### Milestone 9 — Reference enrichment

**Scope.** Post-annotation pass that scans PR bodies and commit messages for
issue references and creates `REFERENCES` edges.

**Files.**
- `enrichment/reference_extractor.py`

**Regex (tested, do not reinvent):**
```python
REF_PATTERN = re.compile(
    r"(?:(?P<mechanism>close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|see)\s+)?"
    r"#(?P<number>\d+)",
    re.IGNORECASE,
)
```
`mechanism` captures `closes|fixes|resolves|ref|refs|see` (normalise to
lowercase canonical form); `None` → `mechanism="bare"`.

**Cypher.** Iterate over all TextUnits with `role` in
`{body, commit_message, comment_body}`, extract references, MERGE edges:
```cypher
MATCH (src:Issue|PullRequest|Commit {id: $src_id})
MATCH (dst:Issue {repo: $repo, number: $dst_number})
MERGE (src)-[r:REFERENCES]->(dst)
  ON CREATE SET r.mechanism = $mechanism, r.source_text_unit = $text_unit_id
```

**Acceptance check.**
```cypher
MATCH (p:PullRequest)-[r:REFERENCES]->(i:Issue) RETURN r.mechanism, count(*);
```
Should produce non-zero counts on a real repo.

---

### Milestone 10 — Descriptive notebook

**Scope.** First end-to-end demonstration. Produces plots, not insights.

**Notebook.** `notebooks/01_descriptive.ipynb` with sections:
1. Counts per node label.
2. Signals per layer × category (heatmap).
3. Top lexical markers.
4. Classifier label distribution vs. signal counts (scatter plot,
   unit-level).
5. First cut at RQ5: distribution of layer-diversity among units with
   classifier label 0 (histogram).

Use the Neo4j Python driver + pandas. Do not build a reusable query library
yet; duplicated queries across notebooks are fine in v0.

**Acceptance check.** Notebook runs end-to-end without errors on the
`python/cpython` pilot ingest.

---

## 7. v0 "done" criteria

v0 is complete when all ten milestones pass. Concretely:

- [ ] `docker compose up` brings the three services up cleanly.
- [ ] `python scripts/mine_one.py --repo python/cpython` fills MongoDB.
- [ ] `python scripts/run_pipeline.py` runs extractor + annotator + projector
      workers to exhaustion.
- [ ] The sanity queries in `ontology.cypher` §4 return plausible numbers.
- [ ] `pytest tests/test_annotators.py` passes with ≥1 golden example per
      signal category.
- [ ] `notebooks/01_descriptive.ipynb` runs top-to-bottom.

> **Status (2026-08):** the ten milestones are implemented. Two acceptance
> gates are current known issues, not evidence of incomplete implementation:
> the golden-example suite needs the `run`/`nlp` fixtures that are missing
> from `tests/conftest.py` (open debt 7), and `extractor.worker --once` does
> not exist (open debt 8). See the open technical debt section below.

---

## 8. What is deferred (v1+)

Not in v0, not even in scaffold form. Listed here only so the agent does
not "helpfully" add them:

- Sentence-level TextUnit splitting
- Active learning / classifier retraining
- Statistical metaphor identification (Shutova et al.)
- MLX backend for the classifier *(scaffolded `backend="mlx"` option exists;
  deliberately not the default — MPS is)*
- Multilingual support *(a `annotate_languages` scope filter exists; only "en"
  is annotated)*
- Source-code-AST features
- Web UI, REST API
- Distributed workers, Kubernetes, observability stack
- **Taxonomy-based clustering as the RQ4 residual definition** — abandoned in
  v0.2; the residual is defined from the coded sample. Clustering survives only
  as RQ4 sampling-frame construction (`rq4_marker_communities.csv`) and routine
  community clustering (RQ6).
- Cross-repo comparative analysis — v1
- **Repairing / merging the ignorance taxonomies** — explicitly *not asked* in
  v0.2 (REFINED_RQS_v0.2.md scope discipline): it needs a second corpus and
  would turn a falsifiable measurement into an unfalsifiable proposal.
- **A refined `ClassifierVerdict` signal_id** — see §4.3 note; currently safe
  only via the projector's verdict routing.

---

## 8a. Open technical debt (accepted for now; fix in a future update)

These are genuine defects or gaps, each with a small, known fix. They do not
block research because the current workflows route around them, but they will
bite the moment someone follows this spec's acceptance checks literally.
**The spec is not edited to excuse them; they are logged here so they are not
silently re-diagnosed.**

| # | Defect | Where | Fix (future) |
|---|--------|-------|--------------|
| 7 | `tests/test_annotators.py:31` imports `run` and consumes an `nlp` fixture, but `tests/conftest.py` defines neither. The golden-example suite for §7 / M4/M5 cannot pass until fixed. | `tests/conftest.py`, `tests/test_annotators.py` | Add a lightweight `run(ann, nlp, text)` helper and an `nlp` fixture (spaCy `en_core_web_md`) to conftest. |
| 8 | `python -m extractor.worker --once` cannot run — no `if __name__ == "__main__"` / `--once` flag in `extractor/worker.py`. M2's acceptance check is not executable. | `extractor/worker.py` | Add an entrypoint + `--once` (drain stream then exit). |
| 9 | `scripts/mine_one.py --max-items` is parsed but never passed to `mine_repositories` — M1's debug bound is a no-op. | `scripts/mine_one.py:40` | Thread `max_items` through `AsyncGitHubMiner.mine_repositories`/`mine_repository`. |
| 10 | `.env.example` missing (spec §3 / M0 lists it). Only a real `.env` is present. | repo root | Commit a `.env.example` with placeholder secrets. |
| 11 | `miner/async_miner.py` — a "frozen" file per AGENTS.md §3 — had its `mine_repositories` default flipped `True → False` (2026-08-04, CHANGELOG 2026-08-09). Documented here as an accepted divergence, decided from pilot observation; **revert requires a deliberate decision**, and future edits to this file remain subject to the frozen-file rule. | `miner/async_miner.py:237` | None (decision, not a bug). Do not treat as a license to edit further. |

---

## 9. Pointers for the agent

When confused, the correct place to look, in order:

1. `BUILD_SPEC.md` (this file) — milestone scope, data shapes, interfaces, open debt.
2. `AGENTS.md` — rules of engagement, common commands, canonical layout (§9).
3. `FRAMEWORK_DESIGN.md` — *why* a choice was made.
4. `ontology/ontology.cypher` — exact Cypher to emit.
5. `lexicons/*.yml`, `patterns/*.yml` — actual research content.
6. `REFINED_RQS_v0.2.md` — the question being answered; `MARKER_REVIEW.md` —
   why a marker rule says what it says; `CODING_MANUAL.md` /
   `TAXONOMY_CROSSWALK.md` / `SOURCES_AUDIT.md` / `ontology/ignorance_codebook_v0.1.yml`
   — the RQ4 instrument.

When genuinely stuck, escalate per `AGENTS.md` §7 ("When to proceed vs. when to ask").

---

*End of BUILD_SPEC.md.*
