# CHANGELOG.md

## 2026-10-16 — Fig A split into four per-layer figures (RQ3.7)

`notebooks/02b_rq_analysis.ipynb` cell 50 (Figure A, composition/dominance) now
emits **four standalone figures** — one per `LAYER_ORDER` layer — each exported
via `_export_fig` as `notebooks/figs/fig_genre_composition_<layer>.{pdf,png}`
(the single 2×2 composite was previously shown but *not* stored; `_export_fig`
was commented out). This lets each layer be placed independently in the paper.
Per-panel content, ordering, palette, and legend are unchanged; each figure is
`figsize=(4.0, 7.0)`. Verified against a synthetic counts CSV: all four figures
render and export with the expected names.

**Fig B layer grouping.** Cell 51 (Figure B, fingerprints) now draws a light-grey
horizontal rule (`#94A3B8`, `lw=0.8`) at each layer transition, grouping the
subcategory rows into their four linguistic-phenomenon blocks, and prints the
`LAYER_LABEL` for each block on the **far right** of the last facet — clear of the
subcategory tick labels on the left. Row order, marker semantics, and export call
are unchanged. Verified against a synthetic fingerprint frame: all four
phenomenon labels appear on the right and the figure renders/ exports unclipped.

## 2026-10-15 — Genre & dataset composition of linguistic ignorance (RQ3.7)

**New extraction module.** `scripts/genre_composition.py` pulls the per-
(dataset, layer, subcategory, rule) NK-signal counts that back the new RQ3.7
section in `notebooks/02b_rq_analysis.ipynb`: within-layer *composition* shares
(Fig A — dominance: what a genre's NK is mostly made of) and *fingerprint*
effects vs. the equal-weight reference composition (Fig B — distinctiveness),
plus a rule-level driver table/CSV. Read-only; writes
`notebooks/genre_composition_counts.csv` (two granularities in one file). The
notebook only reads the cache, so figure iteration never re-queries.

**Decision — hits are the primary count basis; the rule set is active+candidate.**
The four rule layers are kept separate (each is its own composition; never
pooled). `word_formation` has **zero active rules** (all nine are `candidate`),
so an active-only filter would make that layer empty; the default `--ruleset
valid` (active + candidate) keeps all four layers visible, with `--ruleset
active` as the RQ1/RQ2-headline robustness variant. Subcategory *hits* equal the
sum of their rule hits (every Signal carries exactly one rule), so the primary
figure needs a single pass; distinct-unit counts (`--with-units`) are a second,
optional pass. Composition shares are shares of *subcategory incidences* (a unit
with two subcategories contributes twice), stated in the caption — not "NK
units".

**Cypher efficiency (the historical notebook shape timed out).** The old cell
shape `MATCH (u)-[:HAS_SIGNAL]->(s:Signal {layer: ...})` makes the planner seed
from the `Signal(layer)` index — **83.8 M morpho-syntactic signals** — and timed
out at >120 s even for two corpora. The module instead seeds from the indexed
`Artefact.source_corpus` with a scalar corpus equality and keeps the path in one
MATCH (measured: disco ≈ 2 s, alternative-jira ≈ 50 s for all rule layers; the
two 14 M-unit corpora dominate). `p.corpus_id` is unindexed — `source_corpus` is
the indexed twin with identical values (`ontology.cypher` writes both). The full
refresh is ~2–5 min and is handed to the user (AGENTS.md §5.11).

**Genre naming.** 02b keeps `tracker/email/chat/qa`; `scripts.corpus_census.py`
uses `review_email`. The module aliases `review_email → email` and leaves a
`TODO(design-review)` for the standing 02b ↔ census drift (CHANGELOG 2026-10-03).

**Flagged, not fixed.** The pre-flight contamination checks the source plan
proposed (`lex.unknown`/`lex.unresolved` as pasted-software output, `lex.unsure`
as an issue-template phrase) are **skipped for now**, so the figures are
provisional on that question. The `tag_question` concern was checked and
downgraded: `?` survives chat preprocessing (gittercom 6,481; livechat-gitter
3,325; preethac 664; kummerfeld 64) — only disco is low (5). OpenMent is a
role-labelled dataset and NumFOCUS is title-only; both sit inside the `tracker`
genre and are footnoted in the section, not excluded.

**Tests.** `tests/test_genre_composition.py` (12 DB-free tests: 02b genre
mapping, rule→subcategory collapsing incl. layer scoping, distinct-unit join,
share normalisation, equal-weight genre/reference means, and the
`consistent_driver`/`single_dataset`/`low_count` flags). `ruff check`/`format`
clean on the script and tests. The seven new notebook cells were executed
end-to-end against a synthetic counts CSV (all cells run; figures render).

**Not run.** The full 11-corpus refresh against Neo4j is handed to the user
(multi-minute; AGENTS.md §5.11).

## 2026-10-07 — v0.2.2 cross-layer ownership: live filtering + targeted morpho backfill

**Rule-file revision (user).** `lexicons/en_core_v0.2.yml` and
`patterns/morpho_syntactic_v0.2.yml` were revised to remove overlap between the
layers and refresh the literature. Net effect vs HEAD: **39 lexical rules
removed, 13 lexical status flips, 6 rhetorical figures removed, 3 morpho rules
removed, 1 morpho rule added, 5 morpho rules with changed matching**, `weight`
removed/commented throughout, and a rebuilt citation list (verified records).
A `2.2` change-log block inside each YAML documents the ownership principle:
a marker whose NK reading is produced by a grammatical operator (negation,
1st-person subject + complement clause, modal) belongs to the morpho-syntactic
layer, where scope is enforced; the lexical layer keeps lexicalised items.

**Decision — hybrid, not pure live filtering (user, 2026-10-07).** The canonical
predicate resolves `active`/`candidate` *live from the current YAMLs*
(`scripts/openment_roles.py:60+`), so status flips, promotions and outright rule
removals already take effect analysis-side with **no graph write** — the same
mechanism as the 2026-10-03 `embedded_question` decision. Two things that
filtering cannot do were identified and handled explicitly:

1. **Narrowed rules leave ghosts (over-count).** `morph.tense.future_nk_wont_know`
   dropped `can't/cannot`, `morph.epi.neg_cognition_modal` dropped the `wo`
   auxiliary, and `rhetor.metaphor.spatial.uncharted` dropped `terra incognita`.
   Their pre-change spans survive under the same `rule_version`. Added to
   `STALE_SIGNAL_EXCLUSION` (`scripts/openment_roles.py`) — each guard is scoped
   by `rule_id` AND a property of the stale span only (`STARTS WITH 'wo'` /
   `'terra'`), so retained matches are untouched. Mirrored into
   `notebooks/02_rq_analysis.ipynb`, `02b_rq_analysis.ipynb`,
   `03_rq_analysis.ipynb` (20 inline copies) and the defensive guard in
   `scripts/export_threads_docx.py`.
2. **Widened rules have missing matches (under-count).** `morph.neg.scoped_epistemic`
   gained a copular realisation (`be + not + sure/clear`) and
   `morph.hedge.shield_think` gained pro-form / NP realisations. These are the
   NK replacement for the demoted `lex.not_sure`/`lex.not_clear_to_me` (and the
   shield verbs). Filtering cannot add signals, so a **targeted, spaCy-only
   backfill** was written: `scripts/backfill_morpho_gap.py`. It re-parses only
   the units carrying the two rules with a genuine gap (dry-run count:
   **337,791 units**, down from **1,215,154** for the full demoted set — the
   other demotions are pure de-duplication because the old morpho patterns
   already fired), runs `SpacyMorphoAnnotator` only (no RoBERTa, no
   `ClassifierVerdict`, no Redis), and MERGEs the target signals idempotently.
   Dry-run by default; the user runs `--execute` (AGENTS §5.11).

**Not purged.** The 39 lexical + 6 rhetorical + 3 morpho removed rules leave
ghost `:Signal` nodes, excluded live by `rule_id` membership. No mass
`DETACH DELETE` on the external-drive store (the documented slow path).

**Versioning.** `version:` stays `"0.2"` and `settings.pattern_set_version`
stays `"0.2"` on purpose: `NK_SIGNAL_PREDICATE` requires
`s.rule_version = $rule_version`, so bumping to `0.2.2` would exclude **all**
existing signals and silently empty the analysis. 0.2.2 is an in-place
refinement, like 0.2.1.

**Also.** `rules/categories.yml` regenerated from the YAMLs (adds
`not_knowing_ascribed`; prunes retired categories). `tests/test_word_formation_rules.py`
`test_dependency_matcher_patterns_are_well_formed` fixed to handle the `patterns:`
(plural) key added in 0.2.1 — the suite was failing with `KeyError: 'pattern'`.
Lexicon header NOTE corrected (it claimed "status-only", but the working tree
also removes 39 entries).

**Verified.** `pytest tests/test_word_formation_rules.py tests/test_export_threads_docx.py`
→ 14 passed. `ruff check`/`format` clean on `scripts/openment_roles.py`,
`scripts/backfill_morpho_gap.py` and `tests/test_word_formation_rules.py` (see the
pre-existing debt note below for `scripts/export_threads_docx.py`).
`scripts/smoke_annotate.py` confirms the new logic: `"I'm not sure"` →
`morph.neg.scoped_epistemic` (active) + `lex.not_sure` (candidate);
`"I think so"` / `"I suspect a race condition"` → `morph.hedge.shield_think`;
`"won't know"` no longer fires on `can't/cannot`.

**Observed, pre-existing (not fixed here).** `tests/test_gmane_ingester.py`
fails to import (`_group_prefilter_bytes` no longer exists in
`miner/gmane_ingester.py`) — unrelated to this change. `scripts/export_threads_docx.py`
carries pre-existing ruff debt (`UP035`/`UP045`/`B905`) outside the edited block.

## 2026-10-03 — Genre-stratified random NK-unit sampler (100 units)

**New export tool.** `scripts/sample_units_by_genre.py` draws 25 TextUnits per
communicative genre (tracker / review_email / chat / qa = 100) that carry at
least one active non-classifier NK marker, and writes a CSV **and a formatted
`.xlsx`** (`notebooks/genre_sample_100.csv` / `.xlsx`, overridable with `--out`
/ `--xlsx-out` / `--no-xlsx`) with unit metadata,
the unit text, the **raw source document** fetched from MongoDB (issue/PR body,
email, chat message, SO post — with comments for issue-like artefacts), the
total marker count, per-layer counts (`n_lexical` / `n_morpho_syntactic` /
`n_word_formation` / `n_rhetorical`), the contributing `rule_id`s, and whether
the source was found/truncated. No highlighting (CSV of raw text, not docx).

**Sampling method.** Uniform random within genre. Naive `ORDER BY u.id LIMIT n`
is deliberately avoided (ids are corpus-prefixed, so it would pick one corpus
per genre); instead a seed-derived prefix over the indexed, uniform
`TextUnit.sha256` selects an index-backed random subset. Reproducible via
`--seed 20261003`; `--dry-run` prints candidate/pool counts and the pool
`EXPLAIN`. Read-only: writes nothing to Neo4j or Mongo.

**Decision — OpenMent is a *tracker* corpus (user, 2026-10-03).** OpenMent is
GitHub-shaped (issues/PRs), so it is grouped with tracker rather than standing
as its own genre or the stale `email`/`mentor_mentee` registry value, enabling a
later OpenMent-vs-other-tracker comparison. The canonical mapping now lives in
`scripts/corpus_census.py` (`GENRE_BY_CORPUS`, `GENRES`, `genre_of`,
`corpora_by_genre`): tracker = apache-jira, alternative-jira, numfocus, openment;
review_email = curated-email-code-reviews; chat = kummerfeld-irc, preethac-slack,
disco, gittercom, livechat-gitter; qa = sotorrent.

**Flagged, not fixed (design-review pass).** `notebooks/03_rq_analysis.ipynb`
(and `02b`) carry their own genre registries that still emit `email` /
`mentor_mentee`; they now disagree with `GENRE_BY_CORPUS`. A
`TODO(design-review)` note is left in the new script. The marker predicate and
active rule set are imported verbatim from `scripts/openment_roles.py`, so the
sampler cannot drift from the canonical analysis definition.

**Tests.** `tests/test_sample_units_by_genre.py` (26 DB-free tests: registry,
sha256-prefix draw, prefix-length choice, seeded order-independent selection,
per-kind source reconstruction, Mongo source routing, layer aggregation, and the
Excel control-char/length sanitizer + xlsx round-trip).
`ruff check` / `ruff format` clean. Not run: the full candidate-count scan is
handed to the user (AGENTS.md §5.11).

**Observed, pre-existing.** `tests/test_word_formation_rules.py::
test_dependency_matcher_patterns_are_well_formed` currently fails because the
M-4 fix moved `morph.syn.embedded_question` to the plural `patterns:` key while
the test still reads `pattern:`. Unrelated to this change; not fixed here.

## 2026-10-03 — M-4 fix: `morph.syn.embedded_question` scoped by DependencyMatcher

**Bug (user-reported from exported threads).** `morph.syn.embedded_question`
was a spaCy `Matcher` whose *head* token carried `OP: "?"` (optional), so the
rule fired on every bare `if/how/when/which/what/where/why/whether` in the
corpus. Live count: **21,597,420** signals, of which only ~60k are multi-word
(`wonder if`, `unclear how`, …) — **~99.7% single-token false positives**.

**Fix.** `patterns/morpho_syntactic_v0.2.yml`: the rule is now a
`DependencyMatcher` with two stand-alone realisations — (a) verb `wonder` +
wh/if clause, (b) copula + `unclear`/`unsure` + wh/if clause. `which`/`when`
are dropped (relative pronoun / temporal subordinator, not interrogative
complements). The loader (`annotators/morpho_syntactic.py`) now accepts
`patterns:` (plural) for multi-realisation rules; `pattern:` (singular) still
works. Verified with `scripts/smoke_annotate.py`: "wonder if" and
"is unclear how" fire; a leading conditional "If we assume…" does not.

**Also.** `morph.mod.underspecified_cancould` was found `active` in the YAML,
contradicting the 2026-09-21 decision; it is demoted back to `candidate`
(10,841,330 bare can/could/would signals stop counting toward active rates —
they stay in the graph, as candidate signals always do, AGENTS.md §5.3).

**Cleanup.** `scripts/cleanup_morpho_signals.py` — batched, resumable
`DETACH DELETE` of the stale single-token `embedded_question` nodes (keeps the
~60k genuine multi-word spans), with live progress + ETA via
`progress.Progress`. Dry-run by default; `--execute` to delete. **Not run by
the agent** (AGENTS.md §5.11). The annotator walk is "only unannotated", so
existing units are not re-parsed by this cleanup — a deliberate Stage-2
re-annotation is needed if the new rule's output is wanted for already-
annotated units.

**Scope note.** Only `embedded_question` had a changed *definition*, so it is
the only rule the cleaner purges. The five other morpho rules already using
`DependencyMatcher` (`morph.epi.neg_cognition`, `morph.epi.neg_cognition_modal`,
`morph.hedge.shield_think`, `morph.neg.scoped_epistemic`,
`morph.tense.past_nk_notyet`) were NOT changed and their signals are NOT
touched.

**Decision — filter at analysis time, do NOT purge (user, 2026-10-03).** A
partial purge was started, then stopped: deleting ~21.5M nodes on the
external-drive-backed store (`/Volumes/.../NK-Neo4J`) is index-maintenance-bound
random I/O and throughput decayed ~15.5k/s → ~5.3k/s. All OpenMent single-token
nodes had already been removed by then (715,607 → 2,794 remaining, all
multi-word). The project therefore **excludes** the stale single-token signals
at analysis time instead of re-annotating or purging. `STALE_SIGNAL_EXCLUSION`
(`s.rule_id = 'morph.syn.embedded_question' AND NOT surface_form CONTAINS ' '`)
is appended to the canonical `NK_SIGNAL_PREDICATE` in
`scripts/openment_roles.py` and in `notebooks/02_rq_analysis.ipynb`,
`notebooks/02b_rq_analysis.ipynb`, `notebooks/03_rq_analysis.ipynb` (including
their ad-hoc `rule_id IN $active_rules`/`$valid_rules`/`$scoped` predicates), and
as a defensive guard in `scripts/export_threads_docx.py`.
`scripts/cleanup_morpho_signals.py` is retained but marked OPTIONAL/manual only.

**Recall note.** The old Matcher over-matched, so no unit lacks an
embedded-question signal; the filter's only recall cost is genuine embedded
questions whose head was non-adjacent (stored as a single-token span). These are
bounded (order hundreds–low-thousands globally) and their units remain
NK-positive via `lex.unclear`/`unsure`/`not_sure`/`no_idea` and
`morph.syn.i_wonder`, so unit-level classification is unaffected. Accepted as a
documented, one-directional limitation (MARKER_REVIEW M-4 is precision-first).

## 2026-10-02 — RQ3b OpenMent mentor/mentee gap: hygiene audit + P0–P2

**New analysis module, notebook and tests.** `scripts/openment_roles.py`
implements the five-phase RQ3b deep-dive (P0 schema audit, P1 hygiene, P2
project overview with Gamma–Poisson shrinkage, P3 gap decomposition/skew/model,
P4 thread sampling + Word export, P5 signal coding/adjusted rates).
`notebooks/03_rq3b_openment.ipynb` is a thin driver; `tests/test_openment_roles.py`
covers the pure helpers (15 DB-free tests). Outputs land as `notebooks/rq3b_om_*`.
The module reuses the notebook's `NK_SIGNAL_PREDICATE` and rule-id sets verbatim.
A one-line pointer was added to `notebooks/03_rq_analysis.ipynb` (Sub-RQ 2).

**`export_threads_docx.py` moved to `scripts/`** (test import updated). Two small
correctness additions: a `date_display` column is preferred for date/header
rendering (OpenMent dates are anonymised day offsets — Word shows relative
elapsed days from thread start, per user request), and an empty `surface_form`
(whole-unit signals such as the classifier and `morph.syn.question_answer`) is
treated as an unverified full span instead of an alignment failure.

**P0 (schema, live DB).** 75,284 threads / 1,335,605 TextUnits / 566,369
role-labelled units. Thread key = `p.record_id`; OpenMent is GitHub-shaped
(issues/PRs + comments), **not email** — no reply-graph reconstruction needed.
Span offsets are character offsets (char/char_unverified; no failures).

**P1 (hygiene).** Confirmed a real **source-file artifact in `comments.csv`**:
1,218,538 rows for only 858,747 distinct `comment_id` (**359,791 extra duplicate
rows, 29.5%**), plus `_x`/`_y` merged columns (346,630 rows carry a second `_y`
comment). The ingester reads only `_x` and emits every row as a TextUnit, so
each duplicate row becomes a duplicated comment unit with identical text and a
different `creation_day_x` (~31% of comment units). Flagged analysis-side as
`is_repeat`; **not fixed** (ingest change needs a separate decision).
Crucially, **removing repeats/hygiene flags does not close the mentor−mentee
gap — it slightly widens it** (32.0% → 33.6% relative), so the artifact is not
the source of the role asymmetry. MinHash near-dedup is capped at 200k unique
texts for tractability.

**P2 (projects).** Among 744 eligible projects (both roles ≥ 1k tokens), the
mentor−mentee gap is positive in **93.0%**, sign test p≈5e-144, Wilcoxon
p≈2e-109, median +15.4 /1k tokens, bootstrap CI [14.8, 16.6]. The gap is not a
project-composition/Simpson artifact.

**Regression anchor note.** The observed unfiltered rates are **60.635 (mentor) /
45.928 (mentee)**, not the historical 51.837 / 39.471. This is expected: the user
is currently fine-tuning `patterns/morpho_syntactic_v0.2.yml` (in particular
`morph.mod.underspecified_cancould` status / `morph.mod.deontic` status), so the
target rule set is in flux. The module reports the drift loudly rather than
hard-failing. **Do not "fix" the YAML to restore the anchor while this is in
progress.**

**Status:** P0–P2 executed. P3–P5 implemented and unit-tested on synthetic data;
their full live runs are handed to the user (each reloads the corpus, ~3–5 min;
see AGENTS.md §5.11).

## 2026-09-21 — Bugfix: Cypher parameter/type + lexical rule-id-prefix bugs in 02b/03

A full EXPLAIN sweep (37 queries in 02b, 11 in 03) against the live Neo4j
uncovered four defects introduced by the 2026-09-21 rule-id filtering:

1. **Python `set` passed to the Bolt driver → `ValueError: Values of type
   <class 'set'> are not supported`.** `_split_rules_by_status()` returned
   raw `set` objects; every query with `active_rules=$active_rules` crashed on
   serialization. Fixed by returning `sorted(active), sorted(candidate)`.
2. **Lexical rule-id prefix mismatch → all lexical signals silently dropped.**
   `annotators/lexical.py` emits `rule_id = f"lex.{entry.id}"`, but the
   `en_core_v0.2.yml` entries store the bare id (`uncertain`). Cell 2 collected
   bare ids, so `s.rule_id IN $active_rules` matched zero lexical signals.
   Fixed by re-applying the `lex.` prefix inside `_split_rules_by_status()`
   (guard `if not e["id"].startswith("lex.")`). Verified: `sig` query now
   returns lexical (72,944) alongside morpho/word_formation/rhetorical.
3. **`ParameterNotFound: Expected a parameter named active_rules` in 02b RQ2.4
   (cell 23).** The query gained `AND s.rule_id IN $active_rules` but the call
   omitted the argument. Fixed by passing `active_rules=ACTIVE_RULE_IDS`.
4. **pandas `pivot_table` defaulted to `aggfunc='mean'` in 02b §0.2 (cell 8).**
   With one row per (layer, rule_id) and status remapped from rule_id, the
   layer×status table reported mean signals per rule instead of totals.
   Fixed with `aggfunc="sum"`.

Performance note: `s.status` is the only indexed Signal property (no `rule_id`
index), so `NK_SIGNAL_PREDICATE` now keeps `AND s.status IN ['active',
'candidate']` — true for every signal, but it lets the planner use the
`signal_status` index seek instead of a 144M-node label scan (single-rule
queries with a bare `{rule_id: $rid}` MATCH still scan and can be slow; the
notebooks avoid this by querying the `IN $active_rules` list through the
status index path).

Verified: all 48 queries EXPLAIN cleanly; live `sig` and lexical queries return
correctly on openment/kummerfeld-irc with no booster/retired-rule leakage; the
6 promoted rules (graph status 'candidate') are correctly included.

## 2026-09-21 — v0.2.1 marker revision handled analysis-side in 02b + 03 (no graph rewrite)

### The marker revision and its analysis-time fallout

The pattern/lexicon v0.2 files were revised (user decision, "final"): **45 rules
removed** (all 6 boosters, every M-5 SE-native lexical marker incl.
`cannot_reproduce`/`flaky`/`black_box`/spec-doc gaps, `blind_spot` +
`knowledge_gap` fixed phrases, the abbreviated shields `iirc`/`afaik`/`afaict`,
bare negation + bare-`?` + quantifier-`no`, and 3 rhetorical figures), **6 rules
promoted** candidate→active (lexical `missing`, `clueless`, `reckon_v`,
`reportedly`; morpho `morph.neg.nobody_nothing`, `morph.syn.tag_question`).
Two high-frequency promotions were initially made and then **reverted by the
user**: `morph.mod.underspecified_cancould` and `morph.syn.adversative` stay
candidate (they would have collapsed the cue-vs-scope gap from ~11%/6% to <1%).
No new patterns were added.

The Neo4j graph still holds signals annotated under the *pre-revision* rule
set, so `s.status` in the graph is annotation-time truth, not current truth:
retired-active rules (incl. boosters) still carry `status='active'`, promoted
rules still carry `'candidate'`. Consequence observed in the notebooks:
RQ1.3 (cell 17, Baseline 2a) suddenly showed **boosters** in the top-marker
figures, because `NON_NK_SUBCATS` was derived from lexicon polarity and the
booster entries' removal emptied that derivation.

### Resolution: filter by rule_id membership, never by graph `s.status`

Both `notebooks/02b_rq_analysis.ipynb` and `notebooks/03_rq_analysis.ipynb`
Cell 2 now rebuild `ACTIVE_RULE_IDS` / `CANDIDATE_RULE_IDS` / `VALID_RULE_IDS` /
`RULE_STATUS` from the four YAMLs (incl. `rhetorical_v{V}.yml`, previously not
loaded there) and:

- `NON_NK_SUBCATS` pins `{'booster', 'privative', 'privative_certainty'}` on
  top of the polarity-derived set — the polarity-only derivation would
  silently re-admit graph booster signals.
- `NK_SIGNAL_PREDICATE` replaces `s.status = 'active'` with
  `s.rule_id IN $active_rules`; every query interpolating the predicate passes
  `active_rules=ACTIVE_RULE_IDS`. This simultaneously drops ghost signals from
  retired rules and *includes* the 6 promoted rules (graph still says
  candidate for them).
- Candidate/sensitivity queries (`cand`, 03 `lex_cand`) filter
  `s.rule_id IN $valid_rules` and remap status in pandas via
  `cand["status"] = cand["rule_id"].map(RULE_STATUS)`.
- Direct Cypher signal queries (02b cells 8, 16, 18, 22, 23, 25, 30, 59, 67)
  got the same rule-id filter; stale `{layer, status:'active'}` match
  patterns were replaced by `{layer}` + rule-id WHERE clauses.
- 02b RQ1.3 figures (cell 16): boosters can no longer leak in; palette comment
  updated (Deep Teal now anchors the 5th-ranked subcategory, repro_gap retired).
- 02b RQ6.3 (cell 67): `task_register` (lexical repro_gap/spec_gap) is
  structurally empty after the retirement — kept as an audited empty group
  with an explicit warning print instead of silently dropping the prediction.
- 03 RQ2a (cell 13): fixed the long-flagged open debt — `lex_cand` used
  `s.layer <> 'classifier'`, letting morpho signals inflate the candidate
  lexical denominators; now `s.layer = 'lexical'` + rule-id filter.
  The lexical SE-native share now legitimately reports 0.0 (retirement of all
  M-5 lexical markers) — recorded as a finding, not a bug. SE-native
  rhetorical figures (opacity, hidden_extent) remain active.
- 03 Sub-RQ 4 (cell 28): dropped the now-stale `s.status = 'active'` clause
  (it would have excluded promoted rules' signals).

Verified: rule-set smoke check (no retired-rule leakage; demoted rules
candidate; promoted rules active; boosters pinned; all 5 scoped rules active),
JSON validity, and `compile()` over every code cell in both notebooks. The
graph was NOT touched — stale statuses are resolved at analysis time by design
(re-annotation would be needed to make graph status current again).

## 2026-09-20 — 02b_rq_analysis.ipynb brought onto the v0.3.1 Baseline 2 metrics

RQ1/RQ2/RQ3 in `notebooks/02b_rq_analysis.ipynb` (the lexical, morpho-syntactic,
rhetorical statistics) are aligned with the 2026-09-19 v0.3.1 restructure
(they are now **Baseline 2a–c**, `REFINED_RQS_v0.3.md` §3). Implemented as
"Option A" — the single-pull pattern of `03_rq_analysis.ipynb`:

- **New Baseline 2.0 cell**: one Cypher pull of all active NK signals into a
  per-corpus/per-genre `sig` frame (shared `NK_SIGNAL_PREDICATE`) plus an
  active+candidate `cand` frame, with the `GRAPH_EMPTY` guard; every RQ1–RQ3
  cell now aggregates in memory. An explicit `layer IN ['lexical',
  'morpho_syntactic', 'rhetorical']` list replaces `03`'s RQ2a
  `s.layer <> 'classifier'` formulation.
- **Per-genre binding constraint applied**: RQ1.1/RQ1.2/RQ2.1/RQ2.2/RQ3.1–RQ3.3
  now normalise by `GENRE_TOKENS` (or corpus tokens) instead of pooled
  `TOTAL_TOKENS`; the pooled SE-native fraction and pooled SE-native:canonical
  ratio are demoted to sensitivity checks. RQ3.3 is active-only per genre;
  the per_1k_units column (a unit-length artefact) is dropped.
- **RQ2 headline metric redefined** (new RQ2.4b cell): cue-vs-scope gap =
  share of ALL morpho signals carried by scoped (DependencyMatcher) rules, per
  genre, classifier-independent (chat 11.1%, QA 6.1% — matching
  `RESULTS_AND_DISCUSSION_v0.3.md` §2.2). The classifier-positive 2×2
  (RQ2.3/RQ2.5) is kept but explicitly demoted to an auxiliary
  keyword-false-negative diagnostic.
- **Bug fixes in 02b**: RQ1.4's double-`WHERE` Cypher (the trailing
  `@sandbox`/corpus filter after `OPTIONAL MATCH` raised `CypherSyntaxError`)
  moved into the parent `MATCH`; RQ1.1's `TOTAL_UNITS` NameError removed by
  the rewrite; `status='active'` added to the RQ2.4 scoped-rule inventory and
  RQ3.4 `opacity` disclosure; RQ1.3 figure denominator documented (pooled
  in-scope tokens, incl. NumFOCUS title register — not a per-genre claim).
- **Flagged, not fixed (TODO(design-review))**: `03_rq_analysis.ipynb` RQ2a
  `lex_cand` query uses `s.layer <> 'classifier'` instead of
  `s.layer = 'lexical'`, so its "active+candidate" SE-native-share upper
  bound denominators (~55M/28M/9M rows) include morpho signals — its
  per-genre *active* share table (chat 0.52% etc.) is unaffected because it
  slices the active lexical `sig` frame. 02b now carries the corrected
  formulation and can serve as the reference when 03 is patched.
- Notebook re-validated by parse only (57 code cells); re-run needed in
  Jupyter against a live Neo4j for fresh outputs (stale outputs cleared).

## 2026-09-19 — v0.3.1 RQ restructure: communities/projects/platforms as the empirical core

### Decision: the paper's centre of gravity shifts from taxonomy/linguistics to SE communities

The headline research questions are now **how SE communities, projects, and
communication platforms shape the articulation and negotiation of non-knowledge**.
Reflected in `REFINED_RQS_v0.3.md` (rewritten §3–§8) and `CODING_MANUAL_v0.3.md`
(new §10), and implemented in `notebooks/03_rq_analysis.ipynb`:

- **Baseline 1** (ex-RQ1) — taxonomy discriminability, literature-only; reported
  in the related-work / framework section.
- **Baseline 2** (ex-RQ2) — descriptive linguistic anatomy; framework section.
- **Sub-RQ 1 (platforms)** — cross-platform NK density/layers/SE-native, with the
  **replication test** as credibility gate (rewritten the crashing RQ3a cell —
  it indexed `profiles.corpus[i]` positionally after empty-corpus filtering,
  `KeyError: 0`; now `reset_index()` + `np.random.default_rng(42)`).
- **Sub-RQ 2 (projects)** — governance (commercial vs foundation) and domain
  contrasts, plus the retained role-asymmetry facet (OpenMent mentor/mentee,
  email author/reviewer). Governance/domain labels are **analysis-side**, applied
  live in the notebook (`GOVERNANCE_MAP`); no schema/ontology change.
- **Sub-RQ 3 (controlled replication)** — Arm A: Clojure community on Slack vs
  Discord as macro community-of-practice samples (identity resolution is out of
  scope — FRAMEWORK_DESIGN §4.8; descriptive, effect-size only, no p-values).
  Arm B: **live set-intersection of 229 Apache project keys shared between
  `apache-jira` (MSR'23) and `alternative-jira` (instance `apache`, MSR'22)** —
  same projects, same platform, two independent datasets (measurement-stability
  test). Verified live during implementation.
- **Sub-RQ 4 (independent qualitative)** — communicative function / epistemic
  referent / conversational trajectory on a **detector-positive** frame of
  **100 units × 2 raters**, Cohen's κ per dimension, 5 calibration units
  excluded from the 100. Codebook in `CODING_MANUAL_v0.3.md` §10.

### Deferred to a companion study (not retracted)

The old hand-coded taxonomy questions (v0.3 RQ4a–c), the 400-unit frame, the
multi-actor flag, and predictions **P1–P6** are **deferred** (`REFINED_RQS_v0.3.md`
§6). Sub-RQ 4 does **not** inherit RQ4a's blind-spot/coverage measurement; that is
stated explicitly in both docs. `CODING_MANUAL_v0.3.md` §§1–9 is retained as the
deferred instrument.

### Fix: corpus census under-reported NumFOCUS

`scripts/corpus_census.py` `CURATED_CORPORA` omitted `numfocus` (10 ids incl.
`openment`; `CANONICAL` had 11 incl. `numfocus`), so `run_pipeline --census` and
`republish_events` reported the ingested 333,393 NumFOCUS docs (134,858
`raw_issues` + 198,535 `raw_pull_requests`) as 0/PENDING and shorted the curated
total by exactly that amount. Added `"numfocus"` to the set; census now reports
it correctly. Related prose fix: `REFINED_RQS_v0.3.md` §2 now says **11 in-scope
corpus ids** (was "10 in-scope corpora" while the table listed 11).

### Declared confounds restated (REFINED_RQS_v0.3.md §2)

- **Curated email is full-rate** (10,087,431 docs, post 2026-08-31); the earlier
  ~44.8% hash-sampling confound note is retracted.
- **NumFOCUS is title-only** — analysed as a title register; excluded from
  cross-corpus body-text rate comparisons.
- **Chat artefacts carry no `created_at`** in the graph (verified 0/214k Slack,
  0/1.5M Disco, 0/39k IRC) — era windows for pairs are reported via a bounded
  Mongo-side join and disclosed, not analysed away.
- **Conversation structure is platform-dependent** — `REPLIES_TO` (email, IRC),
  `Conversation` (Slack); Gitter and Discord have none → Sub-RQ 4 trajectory is
  `UNCODABLE_STRUCTURE_ABSENT` there.

## 2026-08-31 — Full-corpus email ingestion, two-mongod divergence recovered, scope retirement

### Full-rate curated-email ingestion (supersedes the 2026-08-14 stratification)

Re-ran `python -m miner.curated_email_ingester --sample-rate 1.0`: the email
code-review corpus is now the **full Patchwork pool** (10,087,431 docs =
4,720,551 from the original 44.84%-sampled run + 5,366,880 new), no longer the
~5M proportional stratification. Insert-only and idempotent (unique `urn`);
the 20k-word body guard applied uniformly to both halves. FRAMEWORK_DESIGN §12
and the EDA notebook corpus descriptions are now stale on this point
(TODO(design-review)); analysis notebooks need re-runs against the enlarged
graph.

### Two-mongod divergence (root cause of the "missing corpora" + `doc not found`)

**Symptom chain:** (1) `Phase 0: doc not found: 6a7f43ba…` for a handful of
events; (2) the extractor logging `Document not found … collection=raw_external`
near stream position ~1.49M of 6.84M, then appearing to hang; (3) a census
showing 6 curated corpora at 0 docs.

**Root cause — TWO mongods owned port 27017 at different times.** A
homebrew `mongodb-community` mongod (LaunchAgent, data on the internal disk at
`/opt/homebrew/var/mongodb`, binding `127.0.0.1:27017`) and the Docker mongo
(compose, data on the external SSD, proxy on `*:27017`) coexisted. Whichever
bound the specific loopback address first silently received `localhost:27017`
traffic: the Aug-27/30 curated-corpus + Gmane ingests went to the *brew*
instance (13,245,470-doc state, matching the 2026-08-30 CHANGELOG), while the
Aug-14/18 email ingest and today's full-rate re-ingest went to the *Docker*
instance. Nothing was ever deleted — the datasets had **diverged across two
mongods**. The pre-reboot census matched Docker (the brew mongod was not
running then); the post-reboot 18:34 census silently hit brew (started at boot
before Docker). The `doc not found` warnings were stale pointer events from the
2026-08-30 `republish_events.py` run (1,469,737 events for sotorrent/
kummerfeld-irc/preethac-slack), whose docs live in brew, not Docker — distinct
from the 2026-08-27 NumFocus collection-routing cause of the same warning.
The extractor's "hang" was its designed backpressure pause (`graphrag.units`
at 50,125 ≥ the 50,000 `extractor_max_stream_units_backlog`) because Phase 1
had stopped draining — consistent with the Docker VM hang that same afternoon
(root cause undetermined; container recreation destroyed the logs).

**Recovery (all insert-only, no `--drop` anywhere):**
1. Brew mongod stopped + LaunchAgent disabled (`launchctl bootout/disable`,
   plist renamed) → Docker is the single owner of 27017.
2. Backups before touching anything: brew db dumped (20.5G gz, SSD);
   Docker's unique `raw_emails` dumped to the internal disk (6.1G gz, second
   physical device). Fingerprints (counts, indexes, per-corpus, era split)
   archived next to the dump.
3. Brew data restored into a staging db `graph_nk_brew_staging` (27,648,365
   docs, 0 failures), then **scoped insert-only `$merge`** (whenMatched
   keepExisting / whenNotMatched insert, source `_id` stripped) of only the
   in-scope corpora Docker lacked: raw_external filtered to sotorrent/
   kummerfeld-irc/preethac-slack/livechat-gitter (+1,664,536), raw_issues
   (+134,858 numfocus), raw_pull_requests (+198,535 numfocus). `raw_emails`
   NOT merged — Docker already held the complete curated corpus, and Gmane is
   out of study scope. Staging dropped after verification.
4. **Final state (Docker only):** curated total **21,982,215** = email
   10,087,431 · gittercom 3,013,715 · alternative-jira 2,686,222 · disco
   1,508,093 · livechat-gitter 1,650,799 · apache-jira 1,157,541 · sotorrent
   1,216,000 · numfocus 333,393 · openment 75,284 · preethac-slack 214,289 ·
   kummerfeld-irc 39,448. Unique indexes (`urn`, `record_id`, `issue_key`×2)
   verified; sample content hash staging==live.

**Standing rule (AGENTS.md §5.11):** agents must not run terminal commands
expected to exceed ~3 minutes; they hand the exact command to the user and
verify afterwards with bounded read-only checks.

### Scope retirement: BugsRepo and so-emotion-gold

- **BugsRepo** excluded: the distributed dataset consists primarily of *links*
  to Bugzilla bugs, not bug texts; manual reconstruction would diverge from the
  peer-reviewed source and the study goal.
- **SO emotion gold (`so-emotion-gold`)** excluded: too small for the
  corpus-scale design; data inconsistencies (no post ids, synthetic record
  identity).
- Updated: `scripts/corpus_census.py` (both removed from `CURATED_CORPORA` +
  `CANONICAL`), `FRAMEWORK_DESIGN.md` §12 (considered-then-excluded note),
  `REFINED_RQS_v0.3.md` §2 (corpus table now 10 in-scope corpora + exclusion
  note). Ingesters remain as unused code; extractor tests unchanged.

### Next (user-run, per AGENTS §5.11)

`republish_events.py --corpus curated-email-code-reviews --corpus
livechat-gitter --corpus numfocus` → `run_pipeline.py --stage 1` →
`--stage 2 --annotate-shards 8 --only-unannotated` → `--stage 2 --skip-annotate
--enrich`. Stage 2 is the multi-day pole (~10M new TextUnits).

## 2026-08-30 — 02b_rq_analysis.ipynb RQ1.3: publication overhaul & split into two standalone figures

- **RQ1.3 Overhaul & Variable Preservation:** Fixed `rq1_rules` calculation by
  restoring and running the self-contained Neo4j queries for both `rq1_rules`
  (top-25 individual rules) and `rq1_subcats` (corpus-wide subcategory aggregates),
  token-normalised against `TOTAL_TOKENS` with `se_native` classification intact.
- **Two Standalone Publication Figures (`notebooks/figs/`):**
  - **(a) `fig_rq13a_top_subcategories` (.pdf/.png 300-dpi):** Top-10 lexical NK
    subcategories ranked descending, with direct data annotations (`rate (volume)`),
    open spines, subtle x-gridlines, and SE-native markers (`†`).
  - **(b) `fig_rq13b_top_rules` (.pdf/.png 300-dpi):** Top-25 individual markers
    (monospace rule IDs, `lex.` prefix stripped), color-coded by their parent
    subcategory, with a collision-free legend anchored in the lower right.
- **5-Subcategory CVD-Safe Editorial Palette:** Follows the established design
  language (`eda_curated_datasets.ipynb` overhaul):
  - Plausibility shield: Warm Rust `#C2410C` (dark border `#9A3412`)
  - Not knowing: Deep Navy `#1E40AF` (dark border `#1E3A8A`)
  - Epistemic state: Forest Pine `#15803D` (dark border `#14532D`)
  - Evidential (inferential): Amber Ochre `#D97706` (dark border `#B45309`)
  - Reproduction gap (SE-native): Deep Teal `#0D9488` (dark border `#0F766E`)
  - Tail subcategories: Refined Slate `#64748B` (dark border `#475569`) labeled
    as "other subcategories".
- **Verification:** Cell executed cleanly against the live Neo4j database (34.7M
  TextUnits, 1.60B tokens), generating and validating both exported vector and
  raster figures.

## 2026-08-30 — republish_events.py: `--corpus` flag for targeted republishing

**Scope.** Added a repeatable/comma-separated `--corpus ID` flag to
`scripts/republish_events.py` so a corpus whose events were lost (Redis restart
wipes `stream_raw`) can be re-queued without republishing all ~13.2M curated
docs. Motivated by the finding that **sotorrent, so-emotion-gold,
kummerfeld-irc, and preethac-slack are Mongo-ingested but absent from the live
Neo4j graph** (no Artefacts/TextUnits/Signals; the stale outputs in
02b/03_rq_analysis.ipynb predate a graph rebuild).

- **Semantics:** `--corpus` values are validated against `CURATED_CORPORA` and
  **fail fast before any write path** (`p.error` listing valid ids) — a typo
  must degrade to an error, never to "republish everything". `_curated_filter()`
  takes an optional selection and intersects it with `CURATED_CORPORA`; no flag
  → unchanged all-corpus behavior.
- **Verification:** 3-corpus dry-run = 1,469,737 docs (sotorrent 1,216,000 +
  kummerfeld-irc 39,448 + preethac-slack 214,289, all in `raw_external`);
  negative test errors with the valid-ids list; bare dry-run still totals
  13,245,470 (backward compatible). New filter-selection tests in
  `tests/test_republish_events.py` (8 passed).

## 2026-08-30 — eda_curated_datasets.ipynb: publication palette overhaul, four standalone graph figures, and figure suite polish

**Scope.** Complete overhaul of the descriptive and graph-side figure suite in
`notebooks/eda_curated_datasets.ipynb`:
- **Palette & Contrast Overhaul:** Replaced saturated primary colors with a
  refined editorial, CVD-safe palette with a strictly monotonic grayscale
  luminance ladder:
  - Issue/PR trackers: Deep Navy `#1E40AF` (grayscale $Y \approx 68$)
  - Chat messages: Forest Pine `#15803D` ($Y \approx 92$)
  - Email code reviews: Warm Rust `#C2410C` ($Y \approx 116$)
  - Public Q&A: Amber Ochre `#D97706` ($Y \approx 145$)
  - Neutral 4-tier grayscale concentration ramp for stacked shares:
    `#0F172A`, `#334155`, `#64748B`, `#CBD5E1`.
- **Bugfix on `year` & Derived Columns:** `build_fse_sample()` now computes
  `venue_short`, `family`, `ts`, and `year` before returning on all execution
  paths (including Mongo fallback), resolving the `KeyError: 'year'` in Table 1
  and subsequent `NameError: name 't1' is not defined` in Figures A, C, D, E.
- **Figure B Whisker & Layout Fixes:** Samples clipped at `lower=1` to prevent
  whisker compression onto the $x=0$/log axis spine; `xlim(0.9, 5000)`; median
  badges offset cleanly; linguistic threshold annotations moved to the top
  margin to prevent visual collisions.
- **Figure A, C, D, E Polish:** Refined margins, constrained layout, and direct
  collision-free text offsets for direct scatter labeling in Figure E.
- **Four Standalone Graph Statistics Figures:** Replaced the 2×2 composite plot
  with four independent, publication-grade figures exported to `notebooks/figs/`:
  - `figF1_graph_corpus_scale` (`fig_graph_corpus_scale.pdf/.png`): Log-scale
    TextUnits per corpus in Neo4j with token and million-count labels.
  - `figF2_graph_token_distribution` (`fig_graph_token_distribution.pdf/.png`):
    Token count distribution per TextUnit (median dot, p90 whisker, IQR when live).
  - `figF3_graph_genre_aggregates` (`fig_graph_genre_aggregates.pdf/.png`):
    Macro genre totals for tokens and units.
  - `figF4_graph_venue_breadth` (`fig_graph_venue_breadth.pdf/.png`):
    Unique projects/venues per corpus stored in the graph.
- **Verification:** All 11 code cells compile and execute cleanly in test harness
  under both offline fallback and live Neo4j modes. Table 1 CSV exports 11 complete
  rows with all columns populated.
11 fully-populated rows. Live-graph panels (Figure F breadth/percentiles) still
need a running Neo4j to show real values.

## 2026-08-29 — Dataset Statistics & Descriptive Plots Overhaul (Cells 60–80 in eda_curated_datasets.ipynb)

**Scope.** Replaced the prototype dataset figures (cells 64–79) in `notebooks/eda_curated_datasets.ipynb` with a publication-grade suite of 5 descriptive figures (Figures A–E) and an updated Table 1 export, adhering to the repository's unified design system:
- **Global Design Mechanics & Setup (Cell 61):**
  - Integrated `apply_figure_style(sizes=(8, 7, 6))` and palette tokens directly into the setup cell so all dataset plots inherit the same typographic hierarchy, open frames, outward ticks, and 300 DPI exports.
  - Defined platform family colors (`chat #0D9488`, `issue #2563EB`, `email #E05A47`, `qa #8B5CF6`), dark borders, and 4-tier sequential concentration lightness ramps.
- **Figure A — Corpus Scale & Composition (Cell 71, `figA_composition`):**
  - Two-panel layout: Panel (a) Aggregate macro genre share with total counts and percentages; Panel (b) Individual corpus horizontal bars on log scale with exact counts and % shares.
- **Figure B — Text Length & Granularity Spectrum (Cell 73, `figB_text_length`):**
  - Replaced basic boxplots with a polished horizontal distribution spectrum sorted by median length, annotated median badges (`md=...`), genre alpha fills, dark borders, and linguistic reference lines (typical sentence ~15 words, structured post ~100 words).
- **Figure C — Project & Venue Diversity and Structural Concentration (Cell 75, `figC_venues`):**
  - Replaced cramped micro-slice bars with a dual panel: (a) Venue breadth (unique projects/channels on log scale spanning 1 to 2,800+); (b) Within-corpus concentration distribution (100% stacked bar: Top 1, Top 2–5, Top 6–20, Long tail).
- **Figure D — Longitudinal Footprint & Communication Eras (Cell 77, `figD_timeline`):**
  - 2000–2025 longitudinal Gantt timeline with genre-colored rounded pills, active era boundaries, and ecosystem milestone markers (GitHub/SO 2008, Slack 2013, Discord 2015).
- **Figure E — Multi-Dimensional Corpus Landscape (Cell 79, `figE_landscape`):**
  - Multi-dimensional synthesis scatter plot: X = Median Text Length (words, log scale), Y = Active Temporal Span (years), Bubble Area = Total Processed Texts, Color = Genre Family, with direct name labels and clean legend.
- **Export Formats:**
  - All figures now export to `notebooks/figs/` as both vector `.pdf` (publication) and 300-DPI `.png` (display).



## 2026-08-29 — Figure polish in eda_curated_datasets.ipynb (Framework overview, Schema & Instance figures)

**Scope.** Refined the visual layouts and styling of all three graph figures in `notebooks/eda_curated_datasets.ipynb`:
- **Framework overview (Cell 84 / 85):**
  - Standardised horizontal column gaps to an exact 3.5 units across all 5 columns (`Data Sources`, `Extraction`, `Annotation`, `Graph`, `Analysis`), making the layout symmetrical and balanced.
  - Eliminated excess vertical white space by tightening `ylim` and setting `figsize=(7.2, 2.7)` for a clean, wide paper aspect ratio (while keeping bottom legacy/L0 frames safely commented out).
  - Cleaned up the 4 converging data-source arrows to run as clean, parallel horizontal lines into the normalisation frame.
  - Formatted "Artefact layer" and "Ignorance layer" headers in bold black (`color="black"`) with crisp sub-text.
  - Replaced the Claim Layers with `Analysis`, substituting L1–L3 with `RQ2 · Linguistic anatomy`, `RQ3 · Community comparison`, and `RQ4 · Taxonomy check` styled in the taxonomy violet palette (`AMETHYST #6B3E93` and soft tint `#F3E8FA`).
- **Ontology / Schema tiers (Cell 85 / 86):**
  - Updated all four layer chips inside `Signal` to use their distinct layer colors (`lexical`, `morpho-syntactic`, `word formation`, `rhetorical`).
  - Styled `LexicalMarker` and `RhetoricalFigure` frames in lexical blue and rhetorical magenta respectively.
  - Set `IgnoranceType` to taxonomy violet (`AMETHYST`) and added a dotted arrow from `Signal` to `IgnoranceType`.
  - Re-introduced subtle white separation gaps between the three tier background bands (source, pivot, evidence) while keeping all relationship labels (`HAS_TEXT`, `HAS_SIGNAL`, `TYPED_AS`) positioned cleanly over the light blue `PALE` background with plenty of vertical clearance (`figsize=(7.0, 4.2)`).
  - Repositioned `Platform`, `Venue`, `Corpus`, and `Conversation` frames and their relationship labels (`HAS_VENUE`, `COVERS`, `HAS_CONVERSATION`, `CONTAINS`) with ample clearance so labels and arrows no longer collide with box borders.
- **Instantiated TextUnit / Figure 2 (Cell 86 / 87):**
  - Updated palette to match the design system: `LAYER["lexical"]["base"]` for lexical Signal, span ruler, and `LexicalMarker`; `LAYER["morpho_syntactic"]["base"]` for morpho-syntactic Signal and span ruler; `TIER["pivot"]["tint"]` for `:TextUnit` fill.
  - Formatted property text in `GREY_TEXT` and edge label pills on clean white backgrounds.
  - Adjusted canvas proportions to `figsize=(3.45, 3.8)` so it pairs alongside the schema plot on an A4 page.


## 2026-08-28 — Paper design system: unified colour language + notebook plot overhaul (eda_curated_datasets.ipynb)

**Scope.** Reworked the figure styling in `notebooks/eda_curated_datasets.ipynb` — the
two graph-structure figures (schema + instance) and the data-source figures (A–D) — and
fixed the live-asyncio census bug, so the notebook produces a single, coherent colour
and design language reusable across paper, presentation slides, and social media.

**Design-system decision (colour semantics, one meaning per hue).** Three non-conflicting
colour families, rationale documented in the notebook cell 82 header:
- Tier/ontology: `source #1D3557` · `pivot #1B4D3E` · `evidence #C85A17` · `taxonomy #6B3E93`, each with a soft `tint` fill.
- Linguistic signal layers: `lexical #1E6091` · `morpho_syntactic #792E87` · `word_formation #B45309` · `rhetorical #BE185D` · `classifier #028090`.
- Platform families (data-source figures): `chat #0D9488` · `issue #2563EB` · `email #E05A47` · `qa #8B5CF6`.

This removes the old inconsistency where blue meant "source tier" in the schema figure
but "lexical signal" in the instance figure, and replaces the washed-out `LIGHT_BLUE`/
`LIGHT_RED` fills and the harsh crimson `ORANGE` with calibrated tints.

**Graph figures (cells 82–84).** Added `tier_container()` (rounded tier cards with left
accent bar + pill badge), `export_figure()` (paper PDF / slides PNG / social PNG into
`notebooks/figs/{paper,slides,social}/`), colour-coded layer chips inside the `Signal`
hub, and per-layer colouring in the instance figure. `REPLIES_TO` self-loop clearance
widened; edge labels now sit on white pills.

**Data-source figures.** Venue heatmap uses a single-hue sequential ramp with zero-cells
masked (cell 58); Figure A groups bars by genre (cell 71); Figure B/C polish (median
markers, smart slice-label threshold at 8% share); Figure D replaced the `viridis` heatmap
with a genre-coloured Gantt/range-bar timeline (cell 78).

**Async census fix (cells 63 & 65).** `_mongo_census()` and `load_altjira_sample()` were
sync wrappers calling `asyncio.run()`, which raises `RuntimeError: asyncio.run() cannot
be called from a running event loop` inside Jupyter. Both are now `async def` and invoked
with top-level `await` (native in IPython ≥ 7.0), so exact MongoDB counts load instead of
falling back to processed-file counts. Note for future notebook work: never use
`asyncio.run()` at notebook scope; use top-level `await`.

**Verification.** Graph figures render cleanly under `MPLBACKEND=Agg`; `export_figure`
writes PDF/PNG to all three channels. All notebook code cells parse; `ruff check` on
extracted cells shows only expected cross-cell/notebook artefacts (top-level `await`
`F704`, pre-existing semicolon/long-line style) — `ruff check .` does not lint `.ipynb`.
Data-source figures A–D require live Mongo/Neo4j and were not executed here.

## 2026-08-27 — OpenMent/NumFocus ingester collection routing fix (Phase 0 "doc not found")

**Symptom.** After ingesting OpenMent + NumFocus, a fresh Stage 1 Phase 0 run logged
`Phase 0: doc not found: <mongo_id>` for every `pull_request` event (≈198k). The PRs
were silently dropped from the graph.

**Root cause.** The projector's `_collection_for` maps `pull_request` → `raw_pull_requests`
(`projector/worker.py:311`), but the two GitHub-shaped ingesters wrote **all** docs —
issues and PRs alike — into `raw_issues` (`collection="raw_issues"` hardcoded in
`openment_ingester`/`numfocus_ingester`). OpenMent is 100% issues so it never hit this;
NumFOCUS is the first corpus with real PRs. The ingester and the projector disagreed on
where PRs live, so Phase 0 could not resolve the PR docs' Mongo `_id`s.

**Decision.** Route GitHub-shaped docs by `artefact_kind` so the ingester matches the
projector's fixed mapping: issues → `raw_issues`, PRs → `raw_pull_requests`. Both
ingesters now partition docs and call `run_external_ingest` once per kind/collection,
each building its own `issue_key` unique index. This realises the documented intent in
`external_common.py` ("GitHub-shaped corpora reuse the existing
raw_issues/raw_pull_requests collections").

**Data migration.** The 198,535 NumFocus PR docs already in `raw_issues` were moved to
`raw_pull_requests` (preserving `_id`s so the already-published stream pointer events
resolve), and the `issue_key_1` unique index was created there. Verified: sampled
stream `pull_request` `mongo_id`s all resolve in `raw_pull_requests`.

**Verification.** `--dry-run --max 5` on both ingesters shows correct per-kind routing;
`ruff check` clean on both edited files (the one E501 in openment is pre-existing).
A fresh Stage 1 Phase 0 run will now seed the NumFOCUS PRs.

---

*Living record of what has been built, what is pending, and what decisions were
made during implementation. Updated at the end of every implementation session.*

*Format: newest entry at the top. Each entry references the BUILD_SPEC.md milestone
it closes or advances.*

---

## 2026-08-27 — Incremental Stage 2 (`--only-unannotated`): skip already-annotated work

**Symptom.** After ingesting new data, a Stage 2 run re-parses the *entire*
in-scope corpus (31.5M units), not just the new units. Live census confirmed
the earlier "fully annotated" frontier result was correct: 31,520,122/32,552,111
units carry a `CLASSIFIED_AS` verdict; the 1,005 in-scope units without one are
all oversized (> `annotate_max_chars`); the rest of the 1.03M no-verdict units
are out of scope.

**Decision.** Add an explicit incremental mode, `--stage 2 --only-unannotated`,
that selects per-unit from the graph — `NOT EXISTS { MATCH (u)-[:CLASSIFIED_AS]->() }`
plus the oversized guard — instead of a minimum-id frontier. Rationale: the
frontier is only a valid resume boundary for an interrupted, id-ordered FULL
run; for newly-ingested data, new `TextUnit.id`s can sort below/among existing
ids, so a min-id boundary cannot skip already-annotated units that sort above it.
The per-unit predicate is correct regardless of id ordering, and interruption
recovery is simply rerunning the same command (the graph selects what remains).

**Completion-marker ordering (critical safety fix).** `CLASSIFIED_AS` is only a
valid "done" marker if it is written AFTER all of a unit's plain signals +
`MATCHES_MARKER`/`INSTANTIATES` wiring. Previously `upsert_signals_batch` wrote
verdicts FIRST; a Redis loss between the verdict transaction and the signal
transactions would leave a unit marked done with missing signals, and incremental
mode would silently skip it. `_upsert_verdicts` now runs LAST, so a crash before
any of the earlier steps leaves no verdict (the unit is retried; MERGEs are
idempotent). `_flush` still commits the whole batch before Redis trims it.

**Implementation.**
- `annotators/worker.py::_scope_filter(only_unannotated)` adds the two
  predicates; reused by count, pagination, and shard balancing so progress/ETA
  and shard split reflect only remaining work.
- `run_annotator_worker`/`_run_annotator_shard`/`compute_shard_boundaries`
  thread `only_unannotated`; `_hwm_key` includes it in its identity so an
  incremental run can never clobber a full-run checkpoint.
- `count_in_scope` lets the parent short-circuit: zero un-annotated units →
  drain existing signals and exit; fewer units than requested shards → reduce to
  one shard (avoid a failing token-quantile scan).
- Incremental mode requires the classifier: it fails loudly if none is loaded,
  since its verdict is the completion marker.
- `run_pipeline.py --only-unannotated` is validated incompatible with
  `--resume`, `--resume-from`, `--shard-index`, and `--skip-annotate`. A failed
  incremental shard recommends rerunning all shards (not a recomputed
  `--shard-index`, whose partition is stale once the population shrinks).
- `find_annotation_frontier.py` messaging updated: it is the FULL-run recovery
  tool, not the incremental selector; it now says so and points to
  `--only-unannotated`.

**Usage contract.** Use `--only-unannotated` ONLY when (a) new records created
new TextUnits, (b) existing `text` is unchanged, and (c) rules/lexicons/patterns
and classifier config are unchanged. Otherwise run a plain full Stage 2 (MERGEs
idempotently refresh weight/status), because a changed rule must re-annotate the
whole corpus.

**Tests.** New `tests/test_incremental_annotation.py` (11 tests, service-free):
scope predicates, HWM identity separation, CLI validation, projector
verdict-last ordering (incl. verdict-only batch). `tests/test_annotator_resume.py`
and `tests/test_annotator_sharding.py` unchanged and green (59 self-contained
tests pass). `ruff check`/`format` clean on all touched files except the
pre-existing unrelated `_census` import-ordering nit in `run_pipeline.py`.

**Code-review fixes (same day).** A review found two ways a unit could be marked
complete without being fully annotated, plus test and message gaps; all fixed:
- **Verdict suppression on incomplete batches.** `_annotate_batch` now drops all
  `__verdict__` payloads from an incomplete batch (`complete=False` after a
  parse/rule/classifier failure). Previously a failed unit still reached the
  classifier, which published its verdict, so incremental recovery would skip
  it despite its rule signals being partial. Successful non-verdict signals are
  still published (idempotent MERGEs) and the whole batch is retried.
- **Strict annotator loading.** `_load_annotators(strict=True)` now raises if
  ANY expected rule annotator fails to load or the classifier is missing —
  otherwise a unit could get a verdict while never having been annotated by the
  failed rule. `run_annotator_worker` calls it strict in incremental mode; the
  previous classifier-only guard (and its mis-formatted message) removed.
- **Tests.** New failure-injection projector tests assert the verdict is never
  attempted when a plain-signal/lexical/rhetorical transaction fails; new
  orchestration tests cover zero-work drain, shard reduction, and
  `only_unannotated` reaching boundaries + child processes. Incremental suite
  now 17 tests; 93 self-contained tests pass.

---

Added a self-contained **"FSE Data Source statistics"** section to
`notebooks/eda_curated_datasets.ipynb` (before the existing Notes cell). It produces
the Data Source artefacts for the FSE paper from the 12 curated corpora
(FRAMEWORK_DESIGN §12):

- **`PAPER_STATS`** — per-corpus literature facts (paper size, users, projects,
  time span, citation key, documented ingest scope) transcribed from the 14 papers
  in `dataset_papers/` (verified against each paper; see report in-session).
- **Exact counts** from MongoDB via `scripts/corpus_census.py`; corpora not yet
  ingested (NumFOCUS, BugsRepo, IRC, Slack, SO emotion, SOTorrent) fall back to the
  exact processed-file counts measured by the ingesters.
- **Alternative Jira** sample drawn live from the restored `JiraReposAnon` Mongo db.
- **Table 1** (dataset × paper size / our texts / % / median length / time / projects)
  exported to `notebooks/figs/table1_datasets.csv`.
- **Figures A–D** (saved to `notebooks/figs/`): corpus composition (log bars +
  %, platform colour), text-length boxplots by median, top-venue + per-dataset
  project-share composition, and a year×dataset timeline. Each figure carries a
  one-line "key message".

Decisions recorded: counts = Mongo census where ingested else processed-file exacts;
user counts kept paper-reported only (not recomputed from payloads); colour mapping
(family→colour) shared across figures. `notebooks/figs/` git-ignored. The 12-curated
corpus scope excludes the OCEAN test corpus and old GMEAN/GitHub scope. Verified by
executing every new cell against the live env (real census + alt-jira `$sample`);
figure/table logic validated on synthetic sample data. No ingester/ontology changes.

---

## 2026-08-24 — Curated-email `in_reply_to` index crash + threading fix

**Symptom.** Stage 1 Phase 0 crashed mid-seed of the curated email corpus:
`Property value is too large to index ... Index: email_in_reply_to (RANGE)
schema=(:EmailMessage {in_reply_to}) ... property size: 8913`. The failing batch
fell back per-item, failed again on the same document, and `run_pipeline.py`
aborted at ~2.03M / 4.72M events.

**Root cause.** Neo4j RANGE indexes cap an indexed property at ~8 KB. In the
curated email `.jl` files (ffmpeg/ozlabs/kernel, Patchwork-derived), the JSON
field `in_reply_to` is sometimes a **list of ancestor message-ids** (the review /
cover-letter chain), not a single string. Measured in Mongo `raw_emails`
(4,720,551 docs): 25,670 records carry a list, of which 24 exceed 8 KB. The
ingester (`miner/curated_email_ingester.py`) saved the raw list verbatim, and the
projector wrote it straight onto `EmailMessage.in_reply_to` — the oversized ones
aborted the whole batch MERGE.

**Second (silent) defect.** `enrichment/email_threading.py` matches
`parent.message_id = reply.in_reply_to` exactly. A list value never equals a
string `message_id`, so the 25,670 list-typed records would have produced **zero**
REPLIES_TO edges even without the crash — threading was silently lost.

**Decision (interpretation at the projection boundary).** Mongo keeps the
verbatim source (traceability, AGENTS.md §1); interpretation lives in
`projector/graph_projector.py`. New pure helper `_sanitize_email_threading`
(module-level) normalizes `(message_id, in_reply_to, references)`:
- strip `message_id`;
- extract `<...>` tokens from str-or-list `in_reply_to`, order-preserving dedupe,
  drop the message's own id (RFC 5322: a message is never its own In-Reply-To);
- exactly one distinct id survives → that is the direct parent (`in_reply_to`);
- otherwise → `in_reply_to = NULL`, ids preserved on `references` (unindexed,
  exempt from the size cap); a >998-char candidate is demoted rather than
  truncated (a truncated id would be a dead edge target).

Wired into both `_upsert_email_batch` (row building) and `upsert_email_message`
(params). The `references`-on-match refresh is **deterministic** (a pure function
of the Mongo doc), so Phase 0 stays deterministic (§5.10 discipline).

**Healing already-written nodes.** `in_reply_to` was `ON CREATE SET`-only, so the
up-to-25,646 list-typed nodes (<8 KB) written before the crash would have
survived a re-run with stale list values. `ON MATCH SET` now also refreshes
`message_id`/`in_reply_to`/`references` in both email Cypher statements
(`SET prop = NULL` removes a property — the healing semantics). `stream_raw` is
untrimmed, so re-running Stage 1 re-processes all 4,720,551 events idempotently
and heals every previously-written email node. No `republish_events.py`, no
backfill script.

**Distribution recorded (pilot observation 2026-08-24).** 25,670 list records:
22,746 single-distinct (unambiguous parent, 0 self-referential) / 2,924
multi-distinct (of which 131 contain the own id; excluding it rescues 32). Plus
21,450 string-typed `in_reply_to` with surrounding whitespace, 306 multi-token
strings, 333 bracket-less, 392 blank — all now normalized (stripping gains edges:
20k-sample exact-match 8,137 → 8,172). `message_id` is clean in this corpus
(0 whitespace); the strip is defensive for other corpora.

**Tests.** New self-contained `tests/test_email_threading_sanitize.py` (14 golden
examples, no services). `ruff check`/`format` clean. The pre-existing
`tests/test_gmane_ingester.py` collection error (imports `_group_prefilter_bytes`,
renamed) is unrelated and left untouched.

---

## 2026-08-23 — Code-review follow-up: data-safety + correctness fixes to the Stage 2 resume/speed work

A focused review of the 2026-08-23 session's changes found two real data-loss
risks and several correctness/robustness gaps. These fixes land on top of the
original entry below (which stays as the faithful session record; this entry
records the corrections).

**1. Projector deleted Redis events before Neo4j commit (critical).**
`read_all(trim=True)` deleted a yielded batch as soon as the consumer asked for
the next one, but `_phase2_project_signals` buffered multiple batches before
flushing — and `_flush` swallowed write failures. With the batch raised to 500,
up to four 100-msg batches could be deleted while only in the in-memory buffer;
a crash lost them permanently while the producer HWM claimed the units done.
`projector/worker.py` now commits **each** yielded batch (batch_size =
`projector_signal_batch_size`) before read_all can trim it, and `_flush` lets
Neo4j errors propagate so iteration stops and Redis retains the events. The
buffering and its `SIGNAL_FLUSH_SEC` timer were removed (`projector_signal_flush_sec`
setting dropped). A batch is durable (Neo4j) before its Redis entries are freed.

**2. HWM advanced past failed units (critical).** Parse/annotator/classifier
failures were logged but the batch's last id still became the HWM, so a restart
skipped the incomplete batch. `_annotate_batch` now returns a `complete` flag,
false on any unexpected parse/annotator/classifier failure; the worker raises
(loud, re-runnable) without advancing the contiguous HWM. Oversized skips remain
deliberate (marked complete). Signals published before the failure are kept; the
MERGEs are idempotent so the re-do of the boundary unit is free.

**3. The "classifier padding fix" was a no-op (critical).** Sorting a single
batch does not change its max length — all units still padded to the longest.
`_classifier_unit_batches` now sorts AND splits into microbatches of
`classifier_batch_size` (16), the actual mechanism that reduces padded-token
work. `bench_annotators.py` A/B now compares one-call vs microbatch, not sorted
vs unsorted.

**4. HWM key made collision-proof and config-scoped.** TextUnit ids contain
colons, so `{lo}:{hi}` keys could collide; and an old mark could be reused after
a scope/rule/classifier change. `_hwm_key` now hashes canonical JSON of
{bounds, scope, pattern version, classifier path} and the bounds are validated
`id_lo <= hwm < id_hi`.

**5. Frontier is now correct for sharded runs.** `max(annotated id)` is only
valid for K=1; concurrent shards finish out of order and can leave a low-id gap.
`find_annotation_frontier.py` now uses `min(id)` over in-scope, non-oversized
units with no verdict (oversized skips excluded) — correct for both K=1 and
sharded interruption. Re-verified frontier:
`jira_issue:alternative-jira:Mojang:MC-118019:comment_body:3`, 7.72 M units /
355 M tokens remaining.

**6. Shard boundaries are now scope-aware and id_lo-consistent.**
`compute_shard_boundaries` applied the annotation scope to total+scan so the
boundaries partition the in-scope population the workers parse; the first scan
page is inclusive at `id_lo` (matching the half-open ranges). Quantile logic
extracted to pure `_quantile_boundaries` (boundary = first row strictly past
threshold) so it is unit-tested.

**7. CLI hardening.** `--annotate-shards` rejects <1 (was a silent no-op);
the failed-shard recovery message is one command per shard and preserves
`--resume-from`/`--resume` so it re-runs the original partition.

**8. Compose memory parameterized + Redis headroom.** Neo4j pagecache/heap and
Mongo cache are env-parameterized; Redis `maxmemory` (10g) now sits below the
container `mem_limit` (16g) so allocator fragmentation cannot bypass Redis's own
noeviction path.

**9. Malformed-batch trim hang fixed.** `read_all` now trims a batch's IDs even
when every payload failed to parse; previously they stayed in the stream and
`XLEN` never reached 0, so stop_event-aware draining hung forever. Regression
test added.

**10. Progress rate is now a true rolling window** (timestamped-sample deque),
not a resettable tumbling average that diluted late slowdowns.

**11. Bench sampling stratified + classifier counts split.** Units are sampled
across the id space (not a leading prefix), and `rule_signals/unit` is reported
separately from the classifier's `clf_plain/unit` (2 records/unit) so the
classifier's contribution is not conflated.

**Verified:** 135 self-contained tests pass (regression + new tests for
`_quantile_boundaries`, hashed HWM key, microbatch coverage, completeness flag,
malformed-trim drain); `ruff check`/`format` clean; compose validates; frontier
re-run yields the corrected boundary above.

**Note on the resume frontier.** This follow-up moved the frontier from
`...comment_body:2` to `...comment_body:3` (the earliest non-oversized unit with
no verdict). Both are valid resume points for the K=1 interruption; use the
value `find_annotation_frontier.py` reports at resume time.

---

## 2026-08-23 — Stage 2 slowdown diagnosis + resume, instrumentation, and classifier padding fix

The 2026-08-21 Stage-2 run (single-process, K=1) was stopped at 64.8% after
degrading from ~420 to ~26 units/s. Diagnosis and the fixes implemented here.

### Diagnosis (why it got slow)
- **The Progress rate is a lifetime average** (`done/elapsed`); instantaneous
  rate fell 420 → 231 → ~68 → ~26 units/s while the displayed ETA still read
  "24 h" (true remaining was ~1.5–3.5 days). `progress.py` now also logs a
  60 s window rate and the ETA uses it, so a slowdown is visible immediately.
- **Corpus heterogeneity**: the id-ordered walk goes chat (short, ~2.6 signals/
  unit) → GitHub issues → Jira (16.2 M units, avg 57 tokens, ~10 signals/unit).
  Units/s *must* fall along this path — but signals/s also fell (1130 → 270/s).
- **Neo4j page-cache starvation** (systemic): the live store is **111 GiB**
  (22 M TextUnits + 70 M Signals + edges + indexes) behind a **2 GiB pagecache**
  sized when the graph was "~9M nodes". Every signal MERGE page-faults to the
  external SSD through the Docker VM; both the projector's writes and the
  annotator's keyset reads degraded in lockstep. Mongo idled at 21 GiB in the
  shared 63 GiB VM. Neo4j CPU ~3% = I/O bound, not CPU bound.
- **Single annotator process on a 28-core machine**, blocked part of the time on
  MPS classifier inference and Neo4j reads (~77% of one core), with a 25 GiB RSS.
- The **classifier padded every batch to its longest text**: with `padding=True`,
  one 2 000-token Jira body padded the other 63 units to 512 tokens, wasting most
  MPS inference on padding.

### Fixes
1. **Resume support** (`annotators/worker.py`, `scripts/run_pipeline.py`,
   `broker.py`, `scripts/find_annotation_frontier.py`): the id-ordered walk
   makes resume cheap. Each batch's last unit id is persisted to Redis
   (`graphrag.annotate.hwm:{id_lo}:{id_hi}`) after it is fully published; a
   restart with `--resume` continues from the mark instead of re-annotating.
   `--resume-from <id>` is a one-off boundary; `compute_shard_boundaries` gained
   an `id_lo` so resumed shards balance the remaining range only. `broker` gained
   thin `set`/`get` string helpers. Signal MERGEs are idempotent, so the inclusive
   re-do of the single boundary unit is free.
2. **Frontier recovery** (`scripts/find_annotation_frontier.py`): computes the
   resume boundary for a run that had no mark (this one). Boundary = **max
   in-scope id with a ClassifierVerdict**. Deliberately NOT "min id without a
   verdict": oversized units (>100k chars) carry no verdict, so that would land
   on an oversized gap early in the walk and re-annotate millions of done units.
   Verified invariant: every non-oversized in-scope unit below the max-annotated
   id already has a verdict (only 1 723 oversized holes). Reported frontier:
   `jira_issue:alternative-jira:Mojang:MC-118019:comment_body:2`, 7.72 M in-scope
   units / 355 M tokens remaining.
3. **Instrumentation** (`annotators/worker.py::_PhaseTimings`,
   `projector/worker.py`, `scripts/bench_annotators.py`): rolling per-phase
   median timings (parse / rule / classifier / batch_total) logged every 30 s,
   and projector flush latency — the instrument that answers "which annotator is
   the bottleneck" on the real corpus. `bench_annotators.py` samples units per
   parent_type and times each annotator separately, including the classifier
   unsorted vs length-sorted (the padding-fix A/B).
4. **Classifier padding fix** (`annotators/worker.py::_annotate_batch`): sort
   `parsed_units` by text length before the classifier batch so long-tail bodies
   no longer pad their neighbours. Per-unit predictions are order-independent;
   semantics unchanged (verified by test).
5. **Environment** (`docker-compose.yml`): Neo4j pagecache 2g → 48g, heap 4g →
   8g; Mongo capped at 8 GiB (it is idle during Stage 2 but held 21 GiB). **The
   Docker Desktop VM must be raised from 63 to ~128 GiB before `docker compose
   up`** (host has 256 GiB) — otherwise Neo4j's 56 GiB heap+pagecache plus Mongo
   cannot fit.
6. **Projector batch size** (`settings.py`): `projector_signal_batch_size`
   (500, was constant 100) and `projector_signal_flush_sec` as settings.

### Decision
The user chose to stop the limping run and resume with the fixes (full remaining
Jira, no sampling). The corrected resume command:

```
docker compose down && docker compose up -d      # after bumping the VM to 128 GiB
python scripts/find_annotation_frontier.py       # re-run to confirm the frontier
python scripts/run_pipeline.py --stage 2 --annotate-shards 8 \
    --resume-from "jira_issue:alternative-jira:Mojang:MC-118019:comment_body:2"
python scripts/run_pipeline.py --enrich          # the original run's enrichment never started
```

**Verified:** 51 self-contained tests pass (5 new in `tests/test_annotator_resume.py`
covering hwm key, resume-inclusive pagination, and classifier length-sort);
`ruff check`/`format` clean on new code; `smoke_annotate.py` unchanged.

**Not addressed (noted):** concurrent projector tasks (still single-consumer; if the
projector caps below combined shard output after the cache fix, the 200 k backpressure
gate throttles producers safely — revisit only then). `tests/test_gmane_ingester.py`
still fails collection (pre-existing `_group_prefilter_bytes` import, CHANGELOG
2026-08-19).

---

## 2026-08-21 — Stage 2 concurrency: batched publish + concurrent projector + backpressure + sharding

Four coordinated changes to make Stage 2 (annotate + project signals) faster and
safer. The single-process annotator ran at ~172/s (ETA ~36 h for the 22.3M-unit
scope) and, because Stage 2 previously waited to project until annotation
finished, the whole signal backlog piled into Redis before Neo4j saw any of it.

**1. Milestone B — batched signal publishing** (`annotators/worker.py`).
`_annotate_batch` is now pure: it accumulates the serialised Signal payloads for
a whole 64-unit batch and returns them; the worker flushes them in ONE
`broker.publish_many()` per batch instead of one awaited `XADD` per signal
(~hundreds of Redis round trips per batch before).

**2. Milestone C — concurrent Phase-2 projector** (`broker.py`,
`projector/worker.py`, `scripts/run_pipeline.py`). Stage 2 now runs the annotator
process(es) and the Phase-2 projector CONCURRENTLY, so `stream_signals` is
drained while it is produced. `broker.read_all` gained a producer-aware
`stop_event` mode: the projector no longer exits on stream silence (which caused
the 2026-08-18 premature-exit bug) — it exits only once the producers signal
completion AND the stream is drained. `--skip-annotate` keeps the legacy
standalone-drain exit.

**3. Milestone D — annotator backpressure** (`settings.py`,
`annotators/worker.py`). New `settings.annotator_max_stream_signals_backlog`
(default 200k, ~130 MiB at the measured ~675 B/signal) gates the producer: after
each publish it waits if the backlog exceeds the ceiling (mirrors the extractor's
`stream_units` gate). Structurally prevents any producer speed from exhausting
Redis's 12 GiB `noeviction` limit while the projector drains behind it.

**4. Milestone E — keyset-range sharding** (`annotators/worker.py`,
`scripts/run_pipeline.py`, `settings.py`). `--annotate-shards K` spawns K
annotator processes, each owning a disjoint `[id_lo, id_hi)` range of the
ordered `TextUnit.id` space (added via `_shard_where`, applied to count,
pagination, and Progress — label `Annotate[3/8]`). `--shard-index I` re-runs
only that shard (recovery: 1/K of the corpus instead of all of it). Annotators
always run as spawned children (even K=1), so the parent stays free to run the
projector. Live validation: K=8 token-balanced boundaries split the corpus into
8 shards of ~125.6M tokens each (±0.05%), and the range predicate is served by
the `TextUnit.id` uniqueness index. A K=2 smoke confirmed the sharded path
end-to-end (two labeled shard progress lines + concurrent projector drain).

Boundary-computation design note (`compute_shard_boundaries`): exact quantile
boundaries need an O(N) index walk. Two rejected alternatives (measured against
the live 23.4M corpus): per-probe `ORDER BY u.id SKIP n LIMIT 1` took 44 s for a
single SKIP-11M probe (~330 s for K=8); a single unbounded ordered stream OOM'd
the server transaction memory (Neo4j materialises the full result set). Chosen:
one keyset-pagination pass over the id index (~4 min for K=8), paid once per
`--annotate-shards > 1` run; K=1 (default) pays nothing.

Boundaries balance cumulative **`token_count`**, not node count — parse cost
scales with text length. A count-quantile K=2 split proved pathological live:
shard 0 (short chat/issue units) ran 305/s while shard 1 (long Jira bodies)
ran 72/s, so the slow shard set the wall clock. Token-balancing equalises
per-shard work: the 23.4M-unit corpus splits into 8 shards of ~125.6M tokens
each (±0.05%), with unit counts ranging 1.8M–7.4M.

**Verified:** 92 self-contained tests pass (including new
`tests/test_annotator_sharding.py` and updated `tests/test_annotator_worker_batch.py`);
`ruff check`/`format` clean on new code; live smoke K=1 showed the projector
draining `stream_signals` at ~9.6k/s while the annotator child produced, and
drained the 1.34M-signal backlog to ~380 in ~3 min. K=2 smoke run to confirm
two shard progress lines end-to-end.

**Known trade-offs / not addressed:**
- Boundary computation is ~4 min for `--annotate-shards 8` (O(N) floor, one-time).
- Per-shard startup count query is ~24 s (label-scan over the in-scope set).
- Ctrl-C during annotation is handled by the supervisor's `finally` (children
  terminated, projector task cancelled), but spawn children have a
  `multiprocessing.spawn` cmdline — a manual `pkill -f run_pipeline.py` won't
  match them; terminate via the parent or the full process group.

**Follow-up fix (same day, 2026-08-21): projector-death hang.** The parent's
child-liveness poll loop could hang Stage 2 indefinitely if the projector task
failed mid-run: the children would block forever on the backpressure gate
(nothing draining `stream_signals`) while the parent kept polling never-exiting
children, leaving the projector's exception unretrieved. New
`_wait_for_children_or_projector` (scripts/run_pipeline.py) also returns when
the projector task finishes, so its exception re-raises and the `finally` reaps
the children — a loud failure instead of a silent overnight hang. Removed the
now-dead `_publish_signal` (worker.py), and `compute_shard_boundaries` now
raises a descriptive `RuntimeError` (not a bare `KeyError`) if the boundary
scan ever disagrees with `sum(token_count)`. Regression tests added for the
poll helper.

---

## 2026-08-20 — Annotator worker fault tolerance (oversized-unit skip + per-unit fallback)

Symptom: the 2026-08-20 annotation run crashed ~10h in at 28.8% with spaCy
`ValueError [E088]`: one TextUnit of 5,913,370 chars exceeded `nlp.max_length`
(1M default). The exception propagated out of the lazy `nlp.pipe` generator
inside `process_batch` and killed the whole annotator worker.

Root cause (live Cypher census): oversized units are NOT a general TextUnit-size
problem — exactly **2,745 Jira units exceed 100k chars** (1,486 bodies, 1,259
comments; max 15.1M chars), all pasted logs/stack traces in Apache Jira data.
Only 1 GitHub issue unit is oversized. The 22.3M-unit scope is dominated by
**16.2M jira_issue units (median 133 chars)** + 5.8M chat messages + 1.3M
GitHub issues — corpus reality, not an extractor bug.

Decision (annotators/worker.py, settings.py):
1. **Annotation-scope skip, not a TextUnit-granularity change.** New
   `settings.annotate_max_chars = 100_000`; `_annotate_batch` drops units whose
   `len(text) > max_chars` *before* parsing, logging id + parent_type + size.
   Same class of scope decision as `annotate_min_tokens` — **NOT** signal
   filtering (AGENTS.md §5.3). Extractor granularity stays per locked decision
   v0-1 (one unit per parent+role); a >100k-char unit is a paste, not epistemic
   discourse.
2. **Per-unit fallback** — `_annotate_batch` materialises `zip(units, nlp.pipe())`
   inside try/except; on a batch-level parse failure it retries each unit via
   `nlp(text)` with its own try/except, so one bad unit degrades to a skip
   instead of halting the run. Confirmed the classifier must also see only
   successfully-parsed units, or a unit would carry classifier signals but no
   rule signals (partial, incoherent annotation).
3. `_iter_text_units` now also returns `u.parent_type` so skip warnings identify
   the corpus.

Verified: new `tests/test_annotator_worker_batch.py` (4 tests, fake nlp/
annotators/broker) covers oversize skip, pipe-failure fallback, per-unit
failure isolation, and annotator-failure isolation; 76 pre-existing
self-contained tests still pass; `ruff check` clean on new regions.

**Not addressed (noted, not blocked):** the annotator still re-annotates from
scratch after a crash — no resume marker — so a mid-run failure re-does prior
work (idempotent Signal MERGEs make this safe, just slow). Resume support is
deferred; tracked for a future session.

---

## 2026-08-19 — Phase 0 batched end-to-end (Mongo $in + per-family UNWIND)

Symptom: Phase 0 ("Seed artefacts") collapsed to ~100–300/s from the start
(ETA 10–24 h) while the prior healthy run did ~1,250/s (8.99 M ≈ 2 h). Logs
also showed `Phase 0: bad mongo_id … operation cancelled` — the same pymongo
`_OperationCancelled` connection-teardown that crashed the Gitter ingest the
same session. Root cause was two-fold: (a) Phase 0 was the **only stage still
doing per-record round trips** — one Mongo `find_one` + one Neo4j `_run` per
event (9.9 M events ≈ 10 M of each); (b) transient `AutoReconnect` failures
were **silently dropped** by `_seed_one`'s warn-and-return (data loss within a
run) and throttled throughput during connection churn.

Fixes (projector/worker.py, projector/graph_projector.py, settings.py):

1. **Batch the Mongo fetch** — `_phase0_seed_artefacts` now reads
   `phase0_batch_size` (default 1000) events per Redis XREAD and fetches them
   in ONE `$in` `find` per `_collection_for` collection (`_fetch_batch_docs`),
   instead of a `find_one` per event.
2. **Batch the Neo4j writes** — new `GraphProjector.upsert_artefacts_batch`
   groups each batch's (event, doc) pairs by family (email / jira / bugzilla /
   chat / so_post / github issue / PR / commit / repository) and writes each
   family with ONE `UNWIND` MERGE statement, mirroring `upsert_text_units_batch`
   / `upsert_signals_batch`. The per-item `upsert_artefact_from_raw` is kept as
   the per-row fallback (one bad doc does not poison a family batch).
3. **Retry, don't drop** — `_fetch_batch_docs` retries `AutoReconnect` (parent
   of `_OperationCancelled`) 3× with backoff instead of the old per-event
   warn-and-return. A persistent Mongo outage now raises and halts the phase
   rather than silently losing artefacts.
4. **Batch size** — `settings.phase0_batch_size = 1000` amortizes all three hops
   (XREAD, Mongo `$in`, Neo4j `UNWIND`). `projector_phase0_concurrency` /
   `mongo_fetch_concurrency` no longer drive Phase 0 (superseded by batching);
   left in place for backward compatibility.

**Latent bug fixed while batching:** `MERGE (v:Venue {venue_id})-[:HAS_CONVERSATION]->(c)`
(chat conversation wiring, both the new batch path and the existing single-item
`_upsert_chat_artefact`) throws `ConstraintError` "Node already exists with
label Venue" whenever the Venue exists but the edge does not — Neo4j MERGE tries
to CREATE the whole unmatched relationship pattern. Fixed by `MATCH (v:Venue …)`
then `MERGE (v)-[:HAS_CONVERSATION]->(c)`. This was a pre-existing silent
partial-failure in the conversation path.

Verified live against Neo4j + Mongo: synthetic batch exercising every family
produced all 7 artefact labels, 7 `AUTHORED` edges, the SO `ANSWERS` edge, and
the `HAS_CONVERSATION` edge correctly, then cleaned up; `_fetch_batch_docs`
returned the right docs for a mixed-collection batch. `ruff check` / `ruff format`
clean.

Note: the observed VM instability behind the `_OperationCancelled`s (Redis
restarted again today; `mem_limit: 12g` on a 7.65 GiB Docker VM) is a separate
systemic concern and not addressed by this change.

---

## 2026-08-19 — Alternative Jira ingest fixed (3 stacked root causes)

The Alternative Jira corpus (`miner/jira_ingester.py --corpus alternative`) ingested
0 records. Investigation found three stacked causes:

1. **mongorestore prerequisite never run.** The archive holds ONE collection per
   Jira instance in db `JiraReposAnon` (16 collections: Apache, MongoDB, Qt,
   RedHat, Spring, ...), restored with
   `mongorestore --gzip --archive=mongodump-JiraReposAnon.archive`. With the db
   absent, Motor's `find()` returned an empty cursor silently → "0 persisted /
   0 scanned", no error. Docstring's old `--nsFrom/--nsTo` identity mapping was
   a no-op; replaced with the correct command.
2. **Default `--collection issues` did not exist.** The ingester read exactly one
   collection per invocation. Now the alternative path lists all collections in
   the db (or a `--collections` subset) and streams them sequentially.
3. **`ALTI_FIELD_MAP` did not match the doc shape.** Docs are raw Jira REST
   `/search` JSON (confirmed via the dataset's own `DownloadData.ipynb`): the
   issue `key` is top-level, but `summary`, `description`, `status.name`,
   `creator`/`reporter`, `created`, `project.name`, `comments` are all nested
   under `fields`. The flat map found `key` but never summary/description, so
   every doc was dropped as "nothing to annotate". `ALTI_FIELD_MAP` is now a map
   of nested key paths, and `_alt_get` traverses them (first non-null path wins).

Additionally, `record_id` and `venue_id` now include the Jira instance
(collection name) — issue keys like "SPRING-1" can collide across Jira
instances, which would otherwise silently overwrite docs on the `raw_external`
`record_id` unique key. `metadata.jira_instance` records the source instance.
Comment author_login now comes from each comment's own `author` field (falling
back to the issue creator) instead of attributing every comment to the creator
— real comment objects carry their own anonymized author.

Verified against the restored corpus (16 collections, ~2.7M issues): MariaDB
and Mindville carry no comments (both Jiras offline at download time — dataset
README), all 14 others do; sample extraction shows correct titles, bodies,
states, per-comment authors, and namespaced anonymized logins.

Verification: golden tests for the nested REST shape (record_id uniqueness per
instance, None-comments guard, no-text and missing-key → None) added to
`tests/test_external_ingesters.py`; 6 pass. Noted pre-existing breakage:
`tests/test_gmane_ingester.py` fails collection (`ImportError: cannot import
name '_group_prefilter_bytes'` — the function no longer exists in
`miner/gmane_ingester.py`); unrelated to this fix, left as-is.

---

## 2026-08-19 — Curated-ingester fixes + `02b_rq_analysis.ipynb` notebook

### 1. Quadratic progress-logging bug in the shared external ingest engine

`miner/external_common.py::run_external_ingest` fed `prog.add(kept)` the
**cumulative** `kept` total on every batch flush, so `Progress.done` grew as
1000·B·(B+1) (quadratic) and the reported rate rose ~linearly. User log for the
DISCO ingest showed "ingestions/s" climbing from 3.8k to >1.2M/s while the real
rate was constant (~4.9k/s) — the actual corpus write counts were correct, only
the progress/rate accounting was inflated. Every curated ingester that routes
through `run_external_ingest` (all 12) was affected.

Fix: `_flush_batch()` advances progress by `len(batch)` (docs processed per
flush), the trailing batch is now logged too, and `bs` is capped by `--max`
(`min(bs, max_records)`) so a bounded debug run does not over-shoot by a whole
batch. Regression tests (`test_run_external_ingest_progress_is_linear`,
`test_run_external_ingest_max_bounds_batch`) run the non-dry-run path fully
offline via monkeypatched Mongo/Redis/progress.

### 2. DISCO/Slack community-period path parsing

`iter_discord_records` / `iter_slack_records` computed the relative path one
directory short of `data/`: DISCO swapped community↔period (record_ids carried
the period as community and the channel filename as period); Slack always fell
back to "unknown"/"unknown". Both now share `external_common.data_path_parts`,
which splits on the LAST `data/` path component. Regression tests assert the
real period (`2020` / `2018`) appears in each record_id.

### 3. Alternative Jira creator/reporter as user dict

`normalize_alternative_doc` passed the raw `creator` field to
`namespaced_login`; a Jira user dict was stringified into `-name-:-user-`.
New `_alt_author_name` extracts `name`/`username`/`key`/`displayName` from a
dict, is a no-op for plain strings. Regression test covers both shapes.

Added `notebooks/02b_rq_analysis.ipynb` (70 cells): ports `02_rq_analysis.ipynb`
(v0.2 question set, RQ1–RQ6 incl. RQ4a–d and RQ5) onto the v0.8 multi-platform
ontology and the 12 curated MSR corpora. All Cypher routes TextUnits through
`:Artefact` `corpus_id`/`platform_id`/`venue_id` with a corpus registry scope
filter (old GitHub/Gmane excluded); the arena dichotomy becomes corpus × genre
(statistical comparisons and register predictions per genre); RQ6.5 role
contrast (OpenMent mentor vs mentee) and RQ6.6 REPLIES_TO threading position
are ported from the v0.3 notebooks. Exports are prefixed `02b_` so they do not
clobber `02_rq_analysis.ipynb` artefacts. Runs with no services (dry-run/empty
frames are guarded); the canonical v0.3 analysis remains `03_rq_analysis.ipynb`.

---

## 2026-08-18 — Curated-email oversized-body guard (16 MiB BSON crash)

`python -m miner.curated_email_ingester` crashed on `kernel-comment-24774599`:
its review comment embeds the full quoted patch incl. a git binary base85 blob,
pushing the raw Mongo doc past the 16 MiB BSON limit. Because
`run_external_ingest` flushes 2000-doc batches, one oversized doc failed the
WHOLE bulk upsert (`BulkWriteError`) and aborted the run.

Fix (`miner/curated_email_ingester.py`): records whose `body` exceeds
`DEFAULT_MAX_WORDS = 10_000` whitespace tokens are dropped at parse time (with a
warning naming the record), so they never enter a batch. `--max-words` CLI flag
overrides the threshold; `0`/negative disables the guard (`max_words=None`).
The `len(body) > max_words` character pre-check avoids the `split()` allocation
for the ~1.34M normal emails. Authored epistemic discourse never approaches
10k words — oversized bodies are patch/log-embedded content, so no research
loss. Threshold default chosen at user's request over 20k. Scope kept to the
curated-email reader; the shared `external_common.py` engine is unchanged.
Regression test `test_curated_email_skips_oversized_body`.

---

## 2026-08-18 — Email-threading chunking + sequential Stage 2 + batched signal wiring

Two failures on the 2026-08-18 full run, fixed here.

**1. Email threading enrichment timed out (`OSError('No data')`).**
`enrichment/email_threading.py` created ~870k REPLIES_TO edges in ONE unbounded
transaction: it locked ~1.7M nodes at once, Neo4j stalled in GC, and the Bolt
socket timed out. Fixed with `CALL { ... } IN TRANSACTIONS OF 10000 ROWS`
(commits + releases locks every 10k rows). Verified live: completed in ~4.8s,
498,240 REPLIES_TO edges written (MERGE-deduped).

**2. 3.07M signals stuck in Redis, 0 in Neo4j.**
Stage 2 ran the annotator and Phase 2 concurrently; Phase 2 saw 4s of silence
on stream_signals while the annotator loaded spaCy + RoBERTa, declared the
stream exhausted, and exited early. The annotator then ran 14.5h and queued all
3,076,835 signals into Redis, but nothing projected them.
- `scripts/run_pipeline.py`: Stage 2 is now SEQUENTIAL — annotator first, then
  `run_projector_stage2()`. The annotator is not re-run: signals are already in
  Redis, so `--stage 2` alone drains them.
- `projector/graph_projector.py`: `upsert_signals_batch` now batches the
  post-wiring too. Previously each verdict/lexical/rhetorical signal cost one
  Neo4j round trip via `upsert_classifier_verdict` / `_upsert_lexical_marker` /
  `_upsert_rhetorical_figure` (≈3M round trips); now ClassifierVerdict +
  CLASSIFIED_AS, LexicalMarker + MATCHES_MARKER, RhetoricalFigure +
  INSTANTIATES are each ONE UNWIND per ~100 signals. Removed the three dead
  per-signal methods. Verified live: 2-signal smoke produced correct nodes and
  all edge types.

Recovery (nothing to re-annotate — TextUnits + signals already exist):
```bash
python scripts/run_pipeline.py --stage 2    # drain 3.07M signals → Neo4j (batched)
python scripts/run_pipeline.py --enrich     # references (done) + email + IRC threading
```

---

## 2026-08-16 — Phase 1 TextUnit batching + extractor backpressure (+ resume flag)

Symptom (second crash): Phase 1 ("Project TextUnits") consumed `stream_units` at
~500 units/s while the extractor produced ~8,000 TextUnits/s. The queue grew by
~7,500/s until ~700k+ full-text units were buffered in Redis, blowing past the
Docker VM memory and hanging the VM — Neo4j bolt timeouts, then "Connection
closed by server" from Redis, then the Docker daemon froze.

Root cause: `_phase1_project_units` wrote TextUnits ONE AT A TIME
(`await projector.upsert_text_unit(event)` per unit) = one Neo4j round trip per
unit, capping Phase 1 at ~500/s. That is the same "serial per-record round trip"
pattern that Phase 0 suffered from before the earlier batch/memo work.

Fixes:
- `projector/graph_projector.py`: new `upsert_text_units_batch(units)` — ONE
  `UNWIND $units` statement writes up to 100 TextUnits + `HAS_TEXT` edges in one
  round trip. Parents matched uniformly via `:Artefact {record_id: u.parent_id}`
  (every Phase-0-seeded parent carries `:Artefact` and `record_id == parent_id`,
  so this uses the `artefact_record_id` index).
- `projector/worker.py`: `_phase1_project_units` now batches in ~100-unit chunks;
  on a batch failure it falls back to the per-unit `upsert_text_unit` so one bad
  unit does not drop a whole batch. Verified live: 2000 units written correctly
  at ~4,400–7,300/s (vs ~500/s), ~10× faster — now at/above the extractor rate.
- `extractor/worker.py`: backpressure — before each batch the extractor checks
  `stream_length(stream_units)` and pauses (`sleep 0.5`) while the backlog is
  above `extractor_max_stream_units_backlog` (new setting, default 50,000 ≈
  50 MB). This is a safety net that guarantees `stream_units` can never buffer
  the corpus again, whatever the speed balance.
- `scripts/run_pipeline.py`: `--skip-phase0` flag to RESUME a run whose Phase 0
  already completed. After a crash + Redis wipe, Phase 0 re-seeding all 8.99M
  artefacts is a ~2h idempotent no-op; `--skip-phase0` skips it and goes straight
  to extract+project. The extractor still needs `stream_raw` (rebuilt via
  `scripts/republish_events.py`), and parents are already in Neo4j.

Recovery after the crash (all Phase-0 artefacts were preserved on the Neo4j
external-drive volume; Redis is non-persistent so its streams were wiped):
```bash
python scripts/republish_events.py          # rebuild stream_raw (~2 min)
python scripts/run_pipeline.py --skip-phase0 --enrich   # resume extract+project
```
Note: the Docker Desktop VM hung and was restarted; the compose stack was
brought back up with all containers, and `--census` can verify state.

---

## 2026-08-16 — Phase 0 slowdown fix: per-family record_id uniqueness constraints

Symptom: Phase 0 started fast (~700/s) and decayed monotonically to ~133/s at
9.6% (ETA 17h), with Neo4j pegged at ~2000% CPU.

Root cause: the v0.8 external artefacts are upserted by MERGE on their OWN label
(`MERGE (m:ChatMessage {record_id: ...})`, `JiraIssue`, `BugzillaIssue`,
`StackOverflowPost`), but only the shared `:Artefact(record_id)` constraint
existed. A constraint on `:Artefact` does NOT accelerate a MERGE that targets a
more specific label — every such MERGE fell back to a FULL LABEL SCAN growing
linearly with the corpus. Verified live: `EXPLAIN MERGE (m:ChatMessage
{record_id:'x'})` showed `NodeByLabelScan` over 881,070 nodes; at 64-way
concurrency those scans saturated all cores and the cost per item kept rising.

Fix:
- `ontology/ontology.cypher`: added `chatmessage_record_id`,
  `jiraissue_record_id`, `bugzillaissue_record_id`, `sopost_record_id`
  uniqueness constraints (same record_ids as the :Artefact constraint — no new
  keys, just an O(1) seek path for the family-label MERGEs).
- `docker-compose.yml`: Neo4j pagecache 512m → 2g so the ~9M-node graph +
  indexes stay resident.
- Applied the four constraints to the live database (idempotent; verified
  present after the pagecache container recreate). `EXPLAIN` now shows
  `MergeUniqueNode` (O(1)); measured ~2 ms/op vs the previous multi-hundred-ms
  scans. Throughput should return to the 1000s/s and STAY CONSTANT instead of
  decaying, because the seek does not depend on corpus size.
- Swept `graph_projector.py`: every `MERGE (label {key})` now has a matching
  uniqueness constraint (Repository/Actor/Platform/Venue/Corpus/Issue/PR/Commit/
  TextUnit/Conversation/MailingList/EmailMessage/Signal/ClassifierVerdict/
  LexicalMarker/RhetoricalFigure/Artefact + the four new family ones).

---

## 2026-08-16 — Corpus census + pipeline pre-flight visibility

Adds read-only diagnostics so "nothing is missing" can be verified at a glance,
and turns the confusing "0 to process" after a Redis restart into a clear action.

- `scripts/corpus_census.py` (new, shared): canonical dataset list
  (FRAMEWORK_DESIGN §12), the curated `corpus_id` registry, and
  `mongo_corpus_counts(db)` — per-`corpus_id` document counts via one
  aggregation per raw collection (read-only).
- `scripts/run_pipeline.py`:
  - **`--census`** flag: read-only dashboard of MongoDB corpus census + Redis
    stream lengths/memory + Neo4j node counts (Artefact/TextUnit/Signal by
    corpus). Exits without running anything.
  - **Pre-flight gate on Stage 1:** if `stream_raw` is empty but MongoDB holds
    curated docs (the state after a Redis restart — non-persistent), prints the
    full MongoDB census + which canonical datasets are missing + the
    `python scripts/republish_events.py` command, then stops instead of running
    empty stages. Stage-2-only runs are not gated.
- `scripts/republish_events.py`: docs filtered at query time to
  CURATED_CORPORA (no more 15M-doc skip scan), prints the MongoDB census at
  start and a per-corpus published audit + pending-datasets list at completion.
- `miner/external_common.py`: when an ingester finishes `0 persisted (new)` but
  scanned > 0 records, logs that the records already exist in MongoDB and points
  at `republish_events.py` instead of reading as a failure.

Verified live: `--census` reports 8,993,030 curated MongoDB docs
(5/13 datasets pending), `graphrag.raw` 8,993,030 queued, Neo4j empty (needs the
pipeline run); pre-flight passes with a populated stream and prints the census +
prompt with an empty one; DISCO re-ingest prints the new "0 new records — already
exist in MongoDB" hint. 71 self-contained tests pass.

---

## 2026-08-16 — Redis OOM fix: Tier 1 (config) + Tier 3 (Phase 0 speed + staged pipeline)

Root cause of the 2026-08-14 double-crash (both SOTorrent ingest and pipeline
died at once with `Connection reset by peer`): redis-server was OOM-killed.
`stream_raw` is never trimmed (extractor + Phase 0 both read it), it already held
~7M events, SOTorrent added 1.2M more at ~280k/s, and — the decisive factor the
initial fix plan almost missed — **`stream_units` buffered the whole corpus in
Redis**: `run_projector_stage1()` ran Phase 0 to completion BEFORE Phase 1, so
the extractor's ~8-10M TextUnits (full text, ~1KB each ≈ 15-25GB) sat
unconsumed while Phase 0 took hours. Combined with `--save 60 1` (BGSAVE fork
doubling RSS via COW), redis-server crossed the memory ceiling and the kernel
killed it.

Implemented (reviewed plan):

**Tier 1 — Redis config (`docker-compose.yml`).**
- Persistence disabled (`--save ""`): Redis is a transient queue; Mongo is the
  durable source of truth. Removes the fork/COW OOM spike.
- `--maxmemory` 6gb → 12gb and container `mem_limit: 12g`, so an overgrowth
  kills only Redis, not the shared Docker VM.
- Keeps `--maxmemory-policy noeviction` (never silently drop queued work).
- **Consequence (recorded):** streams no longer survive a Redis restart, and
  re-running an ingester does NOT re-publish events for already-ingested docs
  (`bulk_upsert_on_key` returns only new inserts). Recovery is via the new
  `scripts/republish_events.py`, which rebuilds `stream_raw` from Mongo.

**Tier 3 — Phase 0 throughput (`projector/graph_projector.py`, `projector/worker.py`, `settings.py`).**
- Memoized the pure-idempotent container/identity upserts
  (`_ensure_platform_venue_corpus`, `upsert_actor`, Repository MERGE) — venues,
  actors and repos were re-MERGE'd for every artefact (millions of issues vs a
  handful of venues). Memo key is added only AFTER a successful write so a
  failed write can retry.
- Merged each per-artefact `_run` chain (node MERGE + AUTHORED + venue CONTAINS
  + dynamic labels) into ONE statement (`upsert_issue/pull_request/commit/
  email_message`, `_upsert_issue_artefact/chat_artefact/so_post`); conversation
  wiring and the SO `ANSWERS` edge stay separate conditional calls. Removed the
  now-dead `_apply_artefact_labels`.
- New `projector_phase0_concurrency = 64` setting (was effectively 16 via
  `mongo_fetch_concurrency`); `mongo_max_pool_size` 50 → 128.

**Staged pipeline (`scripts/run_pipeline.py`, `projector/worker.py`) — the fix
that caps `stream_units`.**
- Stage 1 split into two sub-stages: (1a) Phase 0 alone (seed artefacts), then
  (1b) extractor + Phase 1 concurrently. Phase 1 (the only `stream_units`
  consumer) now drains `stream_units` live with trim, so it never holds the
  whole corpus. Measured on a 10k-event smoke: peak queue ~34k TextUnits (~34MB)
  instead of multi-GB. `run_projector_stage1()` kept as a legacy sequential
  entry point.
- New `scripts/republish_events.py` + `tests/test_republish_events.py`: rebuilds
  `stream_raw` pointer events deterministically from Mongo for the curated
  corpus only. Old-scope GitHub/Gmane docs are excluded by requiring a curated
  `corpus_id` — re-publishing them re-seeded empty-repo artefacts into the
  graph (caught and cleaned during implementation).

**Atomicity note (as planned).** Per-artefact writes are now a single
transaction instead of 4-8 separate auto-commit transactions. The final graph is
unchanged (idempotent MERGE, deterministic params — Phase 0 contains no
non-deterministic functions; `datetime()` exists only in Phase 2 at Signal /
verdict creation). The behavioral difference: a mid-artefact failure now leaves
NO partial node rather than a partially-seeded one.

**Invariant to preserve (recorded in AGENTS.md).** `_ensure_platform_venue_corpus`,
`upsert_actor` and the Repository MERGE must remain pure idempotent upserts
(no non-deterministic `SET`), or the Phase-0 memoization silently changes
results.

Pipeline-state note: the crash + this container recreate wiped `stream_raw` &
the derived streams. `scripts/republish_events.py` was run and republished the
curated corpus present in Mongo (8,993,030 events: 7.6M raw_external + 1.35M
curated emails; OpenMent/NumFOCUS are not yet ingested). Old-scope GitHub junk
artefacts (5,413) seeded during the smoke were removed from the graph.

---

## 2026-08-14 — v0.3 RQs: curated-corpus scope + OpenMent role metadata

Decisions from the 2026-08-14 planning session (REFINED_RQS_v0.3.md):
- **New scope.** RQ analysis now targets **exclusively the 12 curated MSR
  corpora** (FRAMEWORK_DESIGN §12); old GitHub/Gmane data is excluded by the
  corpus registry in the new notebook.
- **Renumbering (adopted).** RQ4a→RQ1 (instrument, no corpus), RQ1/2/3→RQ2a/b/c
  (linguistic anatomy, reported per genre), RQ6→RQ3 (genre ecology with a
  **within-genre replication test** as the credibility gate), RQ4b/c/d→RQ4a/b/c
  (multi-actor P4 now measured on gold threads), RQ5→RQ5 (+ per-genre reporting
  and classifier domain-shift framing). P1–P6 unchanged; mapping table in
  REFINED_RQS_v0.3.md §6.
- **OpenMent roles.** `miner/openment_ingester.py` now loads `project_roles.csv`
  and carries each thread author's mentor/mentee role in `metadata["roles"]`
  (additive; never part of NK text). Enables RQ3b role-asymmetry.
- **Deliverables:** `REFINED_RQS_v0.3.md`, `CODING_MANUAL_v0.3.md` (decision
  tree unchanged; adds multi-actor flag §5.5, genre-stratified sampling §7),
  `notebooks/03_rq_analysis.ipynb` (RQ1–RQ5; runs against the live Neo4j —
  RQ1 verified end-to-end; RQ2–RQ5 skip cleanly until the curated graph is
  projected). AGENTS.md §9 layout updated.
- Tests: `tests/test_external_ingesters.py` +3 (project roles load + doc
  metadata propagation); 64 self-contained tests pass.

---

## 2026-08-14 — Drop deprecated apoc.create.addLabels for native dynamic labels

- `projector/graph_projector.py::_apply_artefact_labels` now applies dynamic
  labels via native Cypher `SET <alias>:$($labels)` instead of the deprecated
  APOC `apoc.create.addLabels` (which Neo4j flags with a `01N01` deprecation
  notification). Verified on the live Neo4j 2026.02.2 instance. Removes an APOC
  dependency for label assignment and silences the per-query deprecation warnings.

---

## 2026-08-14 — Fix Phase 0 ParameterMissing in v0.8 artefact labelling

- `projector/graph_projector.py::_apply_artefact_labels` now accepts and forwards
  `**params` to `_run`, so the parameterized MATCH clauses passed by its callers
  resolve instead of raising `Neo.ClientError.Statement.ParameterMissing`.
  All 7 callers pass the identifiers their MATCH needs: `repo`+`number`
  (issue/PR), `sha` (commit), `urn` (email), `record_id` (Jira/Bugzilla/chat/SO).
  Without this, Phase 0 failed to seed external artefact parents, blocking
  Phase 1 TextUnit projection and enrichment.
- `scripts/run_pipeline.py`: set `logging.getLogger("neo4j.notifications")` to
  WARNING to silence Neo4j's informational GQL notifications (e.g. idempotent
  `CREATE INDEX ... IF NOT EXISTS` reporting the index already exists). Not an
  error; just log noise.

---

## 2026-08-14 — SOTorrent Posts Ingester + Systematic Subsampling (SOTorrent & Curated Email)

- Added `miner/sotorrent_ingester.py` — streaming ingester for Stack Overflow
  Posts from the SOTorrent dataset (`Posts.sql.7z`, 14.4 GB compressed -> 67.7 GB
  uncompressed MySQL dump, Baltes et al. MSR 2018).
  - Streams decompression on the fly via `bsdtar -xOf` (or `7z x -so`) and
    terminates subprocess cleanly on `--max` early exit.
  - Incrementally parses multi-row MySQL `INSERT INTO Posts VALUES (...)` statements,
    discovering column order from `CREATE TABLE Posts`.
  - `html_to_text()` strips `<pre>`, `<code>`, `<script>`, `<style>` blocks to
    exclude source code from NK linguistic analysis; unescapes HTML entities.
  - Normalizes to `:Artefact:PostArtefact:StackOverflowQuestion` and
    `:Artefact:PostArtefact:StackOverflowAnswer` nodes.
  - Systematic temporal stratification: default `stride = 7` (`post_id % 7 == 0`)
    samples uniformly across the 12.5-year history (2008–2020) preventing early-beta
    chronological bias, plus `min_score = 1` (`Score >= 1`) quality filter,
    targeting ~5,000,000 records total.
  - Deleted posts (`DeletionDate IS NOT NULL`) and non-Q/A posts (`PostTypeId`
    not in `(1, 2)`) are skipped.
- Updated `miner/curated_email_ingester.py` with proportional entity stratification:
  - 100% of smallest project `ffmpeg` (~365k) + ~44.84% deterministic hash sampling
    across `ozlabs` (~1.86M) and `kernel` (~2.78M) targeting ~5,000,000 records total.
  - Preserves natural proportions between review comments, patch messages, and cover letters.
- Updated `projector/graph_projector.py::_upsert_so_post`:
  - Materializes the pre-declared ontology edge `(a:StackOverflowAnswer)-[:ANSWERS]->(q:StackOverflowQuestion)`
    when `post_type == "answer"` and `question_record_id` is present.
- Updated `FRAMEWORK_DESIGN.md` §12 dataset index and `AGENTS.md` §9 layout tree.
- Unit tests in `tests/test_external_ingesters.py` covering HTML stripping, MySQL dump
  parsing, question/answer linking, stride/score filtering, email sampling, and dry-run with `--max`. All pass.

---

## 2026-08-12 — EDA notebook + IRC timestamp fix

- Added `notebooks/eda_curated_datasets.ipynb` — a small, bounded EDA (≤2,000
  records per corpus, using the same parsers as the ingesters) reporting
  text-length stats, date distribution, and venue distribution per corpus, plus
  a combined per-platform overview. Reads only; writes nothing.
- Fixed `miner/irc_ingester.py`: Ubuntu IRC logs carry only `HH:MM`, so their
  timestamps previously parsed as "today" (bogus 2026 cluster). The date is in
  the filename (`<YYYY-MM-DD>_<hh>.ascii.txt`); the ingester now combines it
  with the HH:MM to produce a real datetime. New-domain logs already carry full
  dates. Verified in the EDA (IRC range now 2004–2019, no 2026).

---

## 2026-08-12 — v0.8: curated MSR corpora as first-class graph data (implementation)

Implemented the plan approved on 2026-08-11/12: all 12 non-OCEAN curated MSR
datasets can now be ingested into the graph as first-class, comparable
platform data. **No real ingestion was performed** — every parser was verified
with `--dry-run --max N` and self-contained tests; the researcher runs the real
ingestion and will come back with errors.

### Ontology (FRAMEWORK_DESIGN §4.7, schema.yml, ontology.cypher §3.14)
- New nodes: `Platform`, `Venue` (named so because **"arena" is reserved by
  RQ6**), `Corpus`, `Conversation`, and the shared `Artefact` label with family
  labels (`IssueArtefact`, `MessageArtefact`, `PostArtefact`, `CommitArtefact`)
  and platform labels (`JiraIssue`, `BugzillaIssue`, `SlackMessage`,
  `DiscordMessage`, `GitterMessage`, `IRCMessage`, `StackOverflowQuestion/
  Answer/Comment`, `OpenMent*`, `NumFocus*`).
- Locked decisions: **comments stay flattened** (`comment_body` TextUnits, pos≥2,
  GitHub-style; first-class comments deferred to all platforms at once); **actors
  share one `Actor.login`** via namespaced logins (`<platform>:<corpus>:<id>`);
  **no `GH_issue:` rename** (existing TextUnit/Signal IDs untouched, backfill via
  `scripts/migrate_v0.8.cypher`); **corpus membership = property + coarse
  `COVERS` edge**, not per-record edges (Alternative Jira ≈11.7M records).
- `ontology.cypher` gained constraints (`platform_id`, `venue_id`, `corpus_id`,
  `conversation_id`, `artefact_record_id`), indexes (`platform_id`,
  `source_corpus`, `artefact_kind`, `venue_id`), MERGE templates §3.14, and
  sanity queries §4.6–4.9.

### Pipeline
- Projector: new `upsert_artefact_from_raw(..., extra=event)` dispatch;
  `_upsert_external_artefact` + family upserts (Jira/Bugzilla/ChatMessage/SO);
  `_ensure_platform_venue_corpus`, `_apply_artefact_labels` (via APOC
  `addLabels`); GitHub/email upserts now also tag `:Artefact` + platform props on
  write. `upsert_text_unit` matches new parent types by `Artefact.record_id`.
- Extractor: `extract_from_jira_issue`, `extract_from_bugzilla_issue`,
  `extract_from_chat_message`, `extract_from_so_post`; `extract_email_for_corpus`
  routes `curatedemail:` to the OCEAN extractor; worker dispatches new item_types
  (`jira_issue`, `bugzilla_issue`, `chat_message`, `so_post`) → `raw_external`.

### Ingesters (miner/*_ingester.py)
`external_common.py` (namespaced IDs, shared doc builders, async-aware
`run_external_ingest` engine with dry-run) plus: slack (438k msgs XML),
discord (DISCO-A, `.xml` only), gitter (GitterCom CSV by position + LiveChat
ascii), irc (Kummerfeld Ubuntu + bundled Gouravajhala new-domains, union-find
conversations + reply edges), stackoverflow (emotion workbook, dedup by text,
emotion labels OUT of scope), openment (GitHub-shaped, roles/gender OUT of
scope), numfocus (only issue/PR titles — **the Actions payload contains no
comment bodies**, verified), bugzilla (group by bug_id; Part_2 skipped as
byte-identical to Part_1), curated email (Patchwork .jl → OCEAN-shaped emails;
`code_diff` excluded as non-NL), jira (Apache gzip+BSON streaming; Alternative
requires `mongorestore` prerequisite then reads a Mongo collection).
- `enrichment/irc_threading.py` + `--enrich` wiring (REPLIES_TO from stored
  `reply_to` refs).

### Verification
- `tests/test_external_extractor.py`, `tests/test_external_ingesters.py`
  (28 tests) pass; `test_word_formation_rules.py`, `test_email_integration.py`
  still pass (56 total). `ruff check` clean on all new files.
- `test_gmane_ingester.py` fails to COLLECT: it imports
  `_group_prefilter_bytes` from `miner.gmane_ingester`, which no longer exists
  (removed in an earlier commit; the test is stale). Pre-existing, unrelated to
  this work — flagged, not fixed.
- `miner/gmane_ingester.py` has an unrelated uncommitted docstring edit in the
  working tree (Usage line); left as-is.

### Data observations worth recording
- NumFocus Actions JSONL carries issue/PR **titles only**; comment/review bodies
  and commit messages are absent from the payloads.
- BugsRepo Part_1 ≡ Part_2 (SHA-256 identical); ingester auto-skips the dup.
- `preethac_SlackDisentangled_dataset` is **Slack** (README: Chaterjee,
  Damevski, Kraft, Pollock), NOT the Gouravajhala 2023 IRC paper the §12 index
  previously claimed. The Gouravajhala new-domain IRC data is bundled inside
  `Kummerfeld_UbuntuIRC_dataset/data/new-domains/` and is ingested by
  `miner/irc_ingester.py`. FRAMEWORK_DESIGN §12 corrected.
- IRC annotation pairs `A B -` are 1-based ordinals within the same `.ascii.txt`;
  direction assumed `A replies-to B` (documented; switch in irc_ingester if the
  real ingestion shows otherwise).

### Files
`settings.py`, `ontology/{schema.yml,ontology.cypher}`, `scripts/{migrate_v0.8.cypher,run_pipeline.py}`,
`projector/{graph_projector.py,worker.py}`, `extractor/{text_unit_extractor.py,worker.py}`,
`miner/external_common.py` + 10 ingesters, `enrichment/irc_threading.py`,
`tests/test_external_{extractor,ingesters}.py`, `pyproject.toml` (+openpyxl),
`FRAMEWORK_DESIGN.md`, `BUILD_SPEC.md`, `AGENTS.md`.

---

## 2026-08-11 — Curated MSR datasets documented (docs only, no ingestion)

Added the curated, peer-reviewed MSR dataset corpus to the canonical docs —
documentation only, nothing was ingested. These are research inputs for the
paper, distinct from the disposable `ocean_dataset/` test corpus.

- **`FRAMEWORK_DESIGN.md` §12 (new addendum)** — third corpus alongside GitHub
  and mailing lists: datasets at
  `/Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets` (external drive;
  currently 13, more may be added), companion PDFs in `dataset_papers/` (repo
  root), plus a 13-row dataset→paper index.
- **`AGENTS.md` §9** — added `dataset_papers/` to the canonical layout tree and
  an external-drive corpora note pointing at the same locations and at
  `FRAMEWORK_DESIGN.md` §12.

Note: the drive folder is `Graph_NK_datasets` (plural) — matches the verified
on-disk name; see CHANGELOG 2026-08-09 for the Gmane/mailing-list corpus context.

### Files
`FRAMEWORK_DESIGN.md`, `AGENTS.md`, `CHANGELOG.md`.

---

## 2026-08-10 — OCEAN dataset ingester + segment-free extractor (test-only, not ingested)

Reopened the decision to drop `ocean_dataset/` (CHANGELOG 2026-07-29): the data is
now being **tested** before a final keep/drop call. Built the ingestion path so a
small run can be exercised, but **nothing was ingested** — the build agent ran only
the pure-Python test suite and `--help` (per the task brief).

Key format discovery (verified in `email_eda.ipynb`): OCEAN JSONL is **flat, one
object per line**, with **no** `segments`, `headers`, `lang`, or `group` — unlike
Webis Gmane. So instead of synthesising segment spans for `extract_from_email`,
we added a segment-free extractor mirroring `extract_from_issue`.

- **New `miner/ocean_ingester.py`** — OCEAN counterpart of `miner/gmane_ingester.py`.
  Parses plain JSONL (`iter_ocean_records`), renormalises the flat record into the
  gmane-shaped email doc the projector expects (`to_email_doc`): derived
  `urn = "ocean:<mailing_list>:<message_id>"` (namespaced, collision-safe),
  minimal `headers` (from/to/cc/subject/date/message_id/in_reply_to/references),
  `group` = mailing_list, `lang = "en"` (OCEAN lists are English — documented
  assumption). Persists to Mongo `raw_emails` (upsert on urn, idempotent) then
  publishes a `stream_raw` pointer with `repo_name = "ocean:<list>"`. CLI:
  `python -m miner.ocean_ingester --files ... --lists ... --max N`.
- **New `extract_from_ocean_email`** (`extractor/text_unit_extractor.py`) —
  message-grained, no segments: subject → role `subject`/position 0, whole
  stripped body → role `body`/position 1. Reuses the email parent convention
  (`parent_id = "email:<urn>"`, `parent_type = "email"`) so the projector's
  EmailMessage wiring and the analysis email unit family work unchanged.
- **`extract_email_for_corpus`** (`extractor/text_unit_extractor.py`) — pure
  corpus dispatch (ocean vs gmane) on the `repo_name` namespace; the extractor
  worker (`extractor/worker.py`) delegates to it. Placed in the extractor module
  (not the worker) so it stays importable/testable without services.
- **New `tests/test_ocean_ingester.py`** — 18 pure-Python tests on synthetic
  tmp_path JSONL (never touches the real 3.6 GB files): parser, urn derivation,
  headers mapping, doc wrapping, scope filter, extractor integration, and corpus
  dispatch. Verified: `46 passed` (word-formation + email-integration + ocean),
  `ruff check` and `ruff format` clean on all four touched files.
- Small hygiene fixes in touched files: `from typing import Any` in
  `text_unit_extractor.py` (pre-existing F821), unused `asyncio` import + import
  sort in `worker.py`.

### Files
`miner/ocean_ingester.py` (new), `tests/test_ocean_ingester.py` (new),
`extractor/text_unit_extractor.py`, `extractor/worker.py`, `CHANGELOG.md`.

---

## 2026-08-09 — AGENTS.md restructured + smoke script + layout de-dup

Maintenance pass on the agent-facing contract. Restructured `AGENTS.md` end-to-end
so agents waste less time per session: a start-of-session ritual (read newest
CHANGELOG entry, then the open-debt table), a spin-up/common-commands section,
a rewritten verification section that points at the *actually runnable* checks
(debt 7/8/9 called out explicitly), the `blind spot`/`signal_id`/`present_nk`
do-not-revert cautions inlined, and the layout tree moved to be the **only**
canonical copy (`FRAMEWORK_DESIGN.md §7` and `BUILD_SPEC.md §3` now point to
`AGENTS.md §9` instead of carrying duplicate trees that had drifted once).

**New hard rule 5.9:** any design decision, pilot observation, or accepted
divergence gets a dated CHANGELOG entry before a session ends — the root-cause
fix for the drift that prompted this project's doc-reconciliation work.

**New `scripts/smoke_annotate.py`:** run one rule annotator (or all four) on a
string with no services, the fast loop for lexicon/pattern iteration. Verified
on `--help` + compile; cannot execute here (no spaCy in this sandbox) — run
against the real env per `AGENTS.md §6`.

Section renumbering (old → new): §2 frozen note → §3; §3 hard rules → §5;
§4 verify → §6; §5 proceed/ask + §8 escalation → merged §7; §7 done → §8;
§6 layout → §9. All cross-references in `annotators/*.py`, `projector/*.py`,
`tests/test_annotators.py`, and `CHANGELOG.md` updated to match.

### Files
`AGENTS.md` (restructured), `scripts/smoke_annotate.py` (new),
`FRAMEWORK_DESIGN.md` (§7 → pointer + module→file table), `BUILD_SPEC.md`
 (§3 → pointer + milestone markers; §9 trimmed; debt 11 citation fixed),
`annotators/base.py`, `annotators/lexical.py`, `annotators/rhetorical.py`,
`projector/graph_projector.py`, `tests/test_annotators.py`,
`CHANGELOG.md` (section-ref fixes in earlier entries).

---

## 2026-08-09 — RQ restructure to v0.2 + RQ4 instrument stack + validation underway

The most substantive research update since the framework was designed. The
pre-registered RQ4 instrument is delivered and validation is in progress.

### Research questions restructured (RQ1–RQ6 v0.2)
`REFINED_RQS_v0.2.md` supersedes the v0.1 formulation. `02_rq_analysis.ipynb`
is redesigned around it (67 cells; old 44-cell version archived as
`02_rq_analysis_old.ipynb`).

- **Four layers of claim** instead of three. Layer 0 — instrument-level
  (RQ4a), established from sources, needs **no corpus**. Layers 1–3:
  descriptive (RQ1–RQ3), comparative (RQ6), critical (RQ4b–d, RQ5).
- **RQ4 split into four sub-questions**: RQ4a (can the borrowed taxonomies
  discriminate *on their own terms* — literature-only), RQ4b (coverage under
  the multi-fit pass, zero-cells reported with confidence + access level),
  RQ4c (do the predicted collapses manifest in coder behaviour — needs a
  second annotator), RQ4d (the residual, and the multi-actor/P4 hypothesis,
  defined from the coded sample, not cluster membership).
- **RQ1/RQ3 corrected to token-normalised rates** (per 1k tokens, using
  `TextUnit.token_count`) — per-unit rates were mechanically confounded with
  the GitHub-vs-mailing-list unit-length gap. RQ3's `opacity` double-count
  (rhetorical vs lexical) is disclosed.
- **RQ5 binding constraint made explicit**: the classifier is never used as a
  marker-weight target; marker weight is hand-labelled per-rule precision,
  banded (≈50 units/rule cannot support two decimals).
- **RQ6 narrowed to a descriptive arena claim** — the corpus does not yet
  implement the crossed project×channel design (cpython GitHub vs
  `gmane.comp.python.general`, a *users* list). Added the clean
  `gmane.comp.gis.qgis.devel` vs `.user` audience contrast, reportable now.
- **RQ4 cohort query bug fixed**: a `WHERE v.label = 1` placed *after*
  `OPTIONAL MATCH` degraded the join to an inner join, silently dropping the
  63k marker−/classifier+ units. Defence-in-depth: an RQ4/RQ5 shared
  NK-signal predicate is now defined **once** so both partition the same
  population.

### The RQ4 instrument stack (pre-registered, delivered before corpus contact)
- `ontology/ignorance_codebook_v0.1.yml` (1172 lines) — 28 categories + 3
  Wehling dimensions, each with source locator, `definition_confidence`,
  inclusion/exclusion criteria and discriminating questions. Constructed only
  from primary sources + secondary reception (`built_from` provenance);
  **non-fit codes (RESIDUAL / NOT_NK / UNCODABLE) intentionally live in
  `CODING_MANUAL.md`, not the codebook** — they are not imported taxonomy.
- `TAXONOMY_CROSSWALK.md` — 24 documented relations; **8 of 17
  cross-taxonomy pairs are `NONE_POSSIBLE`** (the sources supply no
  distinguishing test). `roberts.errors` vs `smithson.error` is a
  same-label-different-referent collision **inside the borrowed literature**.
- `SOURCES_AUDIT.md` — evidence asymmetry quantified: Roberts + Wehling at
  full primary text, Smithson partial, **Gross secondary-paraphrase only**.
  Every `definition_confidence` rating is traceable to its real basis.
- `CODING_MANUAL.md` — fixed, pre-registered taxonomy priority (Roberts →
  Wehling → Smithson → Gross), the Step-0–5 decision tree, disambiguation
  notes, and predictions **P1–P6 recorded before any SE unit was examined**.

Consequence encoded in the central claim: the imported taxonomies are (i)
mutually non-discriminating by construction, (ii) unevenly evidenced in their
own primary literature, and (iii) missing a category for the multi-actor,
asynchronously-negotiated non-knowledge that is the structural default of SE
communication platforms.

### Validation in progress (part of the ongoing RQ4/RQ5 work)
- **RQ4a is complete** (data-free): `rq4a_instrument_discriminability.csv`,
  `rq4a_category_confidence.csv`.
- **RQ4b–d coded-sample pipeline live**: `rq4_coding_coderA.csv` (739 rows),
  `rq4_coding_coderB.csv` (200), `rq4_sample_key.csv` (analyst-only),
  `rq4_marker_communities.csv`. Sampling frame: |marker+ ∪ clf+| = 981,817.
- **⚠️ Only one coder present** — RQ4c inter-rater agreement CANNOT be
  computed as specified while that holds. Documented solo fallback
  (intra-coder test–retest on a re-coded subsample) is the instrument's
  highest-priority open dependency (`REFINED_RQS_v0.2.md` RQ4c).
- RQ4d tracks the catch-all codes (`gross.ignorance`, `smithson.error`,
  `smithson.irrelevance`) so the residual rate can be reported with
  catch-all absorption reversed.
- Coding manual v0.2 instrument changes (multi-fit pass mandatory, Wehling
  dimensions scored on all codable units, `residual_but_for` flag,
  parent-chain context for the P4 subsample) are recorded and must land in
  `CODING_MANUAL.md` **before** any unit is coded.
- `APPLY_PROMOTIONS = False` still gates RQ5 per-rule promotion; the
  notebook computes evidence, it does not act on it (MARKER_REVIEW §3.5
  calibration remains deferred).

### Also in this window
- `miner/async_miner.py` (a "frozen" file per AGENTS.md §3): default of
  `mine_repositories(include_commits=...)` flipped `True → False`. Decision
  from pilot observation (2026-07): commits are information-sparse relative
  to the text they carry. **Documented here and in AGENTS.md as an accepted
  divergence; the file remains frozen otherwise.** `scripts/mine_one.py`
  usage updated to match (`--no-commits` default).
- `scripts/mine_one.py` — `--max-items` is **parsed but not wired through**
  to the miner (open defect, see BUILD_SPEC.md "Open technical debt" 9).

### Files
`notebooks/02_rq_analysis.ipynb` (rewritten), `notebooks/02_rq_analysis_old.ipynb`
(archived), `ontology/ignorance_codebook_v0.1.yml`, `CODING_MANUAL.md`,
`TAXONOMY_CROSSWALK.md`, `SOURCES_AUDIT.md`, `REFINED_RQS_v0.2.md`,
`notebooks/rq4_*.csv`, `notebooks/rq5_*.csv` (updated), `miner/async_miner.py`
(frozen-file default), `scripts/mine_one.py`.

---

## 2026-07-29 — OCEAN dataset (test corpus) + lexical matcher build speed-up

- `ocean_dataset/` (angular/golang/nodejs/python, ~3.6 GB `.jsonl`,
  git-ignored) was ingested as a **test corpus**. It is not part of the
  research design and is a candidate for **deletion**; do not build on it.
- `annotators/lexical.py` — PhraseMatcher patterns are now built via
  `nlp.pipe` with the parser and NER disabled, which removes a hidden
  dependency on the parser for match construction (CHANGELOG v0.2 correctly
  warned the parser was re-enabled for scope rules; lexical matching itself
  needs none of it). Materially faster annotator startup for large lexicons.
- `settings.py` — `spacy_model` default moved from `en_core_web_lg` to
  `en_core_web_md` (shape/vector compromise; neither `lg` nor `md` matters
  much to the token-based + dependency rules, and `sm` had no vectors).

### Files
`annotators/lexical.py`, `settings.py`, `ocean_dataset/` (git-ignored).

---

## 2026-07-28 — Mailing List EDA (pre-ingest selection)

- **New `scripts/eda_gmane_corpus.py`** — read-only, pre-ingest census
  (`inventory`) and deep-profile (`profile`) over the Webis Gmane corpus, to
  pick `--groups` before running `miner.gmane_ingester`. It reuses the
  ingester's own `iter_bulk_records`/`record_in_scope` and the extractor's
  `_resolve_email_offset_convention`/`_resolve_final_span`/`strip_text`, so
  "estimated TextUnits" is what `extract_from_email` will actually produce
  (no replicated-logic drift — the v0.6.3 lesson). Byte-based ETA progress
  on stderr, sampling-order biases flagged, thread-resolution rate reported
  as a lower bound under sampling.
- **Committed EDA outputs**: `eda_group_census_01.csv`, `eda_group_census_02.csv`,
  `eda_profile_*_<group>.json` (python.devel, python.linux.general, etc.).
- **`miner/gmane_ingester.py`** — `iter_bulk_records` gains an optional
  `progress_cb` (compressed-bytes-consumed progress for ETA); bulk-write and
  pipelined-XADD paths reworked (`gmane_batch_size`, `gmane_redis_batch_size`,
  `gmane_num_workers` tuning knobs in `settings.py`).
- **New `email_eda.ipynb`** — exploration notebook alongside the script.

### Files
`scripts/eda_gmane_corpus.py` (new), `email_eda.ipynb` (new),
`miner/gmane_ingester.py`, `settings.py`, `eda_group_census_*.csv`,
`eda_profile_*.json`.

---

## 2026-07-16 — v0.7.2: Sandbox guard made conditional (fixes 01N52 warning noise)

**Shipped-artefact bug:** the v0.7.1 zip contained a notebook that hardcoded
`WHERE coalesce(u.sandbox, false) = false` in 18 queries. On a database that
never received the Cypher-course seed, Neo4j 5.x emits
`01N52 property key does not exist` for every one of them. Results were
never wrong (`coalesce(null, false) = false` → true, so all rows pass), but
the warnings are noise — and worse, they train the reader to ignore an
`UNRECOGNIZED`-class notification that also reports genuine property-name
typos (`u.parnet_type` would warn identically and silently return null).

**Why the guard exists at all:** `learn/00_seed_sandbox.cypher` tags every node
it creates with `sandbox: true`, TextUnits included, and its toy issues contain
real NK phrasing ("I'm not sure why this crashes…"). Installed via the seed's
option B (into an existing instance), those nodes would silently pollute every
count in the notebook. Installed via option A (a separate throwaway instance on
port 7688, which the seed itself recommends), they never touch the research
graph — and then the property key doesn't exist, which is what triggers the
warning.

**Fix:** the guard is now resolved once at notebook startup instead of being
hardcoded. `CALL db.propertyKeys()` is checked for `sandbox`; queries write
`@sandbox(u)`, and `q()` expands it to the real predicate when the key exists
or to `true` (a constant the planner folds away) when it doesn't. This is
exactly the warning's own condition — the planner raises 01N52 by consulting
the same token store — so omitting the predicate is provably safe: key absent
⟺ warning fires ⟺ no node can carry the property ⟺ the predicate is a no-op.
The converse is deliberately conservative: property keys are not removed from
the token store when nodes are deleted, so a torn-down sandbox leaves the key
behind and keeps the guard on — harmless, never wrong.

**Deliberately NOT done:** silencing this via the driver's
`notifications_disabled_classifications=["UNRECOGNIZED"]`. One line, but it
would also suppress genuine property-typo warnings for the whole session.
Fixing the cause beats muting the symptom.

**Verified:** all 19 sandbox-guarded queries render structurally valid Cypher
under both branches (no dangling `WHERE`/`AND`, no unexpanded tokens, no
property reference leaking through when disabled); every `@sandbox(var)`
refers to a variable actually bound in its own query; generator compiles
without escape-sequence warnings; notebook nbformat-validated (44 cells).

### Files
`notebooks/02_rq_analysis.ipynb`.

---



New `notebooks/02_rq_analysis.ipynb` (44 cells) implementing the refined
research questions from REFINED_RQS_v0.2.md (added to repo root; supersedes
the v0.1 draft). One section per RQ, each headed by the question +
operationalisation from the refinement doc, so the notebook is
self-documenting. Highlights of the operationalisation choices, and what was
verified:

> Note: this entry describes the 44-cell v0.1 notebook. The 2026-08-09 entry
> above describes the v0.2 restructure (67 cells; old notebook archived as
> `02_rq_analysis_old.ipynb`).

### Design decisions (the ones worth knowing about)
- **Rule metadata is loaded from the same YAML files the annotators load**
  (scoped rule ids for RQ2, non-NK booster subcategories, SE-native
  subcategory lists) — single source of truth, resolved via
  `settings.pattern_set_version`, so the notebook follows pattern-set changes
  automatically instead of hardcoding rule lists that would drift.
- **Non-NK contrastive signals (boosters M-6, `-free` privative) are excluded
  from every NK-positive definition** — extracted from the YAML by
  `polarity == "certainty"`, not hardcoded. They exist for RQ5 stance
  contrast only; counting them as NK would corrupt every rate.
- **Headline numbers use `status='active'` only**; candidates are shown in
  separate tables (RQ1) or both-ways (RQ3, where most SE-native metaphors
  ship as candidates — the honest comparison shows the ratio both ways).
- **RQ2's cue-vs-scope gap** is a 2×2 on classifier-positive units:
  scoped-only / cue-only / both / neither, with "scoped" = the 5
  DependencyMatcher rule ids. The scoped-only share is the direct quantified
  answer to "unknown false negatives from keyword lists."
- **RQ4 keeps the taxonomy mapping manual by design**: the notebook clusters
  (KMeans over log1p unit×category vectors, k by silhouette), exports
  exemplars to CSV for qualitative audit, and provides a `TAXONOMY_MAP` dict
  to fill in; coverage table + residual set are computed from that. Post-hoc
  labels are a human judgement per the framework's own design — automating
  them would fake the paper's core evidence.
- **RQ5 produces the labelling workflow end-to-end**: 2×2 contingency, three
  hand-labelling CSV exports (both disagreement cells + stratified ≈50/rule
  precision sample), re-import cells computing the per-rule reliability table
  against τ=0.7 and a marker-recall estimate. **Writing promotions back to
  the graph is gated behind `APPLY_PROMOTIONS = False`** — calibration
  remains deferred (MARKER_REVIEW §3.5); the notebook computes evidence, it
  does not act on it.
- **RQ6** tests the two register predictions stated in REFINED_RQS_v0.2.md
  (hedging/
  rhetorical ↑ mailing lists; repro_gap/spec_gap ↑ issues), reports χ² with
  Cramér's V (effect size, since large n makes everything "significant"),
  clusters community NK signatures (dendrogram, gated on ≥4 sources), and
  adds a thread-position analysis (openers vs replies via REPLIES_TO).
- Every query excludes sandbox nodes; §0 sanity-asserts the RQ6 quotation-
  exclusion control (zero `role='quotation'` units) and warns loudly on
  silent annotator layers or mixed rule_versions in the graph.

### Verified (without a live Neo4j — what could and couldn't be checked)
- All graph shapes used by the queries checked against the projector's actual
  write paths (TextUnit.parent_type/role/text on-node; CLASSIFIED_AS →
  ClassifierVerdict.label; Repository.full_name / MailingList.name both via
  CONTAINS): all match.
- Parameter hygiene (every `$param` passed), no deprecated `exists()`, all 35
  code cells parse, nbformat-validated.
- All 8 pandas/sklearn/scipy analysis paths smoke-tested on synthetic data
  shaped like real query results (incl. absent-contingency-cell handling,
  zero-division guards, full clustering path, recall arithmetic).
- **One real Cypher bug caught by review before shipping**: in the RQ5.2
  sample queries, `rand()` placed alongside `collect()` in a single `WITH`
  becomes part of the grouping key (evaluated per row), silently breaking the
  aggregation and duplicating units in the sample. Fixed by attaching
  `rand()` in a second `WITH` after the aggregation; the rest of the notebook
  swept for the same bug class (clean — remaining `rand()` uses have no
  aggregation and are intentionally per-row).
- **Not verified**: actual execution against a populated Neo4j (none in this
  environment). Run top-to-bottom on the pilot corpus; §0's sanity cells are
  designed to fail loudly first if anything is off.

### Files
`notebooks/02_rq_analysis.ipynb` (new), `REFINED_RQS_v0.2.md` (new, repo root),
`CHANGELOG.md`, `AGENTS.md` (tree).

---



Integrates a literature-grounded review of all four pattern/lexicon files
(MARKER_REVIEW.md, added to repo root). Central thesis: v0.1 detected NK
**cues** (keywords) but not their **scope** (the grammatical relation that
makes a cue actually mean NK) — the classic cue/scope distinction from
BioScope (Vincze et al. 2008) and the CoNLL-2010 shared task. This release
adds scope-aware matching (spaCy DependencyMatcher) alongside ~10 new marker
classes (M-1–M-7) and 10 corrections to existing rules (C-1–C-10). Full
rationale for every change is in MARKER_REVIEW.md; this entry covers what was
implemented, verified, and what still needs the user's own verification.

### Interpreting "optional context block" (flagged explicitly, not assumed silently)
The task description's "context block... used to change between different
versions of the patterns and lexica" was reconciled against MARKER_REVIEW.md
§4 and the actual v0.2 files: there is no literal `context:` YAML key
anywhere in any of the four files. The mechanism is `type: "DependencyMatcher"`
(scope) vs. absent/`type: "Matcher"` (bare cue, v0.1 behaviour) — a rule can
be "v0.1-style" or "v0.2-style" within the same file, which is the
"different versions" the task description was paraphrasing. Implemented on
that reading.

### ⚠️ Architectural cost, not hidden: the parser is re-enabled
v0.2's scope rules need `token.dep_`/`token.head`, which only the dependency
parser populates. `annotators.base.make_nlp` now loads with
`disable=["ner"]` only — parser is ON. This directly reverses v0.5's
documented "biggest per-document speed-up" (disabling the parser). There is
no way around this: DependencyMatcher cannot function without it. Expect
annotation throughput to drop from the v0.5 numbers; re-benchmark after this
upgrade the same way Phase 1/2 were benchmarked after the schema fix.
`settings.pattern_set_version = "0.1"` still selects the old files (kept on
disk, unmodified) if a pre-review comparison run is wanted, but does not
auto-revert the parser — do that explicitly via `make_nlp(disable=[...])` if
speed matters more than scope for a given run.

### New: `Signal.weight` / `Signal.status` (first-class, not payload-stuffed)
Every annotator now reads a rule's `weight` (float, analysis-time confidence
hint, never filtered at ingest — signal pluralism holds) and `status`
("active"|"candidate") and writes them to the Signal node
(`sig.weight`/`sig.status`, `ON MATCH SET` so a later re-run after empirical
calibration — MARKER_REVIEW §3.5, explicitly DEFERRED per the task — refreshes
existing nodes). New index `signal_status`. **A real chain-of-custody bug was
caught and fixed while wiring this up**: `annotators/worker.py`'s
`_publish_signal` manually lists which Signal fields to put on the Redis
event — weight/status were initially dropped there even though the Signal
dataclass carried them, since that function isn't `dataclasses.asdict()`.
Fixed and verified with an explicit end-to-end trace test.

### `morpho_syntactic.py` — DependencyMatcher routing (the core mechanism)
`SpacyMorphoAnnotator` now builds TWO matchers: a `Matcher` for rules with no
`type` (or `type: "Matcher"`, v0.1 behaviour unchanged) and a
`DependencyMatcher` for `type: "DependencyMatcher"` rules. The YAML pattern
shape (`RIGHT_ID`/`RIGHT_ATTRS`/`LEFT_ID`/`REL_OP`) is spaCy's own
DependencyMatcher format verbatim — no translation layer. A malformed
pattern is logged and skipped per-rule, not fatal to annotator startup.
Span for a DependencyMatcher match is the bounding range over every matched
node (captures the whole scoped construction, e.g. subject+negation+verb).
5 new families this enables: `epistemic_verb/not_knowing` (M-1 — "I don't
know" with zero keywords), `hedging/plausibility_shield` (M-2 — "I think/
believe/guess..."), `negation/scoped_epistemic` (C-3 — negation only counts
attached to an epistemic head), `tense/past_nk` (C-4 — fixes the v0.1
double-'yet' bug via dependency scope instead of a broken token pattern).
**Structurally verified** (all 5 DependencyMatcher patterns in the shipped
YAML have well-formed RIGHT_ID/LEFT_ID reference chains — checked
programmatically, zero dangling references) but **NOT empirically verified
against real spaCy parses** (unavailable in the dev sandbox) — run
`pytest tests/test_annotators.py` and add golden examples for the new
DependencyMatcher rules before trusting them in a production run.

### `lexical.py` — POS-aware matching (MARKER_REVIEW §3 point 2)
`PhraseMatcher(attr="LEMMA")` matches lemma text only — it could not tell
"doubt" the noun from "doubt" the verb, so `lex.doubt_n` and `lex.doubt_v`
both fired on every occurrence regardless of actual use. Every match is now
post-filtered against the entry's declared `pos` (checked on `span.root.
pos_`); skipped for `PHRASE`/`X` entries where a single POS label doesn't
apply. `requires_context` (new field, e.g. on "guess"/"suppose") is advisory
only here, per the lexicon file's own header — enforced by the morpho_syntactic
DependencyMatcher rule that scopes the same cue instead; the two layers
firing in parallel is intentional (mirrors the existing 'blind spot'
double-count, AGENTS.md §5.3), not a bug to fix.

### `word_formation.py` — C-8 and C-2, with a bug caught mid-implementation
- **C-8** (under- blocklist): blocklist matching is now length-aware. A
  blocklist entry LONGER than the prefix (e.g. "under" vs. the "un" prefix)
  is matched via `startswith` — correctly excluding "underspecified" etc.
  from the "un" rule so the new dedicated `affix.prefix.under` rule catches
  them once, not twice. **A first implementation used blanket `startswith`
  for every blocklist entry regardless of length, and a stress test caught
  a real, serious bug before it shipped**: the "in" prefix's own blocklist
  contains "in" itself (same length as the prefix) — every in- candidate
  starts with "in" by definition, so blanket startswith would have silently
  blocked the ENTIRE in- rule, correctly working only by coincidence for the
  handful of words that happen to be separately allowlisted. Fixed via
  `_blocked_by_prefix`: startswith only for entries strictly longer than the
  prefix, exact equality otherwise. Both cases now covered by permanent
  regression tests (`tests/test_word_formation_rules.py`).
- **C-2** (-able suffix): new `mode: "allowlist_only"` skips the blanket
  suffix scan entirely — only explicit allowlist entries
  (questionable/unknowable/...) match, so reproducible/testable/configurable
  (capability, not NK) are excluded without a giant blocklist.
- **NEW**: allowlist-overrides-blocklist for prefixes (and suffixes, for
  consistency) — an allowlisted word always matches regardless of blocklist.
  `polarity` now flows into the payload (used by the new "-free" suffix, a
  deliberate NON-NK contrastive control for RQ5).
- Removed the unused top-level `import spacy` — this file only operates on
  pre-parsed tokens and never calls spaCy directly, so its core logic is now
  testable without spaCy installed at all (see the new pure-Python test file).

### `rhetorical.py` — weight/status pass-through only
No DependencyMatcher usage in this layer (v0.2 rhetorical patterns are all
still plain token `Matcher` patterns). C-5 (rhetor.comparison.kind_of
removed — redundant with morpho hedging, unlike the intentional 'blind spot'
double-count) required no code change, only the data file; verified present.

### `settings.py`
New `pattern_set_version` (default `"0.2"`) — each annotator resolves its
file as `<name>_v<version>.yml`. Both v0.1 and v0.2 files are kept on disk
unmodified, so setting this to `"0.1"` reproduces the pre-review baseline for
comparison (a real, usable ablation lever, not just provenance-preservation).

### `rules/categories.yml` — regenerated, not hand-edited
Rewritten by walking the four actual v0.2 files programmatically and
extracting every (rule_prefix, layer, category, subcategory) combination in
use, rather than manually transcribed — verified to have zero coverage gaps
against the real files (checked with a completeness script). This file is
documentation only; nothing in the codebase currently loads or enforces it
at runtime (verified — the header comment's claim to the contrary predates
this check and was already stale).

### Tests
- `tests/test_word_formation_rules.py` (NEW, 11 tests, spaCy-free, all
  passing): both bugs caught during development as permanent regressions,
  the C-2/C-8 corrections, allowlist-override contract, and structural
  integrity checks on the shipped YAML (duplicate-id detection,
  DependencyMatcher reference-chain validation, C-5 dedup).
- `tests/test_annotators.py`: 2 provably-stale assertions fixed by direct
  inspection of the v0.2 pattern text (seem/appear moved modality→evidential
  per C-6; rhetor.comparison.kind_of removed per C-5, replaced with the
  something_like figure the same test sentence actually fires under v0.2).
  Added an explicit staleness disclaimer — the remaining assertions were
  checked by manual tracing, NOT by running real spaCy (unavailable here);
  this file needs a supervised local run before being trusted, and has zero
  coverage yet for the new DependencyMatcher rules specifically.

### Deferred (explicitly, per task instructions)
MARKER_REVIEW §3 point 5 (empirical calibration: hand-label a stratified
sample, compute per-rule precision, promote/demote active↔candidate) is
NOT implemented. The `weight`/`status` schema is in place and ready for it,
but no filtering or promotion logic exists yet — `status` is currently just
a label carried through to the graph.

### Recommended next steps
1. `pip install -e .` and `python -m spacy download en_core_web_sm` locally,
   then `pytest tests/ -v` — confirm `test_annotators.py` passes and extend
   it with golden examples for the 5 new DependencyMatcher rules.
2. Re-benchmark annotation throughput now that the parser is back on;
   compare against the v0.5 numbers to quantify the real cost.
3. Consider a small ablation run: `pattern_set_version=0.1` vs `0.2` on the
   same corpus slice, compare signal counts per layer — this is now a
   one-line settings change, not a code change.

---



Re-running `scripts/diagnose_email_spans.py` after v0.6.2 showed **identical**
numbers to before the trailing-overshoot clamp was added. Root cause: the
clamp was written inline inside `extract_from_email`'s loop, but the
diagnostic script computed segment validity independently via its own
`_convert_span` + raw bounds check — it never called the clamp logic at all.
Two code paths meant to agree had silently diverged.

### Fix
Extracted the clamp into one shared function, `_resolve_final_span(text,
raw_begin, raw_end, convention)`, which does conversion + the
`TRAILING_OVERSHOOT_TOLERANCE=2` clamp + the final bounds check in one place.
`extract_from_email` and `scripts/diagnose_email_spans.py` now both call this
exact function — they cannot drift out of sync again, because there is only
one implementation of "is this segment valid" left to call.

### Verified against the user's real report
Reconstructed the exact 8 failing examples from the v0.6.2 diagnostic report
(tabular/raw_code segments, each overshooting by exactly 1 character) and
confirmed: under the OLD path (`_convert_span` + raw check) all 8 are
invalid, matching what was reported; under the NEW shared path
(`_resolve_final_span`) all 8/8 are now recovered, matching the fix's intent.

### Files
`extractor/text_unit_extractor.py` (`_resolve_final_span`,
`TRAILING_OVERSHOOT_TOLERANCE`; `extract_from_email`'s loop simplified to call
it), `scripts/diagnose_email_spans.py` (both call sites switched to the
shared function). Tests unchanged and still 17/17 passing (behavior for
`extract_from_email` is identical — only the diagnostic's reporting changes).

### Next step
Re-run `python scripts/diagnose_email_spans.py --sample 10000` — kept-label
validity should now be measurably higher than 95.6%, and the "fails both
conventions" example list should no longer show the tabular/raw_code 1-char
cases (those are now recovered, not failing).

---



Ran `scripts/diagnose_email_spans.py --sample 10000` against real ingested
Gmane data. Results and the fix they justified:

### Findings
- **Kept-label validity (paragraph + section_heading): 95.6%** (20,404/21,338)
  — the number that actually determines research coverage, and it's good.
  The document-level "83.9% partial" figure from the raw diagnostic output
  was misleading exactly as expected: with ~9 segments/email, one bad
  segment (often in a discarded label) marks a whole document "partial" even
  when the content actually used is intact.
- Mathematical proof (verified, not assumed): UTF-8 byte-length is never
  shorter than char-length for any string, so `count_bytes >= count_char`
  for every document. Consequence: a document that best-fits "char" but is
  "partial" has segments failing **both** interpretations — i.e. NOT an
  encoding-convention issue, contrary to what the v0.6.1 diagnostic's
  wording implied.
- The lowest-validity labels — `mua_signature` (50.2%), `personal_signature`
  (74.9%), `closing` (79.0%) — are exactly the labels most likely to be the
  LAST segment in an email. Combined with 8/8 sampled "fails-both"
  examples showing an **exact, uniform 1-character overshoot**
  (`end == len(text_plain) + 1`, confirmed arithmetically), this points at
  one specific, narrow mechanism: a trailing newline present when
  segmentation ran but stripped from the exported `text_plain` afterward.
  Not encoding confusion, not large-scale truncation, not random
  segmentation-model noise.

### Fix
`extract_from_email`: a segment whose converted span overshoots
`len(text_plain)` by 1–2 characters is now clamped to the true length and
kept, instead of being dropped entirely for one missing trailing character.
Deliberately narrow (`_TRAILING_OVERSHOOT_TOLERANCE = 2`) so it cannot mask
genuine truncation — a large overshoot is still rejected and logged exactly
as before (see `test_large_overshoot_is_still_dropped_not_masked`).

### Diagnostic script (`scripts/diagnose_email_spans.py`) extended
Now reports segment-level validity (not just document-level), validity
restricted to `email_segment_labels` (the only labels ever kept — corruption
in discarded labels is irrelevant), a full per-label breakdown, and
position-percentage samples of segments failing both conventions (clustering
near 100% is the truncation/off-by-one signature this release found).

### Tests
`tests/test_email_integration.py`: 2 new tests — the confirmed 1-char
overshoot is recovered; a 50-char overshoot is still dropped, not masked.
17/17 passing.

### Files
`extractor/text_unit_extractor.py` (clamp in `extract_from_email`),
`scripts/diagnose_email_spans.py` (segment/label-level reporting),
`tests/test_email_integration.py`.

---



Two unrelated incidents on first contact with real ingested data (not synthetic
test fixtures). Both are documented here in full because the debugging process
itself surfaced a real design flaw worth remembering.

### Incident 1 — "Document not found" across every collection (Mongo/Redis desync)
**Not a code bug.** Diagnosed by decoding the ObjectId timestamps embedded in
the failing `mongo_id`s: they were ~21–22 hours older than the read attempt,
across every collection (issues, PRs, commits, AND emails) and both `stream_raw`
consumers (extractor, projector Phase 0) simultaneously. Root cause: the
person restarted docker-compose (a testing reset), which cleared MongoDB, while
`stream_raw` — deliberately left untrimmed since the 2026-06-02 Redis-OOM fix,
specifically because it has two consumers — kept its stale pointers into the
now-empty Mongo. Save-before-publish contracts in both the GitHub miner and
the Gmane ingester were re-verified intact; no code path deletes or expires
documents. Resolution: re-mine/re-ingest so Mongo and the stream_raw backlog
are consistent again. No code change — an operational/data-consistency
incident, not a defect.

### Incident 2 — Email segment spans out of bounds (real Gmane data)
Webis documents Gmane segments as "character spans," but real corpus records
produced `segment span out of bounds` on `extract_from_email`, including spans
that were small AND early (ruling out simple cumulative drift over a long
document as the sole explanation).

**Design process (kept here because it matters):** the first fix attempted
per-segment fallback (try char offsets, then UTF-8 byte offsets, then UTF-16
code-unit offsets — the last covers JVM/JS segmentation runtimes where a
codepoint outside the BMP is 2 "chars"). A test written to validate this
caught a real flaw: on a long document, a byte-offset span with small drift
can coincidentally still satisfy the naive char bounds check, so the
per-segment resolver would silently return the WRONG substring with no error
at all — worse than the visible bug it was meant to fix.

**Fix:** offset convention is a property of the whole document (one
segmentation pass produced it), not of an individual segment, so
`_resolve_email_offset_convention` determines the best-fit convention by
**majority vote across all of a document's segments** and applies it
uniformly. An isolated segment that still fails under the document's winning
convention is treated as a data-quality outlier and skipped individually — it
does not override the vote. This was itself refined once more after a second
test failure (an all-or-nothing "every segment must agree" version incorrectly
let one corrupt segment take down an otherwise-valid document).

**Known limitation, stated plainly:** detection is bounds-based, so it can
only distinguish conventions when cumulative drift exceeds a segment's
document length by the point some segment is checked. This is guaranteed true
for every email currently producing a visible "out of bounds" warning (that
visibility IS the proof drift was large enough) — so the fix is verified
correct exactly where it's needed. It is NOT guaranteed for a hypothetical
email where drift exists but stays small relative to a long document — such a
case would produce no warning and could theoretically still misalign
slightly, both before and after this fix (a pre-existing, bounds-checking-
inherent blind spot, not something this change introduces or worsens).

### New
- `scripts/diagnose_email_spans.py` — run against already-ingested `raw_emails`
  to get a real, quantified answer (not a guess) for which convention your
  corpus actually needs, and how many documents have a "clean" vs. "partial"
  majority fit. Usage: `python scripts/diagnose_email_spans.py --sample 500`.
- `tests/test_email_integration.py`: 4 new tests, including the two regression
  tests that caught the per-segment and all-or-nothing design flaws during
  development (kept as permanent regression coverage, not just scratch tests).

### Files
`extractor/text_unit_extractor.py` (`_resolve_email_offset_convention`,
`_convert_span`; segment loop in `extract_from_email` rewritten),
`scripts/diagnose_email_spans.py` (new), `tests/test_email_integration.py`.

### Recommended next step
Run `python scripts/diagnose_email_spans.py --sample 1000` against your
ingested corpus. It reuses the exact same detection function the extractor
uses, so its report is ground truth for your data, not speculation.

---



Scope expansion: NK analysis now covers mailing-list discourse alongside GitHub.
Emails are a third artefact family in the SAME pipeline — annotators, signal
model, projector phases, and scope filters all apply unchanged. Version 0.6.0.
Full design rationale: FRAMEWORK_DESIGN.md §11.

### Ontology
- New nodes `MailingList {name}` (≅ Repository) and `EmailMessage {urn}`
  (≅ Issue) with headers stored as properties; new edge `REPLIES_TO`
  (threading). Constraints on `MailingList.name`, `EmailMessage.urn`; indexes
  on `message_id`, `group`, `in_reply_to` (message_id is deliberately NOT
  unique — crawled archives contain missing/duplicate ids). ontology.cypher
  gained §3.13 templates; schema auto-applies on startup as before.
- Actors: the anonymized `from` value is the Actor login verbatim.
  Cross-platform identity resolution is explicitly out of scope.

### TextUnit granularity for emails (amends locked decision v0-1)
One TextUnit PER SELECTED SEGMENT using the corpus's pre-computed spans
(role = segment label, position = span order; subject at position 0).
Default allowlist `settings.email_segment_labels = ["paragraph",
"section_heading"]`. **`quotation` excluded as a methodological requirement:**
quoted text repeats the previous author's words → duplicate signals attributed
to the wrong author across whole threads. Signatures/patches/logs/code are not
authored epistemic discourse. Corpus `lang` is authoritative per message and
feeds the annotation language filter directly.

### New / changed code
- `miner/gmane_ingester.py` (new): reads Gzip ES-bulk line pairs, tolerant of
  malformed lines (logs + resyncs), filters at ingest (`--groups`, `--lang`,
  `--max` — MANDATORY practice at 153M-email corpus scale), upserts to Mongo
  `raw_emails` keyed on urn, publishes pointer events with `item_type="email"`,
  `repo_name="gmane:<group>"` — the exact miner contract.
- `extractor/text_unit_extractor.py`: `extract_from_email` (segment slicing,
  bounds-checked; ids `email:<urn>:<label>:<pos>`); worker routes `email`.
- `projector/graph_projector.py`: `upsert_email_message` (MailingList + Actor +
  EmailMessage + CONTAINS/AUTHORED); Phase 0 routes emails; `upsert_text_unit`
  gained the `EmailMessage {urn}` parent branch.
- `enrichment/email_threading.py` (new): single batched Cypher creates
  REPLIES_TO edges via the message_id index; reports dangling replies (parent
  outside ingested scope). Hooked into `run_pipeline.py --enrich`.
- `settings.email_segment_labels`.

### Tests (pure-Python, run green here)
`tests/test_email_integration.py` — 11 tests: bulk-format round-trip, malformed
-line resync, scope filters, subject+segment extraction, **quotation-exclusion
invariant**, id/parent conventions, out-of-bounds span tolerance, allowlist
configurability.

### ⚠️ Assumptions to verify on first contact with real data (no sample was
available when this was built):
- A1: records are strict line pairs (action, then source). Parser resyncs if not.
- A2: `_id` is the URN, possibly angle-bracketed. We strip brackets.
- A3: header names arrive lowercased as documented.
When you get access: run the ingester with `--max 1000` on one file, check the
counts log, run `pytest tests/test_email_integration.py`, and add ONE real
record to the test file as a golden sample.

### Usage
```bash
python -m miner.gmane_ingester --files data/gmane/*.gz \
    --groups gmane.comp.python.devel --lang en --max 50000
python scripts/run_pipeline.py --enrich
```

---



### Cause
Phase 1 took ~40 h for 80k nodes because the Neo4j **constraints/indexes were
never applied** — `setup_neo4j.sh` was referenced in the docs but did not exist,
so nobody ran it. Without indexes, `MERGE (u:TextUnit {id})` and
`MATCH (parent:Issue {repo, number})` degrade to full label scans that grow with
the graph (O(n²)) — exactly the superlinear blow-up that reaches tens of hours.

### Fix — schema is now applied automatically, three ways (single source of truth)
The executable DDL is *extracted* from `ontology/ontology.cypher` (only the
`CREATE CONSTRAINT` / `CREATE INDEX` statements; the parameterized MERGE
templates are skipped), so there is no duplicated schema to drift. All statements
are idempotent (`IF NOT EXISTS`), so applying them repeatedly is harmless.

1. **App-side (primary, foolproof):** `GraphProjector.create()` calls
   `ensure_schema()` on startup (toggle: `apply_schema_on_startup`, default True).
   The indexes are guaranteed present however Neo4j was launched — this removes
   the manual step entirely and makes the footgun unrepeatable.
2. **docker-compose `neo4j-init` service:** a one-shot container that waits for
   `neo4j` to be healthy, applies the schema, and exits. Runs on every
   `docker compose up`; safe because idempotent.
3. **`setup_neo4j.sh`** (newly created): manual one-off application of the same
   extracted DDL via `cypher-shell`.

Not done in a Dockerfile: the Neo4j image's entrypoint must own PID 1, so
backgrounding it to inject Cypher is brittle. The init service is the clean
compose-native equivalent.

### Action for the current slow run
Apply the schema (any of the three above — easiest: just re-run the pipeline now
that the projector self-applies it), then re-measure Phase 1. With indexes in
place the MERGE/MATCH become index seeks and the phase should drop from hours to
minutes. The separately-discussed UNWIND batching rewrite is still a worthwhile
improvement, but measure first — indexes alone may make it unnecessary for now.

---



Annotation (spaCy + RoBERTa over every TextUnit) was the dominant cost. This
release attacks it on two fronts: do less redundant work, and process less of
what doesn't matter. Version bumped to **0.5.0**.

### Speed (pure wins — no change to research scope)

1. **Parse each TextUnit once, not four times.** Previously every annotator
   created its own `spacy.load()` pipeline and re-parsed the text — four parses
   per unit, two of them running the slow dependency parser. Now the worker
   builds **one shared pipeline** (`annotators.base.make_nlp`) and passes the
   single parsed `Doc` to every rule annotator. The `Annotator` protocol is now
   `annotate(unit, doc)`.
2. **`nlp.pipe` batching.** The worker parses each batch of texts in one
   `nlp.pipe(..., batch_size, n_process)` call instead of per-document `nlp(text)`.
   `spacy_n_process` (default 1) enables multi-core parsing for more speed.
3. **Lean pipeline.** `make_nlp` disables the dependency parser and NER and adds
   a fast rule-based `sentencizer` (the only thing the morpho Q&A check needs
   sentence boundaries for). Disabling the parser is the biggest per-doc win
   after sharing the parse.
4. **Default spaCy model → `en_core_web_sm`** (`spacy_model`). We never use word
   vectors, so `sm` loads faster and uses less memory with negligible POS/lemma
   loss. `lg` still works. **Run `python -m spacy download en_core_web_sm`.**
5. **Bigger classifier batch on MPS.** `classifier_batch_size` and
   `annotator_batch_size` default to 64 (was 16/32) for better MPS throughput.

### Scope (configurable, research-traceable — answers the v1 questions)

The annotator now filters which TextUnits it processes, via a WHERE clause built
from settings. Defaults are conservative; nothing is dropped silently.

- `annotate_languages` (default `["en"]`) — only annotate these languages. The
  lexicon and classifier are English; annotating other languages produced noise.
- `annotate_min_tokens` (default `2`) — skip trivially short units ("+1", "done").
- `annotate_roles` (default all) — e.g. `["body","comment_body"]` to skip titles.
- `annotate_parent_types` (default all) — e.g. `["issue","pull_request"]` to skip
  commit messages (terse, often templated).
- `annotate_skip_bots` (default `True`) — skip `*[bot]` authors (templated text,
  no genuine NK articulation).
- `annotate_only_referenced_prs` (default `False`) — when set, PR-owned units are
  annotated only if their PR is linked to an Issue by a `REFERENCES` edge (run the
  enrichment pass first). Directly answers "only add PRs mentioned in an issue".

`annotate_languages` and `annotate_min_tokens` work on existing data. The role /
parent-type / skip-bots / referenced-PR filters read fields now stored on the
TextUnit node (`role`, `parent_type`, `author_login`); **re-run stage 1**
(`python scripts/run_pipeline.py --stage 1`) to backfill them — idempotent, the
`ON MATCH SET` in `upsert_text_unit` updates existing nodes.

### On MPS for spaCy
Not viable: the `sm`/`lg` pipelines are CNN-based and spaCy's GPU path targets
CUDA, not Apple MPS. MPS stays where it pays off — the RoBERTa classifier
(already on MPS). spaCy is kept fast on CPU via the points above; use
`spacy_n_process > 1` to spread it across cores.

### Files
`annotators/base.py` (make_nlp + protocol), all four rule annotators (shared nlp,
`annotate(unit, doc)`), `annotators/worker.py` (shared pipeline, `nlp.pipe`
batching, `_scope_filter`, filtered keyset pagination), `settings.py` (new knobs),
`projector/graph_projector.py` (store role/parent_type/author_login on TextUnit),
`tests/` (updated for the new signature), `pyproject.toml` (0.5.0).

### Expected effect
The redundant-parse fix alone is ~3–4× on the rule-annotation portion; `nlp.pipe`
+ the lean `sm` pipeline compound it; scope filters cut the *number* of units
(skipping bots, non-English, titles, commits can remove a large fraction on real
repos). Watch the `Annotate` ETA — it should drop substantially.

---

## 2026-06-03 — Feature: progress logging with rate + ETA

### What
Each long-running phase now logs steady progress (throttled to once every 5 s):
done count, total or queued count, percentage, throughput, elapsed, and ETA.

Example lines:
```
Annotate            9800/20000   (49.0%) |   245/s | elapsed 0:40 | ETA 0:41
Project TextUnits   12000 done |    300 queued |   980/s | elapsed 0:12 | ETA 0:00
```

### How
- New `progress.py` with a `Progress` helper (two modes):
  - **Fixed-total** (percentage + ETA to completion) — used where the total is
    known exactly: `Extract` and `Seed artefacts` (Phase 0) use `XLEN stream_raw`
    (untrimmed, so stable); `Annotate` uses `COUNT(TextUnit)` from Neo4j.
  - **Live-queue** (done + queued + ETA to drain) — used for the trimmed streams
    `Project TextUnits` (Phase 1) and `Project Signals` (Phase 2), where the
    denominator is the live `XLEN` of the stream. The queue may grow while the
    producer is still active; the ETA converges once production stops.
- Instrumented `extractor/worker.py`, `projector/worker.py` (Phases 0/1/2),
  `annotators/worker.py`.

### Notes
- The `Annotate` ETA is the most useful one — annotation (spaCy + RoBERTa) is the
  slowest phase, and its total is exact, so the estimate is reliable after the
  first few seconds.
- Logs are throttled, so they add negligible overhead. Phase 1/2 call `XLEN`
  once per batch (O(1) in Redis).

---



### Symptom
Processing a large backlog failed at the extractor with:
`command not allowed when used memory > 'maxmemory'`.

### Root cause
Redis is in-memory, and `broker.read_all` used `XREAD` but **never deleted
consumed entries** — Redis Streams retain every message until trimmed. So
`stream_units` (one entry per TextUnit, carrying full text) and `stream_signals`
(one per signal) grew without bound and were never reclaimed. On a large repo
they filled Redis; with the default `noeviction` policy, the next `XADD`
(the extractor publishing to `stream_units`) was rejected. Not related to the
earlier Mongo fix or to aborting the miner.

A structural obstacle blocked the obvious fix (trim on consume): `stream_units`
had **two** consumers — the projector in stage 1 and the annotator in stage 2 —
so trimming it during stage 1 would starve the annotator.

### Fix
- `broker.py`: `read_all(..., trim=False)` gained a `trim` flag. When set, each
  batch's message ids are `XDEL`'d once the consumer has processed them,
  reclaiming memory as the stream drains. Verified: every message is delivered
  exactly once and the stream is fully reclaimed.
- `annotators/worker.py`: the annotator now reads TextUnits from **Neo4j**
  (keyset pagination on `u.id`) instead of `stream_units`. Annotators only use
  `text` and `text_unit_id`, both stored on the TextUnit node, so this is
  lossless. This makes `stream_units` a single-consumer stream.
- `projector/worker.py`: Phase 1 (`stream_units`) and Phase 2 (`stream_signals`)
  now consume with `trim=True`. `stream_raw` is left untrimmed (it is small —
  pointer events only — and has two consumers in stage 1).
- `docker-compose.yml`: Redis now starts with an explicit, tunable
  `--maxmemory ${REDIS_MAXMEMORY:-2gb}` and `--maxmemory-policy noeviction`
  (fail loudly rather than silently drop queued work).

### Effect on the framework
- Redis memory is now reclaimed during the run; `stream_units` and
  `stream_signals` no longer accumulate across the whole pipeline or across runs.
- Stage 2 no longer depends on Redis for TextUnits — it reads them from the
  graph, which is disk-backed and already populated by stage 1.
- **Remaining peak:** during stage 1, `stream_units` still fills while the
  extractor produces faster than Phase 1 drains (Phase 1 runs after Phase 0).
  Trimming reclaims it as Phase 1 drains, and it is empty before stage 2. For
  very large repos, raise `REDIS_MAXMEMORY`, or mine+process in chunks. A future
  optimisation (concurrent Phase 0/1 draining with a completion sentinel and
  MERGE-parent) would cap this peak; deferred as it adds coordination complexity.

### Immediate unblock for your current run
Redis is full from the prior failed attempts. The derived streams are safe to
delete — they are regenerated from MongoDB; only keep `stream_raw`:

```bash
redis-cli INFO memory | grep used_memory_human         # inspect
redis-cli DEL graphrag.units graphrag.signals          # safe: regenerated
# do NOT delete graphrag.raw — it is your work list
docker compose up -d                                    # picks up new Redis limits
python scripts/run_pipeline.py --enrich                 # re-run; writes are idempotent
```

If it OOMs again on stage 1, raise the ceiling (e.g. `REDIS_MAXMEMORY=6gb` in
`.env` / environment) and restart the Redis container, or process the repo in
chunks.

---



### Symptom
Running `run_pipeline.py` against a large backlog (~20k+ events from a partially
mined repo) failed immediately and repeatedly with:
`extractor.worker — Event processing failed: localhost:27017: connection pool
paused (configured timeouts: connectTimeoutMS: 20000.0ms)`.

### Root cause
Not related to aborting the miner. The miner writes each doc to MongoDB before
publishing its stream event, so a partial mine is just a smaller, fully-valid
backlog. The real cause was **unbounded concurrency**:

- `broker.read_all` yields batches of 100 events.
- Both `extractor.worker` and `projector.worker` Phase 0 did
  `asyncio.gather(*[_process_event(e) ...])` over the whole batch — 100
  concurrent `find_one` calls each.
- In Stage 1 both run concurrently and both consume `stream_raw`, so up to ~200
  simultaneous Mongo operations.
- The client was created with no pool config (`AsyncIOMotorClient(uri)`).

On a small test repo the backlog was tiny so concurrency never spiked. On a
20k-event backlog every batch saturates the pool; one hiccup pauses it; and the
saturated event loop then starves the driver's server-monitor coroutine, so the
pool never un-pauses. Every subsequent fetch fails identically. A *completed*
20k+ mine would fail the same way — it is backlog-size × concurrency, not abort.

### Fix
- New `storage.py`:
  - `make_mongo_client()` — client with `maxPoolSize`, `retryReads=True`, and
    generous server-selection / socket timeouts.
  - `gather_bounded(coros, limit)` — `asyncio.gather(return_exceptions=True)`
    that never runs more than `limit` coroutines at once (semaphore).
- `settings.py`: added `mongo_max_pool_size` (50),
  `mongo_server_selection_timeout_ms` (30000), `mongo_socket_timeout_ms`
  (120000), and `mongo_fetch_concurrency` (16).
- `extractor/worker.py` and `projector/worker.py`: now build the client via
  `make_mongo_client()` and process each batch with
  `gather_bounded(..., settings.mongo_fetch_concurrency)` instead of an
  unbounded gather.

### Effect on the framework
- Pipeline now processes arbitrarily large backlogs without exhausting the pool.
- Throughput is intentionally capped at 16 concurrent Mongo fetches per worker
  (tune `mongo_fetch_concurrency` if your MongoDB can take more). This is a
  deliberate stability-over-speed trade for research runs.
- **Resuming your aborted run:** nothing was corrupted. Just re-run
  `python scripts/run_pipeline.py --enrich`. All writes are idempotent
  (`MERGE` on stable keys), so re-processing the same events is safe.
- If you want a clean slate instead, stop the stack, `docker compose down -v`
  to wipe volumes, then re-mine — but that is not required.

---



### Symptom
`Neo.ClientError.Statement.TypeError: Property values can only be of primitive
types or arrays thereof. Encountered: Map{...}` raised during
`upsert_signals_batch` (Phase 2), once per batch, the whole 100-signal batch
aborting.

### Root cause
`projector/graph_projector.py` line ~267 wrote `sig.payload = s.payload`, where
`s.payload` is a nested dict. Neo4j property graphs cannot store nested maps as
property values. Because **every** Signal (lexical, morpho, affix, rhetorical,
and the classifier's non-verdict Signal) carries a `payload` dict, every batch
failed. The error message surfaced whichever map Neo4j happened to be evaluating
when the type check fired — in the reported case the classifier payload — but it
was never specific to `upsert_classifier_verdict` (which writes only primitives
and was always correct).

### Fix
- `projector/graph_projector.py`:
  - Added `import json`.
  - In `upsert_signals_batch`, the payload is now JSON-serialised (with internal
    `__`-prefixed sentinel keys stripped) and stored as the string property
    `sig.payload_json`, replacing `sig.payload`.
- `ontology/schema.yml`: `Signal.payload {type: map}` → `Signal.payload_json {type: string}`.
- `ontology/ontology.cypher`: §3.8 template updated to `sig.payload_json` with a
  note explaining the constraint.
- `notebooks/01_descriptive.ipynb`: added a markdown note on parsing payloads with
  `apoc.convert.fromJsonMap(sig.payload_json)`.

### Effect on the framework
- **No data is lost.** All provenance previously in `payload` is preserved
  verbatim inside `payload_json`.
- **Querying payload fields now requires parsing.** Use
  `apoc.convert.fromJsonMap(sig.payload_json).<key>` in Cypher, or
  `json.loads(row['payload_json'])` in pandas. The notebooks do not query payload
  fields, so they are unaffected.
- **The promoted provenance is unchanged.** The fields that matter most for
  analysis — `lemma`/`source_citation` (LexicalMarker), `figure_id`/`family`
  (RhetoricalFigure), `label`/`confidence`/`model_id` (ClassifierVerdict) — were
  always stored as first-class primitive properties on dedicated nodes, not in
  `payload`. So RQ1–RQ5 queries in the notebooks need no changes.
- **Re-ingestion:** if you already have a partial graph from a failed run, the
  Signal MERGEs are idempotent on `signal_id`, so simply re-running
  `python scripts/run_pipeline.py --stage 2` will complete the signal layer.

---

## 2026-04-23 — v0 implementation complete (all 10 milestones)

### ✅ Implemented

#### Foundation (Milestone 0)
- `pyproject.toml` — all dependencies per BUILD_SPEC §2
- `docker-compose.yml` — Neo4j 5, MongoDB 7, Redis 7 with health checks
- `.env.example` — all environment variables documented
- `settings.py` — Pydantic-settings configuration; extends env file
- `broker.py` — Redis Streams wrapper (`RedisBroker`): `publish`, `read_all`
- `scripts/setup_neo4j.sh` — applies `ontology/ontology.cypher` via `cypher-shell`
- `ontology/schema.yml` — human-readable ontology with cross-references to FRAMEWORK_DESIGN.md
- `rules/categories.yml` — master registry of all signal categories → layer mapping

#### Ontology artefacts (from prior session)
- `ontology/ontology.cypher` — DDL: constraints, indexes, MERGE templates
- `lexicons/en_core_v0.1.yml` — seed NK lexicon (~20 entries with provenance)
- `patterns/morpho_syntactic_v0.1.yml` — 18 spaCy Matcher patterns
- `patterns/rhetorical_v0.1.yml` — 11 rhetorical figure patterns
- `patterns/word_formation_v0.1.yml` — 4 prefix + 2 suffix rules with blocklists

#### Milestone 1 — Miner integration tweaks
- `miner/async_miner.py` — two surgical edits applied to the frozen original:
  1. `content_sha256` added to every `_meta` block in MongoDB
  2. `item_subtype` field added to every event published on `stream_raw`

#### Milestone 2 — TextUnitExtractor
- `extractor/text_unit_extractor.py` — pure functions: `strip_text`, `extract_from_issue`,
  `extract_from_pull_request`, `extract_from_commit`
- `extractor/worker.py` — async consumer of `stream_raw`, dispatches to extractors,
  publishes TextUnit events to `stream_units`

#### Milestone 3 — GraphProjector (SE-artefact layer)
- `projector/graph_projector.py` — all Cypher write functions keyed to `ontology.cypher`
  §3 templates: `upsert_repository`, `upsert_actor`, `upsert_issue`,
  `upsert_pull_request`, `upsert_commit`, `upsert_text_unit`
- `projector/worker.py` — async consumer of `stream_units` + `stream_signals`;
  batches up to 100 signals or 2 s before flushing

#### Milestone 4 — LexiconAnnotator
- `annotators/base.py` — `TextUnit`, `Signal`, `Annotator` protocol
- `annotators/lexical.py` — YAML-driven `PhraseMatcher`; emits one Signal per match
  with full provenance in `payload` (lexicon_version, lemma, source_citation)
- `annotators/worker.py` — fan-out consumer; lazy loads all annotators; batches
  ClassifierAnnotator separately

#### Milestone 5 — SpacyMorphoAnnotator
- `annotators/morpho_syntactic.py` — YAML-driven spaCy `Matcher`; 18 patterns
  covering negation, modality, hedging, tense, and syntactic patterns;
  separate `_detect_question_answer` for unit-level Q&A structure

#### Milestone 6 — ClassifierAnnotator
- `annotators/classifier.py` — `NKClassifier` protocol; `HFTransformersClassifier`
  with MPS → CPU fallback; `ClassifierAnnotator` with `batch_annotate()`; emits
  Signal + ClassifierVerdict sentinel per TextUnit

#### Milestone 7 — AffixAnnotator
- `annotators/word_formation.py` — prefix (un-, in-, non-, dis-) and suffix (-less,
  -able) detection with POS gating and YAML blocklists; intentionally noisy

#### Milestone 8 — RhetoricalAnnotator
- `annotators/rhetorical.py` — spaCy `Matcher` over 11 figure patterns; payload
  carries `figure_id` + `family` for the projector's `INSTANTIATES` MERGE

#### Milestone 9 — Reference enrichment
- `enrichment/reference_extractor.py` — post-annotation pass; `extract_references()`
  (pure, tested); `run_reference_enrichment()` writes `REFERENCES` edges with
  canonical mechanism labels (closes, fixes, resolves, refs, see, bare)

#### Milestone 10 — Descriptive notebook
- `notebooks/01_descriptive.ipynb` — 6 sections: node counts, signal heatmap,
  top lexical markers, RQ5 scatter plot, RQ5 false-negative table,
  layer co-occurrence matrix

#### Scripts
- `scripts/mine_one.py` — thin CLI over `AsyncGitHubMiner`; `--repo`, `--repo-file`,
  `--no-commits`
- `scripts/run_pipeline.py` — starts extractor + annotator + projector workers
  concurrently via `asyncio.gather`; `--enrich` triggers reference enrichment

#### Tests
- `tests/conftest.py` — `make_unit()` fixture factory
- `tests/test_annotators.py` — golden examples for all five annotators +
  TextUnitExtractor stripping + reference extractor; **no external services required**

---

### ❌ Not yet implemented (v1+)

These are explicitly deferred per BUILD_SPEC.md §8. Do not implement unless
the spec is updated.

| Item | Reason deferred |
| ---- | --------------- |
| Sentence-level TextUnit splitting | Requires granularity decision after first pilot results |
| ClassifierAnnotator — MLX backend | MPS is sufficient for pilot; interface is ready |
| Statistical metaphor identification (Shutova et al.) | Lexicon+patterns first; expand after first pass |
| Multilingual annotation | Non-EN units are persisted but not annotated |
| Source-code AST features | NK is in natural language; AST is a separate research track |
| Cross-repo comparative analysis | Requires stable ontology first |
| RQ4 taxonomy clustering notebook (`05_rq4_taxonomy.ipynb`) | After manual annotation pass |
| RQ3 rhetorical stance notebook (`04_rq3_rhetorical.ipynb`) | After first descriptive pass |
| `IgnoranceType` post-hoc assignment | Analyst-driven; not pipeline work |
| REST/GraphQL API over the KG | Out of scope; use Neo4j driver directly |
| PR → Commit `TOUCHES` edge | Requires PR→commit API call; deferred |

---

### ⚠️ Known limitations / open issues

1. ~~**`upsert_issue` / `upsert_pull_request` assume Actor exists**~~ — **FIXED**.
   `projector/worker.py` now runs three sequential phases:
   - Phase 0: reads `stream_raw`, fetches each raw doc from MongoDB, seeds
     Repository / Actor / Issue / PullRequest / Commit nodes via
     `upsert_artefact_from_raw` (new method in `graph_projector.py`).
   - Phase 1: reads `stream_units`, writes TextUnit nodes. Parent always exists.
   - Phase 2: reads `stream_signals`, writes Signal nodes. TextUnit always exists.

2. ~~**Race condition — signals arriving before their TextUnit**~~ — **FIXED**.
   `scripts/run_pipeline.py` now runs two sequential **stages**:
   - Stage 1: Extractor + Projector (Phases 0 + 1) concurrently → exhaustion.
   - Stage 2: Annotator + Projector (Phase 2) concurrently → exhaustion.
   Signals are never published until Stage 1 is fully complete.

3. **`AffixAnnotator` blocklists are not exhaustive**. Expect false positives
   in the first pilot run. Document them as `TODO(lexicon-review)` and add
   to the YAML blocklist after inspection. This is a research iteration item,
   not a code defect.

4. **`fasttext-langdetect` model** must be downloaded on first run.
   It will auto-download to `~/.fasttext` on first `_detect_lang` call.

5. **Classifier path**: if `settings.classifier_model_path` does not exist,
   the ClassifierAnnotator is skipped with a WARNING. The rest of the pipeline
   continues normally.

---

## 2026-04-22 — Design session (prior session)

- `FRAMEWORK_DESIGN.md` written — full research frame, ontology, module outlines,
  RQ→Cypher mapping, 10-day plan
- `ontology/ontology.cypher` written — DDL with MERGE templates
- `lexicons/en_core_v0.1.yml` written — seed lexicon with provenance
- `AGENTS.md` written — coding agent behavioural contract
- `BUILD_SPEC.md` written — 10 milestones with acceptance checks
