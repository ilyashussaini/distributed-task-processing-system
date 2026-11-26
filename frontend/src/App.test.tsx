import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import type { Job } from './types'

const completed: Job = {
  id: 'a1b2c3d4-1234-4567-9012-abcdef000001',
  type: 'word_count',
  status: 'completed',
  attempts: 2,
  max_attempts: 3,
  result: { word_count: 2 },
  error: null,
  created_at: '2026-04-01T12:00:00Z',
  completed_at: '2026-04-01T12:00:01Z',
  next_attempt_at: null,
}

const overview = {
  generated_at: '2026-04-01T12:01:00Z',
  counts: { total: 14, pending: 2, running: 1, completed: 10, failed: 1 },
  period: {
    submitted: 0, completed: 0, failed: 0, success_rate: null, failure_rate: null,
    retry_attempts: 0, retried_jobs: 0, failed_attempts: 0, abandoned_attempts: 0,
    duration: { samples: 0, average_ms: null, minimum_ms: null, p95_ms: null, maximum_ms: null },
  },
  activity: [],
}

function json(data: unknown) {
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

function mockAPI() {
  const handler = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, 'http://localhost')
    if (url.pathname === '/api/monitoring/overview') return json(overview)
    if (url.pathname === '/api/monitoring/jobs') {
      return json({ total: 12, jobs: [completed] })
    }
    if (url.pathname === `/api/monitoring/jobs/${completed.id}`) {
      return json({
        job: completed,
        attempts: [{
          number: 1, status: 'failed', started_at: completed.created_at,
          finished_at: completed.completed_at, duration_ms: 41, error: 'Transient error.',
        }],
      })
    }
    if (url.pathname === '/api/jobs' && init?.method === 'POST') {
      return json({ ...completed, status: 'pending', attempts: 0, completed_at: null, result: null })
    }
    throw new Error(`Unexpected request ${url.pathname}`)
  })
  vi.stubGlobal('fetch', handler)
  return handler
}

beforeEach(() => history.replaceState(null, '', '/'))
afterEach(() => vi.unstubAllGlobals())

describe('monitoring dashboard', () => {
  it('loads real counters, switches the time range, and shows an honest empty period', async () => {
    const fetchMock = mockAPI()
    render(<App />)
    expect(await screen.findByText('14', { exact: true })).toBeTruthy()
    expect(await screen.findByText('No activity in this range')).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox', { name: 'Time range' }), { target: { value: '1h' } })
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/monitoring/overview?window=1h', expect.anything())
    })
  })

  it('paginates and resets to page one when status or search changes', async () => {
    history.replaceState(null, '', '/#jobs')
    const fetchMock = mockAPI()
    render(<App />)
    const next = await screen.findByRole('button', { name: 'Next page' })
    await waitFor(() => expect((next as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(next)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/monitoring/jobs?limit=10&offset=10', expect.anything())
    })
    fireEvent.change(screen.getByRole('combobox', { name: 'Filter by status' }), { target: { value: 'completed' } })
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'word count' } })
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/monitoring/jobs?limit=10&offset=0&q=word+count&status=completed', expect.anything())
    })
    expect(screen.getByText('Page 1')).toBeTruthy()

    fireEvent.click(await screen.findByRole('button', { name: 'Inspect job a1b2c3d4' }))
    const details = await screen.findByRole('dialog', { name: 'Job details' })
    expect(await within(details).findByText('Transient error.')).toBeTruthy()
    expect(within(details).getByText('41 ms')).toBeTruthy()
  })

  it('submits word-count input and opens its details after the API accepts it', async () => {
    const fetchMock = mockAPI()
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'New job' }))
    const dialog = screen.getByRole('dialog', { name: 'Submit a job' })
    const submit = within(dialog).getByRole('button', { name: 'Submit job' })
    expect((submit as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Text to count' }), { target: { value: 'two words' } })
    fireEvent.click(submit)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.objectContaining({
        method: 'POST', body: JSON.stringify({ type: 'word_count', payload: { text: 'two words' } }),
      }))
    })
    expect(await screen.findByRole('dialog', { name: 'Job details' })).toBeTruthy()
  })

  it('distinguishes an unavailable backend from an empty queue', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 502 })))
    render(<App />)
    expect((await screen.findAllByText('Disconnected from the API')).length).toBeGreaterThan(0)
    expect(screen.queryByText('No jobs yet')).toBeNull()
  })
})
