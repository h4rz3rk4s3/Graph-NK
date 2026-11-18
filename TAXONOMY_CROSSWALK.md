# TAXONOMY_CROSSWALK.md

**Companion to:** `ignorance_codebook_v0.1.yml`
**Purpose:** T3 deliverable — a readable rendering of every near-neighbour relation recorded in the codebook, across and within the four taxonomies (Roberts 2013, Smithson 1989/1993, Gross 2010, Wehling 2024).

## How to read this document

Each row states a pair of categories/dimensions and the relation between them, **as asserted by the source material or its secondary reception** — never adjudicated by us. Four relation types are used:

- `near_synonym` — the two categories appear to denote essentially the same concept.
- `partial_overlap` — the categories share some but not all of their extension.
- `orthogonal` — the categories address different axes and rarely co-occur as alternatives.
- `conflicting` — the categories use overlapping or identical terminology for **different** concepts, creating a risk of confusion.

Where the source(s) give a way to tell the two apart on a single text unit, it is stated as the **distinguishing test**. Where no such test exists — either because the sources don't provide one, or because the concepts are genuinely coextensive — the entry reads **NONE_POSSIBLE**, with the reason.

**This document does not resolve any of these tensions.** Overlap and conflict between taxonomies is data for RQ4(c), not redundancy to be cleaned up. The four taxonomies remain four separate coding options in the manual; a coder facing a `NONE_POSSIBLE` pair must fall back on the ordered decision procedure in `CODING_MANUAL.md`, which fixes a taxonomy-priority order rather than asking the coder to adjudicate concept identity live.

Of the 31 codeable units in the codebook (9 Roberts + 14 Smithson + 5 Gross + 3 Wehling dimensions), 24 pairwise relations were found explicitly documented in the primary sources or their secondary reception; 28 of the 31 units participate in at least one such relation. Three units — `smithson.confusion`, `smithson.inaccuracy`, and `wehling.intentionality` — have no documented relation to any category in another taxonomy; this absence is recorded, not filled in, per the "do not invent" constraint.

---

## Part 1 — Cross-taxonomy relations (the RQ4c core evidence)

### 1.1 The "known/unknown unknowns" cluster — near-total terminological convergence

| Pair | Relation | Distinguishing test |
|---|---|---|
| `roberts.unknown_unknowns` ↔ `wehling.knowledge_of_nonknowledge` | near_synonym | **NONE_POSSIBLE.** Both trace to the identical Kerwin (1993) "unknown unknowns" concept. Wehling's dimension treats it as one pole of a spectrum rather than a discrete type, but the underlying concept is the same import. |
| `roberts.known_unknowns` ↔ `wehling.knowledge_of_nonknowledge` | near_synonym | **NONE_POSSIBLE.** Same Kerwin (1993) lineage; Roberts operationalises the pole as a discrete category, Wehling as the opposite pole of the same dimension. |
| `gross.nescience` ↔ `roberts.unknown_unknowns` | near_synonym | **NONE_POSSIBLE.** Per secondary paraphrase (Gross 2010, p. 68, via a citing work), nescience is "the complete absence of knowledge," discoverable only in hindsight — indistinguishable in extension from Roberts's unknown unknowns on present evidence. Confidence in Gross's own wording is *low* (secondary paraphrase only), so this convergence itself is only medium-confidence. |
| `gross.non_knowledge` ↔ `roberts.known_unknowns` | near_synonym | **NONE_POSSIBLE.** Both denote a *named*, resolvable-in-principle gap. Gross's version is reconstructed from secondary paraphrase only (low confidence). |
| `gross.non_knowledge` ↔ `wehling.knowledge_of_nonknowledge` | partial_overlap | Gross's category foregrounds resolvability; Wehling's dimension foregrounds degree of awareness. They will often co-occur on the same unit without a clean separating test. |
| `gross.ignorance` ↔ `roberts.known_unknowns` | partial_overlap | Gross's "ignorance" (as reconstructed) is a broader umbrella than Roberts's specific known-unknowns category; the internal structure of Gross's umbrella could not be independently verified, so no fine-grained test is possible at current evidence. |

**Reading for RQ4(c):** this cluster is the single largest point of terminological convergence across the four traditions. Three of the four taxonomies (Roberts, Wehling, and — at low confidence — Gross) import the *same* Rumsfeld/Kerwin (1993) known/unknown-unknowns pairing rather than deriving it independently. A coder cannot use this cluster to discriminate *which taxonomy* an SE utterance belongs to; it can only discriminate *whether* the utterance is this concept at all. This is exactly the kind of "collapse" RQ4(c) is designed to detect, and it is a property of the source literature, not an artefact of the extraction.

### 1.2 The "Errors / distortion" terminology collision

| Pair | Relation | Distinguishing test |
|---|---|---|
| `roberts.errors` ↔ `smithson.error` | **conflicting** | **NONE_POSSIBLE without disambiguation.** Smithson's `error` is a broad top-level *branch* covering all passive-voice ignorance, including mere absence of information. Roberts imports the word "Errors" but narrows it to mean specifically a confidently-held false belief — a much smaller concept. Roberts cites Smithson as the source but does not flag the narrowing. A coder who sees "Errors" in Roberts's list and "Error" in Smithson's list is looking at differently-scoped concepts sharing one label. |
| `roberts.errors` ↔ `smithson.distortion` | near_synonym | **NONE_POSSIBLE.** Roberts's narrow "Errors" concept is, in extension, what Smithson's *sub*-branch `distortion` (not the top-level `error` branch) denotes — Roberts's category is definitionally the outcome of Smithson's distortion. |

**Reading for RQ4(c):** this is a same-word, different-referent collision *within the borrowed literature itself*, not something introduced by applying it to SE. Any residual-rate analysis that reports "Roberts: Errors — 0 hits" alongside "Smithson: Error — 40 hits" is not thereby showing the taxonomies agree or disagree; it is very possibly an artefact of this label collision, and the manual instructs coders accordingly (see `CODING_MANUAL.md`, disambiguation note).

### 1.3 The "taboo" convergence

| Pair | Relation | Distinguishing test |
|---|---|---|
| `smithson.taboo` ↔ `roberts.taboos` | near_synonym | **NONE_POSSIBLE.** Both denote a topic forbidden by authority or social/cultural norm. Roberts's category is explicitly the organizational application of the same underlying concept Smithson names generically. |

### 1.4 Resolvability / durability convergence

| Pair | Relation | Distinguishing test |
|---|---|---|
| `smithson.undecidability` ↔ `wehling.temporal_durability` | partial_overlap | Smithson's undecidability concerns whether a claim's *truth value* can in principle be determined; Wehling's dimension concerns whether the underlying non-knowledge will *ever be converted into knowledge*, independent of the true/false framing. A case that is both (e.g. a question that is both formally undecidable and never going to be resolved) has no source-given way to be cleanly split — flagged here rather than adjudicated. |
| `gross.negative_knowledge` ↔ `wehling.temporal_durability` | near_synonym | **NONE_POSSIBLE.** Both concern principled, irreducible unresolvability. They derive from different lineages (Knorr-Cetina 1999 via Gross; Wehling's own dimensional scheme) and neither source provides a test that would separate them if both were confidence-verified — and Gross's wording here is itself only reconstructed from secondary paraphrase (low confidence). |

### 1.5 Incompleteness / absence overlap with known-unknowns

| Pair | Relation | Distinguishing test |
|---|---|---|
| `smithson.incompleteness` ↔ `roberts.known_unknowns` | partial_overlap | Roberts's known unknowns require the *actor* to be aware of the gap; Smithson's incompleteness is a state describable independent of any particular actor's awareness (an analyst can call something "incomplete" without any party in the text being shown as aware of it). A text unit that merely lacks information, with no marker of anyone's awareness of the lack, is Smithson-codable but not automatically Roberts-codable. |
| `smithson.absence` ↔ `roberts.unknown_unknowns` | partial_overlap | Same awareness-asymmetry as above, applied to the narrower "wholly missing" case. |
| `roberts.known_unknowns` ↔ `smithson.uncertainty` | partial_overlap | Smithson's uncertainty concerns imprecision in information that *is* present; Roberts's known unknowns concerns information that is entirely absent but whose absence is recognized. Overlap arises when hedged/imprecise information (Smithson) is also framed by the writer as a recognized gap (Roberts). |

### 1.6 Irrelevance-family orthogonality with Roberts's resource-allocation categories

| Pair | Relation | Distinguishing test |
|---|---|---|
| `smithson.irrelevance` ↔ `roberts.knowable_known_unknowns` | partial_overlap | Roberts's category is specifically a resource-investment decision about a *named* gap; Smithson's irrelevance is a broader active-exclusion stance that need not involve any named gap. No sharp test for intermediate cases is given by either source. |
| `smithson.untopicality` ↔ `roberts.knowable_known_unknowns` | orthogonal | Untopicality is a relevance judgment requiring no named gap at all; Roberts's category requires one. These rarely describe the same text unit. |

### 1.7 Absence-vs-awareness across Roberts and Gross

| Pair | Relation | Distinguishing test |
|---|---|---|
| `roberts.unknown_unknowns` ↔ `smithson.error` (top-level branch) | partial_overlap | Smithson's error branch (passive-voice ignorance in general) is broader than Roberts's unknown-unknowns; Smithson's branch also covers Roberts's known-unknowns and error categories. Not usable as a 1:1 mapping. |

---

## Part 2 — Intra-taxonomy relations relevant to discrimination

These are pairs *within* a single taxonomy where the source itself signals a close or blurred boundary — included because a coder choosing between two categories in the *same* taxonomy faces the identical discrimination problem as choosing across taxonomies.

| Pair | Taxonomy | Relation | Distinguishing test |
|---|---|---|---|
| `roberts.known_unknowns` ↔ `roberts.knowable_known_unknowns` | Roberts | near_synonym | **NONE_POSSIBLE.** Roberts asserts the boundary ("given sufficient motivation and resources") without operationalising a threshold. |
| `roberts.secrecy` ↔ `roberts.privacy` | Roberts | near_synonym | Roberts's own test: privacy is "multilateral" (a reciprocally sanctioned right), secrecy is unilateral/strategic. Asserted once (p. 223), not elaborated for borderline cases (e.g. mutually agreed non-disclosure). |
| `roberts.taboos` ↔ `roberts.denials` | Roberts | partial_overlap | Distinguished by locus of causation: externally-imposed social prohibition (taboo) vs. internal psychological avoidance (denial). No test given for cases where both operate together (a socially-reinforced denial). |
| `roberts.unknown_knowns` ↔ `roberts.unknown_unknowns` | Roberts | orthogonal | Unknown knowns require the knowledge to have objectively existed and been merely unrecognized; unknown unknowns require the knowledge to never have existed in accessible form at all. |
| `smithson.probability` ↔ `smithson.vagueness` | Smithson | partial_overlap | **NONE_POSSIBLE at high confidence.** A secondary source notes only that "statistics primarily operates in the area of incompleteness, across probability and some kinds of vagueness," without giving Smithson's own boundary test. Both leaves are, independently, among the lowest-confidence definitions in the entire codebook (probability: *low*; vagueness: *medium*, sourced from a 2022 restatement rather than the 1989/1993 originals). |
| `smithson.vagueness` ↔ `smithson.ambiguity` | Smithson | partial_overlap | Test given in the 2022 restatement (continuous interval vs. discrete alternative readings) but not verified against the 1989/1993 originals, which deferred defining both terms at first mention. |
| `gross.nescience` ↔ `gross.surprise` | Gross | partial_overlap | Per the one verified verbatim quote (p. 76), surprise is the *triggering event* through which a nescience is revealed; nescience is the *underlying gap* itself. A unit describing the triggering event vs. the gap it reveals may need a foregrounding judgment. |

---

## Part 3 — Categories with no documented relation to any other taxonomy

| Category | Taxonomy | Note |
|---|---|---|
| `smithson.confusion` | Smithson | A leaf of `distortion`, distinguished from its sibling `smithson.inaccuracy` only by the degree/kind split; no source or secondary reception located maps it onto a category in Roberts, Gross, or Wehling. |
| `smithson.inaccuracy` | Smithson | Same as above. |
| `wehling.intentionality` | Wehling | No secondary source located maps this dimension onto a Roberts, Smithson, or Gross category; Wehling's chapter positions the whole three-dimension scheme against Smithson/Faber/Kerwin at the *typology* level (see codebook `source_framing`), not dimension-by-dimension. |

**This absence is itself potentially informative for RQ4(a)/(c):** these three units are exactly the kind of finely-differentiated leaf categories most likely to be either (a) heavily populated in SE discourse without competition from other taxonomies' vocabulary, or (b) entirely unpopulated because the distinction they draw does not correspond to anything speakers in this register bother to mark. Both outcomes are informative; neither was assumed in advance.

---

## Summary table — relation type counts

| Relation type | Count (cross-taxonomy) | Count (intra-taxonomy) |
|---|---|---|
| near_synonym | 7 | 2 |
| partial_overlap | 8 | 4 |
| orthogonal | 1 | 1 |
| conflicting | 1 | 0 |

Of the 17 cross-taxonomy relations documented, **8 are marked NONE_POSSIBLE** — nearly half. This is not a defect in the crosswalk; it is the expected signature of four independently-developed traditions that borrow terminology from a shared, small pool of prior sources (chiefly Kerwin 1993, Merton 1987, Knorr-Cetina 1999) without harmonizing their scope. Where a taxonomy's own literature cannot tell two of its imported neighbours apart, the codebook does not manufacture a test; it records `NONE_POSSIBLE` and lets the decision procedure's fixed priority order (§`CODING_MANUAL.md`) settle which code a coder assigns.
