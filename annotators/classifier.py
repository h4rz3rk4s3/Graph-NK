"""
Module 3e — ClassifierAnnotator (Milestone 6).

Wraps the trained RoBERTa NK classifier behind the Annotator protocol.
Emits two records per TextUnit (see BUILD_SPEC.md §4.4):
  1. A Signal (layer='classifier') — so the classifier appears in all
     cross-layer queries alongside rule-based signals.
  2. A ClassifierVerdict sentinel — routed by the projector to the
     ClassifierVerdict MERGE template.

Backend: HuggingFace Transformers, device='mps' (Apple Silicon) by default.
Fallback: CPU if MPS is unavailable. The NKClassifier protocol allows a
future MLX backend to be dropped in without changing this class.

See FRAMEWORK_DESIGN.md §5 Module 3e; BUILD_SPEC.md §6 Milestone 6.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from annotators.base import Annotator, Signal, TextUnit
from settings import settings

logger = logging.getLogger(__name__)

_MAX_TOKENS = 512


@runtime_checkable
class NKClassifier(Protocol):
    """
    Backend protocol — see BUILD_SPEC.md §5.2.
    predict() is synchronous; batch size is managed by the caller.
    """
    model_id:      str
    model_version: str

    def predict(self, texts: list[str]) -> list[tuple[int, float]]:
        """Returns (label, confidence) pairs in the same order as texts."""
        ...


class HFTransformersClassifier:
    """
    MPS-backed HuggingFace Transformers implementation of NKClassifier.
    Falls back to CPU if MPS is unavailable.
    """

    def __init__(self, model_path: str, device: str | None = None) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if device is None:
            device = settings.classifier_device

        # Device fallback: MPS → CPU
        if device == "mps" and not torch.backends.mps.is_available():
            logger.warning("MPS requested but not available. Falling back to CPU.")
            device = "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA requested but not available. Falling back to CPU.")
            device = "cpu"

        self._device = device
        self._torch = torch

        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = (
            AutoModelForSequenceClassification
            .from_pretrained(model_path)
            .to(device)
            .eval()
        )

        self.model_id = str(Path(model_path).name)
        self.model_version = self.model_id
        logger.info(
            "HFTransformersClassifier loaded '%s' on device='%s'",
            self.model_id, self._device,
        )

    def predict(self, texts: list[str]) -> list[tuple[int, float]]:
        import torch
        with torch.no_grad():
            enc = self._tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=_MAX_TOKENS,
                return_tensors="pt",
            ).to(self._device)
            logits = self._model(**enc).logits
            probs = logits.softmax(dim=-1)
            return [(int(p.argmax()), float(p.max())) for p in probs]


class ClassifierAnnotator:
    """
    Wraps an NKClassifier as an Annotator.
    Supports batch_annotate() for throughput; single annotate() for interface compat.
    """
    name = "ClassifierAnnotator"
    version = "0.1"

    def __init__(self, classifier: NKClassifier | None = None) -> None:
        if classifier is None:
            classifier = HFTransformersClassifier(settings.classifier_model_path)
        self._clf = classifier

    def annotate(self, unit: TextUnit) -> list[Signal]:
        return self.batch_annotate([unit])

    def batch_annotate(self, units: list[TextUnit]) -> list[Signal]:
        """
        Classify a batch of TextUnits. Emits Signal + Verdict for each.
        Caller should batch for throughput (see annotators/worker.py).
        """
        texts = [u.text for u in units]
        predictions = self._clf.predict(texts)
        signals: list[Signal] = []

        for unit, (label, confidence) in zip(units, predictions):
            # 1. The classifier Signal — participates in cross-layer queries
            clf_signal = Signal(
                text_unit_id=unit.text_unit_id,
                layer="classifier",
                category="roberta_binary",
                subcategory=None,
                surface_form="",               # whole-unit; no token span
                span_start=0,
                span_end=len(unit.text),
                rule_id="clf.roberta_binary",
                rule_version=self._clf.model_version,
                confidence=confidence,
                payload={
                    "label":         label,
                    "model_id":      self._clf.model_id,
                    "model_version": self._clf.model_version,
                },
            )
            signals.append(clf_signal)

            # 2. The ClassifierVerdict sentinel — routed by projector to verdict MERGE
            verdict = Signal(
                text_unit_id=unit.text_unit_id,
                layer="classifier",
                category="roberta_binary",
                subcategory=None,
                surface_form="",
                span_start=0,
                span_end=len(unit.text),
                rule_id="clf.roberta_binary",
                rule_version=self._clf.model_version,
                confidence=confidence,
                payload={
                    "label":         label,
                    "model_id":      self._clf.model_id,
                    "model_version": self._clf.model_version,
                    "__verdict__":   True,
                },
            )
            signals.append(verdict)

        return signals
