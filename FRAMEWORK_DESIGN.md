# GraphRAG-NK — Framework Design

*A research-grade pipeline for studying Non-Knowledge (NK) in GitHub repositories,
grounded in the linguistic & sociological literature on ignorance studies
(Janich & Simmerling; Roberts; Vincze et al.; Szarvas et al.; Smithson; and others).*

---

## 0. How to read this document

This is a design outline, not an implementation. It defines:

1. The **research frame** (§1) and **refined research questions** (§2) that the
   framework must answer.
2. The **ontology** (§4) — the single most important artefact, because every later
   analytical move depends on it.
3. The **pipeline architecture** (§3) and **per-module outline** (§5), kept deliberately
   thin: research code, not production infrastructure.
4. A **RQ → Cypher query mapping** (§6) so the framework is traceable end-to-end.
5. **Out-of-scope** (§8) and **open decisions for you** (§9).

Where I make a design choice, I name the source it comes from so you can reject it
if the reading disagrees with yours.

---

## 1. The design frame: signal pluralism

### 1.1 Why we cannot commit to a single label

The literature you cite converges on one point:

> From a linguistic point of view there are hardly any unambiguous or universally
> valid linguistic markers of ignorance in texts.

What exists are **prototypical patterns** — co-occurrences of cues from several layers
(Janich & Simmerling 2013; Vincze et al. 2008; Szarvas et al. 2012). Any framework that
flattens this at ingest — whether by taking RoBERTa's argmax or by hard-coding a keyword
list — loses the multi-layered evidence structure that makes the phenomenon tractable in
the first place.

### 1.2 The core architectural commitment

**Every detection emits a distinct `Signal` node in the KG.** Signals carry:
- the layer they belong to (`lexical`, `morpho_syntactic`, `word_formation`, `rhetorical`, `classifier`),
- a category + subcategory,
- the exact text span,
- provenance (rule id, lexicon version, model id+version, confidence where applicable),
- a `weight` (float, analysis-time confidence hint — encoded so downstream
  scoring is explicit rather than implicit in match order) and a `status`
  of `active` | `candidate` (empirically-calibrated rule promotion/demotion;
  MARKER_REVIEW §3.5).

Signals are never overwritten, never collapsed, and never filtered at ingest on
any criterion (weight, status, "likely false positive"). The RoBERTa classifier
is *one* signal source. Taxonomic labels (Roberts, etc.) are assigned *over*
signals, by analysts or downstream clustering — never at ingest.

This is what makes the framework honest to your stated goal:
**understand where the existing taxonomies hold, where they break, and where the classifier fails.**

### 1.3 What "research-grade" means here

Per your brief: readability, traceability of assumptions, and fast iteration over
defensive robustness. Concretely:

| we do                                            | we do not                                |
| ------------------------------------------------ | ---------------------------------------- |
| version every lexicon/pattern file               | build retry queues for every failure     |
| record rule IDs on every Signal                  | write exhaustive edge-case handlers      |
| keep raw text on every TextUnit                  | build auth / multi-tenant isolation      |
| use stdlib + a few well-known libs (spaCy, HF)   | introduce k8s / service meshes           |
| let analysts override anything in notebooks      | hide the DB behind a "safe" API          |

---

## 2. Refined Research Questions

The canonical, current statement of the research questions is
**`REFINED_RQS_v0.2.md`** (v0.2, 2026-08). It supersedes the v0.1 formulation
below and reorganises the work into **four layers of claim**:

- **Layer 0 — instrument-level (RQ4a):** what the borrowed ignorance taxonomies
  can and cannot distinguish, established from sources alone (no SE data).
- **Layer 1 — descriptive (RQ1–RQ3):** what markers occur.
- **Layer 2 — comparative (RQ6):** how arenas and communities differ.
- **Layer 3 — critical (RQ4b–d, RQ5):** where the theory and the method fail.

v0.2 changed the design in four material ways, each justified in the refinement
doc by a confound or an audit finding:

1. **RQ4 was split into RQ4a–d.** The taxonomy crosswalk
   (`TAXONOMY_CROSSWALK.md`) showed 8 of 17 documented cross-taxonomy pairs
   admit *no distinguishing test at all* — a literature-level finding that needs
   **no corpus**, so it became its own data-free question (RQ4a). RQ4b covers
   category coverage under the multi-fit pass, RQ4c whether the predicted
   collapses manifest in coder behaviour, RQ4d the residual and the multi-actor
   (P4) hypothesis.
2. **Rates are token-normalised** (per 1k tokens, via `TextUnit.token_count`)
   for RQ1/RQ3/RQ6, because GitHub and mailing-list units differ systematically
   in length.
3. **RQ5 forbids the classifier as a marker-weight target** and defines marker
   weight as banded, hand-labelled per-rule precision (the two instruments must
   stay independently constructed).
4. **RQ6 was narrowed to a descriptive arena claim** — the current corpus does
   not yet implement the crossed project×channel design; a clean within-project
   audience contrast (`gmane.comp.gis.qgis.devel` vs `.user`) is now also
   reported.

The original three-RQ framing, which remains the seed of RQ1–RQ3, was:

**RQ1 — Lexical–denotative.**
Which lexical items (nouns, verbs, adjectives, adverbs, fixed multi-word expressions)
function as markers of NK in SE discourse? How do their frequencies, collocations, and
distributions across artefact types (issue / PR / commit / review) and across
repositories compare to patterns reported by Janich & Simon (2017),
Müller & Stegmeier (2019)?
*(Maps to: Janich & Simmerling §3a.)*

**RQ2 — Morpho-syntactic.**
How do developers articulate NK through tense (past/present/future NK: "we didn't know",
"we don't yet know", "we'll never know"), modality (modal verbs, hedging adverbs),
negation (lexical and morphological via `un-`, `in-`, `-less`, `-able`), and syntactic
patterns (question-answer structures, adversative constructions)?
Which *co-occurrence profiles* of these features are prototypical of SE — i.e., which
combinations recur often enough to count as conventionalised?
*(Maps to: §1a–d, §2.)*

**RQ3 — Rhetorical.**
Which metaphors (spatial, visibility, container), personifications, hyperboles, and
comparative constructions frame NK in SE? What evaluative stance (pejorative,
neutral, valorising) do they impose, and does this stance vary by artefact type
(e.g., bug reports vs. PR reviews)?
*(Maps to: §3b; Simmerling & Janich 2015; Smithson 2008.)*

For the current operationalisation of RQ4 (now RQ4a–d, driven by the
pre-registered instrument stack: `ontology/ignorance_codebook_v0.1.yml`,
`CODING_MANUAL.md`, `TAXONOMY_CROSSWALK.md`, `SOURCES_AUDIT.md`) and of RQ5/RQ6,
see `REFINED_RQS_v0.2.md`.

RQ5 — model vs. linguistic evidence — is the reason `Signal` and
`ClassifierVerdict` must both live in the graph and be queryable side-by-side.

---

## 3. Pipeline architecture

Your existing miner already establishes a **Producer → Broker (Redis Stream) → Consumer**
pattern with MongoDB as the data lake. We extend that same pattern — no new infra.

> **v0.7 data-flow amendment (2026-08):** the annotator worker no longer consumes
> `stream_units`. TextUnit events are fanned out of `stream_units` at ingest and
> the projector **phase 1** writes them straight to Neo4j; the annotator worker
> reads TextUnits back **from Neo4j** in pages (line-scoped by the annotation
> profile), batches them through `nlp.pipe` + the classifier, and publishes
> Signals to `stream_signals`, which phase 2 projects. This was forced by
> reliability: an annotator backlog could silently lose Redis events, and
> re-annotation on existing graph data is now trivially idempotent (MERGE on
> `text_unit_id`). The pipeline *shapes* below are unchanged — only the
> annotator's input source and the projection fan-out differ.

```
┌──────────────────────┐   stream_raw   ┌──────────────────────┐
│  AsyncGitHubMiner    │ ─────────────▶ │ TextUnitExtractor    │  (Module 2)
│  (existing)          │                └──────────┬───────────┘
└──────────────────────┘                           │ stream_units
          │  writes raw JSON                       ▼
          ▼                              ┌──────────────────────┐
     ┌──────────┐                        │ GraphProjector       │  (Module 4)
     │ MongoDB  │◀────reads full doc─────│  phase 1: SE-artefact │
     │ raw_*    │                        │  + TextUnit nodes     │
     └──────────┘                        └──────────┬───────────┘
                                                    │ reads TextUnits from Neo4j (pages)
                                                    ▼
                                          ┌──────────────────────┐
                                          │  Annotator worker    │  (Module 3)
                                          │  single process,     │
                                          │  shared nlp.pipe:    │
                                          │  3a morpho-syntactic │
                                          │  3b word-formation   │
                                          │  3c lexical markers  │
                                          │  3d rhetorical figs  │
                                          │  3e NK classifier    │
                                          └──────────┬───────────┘
                                                     │ stream_signals
                                                     ▼
                                          ┌──────────────────────┐
                                          │  GraphProjector      │  (Module 4)
                                          │  phase 2: signals    │
                                          └──────────┬───────────┘
                                                     ▼
                                                ┌─────────┐
                                                │ Neo4j   │
                                                └────┬────┘
                                                     │
                                                     ▼
                                          ┌──────────────────────┐
                                          │  Analysis notebooks  │  (Module 5)
                                          │  Cypher + pandas     │
                                          └──────────────────────┘
```

### 3.1 Why these boundaries

- **Why split TextUnit extraction from annotation?** Because the *unit of analysis* is
  a decision (one body = one unit? one paragraph = one unit? one sentence = one unit?)
  and you will want to revise it mid-project. Isolating extraction from annotation lets
  you re-run extraction without re-running expensive annotation, and vice versa.
- **Why a single annotator process instead of a per-annotator fan-out?** Because each
  batch is parsed **once** and the shared spaCy `Doc` object is handed to every
  annotator (v0.5 "parse once" change) — a single parse serves five annotators, so
  fanning out per annotator would parse five times. Each annotator keeps its own
  compiled matchers/pattern sets; `annotators/worker.py` orchestrates the batch.
- **Why a dedicated GraphProjector?** So Cypher writes are the *only* place that knows
  the ontology. Annotators emit Signals in a neutral JSON schema; the projector decides
  how they become nodes+edges. If you revise the ontology, only the projector changes.
  **Constraint (amended):** the annotator worker *reads* TextUnits from Neo4j, but it
  never *writes* Cypher — all writes go through the projector.

### 3.2 Idempotency

All Cypher writes use `MERGE` with stable natural keys
(`(repo, artefact_number, text_unit_position)` for TextUnits; `(text_unit_id, rule_id, span)`
for Signals). Re-processing a text unit overwrites its signals cleanly.

---

## 4. Ontology

The ontology has two layers: an **SE-artefact layer** (what exists in the repo) and an
**NK-analytical layer** (the linguistic overlay). Keeping them separate lets you study
NK without committing the SE layer to any particular theory of ignorance.

The ontology is documented in YAML (`/ontology/schema.yml`) and implemented in
`/ontology/ontology.cypher` (constraints + example MERGE templates). The YAML is the
source of truth; the Cypher is its DB projection.

### 4.1 SE-artefact layer

| Node label       | Natural key                        | Key properties                                                  |
| ---------------- | ---------------------------------- | --------------------------------------------------------------- |
| `Repository`     | `full_name`                        | `stars`, `language`, `created_at`, `mined_at`                   |
| `Actor`          | `login`                            | `type` ∈ {User, Bot}, `name`                                    |
| `Issue`          | `(repo, number)`                   | `state`, `created_at`, `closed_at`, `labels`                    |
| `PullRequest`    | `(repo, number)`                   | `state`, `merged`, `created_at`, `closed_at`                    |
| `Commit`         | `sha`                              | `authored_at`, `committed_at`                                   |
| `Comment`        | `github_comment_id`                | `kind` ∈ {issue, pr_review, pr_issue}, `created_at`             |
| `TextUnit`       | `(parent_id, position)`            | `text`, `lang`, `token_count`, `sha256`                         |

> **Implementation status (v0.7, 2026-08):** the `Comment` node layer is
> **declared but not yet populated**. Comments are currently flattened into
> `TextUnit`s directly under the owning Issue (`parent_type="issue"`), and PR
> *reviews* (`kind="pr_review"`) are not mined at all (the review-collection
> branch in `miner/async_miner.py` is disabled). Modelling comments as first-class
> nodes remains the design intent (per-artefact grouping, `AUTHORED` provenance
> to the comment author) and is a valid future enrichment; the constraint is
> already in `ontology.cypher`. Analysis that needs per-comment grouping must
> reconstruct it from `TextUnit.parent_id` + `parent_type` for now.

Edges:
- `(Repository)-[:CONTAINS]->(Issue|PullRequest|Commit)`
- `(Actor)-[:AUTHORED]->(Issue|PullRequest|Commit|Comment)`
- `(Issue|PullRequest)-[:HAS_COMMENT]->(Comment)`
- `(Issue|PullRequest|Commit|Comment|EmailMessage)-[:HAS_TEXT {role}]->(TextUnit)` — `role` ∈ {title, body, commit_message, comment_body, subject} ∪ segment labels (e.g. paragraph, section_heading)
- `(PullRequest)-[:REFERENCES {mechanism}]->(Issue)` — extracted from `fixes #123`, `closes #123`, `refs #123`
- `(PullRequest)-[:TOUCHES]->(Commit)` — planned (PR→commit fetching not yet implemented)

**Design choices.**

- *Every* piece of natural-language text is a `TextUnit`, regardless of whether it came
  from a title, body, commit message, or comment. This gives annotators a single,
  uniform input type and makes cross-artefact comparisons (RQ3) trivial.
- The `position` property on `TextUnit` lets you split long bodies into paragraph- or
  sentence-level units later *without* changing the ontology — just re-extract with a
  finer grain and the graph grows more leaves.
- `sha256` on `TextUnit` is for dedup across artefacts (the same boilerplate disclaimer
  appears hundreds of times in some repos; you want to know that).

### 4.2 NK-analytical layer

This is where the research lives. The central idea: a `Signal` is a typed, provenance-
carrying piece of evidence about a `TextUnit`. Nothing else.

| Node label            | Natural key                              | Key properties                                                                                                                     |
| --------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `Signal`              | `(text_unit_id, rule_id, span_start)`    | `layer`, `category`, `subcategory`, `surface_form`, `span_start`, `span_end`, `rule_id`, `rule_version`, `weight`, `status` (active\|candidate), `payload_json`, `created_at` |
| `LexicalMarker`       | `(lemma, lexicon_version)`               | `pos`, `category`, `subcategory`, `polarity`, `source_citation`                                                                    |
| `RhetoricalFigure`    | `figure_id`                              | `family` ∈ {metaphor, personification, hyperbole, comparison, irony}, `description`, `source_citation`                             |
| `ClassifierVerdict`   | `(text_unit_id, model_id, model_version)`| `label` ∈ {0,1}, `confidence`, `predicted_at`                                                                                      |
| `IgnoranceType`       | `type_id`                                | `name`, `definition`, `source` (e.g., "Roberts 2013"), `scope` ∈ {imported, derived}                                               |

> The `weight`/`status` fields were added in v0.2 (MARKER_REVIEW §4). A rule's
> `weight` is an analysis-time confidence hint and **never** an ingest filter;
> `status` marks empirically-calibrated promotion/demotion (`active`/`candidate`),
> written via `ON MATCH SET` so re-running after calibration refreshes existing
> nodes. There is a `signal_status` index.

Edges:
- `(TextUnit)-[:HAS_SIGNAL]->(Signal)`
- `(Signal)-[:MATCHES_MARKER]->(LexicalMarker)` *(for `layer=lexical`)*
- `(Signal)-[:INSTANTIATES]->(RhetoricalFigure)` *(for `layer=rhetorical`)*
- `(TextUnit)-[:CLASSIFIED_AS]->(ClassifierVerdict)`
- `(TextUnit)-[:TYPED_AS {annotator, confidence, rationale}]->(IgnoranceType)` — *manual or clustering-derived; never from a rule at ingest*

### 4.3 Signal categories — the taxonomy we project the literature onto

This mapping is the crux. It is the answer to your requirement that the ontology
"reflect the linguistic research." Every category has a cited source and is
implemented as a rule file in the repo.

> **Authoritative table (v0.2, 2026-08):** the canonical, complete
> `(layer, category, subcategory)` registry is `rules/categories.yml`, which is
> *regenerated by walking the four pattern/lexicon files themselves*
> (`lexicons/en_core_v0.2.yml`, `patterns/morpho_syntactic_v0.2.yml`,
> `patterns/rhetorical_v0.2.yml`, `patterns/word_formation_v0.2.yml`) so it
> cannot drift from what the annotators load. The full rationale for every
> v0.2 category is `MARKER_REVIEW.md`. The table below is the v0.2 summary —
> read `rules/categories.yml` before adding or renaming a category.

| `layer`            | `category`              | `subcategory` examples                                     | cited source                          |
| ------------------ | ----------------------- | ---------------------------------------------------------- | ------------------------------------- |
| `morpho_syntactic` | `tense`                 | `past_nk` (past_nk_notyet), `future_nk`                    | Janich 2020                           |
| `morpho_syntactic` | `modality`              | `epistemic` (may, might), `underspecified` (can, could, would) | Hyland 1998; Vold 2006; MARKER_REVIEW C-1 |
| `morpho_syntactic` | `hedging`               | `adverbial`, `approximator`, `shield_epistemic`, `shield_plausibility`, `vagueness` | Szarvas et al. 2012; Prince et al. 1982; Hyland 1998 |
| `morpho_syntactic` | `negation`              | `bare_negation`, `scoped_epistemic`, `quantifier_no`, `temporal_never` | Vincze et al. 2008; MARKER_REVIEW C-3 |
| `morpho_syntactic` | `epistemic_verb`        | `not_knowing` (I don't know), `complement_shield` (I think/guess) | Bongelli & Zuczkowski (KUB); Rubin 2007; MARKER_REVIEW M-1/M-2 |
| `morpho_syntactic` | `evidential`            | `inferential` (seem, appear, suggest), `reportative` (apparently, allegedly) | Aikhenvald 2004; MARKER_REVIEW M-3/C-6/C-7 |
| `morpho_syntactic` | `syntactic_pattern`     | `question_answer`, `embedded_question`, `tag_question`, `adversative` (demoted) | Bongelli et al. 2018; Simon 2020; MARKER_REVIEW M-4/C-9 |
| `word_formation`   | `affix_negation`        | `un_prefix`, `in_prefix`, `less_suffix`                    | Janich & Simmerling 2013              |
| `word_formation`   | `shared_feature`        | `epistemic_potentiality` (allowlist: questionable, undecidable, unknowable) | MARKER_REVIEW C-2 (replaces `affix_modality`) |
| `lexical`          | `prototype`             | `epistemic_state`, `imprecision`, `not_knowing`, `plausibility_shield`, `attribution_shield`, `evidential_inferential`, `evidential_reportative`, `booster` (non-NK) | Janich & Simon 2017; MARKER_REVIEW M-1/M-2/M-3/M-6 |
| `lexical`          | `fixed_phrase`          | `visibility_metaphor` (blind spot), `gap_phrase`           | Simmerling & Janich 2015              |
| `lexical`          | `shared_feature`        | SE-native: `repro_gap`, `opacity`, `spec_gap`, `doc_gap`, `non_deterministic_behaviour`, `code_comment_marker`; also `lack_of`, `unresolved` | Müller & Stegmüller 2019; MARKER_REVIEW M-5 |
| `rhetorical`       | `metaphor`              | `SE_native` (black box, rabbit hole, can of worms, fog) vs canonical (`opacity`, `hidden_extent`, `obscurity`) | Simmerling & Janich 2015; MARKER_REVIEW v0.2 |
| `rhetorical`       | `personification`       |                                                            | Simmerling & Janich 2015              |
| `rhetorical`       | `comparison`            | `something_like` (`kind_of` removed — MARKER_REVIEW C-5)   | Simmerling & Janich 2015              |
| `classifier`       | `roberta_binary`        | —                                                          | your model                            |

**v0.2 delta vs v0.1** (full rationale in MARKER_REVIEW.md §§1–2):
- New marker families: `epistemic_verb`, `evidential`, `hedging` shields,
  `embedded_question`, `tag_question` (M-1…M-7); boosters added as the
  **non-NK contrastive pole** for RQ5 stance analysis.
- Renames: `affix_modality` → `shared_feature/epistemic_potentiality` (blanket
  `-able` scan replaced by an allowlist — C-2); `adverbial_not` →
  `bare_negation` with scoped alternatives (C-3); `quasi_modal_seem` →
  `evidential/inferential` (C-6); `kind_of`/`sort_of` comparison removed from
  the rhetorical layer (C-5).
- `present_nk` appears in the v0.1-tense row above but has **no implemented
  rule** in the v0.2 files; do not rely on it until a rule ships.
- Negation/modality raw cues are no longer standalone NK signals where the
  MARKER_REVIEW required scope (C-1, C-3); the scoped variants carry the
  weight, bare cues are demoted to co-occurrence features.

**You will disagree with some of these mappings.** Good — every one of them is one row
in a YAML file. Changing the taxonomy is a PR, not a refactor.

### 4.4 Why `LexicalMarker` and `RhetoricalFigure` are separate nodes

Two reasons:
1. They enable **dictionary queries** ("show me every use of `blind spot` across the
   corpus") without scanning every `Signal` node. One-hop neighbourhood.
2. They carry their own versioned provenance — the lexicon entry's source citation —
   independently of the rule that matched them. When you update the lexicon, you update
   those nodes; existing `Signal`s still point at the specific `(lemma, version)` pair.

### 4.5 Why `IgnoranceType` is assigned *post-hoc*

The point of RQ4 is to test whether Roberts's taxonomy fits SE. If you wire Roberts's
types into the rule base at ingest, you'll find exactly what you wired in. So:

- At ingest: only layer-specific signals fire. No `IgnoranceType` edge.
- At analysis: you (a) hand-label a sample of TextUnits with `IgnoranceType`,
  then (b) train a classifier / cluster based on signal profiles, or (c) declare new
  derived types (`scope=derived`) grounded in the signal clusters you find.

The graph supports all three paths and keeps the provenance (`annotator`, `rationale`)
on the edge.

### 4.6 The RQ4 instrument stack (post-hoc taxonomy layer, v0.2)

RQ4 is operationalised through a **pre-registered coding instrument**, delivered
before corpus contact (2026-08):

- `ontology/ignorance_codebook_v0.1.yml` — 28 categories + 3 orthogonal Wehling
  dimensions, each with `source_locator`, `definition_confidence`,
  `source_vagueness`, inclusion/exclusion criteria and discriminating questions.
  Non-fit codes (RESIDUAL / NOT_NK / UNCODABLE) deliberately live in the manual,
  not the codebook.
- `CODING_MANUAL.md` — the deterministic decision tree (Step 0–5) with a fixed,
  pre-registered taxonomy priority (Roberts → Wehling → Smithson → Gross), plus
  predictions P1–P6 written before data contact.
- `TAXONOMY_CROSSWALK.md` — every documented relation between categories; 8 of 17
  cross-taxonomy pairs are `NONE_POSSIBLE` (no source-given distinguishing test).
- `SOURCES_AUDIT.md` — the evidence basis for every confidence rating
  (Roberts/Wehling at full primary text; Smithson partial; Gross secondary-only).

The hand-coded sample resulting from this instrument is the unit of analysis for
RQ4b–d, replacing the v0.1 plan of defining the residual via cluster membership.

### 4.7 Multi-platform corpus layer (v0.8, 2026-08)

The curated MSR corpora (§12) introduced platforms beyond GitHub and mailing
lists: Jira, Bugzilla, Slack, Discord, Gitter, IRC, and Stack Overflow. The
design principle is that **platforms are first-class and comparable**, not a
bag of "external records":

- `Platform` — the comparison dimension for RQ6 (the communication-channel
  kind): `github`, `jira`, `bugzilla`, `slack`, `discord`, `gitter`, `irc`,
  `stackoverflow`, `mailing_list`.
- `Venue` — the concrete container *within* a platform (one repository, one
  Jira project, one Slack/Discord/Gitter/IRC channel, one SO site, one mailing
  list). Named `Venue`, **not** `Arena` — "arena" is already a fixed concept in
  RQ6/`REFINED_RQS_v0.2.md` (issue-tracker arena vs mailing-list arena), which
  now maps onto `Platform`.
- `Corpus` — a dataset release (citation, license, version, source URI).
- `Conversation` — a dataset-provided/inferred conversational grouping
  (Slack/Discord conversation IDs, IRC gold conversations, Gitter dialogs),
  distinct from `Venue` (the channel) and the message itself.
- `Artefact` — the shared base label for every text-owning source object, with
  family labels (`IssueArtefact`, `MessageArtefact`, `PostArtefact`,
  `CommitArtefact`) and platform labels (`GitHubIssue`, `JiraIssue`,
  `SlackMessage`, `IRCMessage`, `StackOverflowQuestion`, …) added on top.
  Every `Artefact` carries `record_id` (globally namespaced, = the TextUnit
  parent_id), `platform_id`, `venue_id`, `corpus_id`/`source_corpus`, and
  `artefact_kind`.

**Decisions locked for v0.8:**

1. **Comments stay flattened** — new corpora emit `comment_body` TextUnits
   (position ≥ 2) under the owning issue/post, matching the current GitHub
   convention (see the v0.7 implementation-status note in §4.1). First-class
   `Comment` nodes remain a future enrichment for *all* platforms at once, so
   RQ6 per-artefact statistics stay structurally comparable.
2. **Actors share one `Actor.login`** — external actors get a namespaced login
   `"<platform>:<corpus_short>:<id>"` (Gmane precedent: anonymized senders are
   already stored verbatim as login). No parallel actor hierarchy and no
   cross-platform identity resolution (out of scope).
3. **No `GH_issue:` rename** — existing `issue:{repo}:{number}` /
   `pr:…` / `commit:{sha}` / `email:{urn}` TextUnit IDs stay unchanged; they are
   embedded in `Signal.id`, verdict keys, and projector MATCH clauses.
   Comparability comes from the `:Artefact` label + `platform_id`, not from ID
   prefixes. Existing nodes are relabelled by `scripts/migrate_v0.8.cypher`.
4. **Corpus membership is a property, not an edge** — `source_corpus` on every
   artefact (indexed) plus coarse `(Corpus)-[:COVERS]->(Venue)` edges. No
   per-record `CONTAINS` edges (Alternative Jira alone is ~11.7M records).
5. **Dynamic labels via APOC** — `apoc.create.addLabels` applies the family +
   platform label sets (APOC is enabled in docker-compose).

| Node | Natural key | Key properties |
| --- | --- | --- |
| `Platform` | `platform_id` | `name`, `kind` |
| `Venue` | `venue_id` | `platform_id`, `corpus_id`, `external_id`, `name` |
| `Corpus` | `corpus_id` | `name`, `version`, `citation`, `license`, `source_uri` |
| `Conversation` | `conversation_id` | `platform_id`, `venue_id`, `corpus_id`, `source_label` |
| `Artefact` | `record_id` | `platform_id`, `venue_id`, `corpus_id`, `artefact_kind`, `created_at`, `metadata_json` |
| `JiraIssue` / `BugzillaIssue` | `record_id` | `external_id`, `state`, `created_at`, platform/corpus props |
| `ChatMessage` | `record_id` | `channel`, `sequence`, `sent_at`, platform/corpus props |
| `StackOverflowPost` | `record_id` | `post_type` (`question`/`answer`/`comment`), `external_id` |

Edges (v0.8 additions):

```
(Platform)-[:HAS_VENUE]->(Venue)
(Corpus)-[:COVERS]->(Venue)
(Venue)-[:CONTAINS]->(Artefact)          // CONTAINS stays container-only
(Venue)-[:HAS_CONVERSATION]->(Conversation)
(Conversation)-[:CONTAINS]->(ChatMessage)
(Actor)-[:AUTHORED]->(Artefact)          // namespaced Actor.login
(Artefact)-[:HAS_TEXT {role}]->(TextUnit)
(MessageArtefact)-[:REPLIES_TO]->(MessageArtefact)   // IRC gold links, curated-email threading
(StackOverflowAnswer)-[:ANSWERS]->(StackOverflowQuestion)  // only when source provides it
```

`record_id` conventions (also the TextUnit parent_id):

```
jira_issue:apachejira:HBASE-1234        bugzilla_issue:bugsrepo:12345
chat_message:preethac-slack:<team>:<channel>:<year>:<n>
chat_message:disco:<team>:<channel>:<period>:<n>
chat_message:gittercom:<room>:<msg_id>   chat_message:livechat-gitter:<room>:<n>:<sha1>
chat_message:kummerfeld-irc:<split>:<file>:<ordinal>
so_post:so-emotion-gold:<n>              email:curatedemail:<project>:<id>
```

The full DDL, MERGE templates, and sanity queries are in `ontology/ontology.cypher`
§3.14/§4.6–4.9; the machine-readable summary is `ontology/schema.yml`
(`multiplatform_corpus_layer`). This extension was justified against
FRAMEWORK_DESIGN §2 (RQ6 cross-arena comparison) and the dataset papers in
§12 — see AGENTS.md §5.6 (do not extend the ontology unilaterally).

---

## 5. Module outlines

Below: purpose, inputs, outputs, and a code sketch for each module. Sketches are
illustrative, not runnable scaffolds.

### Module 1 — `AsyncGitHubMiner` (existing)

Keep as-is. Two minor integration adjustments:

1. In `_save_and_publish`, add `"content_sha256"` to the `_meta` block (cheap, lets
   downstream dedupe).
2. In the published event, include `item_subtype` for PRs vs plain issues so the
   TextUnitExtractor can branch without a Mongo read when it doesn't need to.

Everything else — rate limiting, pagination, 403 handling — stays.

### Module 2 — `TextUnitExtractor`

**Purpose.** Consume `stream_raw`, fetch the full document from Mongo, split it into
`TextUnit`s with provenance, emit one event per unit on `stream_units`.

**Key decision: granularity.** Start with **one `TextUnit` per (artefact, role)** —
i.e., a whole issue body is one unit. This is coarse but keeps the first pass tractable.
Expose granularity as a CLI flag; revisit after the first analytical pass (you may
want sentence-level for RQ2 co-occurrence work).

```python
# modules/text_unit_extractor.py  (sketch)

@dataclass
class TextUnit:
    parent_id: str         # e.g. "issue:<repo>:<number>"
    role: str              # "title" | "body" | "commit_message" | "comment_body"
    position: int          # 0 for title, 1 for body, 2+ for comments in order
    text: str
    lang: str              # langdetect or None
    author_login: Optional[str]
    created_at: Optional[str]

def extract_from_issue(doc: dict) -> list[TextUnit]:
    units = []
    units.append(TextUnit(..., role="title", position=0, text=doc["title"], ...))
    if doc.get("body"):
        units.append(TextUnit(..., role="body", position=1, text=doc["body"], ...))
    for i, c in enumerate(doc.get("comments_data", []), start=2):
        units.append(TextUnit(..., role="comment_body", position=i, text=c["body"], ...))
    return units
```

Parallel `extract_from_pr`, `extract_from_commit` (commit → one unit from message).

**What to strip.** Collapse `>` quoted replies, strip GitHub-flavoured-Markdown artefacts
(backticked code blocks, image tags), strip `@mentions`. Keep everything else verbatim —
including typos, which matter for RQ1/RQ2.

**Language filter.** Use `fasttext-langdetect` (small, fast). Non-English units are
still persisted but get `lang != "en"`; English-only filtering happens at query time,
not at ingest.

### Module 3 — Annotators

A common interface; five implementations.

```python
# modules/annotators/base.py

@dataclass
class Signal:
    layer: str
    category: str
    subcategory: Optional[str]
    surface_form: str
    span_start: int
    span_end: int
    rule_id: str
    rule_version: str
    confidence: Optional[float] = None
    payload: dict = field(default_factory=dict)  # for layer-specific extras

class Annotator(Protocol):
    name: str
    version: str
    def annotate(self, unit: TextUnit) -> list[Signal]: ...
```

> **Implemented signature (v0.5+):** `annotate(self, unit: TextUnit, doc: Doc)`
> — the shared spaCy `Doc` is parsed once per batch by the orchestrator and
> handed in, avoiding one parse per annotator. The `Signal` dataclass in
> `annotators/base.py` additionally carries `weight: float` and
> `status: str` (see §1.2/§4.2).

The fan-out is **one worker process for all annotators** (single shared
`nlp.pipe` + classifier batch per TextUnit page, then each annotator's matchers
run over the same `Doc`). The worker reads TextUnits **from Neo4j** (see §3)
and writes all Signals to `stream_signals`. A signal carries `text_unit_id` in
its envelope (not shown above) so the projector can reassemble.

#### 3a. Morpho-syntactic annotator (`SpacyMorphoAnnotator`)

**Backbone.** spaCy `en_core_web_md` by default (see §9 open decision 3) with the
parser **enabled** and NER disabled — the v0.2 scope rules need `token.dep_`/`token.head`.
Use Matcher for bare cues and DependencyMatcher for scoped constructions.

Rule families (stored in `patterns/morpho_syntactic_v0.2.yml`, resolved via
`settings.pattern_set_version`, not in code):
- **Tense**: detect `VERB` with morph `Tense=Past|Pres` in the scope of an NK-lexeme.
- **Modality**: sense-underspecified after MARKER_REVIEW C-1 — `may`/`might` as
  high-confidence epistemic; `can/could/would` moved to `modality/underspecified`
  (low weight) instead of asserting sense by lemma; epistemic `will` added.
- **Hedging**: shield adverbs (`perhaps`, `possibly`, `probably`, `arguably`, ...),
  approximators, and the new epistemic/shield families (M-2).
- **Epistemic verbs** (M-1): negated/interrogative first-person cognition verbs
  — the flagship DependencyMatcher construction (`I don't know`, `can't tell`...).
- **Negation**: scoped by dependency — a negation Signal is NK-relevant only when it
  governs/attaches to an epistemic target (C-3); bare negation is a low-weight modifier.
- **Evidentials** (M-3): inferential (`seem`, `appear`, `suggest`) vs reportative.
- **Syntactic patterns**: DependencyMatcher for
  - question-answer pairs (a `?`-terminated sentence followed within the same TextUnit
    by a declarative),
  - embedded questions (`whether`, `if…or`, `I wonder…`), tag questions (M-4),
  - adversative: coordination via `however`, `although`, `though` (`but` demoted, C-9).

Each match produces one `Signal`. The rule id is the YAML key, so `rule_id="morph.neg.bare_negation"`.

#### 3b. Word-formation annotator (`AffixAnnotator`)

Tiny, purely morphological. For each token:
- Prefix check (`un-`, `in-`, `non-`, `dis-`, `mis-`) with a short allowlist of stems to avoid
  false positives (`income` is not NK).
- Suffix check (`-less`, `-free`) and an **allowlist** of NK-relevant deverbal
  adjectives (`questionable`, `undecidable`, `unknowable`, `unverifiable`, ...) —
  the blanket `-able` scan was removed in v0.2 (MARKER_REVIEW C-2).
- The approach matches against a **stem after stripping** rather than blocklisting
  whole surface strings, so genuine `under-` compounds (`underspecified`,
  `underdocumented`) survive (C-8).

Output: one Signal per hit. `rule_id="affix.prefix.un"`, etc.

The annotator is *deliberately conservative* since v0.2 — the research point is
still to see which affixed forms actually recur in SE discourse, but the v0.1
blanket scans were a systematic FP generator (C-2, C-8).

#### 3c. Lexical marker annotator (`LexiconAnnotator`)

Input: a versioned YAML lexicon (see `lexicons/en_core_v0.2.yml`). Algorithm:
1. Load lexicon, build a PhraseMatcher keyed on lemma (patterns compiled via
   `nlp.pipe` with the parser and NER disabled — lexical matching needs neither).
2. For each match, emit a Signal and a pointer to the `LexicalMarker` node.

**This is the only annotator whose behaviour is fully data-driven.** Adding a marker is
a YAML edit + a re-run; no code changes.

#### 3d. Rhetorical-figure annotator (`RhetoricalAnnotator`)

Input: a pattern registry (see `patterns/rhetorical_v0.2.yml`). Patterns are spaCy
Matcher/DependencyMatcher specs expressed as YAML. A figure has:
- a `family` (metaphor / personification / comparison),
- a `subtype` (`opacity`, `hidden_extent`, `obscurity`, SE-native `black_box`...),
- a list of trigger patterns,
- `status` (most SE-native metaphor families ship as `candidate` pending calibration).

Metaphor detection is the hardest part. We stay with the curated **explicit-metaphor
lexicon** (v0.2 added SE-native families: `black box`, `rabbit hole`, `can of worms`,
`fog`, `iceberg`); statistical metaphor identification (Shutova et al.) remains a
closed decision. The double-count between lexical `opacity` and rhetorical opacity is
deliberate and disclosed at analysis time (REFINED_RQS_v0.2.md RQ3), not collapsed.

#### 3e. NK classifier annotator (`ClassifierAnnotator`)

Wraps your trained RoBERTa checkpoint behind an interface so the backend is swappable:

```python
class NKClassifier(Protocol):
    model_id: str
    model_version: str
    def predict(self, texts: list[str]) -> list[tuple[int, float]]: ...  # (label, conf)
```

**Recommended backend: HuggingFace Transformers + MPS.** On Apple Silicon, moving the
model to `device="mps"` gets you 5–10× speedups over CPU with zero conversion pain.
This is the default path.

```python
class HFTransformersClassifier:
    def __init__(self, path: str):
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path).to("mps").eval()
    def predict(self, texts):
        with torch.no_grad():
            enc = self.tok(texts, padding=True, truncation=True, max_length=512, return_tensors="pt").to("mps")
            logits = self.model(**enc).logits
            probs = logits.softmax(-1)
            return [(int(p.argmax()), float(p.max())) for p in probs]
```

**Optional backend: MLX.** `mlx-lm` targets autoregressive LLMs; a fine-tuned RoBERTa
classifier is better served by `mlx-transformers` (community port). Convert the HF
checkpoint once, load via MLX. Worth it **only if** throughput on MPS becomes a
bottleneck — for a single-researcher pilot on a handful of repos, MPS is plenty.
Keep both behind the `NKClassifier` interface and pick at config time.

Output: one `Signal` *and* one `ClassifierVerdict` per TextUnit.
They are distinct: the Signal is evidence at a span (whole-unit span for the classifier),
the Verdict is the per-unit record used in RQ5 queries.

> **Implementation note (as shipped):** the classifier emits both records as one
> Redis event — a normal `Signal` plus a second record carrying a
> `payload["__verdict__"]` sentinel that the projector strips and routes to
> `ClassifierVerdict`. Because both records share the same span/rule_id, the
> derived `signal_id` collides; the projector must route the verdict *away*
> before creating the Signal node. Keep this dependency explicit.
> The default backend is `HFTransformersClassifier` with `device="mps"`, a
> 512-token truncation cap, and a documented CPU fallback (M6 acceptance). `MLX`
> remains a scaffolded `backend="mlx"` option, NOT enabled by default.

### Module 4 — `GraphProjector`

Consumes `stream_units` (phase 1: SE-artefact + TextUnit nodes) and
`stream_signals` (phase 2: Signal + Verdict nodes), batches, writes to Neo4j.

**Only this module knows the Cypher.** Annotators never *write* to the database
(the annotator worker reads TextUnits but is write-path blind).

Phase 1 writes per-event today (not UNWIND-batched — acceptable at pilot scale; see
BUILD_SPEC §6 M3 note). Phase 2 batches Signals and uses `UNWIND` +
`MERGE … ON CREATE SET` (so re-annotation refreshes `weight`/`status` on existing
nodes). The projector is ~200 lines of Python; the Cypher templates
are in `/ontology/ontology.cypher`.

```python
# Illustrative write pattern (not runnable):
CYPHER_WRITE_SIGNALS = """
UNWIND $signals AS s
MATCH (u:TextUnit {id: s.text_unit_id})
MERGE (sig:Signal {id: s.id})
  ON CREATE SET sig += s.props
MERGE (u)-[:HAS_SIGNAL]->(sig)
"""
```

### Module 5 — Analysis (notebooks + small CLI)

Not a pipeline module; a deliverable. Two analysis notebooks are active
(v0.1 taxonomy not per-RQ notebooks):
- `notebooks/01_descriptive.ipynb` — corpus overview & sanity checks; counts per
  layer, per category, per repo.
- `notebooks/02_rq_analysis.ipynb` — **RQ1–RQ6 analysis** (v0.2 restructure,
  67 cells) implementing `REFINED_RQS_v0.2.md`: lexical profile, cue-vs-scope
  gap (RQ2), rhetorical profile (RQ3), RQ4a–d instrument + coded-sample analysis,
  marker–classifier disagreement + per-rule reliability (RQ5), cross-arena/cross-
  community profiles (RQ6). Loads rules from the same YAML the annotators load.
  (`02_rq_analysis_old.ipynb` is the archived v0.1 version.)
- `notebooks/rq4_*.csv`, `notebooks/rq5_*.csv` — validation artefacts exported by
  the notebook (coding sheets, sample key, dry coding frames, reliability tables).

Analysis notebooks use the `neo4j` Python driver directly (no REST/GraphQL API —
see §8).

---

## 6. RQ → Cypher mapping

Small illustrative queries so you can see the ontology earn its keep.

**RQ1. Top lexical markers in issue titles vs. commit messages.**
```cypher
MATCH (u:TextUnit)-[:HAS_SIGNAL]->(s:Signal {layer:'lexical'})-[:MATCHES_MARKER]->(m:LexicalMarker)
MATCH (:Issue|:PullRequest|:Commit)-[r:HAS_TEXT]->(u)
RETURN r.role, m.lemma, count(*) AS n
ORDER BY n DESC LIMIT 50;
```

**RQ2. Co-occurrence profiles — units where negation + modality + hedging all fire.**
```cypher
MATCH (u:TextUnit)-[:HAS_SIGNAL]->(s1:Signal {category:'negation'})
MATCH (u)-[:HAS_SIGNAL]->(s2:Signal {category:'modality'})
MATCH (u)-[:HAS_SIGNAL]->(s3:Signal {category:'hedging'})
RETURN u.id, u.text LIMIT 100;
```

**RQ3. Metaphor inventory by subtype.**
```cypher
MATCH (u:TextUnit)-[:HAS_SIGNAL]->(s:Signal {layer:'rhetorical', category:'metaphor'})
      -[:INSTANTIATES]->(f:RhetoricalFigure)
RETURN f.subtype, count(*) AS n, collect(DISTINCT s.surface_form)[0..10] AS examples
ORDER BY n DESC;
```

**RQ5. Classifier false negatives — model says 0, ≥2 linguistic layers fire.**
```cypher
MATCH (u:TextUnit)-[:CLASSIFIED_AS]->(v:ClassifierVerdict {label: 0})
MATCH (u)-[:HAS_SIGNAL]->(s:Signal)
WHERE s.layer IN ['lexical','morpho_syntactic','rhetorical']
WITH u, v, count(DISTINCT s.layer) AS layer_count
WHERE layer_count >= 2
RETURN u.id, u.text, v.confidence, layer_count
ORDER BY layer_count DESC, v.confidence DESC
LIMIT 200;
```

The last query *is* RQ5 part (a). The framework is honest to the claim that we want to
find where the classifier breaks.

---

## 7. Directory layout

**The canonical, complete repository layout lives in `AGENTS.md` §9** — it is
the only copy kept in the repo, so it cannot drift. If you move a file, update
that tree, not this document. What this section records instead is the
**module → file mapping** the rest of this design document refers to, so §5's
module outline can be resolved to paths:

| Module (§5)      | File(s)                                                                |
| ---------------- | ---------------------------------------------------------------------- |
| Module 1 miner   | `miner/async_miner.py` (FROZEN), `miner/gmane_ingester.py` (mailing lists) |
| Module 2 extractor | `extractor/text_unit_extractor.py` (incl. `extract_from_email`), `extractor/worker.py` |
| Module 3 annotators | `annotators/base.py` (TextUnit, Signal, Annotator), `annotators/lexical.py` (3c), `annotators/morpho_syntactic.py` (3a), `annotators/word_formation.py` (3b), `annotators/rhetorical.py` (3d), `annotators/classifier.py` (3e), `annotators/worker.py` (orchestrator; reads Neo4j → annotate → publish) |
| Module 4 projector | `projector/graph_projector.py` (phases 0/1/2), `projector/worker.py` |
| Module 5 analysis | `notebooks/01_descriptive.ipynb`, `notebooks/02_rq_analysis.ipynb` (+ `rq4_*.csv`, `rq5_*.csv` validation artefacts) |
| Shared           | `settings.py`, `broker.py`, `progress.py`, `storage.py`, `scripts/*`, `tests/*` |
| Rules content    | `lexicons/*.yml`, `patterns/*.yml`, `rules/categories.yml`, `ontology/*` |

---

## 8. Explicitly out of scope

- Production error handling beyond what the miner already has.
- Horizontal scaling: one machine per researcher is enough.
- Auth or multi-tenancy on any service.
- A REST/GraphQL API over the KG; notebooks + `neo4j` Python driver are enough.
- Code-AST analysis of the repo's source tree. The phenomenon is in *natural language*
  (issues, PRs, commits). Source code may come later, as its own module.
- Multilingual NK. Non-English units are persisted but by default not annotated
  (`settings.annotate_languages = ["en"]`; the filter is configurable at run time).
- Active learning or classifier retraining. RoBERTa is treated as a black box input
  for the first pass; RQ5 *results* will inform whether a retraining round is
  warranted.
- **The OCEAN corpus (`ocean_dataset/`, ~3.6 GB jsonl) is a test corpus, not a
  research input.** It was used for testing and is a candidate for deletion;
  nothing in the pipeline design depends on it.

---

## 9. Open decisions I flagged and need your call on

1. **TextUnit granularity (first pass)**: one per (artefact, role) vs. one per sentence.
   My recommendation: start coarse, revisit. Your call.
   *(Resolved in practice: GitHub = one per (artefact, role); emails = one per
   corpus segment — see §11.2.)*
2. **Metaphor detection depth**: lexicon + patterns (tractable) vs. statistical
   (Shutova-style; much harder). Recommendation: lexicon+patterns in v0; flag units
   that don't match anything but are classified NK for manual metaphor mining.
   *(Resolved: lexicon + patterns, including SE-native families; statistical methods
   remain deferred.)*
3. **spaCy model**: `en_core_web_trf` (better, slower) vs. `en_core_web_md` (default
   since 2026-07). The scope rules need the parser enabled regardless; `lg`/`md`
   differ mainly in vectors, which the token/dependency rules do not use.
   *(Resolved: `en_core_web_md`, `disable=["ner"]`.)*
4. **MLX vs. MPS for the classifier**: MPS for pilot, MLX only if throughput
   becomes painful. The interface (`NKClassifier`) makes this a config change.
   *(Resolved: MPS default; MLX scaffolded but disabled by default.)*
5. **Scope of the pilot corpus**: one large, well-documented repo first
   (e.g., `kubernetes/kubernetes`, `python/cpython`) to validate the pipeline end-to-end,
   then expand. Do not mine 50 repos before the ontology is stable — you will regret it.
   *(Resolved: `python/cpython` is the GitHub pilot; mailing lists scoped per §11.3.)*
6. **How Roberts's taxonomy enters the graph**: I've modelled `IgnoranceType` as a
   post-hoc annotation layer. Alternative: pre-seed Roberts's types as nodes and let
   analysts attach edges manually in a dedicated annotation pass. Both compatible
   with the current ontology; I lean post-hoc to avoid priming the analysis.
   *(Resolved: post-hoc only, operationalised via the RQ4 instrument stack — §4.6.)*
7. **PR–Commit–Issue link extraction**: the `REFERENCES` edge needs a regex pass
   over commit messages and PR bodies (`fixes #123` etc.). Should we do this in the
   TextUnitExtractor or as a separate enrichment step? I suggest: separate step,
   because the regex will evolve.
   *(Resolved: separate enrichment pass — `enrichment/reference_extractor.py`,
   invoked via `run_pipeline.py --enrich`.)*

---

## 10. A minimal "first 10 days" plan (non-binding)

If you want a concrete ordering to get to a first result:

1. **Day 1–2**: stand up Neo4j, apply `ontology.cypher`, run miner on one repo,
   verify MongoDB has raw docs.
2. **Day 3**: implement `TextUnitExtractor` and `GraphProjector` end-to-end,
   producing empty signal sets — i.e., SE-artefact layer only. Write RQ-agnostic
   descriptive queries (counts, authors, comment chains).
3. **Day 4**: implement `LexiconAnnotator` with a 30-entry seed lexicon. First real
   Signals in the graph. Validate with RQ1 queries.
4. **Day 5–6**: `SpacyMorphoAnnotator` for negation + modality. Validate RQ2 queries.
5. **Day 7**: `ClassifierAnnotator` (MPS backend). First RQ5 query runs.
6. **Day 8–9**: `AffixAnnotator` + `RhetoricalAnnotator` v0.
7. **Day 10**: notebook `01_descriptive.ipynb`. First quantitative picture.

From here, everything is iteration on the lexicon, patterns, and rules — never on the
architecture. That is the design's promise.

---

*End of design document.*

---

## 11. Addendum (v0.6): Mailing lists — Webis Gmane Email Corpus 2019

The study scope now includes NK in mailing-list discourse, using the Webis
Gmane Email Corpus 2019 (153M parsed & segmented emails, 14,699 lists).
Design principle: emails are a **third artefact family inside the same
pipeline**, not a parallel system — every downstream component (annotators,
signals, projector phases, scope filters) applies unchanged.

### 11.1 Ontology extension

```
(MailingList {name})─[:CONTAINS]──▶(EmailMessage {urn, message_id, subject,
                                    date, group, list_id, in_reply_to,
                                    references, lang})
(Actor)─[:AUTHORED]──▶(EmailMessage)
(EmailMessage)─[:HAS_TEXT {role}]──▶(TextUnit)      // role = segment label | "subject"
(EmailMessage)─[:REPLIES_TO]──▶(EmailMessage)        // threading (enrichment)
```

- `MailingList` ≅ `Repository`; `EmailMessage` ≅ `Issue`. Keys: `name`
  (Gmane group), `urn` (corpus UUID — unique by construction; `message_id` is
  only indexed, since crawled archives contain missing/duplicated ids).
- **Actors:** the anonymized `from` value becomes the `Actor.login` verbatim.
  Cross-platform identity resolution (email actor ↔ GitHub actor) is
  impossible on anonymized data and explicitly out of scope; per-platform
  actor-level analyses remain valid.
- **Threading:** `in_reply_to`/`references` are stored on the node; the
  enrichment pass draws `REPLIES_TO` edges (parents outside the ingested scope
  simply get none, and are countable). This is the substrate for thread-level
  NK questions (e.g. does articulated uncertainty get resolved downthread?).

### 11.2 TextUnit granularity for emails (amends locked decision v0-1)

Emails use the corpus's pre-computed segments: **one TextUnit per selected
segment** (role = segment label, position = span order; subject = position 0).
Selected labels default to `paragraph`, `section_heading`
(`settings.email_segment_labels`).

**Excluding `quotation` is a methodological requirement, not an optimisation:**
quoted text repeats the *previous* author's words, so any NK signal inside a
quote would be (a) duplicated across every reply in a thread and (b) attributed
to the wrong author. Signatures, patch bodies, logs, raw code, and other
non-prose segments are not authored epistemic discourse and are excluded by
default. The corpus `lang` field is authoritative for all of a message's units
and feeds the annotator's language scope filter directly.

### 11.3 Pipeline integration

`miner/gmane_ingester.py` mirrors the GitHub miner's contract exactly
(save to Mongo `raw_emails` → publish pointer event to `stream_raw` with
`item_type="email"`, `repo_name="gmane:<group>"`). Extractor gains
`extract_from_email`; projector Phase 0 seeds MailingList/Actor/EmailMessage;
Phase 1's parent dispatch gains an `EmailMessage {urn}` branch; `--enrich`
now also runs email threading.

**Scale discipline:** the full corpus is ~4 orders of magnitude beyond the
GitHub pilot. Ingest-time scoping (`--groups` allowlist, `--lang`, `--max`) is
mandatory practice; filters run in the ingester so out-of-scope mail never
enters MongoDB. Recommended first study: a handful of developer lists
(e.g. one language community + one infrastructure project), English only.

### 11.4 New comparative research question

**RQ6 (cross-arena):** Do NK expression profiles (layer mix, marker
distribution, classifier agreement) differ systematically between issue-tracker
discourse and mailing-list discourse for comparable communities? The shared
ontology makes this a single Cypher query family:
`MATCH (u:TextUnit)<-[:HAS_TEXT]-(parent)` and group by `labels(parent)`.

---

## 12. Addendum (v0.7): Curated MSR datasets corpus (external drive)

Alongside the GitHub-issue and mailing-list corpora, the study scope now
includes a third corpus: **curated, peer-reviewed MSR datasets** — research-grade
gold corpora (issue trackers, code-review emails, chat/disentanglement datasets,
emotion gold standards, etc.) published together with MSR papers. These are
research inputs for validation/analysis, distinct from the disposable
`ocean_dataset/` test corpus (§8).

**Locations**

- **Datasets:** `/Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets` (external
  drive; 13 datasets currently, more may be added).
- **Companion papers:** `dataset_papers/` in the repo root — one PDF per dataset.

**Dataset → paper index**

| Dataset (in `Graph_NK_datasets/`) | Paper (in `dataset_papers/`) |
| --- | --- |
| `apache_jira_dataset` | `MSR2023JiraIssuesDataset.pdf` |
| `TheAlternativeJiraDataset` | `MSR22_alternativejiraissuedataset.pdf` |
| `BugsRepo_Comments` | `BugsRepo_paper.pdf` |
| `Curated Email-Based Code Reviews Datasets` | `Liang2024_curatedEmailCodeReview.pdf` |
| `DISCO-A Dataset of Discord Chat Conversations for Software Engineering Research` | `MuthuSubash_MSR2022_Disco.pdf` |
| `Emotions_GoldSandard_andAnnotation.xlsx` | `Novielli2018SOEmotionsGoldStandard.pdf` |
| `Kummerfeld_UbuntuIRC_dataset` | `Kummerfeld2019UbuntuIRC.pdf` |
| `LiveChatGitter_dataset` | `Shi2021_LiveChatGitter.pdf` |
| `raw_gittercom_dataset` | `GitterCom_-_A_Dataset_of_Open_Source_Developer_Communications_in_Gitter.pdf` |
| `NumFocus_dataset` | `A_Dataset_of_Contributor_Activities_in_the_NumFocus_Open-Source_Community.pdf` |
| `ocean_dataset` | `Warrick2022_OCEAN_paper.pdf` |
| `OpenMent-dataset` | `OpenMent_A_Dataset_of_Mentor-Mentee_Interactions_in_Google_Summer_of_Code.pdf` |
| `preethac_SlackDisentangled_dataset` | `—` *(see provenance note below; README attributes it to Chaterjee, Damevski, Kraft & Pollock, "Software-related Slack Chats with Disentangled Conversations", submitted)* |
| `SOTorrent` | `SOTorrent_2018_Baltes.pdf` |

> **Retired from study scope (2026-08-31).** Two datasets in the table above
> were considered and are now **excluded** from the study corpus
> (CHANGELOG 2026-08-31; the ingesters remain but are unused):
>
> - **BugsRepo (`BugsRepo_Comments`)** — the distributed dataset consists
>   primarily of *links* to Bugzilla bugs, not the bug texts themselves;
>   reconstructing a usable text corpus would require manual harvesting that
>   diverges from the peer-reviewed data source and the study goal.
> - **SO emotion gold (`Emotions_GoldSandard_andAnnotation.xlsx`,
>   `so-emotion-gold`)** — too small for the corpus-scale design, and data
>   inconsistencies (no post ids; synthetic record identity) made it unfit as
>   a first-class corpus.
>
> The corpus registry (`scripts/corpus_census.py`) and the v0.3 RQ scope
> (`REFINED_RQS_v0.3.md` §2) reflect this exclusion.

> **Provenance correction (v0.8, GRD-NK §4.7):** the earlier index mapped
> `preethac_SlackDisentangled_dataset` to `Gouravajhala_2023_ChatDisentanglement.pdf`.
> On-disk evidence contradicts that: the dataset's `README.md` attributes the
> corpus to Chaterjee/Damevski/Kraft/Pollock; the 12 XML files under `data/**`
> are **Slack** conversations (collected via the Slack API, see
> `scripts/slack/`), whereas the Gouravajhala 2023 paper describes a **new-domain
> IRC** dataset. That new-domain IRC data (rust/stripe/mediawiki/ubuntu-meeting)
> is actually bundled inside `Kummerfeld_UbuntuIRC_dataset/data/new-domains/`
> (the Kummerfeld repo extends the shared annotation format). Both are ingested
> where their text lives: the Slack XML via `miner/slack_ingester.py`; the
> new-domain IRC via `miner/irc_ingester.py`. The `Gouravajhala_2023...pdf`
> paper-file therefore belongs with the `new-domains/` subset of the Kummerfeld
> dataset, not with the Slack folder. The Slack citation is marked *unverified*
> until the original download is confirmed.
