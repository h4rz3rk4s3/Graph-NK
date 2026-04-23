"""
Module 3d — RhetoricalAnnotator (Milestone 8).

Detects rhetorical NK figures (metaphor, comparison, personification) using
spaCy Matcher patterns from patterns/rhetorical_v0.1.yml.

Each match emits one Signal plus payload data for the INSTANTIATES edge to
a RhetoricalFigure node. The projector handles the node MERGE.

Known double-counting with LexiconAnnotator (e.g. 'blind spot' matches both
lex.blind_spot and rhetor.metaphor.visibility.blind_spot) is INTENTIONAL —
the two Signals carry different categorical meanings. See AGENTS.md §3.3.

Literature: Simmerling & Janich 2015; Smithson 2008.
See FRAMEWORK_DESIGN.md §5 Module 3d; BUILD_SPEC.md §6 Milestone 8.
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

_PATTERN_PATH = Path(__file__).parent.parent / "patterns" / "rhetorical_v0.1.yml"


class RhetoricalAnnotator:
    """
    Pattern-driven rhetorical figure detector.
    Implements the Annotator protocol.
    """
    name = "RhetoricalAnnotator"

    def __init__(self, pattern_path: Path = _PATTERN_PATH) -> None:
        self._nlp = spacy.load(settings.spacy_model, disable=["ner"])
        self._figure_data = self._load_figures(pattern_path)
        self._matcher, self._meta = self._build_matcher()
        self.version = self._figure_data["version"]
        logger.info(
            "RhetoricalAnnotator loaded %d figures (v%s)",
            len(self._figure_data["figures"]), self.version,
        )

    def annotate(self, unit: TextUnit) -> list[Signal]:
        if not unit.text:
            return []

        doc = self._nlp(unit.text)
        signals: list[Signal] = []

        for match_id, start, end in self._matcher(doc):
            figure = self._meta[match_id]
            span = doc[start:end]
            signals.append(Signal(
                text_unit_id=unit.text_unit_id,
                layer="rhetorical",
                category=figure["family"],
                subcategory=figure.get("subtype"),
                surface_form=span.text,
                span_start=span.start_char,
                span_end=span.end_char,
                rule_id=figure["rule_id"],
                rule_version=self.version,
                payload={
                    # Projector reads these to MERGE the RhetoricalFigure node
                    "figure_id":       figure["figure_id"],
                    "family":          figure["family"],
                    "subtype":         figure.get("subtype", ""),
                    "description":     figure.get("description", ""),
                    "source_citation": figure.get("source", ""),
                },
            ))

        return signals

    # ── private helpers ───────────────────────────────────────────────────────

    def _load_figures(self, path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_matcher(self) -> tuple[Matcher, dict[int, dict]]:
        """
        Each figure can have multiple alternative patterns.
        All alternatives for a figure share the same match key so they map to
        the same figure metadata.
        """
        matcher = Matcher(self._nlp.vocab)
        meta: dict[int, dict] = {}

        for figure in self._figure_data.get("figures", []):
            key = figure["figure_id"]
            # Each entry in "patterns" is a list of token dicts (one alternative)
            spacy_patterns = [p for p in figure.get("patterns", [])]
            if spacy_patterns:
                matcher.add(key, spacy_patterns)
                meta[self._nlp.vocab.strings[key]] = figure

        return matcher, meta
