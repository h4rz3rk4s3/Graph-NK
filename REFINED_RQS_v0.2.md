# Refined Research Questions v0.2 — FSE Paper (GraphRAG-NK)

*Supersedes `REFINED_RQS.md` (v0.1). Revised after delivery of `ignorance_codebook_v0.1.yml`,
`TAXONOMY_CROSSWALK.md`, `CODING_MANUAL.md`, and `SOURCES_AUDIT.md`.*

**Why this revision exists.** v0.1 assumed the four borrowed taxonomies were coherent
instruments that SE data would then strain. The crosswalk shows they do not discriminate
among *themselves*: of 17 documented cross-taxonomy relations, 8 admit no distinguishing
test at all, and `roberts.errors` / `smithson.error` is a same-label-different-referent
collision **inside the borrowed literature**. This is established from the sources, before
any corpus contact. Three consequences follow, and they are what this revision encodes:

1. Part of old RQ4(c) ("which categories collapse or blur *in this data*") is answerable
   without data, and is *weaker* if routed through the corpus. It becomes its own
   literature-level question (**RQ4a**).
2. The evidence asymmetry recorded in `SOURCES_AUDIT.md` — Roberts and Wehling at full
   primary text, Smithson partial, Gross secondary-paraphrase only — means "category X is
   unpopulated in SE" is confounded with "category X is thinly sourced and priority-last in
   the decision procedure." Coverage claims must be stated conditionally (**RQ4b**).
3. Prediction P4 (distributed / multi-actor non-knowledge) identifies a *structural* gap:
   all four taxonomies presuppose a single actor or single organisation. This is the most
   SE-specific claim the instrument can support and is promoted from a buried prediction to
   a question (**RQ4d**).

**The paper's central claim is correspondingly restated.** Not "SE discourse breaks these
taxonomies," which overstates what one corpus can show and which the prior-breakage
evidence (Kutsch & Hall 2010, IT project risk management) already partly pre-empts. Rather:

> The ignorance taxonomies imported into SE are (i) mutually non-discriminating by
> construction, (ii) unevenly evidenced in their own primary literature, and (iii) missing a
> category for the multi-actor, asynchronously-negotiated non-knowledge that is the
> structural default of SE communication platforms. We quantify all three.

Unchanged from v0.1: signals are never collapsed; taxonomic labels are post-hoc; every RQ
must be falsifiable and map to a concrete measurement.

---

## Framing: four layers of claim

v0.1 had three layers (descriptive → comparative → critical). A fourth is added *below* the
others, because it is logically prior and requires no corpus:

- **Layer 0 — instrument-level** (RQ4a). What the borrowed taxonomies can and cannot
  distinguish, established from sources. No SE data involved.
- **Layer 1 — descriptive** (RQ1, RQ2, RQ3). What markers occur.
- **Layer 2 — comparative** (RQ6). How arenas and communities differ.
- **Layer 3 — critical** (RQ4b–d, RQ5). Where the theory and the method fail.

Reviewers will most reward Layer 0 and Layer 3. Layer 0 is new to this revision and is the
cheapest defensible contribution in the paper — it cannot be attacked on sampling,
annotation, or corpus-composition grounds, because it makes no empirical claim about SE.

---

## RQ1 — What is the lexical-denotative profile of non-knowledge in SE discourse?

*(unchanged from v0.1 in substance; one measurement correction)*

- **Question.** Which lexical NK markers occur, at what relative frequency, and with what
  SE-specific realisations absent from the source taxonomies?
- **Unit.** TextUnit; aggregated per source and per arena.
- **Operationalisation.** Signal counts where `layer='lexical'`, grouped by
  `category`/`subcategory`. **Rates must be normalised per 1k tokens, not per 1k TextUnits**
  — GitHub and mailing-list units differ systematically in length, so per-unit rates are
  mechanically confounded with unit size. `TextUnit.token_count` supports this directly.
  Report SE-native subcategories (`repro_gap`, `opacity`, `spec_gap`, `doc_gap`,
  `code_comment_marker`, `non_deterministic_behaviour`) separately, at both signal and unit
  level, and with the candidate-inclusive figure alongside the active-only figure.
- **Contribution.** First frequency-ranked inventory of how SE lexicalises NK, with the
  SE-native fraction quantified and its dependence on rule-status decisions made explicit.
- **Revision note.** The SE-native fraction is the headline number and is currently diluted
  by two high-frequency non-SE-native subcategories; reporting it at one granularity only
  would be misleading in either direction.

## RQ2 — How is non-knowledge encoded morpho-syntactically, and how much is carried by construction rather than keyword?

*(unchanged from v0.1)*

- **Question.** What is the distribution of NK across negation, modality, hedging,
  evidentiality, tense, and syntactic-pattern signals — and what share of morpho-syntactic
  NK is detectable only via **scoped** (DependencyMatcher) rules rather than bare token
  matches?
- **Unit.** TextUnit.
- **Operationalisation.** Signal counts by `category` within `layer='morpho_syntactic'`;
  then the cue-vs-scope contingency on classifier-positive units. Epistemic-verb / shield /
  evidential families reported separately from modal/negation families.
- **Contribution.** Quantifies the **cue-vs-scope gap** — the empirical justification for
  the multi-layer marker design.
- **Revision note.** No change. This RQ was unaffected by the codebook work; it concerns the
  detection layer, not the taxonomy layer.

## RQ3 — What rhetorical figures express non-knowledge in SE, and how do SE-native metaphors relate to those in the ignorance literature?

*(minor revision)*

- **Question.** Which metaphor / comparison / personification families occur, and do SE
  communities recruit domain-specific NK metaphors (black box, rabbit hole, can of worms) at
  rates comparable to the canonical figures (blind spot, knowledge gap, uncharted territory)
  documented by Simmerling & Janich (2015)?
- **Unit.** TextUnit; also per arena.
- **Operationalisation.** `layer='rhetorical'` counts by `family`/`subtype`; ratio of
  SE-native subtypes (`opacity`, `hidden_extent`, `obscurity`) to canonical subtypes.
  **Per-arena rhetorical density must be token-normalised** (same correction as RQ1).
- **Contribution.** Extends a media-discourse metaphor inventory to a technical register.
- **Revision note.** The `opacity` construct appears in both the lexical (RQ1) and
  rhetorical (RQ3) inventories. Report the overlap explicitly rather than counting it twice;
  state which figure is counted where.

---

## RQ4 — Do the borrowed ignorance taxonomies transfer to SE artefacts, and where exactly do they fail?

*(restructured; replaces v0.1 RQ4 in full)*

v0.1 asked three sub-questions (a) populated categories, (b) residual, (c) collapse. The
crosswalk showed (c) is largely answerable without data, and that (a) is confounded by the
coding instrument's own priority order. RQ4 is therefore split into four sub-questions with
distinct evidentiary bases. **RQ4a requires no corpus. RQ4b–d require the hand-coded
sample.**

### RQ4a — How much can the borrowed taxonomies discriminate, on their own terms?
*(literature-level; no SE data)*

- **Question.** Across Roberts (2013), Smithson (1989/1993), Gross (2010), and Wehling
  (2024): which categories are mutually non-discriminating, which share labels while denoting
  differently-scoped concepts, and how evenly is each taxonomy evidenced in its own primary
  literature?
- **Unit.** Category pair; taxonomy.
- **Operationalisation.** Direct from `TAXONOMY_CROSSWALK.md` and `SOURCES_AUDIT.md`:
  count of relations by type (`near_synonym` / `partial_overlap` / `orthogonal` /
  `conflicting`); count and identity of `NONE_POSSIBLE` pairs; per-category
  `definition_confidence` distribution; per-taxonomy access level (full primary / partial /
  secondary only); and documented prior-breakage evidence from non-SE domains.
- **Contribution.** Establishes, independently of any corpus, that a substantial fraction of
  the imported conceptual apparatus cannot be applied discriminatingly by *any* coder in
  *any* domain — because three of the four traditions import the same Kerwin (1993)
  known/unknown-unknowns pairing without harmonising scope. This is the single most
  attack-resistant result in the paper: it survives every objection to sampling, annotation,
  and corpus composition.
- **Falsification condition.** If most cross-taxonomy pairs had admitted clean distinguishing
  tests, RQ4a would report a coherent, non-redundant conceptual field and the paper's
  framing would shift to RQ4b–d alone.
- **Revision note.** This absorbs the portion of old RQ4(c) that does not need data. What
  remains of (c) — whether the predicted collapse is *observable in coder behaviour* —
  becomes RQ4c below.

### RQ4b — Which taxonomic categories are populated by SE non-knowledge, and which receive no instances?

- **Question.** Under the pre-registered coding instrument, which of the 28 categories and
  3 Wehling dimensions receive instances in SE discourse, and which receive none?
- **Unit.** Hand-coded TextUnit (stratified sample).
- **Operationalisation.** Coverage counts from the **multi-fit pass**, not the primary-code
  pass. *This is a binding methodological requirement:* the manual's priority order (Roberts
  → Wehling → Smithson → Gross) means single-primary-code counts measure the tie-break rule,
  not the corpus. Wehling's three dimensions are scored on **every** codable unit,
  independently of the categorical code, since they are orthogonal axes rather than
  competing categories. Smithson coverage is computed **hierarchy-aware** (a unit coded
  `smithson.absence` also populates `incompleteness` and `error` as ancestors). Empty
  categories are reported as rule-of-three upper bounds (0/n → ≤3/n), never as "0".
- **Mandatory confound reporting.** Every zero or near-zero cell must be reported alongside
  that category's `definition_confidence` and its taxonomy's access level from
  `SOURCES_AUDIT.md`. A `low`-confidence, secondary-sourced, priority-last category
  receiving no instances is **not** evidence about SE discourse.
- **Contribution.** A coverage table for four ignorance taxonomies against a large technical
  corpus, with the instrument's own confounds quantified rather than hidden.
- **Revision note.** v0.1's "categories that receive ~zero SE instances (evidence the
  taxonomy is over-fit to non-SE domains)" was too strong an inference. Post-audit, thin
  sourcing is an equally plausible explanation and cannot be separated without a second
  corpus.

### RQ4c — Do the collapses predicted from the literature actually manifest in coder behaviour?

- **Question.** Do the `NONE_POSSIBLE` category pairs identified in RQ4a produce measurably
  elevated inter-coder disagreement when the instrument is applied to real SE units?
- **Unit.** Coded unit pair (two independent coders); category pair.
- **Operationalisation.** Agreement at the three granularities specified in
  `CODING_MANUAL.md` §6 (exact `type_id`, taxonomy-level, fit/non-fit), plus a
  **taxonomy-level confusion matrix**. Test the pre-registered predictions directly: P2
  (known/unknown-unknowns cluster shows high fit-agreement but low taxonomy-discrimination),
  P3 (the `roberts.errors` / `smithson.error` collision produces scope-artefact differences),
  P5 (Step-4/Gross arrival rate is low).
- **Contribution.** Converts a documentary claim about the literature (RQ4a) into a measured
  behavioural one: categories that cannot be distinguished on paper are shown to be
  indistinguishable in practice, by trained coders, on real data. RQ4a and RQ4c together are
  a substantially stronger argument than either alone.
- **Falsification condition.** If coders agree cleanly on `NONE_POSSIBLE` pairs, the
  predicted collapse does not manifest — an informative negative result suggesting coders
  supply a discrimination the sources do not.
- **Dependency.** Requires a second annotator, or a documented and defensible solo protocol.
  **This is the highest-priority open item in the project.** Under a solo protocol RQ4c is
  measurable only in weakened form (intra-coder test–retest), and the RQ must say so.

### RQ4d — What forms of SE non-knowledge fit no borrowed category, and is multi-actor non-knowledge the principal gap?

- **Question.** What fraction of codable SE units resist every category in all four
  taxonomies (RESIDUAL), what characterises them, and — the pre-registered structural
  hypothesis (P4) — is distributed / multi-actor non-knowledge, in which awareness of a gap
  is asymmetrically spread across identifiable parties in a threaded record, the dominant
  residual type?
- **Unit.** Hand-coded TextUnit; for the P4 sub-question, TextUnit **with parent-chain
  context**.
- **Operationalisation.** RESIDUAL rate over the **codable** denominator (excluding NOT_NK
  and UNCODABLE per P6), with a Wilson interval. Reported **twice**: as coded, and with
  catch-all absorption reversed — i.e. counting units flagged `residual_but_for` when the
  coder assigned `gross.ignorance` or a Smithson branch-level fallback. The gap between the
  two figures measures how much of the taxonomies' apparent coverage is carried by
  low-confidence catch-all categories, and is itself a reportable result. Residual units are
  then characterised (not defined) by marker-profile enrichment against corpus base rates.
  P4 is tested on a subsample where coders see the parent chain.
- **Contribution.** The paper's core positive claim: a named, quantified structural gap in
  the imported apparatus, grounded in a feature of SE communication platforms
  (asynchronous, multi-party, publicly threaded) that has no analogue in the interview,
  organisational, and media settings the taxonomies were built for.
- **Falsification condition.** A low residual rate that survives catch-all reversal would
  mean the taxonomies transfer better than predicted; P4 failing while the residual is
  otherwise large would mean the gap is real but mischaracterised.
- **Revision note.** v0.1 defined the residual via cluster membership. That is abandoned: a
  small cluster is a fact about KMeans geometry, not a claim about content. Clustering is
  demoted to sampling-frame construction, and the residual is defined and counted from the
  coded sample. This also removes the artefactual "99.9% coverage" figure that v0.1's
  operationalisation produced.

---

## RQ5 — Where do the linguistic markers and the trained classifier disagree, and what do the disagreements reveal?

*(unchanged from v0.1 in substance; one constraint made explicit)*

- **Question.** Partitioning TextUnits by (marker-positive?) × (classifier-positive?):
  (a) marker-positive / classifier-negative; (b) marker-negative / classifier-positive (the
  "unknown false negatives"); (c) what is each marker rule's precision against a
  hand-labelled sample, and how many rules clear a reliability threshold τ?
- **Unit.** TextUnit; plus a stratified hand-labelled validation sample.
- **Operationalisation.** 2×2 contingency; per-`rule_id` precision on the labelled sample;
  marker recall estimated by hand-labelling a random sample of classifier-positive units.
  Rules ≥ τ promoted to `status:active`.
- **Binding constraint (made explicit in v0.2).** The classifier is never used as a training
  target for marker weights, and marker weights are never fitted to reduce off-diagonal mass
  in the 2×2. The value of this RQ depends entirely on the two instruments remaining
  independently constructed. Where a continuous marker weight is needed, it is defined as
  hand-labelled per-rule precision, banded rather than continuous, since a sample of ~50
  units per rule does not support two-decimal precision.
- **Contribution.** A marker-reliability table plus a characterisation of implicit NK that
  neither approach captures.
- **Revision note.** Marker-positive units are defined by **active, current-version,
  non-contrastive** signals; the definition must be stated identically in RQ4's sampling
  frame and RQ5's 2×2, or the two analyses partition different populations.

## RQ6 — How do NK profiles differ across arenas and across communities?

*(scope narrowed — this is the most substantive non-RQ4 change)*

- **Question.** Do the issue-tracker arena and the mailing-list arena exhibit different NK
  marker distributions — in rate, in layer mix, and in taxonomic profile — and do
  communities cluster by NK signature?
- **Unit.** Arena; source (repository / list); community.
- **Operationalisation.** NK rate **per 1k tokens** and layer-mix vectors per arena and per
  source; test arena difference; cluster sources by NK-signature vector. Quotation segments
  excluded in mailing lists so quoted text does not double-count a prior author's NK.
- **Stated limitation (new in v0.2).** The current corpus does **not** implement the crossed
  project × channel design. The GitHub arena is a single repository (`python/cpython`); the
  nearest mailing-list counterpart (`gmane.comp.python.general`) is a *users* list, not
  `python-dev`, so the comparison is confounded with an audience contrast; and the largest
  list (`gmane.linux.kernel`) has no GitHub counterpart at all. **Until a genuine paired
  source is ingested, arena differences cannot be separated from project and audience
  effects, and the arena claim must be reported as descriptive rather than causal.**
- **Available within-project contrast (new in v0.2).** `gmane.comp.gis.qgis.devel` vs.
  `gmane.comp.gis.qgis.user` is a clean, same-project, same-channel **audience** contrast
  (developer vs. user). This is currently unexploited and should be reported: it tests
  whether NK marking tracks the medium or the speaker population, and is interpretable
  today without further ingest.
- **Contribution.** First cross-arena comparison of NK expression, with the confound stated
  rather than assumed away; plus a within-project audience contrast that is confound-free.
- **Revision note.** v0.1 asserted the crossed design as a property of the corpus. It is
  currently a property of the *plan*. Either the RQ narrows (as above) or the ingest must
  add `python-dev` and a second repository before the arena claim can carry its v0.1 weight.

---

## What changed from v0.1 (summary)

| v0.1 | change in v0.2 | driver |
|---|---|---|
| RQ1 | rates token-normalised; SE-native fraction reported at two granularities | length confound |
| RQ2 | unchanged | — |
| RQ3 | token-normalised; `opacity` double-count disclosed | length confound; internal consistency |
| RQ4 (single RQ, 3 parts) | split into **RQ4a–d**; (c)'s literature half promoted to a data-free RQ | crosswalk |
| RQ4(a) coverage | now from multi-fit pass; zero-cells reported with confidence + access level | priority-order and evidence-asymmetry confounds |
| RQ4(b) residual | defined from coded sample, not cluster membership; reported twice (catch-all reversal) | clustering degeneracy; `gross.ignorance` absorption |
| RQ4 (new) | **RQ4d** multi-actor NK promoted from prediction P4 to a question | structural gap in all four taxonomies |
| RQ5 | classifier-as-target explicitly prohibited; weight defined as banded per-rule precision | independence requirement |
| RQ6 | arena claim narrowed to descriptive; qgis devel/user audience contrast added | corpus is not yet crossed |

## Pre-registration status

RQ4a is answerable now from documents already delivered. RQ4b–d are blocked on the coded
sample and therefore on the second-annotator decision. Predictions P1–P6 in
`CODING_MANUAL.md` §7 were recorded before corpus contact and remain in force **unchanged**
— this revision reorganises which RQ each prediction reports under, and does not alter, add
to, or soften any prediction.

Instrument changes required before coding begins (each affects an RQ above, and each must be
fixed in `CODING_MANUAL.md` v0.2 *before* any unit is coded, not after):

1. Multi-fit pass promoted from optional (§5.5) to mandatory — RQ4b.
2. Wehling's three dimensions scored on all codable units, not as a Roberts fallback — RQ4b.
3. `residual_but_for` flag recorded whenever a catch-all category is assigned — RQ4d.
4. Parent-chain context supplied for the P4 subsample — RQ4d.
5. The manual's "31 codes, mutually exclusive and jointly exhaustive" corrected: 28
   categories plus 3 orthogonal dimensions; dimensions are not alternatives to categories.

## Two RQs worth *not* asking in this paper (scope discipline)

*(unchanged from v0.1)*

- **Temporal evolution of NK.** Territory of the next (graph-ML) paper. Ingesting it here
  would dilute the descriptive/critical contribution.
- **Causal effect of NK on project outcomes.** Needs an outcome variable and an
  identification strategy; out of scope for a descriptive-linguistic paper. Future work.

**Added in v0.2:**

- **Whether the taxonomies *should* be repaired.** Proposing a corrected or merged ignorance
  taxonomy for SE is a natural next move and will be tempting once RQ4d names the gap. It is
  a separate paper: it requires validating the proposed categories on a second corpus, and
  attempting it here would convert a falsifiable measurement study into an unfalsifiable
  proposal. State the gap; do not fill it.
