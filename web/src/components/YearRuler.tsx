import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { YearPoint } from '../types'
import { formatNumber } from '../lib'

const WIDTH = 920
const HEIGHT = 230
const LEFT = 44
const RIGHT = 900
const TOP = 18
const BOTTOM = 176

export default function YearRuler({ years }: { years: YearPoint[] }) {
  const navigate = useNavigate()
  const [hover, setHover] = useState<{ x: number; y: number; point: YearPoint } | null>(null)
  if (!years.length) return null

  const max = Math.max(...years.map((point) => point.papers), 1)
  const slot = (RIGHT - LEFT) / years.length
  const barWidth = Math.min(22, slot * 0.62)
  const y = (value: number) => BOTTOM - (value / max) * (BOTTOM - TOP)
  const lastYear = years.at(-1)?.year ?? years[0].year
  const ticks = years.filter(
    (point) =>
      point.year === years[0].year ||
      point.year === lastYear ||
      point.year % 10 === 0 ||
      (point.year % 5 === 0 && lastYear - point.year >= 2),
  )

  const openYear = (year: number) => {
    navigate(`/papers?year_from=${year}&year_to=${year}`)
  }

  return (
    <figure className="ep-year-figure">
      <div className="ep-year-head">
        <span>Research articles by year</span>
        <span>Click a year to open it</span>
      </div>
      <div className="ep-year-canvas">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label="Research articles by year across the five journals, split between regular articles and AER Papers and Proceedings."
          onMouseLeave={() => setHover(null)}
        >
          <line x1={LEFT} y1={BOTTOM} x2={RIGHT} y2={BOTTOM} className="ep-year-baseline" />
          {[0.25, 0.5, 0.75, 1].map((fraction) => (
            <line
              key={fraction}
              x1={LEFT}
              y1={y(max * fraction)}
              x2={RIGHT}
              y2={y(max * fraction)}
              className="ep-year-grid"
            />
          ))}
          {years.map((point, index) => {
            const x = LEFT + index * slot + (slot - barWidth) / 2
            const regular = Math.max(point.papers - point.pp, 0)
            const ppY = y(point.pp)
            const regularY = y(point.papers)
            return (
              <g
                key={point.year}
                role="link"
                tabIndex={0}
                className="ep-year-bar-group"
                aria-label={`${point.year}: ${formatNumber(point.papers)} articles, ${formatNumber(point.pp)} in Papers and Proceedings. Open papers from ${point.year}.`}
                onClick={() => openYear(point.year)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    openYear(point.year)
                  }
                }}
                onMouseMove={(event) => {
                  const rect = event.currentTarget.ownerSVGElement?.getBoundingClientRect()
                  if (!rect) return
                  setHover({
                    x: event.clientX - rect.left,
                    y: event.clientY - rect.top,
                    point,
                  })
                }}
              >
                <rect
                  x={x}
                  y={regularY}
                  width={barWidth}
                  height={Math.max(BOTTOM - regularY, 0.8)}
                  className="ep-year-regular"
                />
                {point.pp > 0 && (
                  <rect
                    x={x}
                    y={ppY}
                    width={barWidth}
                    height={Math.max(BOTTOM - ppY, 0.8)}
                    className="ep-year-pp"
                    />
                )}
              </g>
            )
          })}
          {ticks.map((point, index) => {
            const yearIndex = years.findIndex((item) => item.year === point.year)
            return (
              <text
                key={point.year}
                x={LEFT + yearIndex * slot + slot / 2}
                y={BOTTOM + 24}
                textAnchor="middle"
                className="ep-year-tick"
              >
                {index === 0 || point.year === years.at(-1)?.year || point.year % 10 === 0
                  ? point.year
                  : `’${String(point.year).slice(2)}`}
              </text>
            )
          })}
          <text x={LEFT} y={TOP - 4} className="ep-year-max">
            {max}
          </text>
        </svg>
        {hover && (
          <div
            className="ep-chart-tip"
            style={{
              left: `${hover.x}px`,
              top: `${Math.max(hover.y - 8, 4)}px`,
            }}
          >
            <strong>{hover.point.year}</strong>
            <span>{formatNumber(hover.point.papers)} articles</span>
            <span>{formatNumber(hover.point.pp)} AER P&amp;P</span>
            <span>{hover.point.coverage.toFixed(0)}% with a career stage</span>
          </div>
        )}
      </div>
      <figcaption className="ep-figure-caption">
        <span className="ep-legend">
          <span className="ep-legend-swatch is-regular" /> Regular articles
          <span className="ep-legend-swatch is-pp" /> AER Papers &amp; Proceedings
        </span>
        <span>
          AER Papers &amp; Proceedings are included through 2017. Counts include research articles only.
        </span>
      </figcaption>
      <details className="ep-data-table">
        <summary>Yearly counts as a table</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Year</th>
              <th scope="col">Articles</th>
              <th scope="col">AER P&amp;P</th>
              <th scope="col">With career stage</th>
            </tr>
          </thead>
          <tbody>
            {years.map((point) => (
              <tr key={point.year}>
                <td>{point.year}</td>
                <td>{formatNumber(point.papers)}</td>
                <td>{formatNumber(point.pp)}</td>
                <td>{point.coverage.toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}
