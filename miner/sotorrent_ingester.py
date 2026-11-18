"""
SOTorrent Ingester — Stack Overflow Posts (Q&A) dataset (v0.8).

Dataset paper (see dataset_papers/):
  Baltes et al., "SOTorrent: Reconstructing and Analyzing the Evolution of
  Stack Overflow Content", MSR 2018.
Local archive:
  /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/SOTorrent/Posts.sql.7z

SCOPE:
  We ingest Stack Overflow questions and answers from the Posts table dump.
  Post evolution tables (PostVersion, PostBlockVersion, PostBlockDiff, etc.)
  and extensive metadata are explicitly OUT OF SCOPE to focus on the authored
  natural-language discourse (title and post body).
  Deleted posts (DeletionDate IS NOT NULL) and non-Q/A posts (PostTypeId not in
  (1, 2)) are skipped.
  HTML formatting and code blocks (<pre>, <code>, <script>, <style>) are
  stripped to extract clean authored text, matching the text unit extractor's
  code-dropping policy.

STREAMING:
  The 14.4 GB .7z archive (67.7 GB uncompressed MySQL dump) is decompressed on the
  fly via a subprocess pipe (bsdtar or 7z) and parsed incrementally without
  loading the full file into memory or requiring a standalone MySQL instance.
  Early exit (--max) cleanly terminates the decompression subprocess.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import Any

from miner.external_common import (
    EXTERNAL_COLLECTION,
    _base_artefact,
    external_event,
    make_record_id,
    namespaced_login,
    run_external_ingest,
)
from settings import settings

logger = logging.getLogger("miner.sotorrent")

CORPUS_ID = "sotorrent"
PLATFORM_ID = "stackoverflow"
VENUE_ID = "stackoverflow:sotorrent"
DEFAULT_ARCHIVE = os.path.join("SOTorrent", "Posts.sql.7z")
DEFAULT_STRIDE = 7
DEFAULT_MIN_SCORE = 1


# ── HTML -> Clean Text ────────────────────────────────────────────────────────


class _HTMLTextExtractor(HTMLParser):
    """
    Lightweight HTML text extractor.
    Strips <pre>, <code>, <script>, and <style> elements (and their contents)
    so that source code is excluded from Non-Knowledge linguistic analysis.
    Adds newlines around block elements.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0
        self._skip_tags = {"script", "style", "pre", "code"}
        self._block_tags = {
            "p",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "tr",
            "blockquote",
            "hr",
            "br",
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._skip_tags:
            self._skip_depth += 1
        elif tag_lower in self._block_tags:
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._skip_tags:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag_lower in self._block_tags:
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._pieces.append(data)

    def get_text(self) -> str:
        raw = "".join(self._pieces)
        lines = [line.strip() for line in raw.splitlines()]
        clean_lines: list[str] = []
        prev_empty = False
        for line in lines:
            if line:
                clean_lines.append(line)
                prev_empty = False
            elif not prev_empty:
                clean_lines.append("")
                prev_empty = True
        return "\n".join(clean_lines).strip()


def html_to_text(raw_html: str | None) -> str:
    """Strip HTML markup and code blocks, returning clean plain text."""
    if not raw_html:
        return ""
    parser = _HTMLTextExtractor()
    parser.feed(raw_html)
    return html.unescape(parser.get_text())


# ── MySQL dump parser ─────────────────────────────────────────────────────────


def parse_mysql_insert_tuples(line: str) -> Iterator[list[Any]]:
    """
    Parse the multi-row value tuples from a MySQL INSERT statement.
    Handles escaped characters (\\', \\n, \\\\, \\\", \\0, \\Z, \\t, \\r),
    quoted strings with commas/parentheses, NULLs, and integers/floats.
    """
    val_idx = line.find("VALUES")
    if val_idx == -1:
        val_idx = line.find("values")
        if val_idx == -1:
            return

    idx = val_idx + 6
    n = len(line)

    while idx < n:
        while idx < n and line[idx] != "(":
            if line[idx] == ";":
                return
            idx += 1
        if idx >= n:
            break

        idx += 1  # step inside '('
        row: list[Any] = []

        while idx < n:
            while idx < n and line[idx] in " \t\r\n":
                idx += 1
            if idx >= n:
                break

            c = line[idx]
            if c == ")":
                idx += 1
                yield row
                break
            elif c == ",":
                idx += 1
                continue
            elif c == "'":
                idx += 1
                str_chars: list[str] = []
                while idx < n:
                    ch = line[idx]
                    if ch == "\\" and idx + 1 < n:
                        nxt = line[idx + 1]
                        if nxt == "'":
                            str_chars.append("'")
                        elif nxt == '"':
                            str_chars.append('"')
                        elif nxt == "\\":
                            str_chars.append("\\")
                        elif nxt == "n":
                            str_chars.append("\n")
                        elif nxt == "r":
                            str_chars.append("\r")
                        elif nxt == "t":
                            str_chars.append("\t")
                        elif nxt == "0":
                            str_chars.append("\0")
                        elif nxt == "Z":
                            str_chars.append("\x1a")
                        elif nxt == "b":
                            str_chars.append("\b")
                        else:
                            str_chars.append(nxt)
                        idx += 2
                        continue
                    elif ch == "'":
                        if idx + 1 < n and line[idx + 1] == "'":
                            str_chars.append("'")
                            idx += 2
                            continue
                        else:
                            idx += 1
                            break
                    else:
                        str_chars.append(ch)
                        idx += 1
                row.append("".join(str_chars))
            else:
                start = idx
                while idx < n and line[idx] not in ",) \t\r\n":
                    idx += 1
                token = line[start:idx]
                token_upper = token.upper()
                if token_upper == "NULL":
                    row.append(None)
                elif token.isdigit() or (token.startswith("-") and token[1:].isdigit()):
                    row.append(int(token))
                else:
                    try:
                        row.append(float(token))
                    except ValueError:
                        row.append(token)


def _format_iso_datetime(val: Any) -> str | None:
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    if " " in s and "T" not in s:
        s = s.replace(" ", "T")
    if not s.endswith("Z"):
        s += "Z"
    return s


def _get_stream_proc(path: str) -> tuple[subprocess.Popen | None, Any]:
    """
    Open line-oriented reader for path.
    If path is a .7z archive, streams output from bsdtar or 7z.
    """
    if path.endswith(".7z"):
        decompressor = (
            shutil.which("bsdtar")
            or shutil.which("7zz")
            or shutil.which("7z")
            or shutil.which("7za")
        )
        if not decompressor:
            raise RuntimeError(
                f"Cannot decompress {path}: neither 'bsdtar' nor '7z/7za/7zz' was found in PATH."
            )
        cmd = (
            [decompressor, "-xOf", path]
            if os.path.basename(decompressor) == "bsdtar"
            else [decompressor, "x", "-so", path]
        )
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc, proc.stdout
    fh = open(path, encoding="utf-8", errors="replace")
    return None, fh


def iter_sotorrent_records(
    path: str,
    *,
    stride: int = DEFAULT_STRIDE,
    min_score: int | None = DEFAULT_MIN_SCORE,
) -> Iterator[dict[str, Any]]:
    """
    Stream posts from SOTorrent Posts.sql (.7z or plain SQL), yielding
    normalized raw documents.

    Applies systematic temporal stride sampling (1 in `stride` posts across the
    chronological stream) and an optional minimum quality score threshold (`min_score`).
    """
    proc, stream = _get_stream_proc(path)
    cols: list[str] = []
    in_create = False
    schema_done = False
    in_insert = False
    insert_buffer: list[str] = []

    try:
        for line in stream:
            if not schema_done:
                if not in_create:
                    if "CREATE TABLE `Posts`" in line or "CREATE TABLE Posts" in line:
                        in_create = True
                    continue
                stripped = line.strip()
                if (
                    stripped.startswith(")")
                    or stripped.startswith("PRIMARY KEY")
                    or stripped.startswith("KEY ")
                    or stripped.startswith("CONSTRAINT")
                    or stripped.startswith("UNIQUE KEY")
                ):
                    if stripped.startswith(")") or stripped.startswith("PRIMARY KEY"):
                        schema_done = True
                    continue
                m = re.match(r"^\s*`?([a-zA-Z0-9_]+)`?\s+", line)
                if m:
                    cols.append(m.group(1))
                continue

            # Process INSERT statements (handles single-line and multi-line statements)
            if not in_insert:
                if "INSERT INTO `Posts`" in line or "INSERT INTO Posts" in line:
                    if line.rstrip().endswith(";"):
                        stmt = line
                    else:
                        in_insert = True
                        insert_buffer = [line]
                        continue
                else:
                    continue
            else:
                insert_buffer.append(line)
                if line.rstrip().endswith(";"):
                    in_insert = False
                    stmt = "".join(insert_buffer)
                    insert_buffer = []
                else:
                    continue

            for row in parse_mysql_insert_tuples(stmt):
                if len(row) != len(cols):
                    logger.warning(
                        "Row length mismatch: expected %d columns, got %d; skipping row.",
                        len(cols),
                        len(row),
                    )
                    continue
                d = dict(zip(cols, row, strict=True))

                post_type_id = d.get("PostTypeId")
                if post_type_id not in (1, 2):
                    continue
                if d.get("DeletionDate") is not None:
                    continue

                post_id = d.get("Id")
                if post_id is None:
                    continue

                # Stratification: systematic temporal stride across the chronological stream
                if stride > 1 and int(post_id) % stride != 0:
                    continue

                # Quality filter: skip downvoted/zero-score posts if min_score is set
                score = d.get("Score")
                if min_score is not None:
                    if score is None or score < min_score:
                        continue

                is_question = post_type_id == 1
                post_type = "question" if is_question else "answer"
                label = "StackOverflowQuestion" if is_question else "StackOverflowAnswer"
                labels = ["Artefact", "PostArtefact", label]
                record_id = make_record_id("so_post", CORPUS_ID, post_id)

                owner_id = d.get("OwnerUserId")
                author_login = (
                    namespaced_login(PLATFORM_ID, CORPUS_ID, owner_id)
                    if owner_id is not None
                    else None
                )
                created_at = _format_iso_datetime(d.get("CreationDate"))

                title = d.get("Title") if is_question else None
                body_html = d.get("Body") or ""
                clean_text = html_to_text(body_html)
                if not clean_text and not title:
                    continue

                parent_id = d.get("ParentId")
                question_id = (
                    str(post_id) if is_question else (str(parent_id) if parent_id else None)
                )
                parent_post_id = str(parent_id) if (not is_question and parent_id) else None
                question_record_id = (
                    make_record_id("so_post", CORPUS_ID, parent_id)
                    if (not is_question and parent_id)
                    else None
                )

                doc = _base_artefact(
                    record_id=record_id,
                    platform_id=PLATFORM_ID,
                    corpus_id=CORPUS_ID,
                    venue_id=VENUE_ID,
                    artefact_kind=f"so_{post_type}",
                    author_login=author_login,
                    created_at=created_at,
                    labels=labels,
                    source_file=os.path.basename(path),
                    metadata={
                        "post_type_id": post_type_id,
                        "score": d.get("Score"),
                        "view_count": d.get("ViewCount"),
                        "tags": d.get("Tags"),
                        "answer_count": d.get("AnswerCount"),
                        "comment_count": d.get("CommentCount"),
                        "favorite_count": d.get("FavoriteCount"),
                        "accepted_answer_id": d.get("AcceptedAnswerId"),
                    },
                )
                doc.update(
                    {
                        "title": title,
                        "text": clean_text,
                        "post_type": post_type,
                        "external_id": str(post_id),
                        "question_id": question_id,
                        "parent_post_id": parent_post_id,
                        "question_record_id": question_record_id,
                        "score": d.get("Score"),
                    }
                )
                yield doc
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        elif hasattr(stream, "close"):
            stream.close()


def _event_for(doc: dict[str, Any], mongo_id: str) -> dict[str, Any]:
    return external_event(
        "so_post",
        doc["venue_id"],
        mongo_id,
        platform_id=PLATFORM_ID,
        corpus_id=CORPUS_ID,
        venue_id=doc["venue_id"],
        artefact_kind=doc["artefact_kind"],
        artefact_labels=doc["artefact_labels"],
    )


async def ingest(
    path: str | None = None,
    max_records: int | None = None,
    dry_run: bool = False,
    stride: int = DEFAULT_STRIDE,
    min_score: int | None = DEFAULT_MIN_SCORE,
) -> int:
    path = path or os.path.join(settings.datasets_root, DEFAULT_ARCHIVE)
    if not os.path.exists(path):
        raise SystemExit(f"Archive not found: {path}")

    return await run_external_ingest(
        docs=iter_sotorrent_records(path, stride=stride, min_score=min_score),
        collection=EXTERNAL_COLLECTION,
        key_field="record_id",
        event_for=_event_for,
        label=f"Ingest SOTorrent Posts (stride={stride}, min_score={min_score})",
        max_records=max_records,
        dry_run=dry_run,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest SOTorrent Stack Overflow Posts dataset.")
    p.add_argument(
        "--path",
        "--archive",
        dest="path",
        default=None,
        help="Path to Posts.sql.7z or Posts.sql",
    )
    p.add_argument(
        "--stride",
        type=int,
        default=DEFAULT_STRIDE,
        help=f"Temporal sampling stride (default: {DEFAULT_STRIDE} for ~5M sample; 1 for all).",
    )
    p.add_argument(
        "--min-score",
        type=int,
        default=DEFAULT_MIN_SCORE,
        help=f"Minimum score threshold (default: {DEFAULT_MIN_SCORE}; negative to disable).",
    )
    p.add_argument(
        "--max",
        type=int,
        default=None,
        help="Maximum number of records to ingest/scan.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count without writing.",
    )
    args = p.parse_args()

    min_score = args.min_score if args.min_score is not None and args.min_score >= 0 else None
    asyncio.run(
        ingest(
            path=args.path,
            max_records=args.max,
            dry_run=args.dry_run,
            stride=args.stride,
            min_score=min_score,
        )
    )


if __name__ == "__main__":
    main()
