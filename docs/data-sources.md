# Data source reconnaissance

This note records what was actually observed while scoping the project. It is a decision record, not a vendor description.

## Scope decision

The project's validated baseline is **AER 2000–present**; the combined top-five
pilot adds **QJE, JPE, RES, and Econometrica** for the same window. The 2000+
start deliberately excludes the 1911–1999 archive, which has no AEA DOI deposits
and would require JSTOR/RePEc reconstruction. The 2000+ window is where Crossref,
AEA, OpenAlex, and author CVs all have usable coverage.

## Crossref

- Journal endpoints: `https://api.crossref.org/journals/<ISSN>/works` for each
  of the five print ISSNs. The 2000+ filter returned these record counts
  (observed 2026-10): AER **5,498**, QJE **1,368**, JPE **2,143**, RES
  **1,832**, Econometrica **2,602** — **13,443** in total.
- Cursor pagination works with `cursor=*`; `rows=1000` is accepted. A full harvest is roughly six page requests.
- Author records include `given`, `family`, `sequence`, and `affiliation` entries. AEA deposits frequently include publish-time affiliations, often with rank words:

  > `Assistant Professor of Economics, Princeton University (email: )`

- Abstracts are present for many research articles. Subject fields are not consistently populated; JEL codes come from AEA pages instead.
- Crossref rate limits can return HTTP 429 under bursts. The harvester uses a contact address, sequential requests, and exponential backoff, and caches every raw page.

## AEA website (AER only)

These sources apply only to the *American Economic Review*; the other four
journals do not use the AEA platform.

- Article pages are addressable by DOI: `https://www.aeaweb.org/articles?id=<DOI>`.
- The all-issues page `https://www.aeaweb.org/journals/aer/issues` lists every volume and issue with its cover month, including combined issues such as "April 2018 (Vol. 108, No. 4-5)". This is the source of record for issue months.
- Each article page exposes machine-readable `citation_*` meta tags: `citation_publication_date` (`YYYY/MM`), `citation_volume`, `citation_issue`, `citation_firstpage`, `citation_lastpage`, `citation_author`, and `citation_author_institution`. These confirm the issue month and supply volume/issue/pages.
- The page also contains a `JEL Classification` block with codes and official descriptions, and an `Abstract` section. Both are parsed and stored with provenance.
- The 2001 Acemoglu–Johnson–Robinson page was fetched successfully and exposes authors, abstract, JEL classification, volume/issue/pages, and citation text.
- The AEA `robots.txt` disallows GPTBot and Amazonbot; the site is otherwise reachable. The site is proxy-sensitive and occasionally returns a read timeout before succeeding on retry. The crawler uses a browser user agent, a persistent client, a small worker pool, rate limiting, retries, and a per-DOI HTML cache so it can resume without refetching.
- Only metadata and short excerpts are stored; full article text is not redistributed.

## OpenAlex

- AER source: `S23254222`; reported `works_count` is 10,014.
- **Year distribution is not trustworthy for historical work.** Pre-1969 records are nearly absent; a large block of 1960s–1990s articles is mislabelled as 2016 (1,032 AER records in 2016 vs roughly 280 in neighbouring years). An example is a 1994 article with `biblio.volume = 84` and `publication_year = 2016`, landing on Dialnet.
- DOI matching works for 4,735 of 4,786 AER research articles (98.9%). The 51 misses are concentrated in 2006–2007 and in the newest 2026 issue.
- OpenAlex `publication_date` inherits the same one-month-early shift as Crossref for 2002–2009. It is stored for comparison but never used to correct issue months.
- OpenAlex abstracts are useful (1,210 records filled), but some are actually AEA page descriptions ("Title by Authors. Published in volume ... of American Economic Review"). 377 were filtered as boilerplate, leaving 833 usable abstracts.
- OpenAlex topics are stored under `scheme='openalex_topic'` and are not treated as equivalent to JEL codes.
- Author profiles carry useful ORCIDs and citation counts, but `affiliations` is noisy: Markus Brunnermeier's profile lists dozens of institutions that are clearly coauthor affiliations, not his employment history.
- OpenAlex work authorship supplies author IDs and publish-time institution IDs. 5,526 of 5,892 canonical authors receive an OpenAlex link; 40 authors had more than one OpenAlex ID and were reviewed in M3 (3 splits, 32 duplicate-profile cases, 5 uncertain).
- **Missing-byline backfill.** When a publisher deposit has no authors at all, OpenAlex work authorship may supply the byline. Created rows carry `openalex_match_method='openalex_backfill'`, `openalex_author_name`, the raw affiliation, and `institution_source='openalex'`. Crossref authors are never replaced when present. In the top-five pilot this recovered 359 of 388 Econometrica articles from 2008–2014 whose Crossref deposits omit authors; the remaining 29 stay `unattributed`.
- **Decision:** use OpenAlex only as DOI-keyed enrichment, never as the primary paper record or as a career timeline.

## ORCID

- ORCID public records (`https://pub.orcid.org/v3.0/<id>/record`) provide self-reported employment and education with start/end dates, organization names, role titles, and degree names.
- 3,314 of 5,892 canonical authors retain an ORCID after validation, largely obtained from OpenAlex work authorship (the Crossref deposit itself supplies only one ORCID).
- Unlike OpenAlex author profiles, ORCID records are self-reported and therefore useful for a dated timeline. But an ORCID link is only as good as the identity match: common names and OpenAlex profile merging produce wrong links (e.g. an economist matched to a surgeon's ORCID).
- Identity is validated before events are used. A matching AER DOI (1,397 authors) or a matching work title (181) is high confidence; an overlap with an AER byline institution (539) is medium confidence; an economics-department or core-economics-journal signal with no direct AER link (292) is low confidence.
- Records with no positive identity evidence but no contradiction (905) are retained as low-confidence identity links; their employment/education events are withheld. Records whose person name conflicts (72), whose field is clearly non-economics (165), or whose events would change a career stage without positive identity evidence (12) are rejected.
- 2,067 accepted ORCID identities contribute 5,847 employment/education events, of which 4,583 have a start year.
- ORCID data is not complete or uniformly dated. Many records list a current title with an old start year; generic "Professor" is therefore treated as full professor with low confidence.

## CVs and faculty pages

- ORCID researcher URLs and discovered CV links provide 1,362 public sources. 633 homepages were parsed for links, 294 documents were downloaded, and 268 documents were parsed.
- The CV layer is deliberately conservative: it follows public links, stores raw documents only in the ignored local cache, and extracts only Education/Employment sections with years and titles.
- The crawl extracted 1,129 dated CV events and 45 career assignments. CV events are used only after byline, ORCID, and Wayback evidence are absent. The queue is empty; 370 homepages and 72 CV documents remain unreachable.
- The full CV crawl is resumable; it is not presented as complete coverage.

## Wayback Machine

- Historical faculty and personal pages are retrieved through the Internet Archive CDX API. A snapshot near the AER paper year can show the rank that was current at the time, which current ORCID records and faculty pages cannot.
- Candidate snapshots are tied to a paper year and stored in `author_wayback_snapshots`; raw HTML and extracted text stay in the ignored local cache.
- The parser looks for an academic rank phrase near the author's family name and uses the paper's byline institution. It ignores non-academic titles and never assigns from a page that does not mention the author.
- `wayback_employment` sits between ORCID and CV in the evidence hierarchy and is capped at medium confidence.
- The current development network cannot reach `web.archive.org` (connections time out), so the pipeline has been tested with synthetic snapshots but not run against the live archive. Run it from a network with Internet Archive access before treating it as a coverage source.

## RePEc / IDEAS

- Journal page: `https://ideas.repec.org/s/aea/aecrev.html`; `robots.txt` allows crawling except `/cgi-bin/`.
- The journal page is paginated (`aecrev2.html`, …, `aecrev55.html`), so full-history issue lists are available if the scope ever expands.
- Not needed for the 2000+ MVP because Crossref provides the article list.

## Retractions

- Crossref `update-to` identifies both AER retraction pairs: `10.1257/000282802762024656` ← `10.1257/aer.97.3.1032`, and `10.1257/aer.20210369` ← `10.1257/aer.113.7.2053`. The pipeline uses this relation first and keeps the explicit pairs only as a fallback.

## Career data

No bibliographic source contains publish-time career stage. The evidence hierarchy is:

1. Publish-time byline rank (Crossref affiliation string; highest precision in recent years).
2. ORCID education/employment timeline, after identity validation.
3. CV education/employment timeline (degree years, position titles, start/end years).
4. Heuristics from PhD year and first publication (low confidence, used sparingly).
5. `unknown` (displayed as missing).

Career facts will be stored as structured rows with source URLs. Personal data such as birth dates, home addresses, and email addresses is out of scope.

## Known limitations

- Author resolution is name-based, supplemented by OpenAlex evidence. The resolver handles middle initials, surname particles, Unicode transliteration, suffixes, and known namesakes. M3 introduced stable IDs and explicit review: 5,892 canonical authors, 7 resolved namesake candidates, 3 confirmed splits, 32 OpenAlex profile-duplication cases, and 5 uncertain multi-ID authors. 28 OpenAlex fragmentation flags remain. This is not a substitute for CV evidence.
- Stable author IDs live in `author_identity_ledger`; `authors.author_id` remains an internal key and can change on rebuild. Confirmed splits are protected by `author_separation_rules`.
- Affiliation strings are inconsistent, and explicit academic rank is present on only about 0.3% of author slots. OpenAlex resolves publish-time institutions for 10,188 of 10,782 slots (94.5%); combined with the Crossref byline hint, 10,602 slots (98.3%) have some institution string.
- Career assignments cover 2,305 of 10,782 slots (21.4%): 669 byline, 1,591 ORCID, and 45 CV. 8,477 slots remain unknown. 909 of the 965 full-professor assignments rely on generic "Professor" titles and are low confidence.
- ORCID review remains substantial: 905 identities are unverified (events withheld), 292 are low-confidence economics-field matches, 72 have person-name conflicts, 165 have clear field mismatches, and 12 would change a career stage without positive identity evidence. The CV corpus has 268 parsed documents but is not a complete corpus.
- P&P articles are identified as the largest spring issue (April/May, at least 50 articles) in each year through 2017. The issue number is not stable: it is 2 in 2000–2010, 3 in 2011–2013, and 5 in 2014–2017. AEA issue metadata is used for verification where available.
- AER's publication schedule and issue numbering changed over time; year-level analysis is safer than issue-level analysis.
- Crossref coverage of front matter and non-research items varies. AER P&P issues also contain AEA committee reports, minutes, and Job Openings reports; these are classified as `association_report` and excluded from research-article statistics.
- Crossref contains duplicate AER deposits: 51 legacy/modern DOI pairs in 2006 issue 4 and 2007 issue 1, plus research-article, erratum, and P&P front-matter pairs. Normalised matching identifies 67 duplicate rows; the modern DOI is canonical where possible.
- Crossref publication months were one month earlier than the AEA issue cover month for 2002–2009. Every article month now comes from the AEA all-issues calendar or an AEA article page (currently 4,086 and 700 respectively); no article relies on the Crossref fallback. Day-level precision is dropped when the month is replaced; the raw Crossref date remains in `source_records`.
- Crossref provides no subject/JEL fields for AER records. JEL codes are ingested from AEA article pages and stored under `scheme='jel'`; OpenAlex topics are a separate scheme. AEA rate-limits bulk crawling, so JEL coverage is partial and the crawler is resumable from its HTML cache; OpenAlex topics cover 98.9% of articles independently.
- Institution hints are now entity-resolved against OpenAlex for 94.5% of slots, but 180 slots still lack any hint, and Crossref byline fragments (e.g. "and Development Studies Institute") remain in the raw `institution_hint` field.
- OpenAlex does not index 51 AER articles (mostly 2006–2007 and the newest 2026 issue). Their Crossref metadata remains complete, but they lack OpenAlex topics, author IDs, and institution entities.
- OpenAlex citation counts are stored separately from Crossref counts and are not reconciled. They are as-reported and can be inflated by duplicate works or citation-matching errors; the frontend labels the source.
- One reversed numeric page range remains (`10.1257/aer.20181830`); it is flagged by the page validator and will be corrected against the AEA page.
