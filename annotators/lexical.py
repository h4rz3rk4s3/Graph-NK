"""
Module 3c — LexiconAnnotator (Milestone 4).

Detects lexical NK markers by matching lemmas from lexicons/en_core_v0.1.yml
against TextUnit text using spaCy's PhraseMatcher.

Design:
  - Rules are entirely data-driven (YAML).  No marker string appears in Python.
  - One Signal per match, pointing at the LexicalMarker via payload.
  - The projector creates the LexicalMarker node from Signal.payload.

Source: FRAMEWORK_DESIGN.md §5 Module 3c; BUILD_SPEC.md §6 Milestone 4.
Literature: Janich & Simon 2017; Müller & Stegmüller 2019; Simmerling & Janich 2015.
"""
from __future__ import annotations

import logging
from pathlib import Path

import spacy
import yaml
from spacy.matcher import PhraseMatcher

from annotators.base import Annotator, Signal, TextUnit
from settings import settings

logger = logging.getLogger(__name__)

_LEXICON_PATH = Path(__file__).parent.parent / "lexicons" / "en_core_v0.1.yml"


class LexiconAnnotator:
    """
    Matches lexical NK markers defined in lexicons/en_core_v0.1.yml.
    Implements the Annotator protocol.
    """
    name = "LexiconAnnotator"

    def __init__(self, lexicon_path: Path = _LEXICON_PATH) -> None:
        self._nlp = spacy.load(settings.spacy_model, disable=["ner", "parser"])
        self._lexicon = self._load_lexicon(lexicon_path)
        self._matcher, self._id_map = self._build_matcher()
        self.version = self._lexicon["version"]
        logger.info(
            "LexiconAnnotator loaded %d entries from %s (v%s)",
            len(self._lexicon["entries"]), lexicon_path.name, self.version
        )

    def annotate(self, unit: TextUnit) -> list[Signal]:
        if not unit.text:
            return []

        doc = self._nlp(unit.text)
        matches = self._matcher(doc)
        signals: list[Signal] = []

        for match_id, start, end in matches:
            entry_id = self._id_map[match_id]
            entry = self._entry_by_id(entry_id)
            span = doc[start:end]
            signals.append(Signal(
                text_unit_id=unit.text_unit_id,
                layer="lexical",
                category=entry["category"],
                subcategory=entry.get("subcategory"),
                surface_form=span.text,
                span_start=span.start_char,
                span_end=span.end_char,
                rule_id=f"lex.{entry['id']}",
                rule_version=self.version,
                payload={
                    "lexicon_version":  self.version,
                    "lemma":            entry["lemma"],
                    "pos":              entry.get("pos", ""),
                    "polarity":         entry.get("polarity", "neutral"),
                    "source_citation":  entry.get("source", ""),
                },
            ))

        return signals

    # ── private helpers ───────────────────────────────────────────────────────

    def _load_lexicon(self, path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_matcher(self) -> tuple[PhraseMatcher, dict[int, str]]:
        """
        Build a PhraseMatcher keyed on LEMMA.
        Multi-word phrases (e.g. 'blind spot') use multiple-token docs.
        Returns the matcher and a hash → entry_id reverse-lookup map.
        """
        matcher = PhraseMatcher(self._nlp.vocab, attr="LEMMA")
        id_map: dict[int, str] = {}

        for entry in self._lexicon.get("entries", []):
            entry_id = entry["id"]
            pattern_doc = self._nlp(entry["lemma"]) #make_doc
            key = f"LEX_{entry_id}"
            matcher.add(key, [pattern_doc])
            id_map[self._nlp.vocab.strings[key]] = entry_id

        return matcher, id_map

    def _entry_by_id(self, entry_id: str) -> dict:
        for e in self._lexicon["entries"]:
            if e["id"] == entry_id:
                return e
        raise KeyError(f"Lexicon entry not found: {entry_id}")
