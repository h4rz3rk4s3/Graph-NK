"""
Module 2 — TextUnitExtractor (pure functions).

Responsibility: split a raw GitHub document (issue, PR, commit, or comment)
into TextUnit objects, one per (artefact, role). No I/O here — all I/O is
in extractor/worker.py.

TextUnit granularity (v0): one unit per (parent, role). Sentence-level
splitting is deferred to v1. See BUILD_SPEC.md §1 locked decisions and
FRAMEWORK_DESIGN.md §5 Module 2.

Stripping rules (FRAMEWORK_DESIGN.md §5 Module 2):
  - Remove > quoted blocks (GitHub reply quoting)
  - Remove fenced code blocks (``` ... ```)
  - Remove @mentions
  - Remove image tags (![...](...)
  - Remove inline code spans (`...`) — preserve surrounding words
  - Preserve typos, casing, punctuation
  - Skip units whose text is empty after stripping
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# ── stripping regexes ────────────────────────────────────────────────────────

_RE_FENCED_CODE    = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_RE_INLINE_CODE    = re.compile(r"`[^`\n]+`")
_RE_BLOCKQUOTE     = re.compile(r"(?m)^>.*$")
_RE_IMAGE          = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RE_MENTION        = re.compile(r"@\w+")
_RE_HTML_COMMENT   = re.compile(r"<!--[\s\S]*?-->")
_RE_MULTI_NEWLINE  = re.compile(r"\n{3,}")


@dataclass(slots=True)
class TextUnit:
    """
    Atomic unit of NK analysis. All annotation targets TextUnits.
    Shape mirrors BUILD_SPEC.md §4.2.
    """
    text_unit_id: str        # "{parent_id}:{role}" or "{parent_id}:{role}:{position}"
    parent_id:    str        # e.g. "issue:python/cpython:12345"
    parent_type:  str        # "issue" | "pull_request" | "commit" | "comment"
    repo:         str
    parent_number: int | None
    role:         str        # "title" | "body" | "commit_message" | "comment_body"
    position:     int        # 0=title, 1=body, 2+=comments in order
    text:         str        # stripped text
    lang:         str | None # detected language code
    token_count:  int        # whitespace-split estimate
    sha256:       str        # sha256(text) for dedup
    author_login: str | None
    created_at:   str | None


def strip_text(raw: str) -> str:
    """
    Apply all stripping rules in order.
    Returns stripped text, or empty string if nothing remains.
    """
    text = raw or ""
    text = _RE_HTML_COMMENT.sub("", text)
    text = _RE_FENCED_CODE.sub("", text)
    text = _RE_INLINE_CODE.sub("", text)
    text = _RE_BLOCKQUOTE.sub("", text)
    text = _RE_IMAGE.sub("", text)
    text = _RE_MENTION.sub("", text)
    text = _RE_MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def _detect_lang(text: str) -> str | None:
    """
    Detect language using fasttext-langdetect.
    Returns ISO 639-1 code (e.g. 'en') or None on failure.
    Imported lazily — not every caller needs it.
    """
    try:
        from fasttext_langdetect import detect  # type: ignore[import]
        result = detect(text[:1000], low_memory=True)  # first 1000 chars are enough
        return result.get("lang")
    except Exception:
        return None


def _make_unit(
    *,
    parent_id: str,
    parent_type: str,
    repo: str,
    parent_number: int | None,
    role: str,
    position: int,
    raw_text: str,
    author_login: str | None,
    created_at: str | None,
) -> TextUnit | None:
    """
    Strip raw_text, detect language, compute sha256, and build a TextUnit.
    Returns None if the stripped text is empty.
    """
    text = strip_text(raw_text)
    if not text:
        return None

    # Position is part of the ID only for comments (position >= 2)
    if position >= 2:
        text_unit_id = f"{parent_id}:{role}:{position}"
    else:
        text_unit_id = f"{parent_id}:{role}"

    lang = _detect_lang(text) if len(text) >= 10 else None
    sha256 = hashlib.sha256(text.encode()).hexdigest()
    token_count = len(text.split())

    return TextUnit(
        text_unit_id=text_unit_id,
        parent_id=parent_id,
        parent_type=parent_type,
        repo=repo,
        parent_number=parent_number,
        role=role,
        position=position,
        text=text,
        lang=lang,
        token_count=token_count,
        sha256=sha256,
        author_login=author_login,
        created_at=created_at,
    )


# ── Public extraction functions ───────────────────────────────────────────────

def extract_from_issue(doc: dict, repo: str) -> list[TextUnit]:
    """
    Extract TextUnits from a raw issue document (as stored in MongoDB).
    Handles both plain issues and issues where pull_request key is present
    (the miner item_subtype field tells us the actual type).
    """
    number = doc.get("number")
    parent_type = "pull_request" if "pull_request" in doc else "issue"
    prefix = "pr" if parent_type == "pull_request" else "issue"
    parent_id = f"{prefix}:{repo}:{number}"

    author = _actor(doc.get("user"))
    created_at = doc.get("created_at")

    units: list[TextUnit] = []

    # Title (position 0)
    if title := doc.get("title"):
        u = _make_unit(
            parent_id=parent_id, parent_type=parent_type, repo=repo,
            parent_number=number, role="title", position=0,
            raw_text=title, author_login=author, created_at=created_at,
        )
        if u:
            units.append(u)

    # Body (position 1)
    if body := doc.get("body"):
        u = _make_unit(
            parent_id=parent_id, parent_type=parent_type, repo=repo,
            parent_number=number, role="body", position=1,
            raw_text=body, author_login=author, created_at=created_at,
        )
        if u:
            units.append(u)

    # Comments (position 2, 3, ...)
    for i, comment in enumerate(doc.get("comments_data", []), start=2):
        u = _make_unit(
            parent_id=parent_id, parent_type=parent_type, repo=repo,
            parent_number=number, role="comment_body", position=i,
            raw_text=comment.get("body", ""),
            author_login=_actor(comment.get("user")),
            created_at=comment.get("created_at"),
        )
        if u:
            units.append(u)

    return units


def extract_from_pull_request(doc: dict, repo: str) -> list[TextUnit]:
    """
    Extract TextUnits from a raw pull request document.
    PR bodies and comments are annotated separately from issue comments
    because their discourse function differs (code review vs. feature request).
    """
    number = doc.get("number")
    parent_id = f"pr:{repo}:{number}"
    author = _actor(doc.get("user"))
    created_at = doc.get("created_at")

    units: list[TextUnit] = []

    if title := doc.get("title"):
        u = _make_unit(
            parent_id=parent_id, parent_type="pull_request", repo=repo,
            parent_number=number, role="title", position=0,
            raw_text=title, author_login=author, created_at=created_at,
        )
        if u:
            units.append(u)

    if body := doc.get("body"):
        u = _make_unit(
            parent_id=parent_id, parent_type="pull_request", repo=repo,
            parent_number=number, role="body", position=1,
            raw_text=body, author_login=author, created_at=created_at,
        )
        if u:
            units.append(u)

    # Code-review comments (comments_data) and issue-level comments (issue_comments_data)
    # are both annotated as "comment_body" — their kind is preserved in the graph at
    # the parent Comment node level, not at the TextUnit level.
    combined_comments = (
        list(doc.get("comments_data", []))
        + list(doc.get("issue_comments_data", []))
    )
    for i, comment in enumerate(combined_comments, start=2):
        u = _make_unit(
            parent_id=parent_id, parent_type="pull_request", repo=repo,
            parent_number=number, role="comment_body", position=i,
            raw_text=comment.get("body", ""),
            author_login=_actor(comment.get("user")),
            created_at=comment.get("created_at"),
        )
        if u:
            units.append(u)

    return units


def extract_from_commit(doc: dict, repo: str) -> list[TextUnit]:
    """
    Extract TextUnits from a raw commit document.
    One unit per commit: the commit message (subject + body).
    """
    sha = doc.get("sha", "")
    parent_id = f"commit:{sha}"
    raw_message = (doc.get("commit") or {}).get("message", "")
    author = _commit_author(doc)
    committed_at = ((doc.get("commit") or {}).get("committer") or {}).get("date")

    units: list[TextUnit] = []

    u = _make_unit(
        parent_id=parent_id, parent_type="commit", repo=repo,
        parent_number=None, role="commit_message", position=0,
        raw_text=raw_message, author_login=author, created_at=committed_at,
    )
    if u:
        units.append(u)

    return units


# ── Helpers ───────────────────────────────────────────────────────────────────

def _actor(user_obj: dict | None) -> str | None:
    if not user_obj:
        return None
    return user_obj.get("login")


def _commit_author(doc: dict) -> str | None:
    """Prefer GitHub-linked author login; fall back to commit author name."""
    if author_obj := doc.get("author"):
        if login := author_obj.get("login"):
            return login
    commit_author = (doc.get("commit") or {}).get("author") or {}
    return commit_author.get("name")
