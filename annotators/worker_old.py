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
    Reads stream_units to exhaustion, annotates each TextUnit with all
    annotators, publishes Signals to stream_signals.
    """
    broker = await get_broker()
    annotators = _load_annotators()

    # Separate the classifier for batch processing
    from annotators.classifier import ClassifierAnnotator
    clf_annotators = [a for a in annotators if isinstance(a, ClassifierAnnotator)]
    rule_annotators = [a for a in annotators if not isinstance(a, ClassifierAnnotator)]

    logger.info("Annotator worker started. Consuming %s", settings.stream_units)

    # Buffer for classifier batching
    unit_buffer: list[TextUnit] = []

    async def flush_classifier_buffer() -> None:
        if not unit_buffer or not clf_annotators:
            return
        for clf in clf_annotators:
            try:
                signals = clf.batch_annotate(unit_buffer)
                for sig in signals:
                    await _publish_signal(broker, sig)
            except Exception as exc:
                logger.error("ClassifierAnnotator batch failed: %s", exc)
        unit_buffer.clear()

    async for batch in broker.read_all(settings.stream_units):
        for event in batch:
            unit = _event_to_text_unit(event)
            if unit is None:
                continue

            # Rule-based annotators — synchronous, one unit at a time
            for ann in rule_annotators:
                try:
                    for sig in ann.annotate(unit):
                        await _publish_signal(broker, sig)
                except Exception as exc:
                    logger.error(
                        "Annotator %s failed on %s: %s", ann.name, unit.text_unit_id, exc
                    )

            # Buffer for classifier batch
            unit_buffer.append(unit)
            if len(unit_buffer) >= settings.annotator_batch_size:
                await flush_classifier_buffer()

    # Flush any remaining buffered units
    await flush_classifier_buffer()
    logger.info("Annotator worker finished.")


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
