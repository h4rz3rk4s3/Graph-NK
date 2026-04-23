"""
Module 3a — SpacyMorphoAnnotator (Milestone 5).

Detects morpho-syntactic NK signals using spaCy Matcher patterns loaded from
patterns/morpho_syntactic_v0.1.yml.  Pattern content is entirely in YAML;
Python only wires the spaCy API.

Covered feature categories (FRAMEWORK_DESIGN.md §4.3):
  - negation:          adverbial_not, contraction_nt, temporal_never, quantifier_no
  - modality:          epistemic, deontic, quasi_modal
  - hedging:           adverbial, approximator
  - tense:             past_nk, present_nk, future_nk (temporal constructions)
  - syntactic_pattern: adversative, question_answer

Literature:
  Negation  → Vincze et al. 2008; Helmer et al. 2016
  Modality  → Hyland 1998; Vold 2006; Marshman 2008
  Hedging   → Szarvas et al. 2012
  Tense     → Janich 2020
  Syntactic → Bongelli et al. 2018; Simon 2020; Spranz-Fogasy 2014
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import spacy
import yaml
from spacy.matcher import Matcher

from annotators.base import Annotator, Signal, TextUnit
from settings import settings

logger = logging.getLogger(__name__)

_PATTERN_PATH = Path(__file__).parent.parent / "patterns" / "morpho_syntactic_v0.1.yml"


class SpacyMorphoAnnotator:
    """
    Loads Matcher patterns from YAML and emits one Signal per match.
    Implements the Annotator protocol.
    """
    name = "SpacyMorphoAnnotator"

    def __init__(self, pattern_path: Path = _PATTERN_PATH) -> None:
        # disable=["ner"] — we don't need NER; keep parser for dep-based work later
        self._nlp = spacy.load(settings.spacy_model, disable=["ner"])
        self._pattern_data = self._load_patterns(pattern_path)
        self._matcher, self._meta = self._build_matcher()
        self.version = self._pattern_data["version"]
        logger.info(
            "SpacyMorphoAnnotator loaded %d patterns (v%s)",
            len(self._pattern_data["patterns"]), self.version,
        )

    def annotate(self, unit: TextUnit) -> list[Signal]:
        if not unit.text:
            return []

        doc = self._nlp(unit.text)
        signals: list[Signal] = []

        # --- Matcher-based patterns ---
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
                payload={"note": meta.get("note", "")},
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
        Compile YAML pattern specs into a spaCy Matcher.
        Returns the matcher and a hash → metadata reverse-lookup.
        """
        matcher = Matcher(self._nlp.vocab)
        meta: dict[int, dict] = {}

        for p in self._pattern_data.get("patterns", []):
            pattern_id = p["id"]
            spacy_pattern = self._yaml_pattern_to_spacy(p["pattern"])
            matcher.add(pattern_id, [spacy_pattern])
            meta[self._nlp.vocab.strings[pattern_id]] = p

        return matcher, meta

    def _yaml_pattern_to_spacy(self, pattern: list[dict]) -> list[dict]:
        """
        YAML uses plain dicts; spaCy's Matcher expects the same structure.
        This is a passthrough — keeping it explicit so it can be extended.
        """
        return pattern  # type: ignore[return-value]

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
                payload={"source": "Bongelli et al. 2018; Spranz-Fogasy 2014"},
            )]
        return []
