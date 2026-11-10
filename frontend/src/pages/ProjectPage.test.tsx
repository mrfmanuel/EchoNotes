import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  apiError,
  createMockClient,
  makeProject,
  makeProjectDetail,
  makeScreenshot,
  makeTranscript,
  PROJECT_ID,
  type MockApiClient,
} from '../test/mockClient'
import { renderApp } from '../test/renderApp'

const PATH = `/projects/${PROJECT_ID}`
let client: MockApiClient

beforeEach(() => {
  client = createMockClient()
  client.getProject.mockResolvedValue(makeProjectDetail())
  client.listProjects.mockResolvedValue([])
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ProjectPage – content', () => {
  it('lists the transcripts with title, date, language and duration', async () => {
    client.getProject.mockResolvedValue(
      makeProjectDetail({ transcripts: [makeTranscript({ id: 't9', title: 'Week 1' })] }),
    )
    renderApp(PATH, client)

    const list = await screen.findByRole('list', { name: 'Transcripts' })
    const link = within(list).getByRole('link', { name: 'Week 1' })
    expect(link).toHaveAttribute('href', '/transcripts/t9')
    expect(list).toHaveTextContent('2026-11-02 · Spanish · 2:05')
  })

  it('shows an empty state when the project has no transcripts', async () => {
    renderApp(PATH, client)

    expect(await screen.findByText(/no transcripts yet/i)).toBeInTheDocument()
  })

  it('keeps a placeholder section for the PR-G screenshot gallery and export', async () => {
    client.getProject.mockResolvedValue(makeProjectDetail({ screenshots: [makeScreenshot()] }))
    renderApp(PATH, client)

    expect(await screen.findByRole('heading', { name: 'Screenshots' })).toBeInTheDocument()
    expect(screen.getByText(/1 screenshot in this project/)).toBeInTheDocument()
  })

  it('shows "Project not found" for a 404', async () => {
    client.getProject.mockRejectedValue(apiError(404, 'Project not found', 'not_found'))
    renderApp(PATH, client)

    expect(await screen.findByRole('heading', { name: 'Project not found' })).toBeInTheDocument()
  })
})

describe('ProjectPage – rename (US-03)', () => {
  it('US-03 AC1: renames inline with a trimmed name and shows the new name', async () => {
    client.renameProject.mockResolvedValue(makeProject({ name: 'Renamed' }))
    const user = userEvent.setup()
    renderApp(PATH, client)

    await user.click(await screen.findByRole('button', { name: 'Rename' }))
    const input = screen.getByLabelText('Project name')
    await user.clear(input)
    await user.type(input, '  Renamed ')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(client.renameProject).toHaveBeenCalledWith(PROJECT_ID, { name: 'Renamed' })
    expect(await screen.findByRole('heading', { level: 1, name: 'Renamed' })).toBeInTheDocument()
  })

  it('US-03 AC2: an invalid name shows the US-01 validation and calls nothing', async () => {
    const user = userEvent.setup()
    renderApp(PATH, client)

    await user.click(await screen.findByRole('button', { name: 'Rename' }))
    await user.clear(screen.getByLabelText('Project name'))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Enter a project name.')
    expect(client.renameProject).not.toHaveBeenCalled()
  })

  it('US-03 AC2: shows an API 422 as a field error', async () => {
    client.renameProject.mockRejectedValue(apiError(422, 'Name too long', 'validation_error'))
    const user = userEvent.setup()
    renderApp(PATH, client)

    await user.click(await screen.findByRole('button', { name: 'Rename' }))
    await user.type(screen.getByLabelText('Project name'), '!')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Name too long')
  })

  it('cancel leaves rename mode without saving', async () => {
    const user = userEvent.setup()
    renderApp(PATH, client)

    await user.click(await screen.findByRole('button', { name: 'Rename' }))
    await user.type(screen.getByLabelText('Project name'), ' changed')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.getByRole('heading', { level: 1, name: 'Lecture notes' })).toBeInTheDocument()
    expect(client.renameProject).not.toHaveBeenCalled()
  })
})

describe('ProjectPage – delete (US-04)', () => {
  it('US-04 AC1: deletes after confirmation and returns to the list', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    client.deleteProject.mockResolvedValue(undefined)
    const user = userEvent.setup()
    const { router } = renderApp(PATH, client)

    await user.click(await screen.findByRole('button', { name: 'Delete project' }))

    expect(window.confirm).toHaveBeenCalled()
    expect(client.deleteProject).toHaveBeenCalledWith(PROJECT_ID)
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })

  it('US-04 AC2: cancelling the confirmation deletes nothing', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    const { router } = renderApp(PATH, client)

    await user.click(await screen.findByRole('button', { name: 'Delete project' }))

    expect(client.deleteProject).not.toHaveBeenCalled()
    expect(router.state.location.pathname).toBe(PATH)
    expect(screen.getByRole('heading', { level: 1, name: 'Lecture notes' })).toBeInTheDocument()
  })
})

describe('ProjectPage – upload opens the new transcript (US-05 AC1)', () => {
  it('navigates to the transcript after a successful upload', async () => {
    client.createTranscription.mockResolvedValue(makeTranscript({ id: 'created' }))
    client.getTranscription.mockResolvedValue(makeTranscript({ id: 'created' }))
    const user = userEvent.setup()
    const { router } = renderApp(PATH, client)

    await user.upload(
      await screen.findByLabelText('Audio file'),
      new File(['abc'], 'talk.mp3', { type: 'audio/mpeg' }),
    )
    await user.click(screen.getByRole('button', { name: 'Upload and transcribe' }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/transcripts/created'))
  })
})
