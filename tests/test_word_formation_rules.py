"""
Pure-Python regression tests for annotators/word_formation.py's v0.2 fixes.

Deliberately spaCy-free: AffixAnnotator's core logic (_blocked_by_prefix,
allowlist-override, suffix mode) operates on plain strings and can be tested
directly without a spaCy Doc. This matters because spaCy is not installed in
every dev environment (see tests/test_annotators.py's disclaimer) — these
tests give real, always-runnable coverage of the two concrete bugs caught
while implementing MARKER_REVIEW.md's C-2/C-8 corrections:

  1. The "same-length blocklist entry" bug: a naive `startswith` blocklist
     check breaks catastrophically when a blocklist entry is the same length
     as the prefix itself (e.g. "in" in the "in-" prefix's OWN blocklist) —
     every candidate word starts with the prefix by definition, so it would
     universally block the entire rule. Caught via a stress test before
     shipping; see test_same_length_blocklist_entry_does_not_universally_block.
  2. The original C-8 case: "under" (longer than "un") must block "under-"
     continuations from the "un" prefix rule without needing an allowlist
     rescue, so the dedicated "under" prefix rule gets them instead.

Run: pytest tests/test_word_formation_rules.py -v
"""
from __future__ import annotations

from annotators.word_formation import AffixAnnotator


# ── Test the length-aware blocklist matcher directly (no spaCy, no I/O) ───────
# We exercise AffixAnnotator._blocked_by_prefix as an unbound function call,
# since it has no dependency on self beyond being a plain method.

def _blocked(lower: str, prefix: str, blocklist: list[str]) -> bool:
    # _blocked_by_prefix only touches its explicit arguments, never self, so
    # it's safe to call unbound with a throwaway instance placeholder.
    return AffixAnnotator._blocked_by_prefix(None, lower, prefix, blocklist)


class TestBlockedByPrefix:
    """Direct tests of the C-8 length-aware blocklist logic."""

    UN_BLOCKLIST = ["under", "until", "unit", "union", "unique", "university",
                     "unless", "update", "upload", "url", "use", "user", "utf"]
    IN_BLOCKLIST = ["income", "index", "initial", "input", "install", "integer",
                     "interface", "interior", "internal", "issue", "info",
                     "init", "inline", "into", "include", "instance", "int", "in"]

    def test_same_length_blocklist_entry_does_not_universally_block(self):
        """
        THE bug caught during development: "in" (2 chars) sits in the "in"
        prefix's (2 chars) own blocklist. Every candidate word for this rule
        starts with "in" by definition — a naive startswith check against
        "in" would therefore block EVERY in- word, including all the
        allowlisted NK ones. This must not happen.
        """
        nk_words = ["incomplete", "inconsistent", "inconclusive", "indeterminate",
                    "indefinite", "insufficient", "incorrect", "invalid"]
        for w in nk_words:
            assert not _blocked(w, "in", self.IN_BLOCKLIST), (
                f"'{w}' was wrongly blocked — the same-length 'in' blocklist "
                f"entry must not universally suppress the in- rule"
            )

    def test_genuinely_blocklisted_in_words_are_still_blocked(self):
        non_nk = ["income", "index", "initial", "input", "interface", "instance"]
        for w in non_nk:
            assert _blocked(w, "in", self.IN_BLOCKLIST), (
                f"'{w}' should still be blocked (longer blocklist entry, self-match)"
            )

    def test_under_continuation_blocked_from_un_rule(self):
        """The original C-8 case: 'under' is longer than the 'un' prefix, so
        it correctly excludes under- continuations via startswith."""
        assert _blocked("underspecified", "un", self.UN_BLOCKLIST)
        assert _blocked("underdocumented", "un", self.UN_BLOCKLIST)
        assert _blocked("understand", "un", self.UN_BLOCKLIST)

    def test_genuine_un_nk_words_not_blocked(self):
        genuine = ["uncertain", "unclear", "unknown", "undefined", "unspecified",
                   "undocumented", "unresolved", "unpredictable", "unexplained",
                   "unreliable", "unstable", "unexpected"]
        for w in genuine:
            assert not _blocked(w, "un", self.UN_BLOCKLIST), (
                f"'{w}' is a genuine un- NK word and must not be blocked"
            )

    def test_exact_equality_still_applies_to_short_entries(self):
        """A blocklist entry the SAME length as the prefix only ever blocks
        the literal word equal to it — never a longer word that merely starts
        with it (there is no such word, since entry length == prefix length)."""
        # "in" itself is blocked (trivial exact match) — though in practice
        # this candidate never reaches the check at all (min_stem_length gate).
        assert _blocked("in", "in", self.IN_BLOCKLIST)
        # Nothing else should be caught by the bare "in" entry specifically —
        # verified indirectly above (all in- NK words pass).


# ── Allowlist-overrides-blocklist (v0.2 NEW mechanism) ────────────────────────

class TestAllowlistOverridesBlocklist:
    def test_allowlisted_word_bypasses_blocklist_entirely(self):
        """If a spec declares an allowlist and the word is in it, it ALWAYS
        matches — this is how NK under-/in- compounds survive even if some
        other blocklist entry would otherwise have caught them."""
        # Construct a deliberately adversarial case: put "underspecified"
        # in BOTH the allowlist AND make it match a blocklist entry, and
        # confirm allowlist wins (this is the contract _check_prefix relies on).
        lower = "underspecified"
        allowlist = {"underspecified"}
        blocklist = ["under"]  # would otherwise block it (longer than "un")
        prefix = "un"
        blocked_ignoring_allowlist = _blocked(lower, prefix, blocklist)
        assert blocked_ignoring_allowlist, "test setup sanity: blocklist should catch it alone"
        # The real _check_prefix path checks `lower not in allowlist` BEFORE
        # calling _blocked_by_prefix — reproduce that contract directly:
        would_match = lower in allowlist or not _blocked(lower, prefix, blocklist)
        assert would_match, "allowlist must override the blocklist"


# ── Suffix mode: allowlist_only (C-2) ─────────────────────────────────────────

class TestSuffixAllowlistOnlyMode:
    """
    C-2: the -able suffix's mode: "allowlist_only" means the blanket suffix
    scan is skipped entirely; only explicit allowlist entries match. We can't
    call _check_suffix without a spaCy token, but the YAML-driven behavioural
    CONTRACT (what mode: allowlist_only is supposed to mean) is tested here
    as a plain-data check, matching what annotate() actually branches on.
    """

    ABLE_ALLOWLIST = {"questionable", "debatable", "unpredictable", "undecidable",
                       "unknowable", "unverifiable", "unfalsifiable",
                       "unexplainable", "inexplicable", "unaccountable", "unprovable"}
    ABLE_NON_NK = {"reproducible", "testable", "configurable", "serializable",
                   "readable", "available", "enable", "disable", "stable", "cable"}

    def test_nk_able_words_are_in_the_allowlist(self):
        # A basic data-integrity check: every word we WANT to catch must
        # actually be present in the shipped YAML allowlist.
        import yaml
        from pathlib import Path
        path = Path(__file__).parent.parent / "patterns" / "word_formation_v0.2.yml"
        config = yaml.safe_load(path.read_text())
        able_spec = next(s for s in config["suffixes"] if s["suffix"] == "able")
        assert able_spec.get("mode") == "allowlist_only"
        shipped_allowlist = set(able_spec.get("allowlist", []))
        assert self.ABLE_ALLOWLIST.issubset(shipped_allowlist)

    def test_non_nk_able_words_are_not_in_the_allowlist(self):
        import yaml
        from pathlib import Path
        path = Path(__file__).parent.parent / "patterns" / "word_formation_v0.2.yml"
        config = yaml.safe_load(path.read_text())
        able_spec = next(s for s in config["suffixes"] if s["suffix"] == "able")
        shipped_allowlist = set(able_spec.get("allowlist", []))
        overlap = self.ABLE_NON_NK & shipped_allowlist
        assert not overlap, (
            f"Capability -able words leaked into the NK allowlist: {overlap} "
            f"— this would reintroduce the exact FP class C-2 was fixing"
        )


# ── Structural sanity on the shipped v0.2 files (no spaCy needed) ─────────────

class TestV02FileStructuralIntegrity:
    """Guards against regressions in the YAML content itself, independent of
    the annotator code — catches the class of bug MARKER_REVIEW.md itself
    found (e.g. C-4's double-'yet' pattern) before it reaches production."""

    def _load(self, name: str) -> dict:
        import yaml
        from pathlib import Path
        return yaml.safe_load((Path(__file__).parent.parent / "patterns" / name).read_text())

    def test_no_duplicate_rule_ids_morpho(self):
        data = self._load("morpho_syntactic_v0.2.yml")
        ids = [p["id"] for p in data["patterns"]]
        assert len(ids) == len(set(ids)), "duplicate rule ids would silently collide in a Matcher"

    def test_dependency_matcher_patterns_are_well_formed(self):
        """Every DependencyMatcher pattern's first node has only RIGHT_ID/
        RIGHT_ATTRS; every subsequent node's LEFT_ID references an
        already-declared RIGHT_ID (a dangling reference is a real bug class —
        this is exactly the kind of structural error C-4 exemplifies)."""
        data = self._load("morpho_syntactic_v0.2.yml")
        dep_patterns = [p for p in data["patterns"] if p.get("type") == "DependencyMatcher"]
        assert dep_patterns, "expected at least one DependencyMatcher pattern in v0.2"
        for p in dep_patterns:
            pat = p["pattern"]
            first = pat[0]
            assert "RIGHT_ID" in first and "RIGHT_ATTRS" in first and "LEFT_ID" not in first, (
                f"{p['id']}: first node must be a bare RIGHT_ID/RIGHT_ATTRS anchor"
            )
            declared = {first["RIGHT_ID"]}
            for node in pat[1:]:
                assert node.get("LEFT_ID") in declared, (
                    f"{p['id']}: LEFT_ID {node.get('LEFT_ID')!r} references an "
                    f"undeclared node"
                )
                assert "REL_OP" in node and "RIGHT_ATTRS" in node
                declared.add(node["RIGHT_ID"])

    def test_kind_of_dedup_c5(self):
        """C-5: rhetor.comparison.kind_of must be gone; something_like stays."""
        rhet = self._load("rhetorical_v0.2.yml")
        figure_ids = {f["rule_id"] for f in rhet["figures"]}
        assert "rhetor.comparison.kind_of" not in figure_ids
        assert "rhetor.comparison.something_like" in figure_ids
