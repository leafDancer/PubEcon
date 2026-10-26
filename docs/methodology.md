# Methodology

This document defines what EconPub measures, how each field is derived, and where the uncertainty lies. It is intended to be published alongside the database.

## Unit of analysis

- **Paper:** a Crossref record belonging to one of the five journals in scope — the *American Economic Review*, *Quarterly Journal of Economics*, *Journal of Political Economy*, *Review of Economic Studies*, or *Econometrica* — published in 2000 or later. The AER-only baseline and the combined top-five pilot are separate databases with separate reports.
- **Authorship:** one author in one paper, in byline order.
- **Author:** a canonical entity resolved by ORCID when available and otherwise by a middle-initial-, particle-, and Unicode-aware name key with explicit namesake exclusions.
- **Career assignment:** the inferred stage of one author at the publication date of one paper.

## Journal dimension

`papers.journal_code` is a first-class field (`AER`, `QJE`, `JPE`, `RES`,
`ECMA`). It is set at ingest from the journal registry and never inferred from
the container title.

- **Article-type rules are journal-specific.** Generic rules cover issue
  metadata, errata/addenda, announcements, editorial boards, covers, referee
  lists, indexes, supplements, and records with no authors. AER-only rules cover
  Papers & Proceedings, AEA reports/minutes, and AEA front matter. JPE
  turnaround tables, RES meeting notices, and Econometric Society reports have
  their own rules.
- **Deduplication is scoped by journal.** Title, year, volume, issue, and page
  overlap are compared only within the same journal, so an identically titled
  paper in two journals is never merged.
- **Cross-journal identities are merged explicitly.** The same person may have
  papers in several journals; canonical authors are resolved across the whole
  corpus, not per journal. OpenAlex-supported merges retain the same evidence
  and review rules as the AER-only layer.
- **Missing bylines.** When a Crossref deposit has no authors, OpenAlex work
  authorship may supply the byline. Created rows carry
  `openalex_match_method='openalex_backfill'`, the raw affiliation, and
  `institution_source='openalex'`; Crossref authors are never replaced.
- **Coverage is reported per journal.** A pooled coverage number is never shown
  without the per-journal breakdown.

## Career-stage taxonomy

| Stage | Definition |
|---|---|
| `undergraduate` | Enrolled in a bachelor's programme at publication time |
| `masters_student` | Enrolled in a master's programme |
| `phd_student` | Enrolled in a doctoral programme, including candidates |
| `postdoc` | Postdoctoral position |
| `assistant_professor` | Assistant professor or equivalent entry-level tenure-track rank |
| `associate_professor` | Associate professor; usually tenured in the US, but not assumed |
| `full_professor` | Full professor |
| `lecturer_other_academic` | Lecturer, reader, instructor, or similar teaching-track rank |
| `research_fellow` | Named research fellow/scientist position |
| `emeritus` | Emeritus/emerita |
| `non_academic` | Central bank, government, international organisation, industry, consulting |
| `unknown` | Insufficient evidence |

"Tenured" is **not** a separate observed category. In the US, associate and full professors are usually tenured, but this cannot be verified from bylines. The frontend will show rank and, where evidence supports it, a separately labelled tenure inference. It will not silently equate rank with tenure across countries.

## Evidence hierarchy

Each `career_assignments` row carries `evidence_type`, `confidence`, and `source_url`.

1. **`byline_rank` / `byline_affiliation` — high or medium confidence, but rare**
   The publish-time affiliation string explicitly states a rank, e.g. "Assistant Professor of Economics, Princeton University". This is contemporaneous evidence, not a reconstruction. In the AER 2000+ corpus only about 0.3% of author slots carry an explicit academic rank, so this source cannot carry the career layer on its own. Explicit student/postdoc phrases are medium confidence.

2. **`orcid_employment` / `orcid_education` — high, medium, or low confidence**
   ORCID records provide self-reported, dated employment and education. An event is used only when its start/end interval covers the paper year, and only after the ORCID-to-author link passes identity validation (see below). Explicit rank titles are high confidence; generic "Professor" titles are low confidence because the title may be current rather than the rank at the paper date. Doctoral education intervals support `phd_student` at medium confidence.

3. **`wayback_employment` — medium or low confidence**
   A Wayback Machine snapshot of a faculty or personal page near the paper year can show the rank that was current at the time. The parser looks for an academic rank phrase near the author's family name and uses the paper's byline institution. It ignores non-academic titles, caps confidence at medium, and does not assign when the page does not mention the author.

4. **`cv_employment` / `cv_education` — high or medium confidence**
   Public CVs and faculty pages provide dated positions and degrees. The parser is section-based and conservative; events are used only after byline, ORCID, and Wayback evidence are absent. Exact intervals with title and institution are high confidence; single years or missing institutions are medium.

5. **`heuristic` — low confidence**
   Used only when the structured sources are unavailable. Heuristic assignments are always labelled as such.

6. **`unknown`**
   No assignment is stored when the evidence is insufficient. The UI shows a missing badge rather than guessing.

## Author disambiguation

The canonical author layer is rebuilt after content classification and deduplication, so duplicate or non-research records cannot create ghost authors. The resolver uses:

- **ORCID** when present (authoritative).
- A **match key** that removes middle initials and leading initials, absorbs surname particles (`van`, `de`, `dal`, …), transliterates non-ASCII letters instead of dropping them, and handles Crossref's occasional placement of a particle in the given-name field or a middle name in the family-name field.
- **Variant merge** across spellings such as `Parag A Pathak` / `Parag Pathak`, `James A Robinson` / `James Robinson`, and `Abhijit Vinayak Banerjee` / `Abhijit Banerjee`.
- **Conflict splits** that keep distinct people separate when they share the same given/family root but have different middle initials, suffixes, ORCIDs, or a confirmed namesake pattern. Known conflicting pairs are listed explicitly; other uncertain pairs go to `author_merge_candidates` with institutions and years.
- A `needs_review` flag for merged or conflicting clusters; the public methodology page will report the count.

This is still name-based, supplemented by OpenAlex evidence. OpenAlex work authorship supplies an author ID for each matched byline. Matching aligns by byline position when the author counts agree and every name is compatible; otherwise it matches by a unique name. Of 10,782 article author slots, 10,126 (93.9%) match an OpenAlex authorship: 6,007 with high confidence and 4,119 with medium confidence. If all of a canonical author's matched authorships point to one OpenAlex ID, that ID is attached. If they point to several IDs, the author is flagged and the evidence is stored in `author_openalex_evidence`; if several canonical authors share one OpenAlex ID and never co-occur on a paper, the pair is queued as a merge candidate. Only pairs whose names are compatible are merged automatically; everything else waits for manual review.

Current result: 5,892 canonical authors, 6,382 aliases, 0 pending merge candidates, and 5,526 authors with an OpenAlex ID. Seven name-based candidates were resolved as splits; three resolver over-merges were split after OpenAlex review; 32 multi-ID authors were accepted as OpenAlex profile duplication; 5 remain uncertain. 28 authors carry OpenAlex fragmentation flags. ORCID identity validation is a separate review layer, described below: 3,314 authors retain an ORCID, 2,409 with accepted identity evidence and 905 as unverified low-confidence links.

## Stable author identity

`authors.author_id` is an internal key that can change when the author table is rebuilt. Public-facing identity uses `authors.stable_id`, stored in `author_identity_ledger`, which survives rebuilds. The ledger records the person's ORCID, OpenAlex ID, canonical name, name keys, publication-year range, institutions, current author row, and status (`active`, `merged`, `inactive`).

Stable IDs are reconciled after a rebuild by, in order: ORCID, OpenAlex ID, exact name plus year overlap, match key plus year overlap, and institution overlap. A ledger row with no successor is marked `merged` or `inactive`; it is never silently reused for a different person. `author_identity_events` records `created`, `reconciled`, `merged`, and `split` events.

Confirmed name splits are protected by `author_separation_rules`. Each rule records the two OpenAlex IDs and the cross-group authorship pairs, so a later name-only rebuild cannot silently re-merge the two people. The kept group retains the original stable ID; each new group receives a new stable ID.

## Coauthorship network

- **Nodes** are canonical authors. **Edges** are undirected and unweighted: two
  authors are connected when they shared at least one research article. Two
  authors with five shared papers are still one step apart in path queries.
- **Shortest paths** use breadth-first search. The product returns one
  deterministic shortest path, not all of them; a different equally short path
  may exist. Each step carries the shared papers that establish the tie, so the
  connection is inspectable.
- **Journal-scoped graphs** use only papers in the selected journal. A tie in
  the QJE graph is a QJE coauthorship, even if the same two authors also wrote
  an AER paper.
- **Average path length and diameter** are computed over unordered pairs in the
  largest connected component. Authors outside that component are reported as
  components, not as infinitely distant pairs. This avoids hiding fragmentation
  inside a single "average distance" number.
- **Clustering** is the mean local clustering coefficient: the share of an
  author's coauthor pairs that also coauthor with each other.

## Rankings

Overview leaderboards are descriptive, not evaluations:

- **Assistant-professor output** counts papers with an explicit
  `assistant_professor` assignment at high or medium confidence. It reports
  known-stage papers over all top-five papers; authors with more complete
  documentation can rank higher for that reason.
- **Five-journal authors** require at least one research article in each of
  AER, QJE, JPE, RES, and ECMA, and are ranked by total papers.
- **Most coauthors** counts distinct coauthors across all five journals. A
  single large-team paper can place an early-career author high on this list.
- **Strongest pairs** count shared research articles; up to three papers are
  shown per pair.
- **Largest teams** rank papers by author count and exclude papers whose byline
  was recovered from OpenAlex, because that fallback is not reliable enough for
  a byline ranking.
- **Longest careers** measure the span between the first and last top-five
  article, not the author's full academic career.
- **Institutions** rank primary publish-time OpenAlex affiliations by author
  slots. Coverage varies by journal, and the primary flag is positional rather
  than an employer-of-record claim.

Rankings never combine career coverage, citations, and network position into a
composite "influence" score. A missing stage is not treated as zero output.

## ORCID identity validation

An ORCID link is not accepted merely because OpenAlex attached it to an authorship. Each link is assessed against the author's AER record:

| Tier | Evidence | Career events |
|---|---|---|
| `verified_doi` | An ORCID work DOI matches one of the author's AER DOIs | Used; event confidence retained |
| `verified_title` | An ORCID work title matches an AER paper title | Used; event confidence retained |
| `verified_institution` | ORCID employment/education overlaps an AER byline institution | Used; capped at medium confidence |
| `field_economics` | An economics department or core economics journal, with no direct AER link | Used; capped at low confidence and flagged |
| `orcid_unverified` | No positive evidence and no contradiction | ORCID retained as a low-confidence identity link; events withheld |
| `rejected_name` | ORCID person name conflicts with the canonical author | Rejected; events and assignments cleared |
| `rejected_field` | Clear non-economics field signal (medicine, engineering, law, etc.) | Rejected; events and assignments cleared |
| `rejected_career_risk` | A dated event would change a publication's stage, but no positive identity evidence exists | Rejected; events and assignments cleared |

The field test counts economics and non-economics signals rather than rejecting on a single word, and it uses employment and doctoral affiliation rather than incidental paper titles. Name matching uses ORCID credit names and other names, strips suffixes, and recognizes common nickname and transliteration variants before declaring a conflict. This prevents a health economist with one "medical" paper from being rejected, while rejecting a surgeon, political scientist, or computer scientist who happens to share a name. Rejected links leave the authorship-level ORCID in place as provenance, so a later validation pass can reconsider them.

Result: 1,397 DOI-verified, 181 title-verified, 539 institution-verified, 292 low-confidence economics-field, 905 unverified, 72 name-conflict, 165 field-mismatch, and 12 career-risk rejections. Only the first four tiers contribute career events.

## Career assignments

M3 writes `career_assignments` only where the publish-time byline supplies evidence:

- `byline_rank` — high confidence: an explicit rank extracted from the affiliation string, such as Assistant Professor, Full Professor, Research Fellow, or a non-academic title.
- `byline_affiliation` — medium confidence: an explicit student/postdoc status such as "PhD student" or "postdoctoral fellow".

M4 and M6 extend this with ORCID, CV, and historical-page evidence. The current layer assigns 2,305 of 10,782 article slots (21.4%): 669 byline, 1,591 ORCID, and 45 CV assignments. By stage: 965 full professor (909 of them low-confidence generic "Professor" titles), 693 non-academic, 266 assistant professor, 227 associate professor, 44 PhD student, 37 research fellow, 32 emeritus, 28 lecturer/other academic, and 13 postdoc. The remaining 8,477 slots are left unknown rather than inferred.

ORCID is the highest-yield structured source after identity validation: 3,314 of 5,892 canonical authors retain an ORCID, 2,409 have accepted identity evidence, and 2,067 identities contribute 5,847 employment/education events (4,583 with a start year). CV discovery is seeded from ORCID researcher URLs; the crawl parsed 268 documents and 1,129 events. The queue is empty; 370 homepages and 72 CV documents remain unreachable. The full crawl remains resumable. ORCID links that fail identity validation are withheld and flagged rather than attached.

## Publication dates and issue months

Crossref's publication month is one month earlier than the AEA issue cover month for 2002–2009. The pipeline applies a four-level hierarchy:

1. **AEA article page** `citation_publication_date` — high confidence, article-specific.
2. **AEA all-issues page** (`/journals/aer/issues`) — high confidence, maps every volume/issue to its cover month, including combined issues such as 2018 No. 4-5.
3. **Crossref issue metadata** — high confidence where present (2002–2007).
4. **AER five-issue calendar** — medium confidence for 2008–2009, used only when the first two are unavailable.

Every article month now comes from the AEA issue calendar or an AEA article page (currently 4,086 and 700 respectively); no article relies on the Crossref fallback. The issue calendar confirms the P&P issue as May: No. 2 in 2000–2010, No. 3 in 2011–2013, and No. 5 in 2014–2017.

When the month is replaced, `published_day` is cleared because the source only supports month precision. The original Crossref date remains in `source_records`. OpenAlex `publication_date` is stored separately but not used for correction: it inherits the same shift.

## JEL and topics

JEL codes are parsed from the `JEL Classification` block on AEA article pages and stored in `paper_topics` with `scheme='jel'`, the code, and the official description. OpenAlex topics are stored separately with `scheme='openalex_topic'` and a relevance score. The two schemes are never merged: JEL is author-assigned and editorial, while OpenAlex topics are machine-generated.

AEA rate-limits bulk crawling, so JEL coverage is partial and reported explicitly; the crawler is resumable from its HTML cache. The frontend shows JEL where available and OpenAlex topics otherwise, without presenting one as the other.

## Abstracts

Every article records where its abstract came from in `papers.abstract_source`:

- `crossref` — abstract supplied in the Crossref deposit;
- `aea` — parsed from the AEA article page;
- `openalex` — reconstructed from OpenAlex's inverted index.

The preferred abstract is stored in `abstract`; AEA and OpenAlex versions are retained in `abstract_aea` and `abstract_openalex` for audit. OpenAlex sometimes reconstructs the AEA page description ("Title by Authors. Published in volume ...") as an abstract; those records are filtered as boilerplate and either replaced by an AEA abstract or marked missing.

## Citation counts

Crossref's `is-referenced-by-count` is stored in `papers.citation_count`; OpenAlex's `cited_by_count` is stored separately in `papers.openalex_cited_by_count`. They are not reconciled. Both are as-reported by the source and can be affected by duplicate works, citation-matching errors, or differences in what counts as a citation. The API and frontend prefer OpenAlex and fall back to Crossref, always labelling the source; the database does not present a single "true" citation count.

These are **not Google Scholar counts**. Google Scholar indexes full text, working papers, books, theses, slides, and other grey literature, and has no public, reproducible API. OpenAlex and Crossref index a narrower set of works; Crossref's count is based on references deposited by publishers, which many publishers do not deposit in full. Counts from OpenAlex, Crossref, and Google Scholar therefore differ systematically, and OpenAlex can also split or merge works. The project uses OpenAlex/Crossref because they are documented, DOI-keyed, and reproducible; it does not scrape Google Scholar.

## Institution resolution

Each authorship can carry several publish-time institutions. `authorship_institutions` stores resolved OpenAlex institution IDs with a primary flag and provenance; `institutions` stores the OpenAlex ID, display name, country, ROR, and type. The primary flag is positional (the first institution listed by OpenAlex), not a claim about which institution was the author's employer of record. The Crossref byline string remains in `authorships.institution_hint` and is never overwritten when it is non-empty. This preserves the difference between the publisher's string and the resolved entity.

## Publish-time vs current information

Career stage is evaluated **at the paper's publication date**, not at the time of data collection. A current faculty page is therefore only weak evidence about a 2005 paper. The preferred sources are:

- the byline itself;
- CVs that list dated positions;
- archived faculty pages where available.

## Papers & Proceedings

Through 2017, the AER published its Papers & Proceedings as a large spring issue. The issue number is not stable (2 in 2000–2010, 3 in 2011–2013, 5 in 2014–2017), so the pipeline identifies P&P by the issue's structure: the largest April/May issue in the year, with at least 50 articles. The AEA all-issues calendar confirms that the selected issue is the May issue in every year 2000–2017. From 2018, the P&P became a separate journal (*AEA Papers and Proceedings*) and is outside the AER scope.

## Content types

Not every Crossref AER record is a research article. M1 assigns a `content_type` and excludes all non-research types from publication and network statistics:

| `content_type` | Meaning |
|---|---|
| `article` | Research article, including P&P papers (`is_pp = 1`) |
| `front_matter` | Untitled front matter, cover pages, annual meeting notices |
| `association_report` | AEA committee reports, minutes, Job Openings reports |
| `issue_metadata` | Crossref `journal-issue` records with no article content |
| `unattributed` | Article-like record with no author metadata |
| `erratum` | Erratum, corrigendum, or correction |
| `retraction_notice` | Retraction notice; the original stays `article` with `retraction_status='retracted'` |
| `duplicate` | Crossref duplicate of a canonical record (research or paratext) |

## Deduplication

Crossref contains duplicate deposits across issues and paratext. The resolver compares a punctuation- and quote-insensitive title key, normalised issue number, page range (roman numerals included), and author-set similarity. Research-article pairs with identical pages are merged even when one deposit has incomplete author metadata; pairs with only overlapping pages require author-set agreement. A separate pass handles same-issue administrative paratext with identical pages.

The 2000+ AER harvest yields **67 duplicate rows**, including the 51 legacy/modern DOI pairs in 2006 issue 4 and 2007 issue 1, two research-article pairs, one erratum pair, and P&P front-matter pairs. The modern `10.1257/aer...` DOI is retained as canonical where possible; the other record is marked `content_type = 'duplicate'` with a pointer to the canonical `paper_id`. Duplicates are excluded from all statistics and network construction but remain in the database for auditability.

## Missing data and reporting

- Missing affiliations, ranks, abstracts, and career assignments are stored as missing, never imputed silently.
- The quality report publishes coverage by year.
- The public site will show coverage badges and a link to this methodology.
- Any change to the inference rules will be versioned and dated.

## Known limitations (post-M4)

- **Issue months:** the 2002–2009 one-month shift is fully corrected. Every article month comes from the AEA all-issues calendar or an AEA article page (currently 4,086 and 700 respectively); the Crossref issue-metadata and AER-calendar fallbacks are no longer needed for any article. `published_day` is cleared when the month is replaced because the issue source only supports month precision; the raw Crossref date remains in `source_records`.
- **Institution resolution:** OpenAlex resolves a publish-time institution for 10,188 of 10,782 author slots (94.5%); combined with the Crossref byline hint, 10,602 slots (98.3%) have some institution evidence. 180 slots remain missing, and Crossref byline fragments (e.g. "and Development Studies Institute") remain in the raw `institution_hint` field.
- **Academic rank:** explicit byline rank is present on only 0.3% of author slots. ORCID and CV timelines extend coverage, but 909 of 965 full-professor assignments come from generic "Professor" titles and are low confidence.
- **Stable author IDs:** M3 introduced `authors.stable_id` and `author_identity_ledger`. `resolve_all_authors` preserves the ledger, restores `career_assignments` by `authorship_id`, and reassigns stable IDs by ORCID, OpenAlex ID, name/year, and institution. A rebuild still requires a subsequent `m2`/`m3`/`m4` pass to refresh OpenAlex links and review labels; stable IDs and separation rules survive.
- **Author review queue:** 0 merge candidates remain pending; 7 were resolved as splits. Of the 40 multi-ID authors, 3 were confirmed over-merges and split, 32 were accepted as OpenAlex profile duplication, and 5 remain flagged as uncertain (David S Johnson, Jean Lee, Jose Maria Fernandez, Daniel Chen, André Meier). 28 authors carry OpenAlex fragmentation flags. ORCID review is larger and separate: 905 unverified links, 292 low-confidence economics-field links, 72 person-name conflicts, 165 field mismatches, and 12 career-risk rejections.
- **Career coverage:** byline + ORCID + CV covers 2,305 of 10,782 slots (21.4%); 8,477 remain `unknown`. ORCID records are self-reported and often lack dates; the CV parser is section-based and 268 documents have been parsed. Full CV coverage is a resumable crawl, not a completed corpus.
- **ORCID identity:** 72 ORCID records name a person who does not match the canonical author under the name-compatibility rule. 165 more are rejected for a clear non-economics field, and 12 would change a career stage without positive identity evidence. Their events are not attached; they need manual review or an alias update.
- **CV corpus:** 1,362 public CV/homepage sources are tracked, and 268 documents have been parsed. The queue is empty; 370 homepages and 72 CV documents remain unreachable. Raw CVs are stored only in the local ignored cache; the public database stores structured events and short snippets. See `docs/m4-validation.md` for concrete spot checks and parser fixes.
- **JEL and topics:** JEL codes are parsed from AEA article pages; OpenAlex topics are a separate scheme. JEL coverage is reported in `data/reports/m2_quality.md` and varies by year.
- **Abstracts:** coverage is 89.9% after OpenAlex backfill and boilerplate filtering; 481 articles still lack an abstract. Of the 1,210 OpenAlex abstracts, 377 were citation boilerplate and were removed. AEA abstracts are preferred when present.
- **OpenAlex coverage:** 51 AER articles are not indexed by OpenAlex, mostly 2006–2007 and the newest 2026 issue. OpenAlex is also allowed to supply a byline only when the publisher deposit has none; those authorships are marked `openalex_backfill` and never replace an existing Crossref byline. The top-five pilot used this to recover 359 Econometrica articles whose Crossref deposits omit authors.
- **Page validation:** one reversed numeric page range remains (`10.1257/aer.20181830`); it is flagged and will be corrected against the AEA page.
- **P&P flags:** identified structurally by the largest spring issue; the AEA issue calendar confirms that the selected issue is the May issue in every year 2000–2017 (No. 2, No. 3, or No. 5 as the numbering changed).

## Privacy and ethics

- No birth dates, home addresses, phone numbers, or email addresses are stored.
- CV data is reduced to degree/employment facts with a source URL.
- Only metadata and short excerpts are stored; full texts are not redistributed.
- A correction and takedown process will be available before public launch.
