import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { submitCsv, submitWordCount } from './api'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

it('opens sample jobs and rejects both submission paths without a network request', async () => {
  vi.stubEnv('VITE_TASKFLOW_DEMO', 'true')
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  history.replaceState(null, '', '/#jobs')
  render(<App />)
  expect(screen.getByText('Read-only demo')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'New job' })).toBeNull()
  fireEvent.change(screen.getByRole('combobox', { name: 'Filter by status' }), { target: { value: 'failed' } })
  const rows = await screen.findAllByRole('button', { name: /Inspect job/ })
  fireEvent.click(rows[0])
  const dialog = await screen.findByRole('dialog', { name: 'Job details' })
  expect(await within(dialog).findByText('Last error')).toBeTruthy()
  await expect(submitWordCount('example')).rejects.toThrow('read-only')
  await expect(submitCsv(new File(['data'], 'sample.csv'))).rejects.toThrow('read-only')
  expect(fetch).not.toHaveBeenCalled()
})
