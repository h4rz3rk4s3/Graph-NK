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

import dataclasses
import hashlib
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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


def _resolve_email_offset_convention(text: str, segments: list[dict]) -> tuple[str, int, int]:
    """
    Determine which offset convention — "char", "utf8_bytes", or
    "utf16_units" — is MOST CONSISTENT with this document's segments, and
    return (convention, n_segments_valid_under_it, n_segments_total).

    Uses MAJORITY agreement, not unanimous agreement: a single malformed or
    corrupt segment (a genuine data-quality outlier) should not prevent the
    OTHER, mutually-consistent segments in the same document from being
    recovered correctly. The winning convention is applied uniformly to every
    segment; any segment that still fails to validate under the winning
    convention is treated as an isolated issue and skipped individually by
    the caller — it is not evidence against the chosen convention.

    Why per-document at all, rather than per-segment: the offset convention
    is produced by one segmentation pass over one document, so it is
    consistent across a document's segments. Picking a convention by
    majority vote across ALL of a document's segments — rather than asking
    "is THIS segment in bounds?" one at a time — is what avoids a real
    failure mode: an early segment with only small byte-offset drift can
    coincidentally still fall in-bounds under the WRONG convention on a long
    document, silently returning misaligned text with no error at all. Vote
    across every segment and that early segment's neighbours pull the
    decision the right way. See CHANGELOG 2026-07-14 (v0.6.1) and the
    regression test test_document_level_detection_avoids_silent_misalignment.

    Ties favour "char" (Webis's documented convention) over "utf8_bytes"
    (the next most common real-world cause) over "utf16_units" (rarer
    surrogate-pair drift, e.g. from a JVM/JS segmentation runtime).
    """
    spans = [
        (s.get("begin"), s.get("end")) for s in segments
        if isinstance(s.get("begin"), int) and isinstance(s.get("end"), int)
           and s.get("end") > s.get("begin") >= 0
    ]
    if not spans:
        return "char", 0, 0

    candidates = [
        ("char", len(text)),
        ("utf8_bytes", len(text.encode("utf-8"))),
        ("utf16_units", len(text.encode("utf-16-le")) // 2),
    ]
    best_name, best_count = "char", -1
    for name, limit in candidates:
        count = sum(1 for _begin, end in spans if end <= limit)
        if count > best_count:
            best_name, best_count = name, count
    return best_name, best_count, len(spans)


def _convert_span(text: str, begin: int, end: int, convention: str) -> tuple[int, int]:
    """Convert a (begin, end) span expressed in `convention` units to Python
    codepoint indices into `text`. `convention == "char"` is the identity."""
    if convention == "char":
        return begin, end
    if convention == "utf8_bytes":
        encoded = text.encode("utf-8")
        return (
            len(encoded[:begin].decode("utf-8", errors="ignore")),
            len(encoded[:end].decode("utf-8", errors="ignore")),
        )
    if convention == "utf16_units":
        encoded16 = text.encode("utf-16-le")
        return (
            len(encoded16[: begin * 2].decode("utf-16-le", errors="ignore")),
            len(encoded16[: end * 2].decode("utf-16-le", errors="ignore")),
        )
    raise ValueError(f"Unknown offset convention: {convention}")


# Tolerance for the trailing-overshoot clamp below. Confirmed against real
# corpus data (scripts/diagnose_email_spans.py, CHANGELOG 2026-07-14 v0.6.2):
# a segment reaching the very end of a document sometimes overshoots
# len(text_plain) by exactly 1-2 characters — a trailing newline present when
# segmentation ran but stripped from the exported text_plain afterward, not
# truncation. Kept small and deliberate so it can't mask genuine truncation.
TRAILING_OVERSHOOT_TOLERANCE = 2


def _resolve_final_span(
    text: str, raw_begin: Any, raw_end: Any, convention: str
) -> tuple[int, int] | None:
    """
    Convert a raw segment span under `convention` and apply the trailing-
    overshoot clamp, returning Python codepoint indices ready for
    `text[begin:end]`, or None if the segment is invalid even after
    conversion and clamping.

    SINGLE SOURCE OF TRUTH: extract_from_email and
    scripts/diagnose_email_spans.py both call this exact function, so the
    diagnostic's report is always guaranteed to match what extraction
    actually does — no risk of the two drifting out of sync (as happened in
    v0.6.2, where the clamp was only added inline in extract_from_email and
    the diagnostic kept reporting pre-clamp numbers).
    """
    if not (isinstance(raw_begin, int) and isinstance(raw_end, int) and raw_end > raw_begin >= 0):
        return None
    begin, end = _convert_span(text, raw_begin, raw_end, convention)
    n = len(text)
    if 0 <= begin < n < end <= n + TRAILING_OVERSHOOT_TOLERANCE:
        end = n
    if not (0 <= begin < end <= n):
        return None
    return begin, end


def extract_from_email(doc: dict, repo: str) -> list[TextUnit]:
    """
    Extract TextUnits from a Webis Gmane email document (v0.6).

    Granularity (amends locked decision v0-1 for emails — see CHANGELOG
    2026-06-04 v0.6): one TextUnit PER SELECTED SEGMENT, using the corpus's
    pre-computed segment spans, plus the subject as its own unit at position 0.
    role = segment label; position = 1 + segment ordinal (in span order).

    Only segments whose label is in settings.email_segment_labels (default:
    paragraph, section_heading) become TextUnits. Excluding `quotation` is a
    methodological requirement, not an optimisation: quoted text repeats the
    PREVIOUS author's words, so NK signals inside quotes would be duplicated
    across every reply in a thread and attributed to the wrong author.
    Signatures, patches, logs, and raw code are not authored epistemic
    discourse and are likewise excluded by default.

    The email's own `lang` field (corpus-provided) is used for all units —
    it feeds the annotator's language scope filter directly.
    """
    urn = doc.get("urn") or ""
    if not urn:
        return []
    from settings import settings

    parent_id = f"email:{urn}"
    headers = doc.get("headers") or {}
    author = (headers.get("from") or "").strip() or None
    created_at = headers.get("date")
    lang = doc.get("lang")

    units: list[TextUnit] = []

    # Subject (position 0)
    if subject := headers.get("subject"):
        u = _make_unit(
            parent_id=parent_id, parent_type="email", repo=repo,
            parent_number=None, role="subject", position=0,
            raw_text=subject, author_login=author, created_at=created_at,
        )
        if u:
            # Corpus lang is authoritative for the message; subject inherits it.
            u = dataclasses.replace(u, lang=lang or u.lang)
            units.append(u)

    # Segments (positions 1..n, in span order)
    text_plain = doc.get("text_plain") or ""
    allowed = set(settings.email_segment_labels)
    segments = sorted(
        (s for s in (doc.get("segments") or []) if isinstance(s, dict)),
        key=lambda s: (s.get("begin", 0), s.get("end", 0)),
    )
    pos = 1
    convention, n_valid, n_total = _resolve_email_offset_convention(text_plain, list(segments))
    if n_total and n_valid < n_total:
        level = logger.warning if n_valid / n_total < 0.5 else logger.debug
        level(
            "email %s: best-fit offset convention '%s' validates %d/%d segments "
            "(the rest are treated as isolated data-quality issues and skipped "
            "individually below). Run scripts/diagnose_email_spans.py if this "
            "recurs often.", urn, convention, n_valid, n_total,
        )
    elif convention != "char":
        logger.debug("email %s: segments use %s offsets (converted uniformly)", urn, convention)

    for seg in segments:
        label = seg.get("label", "")
        if label not in allowed:
            continue
        raw_begin, raw_end = seg.get("begin"), seg.get("end")
        resolved = _resolve_final_span(text_plain, raw_begin, raw_end, convention)
        if resolved is None:
            logger.warning(
                "email %s: segment (%s..%s) invalid even under best-fit "
                "convention '%s'; skipping.", urn, raw_begin, raw_end, convention,
            )
            continue
        begin, end = resolved
        u = _make_unit(
            parent_id=parent_id, parent_type="email", repo=repo,
            parent_number=None, role=label, position=pos,
            raw_text=text_plain[begin:end],
            author_login=author, created_at=created_at,
        )
        if u:
            # Deterministic positional id for segment units (multiple segments
            # share a role, so the id must always carry the position).
            u = dataclasses.replace(
                u,
                text_unit_id=f"{parent_id}:{label}:{pos}",
                lang=lang or u.lang,
            )
            units.append(u)
            pos += 1

    return units
