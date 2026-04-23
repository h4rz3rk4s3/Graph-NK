"""
Module — Reference Enrichment (Milestone 9).

Post-annotation pass that scans all TextUnits with role in
{body, commit_message, comment_body} for cross-references to issues
(e.g. 'fixes #123', 'closes #45') and writes REFERENCES edges to Neo4j.

Runs AFTER the main annotation pipeline has completed.
Design rationale for separating this from the TextUnitExtractor:
  the reference regex will evolve as we see real corpus data; keeping it
  separate means we can re-run enrichment without re-running extraction.
  See BUILD_SPEC.md §1 locked decisions and §6 M9.

Reference regex: see BUILD_SPEC.md §6 M9.
"""
from __future__ import annotations

import logging
import re

from neo4j import AsyncGraphDatabase, AsyncDriver

from settings import settings

logger = logging.getLogger(__name__)

# Regex that matches GitHub cross-references.
# Named groups: mechanism (optional) + number.
# Canonical forms after normalisation:
#   closes, fixes, resolves, refs, see, bare
_REF_PATTERN = re.compile(
    r"(?:(?P<mechanism>close[sd]?|fix(?:e[sd])?|resolve[sd]?|ref(?:erence)?s?|see)\s+)?"
    r"#(?P<number>\d+)",
    re.IGNORECASE,
)

_MECHANISM_CANONICAL: dict[str, str] = {
    # closes family
    "close":    "closes", "closed": "closes", "closes": "closes",
    # fixes family
    "fix":      "fixes",  "fixed":  "fixes",  "fixes":  "fixes",
    "fixe":     "fixes",
    # resolves family
    "resolve":  "resolves", "resolved": "resolves", "resolves": "resolves",
    # refs family
    "ref":      "refs",   "refs":   "refs",   "reference": "refs", "references": "refs",
    # see
    "see":      "see",
}

_TARGET_ROLES = {"body", "commit_message", "comment_body"}


async def run_reference_enrichment() -> None:
    """
    Entry point.  Queries Neo4j for all eligible TextUnits, extracts references,
    writes REFERENCES edges.
    """
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        await _enrich(driver)
    finally:
        await driver.close()
    logger.info("Reference enrichment complete.")


async def _enrich(driver: AsyncDriver) -> None:
    """
    Fetch all TextUnits in target roles and write REFERENCES edges.
    """
    async with driver.session() as session:
        # Fetch TextUnit id + text + parent info for eligible roles
        result = await session.run(
            """
            MATCH (parent)-[rel:HAS_TEXT]->(u:TextUnit)
            WHERE rel.role IN $roles
            RETURN u.id AS tu_id, u.text AS text, rel.role AS role,
                   labels(parent)[0] AS parent_label,
                   CASE labels(parent)[0]
                     WHEN 'Issue'       THEN parent.repo
                     WHEN 'PullRequest' THEN parent.repo
                     WHEN 'Commit'      THEN parent.repo
                     ELSE null
                   END AS repo,
                   CASE labels(parent)[0]
                     WHEN 'Issue'       THEN parent.number
                     WHEN 'PullRequest' THEN parent.number
                     ELSE null
                   END AS parent_number,
                   CASE labels(parent)[0]
                     WHEN 'Commit' THEN parent.sha
                     ELSE null
                   END AS commit_sha
            """,
            roles=list(_TARGET_ROLES),
        )
        rows = await result.data()

    logger.info("Reference enrichment: scanning %d TextUnits.", len(rows))
    total_refs = 0

    for row in rows:
        text      = row.get("text") or ""
        tu_id     = row["tu_id"]
        repo      = row.get("repo") or ""

        refs = extract_references(text)
        if not refs:
            continue

        async with driver.session() as session:
            for ref_number, mechanism in refs:
                try:
                    await _write_reference(
                        session,
                        parent_label  = row["parent_label"],
                        repo          = repo,
                        parent_number = row.get("parent_number"),
                        commit_sha    = row.get("commit_sha"),
                        ref_number    = ref_number,
                        mechanism     = mechanism,
                        tu_id         = tu_id,
                    )
                    total_refs += 1
                except Exception as exc:
                    logger.warning(
                        "Could not write reference from %s to #%d: %s",
                        tu_id, ref_number, exc,
                    )

    logger.info("Reference enrichment: wrote %d REFERENCES edges.", total_refs)


def extract_references(text: str) -> list[tuple[int, str]]:
    """
    Pure function.  Returns (issue_number, canonical_mechanism) pairs
    found in text.  Exported for testing.
    """
    refs: list[tuple[int, str]] = []
    for m in _REF_PATTERN.finditer(text):
        number = int(m.group("number"))
        raw_mech = (m.group("mechanism") or "").lower().strip()
        mechanism = _MECHANISM_CANONICAL.get(raw_mech, "bare")
        refs.append((number, mechanism))
    return refs


async def _write_reference(
    session: Any,
    *,
    parent_label: str,
    repo: str,
    parent_number: int | None,
    commit_sha: str | None,
    ref_number: int,
    mechanism: str,
    tu_id: str,
) -> None:
    """
    MERGE a REFERENCES edge from the source artefact to the target Issue.
    Cypher template: ontology.cypher §3.14.
    """
    if parent_label in ("Issue", "PullRequest") and parent_number is not None:
        src_match = (
            f"MATCH (src:{parent_label} {{repo: $repo, number: $src_number}})"
        )
        params: dict = dict(
            repo=repo, src_number=parent_number,
            ref_number=ref_number, mechanism=mechanism, tu_id=tu_id,
        )
    elif parent_label == "Commit" and commit_sha:
        src_match = "MATCH (src:Commit {sha: $sha})"
        params = dict(
            repo=repo, sha=commit_sha,
            ref_number=ref_number, mechanism=mechanism, tu_id=tu_id,
        )
    else:
        return  # No valid source — skip silently

    cypher = f"""
    {src_match}
    MATCH (dst:Issue {{repo: $repo, number: $ref_number}})
    MERGE (src)-[r:REFERENCES]->(dst)
      ON CREATE SET r.mechanism = $mechanism,
                    r.source_text_unit = $tu_id
    """
    await session.run(cypher, **params)


# Allow Any in the function signature without a full neo4j import at module level
from typing import Any  # noqa: E402 (below other imports — intentional)
