import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { createMockClient } from './test/mockClient'
import { renderApp } from './test/renderApp'

describe('App shell and routes', () => {
  it('shows the brand header and the projects page at /', async () => {
    const client = createMockClient()
    client.listProjects.mockResolvedValue([])

    renderApp('/', client)

    expect(screen.getByRole('link', { name: /EchoNotes/ })).toHaveAttribute('href', '/')
    expect(screen.getByText('Turn audio into organized text notes.')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument()
  })

  it('shows a not-found page for unknown routes', () => {
    renderApp('/nope')

    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
