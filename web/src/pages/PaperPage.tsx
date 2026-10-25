import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import StageBadge from '../components/StageBadge'
import { ErrorState, LoadingState } from '../components/States'
import { confidenceLabel, formatNumber, useApi } from '../lib'

export default function PaperPage() {
  const params = useParams()
  const doi = decodeURIComponent(params['*'] ?? '')
  const { data, loading, error } = useApi(() => api.paper(doi), [doi])

  if (loading) return <LoadingState label="Loading the paper" />
  if (error) return <ErrorState message={error} />
  if (!data) return null

  const citationCount = data.openalex_cited_by_count ?? data.citation_count

  return (
    <article className="ep-page ep-paper-page">
      <nav className="ep-breadcrumb" aria-label="Breadcrumb">
        <Link to="/papers">Papers</Link>
        <span>/</span>
        <span>{data.year}</span>
      </nav>

      <header className="ep-paper-head">
        <div className="ep-paper-meta">
          <span>{data.year}</span>
          <span>
            Vol. {data.volume ?? '—'}, No. {data.issue ?? '—'}
          </span>
          {data.pages && <span>pp. {data.pages}</span>}
          {data.is_pp && <span className="ep-flag">Papers &amp; Proceedings</span>}
          {data.retraction_status && <span className="ep-flag is-alert">Retracted</span>}
        </div>
        <h1>{data.title}</h1>
        <div className="ep-byline">
          {data.authors.map((author, index) => (
            <span key={`${author.name}-${author.order}`} className="ep-byline-author">
              {author.stable_id ? (
                <Link to={`/authors/${author.stable_id}`}>{author.name}</Link>
              ) : (
                author.name
              )}
              {index < data.authors.length - 1 ? ',' : ''}
            </span>
          ))}
        </div>
      </header>

      {data.retraction?.notice && (
        <div className="ep-alert">
          <strong>Retraction notice.</strong>{' '}
          <Link to={`/papers/${data.retraction.notice.doi}`}>{data.retraction.notice.title}</Link>
        </div>
      )}

      <div className="ep-paper-layout">
        <div className="ep-paper-main">
          <section className="ep-prose" aria-labelledby="abstract-title">
            <h2 id="abstract-title">Abstract</h2>
            {data.abstract ? (
              <p>{data.abstract}</p>
            ) : (
              <p className="ep-muted">No abstract is available from the sources in this record.</p>
            )}
            <p className="ep-provenance-line">
              Abstract source: {data.abstract_source ?? 'not available'}
              {data.provenance.date_source
                ? ` / date source: ${data.provenance.date_source}`
                : ''}
            </p>
          </section>

          <section className="ep-career-section" aria-labelledby="career-at-publication">
            <div className="ep-section-heading">
              <div>
                <h2 id="career-at-publication">Career at publication</h2>
                <p>
                  Each row is the best available evidence for that author at this paper&apos;s
                  publication date. Missing evidence stays missing.
                </p>
              </div>
              <Link className="ep-text-link" to="/methodology">
                Evidence rules
              </Link>
            </div>
            <div className="ep-table-wrap">
              <table className="ep-table">
                <thead>
                  <tr>
                    <th scope="col">Author</th>
                    <th scope="col">Stage</th>
                    <th scope="col">Evidence</th>
                    <th scope="col">Confidence</th>
                    <th scope="col">Affiliation in byline</th>
                  </tr>
                </thead>
                <tbody>
                  {data.authors.map((author) => (
                    <tr key={`${author.name}-${author.order}`}>
                      <td>
                        {author.stable_id ? (
                          <Link to={`/authors/${author.stable_id}`}>{author.name}</Link>
                        ) : (
                          author.name
                        )}
                      </td>
                      <td>
                        <StageBadge stage={author.stage} confidence={author.confidence} compact />
                      </td>
                      <td>{author.evidence_type?.replaceAll('_', ' ') ?? '—'}</td>
                      <td>{author.confidence ? confidenceLabel(author.confidence) : '—'}</td>
                      <td className="ep-cell-affiliation">
                        {author.affiliation ?? author.institution ?? '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <aside className="ep-paper-aside">
          <section className="ep-aside-block">
            <h2>Record</h2>
            <dl className="ep-meta-list">
              <div>
                <dt>DOI</dt>
                <dd>
                  <a href={`https://doi.org/${data.doi}`} target="_blank" rel="noreferrer">
                    {data.doi}
                  </a>
                </dd>
              </div>
              <div>
                <dt>Published</dt>
                <dd>{data.date ?? data.year}</dd>
              </div>
              <div>
                <dt>Citations</dt>
                <dd>
                  {formatNumber(citationCount)}
                  <small> OpenAlex / Crossref as reported</small>
                </dd>
              </div>
              <div>
                <dt>OpenAlex</dt>
                <dd>{data.provenance.openalex_id ?? 'Not indexed'}</dd>
              </div>
            </dl>
          </section>

          {data.jel.length > 0 && (
            <section className="ep-aside-block">
              <h2>JEL codes</h2>
              <ul className="ep-code-list">
                {data.jel.map((item) => (
                  <li key={item.code}>
                    <code>{item.code}</code>
                    <span>{item.label}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {data.topics.length > 0 && (
            <section className="ep-aside-block">
              <h2>OpenAlex topics</h2>
              <ul className="ep-topic-list">
                {data.topics.slice(0, 6).map((topic) => (
                  <li key={`${topic.code}-${topic.label}`}>
                    <span>{topic.label}</span>
                    {topic.primary && <small>primary</small>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="ep-aside-block ep-aside-note">
            <h2>How to cite</h2>
            <p>
              Use the DOI. This page describes the record; it does not replace the published
              article or its metadata at the AEA.
            </p>
          </section>
        </aside>
      </div>
    </article>
  )
}
