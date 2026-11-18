# CODING_MANUAL.md

**Companion to:** `ignorance_codebook_v0.1.yml`, `TAXONOMY_CROSSWALK.md`
**Purpose:** the deterministic coding instrument for RQ4. Given a text unit from SE discourse (an issue comment, PR review comment, commit message, or mailing-list message — this manual does not see, and was not written with reference to, any such unit), two independent coders applying this procedure should reach the same code.

**Standing constraint this manual observes:** every code below is imported unchanged from Roberts (2013), Smithson (1989/1993), Gross (2010), or Wehling (2024). Nothing here has been invented, broadened, or reworded to make SE text easier to classify. Where applying an unmodified category to a hypothetical SE-like sentence would be awkward, that awkwardness is preserved, not smoothed over — it is the finding, not a defect in the instrument.

---

## 1. What this manual is for, and what it is not for

This manual answers: **given one text unit, which single code (or explicit non-fit code) does it receive?**

It does **not**:
- adjudicate which of the four taxonomies is theoretically "better" (that is not a question the codebook answers, and coders should not attempt to answer it either);
- resolve the terminological collisions documented in `TAXONOMY_CROSSWALK.md` by inventing a merged concept (the crosswalk's `NONE_POSSIBLE` entries are treated as ties broken by taxonomy priority — §3 below — never as an invitation to average or blend two definitions);
- allow "fit" to be adjusted after seeing how well a category performs on the actual corpus. The procedure below is fixed before corpus contact.

## 2. Unit of analysis

Code one **text unit** at a time. A text unit is the smallest self-contained span the outer analysis pipeline hands to this instrument (e.g. one issue comment, one commit message, one PR-review thread turn) — this manual takes the unit boundary as given from upstream and does not redefine it. Within a unit, more than one code may in principle apply (see §5, multi-coding); the procedure below determines the *primary* code for the unit.

## 3. Taxonomy priority order (fixed, pre-registered, not data-driven)

Because the four taxonomies overlap and sometimes collide (see `TAXONOMY_CROSSWALK.md` Part 1), a coder facing a unit that plausibly fits categories from more than one taxonomy needs a tie-break rule that does **not** depend on which taxonomy "sounds more natural" for SE text — that judgment is exactly what RQ4 is testing, so it cannot also be the tie-break rule.

The priority order is fixed by **definitional specificity and confidence, as established from the source literature before any corpus contact**, not by fit to SE material:

1. **Roberts (2013)** — highest priority. Its categories are the most operationally concrete (organizational setting, high/medium confidence throughout, Table 1 gives explicit boundary conditions for every category).
2. **Wehling (2024)** — second priority. Dimensional rather than categorical; apply only after checking whether a Roberts category already accounts for the unit, because Roberts's discrete categories are more falsifiable than a position on a continuous dimension.
3. **Smithson (1989/1993)** — third priority. Broad, hierarchical coverage, but several leaves (`probability`, `taboo`, `undecidability`, `vagueness`, `ambiguity`) rest on medium/low-confidence secondary reconstruction (see codebook `definition_confidence` fields).
4. **Gross (2010)** — lowest priority. Every category in this taxonomy is reconstructed from secondary paraphrase with `definition_confidence: low` or `medium` — no page-verified primary quote was obtained for `ignorance`, `non_knowledge`, or `negative_knowledge`. Use Gross's categories only when no higher-priority taxonomy offers ANY plausible code (not just no *better* code) — this is a deliberate, pre-registered method choice given the access limitations recorded in `SOURCES_AUDIT.md`, not a judgment that Gross's ideas are less valid.

**This order is not a claim that Roberts is theoretically correct and Gross is not.** It is a pragmatic, pre-registered rule needed to make the instrument deterministic, chosen on evidentiary grounds (definitional traceability) established *before* any SE unit is examined. A separate, explicit tag records which taxonomy's code was assigned, so downstream RQ4 analysis can always ask "how many units got a Gross code only because nothing else fit" as its own finding.

## 4. The decision procedure

Apply the following ordered checks to one text unit. Stop at the first step that yields a code. This is a decision *tree*, not a checklist — do not skip ahead.

```
STEP 0 — Is the unit codable at all?
  Is the unit a genuine expression, marker, or negotiation of a gap in knowledge —
  someone's not-knowing, not-being-sure, or not-being-able-to-know something —
  as opposed to a gap-free statement (a fact asserted with no hedge, a routine
  status update, a purely social/phatic remark)?
    NO  → code UNCODABLE if the unit is not interpretable at all (garbled, no
          semantic content, e.g. a bot-generated hash string) — see §5.3.
    NO  → code NOT_NK if the unit is interpretable and clearly about something
          else entirely (a technical fact, an agreement, a greeting) — see §5.2.
    YES → continue to STEP 1.

STEP 1 — Check Roberts (2013) categories, in this fixed sub-order:
  1a. roberts.unknown_unknowns   — retrospective-only gap, unnameable in advance?
  1b. roberts.known_unknowns     — a specific, named, actor-aware gap?
  1c. roberts.knowable_known_unknowns — named gap + explicit resource/investment framing?
  1d. roberts.unknown_knowns     — knowledge that existed but was unrecognized until
                                    rediscovered?
  1e. roberts.errors             — a confidently held, specific belief shown to be
                                    wrong (NOT mere absence — see disambiguation
                                    note below)?
  1f. roberts.taboos             — externally/socially/organizationally prohibited
                                    topic?
  1g. roberts.denials            — psychologically motivated rejection of available,
                                    conflicting information?
  1h. roberts.secrecy            — unilateral, strategic withholding by an
                                    identifiable party?
  1i. roberts.privacy            — sanctioned right to withhold information about
                                    oneself specifically?
    A code applies here?  → ASSIGN IT. Record taxonomy = roberts_2013. Stop.
    None apply?           → continue to STEP 2.

STEP 2 — Check Wehling (2024) dimensions.
  Wehling's scheme is dimensional, not categorical: a unit is placed on THREE
  independent axes simultaneously (all three MUST be scored if this step is
  reached; a unit cannot receive "no position" on a Wehling dimension once this
  step is reached — indeterminate position is itself a valid, codeable position,
  see the codebook's permitted_values for each dimension):
    2a. wehling.knowledge_of_nonknowledge — known-unknown pole / unknown-unknown
        pole / intermediate (vague, partially-aware)?
    2b. wehling.intentionality             — unintended / partly attributable to
        action-or-omission / deliberately produced?
    2c. wehling.temporal_durability        — temporary not-yet-knowing / principled
        inability-to-know / intermediate?
  Record taxonomy = wehling_2024, plus all three axis positions. Stop.
    (Only reach this step if STEP 1 produced no code. If a Roberts code was
    already assigned in STEP 1, Wehling's dimensions are NOT additionally scored
    for this unit under the primary-code procedure — see §5 for optional
    supplementary multi-coding.)

STEP 3 — Check Smithson (1989/1993) leaves, in this fixed sub-order:
  3a. smithson.confusion       — one specific thing mistaken for a categorically
                                  different one?
  3b. smithson.inaccuracy      — a quantity/estimate off in magnitude, right
                                  referent?
  3c. smithson.absence         — information wholly missing on an identifiable
                                  question?
  3d. smithson.probability     — likelihood/chance framing (LOW CONFIDENCE leaf —
                                  see codebook; use cautiously)?
  3e. smithson.vagueness       — continuous-dimension interval/range given?
  3f. smithson.ambiguity       — multiple discrete possible readings, none
                                  privileged?
  3g. smithson.untopicality    — topic passed over as not germane, no prohibition
                                  or unresolvability implied?
  3h. smithson.taboo           — forbidden topic (if not already caught by
                                  roberts.taboos in Step 1 — see crosswalk §1.3;
                                  reaching this step means Step 1f did not match,
                                  which given the near-synonymy documented in the
                                  crosswalk should be RARE; if it happens, flag
                                  the unit for review, see §6)?
  3i. smithson.undecidability  — question framed as unresolvable IN PRINCIPLE,
                                  not just currently unresolved?
    A leaf applies?  → ASSIGN IT. Record taxonomy = smithson_1989. Stop.
    None apply, but the unit is clearly some form of passive-voice, non-actively-
    chosen ignorance?  → code smithson.error (branch-level fallback). Stop.
    None apply, but the unit is clearly some form of active exclusion/avoidance
    with no leaf fitting?  → code smithson.irrelevance (branch-level fallback).
    Stop.
    Neither branch fits either?  → continue to STEP 4.

STEP 4 — Check Gross (2010) categories, in this fixed sub-order.
  Reaching this step means NEITHER Roberts NOR Wehling NOR any Smithson leaf/
  branch matched. Given the near-synonymy documented in the crosswalk between
  Gross's categories and Roberts's/Wehling's, reaching Step 4 should be RARE. Its
  frequency is itself a pre-registered quantity of interest (see §7, prediction
  P5).
    4a. gross.nescience           — retrospective-only, unnameable-in-advance gap,
                                    revealed via an unexpected outcome (distinct
                                    from roberts.unknown_unknowns only in being
                                    explicitly frame around a SURPRISE event — see
                                    crosswalk §1.7)?
    4b. gross.surprise            — the triggering unexpected event itself, with
                                    the revealed gap not independently codable?
    4c. gross.non_knowledge       — named, resolvable-in-principle gap, framed as
                                    something a discipline/actor knows how to
                                    investigate?
    4d. gross.negative_knowledge  — explicit claim about the boundary/limits of
                                    knowability, not just an unresolved question?
    4e. gross.ignorance           — none of the above, but the unit clearly shows
                                    conscious awareness of not-knowing something
                                    (coarsest fallback in the entire manual; use
                                    of this code should be treated as a signal to
                                    double-check Steps 1-3, not as a comfortable
                                    default)?
    A code applies?  → ASSIGN IT. Record taxonomy = gross_2010. Stop.
    None apply?  → continue to STEP 5.

STEP 5 — RESIDUAL.
  The unit is a genuine expression of non-knowledge (Step 0 passed) but no
  category in any of the four taxonomies, at any priority level, fits — even
  approximately. Code RESIDUAL. This is not a failure of coding; for RQ4(b),
  this is the primary evidence category. Record a short free-text note of WHY
  no category fit (this note is required, not optional, for every RESIDUAL
  code — see §5.4).
```

### Disambiguation note referenced at Step 1e (`roberts.errors` vs. `smithson.error`)

Per `TAXONOMY_CROSSWALK.md` §1.2, "Errors" (Roberts) and "Error" (Smithson) name **different-sized concepts** despite the shared label. At Step 1e, a coder is checking the **narrow** Roberts sense only (a specific, confidently-held, false belief) — NOT Smithson's broad passive-ignorance branch. If a unit shows mere absence of information with no confidently-held false belief, Step 1e does NOT apply, and the unit proceeds down the tree to Smithson's branch (Step 3), where it may land on `smithson.absence`, `smithson.incompleteness`, or the `smithson.error` branch-level fallback. Recording BOTH labels as literally "error"/"errors" in a results table without this note would silently conflate two different-sized concepts — analysis code consuming this manual's output must key on the full `type_id` (`roberts.errors` vs. `smithson.error`), never on the bare English label.

## 5. Non-fit and edge codes

Three non-fit codes are mutually exclusive and jointly exhaustive with the 31 taxonomy codes above — every unit receives exactly one of {a taxonomy code, RESIDUAL, NOT_NK, UNCODABLE}.

### 5.1 RESIDUAL
Defined in Step 5 above. **Primary evidence for RQ4(b).** Requires a free-text note.

### 5.2 NOT_NK
The unit is interpretable and clearly does **not** express, mark, or negotiate any gap in knowledge — e.g. a routine status confirmation ("build passed"), a purely procedural instruction with no epistemic hedge, a greeting, a thank-you. Assigned at Step 0. This code exists so that "the taxonomy doesn't apply" (RESIDUAL) is never confused with "the taxonomy doesn't apply because there is no non-knowledge content here at all" (NOT_NK) — conflating these two would silently inflate the RESIDUAL count used as RQ4(b) evidence.

### 5.3 UNCODABLE
The unit itself is not interpretable as language at all — a bot-generated hash, a corrupted encoding, a unit consisting only of a code diff with zero natural-language content, etc. Assigned at Step 0. Distinct from NOT_NK: UNCODABLE means the coder cannot determine whether non-knowledge is present or absent; NOT_NK means the coder CAN determine it is absent.

### 5.4 Required free-text notes
Every RESIDUAL code must be accompanied by a short note stating what about the unit resists classification (e.g. "expresses shared/distributed not-knowing across a group with no single locus of awareness — no category in any of the four taxonomies has a multi-actor known-unknown category"). This is not optional; a RESIDUAL code with no note is not a valid coding-manual output and should be treated as incomplete by any downstream QA pass.

### 5.5 Optional supplementary multi-coding
The primary-code procedure above yields exactly one code per unit for the main RQ4(a)/(b)/(c) analysis. If the research design separately calls for recording *all* categories that plausibly apply to a unit (not just the priority winner), that is a supplementary annotation pass layered on top of this manual, out of scope for this document — flag such units with a `multi_fit_candidates` list rather than renegotiating the primary-code priority order per unit.

## 6. Reliability procedure (for two independent coders)

1. Both coders apply the decision procedure independently, blind to each other's codes.
2. Compute agreement at three levels of granularity: (a) exact `type_id` match, (b) taxonomy-level match (did both coders pick a code from the same taxonomy, even if a different leaf within it), (c) fit/non-fit match (did both coders agree the unit was RESIDUAL/NOT_NK/UNCODABLE vs. any taxonomy code).
3. Any unit where the two coders disagree at the taxonomy level (not just the leaf level) should be flagged and adjudicated by a third reading against this manual's decision tree — NOT by discussing "what feels right for SE text," which would reintroduce exactly the post-hoc softening this instrument is designed to prevent.
4. Disagreements clustering around Step 1e (`roberts.errors` vs. Smithson's `error` branch), Step 1c (`roberts.known_unknowns` vs. `roberts.knowable_known_unknowns`), or Step 3d (`smithson.probability`, flagged low-confidence) are expected on definitional grounds (see `TAXONOMY_CROSSWALK.md` and codebook `source_vagueness` fields) and should be reported as such, not treated as coder error.

## 7. Pre-registered predictions (T5)

These predictions are recorded **before** any SE data is examined, so that the eventual RQ4 results can be checked against them rather than narrated after the fact. Each prediction states what pattern of category population, residual, or collapse the source literature's own structure leads us to expect — grounded in the codebook's `definition_confidence` and `source_vagueness` fields and the crosswalk's relation counts, not in any prior look at SE text.

- **P1 (population, RQ4a).** Roberts's `known_unknowns`, `unknown_unknowns`, and `secrecy` — the three highest-confidence, most concretely operationalised categories across all four taxonomies — will be among the most frequently assigned codes in the corpus. Categories built on `definition_confidence: low` (all three Gross top-level categories: `ignorance`, `non_knowledge`, `negative_knowledge`) will be assigned rarely, not because the underlying phenomena are rare in SE discourse, but because Step 4's priority ordering routes most matching units to a higher-priority Roberts/Wehling/Smithson code first (see crosswalk §1.1 near-synonymy).

- **P2 (collapse, RQ4c).** The known/unknown-unknowns cluster (crosswalk §1.1: `roberts.unknown_unknowns`, `roberts.known_unknowns`, `wehling.knowledge_of_nonknowledge`, `gross.nescience`, `gross.non_knowledge`) will show the *highest* inter-coder agreement at the taxonomy-priority level and simultaneously the *lowest* discriminating value between taxonomies — i.e., knowing a unit fits this cluster will predict almost nothing about which of the four taxonomies a coder reaches for, because the sources themselves converge on identical Kerwin (1993)-derived terminology.

- **P3 (collapse, RQ4c).** The Roberts/Smithson "Errors" collision (crosswalk §1.2) will produce measurably different counts depending on which taxonomy's code a coder assigns to superficially similar SE units (e.g. an incorrect confident claim in a commit message vs. a bug report noting a missing test), and this difference is predicted to be an artefact of taxonomy scope, not of any real difference in the underlying phenomena — a downstream check should verify this by inspecting whether `roberts.errors`-coded and `smithson.error`(-branch)-coded units are drawn from similar or dissimilar underlying situations.

- **P4 (residual, RQ4b).** We predict SE-specific forms of *distributed* or *multi-actor* non-knowledge (e.g. a maintainer and a contributor holding asymmetric, partially-overlapping awareness of the same gap, negotiated across multiple turns of a thread) will be a disproportionately large source of RESIDUAL codes, because all four taxonomies were built for single-actor or single-organization framings (interviews, organizations, media discourse) and none defines a category for awareness that is itself distributed unevenly across multiple named parties in a visible, threaded record — a structural feature of SE communication platforms that has no clear analogue in the settings the borrowed taxonomies were built for.

- **P5 (instrument diagnostic).** The frequency with which the decision procedure reaches Step 4 (Gross) at all — as opposed to resolving at Step 1, 2, or 3 — is predicted to be low (a single-digit percentage of codable units), given how much of Gross's category space is already covered by higher-priority near-synonyms (crosswalk §1.1, §1.4). A HIGH observed Step-4 rate would itself be a finding worth flagging, since it would suggest either (a) Gross's own theoretical contribution captures something the other three traditions miss in SE discourse specifically, or (b) the priority ordering in §3 is miscalibrated and should be revisited in v0.2 — the manual does not resolve which explanation is correct in advance.

- **P6 (non-fit rate, RQ4b).** We predict that `UNCODABLE` will be rare (SE text units, even terse ones, are almost always at least minimally interpretable) while `NOT_NK` will be common (a large fraction of any raw GitHub/mailing-list corpus is procedural or purely technical content with no epistemic hedge at all) — meaning the RESIDUAL rate reported for RQ4(b) should be computed as a fraction of codable (non-NOT_NK, non-UNCODABLE) units, not of the raw unit count, or it will be diluted by an artefact of corpus composition rather than taxonomy fit.

These are falsifiable statements about instrument behavior, fixed before corpus contact. If the eventual results contradict any of P1-P6, that contradiction is itself a reportable finding, not evidence the prediction was recorded incorrectly.
