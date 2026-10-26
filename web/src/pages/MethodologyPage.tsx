import { Link } from 'react-router-dom'
import { api } from '../api'
import { formatNumber, formatPct, useApi } from '../lib'

const STAGES = [
  ['phd_student', 'Enrolled in a doctoral programme, including candidates'],
  ['postdoc', 'Postdoctoral position'],
  ['assistant_professor', 'Assistant professor or equivalent entry-level tenure-track rank'],
  ['associate_professor', 'Associate professor'],
  ['full_professor', 'Full professor'],
  ['emeritus', 'Emeritus or emerita'],
  ['lecturer_other_academic', 'Lecturer, reader, instructor, or similar teaching-track rank'],
  ['research_fellow', 'Named research fellow or research scientist'],
  ['non_academic', 'Central bank, government, international organisation, industry, consulting'],
  ['unknown', 'Insufficient evidence; shown as missing'],
]

export default function MethodologyPage() {
  const { data } = useApi(() => api.overview(), [])
  return (
    <div className="ep-page ep-methodology">
      <header className="ep-page-head is-narrow">
        <p className="ep-kicker">Method and limits</p>
        <h1>How the record is built</h1>
        <p className="ep-page-deck">
          EconPub is a public, evidence-first database. Every inferred field carries its source and
          confidence. Missing evidence is displayed as missing, never filled silently.
        </p>
      </header>

      <div className="ep-method-layout">
        <aside className="ep-method-toc">
          <p>On this page</p>
          <a href="#scope">Scope</a>
          <a href="#stages">Career stages</a>
          <a href="#evidence">Evidence hierarchy</a>
          <a href="#orcid">ORCID identity</a>
          <a href="#identity">Stable identity</a>
          <a href="#dates">Dates and topics</a>
          <a href="#limits">Limits</a>
        </aside>

        <div className="ep-prose ep-method-body">
          <section id="scope">
            <h2>Scope</h2>
            <p>
              The record covers the top five economics journals — the <em>American Economic
              Review</em>, <em>Quarterly Journal of Economics</em>, <em>Journal of Political
              Economy</em>, <em>Review of Economic Studies</em>, and <em>Econometrica</em> — from
              2000 onward. AER includes its Papers &amp; Proceedings through 2017. The record does
              not include the pre-2000 archive, full text, or personal data such as birth dates,
              home addresses, or email addresses.
            </p>
            <div className="ep-method-stats">
              <span>
                <strong>{data ? formatNumber(data.counts.papers) : '—'}</strong> research articles
              </span>
              <span>
                <strong>{data ? formatNumber(data.counts.authors) : '—'}</strong> canonical authors
              </span>
              <span>
                <strong>{data ? formatNumber(data.counts.career_assignments) : '—'}</strong> career
                stages
              </span>
            </div>
          </section>

          <section id="stages">
            <h2>Career stages</h2>
            <p>
              The unit is one author at one paper&apos;s publication date. A career stage is stored
              only when a dated event covers that year or the byline states a rank. The taxonomy is
              deliberately close to observed evidence; “tenured” is not treated as observed.
            </p>
            <div className="ep-table-wrap">
              <table className="ep-table">
                <thead>
                  <tr>
                    <th scope="col">Stage</th>
                    <th scope="col">Definition</th>
                  </tr>
                </thead>
                <tbody>
                  {STAGES.map(([stage, definition]) => (
                    <tr key={stage}>
                      <td>
                        <code>{stage}</code>
                      </td>
                      <td>{definition}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section id="evidence">
            <h2>Evidence hierarchy</h2>
            <p>
              Higher evidence does not mean a more senior stage; it means a more direct observation
              of the person at the paper date.
            </p>
            <ol className="ep-evidence-list">
              <li>
                <strong>Byline rank or affiliation.</strong> A publish-time string such as
                “Assistant Professor of Economics, Princeton University” is contemporaneous
                evidence. It is rare: explicit academic rank appears on about 0.3% of author slots.
              </li>
              <li>
                <strong>ORCID employment and education.</strong> Self-reported, dated positions and
                degrees. An event is used only if its interval covers the paper year and the ORCID
                identity passes validation. Explicit rank titles are high confidence; generic
                “Professor” titles are low because the title may describe the present rather than
                the paper date.
              </li>
              <li>
                <strong>Wayback faculty pages.</strong> A historical snapshot near the paper year
                can show the rank that was current at the time. The parser looks for an academic
                rank phrase near the author&apos;s family name, uses the paper&apos;s byline
                institution, and caps confidence at medium.
              </li>
              <li>
                <strong>CV employment and education.</strong> Public CVs and faculty pages,
                discovered through ORCID researcher URLs, are parsed conservatively by section and
                used only after byline, ORCID, and Wayback evidence.
              </li>
              <li>
                <strong>Unknown.</strong> No assignment is stored when the evidence is insufficient.
              </li>
            </ol>
            <p>
              Current coverage: {data ? formatPct(data.coverage.career) : '—'} of author slots have
              a stage. {data ? formatNumber(data.counts.authorships - data.counts.career_assignments) : '—'}{' '}
              remain unknown.
            </p>
          </section>

          <section id="orcid">
            <h2>ORCID identity validation</h2>
            <p>
              An ORCID link is not accepted merely because OpenAlex attached it to an authorship.
              The record is checked against the author&apos;s papers and affiliations across the five journals first.
            </p>
            <div className="ep-table-wrap">
              <table className="ep-table">
                <thead>
                  <tr>
                    <th scope="col">Tier</th>
                    <th scope="col">Evidence</th>
                    <th scope="col">Use</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>
                      <code>verified_doi</code>
                    </td>
                    <td>An ORCID work DOI matches a paper DOI</td>
                    <td>Events used; confidence retained</td>
                  </tr>
                  <tr>
                    <td>
                      <code>verified_title</code>
                    </td>
                    <td>An ORCID work title matches a paper title</td>
                    <td>Events used; confidence retained</td>
                  </tr>
                  <tr>
                    <td>
                      <code>verified_institution</code>
                    </td>
                    <td>ORCID employment/education overlaps a byline institution</td>
                    <td>Events used; capped at medium</td>
                  </tr>
                  <tr>
                    <td>
                      <code>field_economics</code>
                    </td>
                    <td>An economics department or core economics journal, without a direct paper link</td>
                    <td>Events used; capped at low and flagged</td>
                  </tr>
                  <tr>
                    <td>
                      <code>orcid_unverified</code>
                    </td>
                    <td>No positive evidence, but no contradiction</td>
                    <td>Identity kept as low confidence; events withheld</td>
                  </tr>
                  <tr>
                    <td>
                      <code>rejected_*</code>
                    </td>
                    <td>Name conflict, clear non-economics field, or a career-changing event without positive evidence</td>
                    <td>Link withheld; events cleared</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p>
              This prevents a surgeon, political scientist, or computer scientist who shares a name
              from contributing a career timeline, while preserving real movers and sparse but
              plausible records with an explicit confidence label.
            </p>
          </section>

          <section id="identity">
            <h2>Stable identity</h2>
            <p>
              Public author URLs use <code>stable_id</code>, which survives author-table rebuilds.
              The ledger records ORCID, OpenAlex ID, name keys, publication years, institutions, and
              status. Confirmed splits are protected by permanent separation rules so a later
              name-only rebuild cannot re-merge two people. Uncertain identity cases remain visible
              in the review status rather than being silently resolved.
            </p>
          </section>

          <section id="dates">
            <h2>Dates, topics, and citations</h2>
            <p>
              Issue months come from the AEA article page or the AEA all-issues calendar, not from
              Crossref&apos;s historical month field. JEL codes are parsed from AEA article pages
              and stored separately from machine-generated OpenAlex topics; the two schemes are
              never merged. Citation counts are stored as reported by Crossref and OpenAlex and are
              not reconciled into a single “true” count. The interface prefers OpenAlex&apos;s
              <code>cited_by_count</code> and falls back to Crossref&apos;s
              <code>is-referenced-by-count</code>.
            </p>
            <p>
              These counts are not Google Scholar counts. Google Scholar indexes full text, working
              papers, books, and other grey literature, and has no public, reproducible API.
              OpenAlex and Crossref index a narrower set of works, and Crossref only counts
              citations deposited by publishers, so their numbers are usually lower and can
              disagree with each other. The product labels the source and does not present a
              reconciled “true” citation count.
            </p>
            <p>
              Every abstract records its provenance: <code>crossref</code>, <code>aea</code>, or{' '}
              <code>openalex</code>. OpenAlex page-description boilerplate is filtered rather than
              shown as an abstract.
            </p>
          </section>

          <section id="limits">
            <h2>Limits and missingness</h2>
            <ul>
              <li>
                <strong>Career coverage is partial.</strong> {data ? formatPct(data.coverage.career) : '—'}{' '}
                of author slots have a stage. ORCID records are self-reported and often lack dates;
                the CV corpus is a resumable crawl, not a completed census.
              </li>
              <li>
                <strong>Generic titles are ambiguous.</strong> A current “Professor” may have been an
                assistant professor at the paper date. Those assignments are low confidence.
              </li>
              <li>
                <strong>Identity is never perfect.</strong> Namesakes, transliteration variants, and
                OpenAlex profile merges are explicit review states. A rejected ORCID link is shown
                as rejected, not quietly replaced.
              </li>
              <li>
                <strong>Citation counts are as-reported.</strong> They can be affected by duplicate
                works, citation matching, and what each source counts.
              </li>
            </ul>
          </section>

          <section>
            <h2>Corrections and privacy</h2>
            <p>
              CV data is reduced to structured degree and employment facts with a source URL. Raw
              CV documents are kept only in the project&apos;s local cache; the public database does
              not redistribute them. A correction and takedown process will be available before
              public launch.
            </p>
            <p>
              <Link className="ep-text-link" to="/papers">
                Browse the papers
              </Link>
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}
