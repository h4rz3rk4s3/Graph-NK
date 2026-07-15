"""
Annotator base types — TextUnit, Signal, and the Annotator protocol.

All annotators implement Annotator. All emitted evidence is a Signal.
See FRAMEWORK_DESIGN.md §1.2 and BUILD_SPEC.md §5.1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class TextUnit:
    """
    Mirrors the stream_units event shape exactly.
    Populated by extractor.worker and passed to every annotator.
    See BUILD_SPEC.md §4.2 for the canonical field list.
    """
    text_unit_id:  str
    parent_id:     str
    parent_type:   str          # issue | pull_request | commit
    repo:          str
    parent_number: int | None
    role:          str          # title | body | commit_message | comment_body
    position:      int
    text:          str
    lang:          str | None
    token_count:   int
    sha256:        str
    author_login:  str | None
    created_at:    str | None


@dataclass
class Signal:
    """
    A single, provenance-carrying piece of NK evidence.

    Rules (AGENTS.md §3.2–3.3):
      - rule_id and rule_version are MANDATORY — no signal without them.
      - Signals are never collapsed or filtered by the annotator.
      - The classifier emits Signal + ClassifierVerdict (two separate records).

    signal_id is computed deterministically from (text_unit_id, rule_id, span_start)
    to make MERGE idempotent in Neo4j.
    """
    text_unit_id: str
    layer:        str            # lexical | morpho_syntactic | word_formation | rhetorical | classifier
    category:     str
    subcategory:  str | None
    surface_form: str
    span_start:   int
    span_end:     int
    rule_id:      str
    rule_version: str
    confidence:   float | None = None
    payload:      dict[str, Any] = field(default_factory=dict)

    # v0.2 (MARKER_REVIEW.md): analysis-time confidence + lifecycle metadata.
    # weight  — float [0,1], a rule's provisional confidence. Optional; None
    #           means "not yet assessed." Ingest NEVER filters on this — every
    #           Signal is written regardless of weight (signal pluralism,
    #           AGENTS.md §3.2). Weight is for analysis-time scoring only.
    # status  — "active" | "candidate". "candidate" rules are still ingested
    #           (kept in the graph with full provenance) but are conventionally
    #           excluded from headline counts until empirically calibrated
    #           (MARKER_REVIEW §3.5 — deferred; this field just carries the
    #           label, no filtering logic is implemented yet).
    weight:       float | None = None
    status:       str = "active"

    # Sentinel flags used by the projector to route to specialised MERGEs.
    # Do not set these directly — use the class methods below.
    _is_verdict: bool = field(default=False, repr=False)

    @property
    def signal_id(self) -> str:
        """Stable, unique identifier. Used as the Neo4j natural key."""
        return f"{self.text_unit_id}::{self.rule_id}::{self.span_start}"

    def as_verdict(self) -> "Signal":
        """
        Return a copy flagged as a ClassifierVerdict event.
        Used by ClassifierAnnotator — see BUILD_SPEC.md §4.4.
        """
        import copy
        v = copy.copy(self)
        object.__setattr__(v, "_is_verdict", True)
        return v


@runtime_checkable
class Annotator(Protocol):
    """
    All rule-based annotators implement this protocol.

    annotate() receives the TextUnit AND a pre-parsed spaCy Doc, so the text is
    parsed exactly once per unit (by the worker, via nlp.pipe) and shared across
    all annotators — instead of each annotator re-parsing. This is the main v0.5
    speed change. See CHANGELOG 2026-06-04.

    annotate() is synchronous — annotation is CPU-bound. Matchers are built at
    construction time against the shared nlp.vocab.
    """
    name: str
    version: str

    def annotate(self, unit: TextUnit, doc: Any) -> list[Signal]:
        """Return all Signals detected in unit. Never raise — return [] on failure."""
        ...


def make_nlp(model: str | None = None):
    """
    Build the single shared spaCy pipeline used by all rule annotators.

    v0.2 CHANGE (MARKER_REVIEW.md — reverses part of the v0.5 speed decision):
    the dependency PARSER IS NOW ENABLED. v0.2's morpho_syntactic patterns use
    spaCy's DependencyMatcher to encode grammatical SCOPE (e.g. "negation must
    attach to a cognition verb with a 1st-person subject" — see
    morph.epi.neg_cognition), which is the core fix for the cue≠scope problem
    the review identifies. DependencyMatcher requires token.dep_/token.head,
    which only the parser populates — there is no way around this.

    Cost: this undoes v0.5's single biggest per-document speed-up ("Disabling
    the parser is the single biggest per-document speed-up after sharing the
    parse" — no longer true as of v0.2). Expect a real throughput hit. NER
    stays disabled (nothing uses it). If a future run genuinely doesn't need
    any DependencyMatcher rule (e.g. only v0.1 patterns are loaded), pass
    disable=["parser","ner"] explicitly to this function to get the old speed
    back — but that is now a deliberate opt-out, not the default.

    A fast rule-based `sentencizer` is added regardless (used by the
    question/answer check); it does not depend on the parser.

    `en_core_web_sm` is recommended over `lg` — we never use word vectors, and
    sm loads faster and uses less memory with negligible POS/lemma quality
    loss. The parser IS present in sm (only vectors/word-similarity are
    weaker in sm vs lg — dependency parse quality is comparable).
    """
    import spacy

    from settings import settings

    model = model or settings.spacy_model
    nlp = spacy.load(model, disable=["ner"])
    # Sentence boundaries: the parser (now enabled) supplies doc.sents
    # directly. The sentencizer fallback is only needed if a caller opts out
    # of the parser via an explicit disable=[...] override.
    if "parser" not in nlp.pipe_names and "senter" not in nlp.pipe_names \
            and "sentencizer" not in nlp.pipe_names:
        nlp.add_pipe("sentencizer")
    return nlp
