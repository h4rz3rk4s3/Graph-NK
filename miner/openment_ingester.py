"""
OpenMent Ingester — mentor–mentee interactions in GSoC (v0.8).

Dataset paper (see dataset_papers/):
  "OpenMent: A Dataset of Mentor-Mentee Interactions in Google Summer of Code"
Local dataset:
  /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/OpenMent-dataset/

GitHub-shaped but ANONYMIZED (issue/PR/comment/commit ids, project ids, and
author ids are opaque hashes that cannot be joined back to GitHub). The
principal artefacts map cleanly onto our GitHub Issue/PullRequest model, so we
reuse extract_from_issue / extract_from_pull_request under a namespaced repo
("openment:<project_id>") and tag the nodes :OpenMentIssue / :OpenMentPullRequest
(rather than :GitHubIssue, which would falsely claim a GitHub identity).

SCOPE: only issue/PR title+body and comment text become TextUnits. Mentor/
mentee roles, gender, sentiment, emotion, topic and theme columns in the CSVs
are OUT OF SCOPE and kept only as source metadata; commits are intentionally not
ingested here (the GSoC commit stream is information-poor relative to issues,
matching the frozen miner's include_commits=False divergence).

Only comments.csv is ingested for comments; comments_inside_GSoC_time.csv is a
time-window subset and is not read by default (avoid double-counting the same
comments).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import sys
from collections import OrderedDict
from typing import Any

from miner.external_common import (
    content_sha256,
    external_event,
    run_external_ingest,
)
from settings import settings

# Some comment bodies exceed Python's default 128 KiB CSV field limit.
csv.field_size_limit(sys.maxsize)

logger = logging.getLogger("miner.openment")

# Route docs to the collection the projector's `_collection_for` expects
# (worker.py:307): GitHub-shaped issues live in raw_issues, PRs in
# raw_pull_requests. Routing by artefact_kind keeps the projector's fixed
# mapping and the ingester in agreement (CHANGELOG 2026-08-27).
_COLLECTION_FOR_KIND = {
    "issue": "raw_issues",
    "pull_request": "raw_pull_requests",
}

CORPUS_ID = "openment"
PLATFORM_ID = "openment"


def _load_project_map(path: str) -> dict[str, str]:
    """project_id -> issue_pr_id from project_issue_pr_map.csv."""
    mapping: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            issue_id = (row.get("issue_pr_id") or "").strip()
            project_id = (row.get("project_id") or "").strip()
            if issue_id:
                mapping[issue_id] = project_id
    return mapping


def _load_project_roles(path: str) -> dict[str, dict[str, str]]:
    """
    Load project_roles.csv into {project_id: {user_id: role}}.

    Roles (mentor / mentee) are the dataset's own annotation of the GSoC
    expertise asymmetry (RQ3b v0.3). They are carried as per-author metadata on
    each issue/PR doc so the role survives into the graph-facing raw document
    and the analysis can join TextUnit.author_login → role without re-reading
    the source CSV. They are metadata, never NK text (AGENTS.md §5.8).
    """
    roles: dict[str, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            pid = (row.get("project_id") or "").strip()
            uid = (row.get("user_id") or "").strip()
            role = (row.get("role") or "").strip()
            if pid and uid and role:
                roles.setdefault(pid, {})[uid] = role
    return roles


def _load_issues(path: str) -> OrderedDict[str, dict[str, Any]]:
    """Parse issues_pull_requests.csv into {issue_pr_id: doc} preserving order."""
    issues: OrderedDict[str, dict[str, Any]] = OrderedDict()
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            iid = (row.get("issue_pr_id") or "").strip()
            if not iid:
                continue
            issues[iid] = {
                "issue_pr_id": iid,
                "author_id": (row.get("author_id") or "").strip(),
                "type": (row.get("type") or "issue").strip(),
                "title": row.get("title") or "",
                "body": row.get("body") or "",
                "status": (row.get("status") or "").strip(),
                "creation_day": row.get("creation_day"),
                "close_day": row.get("close_day"),
                "comments_data": [],
            }
    return issues


def _attach_comments(issues: OrderedDict[str, dict[str, Any]], path: str) -> None:
    """Attach comments from comments.csv under each issue's comments_data."""
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            parent = (row.get("issue_pr_id_x") or "").strip()
            if parent not in issues:
                continue
            author_id = (row.get("author_id_x") or "").strip()
            text = row.get("text_x") or ""
            issues[parent]["comments_data"].append(
                {
                    "user": {"login": author_id},
                    "body": text,
                    "created_at": row.get("creation_day_x"),
                }
            )


def iter_openment_docs(
    issues: OrderedDict[str, dict[str, Any]],
    project_map: dict[str, str],
    project_roles: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Build GitHub-shaped issue/pull_request docs with a stable integer `number`
    (the issue's position in the CSV, stable across runs) and a namespaced
    `repo` = "openment:<project_id>". Comment/mentor/gender annotations are
    carried as metadata, never as NK text. `project_roles` (if given) maps each
    author hash to mentor/mentee for the RQ3b role-asymmetry analysis.
    """
    project_roles = project_roles or {}
    docs: list[dict[str, Any]] = []
    for n, (iid, dd) in enumerate(issues.items(), start=1):
        project_id = project_map.get(iid, "unknown")
        repo = f"{PLATFORM_ID}:{project_id}"
        is_pr = dd["type"] == "pull_request"
        # Role of every author in this thread (issue author + commenters), from
        # the dataset's own project_roles annotation. Authors the dataset did
        # not label (rare) are simply absent from the mapping.
        roles: dict[str, str] = {
            author: role
            for author, role in (project_roles.get(project_id) or {}).items()
            if author in {dd["author_id"]} | {c.get("user", {}).get("login") for c in dd["comments_data"]}
        }
        doc = {
            "issue_pr_id": iid,
            "number": n,
            "repo": repo,
            "type": dd["type"],
            "title": dd["title"],
            "body": dd["body"],
            "status": dd["status"],
            "created_at": dd["creation_day"] or None,
            "closed_at": dd["close_day"] or None,
            "user": {"login": dd["author_id"]},
            "comments_data": dd["comments_data"],
            "issue_comments_data": [],
            "project_id": project_id,
            "platform_id": PLATFORM_ID,
            "corpus_id": CORPUS_ID,
            "venue_id": f"{PLATFORM_ID}:{project_id}",
            "artefact_kind": "pull_request" if is_pr else "issue",
            "issue_key": f"{repo}:{n}",
            "metadata": {
                "issue_pr_id": iid,
                "author_id": dd["author_id"],
                "creation_day": dd["creation_day"],
                "close_day": dd["close_day"],
                "project_id": project_id,
                "roles": roles,
            },
        }
        doc["_meta"] = {
            "item_type": "pull_request" if is_pr else "issue",
            "corpus_id": CORPUS_ID,
            "platform_id": PLATFORM_ID,
            "record_id": doc["issue_key"],
            "mined_at": "",
            "processed": False,
            "content_sha256": content_sha256({k: v for k, v in doc.items() if k not in ("_meta",)}),
        }
        docs.append(doc)
    return docs


def _event_for(doc: dict[str, Any], mongo_id: str) -> dict[str, Any]:
    is_pr = doc["artefact_kind"] == "pull_request"
    labels = ["Artefact", "IssueArtefact", ("OpenMentPullRequest" if is_pr else "OpenMentIssue")]
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


async def ingest(
    root: str | None = None,
    max_records: int | None = None,
    dry_run: bool = False,
) -> int:
    root = root or os.path.join(settings.datasets_root, "OpenMent-dataset")
    project_map = _load_project_map(os.path.join(root, "project_issue_pr_map.csv"))
    project_roles = _load_project_roles(os.path.join(root, "project_roles.csv"))
    issues = _load_issues(os.path.join(root, "issues_pull_requests.csv"))
    _attach_comments(issues, os.path.join(root, "comments.csv"))
    docs = iter_openment_docs(issues, project_map, project_roles)

    total = 0
    for kind, collection in _COLLECTION_FOR_KIND.items():
        total += await run_external_ingest(
            docs=(d for d in docs if d["artefact_kind"] == kind),
            collection=collection,
            key_field="issue_key",
            event_for=_event_for,
            label=f"Ingest OpenMent {kind}",
            max_records=max_records,
            dry_run=dry_run,
        )
    return total


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest OpenMent GSoC dataset.")
    p.add_argument("--path", default=None)
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(ingest(root=args.path, max_records=args.max, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
