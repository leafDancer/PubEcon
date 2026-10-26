# M6 coverage engineering

M6 is about raising the career-stage coverage without weakening the evidence standard. The article corpus is already the stable base; the missing layer is dated, rank-specific evidence for each author at each paper date.

## Priorities

1. **Finish the CV/homepage crawl.** ORCID researcher URLs seed public CVs and faculty pages. The crawl is resumable and cached locally.
2. **Use historical faculty pages.** A current “Professor” page is weak evidence for a 2005 paper. Wayback snapshots near the paper year can show the rank that was current at the time.
3. **Prefer precision over coverage.** A new assignment is accepted only when the evidence covers the paper year and the identity passes the existing checks. Unknown remains visible.

## CV pipeline changes

The CV crawl now has:

- **Homepage caching** under `data/raw/cvs/homepages/`, with a metadata sidecar recording content type and final URL.
- **Threaded discovery** (`--workers`) with per-thread HTTP clients and shorter retries. Permanent 403/404 responses are not retried.
- **Resume controls**: `--skip-seed`, `--skip-discover`, `--skip-fetch`, `--skip-parse`, `--skip-careers`, `--refresh`, and `--retry-failed`.
- **Progress logging** every 25 pages/documents.
- The existing conservative section-based parser and name check remain in place. A CV is not used if it does not look like the author’s document.

Commands:

```powershell
python run.py cvs --limit 900 --workers 5 --skip-seed
python run.py cvs --retry-failed --skip-seed --skip-fetch --skip-parse --skip-careers
python run.py cvs --skip-seed --skip-discover --skip-fetch --skip-parse
```

## Wayback historical pages

The new `wayback` command uses the Internet Archive CDX API:

1. For authors with low career coverage and at least one ORCID researcher URL, query snapshots around up to `--max-years` AER publication years.
2. Store candidate snapshots in `author_wayback_snapshots`.
3. Fetch the archived HTML and cache it under `data/raw/wayback/`.
4. Find an academic rank phrase near the author’s family name.
5. Write a `source_type='wayback'` career event for that paper year, using the paper’s byline institution.
6. Assign `wayback_employment` after ORCID and before CV; Wayback confidence is capped at medium.

The parser deliberately ignores non-academic titles and does not infer a rank from a page with no mention of the author. A snapshot with no institution is recorded but does not produce an assignment.

```powershell
python run.py wayback --limit 100 --max-years 3 --workers 3
python run.py wayback --skip-collect --skip-fetch --skip-parse
```

### Network caveat

The current development environment cannot reach `web.archive.org` (connections time out). The Wayback pipeline is implemented and covered by parser/snapshot-selection tests, but it has not been run against the live archive here. Run it from a network that can reach the Internet Archive before treating it as a coverage source.

### Common Crawl fallback

Common Crawl is reachable from this environment and was tested as an alternative
historical-page source. The index (`index.commoncrawl.org`) and the WARC range
endpoint (`data.commoncrawl.org`) both respond, and a captured HTML page can be
recovered with a byte-range request, decompressed, and passed to the same
rank parser.

It is not enabled as a coverage source yet:

- The index endpoint returned HTTP 502/504 on a large share of requests, so a
  full author sweep needs long backoff, a response cache, and a single worker.
- Exact-URL captures are sparse for personal faculty pages; several sampled
  homepages had no capture in the crawl nearest the paper year.
- Some captures are redirects (HTTP 301) or empty shells, so only `200`
  `text/html` records with a meaningful body are usable.

The tested flow is documented here so a future run does not have to rediscover
it: choose the crawl nearest the paper year from `collinfo.json`, query the
exact URL with `filter=status:200` and `filter=mime:text/html`, read
`filename`/`offset`/`length`, fetch that byte range from
`data.commoncrawl.org`, gunzip the WARC record, split on the first two
`\r\n\r\n` boundaries, and parse the third part as the HTTP body. Record
Common Crawl captures under their own provenance; do not label them Wayback.

## Current run (2026-10-25)

- **1,362** CV/homepage sources are tracked (ORCID researcher URLs plus discovered CV links).
- **633** homepages were parsed for CV links; **294** documents were downloaded; **268** were parsed.
- **203** documents produced at least one event; the other 65 were parsed with zero events.
- **1,129** CV career events and **45** CV career assignments were extracted across **187** authors.
- The CV queue is empty; **19** were rejected as name mismatches; **370** homepages and **72** CV documents were unreachable.
- Total career assignments are **2,305 of 10,782 article slots (21.4%)**: 669 byline, 1,591 ORCID, and 45 CV.
- The crawler now handles `Asst.`/`Assoc.` abbreviations, colon-terminated section headers, `EARNED DEGREES`, short end years such as `2015-22`, month/year ranges such as `05/2014-07/2017`, HTML masquerading as PDF, and institution names such as `University of St Gallen`.
- Wayback snapshots are **0** in this run because the development network cannot reach `web.archive.org`.

## Coverage accounting

CV sources have five states:

| State | Meaning |
|---|---|
| `candidate` | Discovered homepage or CV link, not yet processed |
| `homepage_fetched` | Homepage parsed for CV-like links |
| `fetched` | Document downloaded and text extracted |
| `parsed` | Text parsed; may contain zero events |
| `name_mismatch` / `failed` | Rejected or unavailable; retained for audit |

Wayback snapshots are tracked separately in `author_wayback_snapshots` with `candidate`, `fetched`, `empty`, `failed`, and `parsed` states.

## Next coverage levers

- RePEc/IDEAS author pages and CV links.
- Common Crawl or another historical-web index where the Internet Archive is unreachable.
- Manual review of high-impact authors and borderline identity cases.
- A public correction workflow: source URL, reviewer, and revision history; never auto-publish an unverified edit.
