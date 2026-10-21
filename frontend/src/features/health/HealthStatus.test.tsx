import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '@/lib/query-client'
import { HealthStatus } from '@/features/health/HealthStatus'

function renderWithClient() {
  const client = createQueryClient()
  client.setDefaultOptions({ queries: { retry: false } })
  return render(
    <QueryClientProvider client={client}>
      <HealthStatus />
    </QueryClientProvider>,
  )
}

describe('HealthStatus', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows ok when backend and database are healthy', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ status: 'ok', db: 'ok' })))
    renderWithClient()
    expect(await screen.findAllByText('ok')).toHaveLength(2)
  })

  it('shows unavailable when the backend is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 502 })))
    renderWithClient()
    expect(await screen.findAllByText('unavailable')).toHaveLength(2)
  })
})
