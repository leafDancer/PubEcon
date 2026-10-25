import type { Confidence } from '../types'
import { confidenceLabel } from '../lib'

export default function ConfidenceMark({
  confidence,
  label = true,
}: {
  confidence: Confidence | string | null | undefined
  label?: boolean
}) {
  const value = confidence || 'unknown'
  return (
    <span className={`ep-confidence is-${value}`}>
      <span className="ep-confidence-mark" aria-hidden="true" />
      {label && <span>{confidenceLabel(value)}</span>}
    </span>
  )
}
