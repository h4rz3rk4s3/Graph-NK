"""
Module 1 — Async GitHub Miner (Producer)

Responsibilities:
  1. Fetch Repositories, Issues (+comments), PRs (+reviews+comments), Commits
     from the GitHub REST API using asyncio + aiohttp.
  2. Persist the raw JSON payload to MongoDB (Data Lake) immediately.
  3. Publish a lightweight event {item_id, item_type, repo_name, mongo_id}
     to the Redis Stream so that downstream workers can process it.

Rate-limit safety:
  - Reads X-RateLimit-Remaining / X-RateLimit-Reset headers on every response.
  - Pauses when remaining ≤ settings.rate_limit_margin.
  - Exponential backoff on 5xx; hard-stop on 401/404 (configuration errors).
  - 403 triggers a full wait-until-reset (secondary rate limit / abuse detection).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient

from broker import get_broker
from settings import settings

logger = logging.getLogger("graphrag_nk.miner")

BASE_URL = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"

# HTTP status codes where we should NOT retry
_NO_RETRY = {401, 404, 422}


# ──────────────────────────────────────────────────────────────────────────────
# Rate-Limit State (shared across all concurrent coroutines via an asyncio.Lock)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _RateLimitState:
    remaining: int = 5_000
    reset_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def maybe_wait(self) -> None:
        async with self.lock:
            if self.remaining <= settings.rate_limit_margin:
                wait = max(0.0, self.reset_at - time.time()) + 1.0
                logger.warning(
                    "Rate limit low (%d remaining). Sleeping %.1fs.", self.remaining, wait
                )
                await asyncio.sleep(wait)

    def update(self, headers: dict) -> None:
        if "X-RateLimit-Remaining" in headers:
            self.remaining = int(headers["X-RateLimit-Remaining"])
        if "X-RateLimit-Reset" in headers:
            self.reset_at = float(headers["X-RateLimit-Reset"])


# ──────────────────────────────────────────────────────────────────────────────
# Main Miner Class
# ──────────────────────────────────────────────────────────────────────────────

class AsyncGitHubMiner:
    """
    Async producer that mines GitHub and publishes raw events to the broker.
    All processing happens *downstream* in dedicated workers — this class is
    intentionally thin and fast.
    """

    def __init__(self) -> None:
        self._token = settings.github_token
        self._rl = _RateLimitState()
        self._session: Optional[aiohttp.ClientSession] = None
        self._mongo: Optional[AsyncIOMotorClient] = None
        self._db = None
        self._broker = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "AsyncGitHubMiner":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.stop()

    async def start(self) -> None:
        headers = {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GraphRAG-NK-Miner/2.0",
        }
        connector = aiohttp.TCPConnector(
            limit=settings.concurrent_requests,
            ssl=True,
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(total=60, connect=10)
        self._session = aiohttp.ClientSession(
            headers=headers, connector=connector, timeout=timeout
        )

        self._mongo = AsyncIOMotorClient(settings.mongo_uri)
        self._db = self._mongo[settings.mongo_db_name]

        self._broker = await get_broker()
        logger.info("AsyncGitHubMiner started.")

    async def stop(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        if self._mongo:
            self._mongo.close()
        logger.info("AsyncGitHubMiner stopped.")

    # ── core request ──────────────────────────────────────────────────────────

    async def _request(
        self,
        url: str,
        params: Optional[dict] = None,
        method: str = "GET",
        json_body: Optional[dict] = None,
        retries: int = 0,
    ) -> tuple[Any, dict]:
        """
        Single resilient HTTP request. Returns (parsed_json, link_headers).
        Raises on unrecoverable errors.
        """
        await self._rl.maybe_wait()
        logging.info("Requesting URL: %s", url)
        try:
            async with self._session.request(
                method, url, params=params, json=json_body
            ) as resp:
                # Update rate-limit state from every response
                self._rl.update(dict(resp.headers))

                links = _parse_link_header(resp.headers.get("Link", ""))

                if resp.status == 204:
                    return None, links

                if resp.status in _NO_RETRY:
                    text = await resp.text()
                    raise ValueError(f"HTTP {resp.status} (unrecoverable): {url} — {text[:200]}")

                if resp.status == 403:
                    # Secondary rate limit — wait until reset
                    wait = max(0.0, self._rl.reset_at - time.time()) + 5.0
                    logger.warning("HTTP 403 on %s. Waiting %.1fs for reset.", url, wait)
                    #logger.warning("Response: %s", resp)
                    await asyncio.sleep(wait)
                    return await self._request(url, params, method, json_body, retries + 1)

                if resp.status >= 500:
                    if retries >= settings.max_retries:
                        resp.raise_for_status()
                    backoff = min(2 ** retries, 60)
                    logger.warning("HTTP %d on %s. Backoff %.1fs.", resp.status, url, backoff)
                    await asyncio.sleep(backoff)
                    return await self._request(url, params, method, json_body, retries + 1)

                resp.raise_for_status()
                return await resp.json(), links

        except aiohttp.ClientError as exc:
            if retries >= settings.max_retries:
                raise
            backoff = min(2 ** retries, 60)
            logger.warning("Client error on %s: %s. Retry in %.1fs.", url, exc, backoff)
            await asyncio.sleep(backoff)
            return await self._request(url, params, method, json_body, retries + 1)

    # ── pagination helper ─────────────────────────────────────────────────────

    async def _paginate(
        self, endpoint: str, params: Optional[dict] = None
    ) -> AsyncIterator[list[dict]]:
        """Async generator yielding pages of results."""
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        p = dict(params or {})
        p.setdefault("per_page", 100)
        page = 1

        while url:
            logger.debug("Fetching page %d: %s", page, endpoint)
            data, links = await self._request(url, p)

            if data is None:  # 204
                break

            items: list[dict] = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("items", [data])

            if not items:
                break

            yield items

            next_url = links.get("next")
            url = next_url or None
            p = None  # next URL already contains params
            page += 1

    # ── public mining methods ─────────────────────────────────────────────────

    async def mine_repository(self, repo_full_name: str, include_commits: bool = True) -> None:
        """Entry point: mine one repository end-to-end."""
        logger.info("▶ Mining: %s", repo_full_name)

        tasks = [
            self._mine_metadata(repo_full_name),
            self._mine_issues(repo_full_name),
            self._mine_pull_requests(repo_full_name),
        ]
        if include_commits:
            tasks.append(self._mine_commits(repo_full_name))

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("✔ Completed: %s", repo_full_name)

    async def mine_repositories(
        self, repo_list: list[str], include_commits: bool = True
    ) -> None:
        """Mine multiple repos with bounded concurrency."""
        sem = asyncio.Semaphore(settings.concurrent_requests)

        async def bounded(repo: str) -> None:
            async with sem:
                try:
                    await self.mine_repository(repo, include_commits)
                except Exception as exc:
                    logger.error("Failed to mine %s: %s", repo, exc)

        await asyncio.gather(*(bounded(r) for r in repo_list))

    # ── private fetch+publish helpers ─────────────────────────────────────────

    async def _mine_metadata(self, repo_full_name: str) -> None:
        url = f"{BASE_URL}/repos/{repo_full_name}"
        data, _ = await self._request(url)
        if data:
            await self._save_and_publish("repository", repo_full_name, data)

    async def _mine_issues(self, repo_full_name: str) -> None:
        endpoint = f"repos/{repo_full_name}/issues"
        params = {"state": "all", "sort": "updated", "direction": "desc"}
        seen_ids: set[int] = set()

        async for page in self._paginate(endpoint, params):
            tasks = []
            for issue in page:
                if issue["id"] in seen_ids:
                    continue
                seen_ids.add(issue["id"])
                tasks.append(self._enrich_and_publish_issue(repo_full_name, issue))
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Issues done for %s (%d total).", repo_full_name, len(seen_ids))

    async def _enrich_and_publish_issue(self, repo_full_name: str, issue: dict) -> None:
        # Fetch comments if any
        if issue.get("comments", 0) > 0:
            comments_url = f"{BASE_URL}/repos/{repo_full_name}/issues/{issue['number']}/comments"
            comments, _ = await self._request(comments_url)
            issue["comments_data"] = comments or []

        issue_type = "pull_request" if "pull_request" in issue else "issue"
        await self._save_and_publish(issue_type, repo_full_name, issue)

    async def _mine_pull_requests(self, repo_full_name: str) -> None:
        endpoint = f"repos/{repo_full_name}/pulls"
        seen_ids: set[int] = set()

        for state in ("open", "closed"):
            async for page in self._paginate(endpoint, {"state": state}):
                tasks = []
                for pr in page:
                    if pr["id"] in seen_ids:
                        continue
                    seen_ids.add(pr["id"])
                    tasks.append(self._enrich_and_publish_pr(repo_full_name, pr))
                await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("PRs done for %s (%d total).", repo_full_name, len(seen_ids))

    async def _enrich_and_publish_pr(self, repo_full_name: str, pr: dict) -> None:
        pr_number = pr["number"]

        # Reviews
        #reviews_url = f"{BASE_URL}/repos/{repo_full_name}/pulls/{pr_number}/reviews"
        #reviews, _ = await self._request(reviews_url)
        #pr["reviews_data"] = reviews or []

        # Comments (code review comments)
        comments_url = f"{BASE_URL}/repos/{repo_full_name}/pulls/{pr_number}/comments"
        comments, _ = await self._request(comments_url)
        pr["comments_data"] = comments or []

        # Issue-level comments
        issue_comments_url = f"{BASE_URL}/repos/{repo_full_name}/issues/{pr_number}/comments"
        issue_comments, _ = await self._request(issue_comments_url)
        pr["issue_comments_data"] = issue_comments or []

        await self._save_and_publish("pull_request", repo_full_name, pr)

    async def _mine_commits(self, repo_full_name: str) -> None:
        endpoint = f"repos/{repo_full_name}/commits"
        count = 0

        async for page in self._paginate(endpoint):
            for commit in page:
                await self._save_and_publish("commit", repo_full_name, commit)
                count += 1

        logger.info("Commits done for %s (%d total).", repo_full_name, count)

    # ── persistence + event publishing ────────────────────────────────────────

    async def _save_and_publish(
        self, item_type: str, repo_full_name: str, data: dict
    ) -> None:
        """
        Persist raw payload to MongoDB, then publish a lightweight event
        to the message broker. This is the only coupling between modules.
        """
        collection = self._db[_collection_for(item_type)]

        # M1 tweak 1: stable content hash for downstream dedup
        content_sha256 = hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str).encode()
        ).hexdigest()

        # Upsert raw payload
        mongo_result = await collection.update_one(
            {"id": data.get("id") or data.get("sha") or data.get("number")},
            {
                "$set": {
                    **data,
                    "_meta": {
                        "item_type": item_type,
                        "repo_full_name": repo_full_name,
                        "mined_at": _utcnow(),
                        "processed": False,
                        "content_sha256": content_sha256,  # M1 tweak 1
                    },
                }
            },
            upsert=True,
        )
        mongo_id = str(
            mongo_result.upserted_id
            or (await collection.find_one({"id": data.get("id") or data.get("sha")}, {"_id": 1}))["_id"]
        )

        # M1 tweak 2: expose PR vs plain-issue distinction so downstream
        # workers don't need a Mongo round-trip to determine the subtype.
        if item_type == "issue":
            item_subtype = "pull_request" if "pull_request" in data else "issue"
        else:
            item_subtype = item_type

        # Publish event — deliberately minimal: workers pull full data from Mongo
        event = {
            "item_id":      str(data.get("id") or data.get("sha") or data.get("number")),
            "item_type":    item_type,
            "item_subtype": item_subtype,  # M1 tweak 2
            "repo_name":    repo_full_name,
            "mongo_id":     mongo_id,
        }
        await self._broker.publish(settings.stream_raw, event)
        logger.debug("Published event for %s/%s", item_type, event["item_id"])


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _collection_for(item_type: str) -> str:
    return {
        "repository":  "raw_repositories",
        "issue":       "raw_issues",
        "pull_request": "raw_pull_requests",
        "commit":      "raw_commits",
    }.get(item_type, "raw_misc")


def _parse_link_header(header: str) -> dict[str, str]:
    """Parse RFC 5988 Link headers → {rel: url}."""
    result: dict[str, str] = {}
    for url, rel in re.findall(r'<([^>]+)>;\s*rel="([^"]+)"', header):
        result[rel] = url
    return result


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
