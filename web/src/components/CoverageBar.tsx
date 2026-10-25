import { formatPct } from '../lib'

export default function CoverageBar({
  value,
  label = 'Career coverage',
  showValue = true,
}: {
  value: number
  label?: string
  showValue?: boolean
}) {
  const width = Math.max(0, Math.min(100, value))
  return (
    <span className="ep-coverage" role="img" aria-label={`${label}: ${formatPct(value)}`}>
      <span className="ep-coverage-track">
        <span className="ep-coverage-fill" style={{ width: `${width}%` }} />
      </span>
      {showValue && <span className="ep-coverage-value">{formatPct(value)}</span>}
    </span>
  )
}
