# Top-five pilot validation

This is a working validation log for the combined dataset. It records what was
checked against the source, what failed, and what remains unverified. It is not
a precision estimate.

## Ingest and article-type checks

Each journal was harvested from Crossref by print ISSN for 2000–present and
classified in its own pilot database before the combined build.

- **QJE** — 1,368 records, 1,181 research articles, 55 duplicate deposits. The
  duplicates are mostly MIT Press (`10.1162/...`) versus Oxford (`10.1093/qje/...`)
  deposits of the same article; title, year, volume, issue, and page range
  agree. Front matter includes editorial boards, tables of contents, covers,
  and referee lists. Crossref provides abstracts for about half the articles;
  OpenAlex raises coverage to 98.6%.
- **JPE** — 2,143 records, 1,500 research articles plus one explicit book review. The largest correction was
  editorial: 592 records are back-cover teasers, JPE turnaround-time tables,
  mastheads, indexes, and submission notices. "Back Cover" pages alone
  accounted for 166 records. Crossref has **no abstracts** for JPE; OpenAlex
  supplied 1,327.
- **RES** — 1,832 records, 1,748 research articles, 35 errata, 8 duplicates.
  Indexes, travel-fund notices, meeting announcements, and editorial
  announcements were moved to front matter. RES has almost no book-review
  deposits in Crossref.
- **ECMA** — 2,602 records, 1,740 research articles after remediation. The
  society's annual reports, editor reports, election/nomination notices,
  forthcoming-paper lists, news notes, and meeting programs were classified as
  association reports or front matter. Six "Supplement to ..." deposits are
  stored as `supplement`, not articles.

## Crossref metadata gaps

- **ECMA 2008–2014** deposits omit authors for 388 articles (DOI prefix
  `10.3982/ecta`). OpenAlex recovered 359 bylines (801 author slots). The
  remaining 30 stay `unattributed`; they are visible in the report rather than
  dropped.
- **AER** had 49 `unattributed` records before the combined build. OpenAlex
  recovered 12 AER bylines. A later administrative cleanup moved 11 AER society
  records out of the article count, so the combined AER figure is 4,787. The
  AER baseline reports still reflect the older number until the main database
  is refreshed.
- **JPE abstracts**: Crossref supplies none. This is a source limitation, not a
  parser failure; OpenAlex is required for JPE abstract coverage.

## Random article-type sample

A random sample of 12 research articles per journal was inspected by title and
year after the classifier was applied. All sampled items were research
contributions. One JPE item was an explicit reply ("Any Non-welfarist Method of
Policy Assessment Violates the Pareto Principle: Reply"), which the pipeline
keeps as a research article. The sample also surfaced one explicit JPE book
review; the classifier now stores titles beginning with "Book Review" as
`book_review`, not `article`.

Comments and replies are kept as research articles by design: AER has 6 titles
starting with "Comment", JPE 6 comments and 1 reply, and ECMA 12 comments and
13 replies. Whether to expose them as a separate type is a product decision,
not a silent reclassification. Unlabelled book reviews whose title is just the
book title remain a known gap.

## OpenAlex backfill correction (2026-10-26)

A review of the largest-team ranking exposed two ECMA papers whose Crossref
deposits had no authors and whose OpenAlex backfill was wrong:

- *Testing Models With Multiple Equilibria by Quantile Methods* (`10.3982/ecta6223`)
  was backfilled with 25 authors; the paper has two (Echenique and Komunjer).
- *Belief-Free Equilibria in Games With Incomplete Information*
  (`10.3982/ecta7134`) was backfilled with nine, including a literal
  "We Thank Pierpaolo Battigalli" entry; the paper has three (Hörner, Lovo,
  Tomala).

Both records were corrected in the combined database, their fictitious
coauthorship ties were removed, and the backfill path now rejects any OpenAlex
byline with more than 12 authors or an acknowledgement/editor-like name. The
largest-team leaderboard excludes papers whose byline came from OpenAlex
backfill. A fresh `top5` build applies the guard automatically.

## Identity checks

The combined build was resolved from scratch, then OpenAlex-supported merges
were applied. Known risks were checked explicitly:

- **Cross-journal reach.** 3,337 authors appear in at least two journals, 1,496
  in at least three, and 178 in all five. Daron Acemoglu has 82 papers across
  all five; John List has 50. This is consistent with their known records.
- **Namesake pairs.** The three AER splits survive the rebuild:
  - Benjamin I. Page (`A5089044770`) and Benjamin R. Page (`A5002652442`).
  - Daniel G. Sullivan (`A5060507064`) and Daniel M. Sullivan (`A5021617351`).
  - John W. Morgan (`A5037782885`, 2001) and John M. Morgan (`A5113551723`,
    2008–2012).
- **The Morgan bridge.** The first combined pass merged John W.'s 2001 paper
  into John M. because a 2009 byline without an OpenAlex ID connected the two
  sides transitively. The resolver now splits any component that contains both
  sides of a separation rule, anchors on the OpenAlex IDs, and assigns unlinked
  bylines by institution, name compatibility, and year proximity. Ambiguous
  bylines stay in a review component.
- **ORCID validation.** 5,988 identifiers were read; 4,075 reached an accepted
  tier (DOI, title, institution, or economics field), 1,439 remain unverified
  with events withheld, and 472 were rejected for name, field, or career risk.
  The top-five corpus gives ORCID validation more papers to compare against,
  but it also produces more same-name candidates; the rejection rules are
  unchanged.

## Career coverage

The combined pilot has ORCID plus a CV layer: 4,107 of 25,212 slots (16.3%)
receive a stage. Per journal: AER 15.9%, RES 17.9%, ECMA 16.0%, JPE 18.2%, QJE
13.8%. The CV crawl parsed 438 documents into 1,895 events and 106 assignments;
the queue is empty and 777 sources failed or were unreachable. The AER baseline
remains at 21.4% because it also has byline rank and a fuller CV corpus. New
journals have no byline rank field in Crossref, so their coverage is
structurally lower; no heuristic fills the gap.

## Still unverified

- A random, manually coded sample of article types for each journal, with a
  published error rate. The current checks are targeted, not random.
- Comments, replies, and short notes: these are kept as research articles.
  Whether to expose them as a separate type is a product decision that needs a
  per-journal count.
- Book reviews in JPE/RES/ECMA: Crossref deposits are sparse or absent, so the
  current corpus may undercount them. They should not be treated as research
  articles if they appear.
- Author identity across journals for common names beyond the three known
  pairs. The review queue and OpenAlex evidence are the controls; a manual
  sample of high-reach authors should be added before release.
- CV coverage for authors who appear only in the new journals. The CV crawl is
  resumable and seeded from ORCID researcher URLs.
- Historical-page evidence for the new journals. The Wayback pipeline exists
  but is not runnable from the current network; Common Crawl is the documented
  fallback.
