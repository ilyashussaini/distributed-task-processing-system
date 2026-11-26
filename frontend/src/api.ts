import type { Attempt, Job, JobPage, JobStatus, Overview, TimeWindow } from './types'

export class RequestError extends Error {
  readonly disconnected: boolean

  constructor(message: string, disconnected = false) {
    super(message)
    this.disconnected = disconnected
  }
}

async function request<T>(path: string, signal?: AbortSignal, init?: RequestInit): Promise<T> {
  const timeout = AbortSignal.timeout(8000)
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      headers: { Accept: 'application/json', ...init?.headers },
    })
  } catch {
    throw new RequestError('The API could not be reached. Check that the local stack is running.', true)
  }

  if (!response.ok) {
    if ([502, 503, 504].includes(response.status)) {
      throw new RequestError('The API is temporarily unavailable.', true)
    }
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : undefined
    throw new RequestError(detail ?? `The API returned an error (${response.status}).`)
  }
  try {
    return await response.json() as T
  } catch {
    throw new RequestError('The API returned an unreadable response.')
  }
}

export const getOverview = (window: TimeWindow, signal: AbortSignal) =>
  request<Overview>(`/monitoring/overview?window=${window}`, signal)

export function getJobs(
  limit: number, offset: number, query: string, status: JobStatus | '', signal: AbortSignal,
) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (query) params.set('q', query)
  if (status) params.set('status', status)
  return request<JobPage>(`/monitoring/jobs?${params}`, signal)
}

export const getJobDetails = (id: string, signal: AbortSignal) =>
  request<{ job: Job; attempts: Attempt[] }>(`/monitoring/jobs/${id}`, signal)

export const submitWordCount = (text: string) => request<Job>('/jobs', undefined, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ type: 'word_count', payload: { text } }),
})
