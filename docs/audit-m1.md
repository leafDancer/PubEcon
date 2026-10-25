# M1 Data Audit — AER 2000+

**Date:** 2026-10-22  
**Scope:** American Economic Review, ISSN 0002-8282, Crossref records published 2000-01-01 onward.  
**Database:** `data/curated/econpub.db` (5,498 records, harvested 2026-10-21).  
**Method:** six independent read-only audit agents (coverage, parsing, classification/dedup, authors/ranks, cross-source, integrity), followed by adversarial verification of every critical/high finding and a completeness critic. No production data or code was modified during the audit. Full structured results are in `docs/audit-m1-findings.json`.

## Overall verdict

The bibliographic and structural layer is in good shape. Record coverage is complete, the raw-to-database reconciliation is exact, SQLite integrity is clean, and P&P issue identification is correct for all 18 years.

The **author identity layer is not fit for network or career analysis yet**. The provisional name-only resolver splits a material share of the same people across multiple IDs. The **career-stage evidence is also far weaker than the current report says**: explicit academic rank appears on only 0.37% of author slots, not 6.2%. Several classification and deduplication rules need correction before M2/M3.

The audit produced 58 raw findings; 30 were adversarially verified (all confirmed or partially confirmed, none refuted), and 28 lower-severity items remain unverified. This report groups the verified findings by root cause.

> **Remediation note:** the counts below describe the pre-P0 database. See [Remediation status (P0)](#remediation-status-p0-2026-10-22) for the current values.

## Critical and high findings

### 1. AUTH-01 (critical): name variants split 456 author IDs into ~225 identities

- **Scale:** 456 of 6,140 article authors (7.4%) are duplicate IDs of about 225 real people. This affects **1,040 of 10,858 article author slots (9.6%)** and **1,405 of 8,331 unique coauthor edges (16.9%)**.
- **Cause:** `resolve_author` keys non-ORCID authors on the exact normalized `family|given` string. There is no middle-initial, surname-particle, or leading-initial normalization. 6,184 of 6,185 authors lack an ORCID.
- **Examples:** Parag A Pathak / Parag Pathak; James A Robinson / James Robinson; Michael Kremer / Michael R Kremer; John J Siegfried / John Siegfried; David H Autor / David Autor; three Banerjee variants; three Levitt variants; surname-particle pairs such as John Van Reenen, Till von Wachter, Pedro Dal Bo, Jan De Loecker, Eric van Wincoop, Eliana La Ferrara, Bram De Rock, Arthur van Soest; leading-initial pairs such as J. Vernon Henderson and W. Reed Walker.
- **Caveat:** blind merging is unsafe. The verifier found a confirmed distinct-namesake pair (Robert L Clark, NC State vs Robert Clark, HEC Montreal/Queen's) and estimated merge precision around 95%. Conflicting-affiliation pairs must go to review.
- **Fix:** middle-initial-insensitive, particle-aware, Unicode-transliterating key; prefer ORCID/OpenAlex IDs; review-merge highest-slot clusters with affiliation evidence; exclude conflicting-affiliation namesakes; rebuild `coauthorship_edges` after merging.

### 2. AUTH-02 (high): academic byline rank is 0.37%, not 6.2%

- **Scale:** only **40 of 10,858 article author slots (0.37%)** carry an academic rank. The reported 6.2% counts 672 non-null rank rows, of which **632 are `non_academic`**; only 40 are academic ranks.
- **Implication:** the byline cannot support career-stage inference for this corpus. The project must rely on CV employment/education timelines, with OpenAlex author IDs and affiliations as supporting evidence. M4 is not optional.
- **Fix:** correct `data/reports/m1_quality.md`, `README.md`, and `docs/data-sources.md`; stop describing 6.2% as academic rank coverage.

### 3. Publication month is one month earlier than the AEA issue for 1,495 records (high)

- **Scope:** 1,495 records, including 1,359 research articles, concentrated in 2002-2009.
- **Cause:** Crossref's `published` date is not the AEA issue cover month; the pipeline stores it as the issue date. Example: 2002 issue 2 has month 4 in AEA but many records carry month 5, and the reverse pattern appears elsewhere.
- **Impact:** issue-level time analysis, P&P month checks, and any "published in month X" display are wrong for those years.
- **Fix:** re-harvest `published-print` and `published-online`, store both, and use issue metadata for issue-level dates. Reconcile 2002-2009 against AEA issue pages.

### 4. AUTH-03 (high): University of California campus is discarded in all 420 hint rows

- **Scope:** all 420 institution hints for UC authors are "University of California" rather than Berkeley, UCLA, San Diego, etc.
- **Impact:** institution-level statistics and mobility analysis are wrong for the largest public university system in the data.
- **Fix:** proper institution resolver using OpenAlex institution IDs and campus-aware parsing; never truncate at "University of California".

### 5. Administrative records inflate article, P&P, and author counts (high)

- **Scope:** **53 non-research AEA editorial/administrative records** are classified as `content_type='article'`; 52 are also flagged P&P. A narrower completeness check independently found 44. Examples include editorial notices, front-matter-like material, and administrative reports that do not match the existing title rules.
- **Impact:** the current headline 4,844 articles / 1,847 P&P / 10,858 author slots are inflated. The corrected baseline is approximately:
  - **4,786 research articles** after removing 53 administrative records, 1 erratum, 2 retraction notices, and 2 missed research duplicate pairs.
  - **1,795 P&P articles** after removing the 52 administrative records from P&P.
  - **10,782 author slots.**
  - If retracted originals are also excluded, 4,784 articles and 10,777 slots.
- **Fix:** extend administrative/retraction title and structural rules; exclude front matter from P&P; add page-continuity and within-issue checks; reclassify and regenerate counts.

### 6. Duplicate detection recall is incomplete (medium severity, high impact)

- **Scope:** 51 duplicate rows are marked, but the actual count is **at least 63** (12 missed), with estimates up to **67 pairs** depending on whether front-matter/P&P pairs are counted. At least **two research-article duplicate pairs remain counted as articles**.
- **Related:** author resolution runs before deduplication, leaving 29 duplicate-only authors and 27 malformed ghost authors. OpenAlex also splits 25 of the 51 duplicate DOI pairs into separate works.
- **Fix:** normalize titles (quotes/apostrophes/HTML entities), roman-vs-arabic page labels, zero-padded issue numbers, trailing-semicolon DOIs, and page tolerance; scan all content types; require page/issue agreement for fuzzy matches; run deduplication and non-research filtering **before** author resolution.

## Medium findings (verified)

| ID | Finding | Affected | Fix |
|---|---|---:|---|
| INT-02 | Author resolution before dedup leaves duplicate-only authors and inconsistent IDs across duplicate pairs | 29 authors / 25 pairs | Reorder pipeline; rebuild authors |
| AUTH-07 | Duplicate and erratum records create malformed ghost authors | 27 | Rebuild from canonical records only |
| F04 / F7 | Crossref author suffix is never parsed; Jr./II/III lost | 45 slots / 24 authors | Add `suffix` to Crossref select and store it |
| CC-05 | Unicode normalizer strips non-ASCII letters and splits names (Hortaçsu, Pęski, Szalay) | 27 authors | Transliterate, do not drop combining/non-ASCII letters |
| AUTH-05 | Non-empty affiliation but no institution hint | 1,013 slots | Fallback parsing; OpenAlex institution IDs |
| AUTH-04 | Malformed institution-hint fragments | 266 | Parser cleanup and validation |
| AUTH-10 | Institution hints fragment into variants at top universities | 652 | Canonical institution resolver |
| AUTH-06 | Combined byline affiliations assigned to every author | 20 | Per-author affiliation parsing |
| AUTH-08 | `non_academic` recall about 87%; foreign central banks/government/consulting missed | 95 | Expand rules; manual taxonomy |
| INT-01 | Dedup misses 16 of 67 pairs | 16 pairs | Normalized fuzzy dedup; see above |
| COV-02 | Two legacy-DOI duplicates of 2007 research articles still counted | 2 | Re-run dedup |
| F2 | Dedup misses at least 12 duplicate deposits, including 2 research articles and an erratum | 12 | Re-run dedup with normalization |
| F03 | Three articles have wrong page ranges; one is reversed (`10.1257/aer.20181830`, 2718-2212), two reuse 411-433 | 3 | Page validators; correct from AEA/IDEAS |
| F4 | Erratum/retraction detection misses one erratum and two retraction notices; retracted originals have no status flag | 5 | Add retraction status and `update-to`/`relation` |
| F3 | `paper_topics` is empty; Crossref provides zero subject fields | 5,498 | Get JEL from AEA pages in M2 |
| F4 | AEA pages cannot fill missing abstracts; OpenAlex can fill about two-thirds but includes boilerplate pseudo-abstracts | 1,370 | Use OpenAlex with filtering; keep provenance |
| F5 | AEA institution metadata is empty for 2002-2007; Crossref affiliations are the only usable source | 29 | Prefer Crossref for that era |
| F8 | OpenAlex publication_year disagrees with DB for matched works | 226 (4.1%) | Do not use OpenAlex year as truth; DOI-keyed only |
| INT-04 | `published_date` drops known months for year-only records | 31 | Store partial dates explicitly |
| INT-06 | Volume/issue/page stored as TEXT; lexical-sort and range-comparison risks | 242 | Add numeric sort keys or typed columns |
| INT-07 | ISSN/container-title inconsistent across records | 361 | Normalize journal identity fields |
| F04 | 45 authorships lose suffixes | 45 | Same as F04 above |
| F06 | Day=1 placeholder on 5,467 dated records | 5,467 | Distinguish date precision |
| F07 | Inline JATS/HTML tag stripping inserts spaces, corrupting 11 titles and 7 abstracts | 18 | Tag-aware text cleanup |
| F08 | Unrepaired encoding artifacts in 3 titles and 1 author name | 4 | Encoding repair |
| F09 | Journal identity fields not normalized (two container titles, comma-joined ISSNs, placeholder 0000-0000) | 418 | Normalize |
| F10 | 34 Foreword/Introduction records still `article`; 24 article records carry roman-numeral pages | 35 | Editorial classification rules |
| F11 | Two 2015 front-matter pairs are duplicate deposits but unmarked | 2 | Re-run dedup on front matter |
| F5 | 58 no-author administrative records labeled `unattributed` rather than front matter/report | 58 | Content-type refinement |
| F12 | OpenAlex and Crossref citation counts diverge (median ratio 1.30) | 5,011 | Choose one citation source; label it |
| INT-05 | Three unmarked duplicate front-matter pairs carry conflicting metadata | 6 | Dedup front matter |
| INT-09 | Six records have colliding or inverted page ranges from Crossref | 6 | Validator + source correction |

## Clean checks (verified)

- **Coverage is exact:** six raw Crossref pages (1000+1000+1000+1000+1000+498), `papers`, and `source_records` all contain 5,498 records with identical DOI sets and byte-identical payloads. The live Crossref API also reports 5,498 for 2000+.
- **Volume-year mapping is exact:** 90=2000 through 116=2026, no missing or extra volumes. All 229 AEA issue labels for 2000-2026 are represented, including the 2018 combined 4-5 issue and the 2011-2013 seven-issue years.
- **2026 partial year is correct:** AEA lists issues 1-10 through October 2026; the DB contains exactly those, max date 2026-10-01, no post-2026 records.
- **14 AEA TOC samples** show no missing research articles; DOI sets matched where compared.
- **P&P selection is correct for all 18 years:** chosen issues are volumes 90-100 issue 2 (2000-2010), 101-103 issue 3 (2011-2013), 104-107 issue 5 (2014-2017). Each is the largest April/May cluster with at least 50 articles and at least 50% April/May. No `is_pp` outside 2000-2017.
- **Structural integrity:** `PRAGMA integrity_check='ok'`, zero foreign-key violations, no duplicate DOIs, no orphan authorships/topics, all duplicate pointers valid and acyclic, contiguous `author_order`, `abstract_available` matches abstract nullness, zero synthetic DOIs.
- **Parsing fidelity:** all 5,498 records match raw Crossref on title, abstract, volume, issue, page split, date parts, and item type; all 11,181 raw author entries match on given/family/full name/affiliation/sequence/ORCID except the suffix omission. No residual HTML tags, entities, truncation, double spaces, or mojibake in the full-table scan.
- **Identifiers:** all 5,498 DOIs start with `10.1257/`, are lowercase, and contain no URL prefix or whitespace.
- **Affiliations/abstracts:** affiliation coverage 10,773/10,858 (99.2%); abstract coverage 3,474/4,844 (71.7%).
- **Cross-source:** all 10 era-stratified DOIs resolve (HTTP 302) to `pubs.aeaweb.org`; 61 sampled AEA article pages return 200; titles, authors, volume/issue, and first page agree; JEL is present on 10/10 sampled AEA pages. The final PDF endpoint is Cloudflare-protected (403), but article metadata pages are usable with polite rate limits.
- **OpenAlex capacity:** 5,470/5,498 DOIs match (99.5%); in a 223-slot sample, 98.7% have OpenAlex author IDs and 68.2% have ORCID. This is the best available basis for disambiguation, but OpenAlex years and affiliation history are noisy.
- **Derived tables are empty:** `coauthorship_edges`, `career_events`, `career_assignments`, `paper_topics`, and `institutions` have zero rows, so the author-identity defects have not yet propagated into network or career outputs.

## Unverified backlog (28 items)

These are lower-severity or overlapping findings that were not adversarially verified. The full list and evidence are in `docs/audit-m1-findings.json`. The most important are:

- **COV-04:** one 2022 article (`10.1257/aer.20181830`) has reversed pages 2718-2212.
- **F02-dedup-missed-pairs:** two 2007 issue 1 article pairs remain unmarked; article duplicate count is 53, not 51.
- **F05-rank-address-false-positive:** the rank regex reads "Avenida Professor Luciano Gualberto" as a professorship for 2 authors.
- **F06-date-precision:** day=1 placeholder on all dated records; 31 month-only dates.
- **F07-inline-tag-spacing:** 18 text fields corrupted by tag stripping.
- **F08-encoding-artifacts:** 3 titles and 1 author name.
- **F09-journal-identity-fields:** two container titles, comma-joined ISSN lists, 10 placeholder ISSNs.
- **F10-editorial-misclassification-pages:** 24 roman-numeral page records; 34 Foreword/Introduction records still articles.
- **F11-frontmatter-duplicates:** two 2015 front-matter duplicate pairs.
- **AUTH-09:** street-name rank false positive (2 authors).
- **F9:** 28 DOIs unmatched in OpenAlex (retry before treating as absent).
- **F12:** OpenAlex/Crossref citation divergence (median ratio 1.30).
- **F13:** 45 authors exist only on duplicate/non-article records.
- **F14:** one stored abstract is a Ricardo epigraph, not an abstract.
- **INT-04/05/06/07/08/09/10/11/12:** date precision, duplicate front-matter metadata, TEXT storage, ISSN/container inconsistency, empty topics, page-range collisions, suffix loss, Mundell erratum, retraction typing.

## Recommended remediation order

### P0 — fix the foundation before any M2/M3 work

1. **Rework author resolution.** Build a middle-initial-insensitive, particle-aware, Unicode-transliterating key. Prefer ORCID/OpenAlex IDs. Review-merge the highest-slot clusters with affiliation evidence, explicitly excluding conflicting-affiliation namesakes. Recompute the author table, author counts, and coauthor edges.
2. **Reorder the pipeline.** Run deduplication and non-research filtering **before** author resolution. Rebuild `authors`, `authorships`, duplicate pointers, and all derived tables from canonical records only.
3. **Re-run dedup with normalization.** Handle quotes/apostrophes/HTML entities, roman-vs-arabic page labels, zero-padded issue numbers, trailing-semicolon DOIs, and page tolerance. Scan all content types. Require page/issue agreement for fuzzy matches. Expect at least 63 duplicate rows, not 51.
4. **Correct classification counts.** Reclassify the 53 administrative records, the 2 missed research duplicate pairs, the erratum, and the retraction notices. Update the headline article/P&P/slot counts and the quality report.

### P1 — repair dates, metadata, and institutions

5. **Re-harvest Crossref with missing fields:** `published-print`, `published-online`, `update-to`, `relation`, `subtitle`, `suffix`. Re-derive dates and retraction links; store print and online dates separately.
6. **Fix the 2002-2009 month shift** by reconciling Crossref dates with AEA issue metadata; use issue dates for issue-level analysis.
7. **Add institution resolution:** campus-aware UC parsing, OpenAlex institution IDs, fallback for the 1,013 missing hints, and cleanup of the 266 malformed fragments.

### P2 — validators, enrichment, and documentation

8. Add page-range and within-issue continuity validators; correct the 3-6 corrupt ranges.
9. Add retraction status and `update-to`/`relation` handling.
10. In M2, get JEL codes from AEA article pages; use OpenAlex for abstract backfill with boilerplate filtering and provenance.
11. Normalize journal identity fields and add numeric sort keys for volume/issue/pages.
12. Correct `data/reports/m1_quality.md`, `README.md`, `docs/methodology.md`, and `docs/data-sources.md` with the audited counts: rank coverage 0.37%, duplicate count at least 63, corrected article/P&P/slot baselines.
13. Add regression tests for the enumerated `paper_id`s, `authorship_id`s, duplicate pairs, and date/rank cases.

## Remediation status (P0, 2026-10-22)

**Completed:**

- Pipeline order: content classification and deduplication now run before author resolution, so duplicates and non-research records cannot create ghost authors.
- Classification: administrative/editorial records are excluded; research articles **4,786**, P&P **1,795**, association reports/minutes 324, front matter 223, unattributed 49, errata 17, retraction notices 2, duplicates **67**.
- Deduplication: punctuation-insensitive title keys, normalized issues, roman/numeric page ranges, author-set similarity, and an administrative-paratext pass. The 67 duplicates match the audit's corrected count.
- Author resolution: middle-initial-, particle-, and Unicode-aware matching; 5,891 canonical authors, 6,381 aliases, 7 pending merge candidates, 47 review flags. Known namesakes are split (Robert L Clark / Robert Clark, Margaret McConnell, Jing Wu, Robert Gordon, Michael Walker); an additional Kevin M / Kevin J Murphy merge was caught and split.
- Retractions: 2 originals carry `retraction_status='retracted'` with notice pointers; 2 notices are typed `retraction_notice`; the Mundell 2002 erratum is typed `erratum`.
- Author suffixes (Jr./II/III) are parsed; UC campuses are retained in institution hints; street-name false-positive ranks are suppressed.
- Coauthorship edges rebuilt from canonical authorships: **9,375** edges, no self-edges or orphan references.
- Database integrity re-checked: `PRAGMA integrity_check='ok'`, zero foreign-key violations, no duplicate canonical names.

**Still open (P1/P2):**

- 2002–2009 issue-month shift — resolved in M2 via the AEA all-issues calendar; see the M2 status below.
- Institution entity resolution and the 1,013 author slots without an institution hint — partially resolved in M2 via OpenAlex (10,188 slots now have an OpenAlex institution).
- Page-range validators, retraction links from Crossref `update-to`/`relation`, JEL/topic ingestion, abstract backfill — addressed in M2; see below.

## Remediation status (M2, 2026-10-22)

**Completed:**

- Issue months: the AEA all-issues calendar maps every volume/issue to its cover month, including combined issues such as 2018 No. 4-5. Every article month now comes from the calendar or an AEA article page (currently 4,086 and 700 respectively); no article relies on the Crossref fallback. `published_day` is cleared when the month is replaced; the raw Crossref date remains in `source_records`. The calendar confirms the P&P issue is May in every year 2000–2017.
- OpenAlex: 4,735 of 4,786 articles matched by DOI (98.9%); 1,210 abstracts backfilled, of which 377 were citation boilerplate and removed (833 retained); 14,199 topic rows; 990 resolved institutions; 10,188 author slots with an OpenAlex institution; 5,520 canonical authors with an OpenAlex ID.
- Author layer (at M2): rebuilt to 5,889 canonical authors and 6,381 aliases. Two resolver splits were repaired with OpenAlex evidence (W. Michael Hanemann / W Michael Hanemann; Steven D Levitt / S Levitt). Seven merge candidates remained; M3 later resolved all seven and split three multi-ID over-merges.
- Retractions: Crossref `update-to` is now the primary link; both AER retraction pairs resolve correctly.
- Abstracts: provenance stored in `abstract_source`; Crossref, AEA, and OpenAlex versions kept separately; OpenAlex citation-boilerplate filtered.
- Page ranges: abbreviated end pages expanded (`1705-41` → `1741`); one genuine reversed range remains and is reported.
- Author disambiguation: middle name filed as a family token (`W`, `Michael Hanemann`) is now normalized.

**Still open (M3/P2):**

- AEA JEL crawl is partial (698 of 4,786 articles, 14.6%) because AEA rate-limits bulk requests; the crawler is resumable from its HTML cache. Coverage is reported in `m2_quality.md`; OpenAlex topic coverage is 98.9% independently.
- 7 merge candidates and 40 multi-OpenAlex-ID authors need review; most multi-ID cases are OpenAlex profile fragmentation, but some may be resolver over-merges (e.g. John W. Morgan vs John M. Morgan).
- 51 articles are absent from OpenAlex (mostly 2006–2007 and 2026); their Crossref metadata is complete but topics/author IDs/institutions are missing.
- 180 author slots still lack an institution hint; Crossref byline fragments remain in `institution_hint`.
- One reversed page range (`10.1257/aer.20181830`) needs source correction.
- P&P flags should be manually verified issue by issue.

## Remediation status (M3, 2026-10-22)

**Completed:**

- Stable identity: 5,892 canonical authors have unique `stable_id` values backed by `author_identity_ledger`; `author_identity_events` records creation, reconciliation, merge, and split events.
- Merge candidates: all 7 pending name candidates were resolved as splits, with OpenAlex/institution/middle-initial evidence recorded in `review_notes`.
- Multi-ID review: 40 authors with multiple OpenAlex IDs were reviewed. 3 confirmed over-merges were split (John W./M. Morgan, Benjamin I./R. Page, Daniel G./M. Sullivan); 32 were accepted as OpenAlex profile duplication; 5 remain uncertain and flagged.
- Split protection: 9 permanent `author_separation_rules` cover the OpenAlex-ID and authorship pairs, so a later author-table rebuild cannot silently re-merge the split people. A full rebuild-plus-M3 test preserves the split authors and stable IDs, and restores all 669 career assignments.
- Career layer: 669 byline-documented assignments (6.2% of slots), all `byline_rank`/high confidence; 632 non-academic, 23 full professor, 4 research fellow, 3 assistant professor, 3 associate professor, 2 lecturer/other academic, 1 emeritus, 1 PhD student.
- 28 authors remain flagged for OpenAlex fragmentation after resolving the namesake and multi-ID cases.

**Still open (M4/P2):**

- 5 multi-ID authors remain uncertain; 28 OpenAlex fragmentation flags remain.
- 10,113 article slots have no career assignment; CV timeline extraction is M4.
- AEA JEL crawl remains partial (698/4,786) because of rate limiting; OpenAlex topics cover 98.9% independently.
- 51 articles are absent from OpenAlex; 481 abstracts remain missing; 180 slots lack an institution hint; one reversed page range remains.

## Remediation status (M4, 2026-10-22)

**Completed:**

- ORCID identity: 3,314 of 5,892 canonical authors retain an ORCID after validation. 2,409 are accepted: 1,397 by matching AER DOI, 181 by matching title, 539 by institution overlap, and 292 by a low-confidence economics-field signal. 905 are unverified links whose events are withheld. 72 person-name conflicts, 165 clear field mismatches, and 12 career-risk links are rejected and cleared.
- ORCID events: 2,067 accepted identities contribute 5,847 employment/education events, of which 4,583 have a start year. Every ORCID link is checked against the author's AER record before its events are used.
- Career assignments: 2,264 of 10,782 article slots (21.0%) now have a stage: 669 byline, 1,591 ORCID, and 4 CV pilot. Byline evidence remains paper-specific and takes precedence; generic "Professor" titles are low confidence. 1,349 assignments are high/medium confidence and 915 are low.
- CV layer: 1,088 public CV/homepage sources were seeded from ORCID researcher URLs. The pilot parsed 17 CVs, extracting 60 dated events and 4 assignments. Raw documents are stored only in the local ignored cache.
- ORCID/CV provenance is explicit in `career_events` (`source_type`, `source_url`, `source_snippet`, confidence) and `career_assignments` (`evidence_type`, `career_event_id`, confidence). `authors.orcid_source` records the identity tier or rejection reason.

**Still open (M5/P2):**

- 8,518 article slots remain without a career assignment; full CV discovery/parsing is resumable.
- 900 of 956 full-professor assignments are low-confidence generic "Professor" titles and need CV/rank corroboration.
- ORCID review remains: 905 unverified links, 292 low-confidence economics-field links, 72 person-name conflicts, 165 field mismatches, and 12 career-risk rejections. 5 multi-ID authors also remain uncertain.
- The CV parser has only been piloted on 17 documents; precision on a larger sample is not yet measured.
- AEA JEL remains partial (698/4,786); OpenAlex topics cover 98.9% independently.
- The 7 pending merge candidates and 47 review-flagged authors need OpenAlex/CV evidence or manual review.

## Policy decisions needed

1. **Retracted originals:** keep them with a `retraction_status` flag but exclude from default counts, or exclude entirely?
2. **P&P:** keep P&P articles in the research-article count with `is_pp=1` (current policy), or report them as a separate series by default?
3. **Duplicates:** mark and retain duplicates (current policy) or delete them? Marking preserves auditability and is recommended.
4. **Author merges:** automatic merge only for high-confidence clusters, with a review queue for conflicting affiliations. Blind merging of all 456 IDs would introduce at least one confirmed namesake error.
