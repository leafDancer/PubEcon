import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import CareerTimeline from '../components/CareerTimeline'
import ConfidenceMark from '../components/ConfidenceMark'
import CoverageBar from '../components/CoverageBar'
import StageBadge from '../components/StageBadge'
import { ErrorState, LoadingState } from '../components/States'
import {
  confidenceLabel,
  formatNumber,
  formatPct,
  sourceLabel,
  stageLabel,
  useApi,
  yearRange,
} from '../lib'
import type { Confidence } from '../types'

export default function AuthorPage() {
  const { stableId = '' } = useParams()
  const { data, loading, error } = useApi(() => api.author(stableId), [stableId])

  if (loading) return <LoadingState label="Loading the author" />
  if (error) return <ErrorState message={error} />
  if (!data) return null

  return (
    <article className="ep-page ep-author-page">
      <nav className="ep-breadcrumb" aria-label="Breadcrumb">
        <Link to="/authors">Authors</Link>
        <span>/</span>
        <span>{data.name}</span>
      </nav>

      <header className="ep-author-head">
        <div className="ep-author-head-main">
          <p className="ep-kicker">Author record / {data.stable_id}</p>
          <h1>{data.name}</h1>
          <p className="ep-page-deck">
            {data.institution ?? 'Institution not resolved'} (AER papers {yearRange(data.first_year, data.last_year)})
          </p>
          <div className="ep-author-head-links">
            {data.orcid ? (
              <a href={data.orcid} target="_blank" rel="noreferrer" className="ep-text-link">
                ORCID record
              </a>
            ) : (
              <span className="ep-muted">No ORCID attached</span>
            )}
            <span className={`ep-source-note ${data.orcid_source?.startsWith('rejected') ? 'is-alert' : ''}`}>
              {sourceLabel(data.orcid_source)}
              {data.orcid_confidence ? `, ${confidenceLabel(data.orcid_confidence)}` : ''}
            </span>
            <Link className="ep-text-link" to={`/network?focus=${data.stable_id}`}>
              View coauthor network
            </Link>
          </div>
        </div>
        <div className="ep-author-head-stats">
          <div>
            <strong>{formatNumber(data.papers)}</strong>
            <span>AER papers</span>
          </div>
          <div>
            <strong>{formatNumber(data.coauthor_count)}</strong>
            <span>coauthors</span>
          </div>
          <div>
            <strong>{formatPct(data.coverage)}</strong>
            <span>with a career stage</span>
          </div>
        </div>
      </header>

      {data.needs_review && (
        <div className="ep-alert is-soft">
          <strong>Identity review flag.</strong> This record has an unresolved identity or
          evidence-review flag: {data.review_status?.replaceAll('_', ' ') ?? 'needs review'}.
        </div>
      )}

      <CareerTimeline author={data} />

      <div className="ep-author-layout">
        <section className="ep-panel" aria-labelledby="author-papers">
          <div className="ep-section-heading">
            <div>
              <h2 id="author-papers">AER papers</h2>
              <p>Each row carries the stage assigned at that paper&apos;s publication date.</p>
            </div>
          </div>
          {data.paper_list.length === 0 ? (
            <p className="ep-empty-inline">No research articles are attached to this author.</p>
          ) : (
            <div className="ep-table-wrap">
              <table className="ep-table ep-paper-table">
                <thead>
                  <tr>
                    <th scope="col">Year</th>
                    <th scope="col">Paper</th>
                    <th scope="col">Stage at publication</th>
                    <th scope="col">Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {data.paper_list.map((paper) => (
                    <tr key={`${paper.doi}-${paper.author_order}`}>
                      <td>{paper.year}</td>
                      <td>
                        <Link to={`/papers/${paper.doi}`}>{paper.title}</Link>
                        <small className="ep-cell-note">
                          {paper.is_pp ? 'Papers & Proceedings' : 'Research article'}
                        </small>
                      </td>
                      <td>
                        <StageBadge
                          stage={paper.stage}
                          confidence={paper.career_confidence as Confidence | null}
                          compact
                        />
                      </td>
                      <td>
                        {paper.evidence_type?.replaceAll('_', ' ') ?? 'No stage evidence'}
                        {paper.career_confidence ? `, ${confidenceLabel(paper.career_confidence)}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <aside className="ep-author-aside">
          <section className="ep-aside-block">
            <h2>Identity</h2>
            <dl className="ep-meta-list">
              <div>
                <dt>Stable ID</dt>
                <dd>
                  <code>{data.stable_id}</code>
                </dd>
              </div>
              <div>
                <dt>OpenAlex</dt>
                <dd>{data.openalex_id ?? 'Not linked'}</dd>
              </div>
              <div>
                <dt>ORCID confidence</dt>
                <dd>
                  {data.orcid_confidence ? (
                    <ConfidenceMark confidence={data.orcid_confidence as Confidence} />
                  ) : (
                    '—'
                  )}
                </dd>
              </div>
              <div>
                <dt>Career coverage</dt>
                <dd>
                  <CoverageBar value={data.coverage} />
                </dd>
              </div>
            </dl>
          </section>

          <section className="ep-aside-block">
            <h2>Institutions in the record</h2>
            {data.institutions.length === 0 ? (
              <p className="ep-muted">No resolved institutions.</p>
            ) : (
              <ul className="ep-institution-list">
                {data.institutions.map((institution) => (
                  <li key={institution.display_name}>
                    <span>{institution.display_name}</span>
                    <small>
                      {institution.slots} paper{institution.slots === 1 ? '' : 's'},{' '}
                      {yearRange(institution.first_year, institution.last_year)}
                    </small>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="ep-aside-block">
            <h2>Frequent coauthors</h2>
            {data.coauthors.length === 0 ? (
              <p className="ep-muted">No coauthors in the record.</p>
            ) : (
              <ol className="ep-coauthor-list">
                {data.coauthors.map((coauthor) => (
                  <li key={coauthor.stable_id}>
                    <Link to={`/authors/${coauthor.stable_id}`}>{coauthor.canonical_name}</Link>
                    <span>{coauthor.shared} shared</span>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className="ep-aside-block">
            <h2>Stage distribution</h2>
            {data.stage_counts.length === 0 ? (
              <p className="ep-muted">No assigned stages.</p>
            ) : (
              <ul className="ep-stage-count-list">
                {data.stage_counts.map((item) => (
                  <li key={item.stage}>
                    <span>{stageLabel(item.stage)}</span>
                    <strong>{item.n}</strong>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="ep-aside-block ep-aside-note">
            <h2>About this record</h2>
            <p>
              Stable IDs survive pipeline rebuilds. A stage is shown only when a dated event covers
              the paper year or the byline states a rank. Identity and evidence conflicts remain
              visible rather than being smoothed away.
            </p>
          </section>
        </aside>
      </div>
    </article>
  )
}
