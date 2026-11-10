import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { apiError, createMockClient, makeProject, makeProjectDetail, type MockApiClient } from '../test/mockClient'
import { renderApp } from '../test/renderApp'

let client: MockApiClient

beforeEach(() => {
  client = createMockClient()
  client.listProjects.mockResolvedValue([])
  client.getProject.mockResolvedValue(makeProjectDetail({ id: 'new-id', name: 'Fresh' }))
})

describe('ProjectsPage – list (US-02)', () => {
  it('US-02 AC1: lists projects newest update first with transcript and screenshot counts', async () => {
    client.listProjects.mockResolvedValue([
      makeProject({ id: 'old', name: 'Old', updated_at: '2026-10-01T00:00:00Z' }),
      makeProject({
        id: 'new',
        name: 'New',
        transcript_count: 3,
        screenshot_count: 1,
        updated_at: '2026-11-09T00:00:00Z',
      }),
    ])

    renderApp('/', client)

    const list = await screen.findByRole('list', { name: 'Projects' })
    const items = within(list).getAllByRole('listitem')
    expect(items.map((item) => within(item).getByRole('link').textContent)).toEqual(['New', 'Old'])
    expect(items[0]).toHaveTextContent('3 transcripts · 1 screenshot')
    expect(within(items[0]).getByRole('link')).toHaveAttribute('href', '/projects/new')
  })

  it('US-02 AC2: shows an empty state inviting to create a project', async () => {
    renderApp('/', client)

    expect(await screen.findByRole('heading', { name: 'No projects yet' })).toBeInTheDocument()
    expect(screen.getByText(/create your first project/i)).toBeInTheDocument()
  })

  it('shows an error with a retry button when loading fails', async () => {
    client.listProjects.mockRejectedValueOnce(apiError(500))
    const user = userEvent.setup()

    renderApp('/', client)

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('No projects yet')).toBeInTheDocument()
    expect(client.listProjects).toHaveBeenCalledTimes(2)
  })
})

describe('ProjectsPage – create (US-01)', () => {
  it('US-01 AC1: creates the project with a trimmed name and opens its page', async () => {
    client.createProject.mockResolvedValue(makeProject({ id: 'new-id', name: 'Fresh' }))
    const user = userEvent.setup()
    const { router } = renderApp('/', client)

    await user.type(await screen.findByLabelText('New project name'), '  Fresh  ')
    await user.click(screen.getByRole('button', { name: 'Create project' }))

    expect(client.createProject).toHaveBeenCalledWith({ name: 'Fresh' })
    await waitFor(() => expect(router.state.location.pathname).toBe('/projects/new-id'))
  })

  it('US-01 AC2: rejects a whitespace-only name without calling the API', async () => {
    const user = userEvent.setup()
    renderApp('/', client)

    await user.type(await screen.findByLabelText('New project name'), '   ')
    await user.click(screen.getByRole('button', { name: 'Create project' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Enter a project name.')
    expect(screen.getByLabelText('New project name')).toHaveAttribute('aria-invalid', 'true')
    expect(client.createProject).not.toHaveBeenCalled()
  })

  it('US-01 AC2: rejects a name longer than 100 characters without calling the API', async () => {
    const user = userEvent.setup()
    renderApp('/', client)

    const input = await screen.findByLabelText('New project name')
    await user.click(input)
    await user.paste('a'.repeat(101))
    await user.click(screen.getByRole('button', { name: 'Create project' }))

    expect(screen.getByRole('alert')).toHaveTextContent('at most 100 characters')
    expect(client.createProject).not.toHaveBeenCalled()
  })

  it('US-01 AC2: shows an API 422 as a field error', async () => {
    client.createProject.mockRejectedValue(
      apiError(422, 'Name must not be blank', 'validation_error'),
    )
    const user = userEvent.setup()
    renderApp('/', client)

    await user.type(await screen.findByLabelText('New project name'), 'Valid')
    await user.click(screen.getByRole('button', { name: 'Create project' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Name must not be blank')
  })
})
