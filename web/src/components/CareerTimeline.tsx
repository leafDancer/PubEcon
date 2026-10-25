import type { AuthorDetail, CareerEvent } from '../types'
import { confidenceLabel, formatYear, stageLabel } from '../lib'
import StageBadge from './StageBadge'

const CURRENT_YEAR = 2026

function eventLabel(event: CareerEvent): string {
  return event.title || (event.event_type === 'education' ? 'Degree' : 'Position')
}

function eventSourceClass(event: CareerEvent): string {
  if (event.source_type === 'orcid') return 'is-orcid'
  if (event.source_type === 'wayback') return 'is-wayback'
  if (event.source_type === 'cv') return 'is-cv'
  return 'is-other'
}

export default function CareerTimeline({ author }: { author: AuthorDetail }) {
  const dated = author.career_events.filter((event) => event.start_year !== null)
  const eventEnd = (event: CareerEvent) =>
    event.end_year ?? (event.is_current ? CURRENT_YEAR : (event.start_year as number))
  const years = [
    ...dated.map((event) => event.start_year as number),
    ...dated.map((event) => eventEnd(event)),
    ...author.paper_list.map((paper) => paper.year),
    author.first_year ?? CURRENT_YEAR,
    author.last_year ?? CURRENT_YEAR,
  ].filter((value): value is number => Number.isFinite(value))
  const minYear = Math.min(...years, CURRENT_YEAR) - 1
  const maxYear = Math.max(...years, CURRENT_YEAR) + 1
  const span = Math.max(maxYear - minYear, 1)
  const position = (year: number) => ((year - minYear) / span) * 100
  const width = (start: number, end: number) => Math.max(((end - start) / span) * 100, 1.2)
  const ticks: number[] = []
  const firstTick = Math.ceil(minYear / 5) * 5
  for (let year = firstTick; year <= maxYear; year += 5) ticks.push(year)

  const papersByYear = new Map<number, typeof author.paper_list>()
  for (const paper of author.paper_list) {
    const bucket = papersByYear.get(paper.year) ?? []
    bucket.push(paper)
    papersByYear.set(paper.year, bucket)
  }

  return (
    <section className="ep-timeline-block" aria-labelledby="career-timeline-title">
      <div className="ep-section-heading">
        <div>
          <h2 id="career-timeline-title">Career timeline</h2>
          <p>
            Dated employment and education evidence. Papers are placed at their publication year
            and shaded by the confidence of the stage assignment.
          </p>
        </div>
        <div className="ep-legend ep-legend-stack">
          <span className="ep-legend">
            <span className="ep-legend-swatch is-orcid" /> ORCID
            <span className="ep-legend-swatch is-wayback" /> Historical page
            <span className="ep-legend-swatch is-cv" /> CV
          </span>
          <span className="ep-legend">
            <span className="ep-legend-dot is-high" /> High
            <span className="ep-legend-dot is-medium" /> Medium
            <span className="ep-legend-dot is-low" /> Low
            <span className="ep-legend-dot is-unknown" /> Unknown
          </span>
        </div>
      </div>

      {dated.length === 0 && author.paper_list.length === 0 ? (
        <p className="ep-empty-inline">No dated career evidence or papers are available.</p>
      ) : (
        <div className="ep-timeline" role="group" aria-label="Career timeline">
          <div className="ep-timeline-axis">
            <span className="ep-timeline-axis-label">Year</span>
            <div className="ep-timeline-axis-track">
              {ticks.map((year) => (
                <span key={year} style={{ left: `${position(year)}%` }}>
                  {year}
                </span>
              ))}
            </div>
          </div>

          <div className="ep-timeline-row is-papers">
            <div className="ep-timeline-label">
              <span className="ep-timeline-label-main">Papers</span>
              <span className="ep-timeline-label-meta">{author.paper_list.length} AER articles</span>
            </div>
            <div className="ep-timeline-track">
              {[...papersByYear.entries()].map(([year, papers]) => (
                <span
                  key={year}
                  className={`ep-paper-dot is-${papers[0].career_confidence ?? 'unknown'}`}
                  style={{ left: `${position(year)}%` }}
                  title={`${year}: ${papers.length} paper${papers.length === 1 ? '' : 's'}${papers[0].stage ? ` — ${stageLabel(papers[0].stage)}` : ''}`}
                  tabIndex={0}
                />
              ))}
            </div>
          </div>

          {dated.map((event, index) => {
            const start = event.start_year as number
            const end = eventEnd(event)
            const duration = end - start
            return (
              <div className="ep-timeline-row" key={`${event.event_type}-${event.title}-${start}-${index}`}>
                <div className="ep-timeline-label">
                  <span className="ep-timeline-label-main">
                    {event.institution || eventLabel(event)}
                  </span>
                  <span className="ep-timeline-label-meta">
                    {eventLabel(event)}
                    {event.end_year === null && event.is_current ? ', current' : ''}
                  </span>
                </div>
                <div className="ep-timeline-track">
                  <span
                    className={`ep-timeline-bar ${eventSourceClass(event)}`}
                    style={{
                      left: `${position(start)}%`,
                      width: `${width(start, end + 0.35)}%`,
                    }}
                    title={`${eventLabel(event)} at ${event.institution ?? 'unknown institution'} (${start}–${event.end_year ?? (event.is_current ? 'present' : '—')}), ${event.source_type.toUpperCase()}, ${confidenceLabel(event.confidence)} confidence`}
                    tabIndex={0}
                  >
                    {duration >= 3 && (
                      <span className="ep-timeline-bar-label">
                        {formatYear(start)}
                        {duration > 0 ? `–${event.end_year ?? (event.is_current ? 'now' : '')}` : ''}
                      </span>
                    )}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {dated.length === 0 && author.paper_list.length > 0 && (
        <p className="ep-empty-inline">
          No dated employment or education events are available for this author. The paper markers
          above show when they published in the AER.
        </p>
      )}

      <details className="ep-data-table">
        <summary>Career evidence as a table</summary>
        {author.career_events.length === 0 ? (
          <p>No career events are stored for this author.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th scope="col">Type</th>
                <th scope="col">Role or degree</th>
                <th scope="col">Institution</th>
                <th scope="col">Years</th>
                <th scope="col">Source</th>
                <th scope="col">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {author.career_events.map((event, index) => (
                <tr key={`event-table-${index}`}>
                  <td>{event.event_type}</td>
                  <td>{event.title ?? '—'}</td>
                  <td>{event.institution ?? '—'}</td>
                  <td>
                    {formatYear(event.start_year)}–{event.end_year ?? (event.is_current ? 'present' : '—')}
                  </td>
                  <td>
                    {event.source_url ? (
                      <a href={event.source_url} target="_blank" rel="noreferrer">
                        {event.source_type.toUpperCase()}
                      </a>
                    ) : (
                      event.source_type.toUpperCase()
                    )}
                  </td>
                  <td>{confidenceLabel(event.confidence)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </details>

      {author.stage_counts.length > 0 && (
        <div className="ep-stage-summary">
          <h3>Stages assigned at publication</h3>
          <div className="ep-stage-summary-list">
            {author.stage_counts.map((item) => (
              <span key={item.stage}>
                <StageBadge stage={item.stage} compact />
                <strong>{item.n}</strong>
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
