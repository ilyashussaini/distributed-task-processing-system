import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { RequestError } from './api'
import { POLL_INTERVAL, usePoll } from './usePoll'

afterEach(() => vi.useRealTimers())

it('refreshes on an interval and retains stale data during a disconnect', async () => {
  vi.useFakeTimers()
  const load = vi.fn()
    .mockResolvedValueOnce('pending')
    .mockRejectedValueOnce(new RequestError('Backend unavailable.', true))
    .mockResolvedValue('completed')

  const { result, unmount } = renderHook(() => usePoll('job', load))
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(result.current).toMatchObject({ data: 'pending', status: 'ready' })

  await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL) })
  expect(result.current).toMatchObject({ data: 'pending', status: 'disconnected' })

  await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL) })
  expect(result.current).toMatchObject({ data: 'completed', status: 'ready' })

  unmount()
  await vi.advanceTimersByTimeAsync(POLL_INTERVAL)
  expect(load).toHaveBeenCalledTimes(3)
})
