import type {
  AuthorDetail,
  AuthorList,
  NetworkPayload,
  Overview,
  PaperDetail,
  PaperList,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

function withParams(path: string, params?: Params): string {
  if (!params) return `${API_BASE}${path}`
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    query.set(key, String(value))
  }
  const suffix = query.toString()
  return `${API_BASE}${path}${suffix ? `?${suffix}` : ''}`
}

async function get<T>(path: string, params?: Params): Promise<T> {
  const response = await fetch(withParams(path, params), {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const payload = await response.json()
      if (payload?.error) message = String(payload.error)
    } catch {
      // keep the status message
    }
    throw new ApiError(message, response.status)
  }
  return (await response.json()) as T
}

export const api = {
  overview: () => get<Overview>('/overview'),
  stats: () => get<Overview>('/stats'),
  papers: (params: Params) => get<PaperList>('/papers', params),
  paper: (doi: string) => get<PaperDetail>(`/papers/${doi}`),
  authors: (params: Params) => get<AuthorList>('/authors', params),
  author: (stableId: string) => get<AuthorDetail>(`/authors/${stableId}`),
  authorNetwork: (stableId: string, limit = 50, journal?: string) =>
    get<NetworkPayload>(`/authors/${stableId}/network`, { limit, journal }),
  network: (params: Params) => get<NetworkPayload>('/network', params),
}
