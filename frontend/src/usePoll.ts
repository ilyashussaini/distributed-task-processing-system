import { useEffect, useState } from 'react'
import { RequestError } from './api'

export const POLL_INTERVAL = 5000
type PollStatus = 'loading' | 'ready' | 'disconnected' | 'error'

export interface PollState<T> {
  data: T | null
  status: PollStatus
  error: string | null
  updatedAt: number | null
}

const empty = { data: null, status: 'loading', error: null, updatedAt: null } as const

export function usePoll<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
  interval: number | null = POLL_INTERVAL,
) {
  const [record, setRecord] = useState<{ key: string; state: PollState<T> }>()
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let next: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const data = await load(controller.signal)
        if (controller.signal.aborted) return
        setRecord({ key, state: { data, status: 'ready', error: null, updatedAt: Date.now() } })
      } catch (error) {
        if (controller.signal.aborted) return
        setRecord((previous) => ({
          key,
          state: {
            ...(previous?.key === key ? previous.state : empty),
            status: error instanceof RequestError && error.disconnected ? 'disconnected' : 'error',
            error: error instanceof Error ? error.message : 'Something went wrong.',
          },
        }))
      } finally {
        if (!controller.signal.aborted && interval !== null) next = setTimeout(poll, interval)
      }
    }
    void poll()
    return () => {
      clearTimeout(next)
      controller.abort()
    }
  }, [enabled, interval, key, load, revision])

  return {
    ...(record?.key === key ? record.state : empty),
    refresh: () => setRevision((previous) => previous + 1),
  }
}
