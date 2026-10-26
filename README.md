# EconPub

A public, methodologically documented database of publications in the top five economics journals — the *American Economic Review*, *Quarterly Journal of Economics*, *Journal of Political Economy*, *Review of Economic Studies*, and *Econometrica* — with a coauthor network and publish-time career-stage inference.

## Why this exists

Existing economics publication sites are strong on citation counts and journal rankings, but weak on two questions that matter for understanding how the field works:

1. **Who worked with whom, and how did those networks evolve?**
2. **What was each author's career stage when the paper was published?**

EconPub makes both first-class. Every inferred field carries its evidence and confidence, so the result is inspectable rather than a black box.

## Scope (v1.0)

- **Journals:** AER (0002-8282), QJE (0033-5533), JPE (0022-3808), RES (0034-6527), Econometrica (0012-9682)
- **Years:** 2000–present
- **Status:** The combined top-five dataset is built: 13,443 Crossref records classified and deduplicated by journal, OpenAlex DOI enrichment and missing-byline recovery, 10,042 active canonical authors, 19,728 distinct coauthor ties (24,108 author–paper edge records), ORCID and CV career validation, and journal-aware API/frontend views. The top-five database is the default served dataset; the AER-only reports remain as a historical baseline. Per-journal validation limits are documented rather than converted into a precision claim.
- **Not included:** pre-2000 archive, full text, or personal data such as birth dates, home addresses, phone numbers, and emails.
- **Plan:** `docs/roadmap.md` tracks the M7 phases, acceptance criteria, and risks.

## Architecture

The browser never downloads the database. A read-only FastAPI service exposes paginated paper and author views, bounded network subgraphs, shortest-path queries, and cached graph statistics; a React/Vite frontend consumes only those endpoints.

```
React (web/)  ->  FastAPI /api (src/econpub/api.py)  ->  SQLite mode=ro
```

The API caps page sizes and never serializes the full author table: the top-five dataset has 10,042 active authors, 19,728 distinct coauthor ties, and 24,108 author–paper edge records; the AER baseline has 5,892 authors and 8,238 distinct ties. Network views are explicit ranked samples, and the response reports what was truncated. See `docs/m5-frontend.md` for routes, endpoints, design tokens, and deployment notes.

## Top-five dataset (v1.0)

| Journal | Research articles | Author slots | Abstracts |
|---|---|---|---|
| AER | 4,787 | 10,786 | 4,305 |
| RES | 1,749 | 4,037 | 1,717 |
| ECMA | 1,740 | 3,820 | 1,621 |
| JPE | 1,500 | 3,477 | 1,329 |
| QJE | 1,181 | 3,085 | 1,164 |
| **Total** | **10,957** | **25,205** | **10,136** |

The combined dataset has 10,042 active canonical authors, 19,728 distinct coauthor ties, and 24,108 author–paper edge records. 3,336 authors appear in at least two journals, 1,497 in at least three, and 179 in all five. In the largest connected component (7,466 authors), the average shortest coauthorship path is 6.58 steps and the diameter is 18; journal-scoped averages range from 7.10 (QJE) to 10.74 (JPE). The overview shows the top five of seven leaderboards; a dedicated Leaderboards page exposes up to 100 rows for assistant-professor output, the five-journal club, most coauthors, strongest recurring pairs, largest teams, longest careers, and institutions. A connection finder returns shortest paths with paper evidence, and portals link to the network, methodology, and paper index. Career coverage is 4,961 assignments (19.7% of slots): 958 publish-time byline, 3,899 ORCID, and 104 CV assignments. The CV layer parsed 438 documents into 1,895 events; the queue is empty, and 777 sources failed or were unreachable and remain visible for audit. See `data/reports/top5_quality.md`, `data/reports/network_stats.md`, and `docs/roadmap.md`.

## AER baseline dataset (M4, historical)

| Metric | Value |
|---|---|
| Crossref records | 5,498 |
| Research articles (incl. P&P) | 4,786 |
| P&P articles (2000–2017) | 1,795 |
| Author slots | 10,782 |
| Canonical authors | 5,892 |
| Authors with stable IDs | 5,892 |
| Author aliases | 6,382 |
| Pending merge candidates | 0 |
| Resolved split candidates | 7 |
| Confirmed author splits | 3 |
| Multi-ID fragmentation reviewed | 32 authors |
| Multi-ID uncertain (flagged) | 5 authors |
| Authors flagged for review | 1,459 (905 unverified ORCID, 292 field-low, 249 rejected, 28 OpenAlex; overlaps) |
| Authors with OpenAlex ID | 5,526 |
| Authors with ORCID | 3,314 (56.2%) |
|   — accepted identity evidence | 2,409 |
|   — unverified (events withheld) | 905 |
|   — rejected identity | 249 |
| ORCID identities contributing events | 2,067 |
| ORCID career events | 5,847 (4,583 dated) |
| CV/homepage sources discovered | 1,362 |
| CV documents parsed | 268 |
| Coauthorship edges | 9,375 |
| Career assignments (all sources) | 2,305 (21.4% of slots) |
|   — byline | 669 |
|   — ORCID | 1,591 |
|   — CV | 45 |
|   — high/medium confidence | 1,381 |
|   — low confidence | 924 |
| Publish-time byline coverage | 99.8% |
| Resolved institution (OpenAlex) coverage | 94.5% |
| Any rank/title mention | 6.2% |
| Explicit academic rank coverage | 0.3% |
| Abstract coverage | 89.9% (boilerplate filtered) |
| OpenAlex work coverage | 98.9% |
| JEL coverage | 14.6% and rising (AEA crawl resumable) |
| Duplicate records excluded | 67 |
| Retraction notices / retracted originals | 2 / 2 |

The M2/M3/M4 reports are in `data/reports/m2_quality.md`, `m3_quality.md`, and `m4_quality.md`; the M6 coverage report is `data/reports/m6_coverage.md`; the combined top-five report is `data/reports/top5_quality.md`. The M1 independent audit and its full evidence are in `docs/audit-m1.md` and `docs/audit-m1-findings.json`. The API and frontend are documented in `docs/m5-frontend.md`; coverage engineering is in `docs/m6-coverage.md`; the top-five expansion plan is in `docs/roadmap.md`.

Three findings shape the next milestones:

1. **ORCID is the highest-yield career source, but only after identity validation.** 3,314 authors retain an ORCID; 2,409 have direct evidence (matching AER DOI/title or institution) or a conservative economics-field signal, and 905 are unverified links whose events are withheld. 2,067 accepted identities contribute 5,847 events and raise career coverage from 6.2% (byline only) to 21.4% (2,305 assignments). Generic "Professor" titles are stored as full professor with **low confidence** because the title may be current rather than the rank at the paper date; explicit ranks are high confidence.
2. **Stable identity needs explicit reconciliation.** The 40 multi-OpenAlex-ID authors were reviewed: 3 were confirmed resolver over-merges and split (John W./M. Morgan, Benjamin I./R. Page, Daniel G./M. Sullivan), 32 are OpenAlex duplicate profiles, and 5 remain uncertain. 28 authors carry OpenAlex fragmentation flags. ORCID identity validation rejects 72 person-name conflicts, 165 clear field mismatches, and 12 career-changing links without positive evidence.
3. **CVs are the next coverage frontier.** ORCID researcher URLs and discovered CV links yielded 1,362 public sources. The crawl parsed 268 documents, extracted 1,129 dated events, and produced 45 CV assignments. The queue is empty; 370 homepages and 72 CV documents remain unreachable. The corpus is larger but still not complete.

## Data sources

| Source | Role |
|---|---|
| Crossref REST API | Primary article metadata for all five journals and publish-time affiliation strings |
| AEA article pages | AER-only JEL classification, abstracts, and publication details |
| OpenAlex | DOI-keyed enrichment: author IDs, citation counts, topics, institutions, and missing-byline recovery |
| ORCID | Self-reported employment and education timelines, used only after identity validation |
| Author CVs and faculty pages | Education and employment timelines where byline/ORCID evidence is absent |

OpenAlex is never used as the primary record. Its author affiliation history mixes in coauthor institutions, and its historical publication years contain known errors. See `docs/data-sources.md` for the reconnaissance evidence.

## Quick start

Install the package and its API/CV extras first:

```powershell
pip install -e ".[api]"
```

The product itself is the combined top-five database; the commands below build
the AER baseline first, then the combined dataset. A fresh clone can run the
top-five build directly (see “Build the combined top-five database”).

```powershell
python run.py all
```

This creates:

- `data/curated/econpub.db` — SQLite database
- `data/raw/crossref/pages/` — verbatim API pages for auditing and resume
- `data/reports/m1_quality.md` and `m1_quality.json` — M1 coverage and quality report

After the M1 pipeline, run the enrichment pass:

```powershell
python run.py m2 --workers 1 --delay 1.0
```

This fixes issue months, crawls AEA article pages for JEL/abstracts, enriches with OpenAlex, links authors, and writes `data/reports/m2_quality.md`.

Then run the identity and career passes:

```powershell
python run.py m3
python run.py m4
```

M3 assigns stable author IDs, resolves the seven namesake candidates, reviews the 40 authors with multiple OpenAlex IDs (splitting three confirmed over-merges), writes permanent separation rules, and produces byline career assignments. M4 adds ORCID employment/education timelines, validates each ORCID link against AER evidence before using its events, and infers career stages at publication. The reports are `data/reports/m3_quality.md` and `data/reports/m4_quality.md`.

The CV layer is a separate, resumable crawl:

```powershell
python run.py cvs --limit 300
```

It seeds from ORCID researcher URLs, discovers CV links, stores raw documents only in the local ignored cache, extracts dated events, and uses them only where byline/ORCID evidence is absent. PDF text uses the optional system `pdftotext -layout` when available and falls back to the declared `pypdf` dependency.

### Build the combined top-five database

The combined build is separate from the AER baseline so the validated reports are
not overwritten while the new journals are checked:

```powershell
python run.py top5 --db data/curated/top5.db --cv
```

The `top5` command harvests all five journals, classifies and deduplicates by
journal, rebuilds canonical authors, enriches with OpenAlex (including missing-
byline recovery), validates ORCID links, assigns byline and ORCID career stages,
optionally runs the CV crawl (`--cv`), computes the cached network statistics,
and writes `data/reports/top5_quality.md` and `.json`. The pipeline is
resumable: Crossref pages and OpenAlex/ORCID payloads are cached under
`data/raw/`. The CV crawl is the slowest stage and can take hours; omit `--cv`
to build the bibliographic and ORCID layers first. Use `--skip-network-stats`
to skip the exact all-pairs statistics. Because career events are author-keyed,
a database that already has them refuses a harvest/OpenAlex refresh; rebuild
from a fresh database, or pass `--skip-harvest --skip-openalex` to refresh only
the career/report layers.

### Run the public interface

The frontend and API are separate processes. Install the API extra once:

```powershell
pip install -e ".[api]"
```

In one terminal:

```powershell
python run.py serve --port 8000 --db data/curated/top5.db
```

Without `--db`, the API serves `data/curated/top5.db` when it exists and falls back to the AER baseline (`data/curated/econpub.db`). Set `ECONPUB_DB` explicitly in deployment.

In another:

```powershell
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the FastAPI service. For a separated deployment, set `VITE_API_BASE` at frontend build time and `ECONPUB_CORS_ORIGINS` on the API; see `docs/m5-frontend.md`.

Useful commands:

```powershell
python run.py harvest --resume   # reuse cached Crossref pages
python run.py harvest --refresh  # re-fetch with the current field selection
python run.py aea --workers 1 --delay 1.0   # resume the cached AEA crawl
python run.py openalex          # reuse cached OpenAlex batches
python run.py pages             # expand abbreviated page ranges
python run.py calendar          # apply the AEA issue-month calendar
python run.py m3                # rebuild identity review and byline careers
python run.py m4                # fetch ORCID timelines, validate identities, assign careers
python run.py m4 --skip-orcid   # revalidate cached ORCID links without network
python run.py cvs --limit 300   # expand CV discovery/parsing
python run.py cvs --workers 5 --skip-seed   # resume the cached CV crawl
python run.py wayback --limit 100           # historical faculty-page snapshots
python run.py top5-report --db data/curated/top5.db      # per-journal quality report
python run.py network-stats --db data/curated/top5.db     # cached path-length/diameter statistics
python run.py privacy --db data/curated/top5.db           # scrub personal data from legacy rows
python run.py release-manifest --db data/curated/top5.db  # checksums and counts for a release
python run.py serve             # run the read-only JSON API on port 8000
python run.py report            # regenerate the report without rebuilding authors
python -m unittest discover -s tests -v
```

The pure unit tests run on a fresh clone. The API integration tests require a
curated database and skip when `data/curated/econpub.db` or `top5.db` is absent;
`tests/test_top5.py` exercises the combined dataset when it is available. The
release manifest records the exact database bytes used for a release.

`report` is read-only with respect to the author layer. Rebuilding authors is done by `harvest`/`all`; stable IDs and separation rules survive, but rerun `m2`/`m3` to refresh OpenAlex links and review labels.

Set a contact address for Crossref's polite pool:

```powershell
$env:ECONPUB_MAILTO="you@example.com"
```

## Project layout

```
src/econpub/
  config.py        paths, journal constants, API settings
  normalize.py     text/date/name/rank/page normalization
  db.py            SQLite schema and upserts
  crossref.py      paginated Crossref harvest
  classify.py      content types, P&P, retractions, deduplication
  authors.py       canonical author resolution and coauthorship edges
  aea.py           AEA article-page crawl: JEL, abstracts, issue months
  openalex.py      DOI-keyed OpenAlex work/author/institution enrichment
  identity.py      stable author IDs, ledger, and identity events
  review.py        merge-candidate resolution, multi-ID review, author splits
  career.py        byline, ORCID, and CV career-stage assignments
  orcid.py         ORCID record harvest and employment/education events
  cv.py            CV/homepage discovery, caching, and conservative CV parsing
  wayback.py       Wayback CDX snapshots and historical rank extraction
  pages.py         abbreviated page-range expansion and validation
  quality.py       coverage, provenance, and M2-M4 reports
  coverage.py      M6 CV and historical-page coverage report
  top5_build.py    combined top-five harvest, identity, ORCID, and report pipeline
  top5_report.py   per-journal inventory, coverage, identity, and missingness report
  network_report.py exact coauthor-network statistics and cached report
  privacy.py       personal-data scrub for career events and affiliations
  release.py       release manifest, checksums, and reproducibility metadata
  api.py           read-only FastAPI service for the public frontend
  cli.py           command-line entry point
  schema.sql       database schema
web/
  src/             React routes, components, charts, network explorer, connection finder
  public/          static assets
  scripts/         build helpers (SPA 404 fallback)
docs/
  methodology.md   public methodology and inference rules
  data-sources.md  source reconnaissance and known limitations
  m4-validation.md  concrete ORCID/CV spot checks and parser fixes
  m5-frontend.md   API surface, frontend routes, design system, deployment
  m6-coverage.md   CV crawl, Wayback historical pages, coverage policy
  roadmap.md       top-five expansion phases, acceptance criteria, and risks
  top5-validation.md  per-journal ingest, identity, and coverage checks
  corrections.md   correction and takedown workflow
  release.md       v1.0 release checklist, manifest, and open gates
  audit-m1.md      independent multi-agent audit and remediation status
tests/
  test_normalize.py
  test_classify.py
  test_m2.py
  test_m3.py
  test_m4.py
  test_api.py
  test_m7.py      journal registry, multi-journal ingest, classification, report
```

## Data model

The core tables are `papers`, `authorships`, `authors`, `author_aliases`, `author_merge_candidates`, `author_openalex_evidence`, `author_split_candidates`, `author_identity_ledger`, `author_identity_events`, `author_separation_rules`, `institutions`, `authorship_institutions`, `paper_topics`, and `source_records`. `coauthorship_edges` is built from canonical authorships. `career_events` stores dated education/employment facts from ORCID and CVs; `career_assignments` stores the inferred stage at each publication with evidence type, confidence, and source URL. `author_cv_sources` records public CV/homepage provenance; raw documents are kept only in the ignored local cache.

`papers.journal_code` identifies the journal; `papers.content_type` separates research articles from front matter, issue metadata, unattributed records, errata, society reports, supplements, retraction notices, and duplicates. Duplicate detection is scoped by journal. Only research articles feed the publication and network statistics; P&P articles are research articles with `is_pp = 1`. Retracted originals stay in `article` with a `retraction_status` flag and a pointer to the notice. Crossref `update-to` is the primary retraction link, with an explicit fallback pair list.

Author resolution is rebuildable: `authors.py` groups authorships by a middle-initial-, particle-, and Unicode-aware key, merges safe variants, splits known namesakes, and writes uncertain pairs to `author_merge_candidates`. `openalex.py` attaches OpenAlex author IDs, records every observed ID in `author_openalex_evidence`, and merges only pairs that OpenAlex says are the same person and whose names are compatible.

`papers.abstract_source` and `papers.date_source` record provenance. `paper_topics` uses separate schemes for author-assigned JEL codes and machine-generated OpenAlex topics. `institutions` and `authorship_institutions` store resolved entities and multiple publish-time affiliations per authorship.

`career_assignments` is the key table for the project's distinctive claim: each row records a publish-time stage, the evidence type, a confidence level, and a source URL. `authors.orcid_source` records the identity tier (`verified_doi`, `verified_title`, `verified_institution`, `field_economics`, `orcid_unverified`) or rejection reason; only accepted tiers contribute ORCID events.

`api.py` opens the database read-only and serves bounded JSON views. The React frontend never receives raw tables; paper and author indexes are paginated, and network views are ranked subgraphs with explicit truncation metadata.

## Roadmap

- **M1** — schema, Crossref harvest, content classification, deduplication, canonical authors, quality report ✅
- **M2** — AEA JEL/abstract enrichment; OpenAlex DOI-keyed enrichment, author IDs, institutions, topics; fix 2002–2009 issue-month mapping; page-range validation ✅
- **M3** — stable author IDs and identity ledger; resolve the 7 merge candidates and 40 multi-OpenAlex-ID authors; split confirmed over-merges; byline-only career assignments ✅
- **M4** — ORCID employment/education timelines; conservative CV discovery and parsing; career assignments with evidence and confidence ✅ (CV corpus remains resumable)
- **M5** — read-only FastAPI service and React frontend: paper pages, author pages, career timelines, coauthor network explorer, methodology page, and a bounded network API ✅ (deployment remains)
- **M6** — coverage engineering: resumable CV crawl with caching/threading (268 documents parsed, 1,129 events), historical Wayback faculty-page pipeline, and evidence tests ✅ (Internet Archive was unreachable from the development network; the pipeline must be run where archive.org is accessible)
- **M7** — top-five expansion: journal registry, journal-scoped Crossref ingest and deduplication, OpenAlex missing-byline recovery, cross-journal identity reconciliation, ORCID career layer, journal-aware API/frontend, and a per-journal quality report 🚧 (pilot complete; per-journal validation, CV coverage, and the served-database switch remain)

## Data ethics

- Only bibliographic metadata and short excerpts are stored; no full text.
- CV-derived data is limited to structured degree/employment facts with a source URL.
- Missing data is shown as missing, not silently imputed.
- Corrections and takedowns follow `docs/corrections.md`; a public intake channel must be configured at deployment.

## License

- **Code:** MIT; see `LICENSE`.
- **Database compilation:** CC BY 4.0; see `DATA_LICENSE.md`.
- **Third-party material:** Crossref/OpenAlex/ORCID metadata, publisher
  abstracts, titles, and author names remain subject to their source terms and
  are not relicensed by EconPub. No full text is redistributed.
