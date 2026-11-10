import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { createApiClient } from '../api/client'
import type { Health } from '../api/types'
import { createMockClient } from '../test/mockClient'
import { renderApp } from '../test/renderApp'
import { formatBuildInfo } from '../lib/format'

const FULL_SHA = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'

function makeHealth(overrides: Partial<Health> = {}): Health {
  return {
    status: 'ok',
    version: '0.1.0',
    database: 'ok',
    commit: FULL_SHA,
    environment: 'dev',
    ...overrides,
  }
}

function healthResponse(status: number, body: Health): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Real API client over a mocked `fetch`: /api/health answers `health`, the project list `[]`. */
function clientWithFetch(health: Response | Error) {
  const real = createApiClient('', (input: string) => {
    if (input === '/api/health') {
      return health instanceof Error ? Promise.reject(health) : Promise.resolve(health)
    }
    return Promise.resolve(new Response('[]', { status: 200 }))
  })
  const client = createMockClient()
  client.getHealth.mockImplementation(real.getHealth)
  client.listProjects.mockImplementation(real.listProjects)
  return client
}

describe('AppFooter (US-17 AC4)', () => {
  it('US-17 AC4: shows version, 7-char short commit and environment from /api/health', async () => {
    renderApp('/', clientWithFetch(healthResponse(200, makeHealth())))

    expect(await screen.findByText('v0.1.0 · a1b2c3d · dev')).toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toHaveTextContent('v0.1.0 · a1b2c3d · dev')
  })

  it('US-17 AC4: shows "unknown" when the commit is unknown', async () => {
    const health = makeHealth({ commit: 'unknown', environment: 'local' })
    renderApp('/', clientWithFetch(healthResponse(200, health)))

    expect(await screen.findByText('v0.1.0 · unknown · local')).toBeInTheDocument()
  })

  it('still shows the build info when health is degraded (503 with a body)', async () => {
    const health = makeHealth({ status: 'degraded', database: 'error', environment: 'prod' })
    renderApp('/', clientWithFetch(healthResponse(503, health)))

    expect(await screen.findByText('v0.1.0 · a1b2c3d · prod')).toBeInTheDocument()
  })

  it('degrades gracefully when /api/health is unreachable: no footer, page still renders', async () => {
    const client = clientWithFetch(new TypeError('Failed to fetch'))
    renderApp('/', client)

    expect(await screen.findByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument()
    await waitFor(() => expect(client.getHealth).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument()
  })

  it('degrades gracefully when /api/health returns a non-JSON error page', async () => {
    const client = clientWithFetch(new Response('<html>Bad gateway</html>', { status: 502 }))
    renderApp('/', client)

    expect(await screen.findByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument()
    await waitFor(() => expect(client.getHealth).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument()
  })
})

describe('formatBuildInfo', () => {
  it('shortens a full SHA to 7 characters', () => {
    expect(formatBuildInfo(makeHealth())).toBe('v0.1.0 · a1b2c3d · dev')
  })

  it('keeps "unknown" and treats an empty commit as unknown', () => {
    expect(formatBuildInfo(makeHealth({ commit: 'unknown' }))).toBe('v0.1.0 · unknown · dev')
    expect(formatBuildInfo(makeHealth({ commit: '' }))).toBe('v0.1.0 · unknown · dev')
  })
})
