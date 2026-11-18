"""
DISCO-A Ingester — Discord chat conversations (v0.8).

Muthu Subash Kavumkal et al., "DISCO: A Dataset of Discord Chat Conversations
for Software Engineering Research", MSR 2022 (Data Showcase).
Local dataset (directory has a space in its name):
  /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/DISCO-A Dataset of Discord
  Chat Conversations for Software Engineering Research/

Format (data/<community>/<period>/<name>.xml):
    <discord>
      <team_domain>Clojurians</team_domain>
      <channel_name>clojure</channel_name>
      <start_date>...</start_date><end_date>...</end_date>
      <message><ts>…</ts><user>…</user><text>…</text></message>
      ...

We ingest ONLY the base `.xml` files. The sibling `.out` files are the model's
conversation-grouping output and are deliberately skipped (generated annotation,
not a canonical source — AGENTS.md / FRAMEWORK_DESIGN §12 keep source annotations
out of the corpus unless they are part of the released ground truth for our
research question). Consequently DISCO messages carry no conversation_id here.

Usage:
    python -m miner.discord_ingester [--path <root>] [--max N] [--dry-run]
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

logger = logging.getLogger("miner.disco")

# The on-disk dataset directory name contains spaces; the default root below
# uses settings.datasets_root + this relative folder.
CORPUS_ID = "disco"
PLATFORM_ID = "discord"
LABELS = ["Artefact", "MessageArtefact", "DiscordMessage"]
DATA_DIR = "DISCO-A Dataset of Discord Chat Conversations for Software Engineering Research"


def iter_disco_files(root: str) -> list[str]:
    # Only base XML (name NOT ending in .out).
    files = sorted(glob.glob(os.path.join(root, "data", "*", "*", "*.xml")))
    files = [f for f in files if not f.endswith(".xml.out")]
    if not files:
        raise SystemExit(f"No DISCO XML files found under {root}/data/**/*.xml")
    return files


def iter_discord_records(path: str) -> Iterator[dict[str, Any]]:
    # Files live at <root>/data/<community>/<period>/<file>.xml. The pre-fix code
    # computed relpath one directory short of `data/`, so "community" became the
    # period and "period" became the channel file (CHANGELOG 2026-08-19).
    community, period, _ = data_path_parts(path)

    root = ET.parse(path).getroot()
    team_domain = (root.findtext("team_domain") or community).strip()
    channel_name = (root.findtext("channel_name") or "unknown").strip()
    venue_id = f"{PLATFORM_ID}:{CORPUS_ID}:{team_domain}/{channel_name}"

    for ordinal, msg in enumerate(root.findall("message"), start=1):
        user = (msg.findtext("user") or "").strip()
        text = (msg.findtext("text") or "").strip()
        ts = (msg.findtext("ts") or "").strip()
        if not user:
            continue
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
            source_file=os.path.basename(path),
            metadata={
                "team_domain": team_domain,
                "channel_name": channel_name,
                "file_period": period,
                "user_raw": user,
            },
        )


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
    )


async def ingest(
    root: str | None = None, max_records: int | None = None, dry_run: bool = False
) -> int:
    root = root or os.path.join(settings.datasets_root, DATA_DIR)
    files = iter_disco_files(root)

    def gen() -> Iterator[dict[str, Any]]:
        for path in files:
            yield from iter_discord_records(path)

    return await run_external_ingest(
        docs=gen(),
        collection=EXTERNAL_COLLECTION,
        key_field="record_id",
        event_for=_event_for,
        label="Ingest DISCO",
        max_records=max_records,
        dry_run=dry_run,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest DISCO-A Discord XML corpus.")
    p.add_argument("--path", default=None)
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    import asyncio

    asyncio.run(ingest(root=args.path, max_records=args.max, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
