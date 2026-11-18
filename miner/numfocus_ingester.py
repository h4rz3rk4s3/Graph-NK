"""
NumFocus Ingester — contributor activity in the NumFOCUS community (v0.8).

Dataset paper (see dataset_papers/):
  "A Dataset of Contributor Activities in the NumFOCUS Open-Source Community"
Local files:
  /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/NumFocus_dataset/
      NumFocus_Jan22-Dec24_GH_Actions.jsonl
      NumFocus_Jan22-Dec24_GH_Activities.jsonl

This is a GitHub *activity stream*, not a full issue/PR export. We read the
Actions file (the higher-fidelity event source) and emit graph records ONLY
where natural-language text exists. KEY DATA LIMITATION (verified on the raw
payloads): comment/review events carry only {id, position} — the comment BODY
text is NOT in this dataset — and PushCommits carries only a commit count, not
SHA/message. So the only text available from NumFocus is issue and pull-request
TITLES (plus their state/dates). Bodies and comments are absent by design; we
never fabricate them.

Design: stream events, one GitHub-shaped Issue/PullRequest doc per event that
carries an issue/pr object with a title; dedupe downstream via the unique
`issue_key` (= repo + number) and the projector's (repo, number) MERGE, exactly
as for native GitHub issues. Non-text events (push, comments, reviews, stars,
forks, ...) are skipped from the graph (kept only in Mongo as raw source if we
ever need them later — not written here).

Usage:
    python -m miner.numfocus_ingester [--path <jsonl>] [--max N] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from collections.abc import Iterator
from typing import Any

from miner.external_common import content_sha256, external_event, run_external_ingest
from settings import settings

logger = logging.getLogger("miner.numfocus")

CORPUS_ID = "numfocus"
PLATFORM_ID = "numfocus"
FILE = "NumFocus_Jan22-Dec24_GH_Actions.jsonl"


def iter_numfocus_events(path: str) -> Iterator[dict[str, Any]]:
    """Yield raw Actions events, tolerant of malformed lines."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("%s:%d — malformed JSON, skipping (%s)", path, line_no, exc)


def _event_issue_or_pr(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return ('issue'|'pull_request', details_obj) if the event carries a titled item."""
    details = event.get("details") or {}
    for kind in ("issue", "pull_request"):
        obj = details.get(kind)
        if isinstance(obj, dict) and (obj.get("title") or "").strip():
            return kind, obj
    return None


def iter_numfocus_docs(path: str) -> Iterator[dict[str, Any]]:
    """Emit GitHub-shaped issue/PR docs; only events that carry titled items."""
    for event in iter_numfocus_events(path):
        found = _event_issue_or_pr(event)
        if not found:
            continue
        kind, obj = found
        is_pr = kind == "pull_request"
        repo_obj = event.get("repository") or {}
        repo_id = repo_obj.get("id") or "unknown"
        repo_name = repo_obj.get("name") or f"repo-{repo_id}"
        repo_ns = f"{PLATFORM_ID}:{repo_id}"
        number = obj.get("number")
        if number is None:
            number = int(obj.get("id", 0))  # fallback: issue id as number
        author_login = (event.get("actor") or {}).get("login") or ""
        title = (obj.get("title") or "").strip()
        state = obj.get("state") or ""
        created_at = obj.get("created_date") or event.get("date")
        issue_key = f"{repo_ns}:{number}"

        doc = {
            "issue_pr_id": str(obj.get("id", "")),
            "number": number,
            "repo": repo_ns,
            "type": kind,
            "title": title,
            "body": None,
            "status": state,
            "state": state,
            "merged": obj.get("merged", False),
            "created_at": created_at,
            "closed_at": obj.get("closed_date"),
            "user": {"login": author_login},
            "comments_data": [],
            "issue_comments_data": [],
            "platform_id": PLATFORM_ID,
            "corpus_id": CORPUS_ID,
            "venue_id": repo_ns,
            "artefact_kind": kind,
            "issue_key": issue_key,
            "metadata": {
                "event_id": str(event.get("event_id", "")),
                "action": event.get("action", ""),
                "repo_id": repo_id,
                "repo_name": repo_name,
            },
        }
        doc["_meta"] = {
            "item_type": "pull_request" if is_pr else "issue",
            "corpus_id": CORPUS_ID,
            "platform_id": PLATFORM_ID,
            "record_id": issue_key,
            "mined_at": "",
            "processed": False,
            "content_sha256": content_sha256({k: v for k, v in doc.items() if k != "_meta"}),
        }
        yield doc


def _event_for(doc: dict[str, Any], mongo_id: str) -> dict[str, Any]:
    is_pr = doc["artefact_kind"] == "pull_request"
    labels = ["Artefact", "IssueArtefact", ("NumFocusPullRequest" if is_pr else "NumFocusIssue")]
    return external_event(
        "pull_request" if is_pr else "issue",
        doc["repo"],
        mongo_id,
        platform_id=PLATFORM_ID,
        corpus_id=CORPUS_ID,
        venue_id=doc["venue_id"],
        artefact_kind=doc["artefact_kind"],
        artefact_labels=labels,
    )


# Route docs to the collection the projector's `_collection_for` expects
# (worker.py:307): GitHub-shaped issues live in raw_issues, PRs in
# raw_pull_requests. Routing by artefact_kind keeps the projector's fixed
# mapping and the ingester in agreement (CHANGELOG 2026-08-27).
_COLLECTION_FOR_KIND = {
    "issue": "raw_issues",
    "pull_request": "raw_pull_requests",
}


def _docs_of_kind(path: str, kind: str) -> Iterator[dict[str, Any]]:
    """Yield only the NumFocus docs whose artefact_kind matches `kind`."""
    for doc in iter_numfocus_docs(path):
        if doc["artefact_kind"] == kind:
            yield doc


async def ingest(
    path: str | None = None,
    max_records: int | None = None,
    dry_run: bool = False,
) -> int:
    path = path or os.path.join(settings.datasets_root, "NumFocus_dataset", FILE)
    if not os.path.exists(path):
        raise SystemExit(f"NumFocus Actions file not found: {path}")
    total = 0
    for kind, collection in _COLLECTION_FOR_KIND.items():
        total += await run_external_ingest(
            docs=_docs_of_kind(path, kind),
            collection=collection,
            key_field="issue_key",
            event_for=_event_for,
            label=f"Ingest NumFocus {kind}",
            max_records=max_records,
            dry_run=dry_run,
        )
    return total


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest NumFOCUS activity dataset.")
    p.add_argument("--path", default=None)
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(ingest(path=args.path, max_records=args.max, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
