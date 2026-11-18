"""
Bugzilla Ingester — BugsRepo comments dataset (v0.8).

Dataset paper (see dataset_papers/):
  "BugsRepo: A Dataset of Reproducibility Information For Bug Reports"
  (the local PDF is BugsRepo_paper.pdf).
Local dataset:
  /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/BugsRepo_Comments/

Format: wide denormalized CSVs (~315 columns) from the Mozilla Bugzilla export,
one row PER COMMENT with the bug's fields repeated. A row where `Bug report` ==
'True' holds the bug description (summary + text); all other rows with that
`bug_id` are comments. We group rows by bug_id into one BugzillaIssue per bug.

KNOWN DUPLICATES (verified by SHA-256 on disk): comments_Dataset_Part_1.csv and
comments_Dataset_Part_2.csv are byte-identical. Part_2 is skipped automatically
by content hash dedupe.

SCOPE: bug summary (title), report text (body), and comment text become
TextUnits. Product/component/severity/priority/status/resolution and the
`contains_steps_to_reproduce` flag are kept as metadata. The bug is represented
as :BugzillaIssue under a namespaced venue ("bugzilla:bugsrepo:<product>") —
NOT as a GitHub :Issue, per FRAMEWORK_DESIGN §4.8.

Usage:
    python -m miner.bugzilla_ingester [--path <dir>] [--max N] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import logging
import os
import sys
from collections import OrderedDict
from typing import Any

from miner.external_common import (
    EXTERNAL_COLLECTION,
    issue_doc,
    make_record_id,
    namespaced_login,
    run_external_ingest,
)
from settings import settings

# Bugzilla descriptions/comments can exceed Python's default CSV field limit.
csv.field_size_limit(sys.maxsize)

logger = logging.getLogger("miner.bugzilla")

CORPUS_ID = "bugsrepo"
PLATFORM_ID = "bugzilla"
LABELS_ISSUE = ["Artefact", "IssueArtefact", "BugzillaIssue"]
BOGUS_META = "_mozilla_bug"


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _group_file(path: str) -> OrderedDict[str, dict[str, Any]]:
    """
    Group all rows of one CSV into {bug_id: merged doc}. The report row
    ('Bug report' == 'True') supplies title/body/author/dates/state; the
    remaining rows of the same bug become comments.
    """
    bugs: OrderedDict[str, dict[str, Any]] = OrderedDict()
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            bug_id = (row.get("bug_id") or "").strip()
            if not bug_id:
                continue
            is_report = str(row.get("Bug report")).strip().lower() == "true"
            text = (row.get("text") or row.get("raw_text") or "").strip()
            creator = (row.get("creator_x") or row.get("author") or "").strip()
            created = (row.get("creation_time_x") or "").strip()

            bug = bugs.setdefault(bug_id, {"comments": [], "is_report": False})
            if is_report:
                bug["is_report"] = True
                bug["summary"] = row.get("summary") or ""
                bug["description"] = text
                bug["author_login"] = namespaced_login(PLATFORM_ID, CORPUS_ID, creator)
                bug["created_at"] = created or (row.get("creation_time_y") or "").strip()
                bug["state"] = row.get("status") or ""
                bug["product"] = row.get("product") or "mozilla"
                bug["component"] = row.get("component") or ""
                bug["severity"] = row.get("severity") or ""
                bug["priority"] = row.get("priority") or ""
                bug["resolution"] = row.get("resolution") or ""
                bug["contains_steps_to_reproduce"] = row.get("contains_steps_to_reproduce")
            else:
                bug["comments"].append(
                    {
                        "body": text,
                        "author_login": namespaced_login(PLATFORM_ID, CORPUS_ID, creator),
                        "created_at": created,
                    }
                )
    return bugs


def iter_bugzilla_docs(files: list[str]) -> dict[str, dict[str, Any]]:
    """Group bugs across all (dedup'd) files, one issue_doc per bug."""
    seen_hashes: set[str] = set()
    docs: dict[str, dict[str, Any]] = {}
    for path in files:
        h = _file_hash(path)
        if h in seen_hashes:
            logger.warning("Skipping duplicate file by content hash: %s", os.path.basename(path))
            continue
        seen_hashes.add(h)
        for bug_id, bug in _group_file(path).items():
            product = bug.get("product") or "mozilla"
            venue_id = f"{PLATFORM_ID}:{CORPUS_ID}:{product}"
            record_id = make_record_id("bugzilla_issue", CORPUS_ID, bug_id)
            # Only emit the bug if we found the report row (otherwise we only
            # have stray comments with no report text to anchor them to).
            if bug["is_report"]:
                docs[record_id] = issue_doc(
                    record_id=record_id,
                    external_id=bug_id,
                    title=bug.get("summary"),
                    body=bug.get("description"),
                    comments=bug["comments"],
                    author_login=bug.get("author_login"),
                    created_at=bug.get("created_at"),
                    platform_id=PLATFORM_ID,
                    corpus_id=CORPUS_ID,
                    venue_id=venue_id,
                    artefact_kind="bugzilla_issue",
                    labels=LABELS_ISSUE,
                    state=bug.get("state"),
                    source_file=os.path.basename(path),
                    metadata={
                        "bug_id": bug_id,
                        "component": bug.get("component"),
                        "severity": bug.get("severity"),
                        "priority": bug.get("priority"),
                        "resolution": bug.get("resolution"),
                        "contains_steps_to_reproduce": bug.get("contains_steps_to_reproduce"),
                    },
                )
    return docs


def _event_for(doc: dict[str, Any], mongo_id: str) -> dict[str, Any]:
    from miner.external_common import external_event

    return external_event(
        "bugzilla_issue",
        doc["venue_id"],
        mongo_id,
        platform_id=PLATFORM_ID,
        corpus_id=CORPUS_ID,
        venue_id=doc["venue_id"],
        artefact_kind="bugzilla_issue",
        artefact_labels=LABELS_ISSUE,
    )


async def ingest(
    root: str | None = None,
    max_records: int | None = None,
    dry_run: bool = False,
) -> int:
    root = root or os.path.join(settings.datasets_root, "BugsRepo_Comments")
    files = sorted(
        f for f in os.listdir(root) if f.startswith("comments_Dataset_") and f.endswith(".csv")
    )
    if not files:
        raise SystemExit(f"No BugsRepo CSV files found under {root}")
    docs = iter_bugzilla_docs([os.path.join(root, f) for f in files])
    return await run_external_ingest(
        docs=iter(docs.values()),
        collection=EXTERNAL_COLLECTION,
        key_field="record_id",
        event_for=_event_for,
        label="Ingest BugsRepo",
        max_records=max_records,
        dry_run=dry_run,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest BugsRepo Bugzilla dataset.")
    p.add_argument("--path", default=None)
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(ingest(root=args.path, max_records=args.max, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
