"""
Module 3b — AffixAnnotator (Milestone 7).

Detects morphological NK signals via prefixes (un-, in-, non-, dis-) and
suffixes (-less, -able) on ADJ/NOUN tokens.

Design notes (BUILD_SPEC.md M7):
  - Deliberately noisy in v0. The research goal is to discover which affixed
    forms actually recur in SE discourse; over-filtering now would hide signal.
  - Blocklists in YAML prevent the most obvious SE false positives.
  - spaCy is used for POS tagging. The model must already be loaded by the
    worker — pass a pre-parsed Doc where possible (optional v0 optimisation;
    not required, falls back to re-parsing).

Literature: Janich & Simmerling 2013.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import spacy
import yaml

from annotators.base import Annotator, Signal, TextUnit
from settings import settings

logger = logging.getLogger(__name__)

_PATTERN_PATH = Path(__file__).parent.parent / "patterns" / "word_formation_v0.1.yml"

# POS tags that are valid targets for affix detection
_TARGET_POS = {"ADJ", "NOUN", "ADV"}


class AffixAnnotator:
    """
    Morphological NK annotator. One Signal per matching token.
    Implements the Annotator protocol.
    """
    name = "AffixAnnotator"

    def __init__(self, nlp, pattern_path: Path = _PATTERN_PATH) -> None:
        self._nlp = nlp #spacy.load(settings.spacy_model, disable=["ner", "parser"])
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

        if doc is None:
            doc = self._nlp(unit.text)
        signals: list[Signal] = []

        for token in doc:
            # Only ADJ, NOUN, ADV targets — avoids matching function words
            if token.pos_ not in _TARGET_POS:
                continue
            lower = token.lower_

            for spec in self._prefix_specs:
                sig = self._check_prefix(unit, token, lower, spec)
                if sig:
                    signals.append(sig)

            for spec in self._suffix_specs:
                # Suffix specs may restrict to specific POS
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

    def _check_prefix(
        self, unit: TextUnit, token: Any, lower: str, spec: dict
    ) -> Signal | None:
        prefix = spec["prefix"]
        min_len = spec.get("min_stem_length", 3)
        blocklist: set[str] = set(spec.get("blocklist", []))

        if not lower.startswith(prefix):
            return None
        stem = lower[len(prefix):]
        if len(stem) < min_len:
            return None
        # Block if the full token is in the blocklist
        if lower in blocklist:
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
            payload={
                "prefix": prefix,
                "stem": stem,
                "pos": token.pos_,
                "lemma": token.lemma_,
                "source": spec.get("source", ""),
            },
        )

    def _check_suffix(
        self, unit: TextUnit, token: Any, lower: str, spec: dict
    ) -> Signal | None:
        suffix = spec["suffix"]
        min_len = spec.get("min_word_length", 4)
        blocklist: set[str] = set(spec.get("blocklist", []))

        if not lower.endswith(suffix):
            return None
        if len(lower) < min_len:
            return None
        if lower in blocklist:
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
            payload={
                "suffix": suffix,
                "stem": lower[: -len(suffix)],
                "pos": token.pos_,
                "lemma": token.lemma_,
                "source": spec.get("source", ""),
            },
        )
