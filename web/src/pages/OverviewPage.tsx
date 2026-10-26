import { Link } from 'react-router-dom'
import { api } from '../api'
import NetworkGraph from '../components/NetworkGraph'
import PaperRow from '../components/PaperRow'
import StageBadge from '../components/StageBadge'
import YearRuler from '../components/YearRuler'
import { formatNumber, formatPct, useApi } from '../lib'
import { ErrorState, LoadingState } from '../components/States'

function Stat({
  value,
  label,
  note,
}: {
  value: string
  label: string
  note?: string
}) {
  return (
    <div className="ep-stat">
      <strong>{value}</strong>
      <span>{label}</span>
      {note && <small>{note}</small>}
    </div>
  )
}

export default function OverviewPage() {
  const { data, loading, error } = useApi(() => api.overview(), [])
  const network = useApi(() => api.network({ limit: 36, min_papers: 4 }), [])

  if (loading) return <LoadingState label="Loading the EconPub record" />
  if (error) return <ErrorState message={error} />
  if (!data) return null

  const stageMax = Math.max(...data.stages.map((item) => item.n), 1)
  const topStages = data.stages.slice(0, 9)

  return (
    <div className="ep-page ep-overview">
      <section className="ep-hero">
        <div className="ep-hero-copy">
          <p className="ep-kicker">{data.dataset.journal} / 2000–2026</p>
          <h1>Twenty-six years of economics, in the open.</h1>
          <p className="ep-hero-deck">
            Every research article in the top five economics journals since 2000, its authors,
            and the career stage each author held when the paper was published. Evidence and
            confidence travel with every claim.
          </p>
          <div className="ep-actions">
            <Link className="ep-button" to="/papers">
              Browse the papers
            </Link>
            <Link className="ep-text-link" to="/methodology">
              How the record is built
            </Link>
          </div>
        </div>
        <div className="ep-hero-figure">
          <YearRuler years={data.years} />
        </div>
      </section>

      <section className="ep-stat-strip" aria-label="Dataset summary">
        <Stat
          value={formatNumber(data.counts.papers)}
          label="research articles"
          note="from five journals, 2000–2026"
        />
        <Stat value={formatNumber(data.counts.authors)} label="canonical authors" note="with stable public IDs" />
        <Stat
          value={formatNumber(data.counts.career_assignments)}
          label="career stages assigned"
          note={`${formatPct(data.coverage.career)} of author slots`}
        />
        <Stat
          value={formatNumber(data.counts.coauthorship_edges)}
          label="coauthor ties"
          note={`from ${formatNumber(data.counts.papers)} article records`}
        />
      </section>

      <section className="ep-split">
        <div className="ep-panel">
          <div className="ep-section-heading">
            <div>
              <h2>Career stage at publication</h2>
              <p>
                Stage is inferred at the paper date, not at the time of collection. Generic
                “Professor” titles remain low confidence.
              </p>
            </div>
            <Link className="ep-text-link" to="/methodology">
              Evidence hierarchy
            </Link>
          </div>
          <div className="ep-stage-bars">
            {topStages.map((item) => (
              <div className="ep-stage-bar-row" key={item.stage}>
                <StageBadge stage={item.stage} compact />
                <div className="ep-stage-bar-track">
                  <span style={{ width: `${(item.n / stageMax) * 100}%` }} />
                </div>
                <strong>{formatNumber(item.n)}</strong>
              </div>
            ))}
          </div>
          <p className="ep-note">
            {formatPct(data.coverage.career)} of author slots have a stage. The remaining{" "}
            {formatNumber(data.counts.authorships - data.counts.career_assignments)} are shown as
            unknown rather than imputed.
          </p>
        </div>

        <div className="ep-panel">
          <div className="ep-section-heading">
            <div>
              <h2>Who works with whom</h2>
              <p>
                A sample of the most connected authors. The explorer lets you move from a
                sample to any author&apos;s ego network.
              </p>
            </div>
            <Link className="ep-text-link" to="/network">
              Open the network
            </Link>
          </div>
          {network.data && network.data.nodes.length > 0 ? (
            <NetworkGraph compact nodes={network.data.nodes} edges={network.data.edges} />
          ) : (
            <p className="ep-empty-inline">The network sample is not available.</p>
          )}
        </div>
      </section>

      <section className="ep-panel ep-journal-panel">
        <div className="ep-section-heading">
          <div>
            <h2>The five journals</h2>
            <p>
              Each journal is a first-class scope, not a filter applied after the fact. Coverage
              is reported separately so a pooled number never hides a weak journal.
            </p>
          </div>
          <Link className="ep-text-link" to="/papers">
            Browse all
          </Link>
        </div>
        <div className="ep-journal-list">
          {data.dataset.journals.map((item) => (
            <Link
              className="ep-journal-row"
              key={item.code}
              to={`/papers?journal=${item.code}`}
            >
              <span className="ep-journal-code">{item.code}</span>
              <span className="ep-journal-name">{item.name}</span>
              <span className="ep-journal-metric">
                <strong>{formatNumber(item.papers)}</strong> papers
              </span>
              <span className="ep-journal-metric">
                <strong>{formatPct((100 * item.abstracts) / Math.max(item.papers, 1))}</strong>{' '}
                abstracts
              </span>
              <span className="ep-journal-metric">
                <strong>{formatPct(item.career_coverage)}</strong> career
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section className="ep-split ep-lists">
        <div className="ep-panel">
          <div className="ep-section-heading">
            <div>
              <h2>Recent papers</h2>
              <p>The newest research articles in the record.</p>
            </div>
            <Link className="ep-text-link" to="/papers?sort=year_desc">
              All papers
            </Link>
          </div>
          <div className="ep-paper-list">
            {data.recent_papers.map((paper) => (
              <PaperRow key={paper.doi} paper={paper} />
            ))}
          </div>
        </div>
        <div className="ep-panel">
          <div className="ep-section-heading">
            <div>
              <h2>Most cited</h2>
              <p>OpenAlex citation counts, shown as reported.</p>
            </div>
            <Link className="ep-text-link" to="/papers?sort=cited">
              Ranked list
            </Link>
          </div>
          <div className="ep-paper-list">
            {data.most_cited.map((paper) => (
              <PaperRow key={paper.doi} paper={paper} />
            ))}
          </div>
        </div>
      </section>

      <section className="ep-split">
        <div className="ep-panel">
          <div className="ep-section-heading">
            <div>
              <h2>Authors with the deepest record</h2>
              <p>Ranked by research articles in the database.</p>
            </div>
            <Link className="ep-text-link" to="/authors">
              Browse authors
            </Link>
          </div>
          <ol className="ep-ranked-list">
            {data.top_authors.map((author, index) => (
              <li key={author.stable_id}>
                <span className="ep-rank-index">{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <Link to={`/authors/${author.stable_id}`}>{author.name}</Link>
                  <small>{author.institution ?? 'Institution not resolved'}</small>
                </div>
                <span className="ep-rank-value">{author.papers}</span>
              </li>
            ))}
          </ol>
        </div>

        <div className="ep-panel ep-note-panel">
          <div className="ep-section-heading">
            <div>
              <h2>What this record does not claim</h2>
              <p>Coverage is real, and so are the gaps.</p>
            </div>
          </div>
          <dl className="ep-definition-list">
            <div>
              <dt>Career stage</dt>
              <dd>
                {formatPct(data.coverage.career)} of author slots. ORCID identities are validated
                against their publication record before their events are used.
              </dd>
            </div>
            <div>
              <dt>Abstracts</dt>
              <dd>{formatPct(data.coverage.abstract)} of articles have an abstract from the publisher, Crossref, or OpenAlex.</dd>
            </div>
            <div>
              <dt>Institutions</dt>
              <dd>OpenAlex resolves publish-time institutions for most, but not all, author slots.</dd>
            </div>
            <div>
              <dt>Missingness</dt>
              <dd>Unknown is a visible value. The interface does not infer a stage from age or seniority.</dd>
            </div>
          </dl>
          <Link className="ep-text-link" to="/methodology">
            Read the methodology
          </Link>
        </div>
      </section>
    </div>
  )
}
