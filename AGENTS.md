# AGENTS.md

*Behavioural contract for any coding agent (Claude Code, Cursor, Codex, etc.)
working on this repository. Read this file on every session. This file is the
authoritative entry point; it overrides inferred conventions.*

> If you are Claude Code: this file is also valid as `CLAUDE.md` — symlink or
> copy as needed. Content is identical.

---

## 1. What this project is

**GraphRAG-NK** — a research pipeline that mines GitHub repositories, annotates
the natural-language artefacts (issue/PR/commit/comment text) with linguistic
signals of *non-knowledge*, and stores everything in a Neo4j knowledge graph for
corpus-linguistic analysis.

**This is research code, not a product.** The quality bar is:

1. **Traceability of assumptions** — every rule, lexicon entry, and threshold
   must cite its source (paper, pilot observation, or `FRAMEWORK_DESIGN.md`
   section).
2. **Readability** — a researcher who is not the author should be able to read
   any module top-to-bottom and understand it in one sitting.
3. **Fast iteration** — changing a rule should be a YAML edit, not a refactor.

**Robustness, throughput, and operational polish are explicit non-goals.**

---

## 2. Canonical sources of truth (read before acting)

Treat these as authoritative. If what you are about to write disagrees with
them, **stop and flag the conflict** instead of silently diverging.

| File                              | Authority over                                           |
| --------------------------------- | -------------------------------------------------------- |
| `FRAMEWORK_DESIGN.md`             | Research frame, RQs, architecture, ontology, rationale   |
| `BUILD_SPEC.md`                   | Current implementation plan and milestone ordering       |
| `CHANGELOG.md`                    | Implementation status, known issues, deferred items      |
| `ontology/ontology.cypher`        | Database schema (constraints, indexes, MERGE templates)  |
| `ontology/schema.yml`             | Human-readable source of truth for the ontology          |
| `lexicons/*.yml`                  | Lexical markers — the ONLY place to add/edit markers     |
| `patterns/*.yml`                  | Morpho-syntactic and rhetorical patterns                 |
| `rules/categories.yml`            | Mapping of `rule_id` → (layer, category, subcategory)    |

**The existing `miner/async_miner.py` is frozen.** Do not refactor it. The only
allowed changes are the two small integration additions called out in
`BUILD_SPEC.md` Milestone 1.

---

## 3. Hard rules

These are non-negotiable. Violating them means your work will be reverted.

### 3.1 Rules live in YAML, not in Python

- **Never inline a lexical marker, regex, or spaCy pattern in Python code.**
- Annotators load their rules from the YAML files in `lexicons/` and `patterns/`.
- If a rule needs expressive power YAML cannot give, add a *mechanism* in Python
  and keep the *content* in YAML.

### 3.2 Every Signal carries provenance

- Every `Signal` emitted by an annotator must set `rule_id`, `rule_version`,
  and (for lexicon/pattern-based signals) the file version it came from.
- If you cannot produce a stable `rule_id`, you are not ready to emit a signal.

### 3.3 Signals are never collapsed

- Do not combine multiple detections into a single signal "for efficiency."
- Do not filter out "likely false positive" signals at ingest. Let them through;
  analysis handles disagreement. This is the core research design commitment —
  see `FRAMEWORK_DESIGN.md` §1.

### 3.4 The classifier is one signal among many

- Never use the RoBERTa classifier's output to gate, filter, or weight other
  annotators' output.
- Never early-exit an annotator because the classifier already said 0 or 1.
- The classifier produces both a `Signal` (for consistency) *and* a
  `ClassifierVerdict` node. Do not skip either.

### 3.5 Do not add infrastructure we did not ask for

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

### 3.6 Do not extend the ontology unilaterally

Adding a node label, relationship type, or signal category requires:

1. An update to `FRAMEWORK_DESIGN.md` §4 (prose + table).
2. An update to `ontology/schema.yml` and `ontology/ontology.cypher`.
3. A one-line entry in `rules/categories.yml` if it's a signal category.

If you cannot justify the addition against a cited source or an already-agreed
open decision, **do not add it.**

### 3.7 Python conventions

- Python 3.12+. Use modern typing: `list[str]`, `dict[str, Any]`, `str | None`,
  `Protocol`, `TypeAlias`, `@dataclass`.
- Type hints on **every** public function and method.
- `from __future__ import annotations` at the top of every module.
- Module-level logger: `logger = logging.getLogger(__name__)`. No `print`.
- Async where I/O is involved (HTTP, Mongo, Redis, Neo4j driver async);
  synchronous for pure compute (annotators).
- Line length 100. Format with `ruff format`. Lint with `ruff check`.

### 3.8 Writing style for code comments

Comments explain **why**, not what. If you feel the need to explain what,
the code is unclear — rewrite the code. A good comment cites a design doc
section or a paper.

---

## 4. How to verify your own work

Before declaring a milestone complete:

1. **Run the acceptance check** from the relevant `BUILD_SPEC.md` milestone.
   Every milestone has one, and it is runnable.
2. **Run the golden examples** for any annotator you touched
   (`pytest tests/test_annotators.py -k <your_annotator>`). Golden examples are
   one-line text inputs with expected signals hardcoded. Do not add broad
   integration tests; they rot.
3. **Run the sanity Cypher queries** at the bottom of `ontology.cypher` and
   check the numbers are plausible.

If any of these fail, the milestone is not complete. Do not move on.

---

## 5. When to proceed vs. when to ask

**Proceed without asking** when:
- The decision is aesthetic (variable naming, import order) — just follow the
  conventions in §3.7.
- The answer is in `FRAMEWORK_DESIGN.md` or `BUILD_SPEC.md` and you just need
  to read further.
- You need to add a lexicon entry or pattern that an earlier pilot observation
  justifies — add it with a `source: "pilot observation <date>"` field and move on.

**Stop and ask** when:
- You are about to violate one of the hard rules in §3.
- The `BUILD_SPEC.md` milestone is ambiguous about a data shape or interface.
- You find yourself wanting to change `async_miner.py` beyond the two listed
  integration tweaks.
- An annotator's rule would require NLP capability beyond spaCy + the
  RoBERTa classifier (e.g., you think you need a second ML model).
- You discover the ontology cannot express something the research requires.

**Flag but do not block** when:
- You notice a mistake or stale assumption in `FRAMEWORK_DESIGN.md`.
  Leave a `TODO(design-review)` comment with a one-sentence description and
  keep going against the current spec. The design doc gets updated in a
  dedicated pass, not inline.

---

## 6. Layout of the repository

```
graphrag_nk/
├── AGENTS.md                     # this file
├── FRAMEWORK_DESIGN.md           # research frame + ontology rationale
├── BUILD_SPEC.md                 # agent-facing implementation plan
├── pyproject.toml
├── docker-compose.yml            # Neo4j + MongoDB + Redis for local dev
├── settings.py                   # (existing)
├── broker.py                     # (existing)
├── miner/                        # Module 1 — FROZEN
│   └── async_miner.py
├── extractor/                    # Module 2
├── annotators/                   # Module 3 (five sub-modules)
├── projector/                    # Module 4
├── enrichment/                   # post-ingest enrichments (REFERENCES, etc.)
├── ontology/
│   ├── schema.yml
│   └── ontology.cypher
├── lexicons/
│   └── en_core_v0.1.yml
├── patterns/
│   ├── morpho_syntactic_v0.1.yml
│   └── rhetorical_v0.1.yml
├── rules/
│   └── categories.yml
├── notebooks/
├── scripts/
│   ├── setup_neo4j.sh            # applies ontology.cypher
│   └── run_pipeline.py           # starts all workers
└── tests/
    └── test_annotators.py        # golden-example tests only
```

---

## 7. Minimal expectations per module

A module is "done" when:

1. It implements the interface defined for it in `BUILD_SPEC.md`.
2. It reads its rules from YAML (never inline).
3. It has **at least one golden-example test per signal category it can emit**.
4. Its module-level docstring names the `FRAMEWORK_DESIGN.md` section it
   realises.
5. The acceptance check in its milestone passes.

Anything beyond that is out of scope for v0.

---

## 8. Escalation

If you are stuck, produce:
- a concise description of the blocker,
- the exact file/line where you stopped,
- two or three options with their trade-offs,
- your recommended option.

Never silently pick. Never add speculative abstractions "to keep options open."

---

*End of AGENTS.md.*
