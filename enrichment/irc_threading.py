"""
IRC reply-threading enrichment (v0.8) — creates REPLIES_TO edges.

The Kummerfeld IRC ingester stores each message doc's documented reply targets
as `reply_to` (a list of record_ids) in the raw_external Mongo collection. This
pass reads those refs and draws (message)-[:REPLIES_TO]->(parent) edges once
both endpoints exist in the graph — the counterpart of enrichment/email_threading
and GitHub REFERENCES. Runs after ingestion; idempotent via MERGE.

Only edges whose parent endpoint already exists are drawn; dangling refs (parent
out of range / not yet ingested — see miner/irc_ingester.py) are reported but
never fabricated.
"""

from __future__ import annotations

import logging

from neo4j import AsyncGraphDatabase

from settings import settings
from storage import make_mongo_client

logger = logging.getLogger("enrichment.irc_threading")

IRC_CORPUS = "kummerfeld-irc"
EXTERNAL_COLLECTION = "raw_external"


async def run_irc_threading_enrichment() -> None:
    """Read IRC reply refs from Mongo and MERGE REPLIES_TO edges in Neo4j."""
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    mongo = make_mongo_client()
    total = dangling = 0
    try:
        coll = mongo[settings.mongo_db_name][EXTERNAL_COLLECTION]
        cursor = coll.find({"corpus_id": IRC_CORPUS, "reply_to": {"$exists": True, "$ne": None}})
        async for doc in cursor:
            child_id = doc.get("record_id")
            for parent_id in doc.get("reply_to") or []:
                async with driver.session() as session:
                    res = await session.run(
                        """
                        MATCH (child:ChatMessage {record_id: $child_id})
                        OPTIONAL MATCH (parent:Artefact {record_id: $parent_id})
                        WITH child, parent
                        WHERE parent IS NOT NULL
                        MERGE (child)-[:REPLIES_TO]->(parent)
                        RETURN count(*) AS made
                        """,
                        child_id=child_id,
                        parent_id=parent_id,
                    )
                    rec = await res.single()
                    made = rec["made"] if rec else 0
                    total += made
                    if not made and parent_id:
                        dangling += 1
        logger.info(
            "IRC threading: %d REPLIES_TO edges ensured; %d dangling refs "
            "(parent not in graph, skipped).",
            total,
            dangling,
        )
    finally:
        mongo.close()
        await driver.close()
