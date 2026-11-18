"""
Slack Ingester — reads the preethac "Software-related Slack Chats with
Disentangled Conversations" XML corpus into the pipeline (v0.8).

Corpus format: one XML file per community/channel/year under
data/<community>/<year>/merged-<community>-<channel>.xml (12 files, ~438k
messages). Each message is:

    <message conversation_id="1">
      <ts>2017-06-16T10:51:34.290598</ts>
      <user>Melvin</user>
      <text>...</text>
    </message>

with `conversation_id` a dataset-provided grouping label (NOT a native Slack
thread id) and `user` an anonymized alias (see scripts/anonslack.py).

METHODOLOGICAL NOTE: the XML under data/ is the canonical text source. The
dataset's own preprocessing scripts (scripts/disentanglement/preprocessing/
preprocessChat.py) are NOT used — they drop line breaks, clobber emoji and
fenced code, and rewrite mentions, which would corrupt the authored text we
anonymise/analyse.

SOURCE / PAPER (unverified attribution — the local README, not the project's
FRAMEWORK_DESIGN §12 index which points at Gouravajhala et al. 2023):
  P. Chaterjee, K. Damevski, N. Kraft, L. Pollock,
  "Software-related Slack Chats with Disentangled Conversations" (submitted).
Local dataset:
  /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/preethac_SlackDisentangled_dataset/
The bundled elsner-charniak-08-mod/IRC subtree is a SEPARATE reference corpus
and is deliberately NOT ingested here (see miner/irc_ingester.py / README).

Usage:
    python -m miner.slack_ingester [--path <root>] [--max N] [--dry-run]
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Any

from miner.external_common import (
    EXTERNAL_COLLECTION,
    chat_doc,
    data_path_parts,
    external_event,
    make_record_id,
    namespaced_login,
    run_external_ingest,
)
from settings import settings

logger = logging.getLogger("miner.slack")

CORPUS_ID = "preethac-slack"
PLATFORM_ID = "slack"
LABELS = ["Artefact", "MessageArtefact", "SlackMessage"]


def iter_slack_files(root: str, channels: list[str] | None = None) -> list[str]:
    """Discover the source XML files under root/data/<community>/<year>/."""
    pattern = os.path.join(root, "data", "*", "*", "merged-*.xml")
    files = sorted(glob.glob(pattern))
    if channels:
        files = [f for f in files if any(c in os.path.basename(f) for c in channels)]
    if not files:
        raise SystemExit(f"No Slack XML files found under {root}/data/**/*.xml")
    return files


def iter_slack_records(path: str) -> Iterator[dict[str, Any]]:
    """
    Yield one normalized chat message doc per <message> in one XML file.

    Uses a stable message ordinal within the file as the disambiguator
    (timestamps are NOT unique — several messages can share a second).
    Messages without a <user> are skipped (matches the corpus's own
    slack2xml.py, which drops no-user messages).
    Files live at <root>/data/<community>/<year>/merged-<community>-<channel>.xml.
    The pre-fix relative-path computation cut one directory short of `data/`, so
    community/period always fell back to "unknown" (CHANGELOG 2026-08-19).
    """
    community, period, _ = data_path_parts(path)

    tree = ET.parse(path)
    root = tree.getroot()
    team_domain = (root.findtext("team_domain") or community).strip()
    channel_name = (root.findtext("channel_name") or "unknown").strip()
    venue_id = f"{PLATFORM_ID}:{CORPUS_ID}:{team_domain}/{channel_name}"

    for ordinal, msg in enumerate(root.findall("message"), start=1):
        user = _text_of(msg, "user")
        if not user:
            continue  # matches slack2xml.py (no-user messages dropped)
        text = _text_of(msg, "text")
        ts = _text_of(msg, "ts")
        conv = msg.get("conversation_id")
        record_id = make_record_id(
            "chat_message", CORPUS_ID, team_domain, channel_name, period, ordinal
        )
        yield chat_doc(
            record_id=record_id,
            text=text,
            author_login=namespaced_login(PLATFORM_ID, CORPUS_ID, user),
            created_at=ts or None,
            channel=channel_name,
            sequence=ordinal,
            platform_id=PLATFORM_ID,
            corpus_id=CORPUS_ID,
            venue_id=venue_id,
            labels=LABELS,
            conversation_id=conv,
            source_file=os.path.basename(path),
            metadata={
                "team_domain": team_domain,
                "channel_name": channel_name,
                "file_period": period,
                "user_raw": user,
            },
        )


def _text_of(msg: ET.Element, tag: str) -> str:
    el = msg.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


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
    channels: list[str] | None = None,
) -> int:
    root = root or settings.datasets_root + "/preethac_SlackDisentangled_dataset"
    files = iter_slack_files(root, channels)

    def gen() -> Iterator[dict[str, Any]]:
        for path in files:
            yield from iter_slack_records(path)

    return await run_external_ingest(
        docs=gen(),
        collection=EXTERNAL_COLLECTION,
        key_field="record_id",
        event_for=_event_for,
        label="Ingest Slack",
        max_records=max_records,
        dry_run=dry_run,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest preethac Slack XML corpus.")
    p.add_argument("--path", default=None, help="Override dataset root.")
    p.add_argument(
        "--channels",
        nargs="*",
        default=None,
        help="Only files whose basename contains any of these.",
    )
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    import asyncio

    asyncio.run(
        ingest(root=args.path, max_records=args.max, dry_run=args.dry_run, channels=args.channels)
    )


if __name__ == "__main__":
    main()
