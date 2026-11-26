export type JobStatus = 'pending' | 'running' | 'completed' | 'failed'
export type TimeWindow = '1h' | '24h' | '7d' | '30d'
export type View = 'overview' | 'jobs' | 'analytics'

export interface Job {
  id: string
  type: string
  status: JobStatus
  attempts: number
  max_attempts: number
  result: Record<string, unknown> | null
  error: string | null
  created_at: string
  completed_at: string | null
  next_attempt_at: string | null
}

export interface JobPage {
  jobs: Job[]
  total: number
}

export interface Attempt {
  number: number
  status: JobStatus | 'abandoned'
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  error: string | null
}

export interface ActivityBucket {
  start: string
  submitted: number
  completed: number
  failed: number
}

export interface Overview {
  generated_at: string
  counts: Record<JobStatus | 'total', number>
  period: {
    submitted: number
    completed: number
    failed: number
    success_rate: number | null
    failure_rate: number | null
    retry_attempts: number
    retried_jobs: number
    failed_attempts: number
    abandoned_attempts: number
    duration: {
      samples: number
      average_ms: number | null
      minimum_ms: number | null
      p95_ms: number | null
      maximum_ms: number | null
    }
  }
  activity: ActivityBucket[]
}
