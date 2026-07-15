"""
Module 3c — LexiconAnnotator (Milestone 4).

Detects lexical NK markers by matching lemmas from lexicons/en_core_v0.2.yml
against TextUnit text using spaCy's PhraseMatcher, POS-disambiguated.

Design:
  - Rules are entirely data-driven (YAML).  No marker string appears in Python.
  - One Signal per match, pointing at the LexicalMarker via payload.
  - The projector creates the LexicalMarker node from Signal.payload.

v0.2 (MARKER_REVIEW.md §3 point 2 — "disambiguate by POS + lemma... extend
it"): PhraseMatcher(attr="LEMMA") matches on lemma text alone; it cannot tell
"doubt" the noun from "doubt" the verb, so both "doubt_n" and "doubt_v"
entries fired on EVERY occurrence of "doubt" regardless of actual use. Every
match is now POST-FILTERED against the entry's declared `pos` (checked
against the matched span's root token), so an entry only fires when the
lexeme is genuinely used in that part of speech. Filtering is skipped for
"PHRASE" and "X" (abbreviation/register-specific) entries, where a single POS
label doesn't meaningfully apply to a multi-word span or a token spaCy's
tagger wasn't trained to classify (IIRC, AFAIK, TODO, etc.).

`requires_context` (v0.2, e.g. on "guess"/"suppose"/"confused") is ADVISORY
ONLY here — per lexicons/en_core_v0.2.yml's own header, it is enforced only
for the entries the morpho_syntactic annotator scopes via DependencyMatcher
(e.g. morph.hedge.shield_think for "I think/guess/suppose ..."). The lexical
layer deliberately still fires the bare cue in parallel — this mirrors the
existing, intentional 'blind spot' double-count (AGENTS.md §3.3): different
layers, different questions, never collapsed. requires_context is carried
through to the payload so it's visible in the graph for analysis.

Source: FRAMEWORK_DESIGN.md §5 Module 3c; BUILD_SPEC.md §6 Milestone 4.
Literature: Janich & Simon 2017; Müller & Stegmüller 2019; Simmerling & Janich
2015; Bongelli & Zuczkowski (KUB); Aikhenvald 2004; Hyland 2005; Channell 1994.
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

# POS values that do not correspond to a single-token spaCy tag, and are
# therefore never POS-filtered — a phrase spans multiple tokens (no single
# "root POS" that means "is this a match"), and "X" denotes register-specific
# abbreviations (IIRC, AFAIK, TODO...) that spaCy's tagger was not trained to
# classify reliably.
_NO_POS_FILTER = {"PHRASE", "X"}


def _default_lexicon_path() -> Path:
    v = settings.pattern_set_version
    return Path(__file__).parent.parent / "lexicons" / f"en_core_v{v}.yml"


class LexiconAnnotator:
    """
    Matches lexical NK markers defined in lexicons/en_core_v0.2.yml.
    Implements the Annotator protocol.
    """
    name = "LexiconAnnotator"

    def __init__(self, nlp, lexicon_path: Path | None = None) -> None:
        self._nlp = nlp
        lexicon_path = lexicon_path or _default_lexicon_path()
        self._lexicon = self._load_lexicon(lexicon_path)
        self._matcher, self._id_map = self._build_matcher()
        self.version = self._lexicon["version"]
        logger.info(
            "LexiconAnnotator loaded %d entries from %s (v%s)",
            len(self._lexicon["entries"]), lexicon_path.name, self.version
        )

    def annotate(self, unit: TextUnit, doc) -> list[Signal]:
        if not unit.text:
            return []

        matches = self._matcher(doc)
        signals: list[Signal] = []

        for match_id, start, end in matches:
            entry_id = self._id_map[match_id]
            entry = self._entry_by_id(entry_id)
            span = doc[start:end]

            declared_pos = entry.get("pos", "")
            if declared_pos not in _NO_POS_FILTER and span.root.pos_ != declared_pos:
                continue  # e.g. "doubt" used as VERB doesn't fire the NOUN entry

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
                weight=entry.get("weight"),
                status=entry.get("status", "active"),
                payload={
                    "lexicon_version":  self.version,
                    "lemma":            entry["lemma"],
                    "pos":              declared_pos,
                    "polarity":         entry.get("polarity", "neutral"),
                    "source_citation":  entry.get("source", ""),
                    "requires_context": entry.get("requires_context", ""),
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
        POS is NOT filtered here (PhraseMatcher has no per-pattern POS
        constraint) — it is checked post-match in annotate(), against
        span.root.pos_.
        Returns the matcher and a hash → entry_id reverse-lookup map.
        """
        matcher = PhraseMatcher(self._nlp.vocab, attr="LEMMA")
        id_map: dict[int, str] = {}

        for entry in self._lexicon.get("entries", []):
            entry_id = entry["id"]
            pattern_doc = self._nlp.make_doc(entry["lemma"])
            key = f"LEX_{entry_id}"
            matcher.add(key, [pattern_doc])
            id_map[self._nlp.vocab.strings[key]] = entry_id

        return matcher, id_map

    def _entry_by_id(self, entry_id: str) -> dict:
        for e in self._lexicon["entries"]:
            if e["id"] == entry_id:
                return e
        raise KeyError(f"Lexicon entry not found: {entry_id}")
