import type { ActivityBucket, Attempt, Job, JobStatus, Overview, TimeWindow } from './types'

export const isDemoMode = () => import.meta.env.VITE_TASKFLOW_DEMO === 'true'

const minute = 60_000
const hour = 60 * minute
const snapshot = Date.UTC(2026, 10, 20, 16)
const iso = (time: number) => new Date(time).toISOString()
const ranges: Record<TimeWindow, [number, number]> = {
  '1h': [5 * minute, 12], '24h': [hour, 24], '7d': [24 * hour, 7], '30d': [24 * hour, 30],
}

function example(index: number): { job: Job; attempts: Attempt[] } {
  const created = snapshot - (index * 29 + index % 4 * 6 + 2) * minute
  const csv = index % 3 !== 1
  const status: JobStatus = index === 0 ? 'running' : index === 1 ? 'pending'
    : index % 8 === 2 ? 'failed' : 'completed'
  const error = csv ? 'Row 9 has an invalid quantity.' : 'Text must contain at least one word.'
  const retried = status === 'completed' && index % 5 === 0
  const count = status === 'pending' ? 0 : retried ? 2 : 1
  const attempts: Attempt[] = Array.from({ length: count }, (_, attempt) => {
    const started = created + 700 + 150 * (index % 7) + attempt * 2400
    const duration = (csv ? 410 : 170) + 65 * (index % 9)
    const attemptStatus = retried && attempt === 0 ? 'failed' : status
    return {
      number: attempt + 1,
      status: attemptStatus === 'pending' ? 'running' : attemptStatus,
      started_at: iso(started),
      finished_at: attemptStatus === 'running' ? null : iso(started + duration),
      duration_ms: attemptStatus === 'running' ? null : duration,
      error: attemptStatus === 'failed' ? (retried ? 'Handler process exited unexpectedly.' : error) : null,
    }
  })
  const result = csv ? {
    orders: 4, units_sold: 10, revenue: '105.71', average_order_value: '26.43',
    regions: [
      { region: 'North', orders: 1, units_sold: 1, revenue: '35.25' },
      { region: 'South, East', orders: 1, units_sold: 4, revenue: '19.96' },
      { region: 'West', orders: 2, units_sold: 5, revenue: '50.50' },
    ],
  } : { word_count: 20 + index }
  return {
    job: {
      id: `${(0xaf400000 + index * 12391).toString(16)}-0d00-4000-8100-${String(index).padStart(12, '0')}`,
      type: csv ? 'csv_sales_summary' : 'word_count',
      status, attempts: count, max_attempts: 3,
      result: status === 'completed' ? result : null,
      error: status === 'failed' ? error : null,
      created_at: iso(created),
      completed_at: attempts.at(-1)?.finished_at ?? null,
      next_attempt_at: status === 'pending' ? iso(snapshot + minute) : null,
    },
    attempts,
  }
}

const examples = Array.from({ length: 38 }, (_, index) => example(index))

export function demoJobs(limit: number, offset: number, query: string, status: JobStatus | '') {
  const needle = query.trim().toLowerCase()
  const matching = examples.map(({ job }) => job).filter((job) =>
    (!status || job.status === status)
    && `${job.id} ${job.type} ${job.type.replaceAll('_', ' ')}`.includes(needle),
  )
  return { jobs: matching.slice(offset, offset + limit), total: matching.length }
}

export function demoDetails(id: string) {
  return examples.find(({ job }) => job.id === id)
}

export function demoOverview(window: TimeWindow): Overview {
  const [step, size] = ranges[window]
  const start = snapshot - step * size
  const from = (date: string) => Math.floor((Date.parse(date) - start) / step)
  const activity: ActivityBucket[] = Array.from({ length: size }, (_, index) =>
    ({ start: iso(start + step * index), submitted: 0, completed: 0, failed: 0 }),
  )
  const counts = { total: examples.length, pending: 0, running: 0, completed: 0, failed: 0 }
  const durations: number[] = []
  let retryCount = 0
  let failedAttempts = 0
  for (const { job, attempts } of examples) {
    counts[job.status]++
    const submitted = activity[from(job.created_at)]
    if (submitted) submitted.submitted++
    if (job.completed_at) {
      const finished = activity[from(job.completed_at)]
      if (finished && (job.status === 'completed' || job.status === 'failed')) finished[job.status]++
    }
    for (const attempt of attempts) {
      if (!activity[from(attempt.started_at)]) continue
      if (attempt.number > 1) retryCount++
      if (attempt.status === 'failed') failedAttempts++
      if (attempt.duration_ms !== null) durations.push(attempt.duration_ms)
    }
  }
  const completed = activity.reduce((sum, row) => sum + row.completed, 0)
  const failed = activity.reduce((sum, row) => sum + row.failed, 0)
  const terminal = completed + failed
  const sorted = durations.sort((left, right) => left - right)
  return {
    generated_at: iso(snapshot),
    counts,
    activity,
    period: {
      submitted: activity.reduce((sum, row) => sum + row.submitted, 0),
      completed, failed,
      success_rate: terminal ? completed / terminal : null,
      failure_rate: terminal ? failed / terminal : null,
      retry_attempts: retryCount, retried_jobs: retryCount, failed_attempts: failedAttempts, abandoned_attempts: 0,
      duration: {
        samples: sorted.length,
        average_ms: sorted.length ? sorted.reduce((sum, value) => sum + value, 0) / sorted.length : null,
        minimum_ms: sorted[0] ?? null,
        p95_ms: sorted[Math.ceil(sorted.length * .95) - 1] ?? null,
        maximum_ms: sorted.at(-1) ?? null,
      },
    },
  }
}
