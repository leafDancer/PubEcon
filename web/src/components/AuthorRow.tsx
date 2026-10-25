import { Link } from 'react-router-dom'
import type { AuthorListItem } from '../types'
import { formatNumber, formatPct, sourceLabel, yearRange } from '../lib'
import StageBadge from './StageBadge'
import CoverageBar from './CoverageBar'

export default function AuthorRow({ author }: { author: AuthorListItem }) {
  return (
    <article className="ep-author-row">
      <div className="ep-author-main">
        <h2>
          <Link to={`/authors/${author.stable_id}`}>{author.name}</Link>
        </h2>
        <p className="ep-author-inst">{author.institution ?? 'Institution not resolved'}</p>
        <p className="ep-author-orcid">
          {author.orcid ? (
            <a href={author.orcid} target="_blank" rel="noreferrer">
              ORCID
            </a>
          ) : (
            'No ORCID'
          )}
          <span className="ep-sep">/</span>
          <span className={`ep-source-note ${author.orcid_source?.startsWith('rejected') ? 'is-alert' : ''}`}>
            {sourceLabel(author.orcid_source)}
          </span>
        </p>
      </div>
      <div className="ep-author-stage">
        <StageBadge stage={author.stage} confidence={author.career_confidence} />
      </div>
      <div className="ep-author-count">
        <strong>{formatNumber(author.papers)}</strong>
        <span>papers</span>
        <small>{yearRange(author.first_year, author.last_year)}</small>
      </div>
      <div className="ep-author-coverage">
        <CoverageBar value={author.coverage} />
        <small>
          {formatPct(author.coverage)} of papers have a stage
        </small>
      </div>
    </article>
  )
}
