"""
scripts/export_threads_docx.py — export artefact threads to Word with NK marker
spans shaded, for qualitative reading (RQ3b OpenMent; IMPLEMENTATION_PLAN §7.3).

The module is DB-free: it takes two plain DataFrames, so it can be unit-tested
and reused for any corpus. The notebook cell that queries Neo4j lives in
``notebooks/03_rq3b_openment.ipynb``.

Inputs
------
units    one row per TextUnit
         required: thread_id, message_id, tu_id, text
         optional: sent_at, author, role, tu_role, position, tokens, project_id
signals  one row per Signal (already filtered by the analysis predicate)
         required: tu_id, layer, category, span_start, span_end
         optional: subcategory, surface_form, rule_id, status, signal_id
thread_meta  optional DataFrame indexed by thread_id; every column is printed
         in the thread's metadata table (e.g. stratum, selection_reason)

Output per thread
-----------------
1. metadata table (project, participants with roles, dates, tokens / NK
   signals / NK per 1k tokens by role, alignment problems)
2. markers-per-phenomenon table: counts per (layer, category, subcategory)
   by role; the phenomenon cell carries the same shading as the spans, so the
   table doubles as the legend
3. all messages in order, every unit as a paragraph, every signal span shaded

Assumptions (verify in P0, see IMPLEMENTATION_PLAN §3):
- span_start/span_end are CHARACTER offsets into TextUnit.text. Every span is
  checked against surface_form; mismatches fall back to token offsets (if a
  spaCy tokenizer is passed), then to a text search near span_start. The
  method used is recorded per signal and summarised in the alignment report,
  so a wrong assumption is visible, not silent.
- Overlapping spans (e.g. lexical `opacity` + rhetorical opacity, which is a
  disclosed double-count) are segmented: each segment gets the colour of the
  innermost (shortest) covering span; segments covered by spans of different
  colours are additionally double-underlined.
- Counts come from the signal table, not from rendering: signals that could
  not be placed in the text are still counted and listed as unaligned.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
from docx import Document
from docx.enum.text import WD_UNDERLINE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# Light background colours (hex, no '#'), chosen to stay readable under black
# text and to be distinguishable from each other. Cycled if exhausted.
PALETTE = [
    "FFF2A8",  # yellow
    "CDE8FF",  # blue
    "CFF5CF",  # green
    "FFD9C2",  # orange
    "E6D9FF",  # lavender
    "FFD6E7",  # pink
    "C4F0EB",  # teal
    "EFE0C4",  # sand
    "E3F2B0",  # lime
    "DADFEA",  # slate
    "FFE3A8",  # apricot
    "F3D1F5",  # orchid
    "D5EDDC",  # sage
    "FCE0E0",  # rose
    "D8F0FA",  # sky
    "ECECEC",  # grey
]

ROLE_ORDER = ["mentor", "mentee"]
ROLE_TEXT_COLOUR = {"mentor": RGBColor(0x1F, 0x3A, 0x8A), "mentee": RGBColor(0x1B, 0x6B, 0x2F)}
LABEL_COLOUR = RGBColor(0x80, 0x80, 0x80)

# Schema order of <w:rPr> / <w:tcPr> children that must come AFTER <w:shd>.
_RPR_AFTER_SHD = (
    "w:fitText",
    "w:vertAlign",
    "w:rtl",
    "w:cs",
    "w:em",
    "w:lang",
    "w:eastAsianLayout",
    "w:specVanish",
    "w:oMath",
)
_TCPR_AFTER_SHD = (
    "w:noWrap",
    "w:tcMar",
    "w:textDirection",
    "w:tcFitText",
    "w:vAlign",
    "w:hideMark",
    "w:headers",
    "w:cellIns",
    "w:cellDel",
    "w:cellMerge",
    "w:tcPrChange",
)

# Characters lxml refuses in XML text (offsets are computed on the raw text;
# cleaning happens per rendered segment, so it never shifts spans).
_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff￾￿]")


# ─────────────────────────────────────────────────────────────────────────────
# Span alignment
# ─────────────────────────────────────────────────────────────────────────────


def _norm(s: str) -> str:
    """Lower-case, all whitespace removed ('do n't know' == "don't know")."""
    return re.sub(r"\s+", "", str(s)).lower()


def _loose_match(slice_: str, surface: str) -> bool:
    """Non-contiguous constructions (dependency matches): the slice starts with
    the surface form's first word and ends with its last word."""
    words = str(surface).split()
    if len(words) < 2:
        return False
    s = _norm(slice_)
    return s.startswith(_norm(words[0])) and s.endswith(_norm(words[-1]))


def _search(text: str, surface: str, near: int) -> Optional[tuple[int, int]]:
    """Case-insensitive search for surface_form; occurrence closest to `near`."""
    surface = str(surface).strip()
    if len(surface) < 2:
        return None
    pat = r"\s*".join(re.escape(p) for p in surface.split())
    hits = [(m.start(), m.end()) for m in re.finditer(pat, text, flags=re.I)]
    if not hits:
        return None
    return min(hits, key=lambda h: abs(h[0] - near))


def align_spans(units: pd.DataFrame, signals: pd.DataFrame, tokenizer=None) -> pd.DataFrame:
    """Return `signals` with a_start, a_end (character offsets into the unit
    text, or NA) and `align_method` ∈ {char, char_loose, char_unverified, token,
    search, failed, no_text}.

    tokenizer: optional callable text -> spaCy Doc (e.g. spacy.blank("en").tokenizer),
    used only when the character interpretation fails.
    """
    texts = dict(zip(units.tu_id, units.text.fillna("").astype(str)))
    doc_cache: dict[str, object] = {}
    out_s, out_e, how = [], [], []

    for r in signals.itertuples(index=False):
        text = texts.get(r.tu_id)
        sf = getattr(r, "surface_form", None)
        sf = None if sf is None or (isinstance(sf, float) and pd.isna(sf)) else str(sf)
        # Whole-unit signals (classifier, some syntactic rules) carry an empty
        # surface form; treat them as an unverified full span, not a failure.
        if sf is not None and sf.strip() == "":
            sf = None
        if text is None:
            out_s.append(pd.NA)
            out_e.append(pd.NA)
            how.append("no_text")
            continue
        try:
            s, e = int(r.span_start), int(r.span_end)
        except (TypeError, ValueError):
            s, e = -1, -1

        # 1) character offsets
        if 0 <= s < e <= len(text):
            sl = text[s:e]
            if sf is None:
                out_s.append(s)
                out_e.append(e)
                how.append("char_unverified")
                continue
            if _norm(sl) == _norm(sf):
                out_s.append(s)
                out_e.append(e)
                how.append("char")
                continue
            if _loose_match(sl, sf):
                out_s.append(s)
                out_e.append(e)
                how.append("char_loose")
                continue

        # 2) token offsets
        if tokenizer is not None and sf is not None and 0 <= s < e:
            doc = doc_cache.get(r.tu_id)
            if doc is None:
                doc = doc_cache[r.tu_id] = tokenizer(text)
            if e <= len(doc):
                span = doc[s:e]
                if _norm(span.text) == _norm(sf) or _loose_match(span.text, sf):
                    out_s.append(span.start_char)
                    out_e.append(span.end_char)
                    how.append("token")
                    continue

        # 3) search near the stated start
        hit = _search(text, sf, max(s, 0)) if sf else None
        if hit:
            out_s.append(hit[0])
            out_e.append(hit[1])
            how.append("search")
            continue

        out_s.append(pd.NA)
        out_e.append(pd.NA)
        how.append("failed")

    res = signals.copy()
    res["a_start"], res["a_end"], res["align_method"] = out_s, out_e, how
    return res


def alignment_report(aligned: pd.DataFrame) -> pd.DataFrame:
    """Counts of alignment methods per layer (rows) — 'failed'/'search' should be rare."""
    return (
        aligned.groupby(["layer", "align_method"])
        .size()
        .unstack(fill_value=0)
        .assign(total=lambda d: d.sum(axis=1))
    )


# ─────────────────────────────────────────────────────────────────────────────
# Colours and keys
# ─────────────────────────────────────────────────────────────────────────────


def _val(x, default="—") -> str:
    return default if x is None or (isinstance(x, float) and pd.isna(x)) or x == "" else str(x)


def colour_key(row, color_by: str) -> str:
    if color_by == "layer":
        return _val(row.layer)
    if color_by == "category":
        return _val(row.category)
    if color_by == "subcategory":
        return f"{_val(row.category)}/{_val(getattr(row, 'subcategory', None))}"
    return f"{_val(row.layer)} › {_val(row.category)}"  # layer_category


def build_palette(keys: Iterable[str]) -> dict[str, str]:
    """Deterministic key → colour mapping (sorted keys), stable across threads."""
    keys = sorted(set(keys))
    if len(keys) > len(PALETTE):
        print(
            f"⚠️  {len(keys)} colour keys but {len(PALETTE)} colours — colours repeat; "
            "consider color_by='layer' or a smaller layer set."
        )
    return {k: PALETTE[i % len(PALETTE)] for i, k in enumerate(keys)}


# ─────────────────────────────────────────────────────────────────────────────
# Low-level docx helpers
# ─────────────────────────────────────────────────────────────────────────────


def _clean(s: str) -> str:
    return _XML_BAD.sub("", s.replace("\r\n", "\n").replace("\r", "\n"))


def _shade_run(run, fill: str) -> None:
    rPr = run._r.get_or_add_rPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    rPr.insert_element_before(shd, *_RPR_AFTER_SHD)


def _shade_cell(cell, fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.insert_element_before(shd, *_TCPR_AFTER_SHD)


def _table(
    doc,
    rows: list[list[str]],
    header: bool = True,
    fills: Optional[dict] = None,
    widths_cm: Optional[list[float]] = None,
):
    """Simple grid table; fills maps (row_idx, col_idx) -> hex fill."""
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    try:
        t.style = "Table Grid"
    except Exception:
        pass
    if widths_cm:
        t.autofit = False
        grid = t._tbl.tblGrid.findall(qn("w:gridCol"))  # LibreOffice reads the grid,
        for j, w in enumerate(widths_cm):  # Word reads the cell widths
            grid[j].set(qn("w:w"), str(int(Cm(w).twips)))
            for cell in t.columns[j].cells:
                cell.width = Cm(w)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = t.cell(i, j)
            cell.text = ""
            run = cell.paragraphs[0].add_run(_clean(str(val)))
            run.font.size = Pt(9)
            if header and i == 0:
                run.bold = True
                _shade_cell(cell, "E7E6E6")
            if fills and (i, j) in fills:
                _shade_cell(cell, fills[(i, j)])
    return t


def _add_marked_paragraph(
    doc, text: str, spans: list[dict], show_labels: bool, prefix: Optional[str] = None
):
    """One paragraph; text split at every span boundary, segments shaded."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    if prefix:
        r = p.add_run(f"[{prefix}] ")
        r.font.size = Pt(8)
        r.font.color.rgb = LABEL_COLOUR
    if not text:
        return p

    bounds = sorted({0, len(text)} | {sp["start"] for sp in spans} | {sp["end"] for sp in spans})
    for a, b in zip(bounds, bounds[1:]):
        if a >= b:
            continue
        covering = [sp for sp in spans if sp["start"] <= a and sp["end"] >= b]
        seg = _clean(text[a:b])
        if seg:
            run = p.add_run(seg)
            if covering:
                inner = min(covering, key=lambda sp: (sp["end"] - sp["start"], sp["key"]))
                _shade_run(run, inner["fill"])
                if len({sp["fill"] for sp in covering}) > 1:
                    run.font.underline = WD_UNDERLINE.DOUBLE  # python-docx keeps schema order
        if show_labels:
            for sp in sorted((sp for sp in spans if sp["end"] == b), key=lambda sp: sp["start"]):
                lab = p.add_run(f"[{sp['label']}]")
                lab.font.size = Pt(7)
                lab.font.color.rgb = LABEL_COLOUR
                lab.font.superscript = True
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Thread rendering
# ─────────────────────────────────────────────────────────────────────────────


def _roles_present(series: pd.Series) -> list[str]:
    present = [r for r in series.fillna("unknown").unique()]
    return [r for r in ROLE_ORDER if r in present] + sorted(
        r for r in present if r not in ROLE_ORDER
    )


def _phenomenon(row) -> str:
    return f"{_val(row.layer)} › {_val(row.category)} › {_val(getattr(row, 'subcategory', None))}"


def _render_thread(
    doc,
    tid,
    tu: pd.DataFrame,
    sig: pd.DataFrame,
    meta: Optional[pd.Series],
    palette: dict,
    color_by: str,
    show_labels: bool,
    shade_exclude_layers: tuple,
    label_field: str,
):
    tu = tu.copy()
    tu["role"] = tu.get("role", pd.Series(index=tu.index, dtype=object)).fillna("unknown")
    tu["author"] = tu.get("author", pd.Series(index=tu.index, dtype=object)).fillna("—")
    tu["tokens"] = pd.to_numeric(tu.get("tokens", 0), errors="coerce").fillna(0).astype(int)
    tu["_ts"] = (
        pd.to_datetime(tu.get("sent_at"), errors="coerce", utc=True) if "sent_at" in tu else pd.NaT
    )
    # Optional human-readable clock for corpora with anonymised/relative time
    # (OpenMent stores anonymised day offsets, so calendar dates are meaningless).
    has_display = "date_display" in tu.columns
    tu["position"] = pd.to_numeric(tu.get("position", 0), errors="coerce").fillna(0)
    msg_order = tu.groupby("message_id")["_ts"].min().sort_values(na_position="last").index.tolist()
    sig = sig.merge(tu[["tu_id", "role"]], on="tu_id", how="left")
    roles = _roles_present(tu.role)

    h = doc.add_heading(f"Thread {tid}", level=1)
    h.paragraph_format.page_break_before = True  # no empty break paragraphs

    # ── 1. metadata ─────────────────────────────────────────────────────────
    doc.add_heading("Metadata", level=2)
    per_msg = tu.drop_duplicates("message_id")
    participants = (
        tu.drop_duplicates(["message_id"]).groupby(["author", "role"]).size().reset_index(name="n")
    )
    ts = tu["_ts"].dropna()
    if has_display:
        disp = tu["date_display"].dropna().astype(str)
        date_range = f"{disp.iloc[0]} → {disp.iloc[-1]}" if len(disp) else "—"
    else:
        date_range = f"{ts.min():%Y-%m-%d %H:%M} → {ts.max():%Y-%m-%d %H:%M}" if len(ts) else "—"
    tok = tu.groupby("role").tokens.sum()
    nk = sig.groupby("role").size()
    rows = [
        ["Field", "Value"],
        ["Thread ID", str(tid)],
        ["Project", ", ".join(sorted(tu.get("project_id", pd.Series(["—"])).astype(str).unique()))],
        [
            "Messages",
            f"{len(per_msg)}  ("
            + ", ".join(f"{r}: {int((per_msg.role == r).sum())}" for r in roles)
            + ")",
        ],
        ["Text units", str(len(tu))],
        [
            "Participants",
            "; ".join(f"{a} ({r}, {n} msg)" for a, r, n in participants.itertuples(index=False)),
        ],
        ["Date range", date_range],
        [
            "Tokens",
            ", ".join(f"{r}: {int(tok.get(r, 0)):,}" for r in roles)
            + f"  (total {int(tok.sum()):,})",
        ],
        [
            "NK signals",
            ", ".join(f"{r}: {int(nk.get(r, 0))}" for r in roles) + f"  (total {len(sig)})",
        ],
        [
            "NK per 1k tokens",
            ", ".join(
                f"{r}: {1000 * nk.get(r, 0) / tok[r]:.1f}" if tok.get(r, 0) else f"{r}: —"
                for r in roles
            ),
        ],
    ]
    unaligned = sig[sig.a_start.isna()]
    if len(unaligned):
        rows.append(
            [
                "Signals not placed in text",
                f"{len(unaligned)} — "
                + "; ".join(
                    f"{_val(r.surface_form) if 'surface_form' in sig else ''} ({r.tu_id})"
                    for r in unaligned.head(10).itertuples(index=False)
                ),
            ]
        )
    if meta is not None:
        for k, v in meta.items():
            rows.append([str(k), _val(v)])
    _table(doc, rows, widths_cm=[4.0, 12.5])

    # ── 2. markers per phenomenon ───────────────────────────────────────────
    doc.add_heading("Markers per phenomenon", level=2)
    if len(sig):
        sig = sig.assign(
            _ph=[_phenomenon(r) for r in sig.itertuples(index=False)],
            _key=[colour_key(r, color_by) for r in sig.itertuples(index=False)],
        )
        ct = sig.pivot_table(
            index=["_ph", "_key", "layer"],
            columns="role",
            values="tu_id",
            aggfunc="size",
            fill_value=0,
        ).reindex(columns=roles, fill_value=0)
        ct["total"] = ct.sum(axis=1)
        ct = ct.sort_values("total", ascending=False)
        rows = [["Phenomenon (layer › category › subcategory)"] + roles + ["Total"]]
        fills = {}
        for i, ((ph, key, layer), r) in enumerate(ct.iterrows(), start=1):
            note = "  (not shaded)" if layer in shade_exclude_layers else ""
            rows.append([ph + note] + [str(int(r[c])) for c in roles] + [str(int(r.total))])
            if layer not in shade_exclude_layers:
                fills[(i, 0)] = palette.get(key, "FFFFFF")
        rows.append(["Total"] + [str(int(ct[c].sum())) for c in roles] + [str(int(ct.total.sum()))])
        rest = 7.5 / (len(roles) + 1)
        _table(doc, rows, fills=fills, widths_cm=[9.0] + [rest] * (len(roles) + 1))
    else:
        doc.add_paragraph("No NK signals in this thread.")

    # ── 3. messages ────────────────────────────────────────────────────────
    doc.add_heading("Messages", level=2)
    spans_by_tu: dict[str, list[dict]] = {}
    for r in sig.itertuples(index=False):
        if pd.isna(r.a_start) or r.layer in shade_exclude_layers:
            continue
        key = colour_key(r, color_by)
        lab = _val(getattr(r, label_field, None), default=_val(r.category))
        spans_by_tu.setdefault(r.tu_id, []).append(
            {
                "start": int(r.a_start),
                "end": int(r.a_end),
                "key": key,
                "fill": palette.get(key, "FFFFFF"),
                "label": lab,
            }
        )

    for k, mid in enumerate(msg_order, start=1):
        m = tu[tu.message_id == mid].sort_values("position")
        first = m.iloc[0]
        hp = doc.add_paragraph()
        hp.paragraph_format.space_before = Pt(10)
        hp.paragraph_format.keep_with_next = True
        r1 = hp.add_run(f"#{k}  {first.author}  ·  {first.role}")
        r1.bold = True
        if first.role in ROLE_TEXT_COLOUR:
            r1.font.color.rgb = ROLE_TEXT_COLOUR[first.role]
        ts0 = first["_ts"]
        if has_display and pd.notna(first.get("date_display")):
            when = _val(first.get("date_display"))
        else:
            when = f"{ts0:%Y-%m-%d %H:%M}" if pd.notna(ts0) else _val(first.get("sent_at"))
        r2 = hp.add_run(f"  ·  {when}  ·  {mid}")
        r2.font.size = Pt(8)
        r2.font.color.rgb = LABEL_COLOUR
        for u in m.itertuples(index=False):
            tu_role = _val(getattr(u, "tu_role", None), default="")
            prefix = (
                tu_role if tu_role and tu_role not in ("paragraph", "body", "message") else None
            )
            _add_marked_paragraph(
                doc,
                str(u.text if isinstance(u.text, str) else ""),
                spans_by_tu.get(u.tu_id, []),
                show_labels,
                prefix,
            )


def export_threads_docx(
    units: pd.DataFrame,
    signals: pd.DataFrame,
    out_path: str | Path,
    thread_meta: Optional[pd.DataFrame] = None,
    thread_ids: Optional[list] = None,
    one_file_per_thread: bool = False,
    color_by: str = "layer_category",
    show_labels: bool = True,
    label_field: str = "subcategory",
    shade_exclude_layers: tuple = ("classifier",),
    tokenizer=None,
    title: str = "NK marker export",
) -> dict:
    """Write the threads to Word. Returns {'paths': [...], 'alignment': DataFrame,
    'aligned': DataFrame}.

    one_file_per_thread=False → one file at `out_path` (page break between threads);
    True → `out_path` is treated as a directory, one `thread_<id>.docx` per thread.
    color_by ∈ {'layer_category' (default), 'layer', 'category', 'subcategory'}.
    shade_exclude_layers: layers counted in the tables but not shaded (the
    classifier 'span' is the whole unit and would shade everything).
    """
    units = units.copy()
    units["thread_id"] = units.thread_id.astype(str)
    units["text"] = units.text.fillna("").astype(str)
    if thread_ids is None:
        thread_ids = list(dict.fromkeys(units.thread_id))
    thread_ids = [str(t) for t in thread_ids]
    units = units[units.thread_id.isin(thread_ids)]
    signals = signals[signals.tu_id.isin(units.tu_id)].copy()
    # 2026-10-03 / 2026-10-07: drop stale spans left by rule definitions that
    # were NARROWED in place under the same rule_version. Kept in sync with
    # STALE_SIGNAL_EXCLUSION in scripts/openment_roles.py so a caller that
    # forgot the analysis predicate cannot reintroduce the noise.
    #   - morph.syn.embedded_question: old Matcher OP:"?" bug matched bare
    #     if/how/when/which/what/where/why/whether; genuine embedded questions
    #     are multi-word ("wonder if", "unclear how").
    #   - morph.tense.future_nk_wont_know dropped can't/cannot: surviving spans
    #     start with "wo".
    #   - morph.epi.neg_cognition_modal dropped the "wo" auxiliary.
    #   - rhetor.metaphor.spatial.uncharted dropped "terra incognita".
    # See CHANGELOG 2026-10-03 and 2026-10-07.
    if {"rule_id", "surface_form"}.issubset(signals.columns):
        sf = signals.surface_form.fillna("").astype(str)
        low = sf.str.lower()
        stale = (
            (signals.rule_id.eq("morph.syn.embedded_question") & ~sf.str.contains(" ", regex=False))
            | (signals.rule_id.eq("morph.tense.future_nk_wont_know") & ~low.str.startswith("wo"))
            | (signals.rule_id.eq("morph.epi.neg_cognition_modal") & low.str.startswith("wo"))
            | (
                signals.rule_id.eq("rhetor.metaphor.spatial.uncharted")
                & low.str.startswith("terra")
            )
        )
        signals = signals[~stale].copy()

    aligned = align_spans(units, signals, tokenizer=tokenizer)
    report = alignment_report(aligned) if len(aligned) else pd.DataFrame()
    shade_keys = [
        colour_key(r, color_by)
        for r in aligned.itertuples(index=False)
        if r.layer not in shade_exclude_layers
    ]
    palette = build_palette(shade_keys)
    sig_by_thread = aligned.merge(units[["tu_id", "thread_id"]], on="tu_id", how="left")
    if thread_meta is not None:
        thread_meta = thread_meta.copy()
        thread_meta.index = thread_meta.index.astype(str)

    def new_doc():
        d = Document()
        st = d.styles["Normal"]
        st.font.name = "Calibri"
        st.font.size = Pt(10.5)
        z = d.settings.element.find(qn("w:zoom"))  # template lacks the required attribute
        if z is not None and z.get(qn("w:percent")) is None:
            z.set(qn("w:percent"), "100")
        return d

    def front_matter(d, tids):
        d.add_heading(title, level=0)
        p = d.add_paragraph()
        p.add_run(
            f"Generated {date.today():%Y-%m-%d} · {len(tids)} thread(s) · colour by "
            f"{color_by} · not shaded: {', '.join(shade_exclude_layers) or '—'}"
        ).font.size = Pt(9)
        d.add_heading("Legend", level=2)
        rows = [["Colour key", "Signals in this file"]]
        cnt = (
            sig_by_thread[
                sig_by_thread.thread_id.isin(tids) & ~sig_by_thread.layer.isin(shade_exclude_layers)
            ]
            .assign(_k=lambda x: [colour_key(r, color_by) for r in x.itertuples(index=False)])
            ._k.value_counts()
        )
        fills = {}
        for i, k in enumerate(sorted(cnt.index), start=1):
            rows.append([k, str(int(cnt[k]))])
            fills[(i, 0)] = palette[k]
        if len(rows) > 1:
            _table(d, rows, fills=fills, widths_cm=[9.0, 4.0])
        d.add_paragraph().add_run(
            "Overlapping spans: the innermost span sets the colour; segments covered by spans of "
            "different colours are double-underlined. Grey superscripts give the "
            f"{label_field} of each span at its end."
        ).font.size = Pt(8)

    paths = []
    out_path = Path(out_path)
    if one_file_per_thread:
        out_path.mkdir(parents=True, exist_ok=True)
    doc = None
    for tid in thread_ids:
        if one_file_per_thread or doc is None:
            doc = new_doc()
            front_matter(doc, [tid] if one_file_per_thread else thread_ids)
        meta = (
            thread_meta.loc[tid] if thread_meta is not None and tid in thread_meta.index else None
        )
        if isinstance(meta, pd.DataFrame):  # duplicate index rows → first
            meta = meta.iloc[0]
        _render_thread(
            doc,
            tid,
            units[units.thread_id == tid],
            sig_by_thread[sig_by_thread.thread_id == tid].drop(columns="thread_id"),
            meta,
            palette,
            color_by,
            show_labels,
            shade_exclude_layers,
            label_field,
        )
        if one_file_per_thread:
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", tid)[:120]
            p = out_path / f"thread_{safe}.docx"
            doc.save(p)
            paths.append(p)
    if not one_file_per_thread and doc is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(out_path)
        paths.append(out_path)
    return {"paths": paths, "alignment": report, "aligned": aligned}
