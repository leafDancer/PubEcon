import { Link } from 'react-router-dom'
import type { Paper } from '../types'
import { formatNumber } from '../lib'
import StageBadge from './StageBadge'

export default function PaperRow({ paper }: { paper: Paper }) {
  const authors = paper.authors ?? []
  const visibleAuthors = authors.slice(0, 4)
  const knownCount = authors.filter((author) => author.stage).length
  const knownStages = authors.filter((author) => author.stage).slice(0, 3)
  return (
    <article className="ep-paper-row">
      <div className="ep-paper-year">{paper.year}</div>
      <div className="ep-paper-body">
        <h2 className="ep-paper-title">
          <Link to={`/papers/${paper.doi}`}>{paper.title}</Link>
        </h2>
        <p className="ep-paper-byline">
          {visibleAuthors.map((author, index) => (
            <span key={`${author.stable_id ?? author.name}-${author.order}`}>
              {author.stable_id ? (
                <Link to={`/authors/${author.stable_id}`}>{author.name}</Link>
              ) : (
                author.name
              )}
              {index < visibleAuthors.length - 1 ? ', ' : ''}
            </span>
          ))}
          {authors.length > visibleAuthors.length ? ` +${authors.length - visibleAuthors.length}` : ''}
        </p>
        {knownStages.length > 0 && (
          <div className="ep-paper-stages">
            {knownStages.map((author) => (
              <StageBadge
                key={`${author.stable_id ?? author.name}-stage`}
                stage={author.stage}
                confidence={author.confidence}
                compact
              />
            ))}
            {knownCount > 0 && knownCount < authors.length && (
              <span className="ep-muted-small">
                stage known for {knownCount} of {authors.length}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="ep-paper-flags">
        <span className="ep-flag is-journal">{paper.journal}</span>
        {paper.is_pp && <span className="ep-flag">AER P&amp;P</span>}
        {paper.retraction_status && <span className="ep-flag is-alert">Retracted</span>}
      </div>
      <div className="ep-paper-cites">
        <span>{formatNumber(paper.openalex_cited_by_count ?? paper.citation_count)}</span>
        <small>
          {paper.openalex_cited_by_count != null ? 'OpenAlex cites' : 'Crossref cites'}
        </small>
      </div>
    </article>
  )
}
