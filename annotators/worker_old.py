"""
Annotator Worker — fan-out coordinator (Milestones 4–8).

Consumes TextUnit events from stream_units, runs all registered annotators,
and publishes each Signal to stream_signals.

Architecture:
  - Annotators are registered in ANNOTATORS list at the bottom of this module.
  - The ClassifierAnnotator uses batch_annotate() for throughput; all others
    are called one unit at a time (CPU-bound, fast enough at research scale).
  - No annotator error can block the others — each is wrapped in try/except
    and failures are logged with enough context to reproduce.

See FRAMEWORK_DESIGN.md §3.1 (fan-out rationale); BUILD_SPEC.md §6 M4–M8.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import Any

from annotators.base import Signal, TextUnit
from broker import get_broker
from settings import settings
from progress import Progress

logger = logging.getLogger(__name__)


def _load_annotators() -> list[Any]:
    """
    Lazily imports and instantiates all annotators.
    ClassifierAnnotator is excluded if no model path is configured.
    Import errors are caught per-annotator so a missing spaCy model doesn't
    silently kill the whole worker.
    """
    annotators = []

    try:
        from annotators.lexical import LexiconAnnotator
        annotators.append(LexiconAnnotator())
    except Exception as exc:
        logger.error("Could not load LexiconAnnotator: %s", exc)

    try:
        from annotators.morpho_syntactic import SpacyMorphoAnnotator
        annotators.append(SpacyMorphoAnnotator())
    except Exception as exc:
        logger.error("Could not load SpacyMorphoAnnotator: %s", exc)

    try:
        from annotators.word_formation import AffixAnnotator
        annotators.append(AffixAnnotator())
    except Exception as exc:
        logger.error("Could not load AffixAnnotator: %s", exc)

    try:
        from annotators.rhetorical import RhetoricalAnnotator
        annotators.append(RhetoricalAnnotator())
    except Exception as exc:
        logger.error("Could not load RhetoricalAnnotator: %s", exc)

    try:
        from annotators.classifier import ClassifierAnnotator
        import os
        if os.path.isdir(settings.classifier_model_path):
            annotators.append(ClassifierAnnotator())
        else:
            logger.warning(
                "Classifier model not found at '%s'. Skipping ClassifierAnnotator.",
                settings.classifier_model_path,
            )
    except Exception as exc:
        logger.error("Could not load ClassifierAnnotator: %s", exc)

    logger.info("Annotator worker: %d annotators loaded.", len(annotators))
    return annotators


async def run_annotator_worker() -> None:
    """
    Main entry point for the annotator worker.

    Reads TextUnits from Neo4j (where the projector persisted them in stage 1),
    annotates each with all annotators, and publishes Signals to stream_signals.

    Why Neo4j and not stream_units: stream_units is now drained and trimmed by
    the projector in stage 1, so it is empty by stage 2. Reading TextUnits from
    Neo4j makes stream_units a single-consumer stream that can be safely trimmed,
    which is what keeps Redis memory bounded on large backlogs.
    See CHANGELOG 2026-06-02. Annotators only use `text` and `text_unit_id`.
    """
    from neo4j import AsyncGraphDatabase

    broker = await get_broker()
    annotators = _load_annotators()

    from annotators.classifier import ClassifierAnnotator
    clf_annotators = [a for a in annotators if isinstance(a, ClassifierAnnotator)]
    rule_annotators = [a for a in annotators if not isinstance(a, ClassifierAnnotator)]

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )

    # Exact total for an accurate ETA: stage 1 already created every TextUnit.
    async with driver.session() as session:
        res = await session.run("MATCH (u:TextUnit) RETURN count(u) AS n")
        rec = await res.single()
        total_units = rec["n"] if rec else 0
    prog = Progress("Annotate", total=total_units)
    logger.info("Annotator worker started. Reading %d TextUnits from Neo4j.", total_units)

    unit_buffer: list[TextUnit] = []

    async def flush_classifier_buffer() -> None:
        if not unit_buffer or not clf_annotators:
            unit_buffer.clear()
            return
        for clf in clf_annotators:
            try:
                for sig in clf.batch_annotate(unit_buffer):
                    await _publish_signal(broker, sig)
            except Exception as exc:
                logger.error("ClassifierAnnotator batch failed: %s", exc)
        unit_buffer.clear()

    total = 0
    try:
        async for unit in _iter_text_units(driver, page_size=settings.annotator_batch_size * 10):
            # Rule-based annotators — synchronous, one unit at a time
            for ann in rule_annotators:
                try:
                    for sig in ann.annotate(unit):
                        await _publish_signal(broker, sig)
                except Exception as exc:
                    logger.error("Annotator %s failed on %s: %s", ann.name, unit.text_unit_id, exc)

            unit_buffer.append(unit)
            if len(unit_buffer) >= settings.annotator_batch_size:
                await flush_classifier_buffer()
            total += 1
            prog.add(1)
            prog.maybe_log()

        await flush_classifier_buffer()
    finally:
        await driver.close()

    prog.finish()
    logger.info("Annotator worker finished. Annotated %d TextUnits.", total)


async def _iter_text_units(driver: Any, page_size: int = 500):
    """
    Stream all TextUnits from Neo4j using keyset pagination on the unique `id`.
    Keyset (WHERE id > last) is O(log n) per page, unlike SKIP which is O(n).
    Yields minimal TextUnit objects — only `text` and `text_unit_id` are used by
    annotators, so the other fields are filled with harmless placeholders.
    """
    last_id = ""
    while True:
        async with driver.session() as session:
            result = await session.run(
                """
                MATCH (u:TextUnit)
                WHERE u.id > $last_id
                RETURN u.id AS id, u.text AS text
                ORDER BY u.id
                LIMIT $limit
                """,
                last_id=last_id, limit=page_size,
            )
            rows = [(r["id"], r["text"]) async for r in result]

        if not rows:
            return

        for tu_id, text in rows:
            yield TextUnit(
                text_unit_id=tu_id, parent_id="", parent_type="", repo="",
                parent_number=None, role="", position=0, text=text or "",
                lang=None, token_count=0, sha256="", author_login=None, created_at=None,
            )
        last_id = rows[-1][0]


async def _publish_signal(broker: Any, sig: Signal) -> None:
    """Serialise a Signal and publish it to stream_signals."""
    payload = {
        "signal_id":     sig.signal_id,
        "text_unit_id":  sig.text_unit_id,
        "layer":         sig.layer,
        "category":      sig.category,
        "subcategory":   sig.subcategory,
        "surface_form":  sig.surface_form,
        "span_start":    sig.span_start,
        "span_end":      sig.span_end,
        "rule_id":       sig.rule_id,
        "rule_version":  sig.rule_version,
        "confidence":    sig.confidence,
        "payload":       sig.payload,
    }
    await broker.publish(settings.stream_signals, payload)


def _event_to_text_unit(event: dict[str, Any]) -> TextUnit | None:
    """Reconstruct a TextUnit from the stream_units event dict."""
    from annotators.base import TextUnit as TU
    try:
        return TU(
            text_unit_id  = event["text_unit_id"],
            parent_id     = event["parent_id"],
            parent_type   = event["parent_type"],
            repo          = event["repo"],
            parent_number = event.get("parent_number"),
            role          = event["role"],
            position      = event["position"],
            text          = event["text"],
            lang          = event.get("lang"),
            token_count   = event.get("token_count", 0),
            sha256        = event.get("sha256", ""),
            author_login  = event.get("author_login"),
            created_at    = event.get("created_at"),
        )
    except KeyError as exc:
        logger.warning("Malformed TextUnit event, missing field %s. Skipping.", exc)
        return None
