#!/usr/bin/env python3
"""
scripts/smoke_annotate.py

Run one rule annotator (or all four) on a single string and print one line
per Signal. This is the fast iteration loop for lexicon/pattern changes —
what AGENTS.md §6 calls "a change you cannot run is a change that has not
happened." It needs no MongoDB/Redis/Neo4j; only spaCy + the annotated YAML.

Usage:
    python scripts/smoke_annotate.py --text "I'm not sure about the root cause."
    python scripts/smoke_annotate.py --text "we can't reproduce this flaky failure" --annotator all
    echo "blind spot here" | python scripts/smoke_annotate.py --annotator rhetor
    python scripts/smoke_annotate.py --text "..." --annotator classifier   # loads HF model (slow)

Output: one line per Signal:
    <rule_id>  <layer>/<category>/<subcategory>  "<surface_form>"  [start:end]  weight=<w>  status=<s>

The classifier performs whole-unit classification; its "surface_form" is shown
empty and its span is the full unit, matching BUILD_SPEC.md §4.4.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from annotators.base import make_nlp, TextUnit


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--text", default=None, help="String to annotate (else read stdin).")
    p.add_argument(
        "--annotator",
        default="all",
        choices=["lex", "morpho", "rhetor", "affix", "classifier", "all"],
        help="Which annotator to run. Default: all rule-based (no classifier).",
    )
    p.add_argument("--unit-id", default="smoke:repo:1:body", help="Stable TextUnit id for the signal.")
    p.add_argument("--role", default="body", help="TextUnit role (title/body/commit_message/comment_body).")
    p.add_argument("--lang", default="en", help="TextUnit language tag.")
    return p.parse_args()


def _make_unit(text: str, args: argparse.Namespace) -> TextUnit:
    """Build the smallest TextUnit that matches the stream_units shape."""
    return TextUnit(
        text_unit_id=args.unit_id,
        parent_id="smoke:repo:1",
        parent_type="issue",
        repo="smoke/repo",
        parent_number=1,
        role=args.role,
        position=1,
        text=text,
        lang=args.lang,
        token_count=len(text.split()),
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        author_login=None,
        created_at=None,
    )


def _load_annotators(nlp, which: str) -> list[tuple[str, object]]:
    from annotators.lexical import LexiconAnnotator
    from annotators.morpho_syntactic import SpacyMorphoAnnotator
    from annotators.rhetorical import RhetoricalAnnotator
    from annotators.word_formation import AffixAnnotator

    registry: list[tuple[str, object]] = [
        ("lex", LexiconAnnotator(nlp)),
        ("morpho", SpacyMorphoAnnotator(nlp)),
        ("rhetor", RhetoricalAnnotator(nlp)),
        ("affix", AffixAnnotator(nlp)),
    ]
    if which == "all":
        return registry
    if which == "classifier":
        from annotators.classifier import ClassifierAnnotator, HFTransformersClassifier
        from settings import settings

        clf = HFTransformersClassifier(settings.classifier_model_path, device=settings.classifier_device)
        return [("classifier", ClassifierAnnotator(clf))]
    return [entry for key, entry in registry if key == which]


def _print_signal(sig) -> None:
    span = f"[{sig.span_start}:{sig.span_end}]"
    weight = f"weight={sig.weight}" if sig.weight is not None else "weight=None"
    print(
        f"{sig.rule_id}  {sig.layer}/{sig.category}/{sig.subcategory or '-'}  "
        f"{sig.surface_form!r}  {span}  {weight}  status={sig.status}"
    )


def main() -> None:
    args = _parse_args()
    text = args.text if args.text is not None else sys.stdin.read().strip()
    if not text:
        print("error: empty text (pass --text or pipe stdin)", file=sys.stderr)
        raise SystemExit(2)

    nlp = make_nlp()
    unit = _make_unit(text, args)
    doc = nlp(text)
    annotators = _load_annotators(nlp, args.annotator)

    print(f"# {args.annotator} on {unit.text!r}")
    total = 0
    for name, ann in annotators:
        # Rule annotators share the parsed Doc (annotate(unit, doc)); the
        # classifier does whole-unit inference and takes only the unit.
        if name == "classifier":
            signals = ann.annotate(unit)
        else:
            signals = ann.annotate(unit, doc)
        total += len(signals)
        for sig in signals:
            if sig.layer == "classifier":
                print(
                    f"{sig.rule_id}  classifier/{sig.payload.get('label', '?')}  "
                    f"conf={sig.confidence:.3f}  status={sig.status}"
                )
                continue
            _print_signal(sig)
    print(f"# total: {total} signal(s)")


if __name__ == "__main__":
    main()