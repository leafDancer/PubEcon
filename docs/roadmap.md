# Roadmap: expanding from AER to the top five journals

The current product covers the *American Economic Review* (AER), 2000–present. The
next major scope change is to cover the five journals most often treated as the
top five in economics:

| Code | Journal | ISSN (print) | Publisher (2000–present) |
|---|---|---|---|
| AER | American Economic Review | 0002-8282 | AEA |
| QJE | Quarterly Journal of Economics | 0033-5533 | MIT Press / Oxford |
| JPE | Journal of Political Economy | 0022-3808 | University of Chicago Press |
| RES | Review of Economic Studies | 0034-6527 | Oxford University Press |
| ECMA | Econometrica | 0012-9682 | Econometric Society / Wiley |

The goals that distinguish EconPub do not change: coauthor-network topology,
career stage at publication, explicit provenance and confidence, and visible
missingness. Expanding the journal set increases the value of the first two —
a cross-journal coauthor network is far more informative than five separate
single-journal graphs — while increasing the scale and the validation burden.

## Scale estimate

Crossref reports the following record counts for 2000–present (queried
2026-10-26, `rows=0`):

| Journal | Crossref records 2000–present |
|---|---|
| AER | 5,498 |
| QJE | 1,368 |
| JPE | 2,143 |
| RES | 1,832 |
| ECMA | 2,602 |
| **Total** | **13,443** |

These include book reviews, comments, editorials, and other non-research
items, so the research-article count will be lower. The author-slot count is
likely roughly 2.5–3× the current AER corpus; the exact figure depends on
article classification and byline parsing.

## Why this is a planned milestone, not a config change

The existing pipeline is AER-specific in several places:

- `config.py` hard-codes one journal name and ISSN.
- AEA issue pages supply the article calendar and some byline detail; QJE, JPE,
  RES, and Econometrica do not use the AEA platform.
- The article-type classifier is tuned to AER's sections (Articles, Shorter
  Papers, Papers & Proceedings, Comments and Replies).
- The API and frontend assume one journal in overview, filters, and labels.
- Career coverage is reported against AER slots only.

A journal is therefore a first-class dimension of the data model, not a filter
applied after ingestion.

## M7.1 status (2026-10-26)

The multi-journal data foundation is in progress:

- A journal registry (`config.JOURNALS`) now holds the five codes, names, and
  print ISSNs. `harvest --journal {AER,QJE,JPE,RES,ECMA}` selects one.
- `papers.journal_code` is part of the schema, backfilled to `AER` for the
  existing database, and indexed with `(journal_code, published_year)`.
- Crossref page caches are namespaced per journal (`data/raw/crossref/pages/QJE/`).
- The classifier now separates generic rules (issue metadata, errata,
  announcements, editorial board/table-of-contents pages, duplicates) from
  AER-only section conventions (P&P, AEA reports, AEA front matter). AER output
  is unchanged; the AER-only SQL is gated by `journal_code`.
- All four new journals were piloted in separate databases, not merged into the
  public AER corpus. Every Crossref record for 2000–present was ingested:

| Journal | Records | Research articles | Author slots | Abstracts (after OpenAlex) | Unattributed |
|---|---|---|---|---|---|
| QJE | 1,368 | 1,181 | 3,085 | 1,164 | 0 |
| JPE | 2,143 | 1,501 | 3,478 | 1,327 | 0 |
| RES | 1,832 | 1,748 | 4,034 | 1,715 | 0 |
| ECMA | 2,602 | 1,741 | 3,858 | 1,623 | 29 |

- The classifier gained generic rules for announcements, editorial-board and
  cover pages, referee lists, indexes, errata/addenda, and supplements, plus
  journal-specific rules for JPE turnaround/cover records, RES meeting notices,
  and Econometric Society reports. No pilot has an unclassified editorial
  record left.
- OpenAlex backfilled missing bibliographic metadata without replacing the
  Crossref record:
  - **JPE had no Crossref abstracts at all**; OpenAlex supplied 1,327.
  - **ECMA 2008–2014 deposits omit authors** for 388 articles. OpenAlex
    recovered 359 of them, raising ECMA from 1,382 to 1,741 articles and from
    3,058 to 3,858 author slots. The remaining 29 stay `unattributed`.
- The combined research-article base is now **25,237 author slots**
  (AER 10,782 plus 14,455 in the four new journals), about 2.3× AER.
- Three identity-layer edge cases surfaced and were fixed: an ORCID can no
  longer be assigned to two components split by a namesake rule, a merge
  candidate whose author was already merged in the same pass is left pending
  instead of dereferencing a missing row, and a component bridged across a
  namesake rule is split on the rule's OpenAlex IDs.
- Cross-journal overlap is substantial even before the ORCID pass: the four
  pilot databases contain **6,220** distinct OpenAlex-linked authors, of whom
  **1,814** appear in at least two journals and **651** in at least three.
  Merging identities across journals is therefore the main value of M7.2, not
  a cosmetic deduplication step.

### Combined top-five pilot (2026-10-26)

A separate `top5.db` was built from cached Crossref pages with all five
journals, OpenAlex enrichment, author resolution, and OpenAlex-supported
merges. It is a validation build, not the served database.

| Journal | Research articles | Author slots | Abstracts |
|---|---|---|---|
| AER | 4,787 | 10,786 | 4,305 |
| RES | 1,748 | 4,034 | 1,716 |
| ECMA | 1,740 | 3,859 | 1,621 |
| JPE | 1,500 | 3,477 | 1,329 |
| QJE | 1,181 | 3,085 | 1,164 |
| **Total** | **10,956** | **25,241** | **10,135** |

- OpenAlex backfilled **801** authorships, including 12 AER articles that
  lacked Crossref authors and 359 ECMA articles. A later administrative cleanup
  moved 11 AER society records out of the article count, leaving 4,787 AER
  research articles in the combined database.
- The combined identity layer has **10,065 canonical authors** and **24,478**
  coauthorship edges.
- Cross-journal reach is large: **3,337** authors appear in at least two
  journals, **1,496** in at least three, and **178** in all five.
- All three AER namesake pairs survive the from-scratch rebuild
  (Page/Sullivan/Morgan). The first pass still merged John W./M. Morgan through
  a 2009 byline without an OpenAlex ID, so the resolver now splits any component
  that contains both sides of a known namesake rule: the OpenAlex IDs anchor the
  two sides, and unlinked bylines are assigned by institution overlap, name
  compatibility, and year proximity. Ambiguous bylines stay in their own review
  component. This is a general fix, not a special case for Morgan.

### M7.3 pilot: ORCID career layer (2026-10-26)

The combined database now has an ORCID career layer:

- **5,988** ORCID identifiers were read (3,583 already cached, 2,403 fetched
  in this run; 2 failed with HTTP 409). **3,499** records parsed into **9,803**
  dated events.
- Identity tiers: 2,376 verified by DOI, 346 by title, 899 by institution, 454
  by economics-field signal, 1,439 unverified (events withheld), 150 rejected
  for name conflict, 294 for field mismatch, and 28 for career risk.
- **4,003 of 25,241 author slots (15.9%)** receive an ORCID career stage,
  plus **106** CV assignments (438 parsed documents, 1,895 events), for
  **4,109 total assignments (16.3%)**. Confidence: 506 high, 1,143 medium, and
  2,280 low from ORCID, plus 18 high, 58 medium, and 30 low from CV.

| Journal | Slots | Assigned | Coverage | High/medium |
|---|---|---|---|---|
| AER | 10,786 | 1,713 | 15.9% | 768 |
| RES | 4,034 | 722 | 17.9% | 332 |
| ECMA | 3,859 | 613 | 15.9% | 244 |
| JPE | 3,477 | 634 | 18.2% | 269 |
| QJE | 3,085 | 427 | 13.8% | 182 |

This is an **ORCID plus CV** layer for the combined database. The CV crawl has
parsed 438 documents into 1,895 events and 106 assignments; the queue is empty
and 777 sources failed or were unreachable. The separate AER database still reaches
21.4% because it also has byline rank (669 slots) and a fuller CV corpus.
New-journal authors have no byline rank data, so their coverage is lower and
remains visibly missing rather than imputed. Coverage rises from about 11% for
2000 papers to about 21% for 2026 papers, tracking the period ORCID records
describe best.

### M7.4 progress

The read-only API and frontend now expose the journal dimension:

- Paper payloads include `journal`; `/api/papers` and `/api/authors` accept a
  `journal=` filter; `/api/overview` reports per-journal papers, abstracts,
  author slots, career assignments, and career coverage.
- The papers page has a journal selector and journal badges; the overview has a
  per-journal breakdown; the author page shows the journal for every paper and a
  cross-journal career timeline; the app shell and methodology page are
  journal-aware.
- The combined database can be served with
  `python run.py serve --db data/curated/top5.db`, or by setting `ECONPUB_DB`.
- The network explorer supports a journal filter. When a journal is selected,
  edges are derived from that journal's papers, so a tie is a tie in that
  journal; the "All five" view uses the precomputed cross-journal edge table.
- The served database remains the AER baseline until the combined pilot passes
  the remaining validation and the CV queue is processed.

## Phases

### M7.1 — Multi-journal data foundation

1. Replace the single-journal constants with a journal registry (code, name,
   ISSN print/online, publisher, Crossref prefix, platform).
2. Harvest Crossref by ISSN for 2000–present, preserving raw source records.
3. Classify research articles, P&P/short papers, comments/replies, book
   reviews, editorials, and corrigenda **per journal**. Validate the classifier
   against a manually coded sample from each journal; publish the sample and
   the error rate.
4. Deduplicate across journals and against the existing AER corpus. Add a
   `journal_code` column and `(journal_code, published_year)` index.
5. Produce an M1-style audit for each new journal: record counts, date
   coverage, author-slot counts, abstract and affiliation coverage, and a
   list of classification edge cases.

Acceptance: each journal has a reproducible ingest, a documented article-type
rule set, and an audit report; no journal is silently mixed into AER totals.

### M7.2 — Identity and enrichment across journals

1. Run OpenAlex DOI-keyed enrichment for all journals (the layer is already
   journal-agnostic).
2. Re-run ORCID identity matching with the larger corpus. A new paper is
   additional evidence, so some previously unverified ORCID links may become
   verifiable — and some new false positives may appear. Re-run the rejection
   rules and report the change.
3. Reconcile author identities across journals: the same person must share one
   `stable_id`. Review cross-journal merges and splits with the existing ledger.
4. Rebuild the coauthorship graph with journal and year attributes on edges.

Acceptance: cross-journal stable IDs are reviewed; identity precision is not
worse than the AER-only layer; the network is queryable by journal and year.

### M7.3 — Career layer at the new scale

1. Extend ORCID/CV coverage to authors who appear only in the new journals.
2. Prioritize authors with many papers and low existing coverage; keep the
   current evidence hierarchy (byline > ORCID > historical web > CV > heuristic).
3. Use Common Crawl as the historical-page source where the Internet Archive
   is unreachable. Record it as its own provenance, not as Wayback.
4. Report career coverage **per journal and per year**, not only in aggregate.

Acceptance: coverage is measured and documented for every journal; missingness
remains explicit; no imputation is introduced to make the numbers look better.

### M7.4 — API and frontend

1. Add `journal` to paper, author, overview, and network responses.
2. Add journal filters to paper search, author lists, and the network explorer;
   keep "all journals" as an explicit option.
3. Show per-journal coverage in the overview and methodology pages.
4. Re-check pagination, query plans, and network bounds at roughly five times
   the current data volume.

Acceptance: no endpoint serializes the full database; every view states which
journals it covers.

### M7.5 — Validation and release

1. Per-journal spot checks of article types, authorship order, and dates.
2. Cross-journal identity spot checks, especially common names.
3. Regenerate all reports; version the release and keep the AER-only snapshot
   reproducible.
4. Update `docs/methodology.md`, `docs/data-sources.md`, and the README scope.

## Current status

| Phase | Status |
|---|---|
| M7.1 data foundation | Complete for all five journals; per-journal pilots and combined build done |
| M7.2 identity and enrichment | Complete; cross-journal reach validated, namesake splits preserved, OpenAlex missing-bylines recovered |
| M7.3 career layer | ORCID complete; CV crawl queue empty (438 parsed documents, 106 assignments; 777 failed sources remain visible) |
| M7.4 API and frontend | Complete, including journal-scoped networks; top-five database is the default when present |
| M7.5 validation and release | Random 12-per-journal article sample done; per-journal error rates, a public correction workflow, and the final deployment remain |

## Risks and controls

| Risk | Control |
|---|---|
| Article-type misclassification differs by journal | Manual sample per journal; publish error rates; keep ambiguous types out of research-article counts |
| Crossref metadata quality varies (abstracts, affiliations) | Report coverage by journal; use OpenAlex/ publisher pages only as documented supplements |
| Cross-journal author merges create false identities | Existing ledger and review queue; conservative merge rules; visible uncertainty |
| Scale makes the crawl and API slow | Resumable harvests, indexes, bounded pages, explicit truncation reporting |
| Coverage look better in aggregate but worse in a journal | Per-journal reporting; no pooled headline without the breakdown |
| Historical-web evidence is weaker than byline/ORCID | Keep the evidence hierarchy and confidence caps; never promote archive evidence above explicit sources |

## Explicit non-goals

- Full-text redistribution of any journal.
- Pre-2000 coverage in this phase.
- Treating the five journals as a ranking of all economics output.
- Auto-publishing unreviewed corrections or inferred career stages.
