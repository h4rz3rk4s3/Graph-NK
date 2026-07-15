"""
Golden-example tests for all annotators.

Rules (AGENTS.md §4):
  - At least one example per signal category each annotator can emit.
  - Tests are synchronous — annotators are CPU-bound.
  - No external services (Neo4j, Redis, Mongo) required.
  - These tests do NOT cover infrastructure; they cover linguistic correctness.

⚠️ v0.2 STATUS (MARKER_REVIEW.md upgrade — see CHANGELOG): the two assertions
that were PROVABLY stale against v0.2's rule changes (seem/appear moved
modality→evidential per C-6; rhetor.comparison.kind_of removed per C-5) have
been corrected below, verified by direct inspection of the v0.2 YAML pattern
text. The remaining assertions are believed still correct by the same kind of
manual tracing, but this file was NOT re-run against real spaCy while making
these changes (spaCy is unavailable in the dev sandbox — same constraint as
the v0.5 speed pass). In particular, the NEW DependencyMatcher-scoped rules
(morph.epi.*, morph.hedge.shield_*, morph.neg.scoped_epistemic,
morph.tense.past_nk_notyet) and the lexical POS-disambiguation fix have zero
automated coverage here yet — run `pytest tests/test_annotators.py -v` with
spaCy installed before trusting this file, and add golden examples for the
DependencyMatcher rules (none exist yet; see tests/test_word_formation_rules.py
for what pure-Python coverage looks like for the parts that don't need spaCy).

Run:  pytest tests/test_annotators.py -v
"""
from __future__ import annotations

import pytest

from tests.conftest import make_unit, run


# ─────────────────────────────────────────────────────────────────────────────
# LexiconAnnotator — Milestone 4
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def lexicon_ann(nlp):
    from annotators.lexical import LexiconAnnotator
    return LexiconAnnotator(nlp)


@pytest.mark.parametrize("text, expected_rule_ids", [
    # prototype: epistemic_state
    ("I'm not entirely sure what caused this.",          ["lex.uncertain"]),
    ("There is genuine doubt about this behaviour.",     ["lex.doubt_n"]),
    ("The root cause is completely unknown to us.",      ["lex.unknown"]),
    # prototype: imprecision
    ("The specification is ambiguous and vague.",        ["lex.ambiguous", "lex.vague"]),
    # fixed_phrase: visibility / gap
    ("This is a clear blind spot for the team.",         ["lex.blind_spot"]),
    ("There is a knowledge gap in the documentation.",   ["lex.knowledge_gap"]),
    # shared_feature
    ("Several issues remain unresolved after the sprint.",["lex.unresolved"]),
    ("There is a lack of documentation for this API.",   ["lex.lack_of"]),
    # negative — no NK signal expected
    ("The implementation works correctly.",              []),
    ("All tests pass on the main branch.",               []),
])
def test_lexicon_annotator(nlp, lexicon_ann, text, expected_rule_ids):
    signals = run(lexicon_ann, nlp, text)
    result_ids = sorted(s.rule_id for s in signals)
    assert result_ids == sorted(expected_rule_ids), (
        f"Text: {text!r}\nExpected: {sorted(expected_rule_ids)}\nGot: {result_ids}"
    )


def test_lexicon_signal_has_provenance(nlp, lexicon_ann):
    """Every Signal must carry rule_id, rule_version, and non-empty payload."""
    signals = run(lexicon_ann, nlp, "I'm unsure about the root cause.")
    assert signals, "Expected at least one signal"
    for sig in signals:
        assert sig.rule_id.startswith("lex."), f"Bad rule_id: {sig.rule_id}"
        assert sig.rule_version, "rule_version must not be empty"
        assert sig.payload.get("lexicon_version"), "payload must contain lexicon_version"
        assert sig.payload.get("source_citation"), "payload must contain source_citation"


# ─────────────────────────────────────────────────────────────────────────────
# SpacyMorphoAnnotator — Milestone 5
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def morpho_ann(nlp):
    from annotators.morpho_syntactic import SpacyMorphoAnnotator
    return SpacyMorphoAnnotator(nlp)


def _categories(signals):
    return {s.category for s in signals}

def _rule_ids(signals):
    return {s.rule_id for s in signals}


@pytest.mark.parametrize("text, expected_categories", [
    # negation
    ("We can't reproduce this on our machines.",       {"negation"}),
    ("I never saw this error before the last release.", {"negation"}),
    # modality
    ("This might be a race condition.",                 {"modality"}),
    ("We should fix the root cause, not the symptom.",  {"modality"}),
    # evidential (v0.2 C-6: seem/appear moved OUT of modality — was mislabelled quasi_modal in v0.1)
    ("It seems to only happen under load.",              {"evidential"}),
    # hedging
    ("Perhaps the timeout is too short.",               {"hedging"}),
    ("This is kind of hard to reproduce.",              {"hedging"}),
    # adversative syntactic pattern
    ("I tried the workaround but the issue persists.", {"syntactic_pattern"}),
    # no signal expected
    ("Everything is working as expected.",              set()),
])
def test_morpho_annotator_categories(nlp, morpho_ann, text, expected_categories):
    signals = run(morpho_ann, nlp, text)
    result_cats = _categories(signals)
    for cat in expected_categories:
        assert cat in result_cats, (
            f"Expected category '{cat}' in {result_cats!r} for text: {text!r}"
        )


def test_morpho_question_answer_detection(nlp, morpho_ann):
    """A TextUnit with both a question and a declarative triggers question_answer."""
    text = "Why does this only happen on Linux? It seems related to the kernel version."
    signals = run(morpho_ann, nlp, text)
    rule_ids = _rule_ids(signals)
    assert "morph.syn.question_answer" in rule_ids, (
        f"Expected question_answer signal. Got: {rule_ids}"
    )


def test_morpho_signal_provenance(nlp, morpho_ann):
    signals = run(morpho_ann, nlp, "This might not work correctly.")
    for sig in signals:
        assert sig.rule_id.startswith("morph."), f"Bad rule_id prefix: {sig.rule_id}"
        assert sig.rule_version
        assert sig.layer == "morpho_syntactic"


# ─────────────────────────────────────────────────────────────────────────────
# AffixAnnotator — Milestone 7
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def affix_ann(nlp):
    from annotators.word_formation import AffixAnnotator
    return AffixAnnotator(nlp)


@pytest.mark.parametrize("text, expected_rule_ids_subset", [
    # un- prefix
    ("The behaviour is unclear and unreliable.",        ["affix.prefix.un", "affix.prefix.un"]),
    # in- prefix (careful: 'interface' is blocklisted)
    ("This situation is impossible to reproduce.",     ["affix.prefix.in"]),
    # -less suffix
    ("The team was helpless without the logs.",         ["affix.suffix.less"]),
    # -able suffix
    ("This is a questionable design decision.",         ["affix.suffix.able"]),
    # non- prefix
    ("Non-deterministic test failures are frustrating.",["affix.prefix.non"]),
    # blocklist: 'interface' must NOT fire
    ("The interface is stable.",                        []),
])
def test_affix_annotator(nlp, affix_ann, text, expected_rule_ids_subset):
    signals = run(affix_ann, nlp, text)
    result_ids = [s.rule_id for s in signals]
    for expected in expected_rule_ids_subset:
        assert expected in result_ids, (
            f"Expected rule_id '{expected}' in {result_ids!r} for: {text!r}"
        )


def test_affix_blocklist_works(nlp, affix_ann):
    """Common SE terms that start with a blocked prefix must not produce signals."""
    for word in ["interface", "internal", "input", "index"]:
        signals = run(affix_ann, nlp, f"The {word} is fine.")
        rule_ids = [s.rule_id for s in signals]
        assert "affix.prefix.in" not in rule_ids, (
            f"'{word}' should be blocklisted but fired affix.prefix.in"
        )


# ─────────────────────────────────────────────────────────────────────────────
# RhetoricalAnnotator — Milestone 8
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rhetor_ann(nlp):
    from annotators.rhetorical import RhetoricalAnnotator
    return RhetoricalAnnotator(nlp)


@pytest.mark.parametrize("text, expected_figure_ids", [
    # spatial metaphor
    ("This is completely uncharted territory for us.",    ["rhetor.metaphor.spatial.uncharted"]),
    # visibility metaphor
    ("Concurrency bugs are a classic blind spot.",        ["rhetor.metaphor.visibility.blind_spot"]),
    # gap metaphor
    ("There is a knowledge gap in the test coverage.",   ["rhetor.metaphor.gap.knowledge_gap"]),
    # comparison approximator (v0.2 C-5: rhetor.comparison.kind_of REMOVED —
    # "kind of" lives in morpho hedging only now. This sentence still fires
    # rhetor.comparison.something_like via "feels like".)
    ("This feels like a kind of race condition.",        ["rhetor.comparison.something_like"]),
    # no rhetorical signal
    ("The fix was merged into main yesterday.",          []),
])
def test_rhetorical_annotator(nlp, rhetor_ann, text, expected_figure_ids):
    signals = run(rhetor_ann, nlp, text)
    result_figure_ids = [s.payload.get("figure_id") for s in signals]
    for fid in expected_figure_ids:
        assert fid in result_figure_ids, (
            f"Expected figure_id '{fid}' in {result_figure_ids!r} for: {text!r}"
        )


def test_rhetorical_signal_has_figure_payload(nlp, rhetor_ann):
    """Rhetorical signals must carry figure_id and family in payload for INSTANTIATES edge."""
    signals = run(rhetor_ann, nlp, "This is a real blind spot for the team.")
    assert signals
    for sig in signals:
        assert sig.payload.get("figure_id"), "Missing figure_id in payload"
        assert sig.payload.get("family") in {"metaphor", "comparison", "personification", "hyperbole"}, \
            f"Unexpected family: {sig.payload.get('family')}"
        assert sig.layer == "rhetorical"


def test_intentional_double_count(nlp, lexicon_ann, rhetor_ann):
    """
    'blind spot' must produce BOTH a lexical and a rhetorical signal.
    This is intentional — the two signals have different categorical meanings.
    See AGENTS.md §3.3 and FRAMEWORK_DESIGN.md §5 Module 3d.
    """
    text = "This is a serious blind spot in the architecture."
    lex_signals    = run(lexicon_ann, nlp, text)
    rhetor_signals = run(rhetor_ann, nlp, text)
    lex_ids    = [s.rule_id for s in lex_signals]
    rhetor_ids = [s.rule_id for s in rhetor_signals]
    assert "lex.blind_spot" in lex_ids, "Lexical blind_spot signal missing"
    assert "rhetor.metaphor.visibility.blind_spot" in rhetor_ids, \
        "Rhetorical blind_spot signal missing"


# ─────────────────────────────────────────────────────────────────────────────
# TextUnitExtractor — Milestone 2
# ─────────────────────────────────────────────────────────────────────────────

def test_strip_code_blocks():
    from extractor.text_unit_extractor import strip_text
    raw = "I think this fails.\n```python\nprint('x')\n```\nNot sure why."
    result = strip_text(raw)
    assert "print" not in result
    assert "I think this fails." in result
    assert "Not sure why." in result


def test_strip_quotes():
    from extractor.text_unit_extractor import strip_text
    raw = "> Previous comment\nActual reply here."
    result = strip_text(raw)
    assert "Previous comment" not in result
    assert "Actual reply here" in result


def test_strip_mentions():
    from extractor.text_unit_extractor import strip_text
    raw = "@octocat can you look at this?"
    result = strip_text(raw)
    assert "@octocat" not in result
    assert "can you look at this?" in result


def test_extract_from_issue_units():
    from extractor.text_unit_extractor import extract_from_issue
    doc = {
        "number": 42,
        "title": "Something is unclear",
        "body": "I have no idea what is happening here.",
        "user": {"login": "alice"},
        "created_at": "2024-01-01T00:00:00Z",
        "labels": [],
        "comments_data": [
            {"body": "Me neither, very confusing.", "user": {"login": "bob"},
             "created_at": "2024-01-02T00:00:00Z"},
        ],
    }
    units = extract_from_issue(doc, "test/repo")
    roles = [u.role for u in units]
    assert "title" in roles
    assert "body" in roles
    assert "comment_body" in roles
    assert len(units) == 3


def test_empty_body_skipped():
    from extractor.text_unit_extractor import extract_from_issue
    doc = {
        "number": 1, "title": "Hello", "body": "",
        "user": {"login": "alice"}, "created_at": None,
        "labels": [], "comments_data": [],
    }
    units = extract_from_issue(doc, "test/repo")
    # Only the title unit should survive — empty body is skipped
    assert len(units) == 1
    assert units[0].role == "title"


# ─────────────────────────────────────────────────────────────────────────────
# Reference extractor — Milestone 9
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected_refs", [
    ("fixes #123",                          [(123, "fixes")]),
    ("closes #42 and refs #7",              [(42, "closes"), (7, "refs")]),
    ("See #100 for more context.",          [(100, "see")]),
    ("This addresses #999",                 [(999, "bare")]),
    ("No cross-references here.",           []),
    ("resolves #1 and closes #2",           [(1, "resolves"), (2, "closes")]),
])
def test_extract_references(text, expected_refs):
    from enrichment.reference_extractor import extract_references
    result = extract_references(text)
    assert result == expected_refs, f"Text: {text!r}\nExpected: {expected_refs}\nGot: {result}"
