"""
Kummerfeld Ubuntu IRC Ingester (v0.8).

Jonathan K. Kummerfeld et al., "A Large-Scale Corpus for Conversation
Disentanglement" (ACL 2019). Local dataset:
  /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/Kummerfeld_UbuntuIRC_dataset/

The repository bundles TWO corpora:
  - the main Ubuntu IRC disentanglement corpus under data/dev, data/test, ...;
  - Gouravajhala et al. 2023 ("Chat Disentanglement: Data for New Domains",
    ALTA 2023) new-domain data under data/new-domains/ (rust, stripe, mediawiki,
    ubuntu-meeting), which extends the same format. Both are ingested here under
    corpus_id "kummerfeld-irc", distinguished by their split/domain path.

Formats:
  .ascii.txt  — one message per line:
      ubuntu:      [HH:MM] <nick> text
      new-domain:  channel YYYY-MM-DD [HH:MM] <nick> text
  .annotation.txt — one edge per line: "<child> <parent> -" where the numbers
      are 1-based line ordinals in the SAME .ascii.txt file (verified against
      the data: annotation max ≤ ascii line count per file).

SEMANTIC ASSUMPTION (documented, from the amended/new-domain format):
  annotation pair (A, B) means "message A is a child in the conversation of
  message B", i.e. A replies to B. We build REPLIES_TO edges A→B and derive a
  conversation grouping by union-find over all edges (a message's conversation
  root = the earliest message ordinal in its component). If a real ingestion
  exposes the opposite direction, change `edge_child_of` below and re-run —
  the enrichment (enrichment/irc_threading.py) reads the stored reply_to refs.
  Where a pair's ordinals are out of range they are dropped with a warning
  (never fabricated).

Usage:
    python -m miner.irc_ingester [--path <root>] [--splits dev test new-domains]
                                 [--max N] [--dry-run]
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import re
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

logger = logging.getLogger("miner.irc")

CORPUS_ID = "kummerfeld-irc"
PLATFORM_ID = "irc"
LABELS = ["Artefact", "MessageArtefact", "IRCMessage"]

# Ubuntu logs: [HH:MM] <nick> text
_UBUNTU_RE = re.compile(r"^\[(\d{2}:\d{2})\]\s*<([^>]+)>\s?(.*)$")
# New-domain logs: channel YYYY-MM-DD [HH:MM[:SS]] <nick> text
_NDOMAIN_RE = re.compile(
    r"^([A-Za-z0-9_-]+)\s+(\d{4}-\d{2}-\d{2})\s+\[(\d{2}:\d{2}(?::\d{2})?)]\s*<([^>]+)>\s?(.*)$"
)


class UnionFind:
    """Minimal union-find for assigning conversation ids to IRC messages."""

    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # chain by smaller root to give a stable conversation label
            if ra < rb:
                self.parent[rb] = ra
            else:
                self.parent[ra] = rb


def parse_line(line: str) -> tuple[str, str, str, str] | None:
    """
    Parse one .ascii.txt line → (channel, created_at, user, text) or None.

    Handles both the ubuntu and new-domain log shapes; returns the channel the
    message belongs to (domain name for new domains, "ubuntu" otherwise).
    """
    line = line.rstrip("\n")
    m = _NDOMAIN_RE.match(line)
    if m:
        channel, date, hhmm, user, text = m.groups()
        # hhmm is "HH:MM" or "HH:MM:SS" (seconds only in new-domain logs)
        stamp = hhmm if len(hhmm) > 5 else f"{hhmm}:00"
        return channel, f"{date}T{stamp}", user, text
    m = _UBUNTU_RE.match(line)
    if m:
        hhmm, user, text = m.groups()
        return "ubuntu", hhmm, user, text
    return None


def _ascii_and_annotation(path: str) -> tuple[str, str | None]:
    """Return (ascii_path, annotation_path_or_None) for a corpus window."""
    annotation = path[: -len(".ascii.txt")] + ".annotation.txt"
    if os.path.exists(annotation):
        return path, annotation
    return path, None


def _load_edges(annotation_path: str | None) -> list[tuple[int, int]]:
    """Parse "child parent -" annotation lines into (child, parent) ordinals."""
    edges: list[tuple[int, int]] = []
    if not annotation_path:
        return edges
    with open(annotation_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 2:
                continue
            a, b = parts[0], parts[1]
            try:
                edges.append((int(a), int(b)))
            except ValueError:
                continue
    return edges


def iter_irc_windows(root: str, splits: list[str]) -> Iterator[tuple[str, str | None]]:
    """Yield (ascii_path, annotation_path) for each corpus window selected."""
    for split in splits:
        for ascii_path in sorted(glob.glob(os.path.join(root, split, "*.ascii.txt"))):
            yield _ascii_and_annotation(ascii_path)


def iter_irc_records_from_window(
    ascii_path: str,
    annotation_path: str | None,
) -> Iterator[dict[str, Any]]:
    """Emit message docs for one window, with reply/conversation metadata."""
    rel = os.path.relpath(ascii_path, os.path.dirname(os.path.dirname(ascii_path)))
    split, fname = rel.split(os.sep)[0], os.path.basename(ascii_path)
    # Ubuntu log files name their date: "<YYYY-MM-DD>_<hh>.ascii.txt". New-domain
    # logs carry the full date on every line, so this only fills the HH:MM case.
    file_date = os.path.basename(ascii_path)[:10]
    file_date = file_date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", file_date) else None

    # Parse all messages up front (1-based line ordinals as identifiers).
    msgs: list[dict[str, Any]] = []
    with open(ascii_path, encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, start=1):
            parsed = parse_line(line)
            if not parsed:
                continue
            channel, created_at, user, text = parsed
            # Ubuntu lines give only "HH:MM"; combine with the file's date so the
            # timestamp is a real datetime (the filename encodes the log's date).
            if file_date and re.fullmatch(r"\d{2}:\d{2}", created_at):
                created_at = f"{file_date}T{created_at}:00"
            record_id = make_record_id("chat_message", CORPUS_ID, split, fname, line_no)
            msgs.append(
                {
                    "record_id": record_id,
                    "ordinal": line_no,
                    "channel": channel,
                    "created_at": created_at,
                    "user": user,
                    "text": text,
                    "venue_id": f"{PLATFORM_ID}:{CORPUS_ID}:{channel}",
                }
            )

    # Conversation grouping + reply edges from the annotation file.
    uf = UnionFind()
    for a, b in _load_edges(annotation_path):
        uf.union(a, b)
    reply_map: dict[int, list[int]] = {}
    for a, b in _load_edges(annotation_path):
        reply_map.setdefault(a, []).append(b)

    by_ordinal = {m["ordinal"]: m for m in msgs}
    for m in msgs:
        ordn = m["ordinal"]
        if ordn in uf.parent:
            root = uf.find(ordn)
            conversation_label = f"{root}"
            parent_ids = [
                r
                for r in reply_map.get(ordn, [])
                if r in by_ordinal  # drop out-of-range refs, never fabricate
            ]
        else:
            conversation_label = None
            parent_ids = []
        yield chat_doc(
            record_id=m["record_id"],
            text=m["text"],
            author_login=namespaced_login(PLATFORM_ID, CORPUS_ID, m["user"]),
            created_at=m["created_at"],
            channel=m["channel"],
            sequence=ordn,
            platform_id=PLATFORM_ID,
            corpus_id=CORPUS_ID,
            venue_id=m["venue_id"],
            labels=LABELS,
            conversation_id=conversation_label,
            reply_to=[by_ordinal[r]["record_id"] for r in parent_ids] or None,
            source_file=fname,
            metadata={
                "split": split,
                "file": fname,
                "ordinal": ordn,
                "user_raw": m["user"],
                "annotation_file": os.path.basename(annotation_path) if annotation_path else None,
            },
        )


def iter_all_records(root: str, splits: list[str]) -> Iterator[dict[str, Any]]:
    for ascii_path, annotation_path in iter_irc_windows(root, splits):
        yield from iter_irc_records_from_window(ascii_path, annotation_path)


def _event_for(doc: dict[str, Any], mongo_id: str) -> dict[str, Any]:
    return external_event(
        "chat_message",
        doc["venue_id"],
        mongo_id,
        platform_id=PLATFORM_ID,
        corpus_id=CORPUS_ID,
        venue_id=doc["venue_id"],
        artefact_kind="chat",
        artefact_labels=LABELS,
        conversation_id=doc.get("conversation_id"),
    )


async def ingest(
    root: str | None = None,
    max_records: int | None = None,
    dry_run: bool = False,
    splits: list[str] | None = None,
) -> int:
    root = root or os.path.join(settings.datasets_root, "Kummerfeld_UbuntuIRC_dataset", "data")
    splits = splits or ["dev", "test", "new-domains"]
    return await run_external_ingest(
        docs=iter_all_records(root, splits),
        collection=EXTERNAL_COLLECTION,
        key_field="record_id",
        event_for=_event_for,
        label="Ingest IRC",
        max_records=max_records,
        dry_run=dry_run,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest Kummerfeld Ubuntu IRC corpus.")
    p.add_argument("--path", default=None)
    p.add_argument("--splits", nargs="*", default=None)
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    import asyncio

    asyncio.run(
        ingest(root=args.path, max_records=args.max, dry_run=args.dry_run, splits=args.splits)
    )


if __name__ == "__main__":
    main()
