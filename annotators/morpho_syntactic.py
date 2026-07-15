"""
Module 3a — SpacyMorphoAnnotator (Milestone 5).

Detects morpho-syntactic NK signals using spaCy patterns loaded from
patterns/morpho_syntactic_v0.2.yml. Pattern content is entirely in YAML;
Python only wires the spaCy API.

v0.2 (MARKER_REVIEW.md): patterns now come in two kinds, selected per-rule by
an optional `type` field:
  - type absent, or type: "Matcher"      → spaCy token Matcher (v0.1 behaviour,
                                            unchanged — a bare cue, no scope).
  - type: "DependencyMatcher"            → spaCy DependencyMatcher. Pattern is
                                            a list of {RIGHT_ID, RIGHT_ATTRS}
                                            (+ LEFT_ID/REL_OP for all but the
                                            first node), i.e. spaCy's native
                                            DependencyMatcher pattern shape
                                            verbatim — no translation needed.
                                            Encodes SCOPE: the cue only fires
                                            in the stated grammatical relation
                                            (e.g. negation attached to a
                                            cognition verb with a 1st-person
                                            subject). This is the review's
                                            fix for the cue≠scope problem.
This is backward-compatible by construction: a pattern file with no `type`
fields (v0.1) is loaded entirely by the Matcher path.

REQUIRES the dependency parser (see annotators.base.make_nlp — parser is
enabled again as of v0.2, reversing part of the v0.5 speed decision).

Covered feature categories (FRAMEWORK_DESIGN.md §4.3, extended by v0.2):
  - negation:          scoped_epistemic, bare_negation (modifier), quantifier_no
  - modality:          epistemic (may/might/must/will), underspecified, deontic
  - hedging:           adverbial, approximator, plausibility_shield, attribution_shield
  - evidential:        inferential, reportative (new — M-3/C-6/C-7)
  - epistemic_verb:    not_knowing (new — M-1, DependencyMatcher)
  - tense:             past_nk, future_nk
  - syntactic_pattern: adversative (modifier), embedded_question, tag_question,
                       question_mark (modifier), question_answer (unit-level)

Literature:
  Negation     → Vincze et al. 2008; Morante & Sporleder 2012; Helmer 2016
  Modality     → Hyland 1998; Vold 2006; Morante & Sporleder 2012
  Hedging      → Lakoff 1973; Prince et al. 1982; Szarvas et al. 2012
  Evidentiality→ Aikhenvald 2004; San Roque et al. 2015
  Not-knowing  → Bongelli & Zuczkowski (KUB); Rubin 2007
  Tense        → Janich 2020
  Syntactic/Q  → Bongelli et al. 2018; San Roque et al. 2015
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import spacy
import yaml
from spacy.matcher import DependencyMatcher, Matcher

from annotators.base import Annotator, Signal, TextUnit
from settings import settings

logger = logging.getLogger(__name__)


def _default_pattern_path() -> Path:
    v = settings.pattern_set_version
    return Path(__file__).parent.parent / "patterns" / f"morpho_syntactic_v{v}.yml"


class SpacyMorphoAnnotator:
    """
    Loads Matcher + DependencyMatcher patterns from YAML and emits one Signal
    per match. Implements the Annotator protocol.
    """
    name = "SpacyMorphoAnnotator"

    def __init__(self, nlp, pattern_path: Path | None = None) -> None:
        self._nlp = nlp
        pattern_path = pattern_path or _default_pattern_path()
        self._pattern_data = self._load_patterns(pattern_path)
        self._matcher, self._meta = self._build_matcher()
        self._dep_matcher, self._dep_meta = self._build_dependency_matcher()
        self.version = self._pattern_data["version"]
        logger.info(
            "SpacyMorphoAnnotator loaded %d Matcher + %d DependencyMatcher "
            "patterns from %s (v%s)",
            len(self._meta), len(self._dep_meta), pattern_path.name, self.version,
        )

    def annotate(self, unit: TextUnit, doc) -> list[Signal]:
        if not unit.text:
            return []

        signals: list[Signal] = []

        # --- Matcher-based patterns (bare cue, no scope — v0.1 behaviour) ---
        for match_id, start, end in self._matcher(doc):
            meta = self._meta[match_id]
            span = doc[start:end]
            signals.append(Signal(
                text_unit_id=unit.text_unit_id,
                layer="morpho_syntactic",
                category=meta["category"],
                subcategory=meta.get("subcategory"),
                surface_form=span.text,
                span_start=span.start_char,
                span_end=span.end_char,
                rule_id=meta["id"],
                rule_version=self.version,
                weight=meta.get("weight"),
                status=meta.get("status", "active"),
                payload={"note": meta.get("note", "")},
            ))

        # --- DependencyMatcher patterns (scoped — v0.2, MARKER_REVIEW §4) ---
        if self._dep_matcher is not None and len(self._dep_meta):
            for match_id, token_ids in self._dep_matcher(doc):
                meta = self._dep_meta[match_id]
                # Span = the bounding range over every matched node, so the
                # surface_form captures the whole scoped construction (e.g.
                # subject + negation + verb), not just one token.
                lo, hi = min(token_ids), max(token_ids)
                span = doc[lo : hi + 1]
                signals.append(Signal(
                    text_unit_id=unit.text_unit_id,
                    layer="morpho_syntactic",
                    category=meta["category"],
                    subcategory=meta.get("subcategory"),
                    surface_form=span.text,
                    span_start=span.start_char,
                    span_end=span.end_char,
                    rule_id=meta["id"],
                    rule_version=self.version,
                    weight=meta.get("weight"),
                    status=meta.get("status", "active"),
                    payload={"note": meta.get("note", ""), "matcher": "dependency"},
                ))

        # --- Question-answer syntactic pattern (not expressible in one Matcher rule) ---
        signals.extend(self._detect_question_answer(unit, doc))

        return signals

    # ── private helpers ───────────────────────────────────────────────────────

    def _load_patterns(self, path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_matcher(self) -> tuple[Matcher, dict[int, dict]]:
        """
        Compile every pattern WITHOUT type: "DependencyMatcher" (i.e. type
        absent, or explicitly "Matcher") into a spaCy token Matcher — the
        v0.1 behaviour, unchanged.
        """
        matcher = Matcher(self._nlp.vocab)
        meta: dict[int, dict] = {}

        for p in self._pattern_data.get("patterns", []):
            if p.get("type") == "DependencyMatcher":
                continue  # handled by _build_dependency_matcher
            pattern_id = p["id"]
            try:
                matcher.add(pattern_id, [p["pattern"]])
            except Exception as exc:
                logger.error("Skipping malformed Matcher pattern '%s': %s", pattern_id, exc)
                continue
            meta[self._nlp.vocab.strings[pattern_id]] = p

        return matcher, meta

    def _build_dependency_matcher(self) -> tuple[DependencyMatcher | None, dict[int, dict]]:
        """
        Compile every pattern with type: "DependencyMatcher" into a spaCy
        DependencyMatcher. The YAML pattern shape (RIGHT_ID/RIGHT_ATTRS/
        LEFT_ID/REL_OP) is spaCy's own DependencyMatcher pattern format
        verbatim — no translation needed, just validation and loading.

        A malformed pattern (e.g. bad REL_OP, dangling LEFT_ID reference) is
        logged and skipped rather than crashing annotator startup — one bad
        rule should not take down the whole layer (same philosophy as the
        Matcher path above).
        """
        dep_patterns = [p for p in self._pattern_data.get("patterns", []) if p.get("type") == "DependencyMatcher"]
        if not dep_patterns:
            return None, {}

        matcher = DependencyMatcher(self._nlp.vocab)
        meta: dict[int, dict] = {}
        for p in dep_patterns:
            pattern_id = p["id"]
            try:
                matcher.add(pattern_id, [p["pattern"]])
            except Exception as exc:
                logger.error("Skipping malformed DependencyMatcher pattern '%s': %s", pattern_id, exc)
                continue
            meta[self._nlp.vocab.strings[pattern_id]] = p

        return matcher, meta

    def _detect_question_answer(self, unit: TextUnit, doc: Any) -> list[Signal]:
        """
        Detects question-answer structures: a TextUnit that contains both a
        '?'-terminated sentence and at least one declarative sentence.
        This co-presence signals epistemic Q&A dynamics (Bongelli et al. 2018).

        Emits at most one Signal per TextUnit (unit-level, not token-level).
        """
        sents = list(doc.sents)
        has_question    = any("?" in s.text for s in sents)
        has_declarative = any("?" not in s.text and s.text.strip() for s in sents)

        if has_question and has_declarative:
            return [Signal(
                text_unit_id=unit.text_unit_id,
                layer="morpho_syntactic",
                category="syntactic_pattern",
                subcategory="question_answer",
                surface_form="",          # unit-level signal, no single span
                span_start=0,
                span_end=len(unit.text),
                rule_id="morph.syn.question_answer",
                rule_version=self.version,
                weight=0.5,
                status="active",
                payload={"source": "Bongelli et al. 2018; Spranz-Fogasy 2014"},
            )]
        return []
