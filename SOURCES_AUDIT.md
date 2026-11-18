# SOURCES_AUDIT.md

**Companion to:** `ignorance_codebook_v0.1.yml`, `CODING_MANUAL.md`, `TAXONOMY_CROSSWALK.md`
**Purpose:** T6 deliverable — a full, honest account of what was and was not directly verified against primary text for each of the four taxonomies, what secondary reception was used and for what purpose, and what remains unverifiable. This document exists so that every `definition_confidence` rating and `source_locator` field in the codebook can be traced back to its actual evidentiary basis, rather than taken on faith.

**Standing rule observed throughout:** secondary literature was used only for two purposes — (1) disambiguating a primary definition that was itself accessed but ambiguous or contested, or (2) recording prior evidence that a category has broken down empirically in some other domain (prior-breakage evidence, directly relevant to RQ4's own logic). Secondary literature was never used to add, broaden, or invent a category not present in the primary source's own account of itself.

---

## 1. Roberts (2013) — Organizational ignorance: Towards a managerial perspective on the unknown

**Access level: FULL PRIMARY TEXT.** The complete article (Management Learning, 44(3), 215-236) was supplied by the user as a PDF and extracted in full, including Table 1 (pp. 227-229), which gives the canonical summary of all nine categories.

**Confidence distribution:** 6 of 9 categories at `high` confidence, 3 at `medium`. No category rests on secondary reconstruction alone.

**What secondary reception was gathered, and how it was used:**

| Claim | Source | Use |
|---|---|---|
| Roberts (2013) is repeatedly cited as one of the few systematic typologies of organizational ignorance, filling a gap in management studies | Bakken & Wiik (2018); Essén, Knudsen & Alvesson (2022), *Explaining Ignoring*, Organization Studies | Context only — not used to add or alter categories. |
| Later organizational-ignorance work draws directly on Roberts's taboos/denials/secrecy categories as reference categories | *ephemera* journal, "Organised ignorance" (Knudsen, Pors & Bakken); "How to study strategic ignorance in organizations: A material approach" | Confirms continued scholarly uptake of these three specific categories; no category expansion performed. |
| No secondary source located reports a Roberts (2013) category as empirically empty, unusable, or unreliable in another empirical domain | Multiple citing works (2013–2024) reviewed | **Prior-breakage evidence: ABSENT.** Recorded as an absence, not as evidence the categories are robust — no domain-transfer stress test of this typology was found in the literature search conducted. |

**Unverifiable claims:** none recorded for this taxonomy — full-text access removed the need for any UNVERIFIED locator.

**Residual uncertainty not classified as "unverifiable" but worth flagging:** Roberts's own text leaves two boundary conditions asserted rather than operationalised — the resource-investment threshold separating `known_unknowns` from `knowable_known_unknowns`, and the "multilateral" criterion separating `secrecy` from `privacy`. These are recorded as `source_vagueness` in the codebook, not as access gaps; the source itself does not resolve them.

---

## 2. Smithson (1989/1993) — *Ignorance and Uncertainty: Emerging Paradigms* / "Ignorance and science: Dilemmas, perspectives, and prospects"

**Access level: PARTIAL.** Neither primary source was accessed in full.

- **Smithson (1993)**, "Ignorance and science" (DOI 10.1177/107554709301500202): `fetch_article_fulltext` returned closed access. Unpaywall, Semantic Scholar, PMC, and CrossRef TDM all reported no open-access location. Only the abstract was retrievable.
- **Smithson (1989) book**: not accessed as a complete text. A digitized excerpt — apparently OCR'd from the book's opening chapter, including an inline page-break marker ("8") and a garbled rendering of the book's Figure 1.1 tree diagram — was located hosted at vdoc.pub and treated as a primary-text fragment for the passages it actually contains (the distortion/incompleteness/absence/uncertainty branch).

**Confidence distribution:** 4 categories at `high`, 4 at `medium-high`, 5 at `medium`, 1 at `low` (`probability`).

**Secondary reception gathered and its use:**

| Claim | Source | Use |
|---|---|---|
| In addition to Smithson's three subcategories of irrelevance (untopicality, undecidability, taboo), a qualitative study of IT project managers found a fourth kind of irrelevance emerging empirically | Kutsch & Hall (2010), *Deliberate ignorance in project risk management*, Int. J. Project Management 28(3), 245-255 (as reported in an ANU Press chapter) | **Prior-breakage evidence.** Directly relevant to RQ4's own logic — the taxonomy has already been observed to under-cover a domain once, outside SE. Not used to add a category here. |
| A related project-management case study confirmed the three subtypes but reported a further, unclassified type of irrelevance that did not fit any of the three | POMS conference paper 008-0307 | **Prior-breakage evidence.** Same status as above. |
| Smithson's own later work adds "conflict" as a fourth member of the uncertainty branch (alongside 1989's probability, vagueness, ambiguity) | Smithson, "Understanding Uncertainty" (ANU Press, in Bammer & Smithson, Eds., 2008) | Disambiguation only. **"Conflict" is explicitly excluded from the codebook** — it postdates 1989 and is not part of the original typology being coded. |
| Smithson (1989) splits ignorance into "the state of ignorance (error)" and "the act of ignorance (irrelevance)" | Synthese (2019), "Negative expertise in conditions of manufactured ignorance" | Disambiguation of the top-level branch split. |

**Unverifiable claims (from the delegated research, recorded verbatim in spirit, not invented after the fact):**

1. Exact page numbers for every leaf category except Incompleteness/Absence/Uncertainty (p. 8, inferred from an OCR page-break marker) and the top-level Error/Irrelevance split (p. 9, per a secondary source's citation) could not be independently confirmed — the full book was not accessed.
2. No page-level claims are attributed to the 1993 article itself anywhere in the codebook, since only its abstract was available.
3. Definitions of `vagueness`, `ambiguity`, `taboo`, and `undecidability` are drawn from a 2022 first-person restatement by Smithson (i2insights.org / RealKM) — an author-authored but tertiary source, not verified against the original 1989/1993 pagination.
4. A garbled OCR rendering of the book's Figure 1.1 appears to show the term "Fuzziness" where the running prose lists "ambiguity" under Uncertainty. This discrepancy could not be resolved given OCR quality and is explicitly **not** treated as evidence of an additional or renamed category.
5. No definition specific to Smithson's technical usage of "probability" (as distinct from its everyday statistical meaning) was located in any accessed source — this is why `smithson.probability` carries `definition_confidence: low`, the single lowest-confidence leaf in the entire codebook.

---

## 3. Gross (2010) — *Ignorance and Surprise: Science, Society, and Ecological Design*

**Access level: SECONDARY ONLY.** Neither the 2010 book nor its 2007 predecessor article was retrieved in full text through any available channel.

- The 2010 MIT Press book: no open-access location found via Unpaywall/Semantic Scholar/PMC/CrossRef-TDM. MIT Press's own landing pages (direct.mit.edu, mitpress.mit.edu) return only publisher blurb and jacket endorsements, not chapter text.
- Gross, M. (2007), "The Unknown in Process: Dynamic Connections of Ignorance, Non-knowledge and Related Concepts," *Current Sociology* 55(5): 742-759 — the book's designated conceptual predecessor — was also not retrievable in full text (closed access; only the abstract was obtained).
- **DOI correction required mid-task:** the DOI supplied in the original task instructions for the 2007 article, `10.1177/0011392107077645`, does not resolve in CrossRef at all. The correct DOI, found via web search, is `10.1177/0011392107079928`. `fetch_article_fulltext` was retried against the corrected DOI and still failed (closed access, no TDM link, no PMC/OA copy).

**Every category in this taxonomy is therefore reconstructed exclusively from secondary sources.** This is the weakest-evidenced of the four taxonomies in the codebook, and its confidence ratings reflect that: 3 categories at `low` (`ignorance`, `non_knowledge`, `negative_knowledge`), 2 at `medium` (`nescience`, `surprise` — the two categories for which at least one verbatim-quoted primary sentence was recovered via a book review).

**Secondary reception gathered and its use:**

| Claim | Source | Use |
|---|---|---|
| A 2011 book review reproduces a verbatim sentence from p. 76 of the book tying "nescience" to the retrospective communication of an "error" | *American Journal of Sociology* 116(6) (2011): 2022-2024 | Disambiguation of the primary definition of `nescience` — this is the single piece of verbatim page-cited primary text obtained for this entire taxonomy. |
| A citing academic work paraphrases Gross (2010, p. 68) defining nescience as "the complete absence of knowledge," lying outside the non-knowledge/negative-knowledge mapping | ResearchGate record 346624361 | Disambiguation of `nescience`'s definition and its structural position relative to the other two categories. |
| Michael Smithson's own plain-language explainer describes Gross's 2007 scheme as a "house of the unknown," distinguishing "nonknowledge" (specified, in-principle-resolvable) from "negative knowledge" (Knorr-Cetina's term for irreducible not-knowing) | i2insights.org (2022), "Ignorance: Vocabulary and taxonomy," by Michael Smithson | Disambiguation of the 2007 predecessor scheme only — used to reconstruct `ignorance`, `non_knowledge`, `negative_knowledge`, none of which could be traced to a page-cited primary quote. |

**Unverifiable claims:**

1. The task brief's suggested distinction between "active non-knowledge" and "passive non-knowledge" as Gross's own category labels was **not found in any accessed source** (2007 abstract, book reviews, or citing works). **This pairing is explicitly excluded from the codebook** — it is not treated as a category, per the "do not invent" rule, even though it would have been a convenient way to fill a structural gap.
2. Whether the 2010 book preserves the 2007 article's "house of the unknown" structure unchanged, extends it, or restructures it — no accessed source gives a systematic walkthrough of the book's full internal taxonomy diagram.
3. Exact page numbers for the book's own definitions of `ignorance`, `non_knowledge`, and `negative_knowledge` (as opposed to the 2007 article) were not located.
4. Whether Gross (2010) distinguishes "specified" from "unspecified" non-knowledge as two independently named subtypes, versus using "specified ignorance" (Merton's term) merely to characterize non-knowledge as a whole — accessed sources support only the latter reading, but this could not be confirmed against the primary text.
5. No source was found explicitly characterizing Gross's category set as conceptually murky, overlapping, or empirically hard to apply in any domain. The three secondary-reception entries above are disambiguation uses only, **not** prior-breakage evidence — this gap in the literature is recorded as an absence and should not be read as evidence of robustness either way.

**Methodological note on this taxonomy's overall standing:** given that every category here rests on secondary paraphrase, the coding manual's priority order (§3 of `CODING_MANUAL.md`) places Gross's categories last, and treats a high rate of Gross-code assignment on the eventual SE corpus as a signal to review, not as a comfortable finding. This decision was made and recorded in the coding manual *before* seeing any corpus data.

---

## 4. Wehling (2024) — "Nichtwissen – ein ungewöhnlicher Schlüsselbegriff der Umweltsoziologie"

**Access level: FULL PRIMARY TEXT (for the 2024 chapter).** The chapter (pp. 671-687, in *Handbuch Umweltsoziologie*) was supplied by the user as part of a book PDF and extracted in full, including the dimensional scheme's core statement (chapter p. 676, section 3.1, "Formen und Varianten des Nichtwissens").

**Important caveat on depth:** the 2024 chapter is itself a **condensed restatement** of a fuller elaboration the chapter explicitly refers back to — Wehling (2006), *Im Schatten des Wissens? Perspektiven der Soziologie des Nichtwissens*, p. 116 ff. — which was **not** independently accessed. The three dimensions (`knowledge_of_nonknowledge`, `intentionality`, `temporal_durability`) are confirmed from the 2024 chapter's own words, but the *fuller* argumentation behind them, including finer subdivisions the 2006 book may contain, is UNVERIFIED against that earlier text.

**Confidence distribution:** all three dimensions at `medium` — reflecting this "condensed restatement of an unverified fuller source" structure, not any weakness in the 2024 text itself, which was read in full.

**Secondary reception gathered and its use:**

| Claim | Source | Use |
|---|---|---|
| Wehling's three dimensions are consistently reproduced in secondary German-language sociology-of-knowledge sources as his signature contribution, and are reported to differ from Smithson's approach (which treats error, ignorance, and risk as themselves subtypes of non-knowledge — a conflation Wehling is reported to reject) | philou.rwth-aachen.de summary; a GRIN student paper applying the scheme to the Contergan/thalidomide case | Disambiguation — corroborates the three-dimension structure and surfaces an explicit theoretical disagreement between Wehling and Smithson. **This disagreement is recorded as a conflicting relation in the crosswalk, not resolved or adjudicated.** |
| A Peter Lang book chapter by Wehling himself corroborates the intentionality dimension's page location (2006: 116ff.) and adds that intentionality covers "weaker" forms like negligence or limited epistemic interest, not only explicit refusal to know | Wehling, "Verantwortung für das Unvermeidliche…" in *Unsicherheit als Herausforderung für die Wissenschaft* (Peter Lang) | Disambiguation of the intentionality dimension's scope; corroborates rather than expands. |
| No secondary source located reports empirical application of Wehling's three dimensions outside STS/risk-governance case studies (Contergan/thalidomide, anonymous sperm donation) | GRIN paper; philou summary; nichtwissen.com blog series | **Prior-breakage evidence: ABSENT** for any domain resembling SE discourse. Recorded per the same absence-reporting rule as the other three taxonomies. |

**Unverifiable claims:**

1. The exact page range of the fuller 2006 elaboration (cited by the 2024 chapter as "S. 116 ff." for intentionality, and elsewhere for the other two dimensions) is UNVERIFIED against primary text. A table-of-contents fragment (library.mpib-berlin.mpg.de) shows plausible matching subsection titles and page numbers (§4.2.1 "Das (Nicht-)Wissen des Nichtwissens," p. 117; §4.2.2 "Die Intentionalität des Nichtwissens," p. 127; §4.2.3 "Die zeitliche Stabilität von Nichtwissen," p. 132; §4.2.4 "Die Mehrdimensionalität von Nichtwissens-Phänomenen," p. 146) but these are secondary-source corroborated, not independently verified against the book's actual pages.

---

## 5. Cross-cutting audit notes

**Access asymmetry across the four taxonomies is itself a limitation of this codebook, not just of any one entry.** Roberts and Wehling were verified against full primary text (user-supplied PDFs); Smithson against a partial primary excerpt plus author-authored tertiary restatement; Gross against secondary paraphrase only. This asymmetry means the codebook's overall category set is **not evenly evidenced** — a fact that must travel with any downstream RQ4 finding. A category collapsing or going unpopulated in SE data could, in principle, reflect thin sourcing rather than a genuine mismatch with SE discourse; `CODING_MANUAL.md` §3 and §7 (P5) build this asymmetry into the priority order and into an explicit pre-registered diagnostic, precisely so it cannot be mistaken for a substantive RQ4(c) finding after the fact.

**No secondary source, across any of the four taxonomies, reports a prior empirical stress-test of that taxonomy in a domain resembling software-engineering discourse.** All "prior-breakage evidence" found (Smithson's project-management studies) comes from adjacent-but-distinct domains (IT project risk management), not SE communication artefacts specifically. This absence is recorded as a gap in the literature, not as license to assume the taxonomies will transfer cleanly.

**Nothing in this audit was used to relax, extend, or narrow any category definition to make it more applicable to SE text.** Every secondary-reception use recorded above is either disambiguation of a primary-source ambiguity or prior-breakage evidence from a non-SE domain — never expansion.
