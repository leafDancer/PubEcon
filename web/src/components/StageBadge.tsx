import type { Confidence } from '../types'
import { confidenceLabel, stageLabel } from '../lib'

function stageGroup(stage: string | null | undefined): string {
  if (!stage) return 'unknown'
  if (['phd_student', 'masters_student', 'undergraduate'].includes(stage)) return 'trainee'
  if (['postdoc', 'research_fellow'].includes(stage)) return 'early'
  if (stage === 'assistant_professor') return 'assistant'
  if (['associate_professor', 'full_professor', 'emeritus'].includes(stage)) return 'senior'
  return 'other'
}

export default function StageBadge({
  stage,
  confidence,
  compact = false,
}: {
  stage: string | null | undefined
  confidence?: Confidence | null
  compact?: boolean
}) {
  return (
    <span
      className={`ep-stage is-${stageGroup(stage)}${compact ? ' is-compact' : ''}`}
      title={confidence ? `${confidenceLabel(confidence)} confidence` : undefined}
    >
      <span className="ep-stage-dot" aria-hidden="true" />
      <span>{stageLabel(stage)}</span>
      {confidence && <span className="ep-stage-conf">{confidenceLabel(confidence)}</span>}
    </span>
  )
}
