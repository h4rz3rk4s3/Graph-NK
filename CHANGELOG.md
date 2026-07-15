# CHANGELOG.md

*Living record of what has been built, what is pending, and what decisions were
made during implementation. Updated at the end of every implementation session.*

*Format: newest entry at the top. Each entry references the BUILD_SPEC.md milestone
it closes or advances.*

---

## 2026-07-15 — v0.7.0: MARKER_REVIEW.md upgrade — scope, not just cues

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
double-count, AGENTS.md §3.3), not a bug to fix.

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
