# Corrections and takedowns

EconPub publishes inferred and source-derived records. A correction is a
first-class data change, not a silent edit.

## How to report

Use the repository's public **GitHub Issues** tracker and choose the
“Correction or takedown” template. Include:

- the DOI or stable author ID;
- the field that is wrong;
- the value you believe is correct;
- a public evidence URL (publisher page, Crossref record, ORCID record, CV, or
  institutional page);
- whether the request is a correction, an identity merge/split, or a takedown.

Do not send private documents. If a source is private, describe it and let the
maintainer decide whether it can be used.

## What happens next

1. **Acknowledge** the report and assign it a tracking issue.
2. **Verify** the claim against the named source and at least one independent
   source where one exists. Unsupported claims are not applied.
3. **Apply** the change through the pipeline or a documented manual repair.
   Preserve the old value in `source_records`, the identity ledger, or the
   report history; never overwrite it without an audit trail.
4. **Recompute** affected career assignments, coauthorship edges, network
   statistics, leaderboards, and reports.
5. **Record** the change, date, evidence, and reviewer in the release notes or
   correction log.
6. **Reply** to the reporter with the outcome. A rejected claim gets a short
   reason.

## Takedowns

For a privacy, safety, or legal takedown, remove the public field or record
promptly and preserve only the minimum audit note needed to prevent
reintroduction. Do not wait for the normal correction cycle. Do not republish
the removed material in a report.

## Scope

Corrections do not create a right to be omitted from bibliographic facts such as
authorship of a published article. They do apply to wrong identity links,
unsupported career-stage assignments, stale affiliations, and personal data that
should never have been collected.
