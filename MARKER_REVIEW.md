# Linguistic Marker Review — GraphRAG-NK (v0.1 → v0.2)

*A literature-grounded audit of the four annotator pattern/lexicon files, in three parts as requested:*
*(1) markers missing from the linguistic literature, (2) markers misinterpreted or mis-integrated, (3) an extension strategy that reduces both false negatives and false positives.*
*Every recommendation is pinned to a source; new markers are supplied in the existing YAML format in the `*_v0.2.yml` files.*

---

## 0. The one issue that cuts across all four files: **cue ≠ scope**

Your own diagnosis — "each pattern is a few words … creating unknown false negatives … and potentially false positives too" — is exactly the **cue/scope distinction** that organises the entire uncertainty-detection literature you already cite:

- **BioScope** (Vincze et al. 2008) annotates two things per instance: the **cue** (the keyword) *and* its **scope** (the span of text the cue makes uncertain/negated). The cue alone is deliberately treated as insufficient.
- The **CoNLL-2010 shared task** (Farkas et al. 2010) split the problem into *Task 1: detect that a sentence is uncertain* and *Task 2: resolve the in-sentence scope of each cue*. Task 2 exists precisely because "there is a cue word" and "this proposition is marked as non-knowledge" are different claims.
- **Morante & Sporleder (2012)** frame modality and negation as **scope phenomena**: a cue has a *focus* and a *scope*, and computational treatment that ignores scope conflates unrelated readings.

v0.1 implements the **cue half only**. Concretely, that produces the two error modes you predicted:

| error | mechanism | example that fires in v0.1 but shouldn't (FP) / should but doesn't (FN) |
|---|---|---|
| **False positive** | cue fires regardless of what it scopes over | `morph.neg.adverbial_not` on *"do **not** rebase onto main"* (imperative, no NK); `morph.mod.epistemic` "can" on *"you **can** run the tests locally"* (ability, not epistemic) |
| **False negative** | the NK is carried by a construction with no seed keyword | *"I have **no clue** why CI is red"*, *"**works on my machine**"*, *"can't **repro**"* — none match any v0.1 rule |

**The single highest-value upgrade is not more keywords — it is adding scope.** Sections 1–3 below add keywords *and* specify the scope/context each needs. The pattern-schema extension that makes scope expressible in YAML (a `context`/`scope` block, compiled to spaCy `DependencyMatcher`) is in §4; it is backward-compatible — existing `Matcher` rules keep working.

A useful mental model, borrowed from Prince, Frader & Bosk (1982): a hedge is a **shield** (it modifies the *speaker's commitment* to a proposition: "I think", "probably") or an **approximator** (it modifies the *proposition's content*: "sort of", "about"). Shields need a proposition to shield; approximators need a term to approximate. Neither is a bare word — both are a word **plus a target**. That is the scope you are missing.

---

## 1. Missing markers (with sources and where they go)

Ordered by expected impact on recall. Full YAML entries are in the v0.2 files; the class summaries here explain *why* each belongs.

### M-1 — First-person epistemic predicates of not-knowing  ⬅ **largest single gap**
v0.1's lexicon captures NK adjectives (`uncertain`, `unclear`, `vague`) and nouns (`doubt`, `ignorance`) but almost **no verbs of (not-)knowing**, which is how NK is most often expressed in conversation. This is the **"Unknowing"** category of the KUB framework (Knowing / Unknowing / Believing; Bongelli & Zuczkowski and colleagues) and the *doubt* pole of Rubin's (2007) certainty scale.
- `I don't know` / `IDK` / `dunno` / `no idea` / `no clue` / `not sure` / `unsure` / `can't tell` / `hard to tell` / `hard to say` / `who knows` / `beats me` / `I'm lost` / `I'm confused` / `I don't get it` / `I can't figure out` / `I can't wrap my head around`.
- Mechanism: negated or interrogative **cognition verbs** (`know, understand, tell, figure out, get, follow, grasp, recall, remember`) with a first-person (or impersonal *it*) subject.
- Goes to: lexicon `prototype/epistemic_state` (fixed phrases) **and** a new morpho-syntactic rule family `epistemic_verb` with scope = *negation/interrogative over cognition verb + 1st-person subject*.
- Source: Bongelli & Zuczkowski (KUB); Rubin 2007; Prince et al. 1982 (shields).

### M-2 — Epistemic lexical verbs / plausibility shields
The most frequent hedges in informal discourse, and the backbone of Hyland's (1998) hedging inventory: `I think`, `I believe`, `I guess`, `I suppose`, `I assume`, `I suspect`, `I reckon`, `I feel like`, `my understanding is`, `presumably`, `as far as I can tell`. v0.1 has only `suggest`/`indicate` — and mislabels them as *modality* (see C-7).
- Goes to: new morpho-syntactic family `hedging/epistemic_verb`; scope = verb governs a complement clause (the shielded proposition).
- Source: Lakoff 1973; Prince et al. 1982; Hyland 1998; Salager-Meyer 1994.

### M-3 — Evidential / attribution markers
A distinct epistemic dimension from hedging: **source of knowledge** rather than degree of certainty (Aikhenvald 2004). `apparently`, `seemingly`, `supposedly`, `reportedly`, `allegedly`, `I've heard`, `I read somewhere`, `according to`, `based on`, `from what I can tell`, `it looks like`, `sounds like`. v0.1 captures only `seem`/`appear` and files them under modality.
- Goes to: new family `evidential` (inferential vs. reportative subtypes).
- Source: Aikhenvald 2004; San Roque et al. 2015; Prince et al. 1982 (attribution shields).

### M-4 — Interrogative NK constructions beyond a bare "?"
`morph.syn.question_mark` fires on any `?`, which cannot distinguish an information-seeking question (NK) from a rhetorical question, a code snippet, or a checklist. The literature on interrogativity and epistemic stance (San Roque et al. 2015; Bongelli et al.) treats **indirect/embedded** questions as the reliable NK signal:
- `whether`, `if … or`, `I wonder (whether/if/why/how)`, `not sure (why/how/if)`, `any idea (why/how)`, `how come`, `no idea (what/why)`, tag questions (`…, right?`, `…, no?`).
- Goes to: new `syntactic_pattern/embedded_question` and `syntactic_pattern/tag_question`; keep the raw `?` rule but **demote it to a co-occurrence feature**, not a standalone NK signal.
- Source: San Roque et al. 2015; Bongelli et al.

### M-5 — SE-native realisations of NK  ⬅ **your paper's "where taxonomies break" contribution**
The borrowed taxonomies were built on science/policy/news prose; SE discourse lexicalises NK in ways none of them anticipate. These are exactly the items RQ4 needs:
- **Reproducibility/observation gaps:** `can't reproduce`, `no repro`, `works on my machine`, `WOMM`, `flaky`, `heisenbug`, `intermittent`, `non-deterministic`, `can't repro locally`.
- **Opacity:** `black box`, `magic`, `it just works`, `voodoo`, `cargo cult`, `spooky`, `smells` (code smell → intuition-without-proof).
- **Specification/documentation gaps:** `undefined behaviour`, `unspecified`, `underspecified`, `undocumented`, `implementation-defined`, `not documented anywhere`, `unclear from the docs`.
- **Code-comment NK markers:** `TODO`, `FIXME`, `XXX`, `HACK`, `NOTE:`, `???` (esp. relevant if commit diffs/comments are ingested).
- **Abbreviated hedges (register-specific):** `IIRC`, `AFAIK`, `AFAICT`, `TBH`, `IANAL`-style disclaimers, `¯\\_(ツ)_/¯`.
- Goes to: lexicon `shared_feature` (with SE subcategories, extending your existing `flaky`/`undefined_behaviour`/`undocumented` seeds) + a small SE-idiom fixed-phrase set.
- Source: SE extension — flag `scope: derived` per your framework's own convention; ground the *type* in Smithson/Roberts once observed.

### M-6 — Boosters / certainty markers (the contrastive pole)
Hyland models stance as **hedges + boosters**; you cannot characterise NK expression without its opposite. `obviously`, `clearly`, `definitely`, `certainly`, `of course`, `no doubt`, `undoubtedly`, `for sure`, `always`, `guaranteed`. These are **not NK**, but they are essential for RQ5 (a booster co-occurring with a hedge is a marked mixed-stance case) and as a precision control.
- Goes to: new layer-neutral category `stance/booster`, explicitly flagged `polarity: certainty` (non-NK).
- Source: Hyland 2005; Rubin 2007 (certainty pole).

### M-7 — Vague language / general extenders
Discourse-level approximation (Channell 1994): `and so on`, `etc.`, `or something`, `or whatever`, `stuff like that`, `-ish` suffix, `some sort of thing`, `you know`.
- Goes to: `hedging/vagueness`.
- Source: Channell 1994; Lakoff 1973.

---

## 2. Misinterpretations & mis-integrations (corrections)

### C-1 — The epistemic/deontic modal split is linguistically unsound as a **lexical** rule
`morph.mod.epistemic = {can, could, may, might, would}` and `morph.mod.deontic = {must, should, shall, ought}` assign modal *sense by lemma*. Modals are **polysemous and context-determined** (Hyland 1998; Vold 2006; Morante & Sporleder 2012):
- `can`/`could` are overwhelmingly **dynamic/ability** or **root-possibility** ("you *can* run it", "*could* you check"), only marginally epistemic → this rule is a large FP source.
- `must` has a strong **epistemic** reading ("that *must* be why it fails") that the deontic-only assignment misses → FN.
- `would` is mostly **conditional/hypothetical**, not epistemic.
- `may`/`might` are the clearest epistemics but are diluted by being bucketed with `can`.
- **Missing:** epistemic `will`/`'ll` (prediction).
**Correction (v0.2):** stop asserting sense from the lemma. Either (a) rename the category `modality (sense-underspecified)` and resolve sense at analysis time, or (b) require an epistemic **context** for the epistemic label — modal + stative/perception/cognition verb, `must/might/could + be/have + …`. v0.2 keeps `may/might` as high-confidence epistemic, moves `can/could/would` to `modality/underspecified` (low weight), and adds epistemic `will`.

### C-2 — `-able` as `affix_modality` mis-grounds the suffix
`-able` derives **dynamic/potential** modality (capability): `reproducible`, `testable`, `configurable`, `serializable` — none of these are non-knowledge. Treating every `-able` adjective as an NK modality marker is a systematic FP generator with no support in the NK literature. Only a small set carries NK: `questionable`, `debatable`, `unpredictable`, `undecidable`, `unknowable`, `unverifiable`, `unfalsifiable`.
**Correction (v0.2):** remove the blanket `-able` scan; replace with an **allowlist** of NK-relevant deverbal adjectives, and relabel from `affix_modality` to `shared_feature/epistemic_potentiality`.

### C-3 — Raw negation is not non-knowledge
`morph.neg.*` fires on all `not/never/no/n't`. But negation marks NK **only when its scope is a cognition/epistemic predicate or an epistemic existential** — this is why Vincze et al. (2008) annotate *negation* and *speculation* as **separate** layers. *"This does **not** work"* is negation, not NK; *"I do **not** know"* / *"**no** evidence"* / *"can**'t** tell"* is NK.
**Correction (v0.2):** negation cues become **scoped** — a negation Signal is NK-relevant only when it governs/attaches to an epistemic target (`know, sure, clear, idea, clue, evidence, repro, reason, explanation`). Standalone negation is retained as a **low-weight modifier** that upgrades an adjacent epistemic cue, not as a standalone NK signal. (This is the biggest precision win available.)

### C-4 — `morph.tense.past_nk_yet` is a buggy pattern
```yaml
pattern: [{LOWER: "not"}, {LOWER: "yet", OP: "?"}, {LOWER: "yet"}]   # requires TWO 'yet' tokens
```
This matches *"not yet yet"*. The intended *"not … yet"* is discontinuous ("we haven't fixed this **yet**") and needs either a gap-tolerant token pattern or a dependency rule. Also `yet` is claimed by **two** rules (`tense.past_nk_yet` and `syn.adversative_however`), so every adversative `yet` double-fires as past-tense NK.
**Correction (v0.2):** replace with a dependency pattern (negated verb + `advmod:yet`); remove `yet` from the adversative list (keep `however/although/though/nevertheless`).

### C-5 — `kind of / sort of` is triple-counted under the same function
It appears in `morpho_syntactic` (`hedging/approximator`) **and** `rhetorical` (`comparison/approximator`) with the *same* functional label. Unlike the `blind spot` double-count (which is intentional — *fixed_phrase* vs *metaphor* are genuinely different functions), this is redundant.
**Correction (v0.2):** keep `kind of/sort of` in the **hedging** layer only; remove the duplicate `rhetor.comparison.kind_of`. Keep `rhetor.comparison.something_like` (distinct: explicit comparison figure).

### C-6 — `seem`/`appear` are evidential, not modal
They express **inference from appearance** (Aikhenvald 2004), a distinct dimension. **Correction:** move to the new `evidential/inferential` family.

### C-7 — `suggest`/`indicate`/`tend` mis-bucketed as `quasi_modal`
`suggest`/`indicate` are **epistemic/evidential lexical verbs** (reporting an inference), not modals; `tend` encodes **frequency/disposition**, not NK at all. **Correction:** reassign `suggest`/`indicate` to `evidential/inferential`; drop `tend`.

### C-8 — Over-broad blocklists introduce false negatives
`under` on the `un-`/prefix blocklist kills the genuine NK forms **underspecified / underdocumented / underdetermined**. **Correction:** the affix approach should match against a *stem* after stripping, not blocklist whole surface strings; at minimum, remove `under` from the blocklist and instead allowlist the NK `under-` compounds.

### C-9 — Adversative `but`/`however` as a standalone NK signal is very low precision
`but` is among the highest-frequency English tokens; as an NK cue it requires the epistemic-contrast frame (assertion + hedge/negation across the connective). **Correction:** demote to a **co-occurrence feature** that only counts when an epistemic cue is present in the same clause pair — not a standalone Signal.

### C-10 — Several lexical "prototypes" denote hazard/defect/dispute, not NK
`risk` (hazard/decision-under-uncertainty), `bug`/`error` (defect), `controversy` (disagreement) are **NK-adjacent but not NK**. You already flag `bug`/`error` as "verify." **Correction:** demote all four to `shared_feature` requiring an epistemic context marker, or drop from the NK layer; `controversy` is better modelled as *disagreement* than *non-knowledge* (a distinction your RQ4 should make explicit).

---

## 3. Extension strategy — from "a few words" to defensible, calibrated patterns

A repeatable method that directly manages the FP/FN trade-off you raised, in five steps:

1. **Complete the cue inventories from the published lists.** For each cue class, expand the seed to the union of the standard inventories — BioScope cue list, CoNLL-2010 cues, Hyland's hedge/booster lists, Prince's shield/approximator sets. (Done for the high-value classes in the v0.2 files; the remainder is a mechanical merge you can finish.)
2. **Disambiguate by POS + lemma + morphology** (v0.1 already does some of this — extend it: `no` only as `DET`, cognition verbs only as `VERB`, etc.).
3. **Add scope via dependency parsing.** A cue emits an NK Signal only when it stands in the right grammatical relation to an NK target or a first-person subject. This is the FP-killer and the FN-reducer at once (it lets you match *constructions*, not word lists). §4 gives the schema.
4. **Model cue interaction:** negated hedges (`not unclear` → cancels), double negation, and — already handled at extraction — cues inside quotes/code. Add: cue inside a `>` quote is excluded (you strip these) but cue inside inline back-ticks should be excluded too.
5. **Calibrate empirically, then freeze.** Because every Signal carries `rule_id` + provenance in the graph, hand-label a stratified sample (≈50–100 units/rule), compute **per-rule precision**, and promote/demote: rules ≥ τ (say 0.7) become `status: active`; below → `status: candidate` (kept in the graph, excluded from headline counts). This operationalises your existing "verify in first pass" notes as a number, and it is reportable in the paper as a marker-reliability table. This is also the honest answer to *"unknown false negatives"*: recall can be **estimated** by annotating a random sample of NK-positive units (per the classifier) and measuring how many carry ≥1 marker.

**Recommended precedence when the same span matches multiple layers** (for analysis, not ingest — ingest keeps all Signals): scoped-epistemic-verb > evidential > hedge-adverb > modal-epistemic > affix > bare-negation. Encode as a `weight` field so downstream scoring is explicit rather than implicit in match order.

---

## 4. Backward-compatible schema extension for scope

Add an optional `context` block to any pattern. If absent, the rule behaves exactly as v0.1 (a bare `Matcher`). If present, the annotator compiles a `DependencyMatcher` requiring the grammatical relation. Illustrative:

```yaml
- id: "morph.epi.neg_cognition"
  layer: "morpho_syntactic"
  category: "epistemic_verb"
  subcategory: "not_knowing"
  source: "Bongelli & Zuczkowski (KUB); Rubin 2007"
  type: "DependencyMatcher"
  weight: 1.0
  pattern:
    - RIGHT_ID: "verb"
      RIGHT_ATTRS: {LEMMA: {IN: ["know", "understand", "tell", "figure", "grasp", "recall"]}}
    - LEFT_ID: "verb"
      REL_OP: ">"
      RIGHT_ID: "neg"
      RIGHT_ATTRS: {DEP: "neg"}          # scope: the verb must be negated
    - LEFT_ID: "verb"
      REL_OP: ">"
      RIGHT_ID: "subj"
      RIGHT_ATTRS: {LOWER: {IN: ["i", "we"]}, DEP: "nsubj"}   # 1st-person subject
```
This single rule captures *"I don't know", "we can't tell", "I couldn't figure … out"* — three constructions that need **zero** additional keywords — while **not** firing on *"the linter knows about this"*. That is the whole thesis of the review in one rule: scope buys recall and precision simultaneously.

The v0.2 files add such rules where they matter most (M-1, M-2, C-3) and leave the low-risk lexical rules as plain `Matcher`.

---

## 5. Summary of changes shipped in the v0.2 files

| file | added | corrected | net effect |
|---|---|---|---|
| `en_core_v0.2.yml` | M-1 phrases, M-2 shields, M-3 evidentials, M-5 SE idioms, M-6 boosters, M-7 extenders | C-10 demotions (risk/bug/error/controversy) | lexicon ~30 → ~95 entries; NK-precision items separated from NK-adjacent |
| `morpho_syntactic_v0.2.yml` | `epistemic_verb`, `evidential`, `embedded_question`, `tag_question` families; scoped-negation rules | C-1 modal split, C-3 negation scope, C-4 `not…yet` bug, C-7 suggest/indicate, C-9 adversative demotion | precision-first; scope via DependencyMatcher |
| `rhetorical_v0.2.yml` | opacity/`black box`, fog, depth, rabbit-hole, iceberg, can-of-worms families | C-5 kind-of dedup | SE-relevant metaphors added |
| `word_formation_v0.2.yml` | `mis-` prefix, `under-` NK compounds, `-free` privative | C-2 `-able` allowlist+relabel, C-8 blocklist fix | far fewer affix FPs |

All four keep the exact v0.1 field structure (plus the optional `weight`/`context`/`status` fields, which the loader can ignore until the annotator supports them). Version strings bumped to `0.2`; change logs appended.

---

## 6. v0.2.2 — cross-layer ownership (2026-10-07)

After v0.2 shipped, a follow-up pass removed the remaining overlap between the
lexical and morpho-syntactic layers and pruned rules that failed in pilot use.
The organising principle is **form-based ownership**:

> A marker whose NK reading is produced by a grammatical operator (negation, a
> 1st-person subject + complement clause, a modal) belongs to the
> **morpho-syntactic** layer, where scope is enforced. A marker whose NK meaning
> is lexicalised in the item itself stays in the **lexical** layer.

**Demotions (active → candidate), with the new owner.** `not_sure`,
`not_clear_to_me`, `no_idea`, `no_clue` → `morph.neg.scoped_epistemic`;
`dont_know` → `morph.epi.neg_cognition`; `cant_tell` →
`morph.epi.neg_cognition_modal`; `guess_v`, `suppose_v`, `assume_v`, `suspect_v`,
`reckon_v` → `morph.hedge.shield_think`. Retained active lexicalised items:
`unsure`, `clueless`, `confused`, `idk`, `who_knows`, `hard_to_tell`,
`hard_to_say`.

**Matching changes.** `morph.neg.scoped_epistemic` gained the copular
realisation `be + not + sure/clear` — the old pattern required the negator to be
a direct child of the adjective, but spaCy attaches it to the copula, so the
most frequent form ("I'm not sure") was never matched. `morph.hedge.shield_think`
gained pro-form ("I guess so") and `suspect + NP` realisations.
`morph.epi.neg_cognition_ascribed` (negated know/understand with a non-1st-person
subject) was added as a **candidate**: self-attributed (KUB "Unknowing") and
other-attributed NK are kept in separate subcategories so they are never pooled.

**Narrowing (stale-span guards).** `future_nk_wont_know` dropped
`can't/cannot` (now owned by the modal rule); `neg_cognition_modal` dropped the
`wo` auxiliary; `spatial.uncharted` dropped `terra incognita`. Because the rule
definitions changed *in place* under the same `rule_version`, the pre-change
spans survive as ghosts and are excluded at analysis time (same policy as M-4's
2026-10-03 fix), not purged.

**Removed (pilot failures and superseded duplicates).** The M-5 SE-native
lexical set (repro/spec/doc/opacity/code-comment), M-6 booster lexical items,
M-7 general extenders, the C-10 hazard/defect terms, and the `iirc`/`afaik`
abbreviations were removed from the lexicon; `black_box`, `iceberg`, `fog`,
`magic`, `rabbit_hole`, `can_of_worms` from the rhetorical layer; the
candidate modifier rules `morph.neg.bare_modifier`, `morph.neg.quantifier_no_det`
and `morph.syn.question_mark` from the morpho layer. The
`opacity`/`blind_spot`/`knowledge_gap` lexical duplicates are gone, but their
rhetorical counterparts remain — no net loss for those phenomena.

**Application.** Status flips and removals are applied analysis-side (the
canonical predicate resolves rule sets from the current YAMLs). Only the widened
realisations need a graph write, done by the spaCy-only, bounded
`scripts/backfill_morpho_gap.py`. See CHANGELOG 2026-10-07 for the full
rationale and the dry-run counts.

