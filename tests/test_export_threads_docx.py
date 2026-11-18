"""tests/test_export_threads_docx.py — DB-free tests for the thread → Word export.

Run: pytest tests/test_export_threads_docx.py -q
"""

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from scripts.export_threads_docx import align_spans, export_threads_docx


def _span(text, needle, occurrence=0):
    i = -1
    for _ in range(occurrence + 1):
        i = text.index(needle, i + 1)
    return i, i + len(needle)


def make_fixture():
    t1 = "Hi Ana,\nI'm not sure this is the right approach, maybe you could try the other API?"
    t2 = "I don't really know how the build works. The docs are a black box to me.\x0b Thanks!"
    t3 = "It seems that the tests are flaky; perhaps it is non-deterministic."
    t4 = "Subject: Re: GSoC proposal"
    units = pd.DataFrame(
        [
            dict(
                thread_id="T1",
                message_id="m1",
                tu_id="u1",
                text=t1,
                sent_at="2019-05-02T10:00:00Z",
                author="mentorA",
                role="mentor",
                tu_role="paragraph",
                position=1,
                tokens=17,
                project_id="p1",
            ),
            dict(
                thread_id="T1",
                message_id="m0",
                tu_id="u0",
                text=t4,
                sent_at="2019-05-01T09:00:00Z",
                author="menteeB",
                role="mentee",
                tu_role="subject",
                position=0,
                tokens=4,
                project_id="p1",
            ),
            dict(
                thread_id="T1",
                message_id="m0",
                tu_id="u2",
                text=t2,
                sent_at="2019-05-01T09:00:00Z",
                author="menteeB",
                role="mentee",
                tu_role="paragraph",
                position=1,
                tokens=16,
                project_id="p1",
            ),
            dict(
                thread_id="T2",
                message_id="m3",
                tu_id="u3",
                text=t3,
                sent_at=None,
                author="someone",
                role=None,
                tu_role="paragraph",
                position=1,
                tokens=11,
                project_id="p2",
            ),
        ]
    )
    s = []

    def add(tu, text, needle, layer, cat, sub, surface=None, occ=0, offsets=None):
        a, b = offsets if offsets else _span(text, needle, occ)
        s.append(
            dict(
                tu_id=tu,
                layer=layer,
                category=cat,
                subcategory=sub,
                surface_form=surface if surface is not None else needle,
                span_start=a,
                span_end=b,
                rule_id=f"{layer}.{sub}",
                status="active",
            )
        )

    add("u1", t1, "not sure", "lexical", "prototype", "epistemic_state")
    add("u1", t1, "I'm not sure", "morpho_syntactic", "epistemic_verb", "not_knowing")  # overlap
    add("u1", t1, "maybe", "morpho_syntactic", "hedging", "adverbial")
    add("u1", t1, "could", "morpho_syntactic", "modality", "underspecified")
    add(
        "u1",
        t1,
        "maybe you could try the other API?",
        "morpho_syntactic",
        "syntactic_pattern",
        "question_answer",
    )  # nested
    add(
        "u2",
        t2,
        "I don't really know",
        "morpho_syntactic",
        "epistemic_verb",
        "not_knowing",
        surface="I do n't know",
    )  # non-contiguous
    add("u2", t2, "black box", "rhetorical", "metaphor", "SE_native")
    add("u2", t2, "black box", "lexical", "shared_feature", "opacity")  # exact overlap
    add(
        "u2", t2, "", "lexical", "prototype", "imprecision", surface="docs", offsets=(500, 504)
    )  # out of range → search
    add(
        "u2",
        t2,
        "",
        "lexical",
        "prototype",
        "epistemic_state",
        surface="zzz unknown",
        offsets=(900, 911),
    )  # → failed
    add("u3", t3, "seems", "morpho_syntactic", "evidential", "inferential")
    add("u3", t3, "perhaps", "morpho_syntactic", "hedging", "adverbial")
    add("u3", t3, "non-deterministic", "lexical", "shared_feature", "non_deterministic_behaviour")
    s.append(
        dict(
            tu_id="u3",
            layer="classifier",
            category="roberta_binary",
            subcategory=None,
            surface_form=t3,
            span_start=0,
            span_end=len(t3),
            rule_id="clf",
            status="active",
        )
    )
    return units, pd.DataFrame(s)


def test_alignment_methods():
    units, sig = make_fixture()
    al = align_spans(units, sig)
    assert al.loc[al.surface_form == "I do n't know", "align_method"].item() == "char_loose"
    assert al.loc[al.surface_form == "docs", "align_method"].item() == "search"
    assert al.loc[al.surface_form == "zzz unknown", "align_method"].item() == "failed"
    assert (al.align_method == "char").sum() == len(al) - 3


def test_export_single_and_per_thread(tmp_path: Path):
    units, sig = make_fixture()
    res = export_threads_docx(
        units,
        sig,
        tmp_path / "all.docx",
        thread_meta=pd.DataFrame({"stratum": ["typical"]}, index=["T1"]),
    )
    p = res["paths"][0]
    assert p.exists()
    xml = zipfile.ZipFile(p).read("word/document.xml").decode()
    assert 'w:fill="' in xml and "\x0b" not in xml
    assert "I'm" in xml and "black box" in xml
    res2 = export_threads_docx(units, sig, tmp_path / "per", one_file_per_thread=True)
    assert {x.name for x in res2["paths"]} == {"thread_T1.docx", "thread_T2.docx"}


def test_export_drops_stale_single_token_embedded_question(tmp_path: Path):
    """Pre-fix morph.syn.embedded_question matched bare 'if'/'how'; those stale
    single-token signals must be dropped, the genuine multi-word kept."""
    text = "I wonder if this works, but I am not sure. If it fails, retry."
    units = pd.DataFrame(
        [
            dict(
                thread_id="T1",
                message_id="m1",
                tu_id="u1",
                text=text,
                sent_at=None,
                author="a",
                role="mentor",
                tu_role="paragraph",
                position=1,
                tokens=20,
                project_id="p1",
            ),
        ]
    )

    def sig(needle: str, surface: str) -> dict:
        a = text.index(needle)
        return dict(
            tu_id="u1",
            layer="morpho_syntactic",
            category="syntactic_pattern",
            subcategory="embedded_question",
            surface_form=surface,
            span_start=a,
            span_end=a + len(surface),
            rule_id="morph.syn.embedded_question",
            status="active",
        )

    signals = pd.DataFrame(
        [
            sig("wonder if", "wonder if"),  # genuine, multi-word → kept
            sig("If it fails", "If"),  # stale, single-token → dropped
        ]
    )
    res = export_threads_docx(units, signals, tmp_path / "t.docx")
    kept = res["aligned"].surface_form.tolist()
    assert "wonder if" in kept
    assert "If" not in kept


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_threads.docx")
    units, sig = make_fixture()
    res = export_threads_docx(
        units,
        sig,
        out,
        title="Synthetic demo — NK marker export",
        thread_meta=pd.DataFrame(
            {"stratum": ["typical"], "selection_reason": ["fixture"]}, index=["T1"]
        ),
    )
    print(res["alignment"])
    print("written", res["paths"])
