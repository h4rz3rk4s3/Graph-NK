"""
Module 3b — AffixAnnotator (Milestone 7).

Detects morphological NK signals via prefixes (un-, in-, non-, dis-, under-,
mis-) and suffixes (-less, -able, -free) on ADJ/NOUN/VERB tokens.

Design notes (BUILD_SPEC.md M7):
  - Deliberately noisy in v0. The research goal is to discover which affixed
    forms actually recur in SE discourse; over-filtering now would hide signal.
  - Blocklists in YAML prevent the most obvious SE false positives.
  - spaCy is used for POS tagging. Operates on the shared pre-parsed Doc.

v0.2 (MARKER_REVIEW.md C-2, C-8):
  C-8 — blocklist matching upgraded to be LENGTH-AWARE. Every candidate word
        for a prefix rule starts with that prefix by definition, so a
        blocklist entry the SAME LENGTH as the prefix (e.g. "in" itself,
        which is literally in the "in" prefix's own blocklist) must be
        matched by EXACT equality — using startswith there would trivially
        match every candidate and silently suppress the whole rule. A entry
        LONGER than the prefix (e.g. "under", which is un + der) represents
        a genuine more-specific continuation and IS matched via startswith,
        so "underspecified" is correctly excluded from the "un" rule (it
        starts with the blocklisted "under") and picked up instead, once, by
        the new dedicated affix.prefix.under rule. See _blocked_by_prefix.
  C-2 — the -able suffix gained a `mode: "allowlist_only"` switch: when set,
        the blanket suffix scan is skipped entirely and only words in the
        allowlist match. This is how "questionable"/"unknowable" are kept
        as NK signals while "reproducible"/"testable"/"configurable" (dynamic
        capability, not NK) are excluded, without a giant per-word blocklist.
  NEW  — allowlist-overrides-blocklist: if a spec declares an `allowlist` and
        the full word is in it, the entry ALWAYS matches regardless of the
        blocklist. This is how "under-" NK compounds and "-able" NK adjectives
        survive their prefix/suffix's otherwise-broad blocklist.
  NEW  — `polarity` is now read from the spec and carried into the payload
        (used by the "-free" suffix, a deliberate NON-NK "certainty" control
        for RQ5 contrastive analysis — see word_formation_v0.2.yml).

Literature: Janich & Simmerling 2013.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from annotators.base import Annotator, Signal, TextUnit
from settings import settings

logger = logging.getLogger(__name__)

# POS tags that are valid targets for affix detection
_TARGET_POS = {"ADJ", "NOUN", "VERB", "ADV"}


def _default_pattern_path() -> Path:
    v = settings.pattern_set_version
    return Path(__file__).parent.parent / "patterns" / f"word_formation_v{v}.yml"


class AffixAnnotator:
    """
    Morphological NK annotator. One Signal per matching token.
    Implements the Annotator protocol.
    """
    name = "AffixAnnotator"

    def __init__(self, nlp, pattern_path: Path | None = None) -> None:
        self._nlp = nlp
        pattern_path = pattern_path or _default_pattern_path()
        self._config = self._load_config(pattern_path)
        self.version = self._config["version"]
        # Pre-build lookup structures from YAML for O(1) token checks
        self._prefix_specs = self._config.get("prefixes", [])
        self._suffix_specs = self._config.get("suffixes", [])
        logger.info(
            "AffixAnnotator loaded %d prefix + %d suffix rules (v%s)",
            len(self._prefix_specs), len(self._suffix_specs), self.version,
        )

    def annotate(self, unit: TextUnit, doc) -> list[Signal]:
        if not unit.text:
            return []

        signals: list[Signal] = []

        for token in doc:
            # Only ADJ, NOUN, VERB, ADV targets — avoids matching function words
            if token.pos_ not in _TARGET_POS:
                continue
            lower = token.lower_

            for spec in self._prefix_specs:
                # Prefix specs may restrict to specific POS (v0.2: several do)
                target_pos = spec.get("target_pos", list(_TARGET_POS))
                if token.pos_ not in target_pos:
                    continue
                sig = self._check_prefix(unit, token, lower, spec)
                if sig:
                    signals.append(sig)

            for spec in self._suffix_specs:
                target_pos = spec.get("target_pos", list(_TARGET_POS))
                if token.pos_ not in target_pos:
                    continue
                sig = self._check_suffix(unit, token, lower, spec)
                if sig:
                    signals.append(sig)

        return signals

    # ── private helpers ───────────────────────────────────────────────────────

    def _load_config(self, path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _blocked_by_prefix(self, lower: str, prefix: str, blocklist: list[str]) -> bool:
        """
        C-8 blocklist matching: a blocklist entry LONGER than the prefix
        itself represents a more specific continuation of it (e.g. "under"
        continuing past the bare "un" prefix) and is matched via startswith,
        so it correctly excludes the whole word-family from this prefix's
        rule. A blocklist entry the SAME length as (or shorter than) the
        prefix — e.g. "in" itself in the "in" prefix's own blocklist — is
        matched by EXACT equality only.

        This distinction is load-bearing, not cosmetic: every candidate word
        for a prefix rule starts with that prefix by definition (that's the
        match condition), so a same-length entry used with startswith would
        match literally everything and silently suppress the entire rule.
        (Caught during development against the "in" prefix's own blocklist,
        which contains "in" itself — see CHANGELOG.)
        """
        for b in blocklist:
            if len(b) > len(prefix):
                if lower.startswith(b):
                    return True
            elif lower == b:
                return True
        return False

    def _check_prefix(
        self, unit: TextUnit, token: Any, lower: str, spec: dict
    ) -> Signal | None:
        prefix = spec["prefix"]
        min_len = spec.get("min_stem_length", 3)
        blocklist: list[str] = spec.get("blocklist", [])
        allowlist: set[str] = set(spec.get("allowlist", []))

        if not lower.startswith(prefix):
            return None
        stem = lower[len(prefix):]
        if len(stem) < min_len:
            return None

        # Allowlist ALWAYS wins over blocklist (v0.2) — this is how genuine
        # NK "under-"/"in-" compounds survive their prefix's blocklist.
        if lower not in allowlist and self._blocked_by_prefix(lower, prefix, blocklist):
            return None

        return Signal(
            text_unit_id=unit.text_unit_id,
            layer="word_formation",
            category=spec["category"],
            subcategory=spec.get("subcategory"),
            surface_form=token.text,
            span_start=token.idx,
            span_end=token.idx + len(token.text),
            rule_id=spec["rule_id"],
            rule_version=self.version,
            weight=spec.get("weight"),
            status=spec.get("status", "active"),
            payload={
                "prefix": prefix,
                "stem": stem,
                "pos": token.pos_,
                "lemma": token.lemma_,
                "source": spec.get("source", ""),
                "polarity": spec.get("polarity", ""),
            },
        )

    def _check_suffix(
        self, unit: TextUnit, token: Any, lower: str, spec: dict
    ) -> Signal | None:
        suffix = spec["suffix"]
        min_len = spec.get("min_word_length", 4)
        blocklist: set[str] = set(spec.get("blocklist", []))
        allowlist: set[str] = set(spec.get("allowlist", []))
        mode = spec.get("mode")

        if mode == "allowlist_only":
            # C-2: skip the blanket suffix scan entirely — only an explicit
            # allowlist entry matches (e.g. "questionable" but never
            # "reproducible"/"testable", which are capability, not NK).
            if lower not in allowlist:
                return None
        else:
            if not lower.endswith(suffix):
                return None
            if len(lower) < min_len:
                return None
            # Allowlist overrides blocklist here too, for consistency.
            if lower not in allowlist and lower in blocklist:
                return None

        return Signal(
            text_unit_id=unit.text_unit_id,
            layer="word_formation",
            category=spec["category"],
            subcategory=spec.get("subcategory"),
            surface_form=token.text,
            span_start=token.idx,
            span_end=token.idx + len(token.text),
            rule_id=spec["rule_id"],
            rule_version=self.version,
            weight=spec.get("weight"),
            status=spec.get("status", "active"),
            payload={
                "suffix": suffix,
                "stem": lower[: -len(suffix)] if lower.endswith(suffix) else lower,
                "pos": token.pos_,
                "lemma": token.lemma_,
                "source": spec.get("source", ""),
                "polarity": spec.get("polarity", ""),
            },
        )
