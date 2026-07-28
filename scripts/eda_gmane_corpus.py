"""
Pre-ingest EDA for the Webis Gmane Email Corpus — choose a subset to ingest.

READ-ONLY. Touches no MongoDB, Redis, or Neo4j; it only streams the .gz files.
Run this BEFORE `python -m miner.gmane_ingester` to decide `--groups`.

WHY THIS REUSES PIPELINE CODE
    Records are read with miner.gmane_ingester.iter_bulk_records and filtered
    with record_in_scope — the ingester's own functions, resync tolerance and
    all. Segment spans are resolved with the extractor's own
    _resolve_email_offset_convention / _resolve_final_span, and text is
    stripped with its strip_text. So "estimated TextUnits" is what
    extract_from_email will ACTUALLY produce, not an idealised approximation.
    (This project has already been bitten once by a diagnostic that reimplemented
    extractor logic and silently drifted from it — CHANGELOG v0.6.3.)

TWO MODES
    inventory   Fast census over many files: which groups exist, how big, what
                languages, what date range. Run this first, on everything.
    profile     Deep dive on a shortlist of groups: threading, segment mix,
                register signals, TextUnit yield, span-convention health.
                Run this second, on the ~5-15 groups you are considering.

TYPICAL WORKFLOW
    # 1. What's in the corpus at all? (sample 1 in 50 for speed)
    python scripts/eda_gmane_corpus.py inventory \\
        --files webis-gmane-19-part01.gz --sample-rate 50 \\
        --out-csv eda_group_census_01.csv

    # 2. Deep-profile the shortlist (full scan of those groups)
    python scripts/eda_gmane_corpus.py profile \\
        --files webis-gmane-19-part01.gz \\
        --groups gmane.comp.python.devel \\
        --out-json eda_profile_01_python_devel.json

    # 3. Read the decision table, pick groups, then:
    python -m miner.gmane_ingester --files 'data/gmane/*.gz' \\
        --groups <chosen> --lang en

TWO SAMPLING TRAPS THIS SCRIPT WARNS ABOUT
    1. --max-per-file truncates at the HEAD of each file. If files are ordered
       chronologically (likely for an archive dump), that biases every date
       statistic toward early messages. Use --sample-rate for statistics and
       keep --max-per-file for smoke tests only. The script flags which one
       was used in its output.
    2. Thread resolution rate is only meaningful on a FULL scan of a group:
       when sampling, most in_reply_to targets are simply not in your sample,
       so the rate is a LOWER BOUND. Reported as such, never silently.

PROGRESS OUTPUT
    Progress goes to the logging module (stderr), so stdout stays clean — you
    can `> report.txt` and still watch the run. Every --log-every seconds
    (default 5):

      [2/7] part-001.gz  38.2% | scanned 124,300 kept 41,022 | 8,930 rec/s
            | file ETA 0:41 | ALL 12.4% ETA 7:22

    and on each file's completion, a line with the RUNNING accumulated totals
    (groups, messages, authors, estimated TextUnits). Percentages and ETAs are
    computed from compressed bytes consumed — the record count of a .gz is not
    knowable until it has been read, so bytes are the only basis for an ETA
    available from the start of a run. Use --quiet to suppress all of it.
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extractor.text_unit_extractor import (  # noqa: E402
    _resolve_email_offset_convention,
    _resolve_final_span,
    strip_text,
)
from miner.gmane_ingester import iter_bulk_records, record_in_scope  # noqa: E402
from progress import _fmt  # noqa: E402  — shared H:MM:SS formatter, not reimplemented
from settings import settings  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("eda.gmane")

PATH_TO_DATA = "/Volumes/Samsung SSD 990 PRO 4TB/Gmane_email_corpus/"

# Segment labels that indicate machine-generated content rather than authored
# discourse. A group dominated by these is a bug-tracker/commit feed, not a
# venue for the epistemic discourse this project studies.
MACHINE_LABELS = {"log_data", "patch", "raw_code", "tabular", "quotation_marker"}

# from-header fragments typical of automated senders. The Webis corpus
# anonymises from-strings, so this catches only what survives anonymisation —
# treat as a weak signal, corroborated by templated-subject rate below.
BOT_FROM_HINTS = ("noreply", "no-reply", "donotreply", "bugzilla", "jenkins",
                  "buildbot", "cron", "daemon", "mailer-daemon", "automated")

# Subject prefixes that mark templated/automated mail.
TEMPLATED_SUBJECT_RE = re.compile(
    r"^\s*(\[?(bug|issue)\s*\d+\]?|re:\s*\[?(bug|issue)\s*\d+\]?|"
    r"\[jira\]|\[github\]|build (failed|succeeded|broken)|"
    r"nightly|buildbot|jenkins|cron\b|svn commit|git commit|r\d+\s+-)",
    re.IGNORECASE,
)


def _mid_hash(message_id: str) -> bytes:
    """8-byte digest — stores millions of message-ids in bounded memory.
    Collision probability is negligible at corpus scale (<1e-9 for 10M ids)."""
    return hashlib.blake2b(message_id.strip().encode("utf-8", "replace"),
                           digest_size=8).digest()


def _n(x: float) -> str:
    """Thousands-separated integer."""
    return f"{int(x):,}"


def _size(n_bytes: float) -> str:
    """Adaptive byte-size formatting — a 900 KB file should not read '0 MB'."""
    if n_bytes >= 1_073_741_824:
        return f"{n_bytes / 1_073_741_824:,.1f} GB"
    if n_bytes >= 1_048_576:
        return f"{n_bytes / 1_048_576:,.0f} MB"
    if n_bytes >= 1024:
        return f"{n_bytes / 1024:,.0f} KB"
    return f"{int(n_bytes)} B"


class ScanProgress:
    """
    Progress for streaming gzip scans, reported against COMPRESSED BYTES.

    Why bytes and not records: the number of records in a .gz is unknown until
    it has been fully read, so a count-based bar (progress.Progress's
    fixed-total mode) cannot produce an ETA here. Compressed size is known
    upfront from the filesystem, and the reader reports its position via
    iter_bulk_records(progress_cb=...) — so fraction-complete, and therefore
    remaining time, is available from the first seconds of a run.

    Reports two ETAs because they answer different questions:
      - file ETA  — "how long until this file is done" (the user's question),
                    from this file's own byte rate.
      - total ETA — "how long until the whole run is done", from the overall
                    byte rate across every file scanned so far.

    Reuses progress._fmt for duration formatting rather than reimplementing it.
    Logs to the logging module (stderr), so stdout stays clean for the report
    tables and can be redirected without losing progress.
    """

    def __init__(self, paths: list[str], log_every_sec: float = 5.0, enabled: bool = True):
        self.paths = paths
        self.sizes = {p: os.path.getsize(p) for p in paths}
        self.total_bytes = max(sum(self.sizes.values()), 1)
        self.enabled = enabled
        self.every = log_every_sec
        self.run_start = time.monotonic()
        self.scanned = 0            # records read (all files)
        self.kept = 0               # records passing scope filters (all files)
        self.bytes_before = 0       # bytes in fully-completed files
        self._summary_fn = lambda: ""
        self._file = None
        self._file_idx = 0
        self._file_pos = 0
        self._file_scanned = 0
        self._file_kept = 0
        self._file_start = 0.0
        self._last_log = 0.0
        if enabled:
            logger.info("Scan start — %d file(s), %s compressed total",
                        len(paths), _size(self.total_bytes))

    def set_summary(self, fn) -> None:
        """fn() -> str describing what has been ACCUMULATED so far (groups,
        estimated units, ...). Shown on each file-completion line."""
        self._summary_fn = fn

    def start_file(self, path: str) -> None:
        self._file = path
        self._file_idx += 1
        self._file_pos = self._file_scanned = self._file_kept = 0
        self._file_start = time.monotonic()
        if self.enabled:
            logger.info("[%d/%d] %s — start (%s)", self._file_idx, len(self.paths),
                        Path(path).name, _size(self.sizes.get(path, 0)))

    def note_bytes(self, pos: int) -> None:
        """Callback handed to iter_bulk_records — compressed bytes consumed."""
        self._file_pos = pos

    def tick(self, kept: bool) -> None:
        self.scanned += 1
        self._file_scanned += 1
        if kept:
            self.kept += 1
            self._file_kept += 1
        self._maybe_log()

    def _maybe_log(self, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and (now - self._last_log) < self.every:
            return
        self._last_log = now

        size = max(self.sizes.get(self._file, 0), 1)
        pos = min(self._file_pos, size)
        file_elapsed = max(now - self._file_start, 1e-9)
        run_elapsed = max(now - self.run_start, 1e-9)

        file_pct = 100.0 * pos / size
        rec_rate = self._file_scanned / file_elapsed
        file_eta = ((size - pos) / (pos / file_elapsed)) if pos > 0 else None

        done_bytes = self.bytes_before + pos
        total_pct = 100.0 * done_bytes / self.total_bytes
        total_eta = (((self.total_bytes - done_bytes) / (done_bytes / run_elapsed))
                     if done_bytes > 0 else None)

        logger.info(
            "[%d/%d] %-22s %5.1f%% | scanned %s kept %s | %s rec/s | file ETA %s | ALL %5.1f%% ETA %s",
            self._file_idx, len(self.paths), Path(self._file or "").name[:22],
            file_pct, _n(self._file_scanned), _n(self._file_kept), _n(rec_rate),
            _fmt(file_eta), total_pct, _fmt(total_eta),
        )

    def finish_file(self) -> None:
        if self._file is None:
            return
        self.bytes_before += self.sizes.get(self._file, 0)
        if self.enabled:
            elapsed = time.monotonic() - self._file_start
            summary = self._summary_fn()
            logger.info(
                "[%d/%d] %s — done in %s: %s scanned, %s in scope%s",
                self._file_idx, len(self.paths), Path(self._file).name,
                _fmt(elapsed), _n(self._file_scanned), _n(self._file_kept),
                f" | ACCUMULATED: {summary}" if summary else "",
            )
        self._file = None

    def finish(self) -> None:
        if not self.enabled:
            return
        elapsed = time.monotonic() - self.run_start
        rate = self.scanned / elapsed if elapsed > 0 else 0.0
        logger.info("Scan complete — %s records read, %s in scope, in %s (%s rec/s)",
                    _n(self.scanned), _n(self.kept), _fmt(elapsed), _n(rate))
        if (summary := self._summary_fn()):
            logger.info("Accumulated: %s", summary)


def _parse_year(date_header: str | None) -> int | None:
    """Extract a 4-digit year from an RFC-2822-ish Date header, tolerantly.
    Full datetime parsing is unnecessary here — year granularity is what the
    subset decision needs (overlap with the GitHub corpus's time range)."""
    if not date_header:
        return None
    m = re.search(r"\b(19[7-9]\d|20[0-4]\d)\b", str(date_header))
    return int(m.group(1)) if m else None


# ══════════════════════════════════════════════════════════════════════════════
# Accumulators
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class InventoryStats:
    """Cheap per-group census — inventory mode."""
    messages: int = 0
    langs: Counter = field(default_factory=Counter)
    years: Counter = field(default_factory=Counter)

    def merge(self, other: "InventoryStats") -> None:
        self.messages += other.messages
        self.langs.update(other.langs)
        self.years.update(other.years)


@dataclass
class ProfileStats:
    """Deep per-group profile — profile mode."""
    messages: int = 0
    langs: Counter = field(default_factory=Counter)
    years: Counter = field(default_factory=Counter)

    # Community
    authors: set = field(default_factory=set)
    bot_from: int = 0
    templated_subject: int = 0

    # Threading (RQ6.5 viability)
    has_in_reply_to: int = 0
    message_ids: set = field(default_factory=set)     # 8-byte digests
    in_reply_to_refs: list = field(default_factory=list)

    # Segments / register
    segment_labels: Counter = field(default_factory=Counter)
    kept_segments: int = 0
    machine_segments: int = 0
    total_segments: int = 0

    # Span health (mirrors scripts/diagnose_email_spans.py, pre-ingest)
    convention: Counter = field(default_factory=Counter)
    kept_span_valid: int = 0
    kept_span_total: int = 0

    # Yield — what the pipeline will actually create
    est_text_units: int = 0
    est_annotatable_units: int = 0
    text_len_buckets: Counter = field(default_factory=Counter)
    total_text_chars: int = 0

    # Optional NK pre-screen (OFF by default — see --nk-prescreen)
    nk_hit_messages: int = 0

    def merge(self, other: "ProfileStats") -> None:
        self.messages += other.messages
        for name in ("langs", "years", "segment_labels", "convention", "text_len_buckets"):
            getattr(self, name).update(getattr(other, name))
        for name in ("bot_from", "templated_subject", "has_in_reply_to",
                     "kept_segments", "machine_segments", "total_segments",
                     "kept_span_valid", "kept_span_total", "est_text_units",
                     "est_annotatable_units", "total_text_chars", "nk_hit_messages"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.authors |= other.authors
        self.message_ids |= other.message_ids
        self.in_reply_to_refs.extend(other.in_reply_to_refs)


# ══════════════════════════════════════════════════════════════════════════════
# Scanning
# ══════════════════════════════════════════════════════════════════════════════

def _iter_scoped(
    paths: Iterable[str],
    groups: set[str] | None,
    langs: set[str] | None,
    sample_rate: int,
    max_per_file: int | None,
    prog: ScanProgress | None = None,
):
    """Yield (urn, doc) for in-scope records, honouring sampling settings.

    Progress is driven from here so both modes report identically: the byte
    position comes from iter_bulk_records' progress_cb, the record counters
    from this loop.
    """
    for path in paths:
        if prog:
            prog.start_file(path)
        seen = kept = 0
        cb = prog.note_bytes if prog else None
        # 1000 lines ≈ 500 records between position updates: tell() is cheap,
        # and the log itself is time-throttled, so this only controls how fresh
        # the percentage/ETA are, not how often we print.
        for urn, doc in iter_bulk_records(path, progress_cb=cb, progress_every_lines=1000):
            seen += 1
            sampled_out = sample_rate > 1 and (seen % sample_rate)
            in_scope = (not sampled_out) and record_in_scope(doc, groups, langs)
            if prog:
                prog.tick(kept=in_scope)
            if not in_scope:
                continue
            yield urn, doc
            kept += 1
            if max_per_file and kept >= max_per_file:
                logger.warning("%s — stopped at --max-per-file=%d (HEAD-truncated; "
                               "date stats from this file are biased)", path, max_per_file)
                break
        if prog:
            prog.finish_file()


def scan_inventory(paths, groups, langs, sample_rate, max_per_file,
                   prog: ScanProgress | None = None) -> dict[str, InventoryStats]:
    stats: dict[str, InventoryStats] = defaultdict(InventoryStats)
    if prog:
        prog.set_summary(lambda: f"{len(stats)} groups, "
                                 f"{_n(sum(s.messages for s in stats.values()))} messages")
    for _urn, doc in _iter_scoped(paths, groups, langs, sample_rate, max_per_file, prog):
        g = doc.get("group") or "<no-group>"
        s = stats[g]
        s.messages += 1
        s.langs[doc.get("lang") or "<none>"] += 1
        if (y := _parse_year((doc.get("headers") or {}).get("date"))):
            s.years[y] += 1
    return dict(stats)


def scan_profile(paths, groups, langs, sample_rate, max_per_file,
                 nk_terms: list[str] | None,
                 prog: ScanProgress | None = None) -> dict[str, ProfileStats]:
    stats: dict[str, ProfileStats] = defaultdict(ProfileStats)
    kept_labels = set(settings.email_segment_labels)
    annotate_langs = set(settings.annotate_languages or [])
    min_tokens = settings.annotate_min_tokens

    if prog:
        prog.set_summary(lambda: (
            f"{len(stats)} groups, "
            f"{_n(sum(s.messages for s in stats.values()))} messages, "
            f"{_n(sum(len(s.authors) for s in stats.values()))} authors, "
            f"{_n(sum(s.est_text_units for s in stats.values()))} est. TextUnits "
            f"({_n(sum(s.est_annotatable_units for s in stats.values()))} annotatable)"
        ))

    for _urn, doc in _iter_scoped(paths, groups, langs, sample_rate, max_per_file, prog):
        g = doc.get("group") or "<no-group>"
        s = stats[g]
        headers = doc.get("headers") or {}
        text_plain = doc.get("text_plain") or ""

        s.messages += 1
        s.langs[doc.get("lang") or "<none>"] += 1
        if (y := _parse_year(headers.get("date"))):
            s.years[y] += 1

        # Community & automation signals
        sender = (headers.get("from") or "").strip()
        if sender:
            s.authors.add(sender)
            if any(h in sender.lower() for h in BOT_FROM_HINTS):
                s.bot_from += 1
        subject = headers.get("subject") or ""
        if subject and TEMPLATED_SUBJECT_RE.search(subject):
            s.templated_subject += 1

        # Threading
        if (mid := headers.get("message_id")):
            s.message_ids.add(_mid_hash(str(mid)))
        if (irt := headers.get("in_reply_to")):
            s.has_in_reply_to += 1
            s.in_reply_to_refs.append(_mid_hash(str(irt)))

        # Text size
        s.total_text_chars += len(text_plain)
        n = len(text_plain)
        bucket = ("0" if n == 0 else "1-200" if n < 200 else "200-1k" if n < 1000
                  else "1k-5k" if n < 5000 else "5k+")
        s.text_len_buckets[bucket] += 1

        # ── Segments: mirror extract_from_email exactly ──────────────────────
        segments = sorted(
            (x for x in (doc.get("segments") or []) if isinstance(x, dict)),
            key=lambda x: (x.get("begin", 0), x.get("end", 0)),
        )
        s.total_segments += len(segments)
        convention, _n_valid, n_total = _resolve_email_offset_convention(text_plain, segments)
        if n_total:
            s.convention[convention] += 1

        # Annotation scope is decided per MESSAGE for language/author and per
        # UNIT for token count, so both are applied exactly rather than
        # approximated — the stripped text is already in hand.
        msg_in_annotate_scope = (not annotate_langs
                                 or (doc.get("lang") or "") in annotate_langs)
        if settings.annotate_skip_bots and sender.endswith("[bot]"):
            msg_in_annotate_scope = False

        est_units = annotatable = 0

        def _count(stripped: str) -> None:
            nonlocal est_units, annotatable
            est_units += 1
            if msg_in_annotate_scope and len(stripped.split()) >= min_tokens:
                annotatable += 1

        # Subject unit at position 0 (only if it survives stripping)
        if subject and (stripped := strip_text(subject)):
            _count(stripped)

        for seg in segments:
            label = seg.get("label", "")
            s.segment_labels[label] += 1
            if label in MACHINE_LABELS:
                s.machine_segments += 1
            if label not in kept_labels:
                continue
            s.kept_segments += 1
            s.kept_span_total += 1
            resolved = _resolve_final_span(text_plain, seg.get("begin"), seg.get("end"), convention)
            if resolved is None:
                continue
            s.kept_span_valid += 1
            begin, end = resolved
            if stripped := strip_text(text_plain[begin:end]):
                _count(stripped)

        s.est_text_units += est_units
        s.est_annotatable_units += annotatable

        # Optional NK pre-screen (see caveat in the report)
        if nk_terms:
            low = text_plain.lower()
            if any(t in low for t in nk_terms):
                s.nk_hit_messages += 1

    return dict(stats)


# ══════════════════════════════════════════════════════════════════════════════
# Reporting
# ══════════════════════════════════════════════════════════════════════════════

def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


def report_inventory(stats: dict[str, InventoryStats], sample_rate: int,
                     top: int, min_messages: int) -> list[dict]:
    rows = []
    for g, s in stats.items():
        if s.messages < min_messages:
            continue
        years = sorted(s.years)
        top_lang, top_lang_n = (s.langs.most_common(1) or [("<none>", 0)])[0]
        rows.append({
            "group": g,
            "messages_sampled": s.messages,
            "messages_estimated": s.messages * sample_rate,
            "top_lang": top_lang,
            "top_lang_pct": _pct(top_lang_n, s.messages),
            "en_pct": _pct(s.langs.get("en", 0), s.messages),
            "year_min": years[0] if years else None,
            "year_max": years[-1] if years else None,
            "n_langs": len(s.langs),
        })
    rows.sort(key=lambda r: -r["messages_estimated"])

    print(f"\n{'='*100}\nINVENTORY — {len(rows)} groups with >= {min_messages} sampled messages"
          f"{f' (1-in-{sample_rate} sample; estimates scaled)' if sample_rate > 1 else ''}\n{'='*100}")
    print(f"{'group':<45}{'est.msgs':>10}{'en%':>7}{'top lang':>10}{'years':>14}")
    print("-" * 100)
    for r in rows[:top]:
        span = f"{r['year_min']}-{r['year_max']}" if r["year_min"] else "?"
        print(f"{r['group'][:44]:<45}{r['messages_estimated']:>10,}{r['en_pct']:>7}"
              f"{r['top_lang'][:9]:>10}{span:>14}")
    if len(rows) > top:
        print(f"... and {len(rows)-top} more (see --out-csv for the full census)")
    return rows


def report_profile(stats: dict[str, ProfileStats], sample_rate: int,
                   full_scan: bool, nk_prescreen: bool) -> list[dict]:
    rows = []
    for g, s in stats.items():
        m = max(s.messages, 1)
        resolvable = sum(1 for h in s.in_reply_to_refs if h in s.message_ids)
        machine_share = _pct(s.machine_segments, s.total_segments)
        para = s.segment_labels.get("paragraph", 0)
        rows.append({
            "group": g,
            "messages_sampled": s.messages,
            "messages_estimated": s.messages * sample_rate,
            "unique_authors": len(s.authors),
            "msgs_per_author": round(s.messages / max(len(s.authors), 1), 1),
            "en_pct": _pct(s.langs.get("en", 0), s.messages),
            "year_min": min(s.years) if s.years else None,
            "year_max": max(s.years) if s.years else None,
            "reply_pct": _pct(s.has_in_reply_to, m),
            "thread_resolution_pct": _pct(resolvable, max(s.has_in_reply_to, 1)),
            "bot_from_pct": _pct(s.bot_from, m),
            "templated_subject_pct": _pct(s.templated_subject, m),
            "machine_segment_pct": machine_share,
            "paragraph_segment_pct": _pct(para, s.total_segments),
            "kept_segments_per_msg": round(s.kept_segments / m, 2),
            "kept_span_valid_pct": _pct(s.kept_span_valid, s.kept_span_total),
            "utf8_bytes_doc_pct": _pct(s.convention.get("utf8_bytes", 0), m),
            "est_text_units": s.est_text_units,
            "est_text_units_scaled": s.est_text_units * sample_rate,
            "est_annotatable_units_scaled": s.est_annotatable_units * sample_rate,
            "mean_chars_per_msg": round(s.total_text_chars / m),
            "nk_prescreen_pct": _pct(s.nk_hit_messages, m) if nk_prescreen else None,
        })
    rows.sort(key=lambda r: -r["est_text_units_scaled"])

    print(f"\n{'='*126}\nPROFILE — {len(rows)} groups\n{'='*126}")
    print(f"{'group':<38}{'est.msgs':>10}{'authors':>9}{'reply%':>8}{'thread%':>9}"
          f"{'para%':>7}{'mach%':>7}{'u/msg':>7}{'est.units':>11}{'annotatable':>13}")
    print("-" * 126)
    for r in rows:
        upm = round(r["est_text_units"] / max(r["messages_sampled"], 1), 2)
        print(f"{r['group'][:37]:<38}{r['messages_estimated']:>10,}{r['unique_authors']:>9,}"
              f"{r['reply_pct']:>8}{r['thread_resolution_pct']:>9}{r['paragraph_segment_pct']:>7}"
              f"{r['machine_segment_pct']:>7}{upm:>7}{r['est_text_units_scaled']:>11,}"
              f"{r['est_annotatable_units_scaled']:>13,}")

    print(f"\n{'-'*118}\nCOLUMN MEANINGS & HOW TO USE THEM")
    print("  reply%     share of messages carrying in_reply_to — raw threading potential.")
    print("  thread%    share of those whose parent is present IN THIS GROUP. This predicts")
    print("             your REPLIES_TO edge yield (RQ6.5). Low = threads span groups/time.")
    if not full_scan:
        print("             ⚠️ SAMPLED SCAN → this is a LOWER BOUND (most parents weren't read).")
    print("  para%      share of segments labelled `paragraph` — authored prose. HIGH is good.")
    print("  mach%      share labelled log_data/patch/raw_code/tabular/quotation_marker —")
    print("             machine content. HIGH means a commit/CI feed, not human discourse.")
    print("  units/msg  TextUnits the extractor will actually create per message (subject +")
    print("             kept segments that resolve and survive stripping) — real yield.")
    print("  est.units  total TextUnits to annotate. THIS drives pipeline cost: the v0.7")
    print("             annotator runs with the spaCy parser ON (DependencyMatcher), so")
    print("             throughput is well below the v0.5 numbers — benchmark before")
    print("             committing to a large subset.")

    print(f"\n{'-'*118}\nSELECTION GUIDANCE (for THIS paper's RQs)")
    print("  RQ6 needs ARENA-MATCHED sources: pick lists that correspond to GitHub repos")
    print("     you have already mined (e.g. python-dev ↔ python/cpython), with overlapping")
    print("     year ranges. Matching matters more than raw size.")
    print("  RQ6 also needs THREADS: prefer high thread% for the opener-vs-reply analysis.")
    print("  Prefer high para% / low mach% — a bug-tracker feed inflates volume with text")
    print("     that carries no authored epistemic stance.")
    print("  Watch msgs_per_author: very high can mean a few dominant posters (or a bot).")
    print("  kept_span_valid% <90 in a group means its segment offsets are unusually")
    print("     damaged; expect proportional TextUnit loss (see CHANGELOG v0.6.2).")

    if nk_prescreen:
        print(f"\n{'!'*118}")
        print("⚠️  NK PRE-SCREEN SELECTION-BIAS WARNING")
        print("    nk_prescreen_pct is a crude substring hit-rate for NK cue words. It is")
        print("    reported ONLY as a floor check (does this group contain ANY NK discourse)")
        print("    and for statistical-power estimation.")
        print("    DO NOT rank or select groups by it. RQ1/RQ3/RQ6 report NK RATES as")
        print("    findings — choosing the corpus by NK density would make those rates an")
        print("    artefact of sampling, and a reviewer will say so. Select on register,")
        print("    arena-matching, threading, and volume instead.")
        print("!" * 118)
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _expand(patterns: list[str]) -> list[str]:
    paths: list[str] = []
    for pat in patterns:
        hits = sorted(glob.glob(pat))
        if not hits:
            logger.warning("no files matched: %s", pat)
        paths.extend(hits)
    if not paths:
        sys.exit("No input files matched. Check --files.")
    return paths


def _write_outputs(rows: list[dict], meta: dict, out_json: str | None, out_csv: str | None) -> None:
    if out_json:
        Path(out_json).write_text(json.dumps({"meta": meta, "groups": rows}, indent=2))
        print(f"\n→ wrote {out_json}")
    if out_csv and rows:
        with open(out_csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"→ wrote {out_csv}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)

    for name in ("inventory", "profile"):
        sp = sub.add_parser(name)
        sp.add_argument("--files", nargs="+", required=True,
                        help="Gzip bulk files (globs OK), same as the ingester's --files.")
        sp.add_argument("--groups", nargs="*", default=None,
                        help="Restrict to these groups (profile mode: the shortlist).")
        sp.add_argument("--lang", nargs="*", default=None,
                        help="Restrict to these langs. Default: no filter, so the report "
                             "SHOWS you the language mix (the ingester defaults to en).")
        sp.add_argument("--sample-rate", type=int, default=1,
                        help="Read 1 in N records. Preferred way to go fast: unbiased "
                             "w.r.t. file order, unlike --max-per-file.")
        sp.add_argument("--max-per-file", type=int, default=None,
                        help="Hard stop per file. HEAD-truncating — biases date stats if "
                             "files are chronological. Smoke tests only.")
        sp.add_argument("--log-every", type=float, default=5.0,
                        help="Seconds between progress lines (default 5).")
        sp.add_argument("--quiet", action="store_true",
                        help="Suppress progress logging; print only the final report.")
        sp.add_argument("--out-json", default=None)
        sp.add_argument("--out-csv", default=None)

    sub.choices["inventory"].add_argument("--top", type=int, default=40,
                                          help="Rows to print (CSV always has all).")
    sub.choices["inventory"].add_argument("--min-messages", type=int, default=1,
                                          help="Hide groups below this sampled count.")
    sub.choices["profile"].add_argument(
        "--nk-prescreen", action="store_true",
        help="Also report a crude NK cue-word hit rate. OFF by default: using it to "
             "SELECT groups biases the NK rates that RQ1/RQ3/RQ6 report as findings.")

    args = p.parse_args()
    logging.getLogger().setLevel(logging.WARNING if args.quiet else logging.INFO)
    paths: list[str] = []
    for pattern in args.files:
        paths.extend(sorted(glob.glob(PATH_TO_DATA + pattern)))
    groups = set(args.groups) if args.groups else None
    langs = set(args.lang) if args.lang else None
    full_scan = args.sample_rate == 1 and not args.max_per_file

    prog = ScanProgress(paths, log_every_sec=args.log_every, enabled=not args.quiet)
    if args.sample_rate > 1:
        logger.info("Sampling 1-in-%d records (counts scaled by %dx in the report)",
                    args.sample_rate, args.sample_rate)
    if args.max_per_file:
        logger.info("--max-per-file=%d — HEAD-truncated, date stats biased if files "
                    "are chronological; prefer --sample-rate for statistics",
                    args.max_per_file)

    meta = {
        "mode": args.mode, "files": len(paths), "sample_rate": args.sample_rate,
        "max_per_file": args.max_per_file, "full_scan": full_scan,
        "groups_filter": sorted(groups) if groups else None,
        "lang_filter": sorted(langs) if langs else None,
        "email_segment_labels": list(settings.email_segment_labels),
        "pattern_set_version": settings.pattern_set_version,
    }

    if args.mode == "inventory":
        stats = scan_inventory(paths, groups, langs, args.sample_rate,
                               args.max_per_file, prog)
        prog.finish()
        rows = report_inventory(stats, args.sample_rate, args.top, args.min_messages)
    else:
        nk_terms = None
        if args.nk_prescreen:
            nk_terms = ["not sure", "unclear", "unknown", "no idea", "don't know",
                        "dunno", "maybe", "perhaps", "might be", "afaik", "iirc",
                        "seems to", "hard to tell", "can't reproduce", "cannot reproduce"]
        stats = scan_profile(paths, groups, langs, args.sample_rate,
                             args.max_per_file, nk_terms, prog)
        prog.finish()
        rows = report_profile(stats, args.sample_rate, full_scan, bool(nk_terms))

    _write_outputs(rows, meta, args.out_json, args.out_csv)


if __name__ == "__main__":
    main()
