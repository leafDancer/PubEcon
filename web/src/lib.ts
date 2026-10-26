import { useEffect, useRef, useState } from 'react'
import type { Confidence } from './types'

export const STAGE_LABELS: Record<string, string> = {
  phd_student: 'PhD student',
  masters_student: "Master's student",
  undergraduate: 'Undergraduate',
  postdoc: 'Postdoc',
  research_fellow: 'Research fellow',
  assistant_professor: 'Assistant professor',
  associate_professor: 'Associate professor',
  full_professor: 'Full professor',
  emeritus: 'Emeritus',
  lecturer_other_academic: 'Lecturer / other academic',
  non_academic: 'Non-academic',
}

export const STAGE_ORDER = [
  'phd_student',
  'masters_student',
  'undergraduate',
  'postdoc',
  'research_fellow',
  'assistant_professor',
  'associate_professor',
  'full_professor',
  'emeritus',
  'lecturer_other_academic',
  'non_academic',
]

export const EVIDENCE_LABELS: Record<string, string> = {
  byline_rank: 'Byline rank',
  byline_affiliation: 'Byline affiliation',
  orcid_employment: 'ORCID employment',
  orcid_education: 'ORCID education',
  cv_employment: 'CV employment',
  cv_education: 'CV education',
}

export const ORCID_SOURCE_LABELS: Record<string, string> = {
  verified_doi: 'ORCID DOI match',
  verified_title: 'ORCID title match',
  verified_institution: 'ORCID institution match',
  field_economics: 'ORCID economics field',
  orcid_unverified: 'ORCID unverified',
  rejected_name: 'ORCID name conflict',
  rejected_field: 'ORCID field mismatch',
  rejected_career_risk: 'ORCID career-risk rejection',
}

export function stageLabel(stage: string | null | undefined): string {
  if (!stage) return 'Stage unknown'
  return STAGE_LABELS[stage] ?? stage.replaceAll('_', ' ')
}

export function confidenceLabel(confidence: Confidence | string | null | undefined): string {
  if (!confidence || confidence === 'unknown') return 'Unknown'
  return confidence.charAt(0).toUpperCase() + confidence.slice(1)
}

export function confidenceRank(confidence: string | null | undefined): number {
  return confidence === 'high' ? 0 : confidence === 'medium' ? 1 : confidence === 'low' ? 2 : 3
}

export function safeInt(
  value: string | null | undefined,
  fallback: number,
  min = Number.MIN_SAFE_INTEGER,
  max = Number.MAX_SAFE_INTEGER,
): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(max, Math.max(min, Math.trunc(parsed)))
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return new Intl.NumberFormat('en-US').format(value)
}

export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(value >= 10 ? 0 : 1)}%`
}

export function formatYear(value: number | null | undefined): string {
  return value ? String(value) : '—'
}

export function yearRange(first: number | null | undefined, last: number | null | undefined): string {
  if (!first && !last) return 'Years unknown'
  if (first === last) return String(first)
  return `${first ?? '—'}–${last ?? '—'}`
}

export function sourceLabel(source: string | null | undefined): string {
  if (!source) return 'No ORCID'
  return ORCID_SOURCE_LABELS[source] ?? source.replaceAll('_', ' ')
}

export function titleForDoi(doi: string): string {
  return doi.startsWith('10.1257/') ? doi.slice('10.1257/'.length) : doi
}

export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export function useApi<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    loaderRef
      .current()
      .then((value) => {
        if (!cancelled) {
          setData(value)
          setLoading(false)
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message)
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
    // The caller controls the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, loading, error }
}
