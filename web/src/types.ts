export type Confidence = 'high' | 'medium' | 'low' | 'unknown'

export interface YearPoint {
  year: number
  papers: number
  pp: number
  assignments: number
  assigned_authors: number
  coverage: number
}

export interface StageCount {
  stage: string
  n: number
}

export interface EvidenceCount {
  evidence_type: string
  confidence: Confidence
  n: number
}

export interface OrcidTier {
  orcid_source: string
  orcid_match_confidence: string
  n: number
}

export interface TopAuthor {
  stable_id: string
  name: string
  papers: number
  first_year: number
  last_year: number
  institution: string | null
  orcid_confidence: string | null
}

export interface Overview {
  generated_at: string
  dataset: { journal: string; issn: string; start_year: number }
  counts: {
    papers: number
    pp_papers: number
    authors: number
    authorships: number
    coauthorship_edges: number
    career_assignments: number
    abstracts: number
    orcid_authors: number
    orcid_accepted: number
    orcid_unverified: number
    cv_sources: number
  }
  coverage: Record<'career' | 'abstract' | 'orcid' | 'dated', number>
  years: YearPoint[]
  stages: StageCount[]
  evidence: EvidenceCount[]
  orcid_tiers: OrcidTier[]
  institutions: Array<{ display_name: string; country: string | null; slots: number }>
  top_authors: TopAuthor[]
  recent_papers: Paper[]
  most_cited: Paper[]
}

export interface AuthorRef {
  stable_id: string | null
  name: string
  order: number
  orcid: string | null
  affiliation: string | null
  institution: string | null
  institution_source: string | null
  rank: string | null
  stage: string | null
  evidence_type: string | null
  confidence: Confidence | null
  source_url: string | null
  notes: string | null
}

export interface Paper {
  doi: string
  title: string
  year: number
  month: number | null
  date: string | null
  volume: string | null
  issue: string | null
  pages: string | null
  is_pp: boolean
  citation_count: number | null
  openalex_cited_by_count: number | null
  abstract_available: boolean
  retraction_status: string | null
  url: string
  abstract_short?: string | null
  authors?: AuthorRef[]
}

export interface PaperDetail extends Paper {
  abstract: string | null
  abstract_source: string | null
  authors: AuthorRef[]
  jel: Array<{ code: string; label: string }>
  topics: Array<{ code: string; label: string; score: number; primary: boolean }>
  retraction: {
    status: string | null
    notice: { doi: string; title: string } | null
  } | null
  provenance: {
    date_source: string | null
    date_confidence: string | null
    abstract_source: string | null
    source_primary: string
    openalex_id: string | null
    aea_url: string | null
  }
}

export interface PaperList {
  items: Paper[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface AuthorListItem {
  stable_id: string
  name: string
  orcid: string | null
  orcid_source: string | null
  orcid_confidence: string | null
  openalex_id: string | null
  review_status: string | null
  needs_review: boolean
  papers: number
  first_year: number | null
  last_year: number | null
  assigned_papers: number
  coverage: number
  institution: string | null
  stage: string | null
  career_confidence: Confidence | null
}

export interface AuthorList {
  items: AuthorListItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface CareerEvent {
  event_type: 'employment' | 'education'
  title: string | null
  institution: string | null
  start_year: number | null
  end_year: number | null
  is_current: number
  source_type: string
  confidence: Confidence
  source_url: string | null
  source_snippet: string | null
}

export interface AuthorPaper {
  doi: string
  title: string
  year: number
  month: number | null
  volume: string | null
  issue: string | null
  pages: string | null
  is_pp: boolean
  author_order: number
  stage: string | null
  evidence_type: string | null
  career_confidence: Confidence | null
  notes: string | null
  source_url: string | null
}

export interface Coauthor {
  stable_id: string
  canonical_name: string
  orcid_match_confidence: string | null
  shared: number
  first_year: number | null
  last_year: number | null
}

export interface Institution {
  display_name: string
  country: string | null
  ror: string | null
  slots: number
  first_year: number
  last_year: number
}

export interface AuthorDetail {
  stable_id: string
  name: string
  orcid: string | null
  orcid_source: string | null
  orcid_confidence: string | null
  openalex_id: string | null
  review_status: string | null
  needs_review: boolean
  papers: number
  first_year: number | null
  last_year: number | null
  assigned_papers: number
  coverage: number
  institution: string | null
  openalex_works_count: number | null
  openalex_cited_by_count: number | null
  career_events: CareerEvent[]
  paper_list: AuthorPaper[]
  stage_counts: StageCount[]
  evidence_counts: EvidenceCount[]
  coauthors: Coauthor[]
  coauthor_count: number
  institutions: Institution[]
}

export interface NetworkNode {
  id: string
  name: string
  papers: number
  first_year: number | null
  last_year: number | null
  institution: string | null
  stage: string | null
  confidence: Confidence
  is_center: boolean
  shared?: number
  shared_first_year?: number
  shared_last_year?: number
}

export interface NetworkEdge {
  source: string
  target: string
  weight: number
  first_year: number | null
  last_year: number | null
}

export interface NetworkPayload {
  mode: 'top' | 'ego'
  focus?: string
  center?: string
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  meta: {
    year_from?: number | null
    year_to?: number | null
    limit?: number
    min_papers?: number
    selected: number
    total_authors?: number
    total_coauthors?: number
    truncated: boolean
  }
}
