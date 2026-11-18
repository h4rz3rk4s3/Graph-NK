"""
Gitter Ingester — GitterCom and LiveChatGitter corpora (v0.8).

Two sources, one platform (`gitter`), two corpus ids:

1. raw_gittercom_dataset — CSVs per repo: Gitter Live 2016 archive (Gitter API).
   Header "message,time,user,message" is MISLEADING: the first column is the
   message id, the last is the message text. Read by position [id, time, user,
   text]. We keep the raw collection as-is; the paper's manually curated
   1,000-message-per-community "purpose" sample is a different artifact and is
   NOT part of our ingestion (purpose labels are out of scope).
   Corpus: gittercom  /  dataset dir: raw_gittercom_dataset

2. LiveChatGitter_dataset — .ascii.txt time-stamped logs:
       [YYYY-MM-DD HH:MM:SS] <user> message
   No reliable per-message ids; derive a deterministic one from
   (channel/file, ordinal, timestamp) + content hash. No reply edges are
   invented. Corpora: livechat-gitter / dir: LiveChatGitter_dataset
   Source format (ranking pilot) referenced by:
   Shi, L., Chen, Z., et al., "Detecting and Characterizing Bots that Commit
   Code Mistakes" / the LiveChatGitter release notes (see dataset folder).

Usage:
    python -m miner.gitter_ingester --corpus gittercom [--path <root>] [--max N] [--dry-run]
    python -m miner.gitter_ingester --corpus livechat [--path <root>] [--max N] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import logging
import os
import re
import sys
from collections.abc import Iterator
from typing import Any

from miner.external_common import (
    EXTERNAL_COLLECTION,
    chat_doc,
    external_event,
    make_record_id,
    namespaced_login,
    run_external_ingest,
)
from settings import settings

# Some message rows are long; raise Python's default CSV field limit.
csv.field_size_limit(sys.maxsize)

logger = logging.getLogger("miner.gitter")

PLATFORM_ID = "gitter"
LABELS = ["Artefact", "MessageArtefact", "GitterMessage"]

CORPORA = {
    "gittercom": {
        "corpus_id": "gittercom",
        "dir": "raw_gittercom_dataset",
        "glob": "*.csv",
    },
    "livechat": {
        "corpus_id": "livechat-gitter",
        "dir": "LiveChatGitter_dataset",
        "glob": "*.ascii.txt",
    },
}

_LIVE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] <([^>]+)> ?(.*)$")


def _gitter_venue(corpus_id: str, room: str) -> str:
    return f"{PLATFORM_ID}:{corpus_id}:{room}"


# ── GitterCom CSV reader ──────────────────────────────────────────────────────


def iter_gittercom_records(path: str) -> Iterator[dict[str, Any]]:
    """Parse a GitterCom CSV (columns by POSITION: id, time, user, text)."""
    corpus_id = CORPORA["gittercom"]["corpus_id"]
    room = os.path.splitext(os.path.basename(path))[0]
    venue_id = _gitter_venue(corpus_id, room)
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        try:
            next(reader)  # skip the header row ("message,time,user,message")
        except StopIteration:
            return
        for row in reader:
            if len(row) < 4:
                continue
            msg_id, ts, user, text = row[0], row[1], row[2], row[3]
            if not user:
                continue
            record_id = make_record_id("chat_message", corpus_id, room, msg_id)
            yield chat_doc(
                record_id=record_id,
                text=text,
                author_login=namespaced_login(PLATFORM_ID, corpus_id, user),
                created_at=ts or None,
                channel=room,
                sequence=None,
                platform_id=PLATFORM_ID,
                corpus_id=corpus_id,
                venue_id=venue_id,
                labels=LABELS,
                source_file=os.path.basename(path),
                metadata={"user_raw": user, "gitter_message_id": msg_id},
            )


# ── LiveChatGitter ascii reader ───────────────────────────────────────────────


def iter_livechat_records(path: str) -> Iterator[dict[str, Any]]:
    """Parse a LiveChatGitter .ascii.txt log (one message per [ts] <user> line)."""
    corpus_id = CORPORA["livechat"]["corpus_id"]
    room = os.path.basename(path).replace(".ascii.txt", "")
    venue_id = _gitter_venue(corpus_id, room)
    ordinal = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            m = _LIVE_RE.match(line)
            if not m:
                continue  # continuation / system lines are skipped
            ts, user, text = m.group(1), m.group(2), m.group(3)
            if not user:
                continue
            ordinal += 1
            # Deterministic id from (room, ordinal, ts, text hash).
            digest = hashlib.sha1(f"{ts}:{user}:{text}".encode()).hexdigest()[:12]
            record_id = make_record_id("chat_message", corpus_id, room, ordinal, digest)
            yield chat_doc(
                record_id=record_id,
                text=text,
                author_login=namespaced_login(PLATFORM_ID, corpus_id, user),
                created_at=ts,
                channel=room,
                sequence=ordinal,
                platform_id=PLATFORM_ID,
                corpus_id=corpus_id,
                venue_id=venue_id,
                labels=LABELS,
                source_file=os.path.basename(path),
                metadata={"user_raw": user},
            )


def iter_files(root: str, corpus: str) -> list[str]:
    cfg = CORPORA[corpus]
    files = sorted(glob.glob(os.path.join(root, cfg["glob"])))
    if not files:
        raise SystemExit(f"No {cfg['glob']} files under {root}")
    return files


def _event_for(corpus_id: str) -> Any:
    def build(doc: dict[str, Any], mongo_id: str) -> dict[str, Any]:
        return external_event(
            "chat_message",
            doc["venue_id"],
            mongo_id,
            platform_id=PLATFORM_ID,
            corpus_id=corpus_id,
            venue_id=doc["venue_id"],
            artefact_kind="chat",
            artefact_labels=LABELS,
        )

    return build


async def ingest(
    corpus: str,
    root: str | None = None,
    max_records: int | None = None,
    dry_run: bool = False,
) -> int:
    if corpus not in CORPORA:
        raise SystemExit(f"--corpus must be one of {list(CORPORA)}")
    cfg = CORPORA[corpus]
    root = root or os.path.join(settings.datasets_root, cfg["dir"])
    files = iter_files(root, corpus)

    reader = iter_livechat_records if corpus == "livechat" else iter_gittercom_records

    def gen() -> Iterator[dict[str, Any]]:
        for path in files:
            yield from reader(path)

    return await run_external_ingest(
        docs=gen(),
        collection=EXTERNAL_COLLECTION,
        key_field="record_id",
        event_for=_event_for(cfg["corpus_id"]),
        label=f"Ingest Gitter {corpus}",
        max_records=max_records,
        dry_run=dry_run,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest Gitter corpora.")
    p.add_argument("--corpus", choices=list(CORPORA), required=True)
    p.add_argument("--path", default=None)
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    import asyncio

    asyncio.run(ingest(args.corpus, root=args.path, max_records=args.max, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
