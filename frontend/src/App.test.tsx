import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App placeholder page', () => {
  it('shows the product name and tagline', () => {
    render(<App />)

    expect(screen.getByRole('heading', { level: 1, name: 'EchoNotes' })).toBeInTheDocument()
    expect(screen.getByText('Turn audio into organized text notes.')).toBeInTheDocument()
  })

  it('lists the planned features', () => {
    render(<App />)

    expect(screen.getAllByRole('listitem')).toHaveLength(5)
  })
})
