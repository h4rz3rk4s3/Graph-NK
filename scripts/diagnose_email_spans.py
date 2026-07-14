"""
Diagnose "segment span out of bounds" on already-ingested Gmane emails.

Reuses the EXACT SAME detection logic as extract_from_email
(extractor.text_unit_extractor._resolve_email_offset_convention), so its
output is guaranteed consistent with what the extractor actually does — this
reports ground truth on your real corpus rather than a guess.

For a sample of emails already in MongoDB raw_emails, it determines each
document's best-fit offset convention (char / UTF-8 bytes / UTF-16 code
units) by majority vote across that document's segments, and reports:
  - how many documents need each convention
  - how many documents have a "clean" majority (100% of segments agree)
    vs. a partial one (some individual segments are outliers even after
    picking the best-fit convention)

Usage:
    python scripts/diagnose_email_spans.py --sample 500
    python scripts/diagnose_email_spans.py --sample 2000 --show-text
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extractor.text_unit_extractor import _resolve_email_offset_convention, _resolve_final_span
from settings import settings
from storage import make_mongo_client


async def main(sample: int, show_text: bool) -> None:
    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]
    coll = db["raw_emails"]

    doc_convention_tally: collections.Counter = collections.Counter()
    clean_vs_partial: collections.Counter = collections.Counter()
    examples: dict[str, list] = collections.defaultdict(list)
    emails_seen = 0
    total_segments = 0

    # v0.6.2 additions: segment-level validity (not just document-level), and
    # a breakdown by label — because "83.9% of documents have SOME problem"
    # can be misleading when documents average many segments each, and
    # because only the labels in settings.email_segment_labels are ever kept
    # by the extractor, so invalid segments of other labels are irrelevant.
    seg_valid = seg_total = 0
    kept_labels = set(settings.email_segment_labels)
    kept_valid = kept_total = 0
    label_tally: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    bad_gap_examples: list = []  # segments failing BOTH char and byte — position pattern

    cursor = coll.find({}, {"text_plain": 1, "segments": 1, "urn": 1}).limit(sample)
    async for doc in cursor:
        emails_seen += 1
        text = doc.get("text_plain") or ""
        segments = doc.get("segments") or []
        total_segments += len(segments)
        n_chars = len(text)

        convention, n_valid, n_total = _resolve_email_offset_convention(text, segments)
        if n_total == 0:
            continue
        doc_convention_tally[convention] += 1
        clean_vs_partial["clean" if n_valid == n_total else "partial"] += 1

        if convention != "char" and len(examples[convention]) < 5:
            seg = next(
                (s for s in segments if isinstance(s.get("begin"), int)
                 and isinstance(s.get("end"), int) and s["end"] > s["begin"]),
                None,
            )
            snippet = None
            if seg and show_text:
                resolved = _resolve_final_span(text, seg["begin"], seg["end"], convention)
                if resolved is not None:
                    b, e = resolved
                    snippet = text[b:e][:60].replace("\n", "\\n")
            examples[convention].append((doc.get("urn"), n_valid, n_total, snippet))

        # Segment-level + per-label validity under exactly the same
        # resolution extract_from_email uses (including the trailing-
        # overshoot clamp) — this is what keeps the diagnostic honest.
        for seg in segments:
            b_raw, e_raw = seg.get("begin"), seg.get("end")
            label = seg.get("label", "")
            if not (isinstance(b_raw, int) and isinstance(e_raw, int) and e_raw > b_raw >= 0):
                continue
            seg_total += 1
            resolved = _resolve_final_span(text, b_raw, e_raw, convention)
            is_valid = resolved is not None
            seg_valid += int(is_valid)
            label_tally[label]["valid" if is_valid else "invalid"] += 1
            if label in kept_labels:
                kept_total += 1
                kept_valid += int(is_valid)
            if not is_valid and len(bad_gap_examples) < 8:
                # Position pattern: near the end of text_plain suggests
                # truncation (offsets computed against a longer reference
                # text than the exported text_plain); scattered positions
                # suggest per-segment model-output noise instead.
                bad_gap_examples.append((doc.get("urn"), label, b_raw, e_raw, n_chars,
                                          round(100 * e_raw / max(n_chars, 1), 1)))
    mongo.close()

    print(f"Checked {emails_seen} emails ({total_segments} total segments), "
          f"requested sample={sample}.\n")
    if emails_seen == 0:
        print("No emails found — is raw_emails populated? (run the ingester first)")
        return

    print("Best-fit convention by document:")
    for conv, count in doc_convention_tally.most_common():
        pct = 100 * count / emails_seen
        print(f"  {conv:14s} {count:6d} documents  ({pct:5.1f}%)")
    print()
    print("Majority fit quality (document level):")
    for kind, count in clean_vs_partial.most_common():
        pct = 100 * count / emails_seen
        label = "100% of segments agree" if kind == "clean" else "some individual outlier segments"
        print(f"  {kind:8s} {count:6d} documents  ({pct:5.1f}%)  — {label}")
    print()

    print("── SEGMENT-level validity (the number that determines actual data loss) ──")
    pct = 100 * seg_valid / seg_total if seg_total else 0
    print(f"  {seg_valid}/{seg_total} segments valid  ({pct:.1f}%)\n")

    print(f"── Validity restricted to KEPT labels {sorted(kept_labels)} "
          f"(email_segment_labels — everything else is discarded regardless) ──")
    pct_kept = 100 * kept_valid / kept_total if kept_total else 0
    print(f"  {kept_valid}/{kept_total} segments valid  ({pct_kept:.1f}%)")
    print(f"  ({'This is the number that matters for research coverage.' if kept_total else ''})\n")

    print("── Validity by label ──")
    for label in sorted(label_tally, key=lambda l: -sum(label_tally[l].values())):
        c = label_tally[label]
        n = c["valid"] + c["invalid"]
        pct_l = 100 * c["valid"] / n if n else 0
        kept_marker = " (KEPT)" if label in kept_labels else ""
        print(f"  {label:20s} {c['valid']:6d}/{n:<6d} valid ({pct_l:5.1f}%){kept_marker}")
    print()

    if bad_gap_examples:
        print("── Sample of segments failing even the document's best-fit convention "
              "(fail BOTH char and byte — not an encoding issue) ──")
        print("   position_pct = end offset as % of text_plain length; values near")
        print("   100% suggest truncation (offsets computed against a longer reference")
        print("   text than what was exported as text_plain); scattered values suggest")
        print("   per-segment model-output noise instead.")
        for urn, label, b, e, n_chars, pct_pos in bad_gap_examples:
            print(f"  {urn}  label={label:16s} end={e:6d}  text_len={n_chars:6d}  "
                  f"position={pct_pos:5.1f}%")
        print()

    for conv, exs in examples.items():
        print(f"── Example documents best-fit to '{conv}' ──")
        for urn, n_valid, n_total, snippet in exs:
            line = f"  {urn}  ({n_valid}/{n_total} segments valid under this convention)"
            if snippet is not None:
                line += f"  sample text: {snippet!r}"
            print(line)
        print()

    print("Interpretation guide:")
    print("  - SEGMENT-level validity is what determines actual data loss — trust it")
    print("    over the document-level 'partial' percentage, which is inflated by")
    print("    documents averaging many segments each (one bad segment marks the")
    print("    whole document 'partial' even if the other 8 are fine).")
    print("  - If validity restricted to KEPT labels is high (>90%), the bulk of any")
    print("    corruption is in labels you already discard (quotation, signatures,")
    print("    etc.) and is largely irrelevant to your research corpus.")
    print("  - Segments failing BOTH char and byte are not an encoding-convention")
    print("    problem. Check the position_pct pattern above: clustering near 100%")
    print("    suggests text_plain was truncated/cleaned after segmentation ran;")
    print("    no pattern suggests scattered model-output noise (expected at some")
    print("    rate from a 96%-accurate segmentation model, per the Webis paper).")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", type=int, default=500,
                    help="Number of emails to check (default 500).")
    p.add_argument("--show-text", action="store_true",
                    help="Print a recovered text snippet per non-char example "
                         "(useful to eyeball whether recovery looks correct).")
    args = p.parse_args()
    asyncio.run(main(args.sample, args.show_text))

