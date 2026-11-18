"""
Stack Overflow emotion gold-standard Ingester (v0.8).

Novielli, Calefato, Lambile, "A Gold Standard for Emotion Annotation in Stack
Overflow", MSR 2018. Local file:
  /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/Emotions_GoldSandard_andAnnotation.xlsx

The workbook has SIX sheets named <Emotion>_all (Love, Joy, Surprise, Anger,
Sadness, Fear), each holding the SAME ~4,800 SO comment/question text rows with
per-emotion rater labels (columns: Group, Set, <idx>, Text, rater 1..3,
Gold Label).

SCOPE (agreed with the researcher): we ingest ONLY the post text. Emotion
labels, rater columns, and gold labels are explicitly OUT OF SCOPE and are not
imported into the NK ontology (they would conflate SocialQA emotion annotation
with GraphRAG-NK's own linguistic evidence). The same physical text appears in
all six sheets, so we emit it ONCE per unique normalized text; the first
sheet/row that contains it is recorded as source metadata.

This is an annotated sample, not a full SO dump: there is NO post id and NO
post type (question vs answer vs comment) in the workbook. We therefore tag
every record with the neutral post_type "text" (the projector maps it to a
generic :StackOverflowPost node) and note the limitation in metadata.

DEPENDENCY: openpyxl (added to pyproject [project.optional-dependencies] dev /
main as needed for this single ingester).

Usage:
    python -m miner.stackoverflow_ingester [--path <xlsx>] [--max N] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
from collections.abc import Iterator
from typing import Any

from miner.external_common import (
    EXTERNAL_COLLECTION,
    _base_artefact,
    external_event,
    make_record_id,
    run_external_ingest,
)
from settings import settings

logger = logging.getLogger("miner.stackoverflow")

CORPUS_ID = "so-emotion-gold"
PLATFORM_ID = "stackoverflow"
LABELS = ["Artefact", "PostArtefact", "StackOverflowPost"]
FILE_NAME = "Emotions_GoldSandard_andAnnotation.xlsx"
# TODO(design-review): the workbook provides no post id / post type; the
# neutral "text" type is a placeholder until the underlying SO dump is linked.


def _norm_key(text: str) -> str:
    return hashlib.sha256(" ".join((text or "").split()).strip().encode()).hexdigest()


def iter_so_records(path: str) -> Iterator[dict[str, Any]]:
    """Yield one normalized SO post doc per unique text across all sheets."""
    import openpyxl  # lazy: openpyxl only needed when this ingester actually runs

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    seen: set[str] = set()
    counter = 0
    for sheet in wb.worksheets:
        rows = wb[sheet.title].iter_rows(values_only=True)
        try:
            next(rows)  # skip the header row (Group, Set, idx, Text, ...)
        except StopIteration:
            continue
        for row in rows:
            # Columns: Group(0), Set(1), idx(2), Text(3), rater1..3, Gold(7)
            if len(row) < 4:
                continue
            text = (row[3] or "").strip()
            if not text:
                continue
            key = _norm_key(text)
            if key in seen:
                continue
            seen.add(key)
            counter += 1
            record_id = make_record_id("so_post", CORPUS_ID, counter)
            venue_id = f"{PLATFORM_ID}:{CORPUS_ID}:stackoverflow"
            doc = _base_artefact(
                record_id=record_id,
                platform_id=PLATFORM_ID,
                corpus_id=CORPUS_ID,
                venue_id=venue_id,
                artefact_kind="so_text",
                author_login=None,
                created_at=None,
                labels=LABELS,
                source_file=os.path.basename(path),
                metadata={
                    "sheet": sheet.title,
                    "row": row[0],
                    "set": row[1] if len(row) > 1 else None,
                    "post_type_source": "unavailable",
                },
            )
            doc.update({"text": text, "post_type": "text", "external_id": str(counter)})
            yield doc


def _event_for(doc: dict[str, Any], mongo_id: str) -> dict[str, Any]:
    return external_event(
        "so_post",
        doc["venue_id"],
        mongo_id,
        platform_id=PLATFORM_ID,
        corpus_id=CORPUS_ID,
        venue_id=doc["venue_id"],
        artefact_kind="so_post",
        artefact_labels=LABELS,
    )


async def ingest(
    path: str | None = None, max_records: int | None = None, dry_run: bool = False
) -> int:
    path = path or os.path.join(settings.datasets_root, FILE_NAME)
    if not os.path.exists(path):
        raise SystemExit(f"Workbook not found: {path}")
    return await run_external_ingest(
        docs=iter_so_records(path),
        collection=EXTERNAL_COLLECTION,
        key_field="record_id",
        event_for=_event_for,
        label="Ingest SO emotion gold",
        max_records=max_records,
        dry_run=dry_run,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest SO emotion gold-standard workbook.")
    p.add_argument("--path", default=None)
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    import asyncio

    asyncio.run(ingest(path=args.path, max_records=args.max, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
