import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { COPIED_FEEDBACK_MS } from '../components/TranscriptEditor'
import {
  apiError,
  createMockClient,
  makeProjectDetail,
  makeScreenshot,
  makeTranscript,
  PROJECT_ID,
  TRANSCRIPT_ID,
  type MockApiClient,
} from '../test/mockClient'
import { renderApp } from '../test/renderApp'

const PATH = `/transcripts/${TRANSCRIPT_ID}`
let client: MockApiClient

beforeEach(() => {
  client = createMockClient()
  client.getTranscription.mockResolvedValue(makeTranscript())
  client.getProject.mockResolvedValue(makeProjectDetail())
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  // The copy tests define navigator.clipboard; remove it so later tests see jsdom's default.
  Reflect.deleteProperty(navigator, 'clipboard')
})

async function renderLoaded() {
  const user = userEvent.setup()
  const view = renderApp(PATH, client)
  await screen.findByLabelText('Title')
  return { user, ...view }
}

describe('TranscriptPage – view and edit (US-08)', () => {
  it('US-08 AC1: shows title, text, language, duration and created date', async () => {
    await renderLoaded()

    expect(screen.getByLabelText('Title')).toHaveValue('Week 1')
    expect(screen.getByLabelText('Text')).toHaveValue('Hola a todos.')
    const details = screen.getByLabelText('Transcript details')
    expect(details).toHaveTextContent('Created2026-11-02')
    expect(details).toHaveTextContent('LanguageSpanish')
    expect(details).toHaveTextContent('Duration2:05')
  })

  it('US-08 AC2: saves edited title and text, sending only the changed fields', async () => {
    client.updateTranscription.mockResolvedValue(
      makeTranscript({ title: 'Week one', text: 'Hola.' }),
    )
    const { user } = await renderLoaded()

    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
    await user.clear(screen.getByLabelText('Title'))
    await user.type(screen.getByLabelText('Title'), 'Week one ')
    await user.clear(screen.getByLabelText('Text'))
    await user.type(screen.getByLabelText('Text'), 'Hola.')
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(client.updateTranscription).toHaveBeenCalledWith(TRANSCRIPT_ID, {
      title: 'Week one',
      text: 'Hola.',
    })
    expect(await screen.findByText('Saved')).toBeInTheDocument()
    expect(screen.getByLabelText('Title')).toHaveValue('Week one')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('US-08 AC2: a blank title shows an error and nothing is saved', async () => {
    const { user } = await renderLoaded()

    await user.clear(screen.getByLabelText('Title'))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Enter a title.')
    expect(client.updateTranscription).not.toHaveBeenCalled()
  })

  it('shows an error when saving fails', async () => {
    client.updateTranscription.mockRejectedValue(apiError(500))
    const { user } = await renderLoaded()

    await user.type(screen.getByLabelText('Text'), '!')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
  })

  it('shows "Transcript not found" for a 404', async () => {
    client.getTranscription.mockRejectedValue(apiError(404, 'Not found', 'not_found'))
    renderApp(PATH, client)

    expect(await screen.findByRole('heading', { name: 'Transcript not found' })).toBeInTheDocument()
  })
})

describe('TranscriptPage – unsaved-changes warning (US-08 AC3)', () => {
  it('asks before in-app navigation and stays when cancelled', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { user, router } = await renderLoaded()

    await user.type(screen.getByLabelText('Text'), ' more')
    await user.click(screen.getByRole('link', { name: 'Lecture notes' }))

    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/unsaved changes/i))
    expect(router.state.location.pathname).toBe(PATH)
    expect(screen.getByLabelText('Text')).toHaveValue('Hola a todos. more')
  })

  it('leaves when the user confirms', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { user, router } = await renderLoaded()

    await user.type(screen.getByLabelText('Text'), ' more')
    await user.click(screen.getByRole('link', { name: 'Lecture notes' }))

    await waitFor(() => expect(router.state.location.pathname).toBe(`/projects/${PROJECT_ID}`))
  })

  it('does not ask when there are no changes', async () => {
    const confirm = vi.spyOn(window, 'confirm')
    const { user, router } = await renderLoaded()

    await user.click(screen.getByRole('link', { name: 'Lecture notes' }))

    expect(confirm).not.toHaveBeenCalled()
    await waitFor(() => expect(router.state.location.pathname).toBe(`/projects/${PROJECT_ID}`))
  })

  it('registers a beforeunload prompt only while there are unsaved changes', async () => {
    const { user } = await renderLoaded()
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false)

    await user.type(screen.getByLabelText('Text'), '!')
    const dirty = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirty)
    expect(dirty.defaultPrevented).toBe(true)
  })
})

describe('TranscriptPage – copy (US-09)', () => {
  it('US-09 AC1: copies the text and shows "Copied" for about 2 s', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    renderApp(PATH, client)
    await screen.findByLabelText('Title')
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    vi.useFakeTimers()

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Copy' })))

    expect(writeText).toHaveBeenCalledWith('Hola a todos.')
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(COPIED_FEEDBACK_MS - 100))
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(100))
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
  })

  it('shows an error when the clipboard is not available', async () => {
    const writeText = vi.fn(() => Promise.reject(new Error('denied')))
    renderApp(PATH, client)
    await screen.findByLabelText('Title')
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Copy' })))

    expect(screen.getByRole('alert')).toHaveTextContent(/could not copy/i)
  })
})

describe('TranscriptPage – download (US-10)', () => {
  it('US-10 AC1/AC2: Download .md and .txt link to the API download endpoint', async () => {
    await renderLoaded()

    const md = screen.getByRole('link', { name: 'Download .md' })
    const txt = screen.getByRole('link', { name: 'Download .txt' })
    expect(md).toHaveAttribute('href', `/api/transcriptions/${TRANSCRIPT_ID}/download?format=md`)
    expect(md).toHaveAttribute('download')
    expect(txt).toHaveAttribute('href', `/api/transcriptions/${TRANSCRIPT_ID}/download?format=txt`)
    expect(txt).toHaveAttribute('download')
  })
})

describe('TranscriptPage – delete (US-11)', () => {
  it('US-11 AC1: deletes after confirmation and returns to the project, even with edits', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    client.deleteTranscription.mockResolvedValue(undefined)
    const { user, router } = await renderLoaded()

    await user.type(screen.getByLabelText('Text'), ' edit')
    await user.click(screen.getByRole('button', { name: 'Delete transcript' }))

    expect(client.deleteTranscription).toHaveBeenCalledWith(TRANSCRIPT_ID)
    await waitFor(() => expect(router.state.location.pathname).toBe(`/projects/${PROJECT_ID}`))
    // Only the delete confirmation; no extra unsaved-changes prompt.
    expect(confirm).toHaveBeenCalledTimes(1)
  })

  it('cancelling the confirmation deletes nothing', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { user, router } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Delete transcript' }))

    expect(client.deleteTranscription).not.toHaveBeenCalled()
    expect(router.state.location.pathname).toBe(PATH)
  })
})

describe('TranscriptPage – linked screenshots (US-14 AC3)', () => {
  it('shows only the screenshots linked to this transcript', async () => {
    client.getProject.mockResolvedValue(
      makeProjectDetail({
        screenshots: [
          makeScreenshot({ id: 's-linked', filename: 'linked.png', transcript_id: TRANSCRIPT_ID }),
          makeScreenshot({ id: 's-other', filename: 'other.png', transcript_id: null }),
        ],
      }),
    )
    await renderLoaded()

    const grid = screen.getByRole('list', { name: 'Linked screenshots' })
    const images = within(grid).getAllByRole('img')
    expect(images).toHaveLength(1)
    expect(images[0]).toHaveAttribute('src', '/api/screenshots/s-linked/image')
    expect(images[0]).toHaveAttribute('alt', 'linked.png')
  })

  it('says so when no screenshots are linked', async () => {
    await renderLoaded()

    expect(screen.getByText(/no screenshots are linked/i)).toBeInTheDocument()
  })
})
