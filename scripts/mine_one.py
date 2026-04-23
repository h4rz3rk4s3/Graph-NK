#!/usr/bin/env python3
"""
scripts/mine_one.py

Thin CLI wrapper around AsyncGitHubMiner.
Mines a single repository (or a list from a file) and exits.

Usage:
    python scripts/mine_one.py --repo python/cpython
    python scripts/mine_one.py --repo python/cpython --no-commits
    python scripts/mine_one.py --repo-file repos.txt   # one repo per line
    python scripts/mine_one.py --repo python/cpython --max-items 50
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from miner.async_miner import AsyncGitHubMiner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("mine_one")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mine one or more GitHub repositories.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo", help="Repository in owner/name format")
    group.add_argument("--repo-file", help="File with one repo per line")
    p.add_argument("--no-commits", action="store_true", help="Skip commit mining")
    p.add_argument(
        "--max-items", type=int, default=0,
        help="(Debug) limit total items mined per collection. 0 = unlimited.",
    )
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    repos: list[str] = []
    if args.repo:
        repos = [args.repo.strip()]
    else:
        repos = [
            line.strip()
            for line in Path(args.repo_file).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]

    include_commits = not args.no_commits
    logger.info("Mining %d repo(s). include_commits=%s", len(repos), include_commits)

    async with AsyncGitHubMiner() as miner:
        await miner.mine_repositories(repos, include_commits=include_commits)

    logger.info("Mining complete.")


if __name__ == "__main__":
    asyncio.run(main())
