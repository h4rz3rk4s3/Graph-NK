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
    All annotators implement this protocol.
    annotate() is synchronous — annotation is CPU-bound.
    I/O (model loading) happens at construction time, not per call.
    See BUILD_SPEC.md §5.1.
    """
    name: str
    version: str

    def annotate(self, unit: TextUnit) -> list[Signal]:
        """Return all Signals detected in unit. Never raise — return [] on failure."""
        ...
