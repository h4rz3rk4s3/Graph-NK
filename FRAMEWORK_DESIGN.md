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
- provenance (rule id, lexicon version, model id+version, confidence where applicable).

Signals are never overwritten, never collapsed. The RoBERTa classifier is *one* signal
source. Taxonomic labels (Roberts, etc.) are assigned *over* signals, by analysts or
downstream clustering — never at ingest.

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

Your original three RQs, reorganised along the four linguistic layers in your brief
plus a model-comparison axis. Each is pinned to specific features from
Janich & Simmerling's overview.

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

**RQ4 — Taxonomic.**
When the signals from RQ1–RQ3 are projected into a feature space and clustered
(or analysed qualitatively from the graph), do the resulting types align with
Roberts's *Organizational Ignorance* taxonomy or related classifications
(Smithson; Gross; Kerwin)? **Where do they break down when confronted with
SE artefacts?** Concretely: what forms of NK in SE (e.g., "works on my machine",
deferred-decision backlog, deliberately underspecified interfaces) are
under-theorised by the borrowed taxonomies?
*(This is your paper's main theoretical contribution.)*

**RQ5 — Model vs. linguistic evidence.**
Where does the RoBERTa classifier's verdict diverge from the rule-based linguistic
evidence? Classify the disagreements into:
- (a) **false negatives of the model** — text with ≥ *k* independent linguistic signals
  but classifier label 0;
- (b) **false positives of the model** — classifier label 1 but no linguistic signal fires;
- (c) **genuine ambiguity** — low classifier confidence *and* conflicting signals.
What do (a) and (b) reveal about the limits of supervised NK detection? What does
(c) reveal about under-theorised NK forms?

RQ5 is the reason `Signal` and `ClassifierVerdict` must both live in the graph and be
queryable side-by-side.

---

## 3. Pipeline architecture

Your existing miner already establishes a **Producer → Broker (Redis Stream) → Consumer**
pattern with MongoDB as the data lake. We extend that same pattern — no new infra.

```
┌──────────────────────┐   stream_raw   ┌──────────────────────┐
│  AsyncGitHubMiner    │ ─────────────▶ │ TextUnitExtractor    │  (Module 2)
│  (existing)          │                └──────────┬───────────┘
└──────────────────────┘                           │ stream_units
          │  writes raw JSON                       ▼
          ▼                              ┌──────────────────────┐
     ┌──────────┐                        │  Annotator fan-out   │  (Module 3)
     │ MongoDB  │◀────reads full doc─────│  3a morpho-syntactic │
     │ raw_*    │                        │  3b word-formation   │
     └──────────┘                        │  3c lexical markers  │
                                         │  3d rhetorical figs  │
                                         │  3e NK classifier    │
                                         └──────────┬───────────┘
                                                    │ stream_signals
                                                    ▼
                                         ┌──────────────────────┐
                                         │  GraphProjector      │  (Module 4)
                                         │  writes Cypher       │
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
- **Why fan out the annotators?** Because their computational profiles differ by orders
  of magnitude (lexicon lookup: microseconds; RoBERTa inference: ~10ms/text on MPS;
  dependency parse: ~1ms/sentence with spaCy). Fanning out lets each scale
  independently and makes adding a sixth annotator (e.g., sentiment) zero-risk.
- **Why a dedicated GraphProjector?** So Cypher writes are the *only* place that knows
  the ontology. Annotators emit Signals in a neutral JSON schema; the projector decides
  how they become nodes+edges. If you revise the ontology, only the projector changes.

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

Edges:
- `(Repository)-[:CONTAINS]->(Issue|PullRequest|Commit)`
- `(Actor)-[:AUTHORED]->(Issue|PullRequest|Commit|Comment)`
- `(Issue|PullRequest)-[:HAS_COMMENT]->(Comment)`
- `(Issue|PullRequest|Commit|Comment)-[:HAS_TEXT {role}]->(TextUnit)` — `role` ∈ {title, body, commit_message, comment_body}
- `(PullRequest)-[:REFERENCES {mechanism}]->(Issue)` — extracted from `fixes #123`, `closes #123`, `refs #123`
- `(PullRequest)-[:TOUCHES]->(Commit)` — if you add PR→commit fetching later

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
| `Signal`              | `(text_unit_id, rule_id, span_start)`    | `layer`, `category`, `subcategory`, `surface_form`, `span_start`, `span_end`, `rule_id`, `rule_version`, `confidence?`             |
| `LexicalMarker`       | `(lemma, lexicon_version)`               | `pos`, `category`, `subcategory`, `polarity`, `source_citation`                                                                    |
| `RhetoricalFigure`    | `figure_id`                              | `family` ∈ {metaphor, personification, hyperbole, comparison, irony}, `description`, `source_citation`                             |
| `ClassifierVerdict`   | `(text_unit_id, model_id, model_version)`| `label` ∈ {0,1}, `confidence`, `predicted_at`                                                                                      |
| `IgnoranceType`       | `type_id`                                | `name`, `definition`, `source` (e.g., "Roberts 2013"), `scope` ∈ {imported, derived}                                               |

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

| `layer`            | `category`              | `subcategory` examples                                     | cited source                          |
| ------------------ | ----------------------- | ---------------------------------------------------------- | ------------------------------------- |
| `morpho_syntactic` | `tense`                 | `past_nk`, `present_nk`, `future_nk`                       | Janich 2020                           |
| `morpho_syntactic` | `modality`              | `epistemic_can`, `deontic_must`, `quasi_modal_seem`        | Hyland 1998; Vold 2006                |
| `morpho_syntactic` | `hedging`               | `adverbial` (perhaps, possibly), `approximator` (kind of)  | Szarvas et al. 2012                   |
| `morpho_syntactic` | `negation`              | `adverbial_not`, `quantifier_no`, `temporal_never`         | Vincze et al. 2008; Helmer et al. 2016 |
| `morpho_syntactic` | `syntactic_pattern`     | `question_answer`, `adversative`                           | Bongelli et al. 2018; Simon 2020      |
| `word_formation`   | `affix_negation`        | `un_prefix`, `in_prefix`, `less_suffix`                    | Janich & Simmerling 2013              |
| `word_formation`   | `affix_modality`        | `able_suffix`                                              | Janich & Simmerling 2013              |
| `lexical`          | `prototype`             | `epistemic_state`, `error_or_failure`, `controversy`       | Janich & Simon 2017                   |
| `lexical`          | `fixed_phrase`          | `visibility_phrase` (blind spot), `gap_phrase`             | Simmerling & Janich 2015              |
| `lexical`          | `shared_feature`        | `lack_of_X`, `unresolved_X`                                | Müller & Stegmüller 2019              |
| `rhetorical`       | `metaphor`              | `spatial_journey`, `visibility`, `container`               | Simmerling & Janich 2015              |
| `rhetorical`       | `personification`       |                                                            | Simmerling & Janich 2015              |
| `rhetorical`       | `comparison`            | `kind_of`, `sort_of`                                       | Simmerling & Janich 2015              |
| `classifier`       | `roberta_binary`        | —                                                          | your model                            |

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

The fan-out is simple: one worker process per annotator, all reading `stream_units`,
all writing `stream_signals`. A signal carries `text_unit_id` in its envelope (not shown
above) so the projector can reassemble.

#### 3a. Morpho-syntactic annotator (`SpacyMorphoAnnotator`)

**Backbone.** spaCy `en_core_web_trf` (transformer) or `en_core_web_lg` (faster).
Use Matcher/DependencyMatcher for patterns.

Rule families (stored in `rules/morpho_syntactic.yml`, not in code):
- **Tense**: detect `VERB` with morph `Tense=Past|Pres` in the scope of an NK-lexeme.
- **Modality**: `MD` tokens (can, could, may, might, must, should, would) and
  quasi-modal verbs (`seem`, `appear`) when governing an NK-lexeme or a negated clause.
- **Hedging**: adverb list (`perhaps`, `possibly`, `probably`, `arguably`, ...) —
  simple lexical check done here rather than in the lexical annotator because it
  needs POS confirmation.
- **Negation**: `neg` dependency, plus quantifier `no` and adverb `never` — track
  scope via dependency tree.
- **Syntactic patterns**: DependencyMatcher for
  - question-answer pairs (a `?`-terminated sentence followed within the same TextUnit
    by a declarative),
  - adversative: coordination via `but`, `however`, `although`.

Each match produces one `Signal`. The rule id is the YAML key, so `rule_id="morph.neg.adverbial_not"`.

#### 3b. Word-formation annotator (`AffixAnnotator`)

Tiny, purely morphological. For each token:
- Prefix check (`un-`, `in-`, `non-`, `dis-`) with a short allowlist of stems to avoid
  false positives (`income` is not NK).
- Suffix check (`-less`, `-able`).

Output: one Signal per hit. `rule_id="affix.prefix.un"`, etc.

This annotator is *deliberately noisy* at first — the research point is to see which
affixed forms actually recur in SE discourse. Refinement happens after the first
descriptive pass.

#### 3c. Lexical marker annotator (`LexiconAnnotator`)

Input: a versioned YAML lexicon (see `lexicons/en_core_v0.1.yml`). Algorithm:
1. Load lexicon, build a PhraseMatcher keyed on lemma.
2. For each match, emit a Signal and a pointer to the `LexicalMarker` node.

**This is the only annotator whose behaviour is fully data-driven.** Adding a marker is
a YAML edit + a re-run; no code changes.

#### 3d. Rhetorical-figure annotator (`RhetoricalAnnotator`)

Input: a pattern registry (see `patterns/rhetorical_v0.1.yml`). Patterns are spaCy
Matcher/DependencyMatcher specs expressed as YAML. A figure has:
- a `family` (metaphor / personification / hyperbole / comparison),
- a `subtype` (`spatial_journey`, `visibility`, ...),
- a list of trigger patterns,
- optional context constraints (POS, dependency).

Metaphor detection is the hardest part. Do not overreach: start with a curated
**explicit-metaphor lexicon** drawn from Simmerling & Janich (2015) and the SE pilot
corpus. Move to statistical metaphor identification (Shutova et al.) only after the
lexicon-based pass is exhausted. This is a research choice we should revisit once we
see first results.

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

### Module 4 — `GraphProjector`

Consumes `stream_signals`, batches by `text_unit_id`, writes to Neo4j.

**Only this module knows the Cypher.** Annotators never touch the DB.

Strategy: for each batch, assemble parameterised `MERGE` statements. Use `UNWIND` to
write many signals at once. The projector is ~200 lines of Python; the Cypher templates
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

Not a pipeline module; a deliverable. Structure:
- `notebooks/01_descriptive.ipynb` — counts per layer, per category, per repo.
- `notebooks/02_rq1_lexical.ipynb` — marker frequencies, collocations (PMI from graph).
- `notebooks/03_rq2_morphosyntactic.ipynb` — co-occurrence profiles; heatmaps.
- `notebooks/04_rq3_rhetorical.ipynb` — metaphor inventory; stance per artefact type.
- `notebooks/05_rq4_taxonomy.ipynb` — clustering; Roberts-fit analysis.
- `notebooks/06_rq5_model_vs_linguistic.ipynb` — disagreement cases.

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

```
graphrag_nk/
├── FRAMEWORK_DESIGN.md          # this document
├── settings.py                  # (existing) config
├── broker.py                    # (existing) Redis stream wrapper
├── miner/
│   └── async_miner.py           # (existing) Module 1
├── extractor/
│   └── text_unit_extractor.py   # Module 2
├── annotators/
│   ├── base.py                  # Annotator, Signal
│   ├── morpho_syntactic.py      # 3a
│   ├── word_formation.py        # 3b
│   ├── lexical.py               # 3c
│   ├── rhetorical.py            # 3d
│   └── classifier.py            # 3e (HF/MLX backends)
├── projector/
│   └── graph_projector.py       # Module 4
├── ontology/
│   ├── schema.yml               # the source-of-truth ontology spec
│   └── ontology.cypher          # constraints + MERGE templates
├── lexicons/
│   └── en_core_v0.1.yml         # NK lexicon
├── patterns/
│   ├── morpho_syntactic_v0.1.yml
│   └── rhetorical_v0.1.yml
├── rules/
│   └── categories.yml           # maps rule_id → (layer, category, subcategory, source)
├── notebooks/
│   ├── 01_descriptive.ipynb
│   ├── 02_rq1_lexical.ipynb
│   ├── ...
└── tests/
    └── test_annotators.py       # minimal: one golden example per rule
```

---

## 8. Explicitly out of scope

- Production error handling beyond what the miner already has.
- Horizontal scaling: one machine per researcher is enough.
- Auth or multi-tenancy on any service.
- A REST/GraphQL API over the KG; notebooks + `neo4j` Python driver are enough.
- Code-AST analysis of the repo's source tree. The phenomenon is in *natural language*
  (issues, PRs, commits). Source code may come later, as its own module.
- Multilingual NK. Non-English units are persisted but not annotated in v0.
- Active learning or classifier retraining. RoBERTa is treated as a black box input
  for the first pass; RQ5 *results* will inform whether a retraining round is
  warranted.

---

## 9. Open decisions I flagged and need your call on

1. **TextUnit granularity (first pass)**: one per (artefact, role) vs. one per sentence.
   My recommendation: start coarse, revisit. Your call.
2. **Metaphor detection depth**: lexicon + patterns (tractable) vs. statistical
   (Shutova-style; much harder). Recommendation: lexicon+patterns in v0; flag units
   that don't match anything but are classified NK for manual metaphor mining.
3. **spaCy model**: `en_core_web_trf` (better, slower) vs. `en_core_web_lg` (fine,
   fast). For a pilot across a few repos, `lg` is enough.
4. **MLX vs. MPS for the classifier**: MPS for pilot, MLX only if throughput
   becomes painful. The interface (`NKClassifier`) makes this a config change.
5. **Scope of the pilot corpus**: one large, well-documented repo first
   (e.g., `kubernetes/kubernetes`, `python/cpython`) to validate the pipeline end-to-end,
   then expand. Do not mine 50 repos before the ontology is stable — you will regret it.
6. **How Roberts's taxonomy enters the graph**: I've modelled `IgnoranceType` as a
   post-hoc annotation layer. Alternative: pre-seed Roberts's types as nodes and let
   analysts attach edges manually in a dedicated annotation pass. Both compatible
   with the current ontology; I lean post-hoc to avoid priming the analysis.
7. **PR–Commit–Issue link extraction**: the `REFERENCES` edge needs a regex pass
   over commit messages and PR bodies (`fixes #123` etc.). Should we do this in the
   TextUnitExtractor or as a separate enrichment step? I suggest: separate step,
   because the regex will evolve.

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
