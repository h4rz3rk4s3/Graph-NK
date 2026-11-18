# CODING_MANUAL_v0.3.md

**Companion to:** `ignorance_codebook_v0.1.yml`, `TAXONOMY_CROSSWALK.md`,
`REFINED_RQS_v0.3.md`
**Purpose:** the deterministic coding instrument for RQ4. Given one text unit
from SE discourse (a Jira/Bugzilla comment, a review email, a chat message, a
Stack Overflow post, an OpenMent issue comment — this manual does not see, and
was not written with reference to, any such unit), two independent coders
applying this procedure should reach the same code.

**Supersedes:** `CODING_MANUAL.md` (v0.1). The decision tree is unchanged in
substance; this revision (a) renumbers the RQ references to the v0.3 numbering,
(b) adds the genre-stratified sampling and parent-chain context requirements the
new corpus makes possible, and (c) adds the multi-actor scoring flag for RQ4c.

> **v0.3.1 restructure (2026-09-19).** The hand-coded taxonomy instrument in
> §§1–9 (28-category decision tree, multi-fit pass, multi-actor flag, P1–P6) is
> **deferred to a companion study** (see `REFINED_RQS_v0.3.md` §6). **Section 10
> below is the active coding instrument** for the independent qualitative
> Sub-RQ 4 (communicative functions, epistemic referents, conversational
> trajectories). Predictions P1–P6 are recorded but **not tested** in this
> paper.

**Standing constraint this manual observes:** every code below is imported
unchanged from Roberts (2013), Smithson (1989/1993), Gross (2010), or Wehling
(2024). Nothing here has been invented, broadened, or reworded to make SE text
easier to classify. Where applying an unmodified category to a hypothetical
SE-like sentence would be awkward, that awkwardness is preserved, not smoothed
over — it is the finding, not a defect in the instrument.

---

## 1. What this manual is for, and what it is not for

This manual answers: **given one text unit, which single code (or explicit
non-fit code) does it receive?**

It does **not**:
- adjudicate which of the four taxonomies is theoretically "better";
- resolve the terminological collisions documented in `TAXONOMY_CROSSWALK.md`
  by inventing a merged concept (`NONE_POSSIBLE` pairs are ties broken by
  taxonomy priority — §3 below — never an invitation to average two
  definitions);
- allow "fit" to be adjusted after seeing how well a category performs on the
  actual corpus.

It **also** does not, in v0.3:
- decide whether multi-actor non-knowledge is "really" one taxonomy category or
  another. RQ4c is a claim about what the four taxonomies **lack**, so the
  multi-actor flag (§5.5) is scored on top of, never instead of, the primary
  code — including when the primary code is RESIDUAL.

## 2. Unit of analysis

Code one **text unit** at a time, as handed down from the pipeline. In v0.3 the
units come from four genres — task tracking, review email, synchronous chat,
public Q&A — plus the OpenMent role dataset. **The unit boundary and the genre
label are given from upstream and taken as fixed.** The coder never re-derives
which genre a unit belongs to; the genre label travels with the unit so that
coverage claims stay genre-conditional (RQ4a).

Where the coder is given **parent-chain context** (§5.5), the unit under code
remains the single target unit; the context is read only to determine the
*multi-actor* flag and to inform the RESIDUAL note, never to loosen or tighten
the primary-code decision.

## 3. Taxonomy priority order (fixed, pre-registered, not data-driven)

Unchanged from v0.1. Priority is fixed by definitional specificity and
confidence established from the source literature *before any corpus contact*:

1. **Roberts (2013)** — highest. Most operationally concrete, high/medium
   confidence throughout, explicit boundary conditions in Table 1.
2. **Wehling (2024)** — second. Dimensional rather than categorical; applied
   only after a Roberts category has been ruled out.
3. **Smithson (1989/1993)** — third. Broad hierarchy; several leaves rest on
   medium/low-confidence secondary reconstruction.
4. **Gross (2010)** — lowest. All categories reconstructed from secondary
   paraphrase with `definition_confidence: low` or `medium`; used only when no
   higher-priority taxonomy offers ANY plausible code.

This order is not a claim about theoretical correctness; it is a pre-registered,
evidentiary tie-break. A separate tag records which taxonomy produced the code
so downstream analysis can ask "how many units got a Gross code only because
nothing else fit".

## 4. The decision procedure

Apply the following ordered checks to one text unit. Stop at the first step
that yields a code. This is a decision *tree*, not a checklist.

```
STEP 0 — Is the unit codable at all?
  Is the unit a genuine expression, marker, or negotiation of a gap in knowledge
  — someone's not-knowing, not-being-sure, or not-being-able-to-know something —
  as opposed to a gap-free statement?
    NO  → code UNCODABLE if not interpretable at all (garbled, bot-generated
          hash, code-only diff) — see §5.2.
    NO  → code NOT_NK if interpretable and clearly about something else (a
          technical fact, an agreement, a greeting) — see §5.2.
    YES → continue to STEP 1.

STEP 1 — Check Roberts (2013), in this fixed sub-order:
  1a. roberts.unknown_unknowns   — retrospective-only gap, unnameable in advance?
  1b. roberts.known_unknowns     — a specific, named, actor-aware gap?
  1c. roberts.knowable_known_unknowns — named gap + explicit resource framing?
  1d. roberts.unknown_knowns     — knowledge that existed but was unrecognized?
  1e. roberts.errors             — a confidently held, specific belief shown
                                    wrong (NOT mere absence — see disambiguation
                                    note below)?
  1f. roberts.taboos             — externally/socially/organizationally
                                    prohibited topic?
  1g. roberts.denials            — psychologically motivated rejection of
                                    available conflicting information?
  1h. roberts.secrecy            — unilateral, strategic withholding by an
                                    identifiable party?
  1i. roberts.privacy            — sanctioned right to withhold information
                                    about oneself?
    A code applies here?  → ASSIGN IT. Record taxonomy = roberts_2013. Stop.
    None apply?           → continue to STEP 2.

STEP 2 — Check Wehling (2024) dimensions.
  Dimensional, not categorical: a unit is placed on THREE independent axes
  simultaneously (all three MUST be scored if this step is reached):
    2a. wehling.knowledge_of_nonknowledge — known-unknown / unknown-unknown /
        intermediate pole?
    2b. wehling.intentionality             — unintended / partly-attributable /
        deliberately produced?
    2c. wehling.temporal_durability        — temporary not-yet-knowing /
        principled inability-to-know / intermediate?
  Record taxonomy = wehling_2024 plus all three axis positions. Stop.
  (Reached only if STEP 1 produced no code.)

STEP 3 — Check Smithson (1989/1993) leaves, in this fixed sub-order:
  3a. smithson.confusion       — one specific thing mistaken for a categorically
                                  different one?
  3b. smithson.inaccuracy      — a quantity off in magnitude, right referent?
  3c. smithson.absence         — information wholly missing on an identifiable
                                  question?
  3d. smithson.probability     — likelihood/chance framing (LOW CONFIDENCE —
                                  use cautiously)?
  3e. smithson.vagueness       — continuous-dimension interval/range given?
  3f. smithson.ambiguity       — multiple discrete readings, none privileged?
  3g. smithson.untopicality    — topic passed over as not germane?
  3h. smithson.taboo           — forbidden topic (should be RARE given 1f; if it
                                  happens, flag for review, see §6)?
  3i. smithson.undecidability  — question framed as unresolvable IN PRINCIPLE?
    A leaf applies?  → ASSIGN IT. Record taxonomy = smithson_1989. Stop.
    None apply, but clearly passive/non-actively-chosen ignorance?
       → code smithson.error (branch-level fallback). Stop.
    None apply, but clearly active exclusion/avoidance with no leaf fitting?
       → code smithson.irrelevance (branch-level fallback). Stop.
    Neither branch fits?  → continue to STEP 4.

STEP 4 — Check Gross (2010), in this fixed sub-order. Reaching here should be
  RARE (near-synonymy with Roberts/Wehling); its frequency is P5.
    4a. gross.nescience           — retrospective-only, unnameable-in-advance
                                    gap framed around a SURPRISE event?
    4b. gross.surprise            — the triggering unexpected event itself?
    4c. gross.non_knowledge       — named, resolvable-in-principle gap, framed
                                    as investigable?
    4d. gross.negative_knowledge  — explicit claim about the boundary of
                                    knowability?
    4e. gross.ignorance           — conscious awareness of not-knowing, nothing
                                    more specific (coarsest fallback; double-
                                    check Steps 1–3 before using)?
    A code applies?  → ASSIGN IT. Record taxonomy = gross_2010. Stop.
    None apply?  → continue to STEP 5.

STEP 5 — RESIDUAL.
  The unit is genuine non-knowledge (Step 0 passed) but no category in any of
  the four taxonomies fits — even approximately. Code RESIDUAL. Required
  free-text note (§5.3). This is the primary evidence category for RQ4a/RQ4c.
```

### Disambiguation note (Step 1e, `roberts.errors` vs. `smithson.error`)

Unchanged from v0.1: these are different-sized concepts sharing a label. Step 1e
checks the narrow Roberts sense (a confidently-held false belief); mere absence
of information proceeds to Step 3, where it may land on `smithson.absence`,
`smithson.incompleteness`, or the `smithson.error` branch. Analysis must key on
the full `type_id`, never the bare English label.

## 5. Non-fit, edge codes, and the v0.3 multi-actor flag

Every unit receives exactly one of {a taxonomy code, RESIDUAL, NOT_NK,
UNCODABLE}. In addition, v0.3 scores the multi-actor flag on every coded unit.

### 5.1 RESIDUAL
Defined at Step 5. **Primary evidence for RQ4a (coverage) and RQ4c
(multi-actor gap).** Requires a free-text note.

### 5.2 NOT_NK and UNCODABLE
Unchanged from v0.1. NOT_NK = interpretable, no non-knowledge content; UNCODABLE
= not interpretable as language. They are never confused with RESIDUAL.

### 5.3 Required free-text notes
Every RESIDUAL code requires a note stating what resists classification. Under
parent-chain context (§5.5), the note should state whether the not-knowing is
held by a single actor or distributed across the thread — this feeds RQ4c's P4
test.

### 5.4 `residual_but_for` flag
Recorded whenever a catch-all category is assigned (`gross.ignorance`,
`smithson.error`, `smithson.irrelevance`). Required for the catch-all reversal
report in RQ4a.

### 5.5 Multi-actor flag and parent-chain context (new in v0.3)
- **The flag.** For every coded unit, record `multi_actor ∈ {single, distributed,
  unknown}`. `distributed` means the unit's non-knowledge is, or is being
  negotiated across, two or more identifiable parties with asymmetric awareness
  (e.g. a maintainer answering a contributor's partial understanding; two
  parties both uncertain of different parts of the same gap). This is **not** a
  taxonomy code — the primary code is assigned without reference to it, and the
  flag is scored on all units (taxonomy-coded and RESIDUAL alike).
- **The context.** For the RQ4c subsample, coders see the unit's parent chain
  (thread title, preceding turns, named authors/roles from the graph: mentor vs
  mentee for OpenMent, author vs reviewer for review email). The context may
  **only** inform the multi-actor flag and the RESIDUAL note; it never changes
  the primary code. Units coded without context are flagged as such, and RQ4c
  reports the multi-actor share on the context-visible subsample only.
- **Why this does not break the instrument.** The four taxonomies contain no
  multi-actor category. If the multi-actor flag and RESIDUAL co-occur far more
  often than expected by chance, that is the RQ4c result — it is measured, not
  defined into existence.

### 5.6 Optional supplementary multi-coding
The multi-fit pass (all categories that plausibly apply, not just the priority
winner) is **mandatory in v0.3** for RQ4a coverage, per `REFINED_RQS_v0.3.md`
RQ4a. It is a layered annotation: the primary code is never renegotiated to
accommodate a candidate in the multi-fit list.

## 6. Reliability procedure (two independent coders)

Unchanged from v0.1, with the v0.3 numbering:

1. Both coders apply the decision procedure independently, blind to each
   other's codes and — where the RQ4b subsample is concerned — to the unit's
   corpus/genre where blinding is feasible (see §7 for the tension this creates
   with genre-conditional reporting).
2. Agreement at three granularities: (a) exact `type_id`, (b) taxonomy-level,
   (c) fit/non-fit.
3. Taxonomy-level disagreements are adjudicated by a third reading against the
   decision tree — never by "what feels right for SE text".
4. Disagreements clustering on the known-collision steps (1e, 1b/1c, 3d) are
   expected and reported as such, not treated as coder error. This is the
   behavioural test of RQ1's `NONE_POSSIBLE` pairs (RQ4b).
5. **v0.3 addition.** Disagreement is also recorded per genre, so RQ4b can
   report whether predicted collapses manifest uniformly across genres or are
   genre-concentrated.

## 7. v0.3 sampling and context requirements (bindings)

These are requirements the pipeline/notebook must meet before coding starts;
they are listed here so the manual and the analysis notebook stay in sync.

1. **Genre-stratified sample.** The hand-coding sample is stratified by genre
   (tracker / review email / chat / Q&A, plus OpenMent separately) with each
   genre's stratum size proportional to a power target set in
   `03_rq_analysis.ipynb` §6.1, so coverage claims stay genre-conditional.
2. **Thread-enriched RQ4c subsample.** Within the RQ4c stratum, units are
   oversampled from threads with ≥2 authors and ≥2 turns (gold `REPLIES_TO` /
   `in_reply_to` / comment-chain structure). Parent-chain context is supplied
   (§5.5).
3. **Role context (OpenMent).** Where a unit's author has a mentor/mentee role
   in the ingested doc metadata, the role label is available to the coder for
   the multi-actor flag. Role is context, never part of the unit text.
4. **Blinding trade-off (stated).** Genre is sometimes identifiable from unit
   text itself (IRC nick syntax, email salutations); perfect genre blinding is
   not claimed. The multi-actor flag is scored on context-visible units, so the
   blinding requirement applies to the *primary code*, not the flag.

## 8. Pre-registered predictions (unchanged from v0.1, renumbered to v0.3 RQs)

These predictions were recorded before any SE data was examined. They are
falsifiable statements about instrument behavior; contradictions are reportable
findings, not evidence of a recording error.

- **P1 (population, RQ4a).** Roberts's `known_unknowns`, `unknown_unknowns`,
  and `secrecy` — the highest-confidence, most concretely operationalised
  categories — will be among the most frequently assigned. Low-confidence
  categories (all three Gross top-level, `smithson.probability`) will be
  assigned rarely, routed away by priority order rather than by rarity of the
  phenomenon.
- **P2 (collapse, RQ4b).** The known/unknown-unknowns cluster (`roberts.
  unknown_unknowns`, `roberts.known_unknowns`, `wehling.knowledge_of_
  nonknowledge`, `gross.nescience`, `gross.non_knowledge`) will show the highest
  taxonomy-priority agreement and the lowest cross-taxonomy discriminating
  value.
- **P3 (collapse, RQ4b).** The Roberts/Smithson "errors" collision will produce
  scope-artefact differences in counts, independent of underlying phenomena.
- **P4 (multi-actor residual, RQ4c).** Distributed/multi-actor non-knowledge
  will be a disproportionately large source of RESIDUAL codes — the taxonomies
  were built for single-actor framings and none defines awareness distributed
  across named parties in a threaded record.
- **P5 (instrument diagnostic, RQ4b).** The Step-4 (Gross) arrival rate will be
  a low single-digit percentage of codable units; a high rate is itself a
  finding.
- **P6 (non-fit rate, RQ4a).** UNCODABLE will be rare; NOT_NK will be common;
  the RESIDUAL rate is computed over **codable** units, never the raw count.

## 9. Genre and context fields the coding sheet carries

Each coded row carries: `text_unit_id`, `genre`, `corpus_id`, `role` (mentor/
mentee / author / reviewer / other / none), `multi_actor`, `primary_code`
(type_id or RESIDUAL/NOT_NK/UNCODABLE), `taxonomy`, `wehling_*` axis positions
(when reached), `multi_fit_candidates`, `residual_but_for`, and the required
note. Analysis code must key on `type_id`, never the English label.

---

## 10. The active qualitative codebook — Sub-RQ 4 (v0.3.1)

> **Status.** This is the **active** coding instrument for the paper's
> independent qualitative sub-RQ (`REFINED_RQS_v0.3.md` §4, Sub-RQ 4). §§1–9
> above are the **deferred** taxonomy instrument. Unlike §§1–9, Section 10 is
> **not** about fitting a unit to a taxonomy of ignorance types; it characterises
> the **communicative act, referent, and conversational resolution** of expressed
> non-knowledge.

### 10.1 Unit of analysis and frame

- Code one **TextUnit** at a time, as handed down from the pipeline's sampling
  cell (§3.6 of the implementation plan / `03_rq_analysis.ipynb` Sub-RQ 4 cells).
- Every sampled unit carries **≥1 active non-knowledge signal** (the frame is
  **detector-positive**). This study characterises how expressed NK is
  communicated; it does **not** measure what the pipeline misses (blind-spot /
  coverage — deferred, `REFINED_RQS_v0.3.md` §6).
- The coder is given **thread context** (preceding and, where structure exists,
  following turns, thread title, named roles) alongside the target unit. The
  context informs Dimension 3 (trajectory) and the free-text note; it **never**
  changes Dimensions 1 and 2, which are scored on the target unit itself.

### 10.2 Dimension 1 — Communicative function (*why* is non-knowledge stated?)

Assign exactly **one** of:

| Code | Definition | Positive prototype | Negative prototype |
|---|---|---|---|
| `HELP_SEEKING` | Spontaneous disclosure of a personal epistemic gap to elicit immediate aid | "does anyone know why this test only fails on ARM?" | "the ARM failure is non-deterministic" (no request) |
| `HEDGING` | Softening a critique/claim to protect the interlocutor's face | "I'm not entirely sure, but wouldn't this leak if closed early?" | "this will leak if closed early" (no hedge) |
| `SPECULATION` | Exploring unverified alternatives / future states / trade-offs | "it's unclear if we need consensus here or a local lock suffices" | "we need consensus here" (assertion) |
| `DEFECT_LOGGING` | Formally documenting a gap/bug as an objective system state | "unable to reproduce on v3.2; root cause unknown" | "build is red" (no ignorance) |
| `INSTRUCTION` | A knowledgeable party framing the known/unknown boundary for others | "we don't know the payload format yet, so leave that field optional" | "leave that field optional" (no NK framing) |

Notes: `HELP_SEEKING` requires an explicit or clearly implied request addressed
to others. `HEDGING` requires a face/threat context (review, correction,
criticism). `DEFECT_LOGGING` frames ignorance as a property of the artefact, not
of the speaker.

### 10.3 Dimension 2 — Epistemic referent (*what* is unknown?)

Assign exactly **one** of:

| Code | Definition | Example |
|---|---|---|
| `CODE_RUNTIME` | Execution semantics, concurrency, memory, flakiness, crashes | "the segfault only happens under heavy load" |
| `ENVIRONMENT` | OS, compiler, hardware, dependencies, network | "works on my Mac but fails on Windows CI" |
| `SPEC_INTENT` | Requirements, API contract, design intent, documentation | "the documented contract doesn't say what happens on null" |
| `COMMUNITY_PROCESS` | Contribution rules, release cadence, ownership, licensing | "who owns the backport for this branch?" |
| `PERSONAL_GAP` | Speaker's own unfamiliarity with a language/feature/tool | "I've never used the new coroutine syntax before" |

### 10.4 Dimension 3 — Conversational trajectory (*how* is it handled?)

Assign exactly **one** of:

| Code | Definition |
|---|---|
| `RESOLVED` | The gap is closed within the visible thread (answer given, root cause found, clarification supplied) |
| `ACTIONABLE_DEFERRED` | The gap is converted into an explicit action item (issue filed, task deferred, profile scheduled) |
| `OPEN_BOUNDARY` | The gap is agreed intractable with current resources (upstream bug, closed-source driver, non-reproducible hardware) |
| `CONTESTED_OR_IGNORED` | The admission is challenged, refuted, or passed over without uptake |
| `UNCODABLE_STRUCTURE_ABSENT` | No thread structure exists in the graph to determine trajectory (e.g. Gitter, Discord) |

If `UNCODABLE_STRUCTURE_ABSENT`, the dimension is excluded from reliability
statistics on that unit; coverage of this code is reported explicitly.

### 10.5 Reliability protocol (2 raters, v0.3.1)

1. **Calibration.** Five pilot units drawn from the same frame but **excluded**
   from the 100 are coded jointly to align boundary rules (one 30-minute sync).
2. **Independent blind coding.** Both raters code all 100 units independently,
   blind to each other's codes and to the corpus/genre where feasible. The
   primary code (Dimensions 1 and 2) is scored on the target unit with context;
   Dimension 3 uses the provided following-turn context.
3. **Reliability statistics.** Cohen's κ and observed agreement $P_o$ are
   computed **per dimension** with `sklearn.metrics.cohen_kappa_score` (explicit
   `labels=` for categories absent from the sample), and κ 95% CIs via bootstrap.
   Dimension 3 κ is computed on the sub-sample with thread structure only.
4. **Adjudication.** Disagreements are resolved by a third reading against the
   definitions above — never by "what feels right for SE text". Consensus codes
   are recorded in the `adjudicated_*` columns.
5. **Disagreement diagnosis.** A confusion matrix per dimension identifies which
   code-pairs collide (e.g. `HEDGING` vs `SPECULATION`), reported as an expected
   measurement property, not coder error.

### 10.6 Coding sheet fields (Sub-RQ 4)

`unit_id`, `stratum` (signal mechanism × genre), `corpus_id`, `platform_id`,
`venue_id`, `role`, `thread_context`, `unit_text`, `detected_signals`,
`rater1_function`, `rater1_referent`, `rater1_trajectory`, `rater1_notes`,
`rater2_function`, `rater2_referent`, `rater2_trajectory`, `rater2_notes`,
`adjudicated_function`, `adjudicated_referent`, `adjudicated_trajectory`.
