import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiProvider } from '../api/ApiProvider'
import type { Summary, SummaryErrorCode } from '../api/types'
import {
  apiError,
  createMockClient,
  makeSummary,
  PROJECT_ID,
  SUMMARY_ID,
  type MockApiClient,
} from '../test/mockClient'
import { SUMMARY_POLL_MS, SummaryPanel } from './SummaryPanel'

const HTML = '<!doctype html><html><body><h1>Week 1 summary</h1></body></html>'
const NEW_ID = '55555555-5555-4555-8555-555555555555'
let client: MockApiClient

beforeEach(() => {
  client = createMockClient()
  vi.useFakeTimers()
})

function renderPanel(transcriptCount = 1) {
  return render(
    <ApiProvider client={client}>
      <SummaryPanel projectId={PROJECT_ID} transcriptCount={transcriptCount} />
    </ApiProvider>,
  )
}

/** Lets pending promises (API mocks) settle and React re-render. */
async function flush(): Promise<void> {
  await act(async () => {})
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

async function click(element: HTMLElement): Promise<void> {
  await act(async () => {
    fireEvent.click(element)
  })
}

function generateButton(): HTMLElement {
  return screen.getByRole('button', { name: /generate summary|generating…/i })
}

function succeeded(overrides: Partial<Summary> = {}): Summary {
  return makeSummary({
    status: 'succeeded',
    provider: 'gemini',
    model: 'gemini-3.8-flash',
    started_at: '2026-11-11T10:00:01Z',
    finished_at: '2026-11-11T10:00:20Z',
    html: HTML,
    ...overrides,
  })
}

/** Mount resolves `onMount`; the following polls resolve `polls` in order (the last repeats). */
function latestSequence(onMount: Summary | null, ...polls: (Summary | null)[]): void {
  client.getLatestSummary.mockResolvedValueOnce(onMount)
  polls.forEach((summary, index) => {
    if (index === polls.length - 1) client.getLatestSummary.mockResolvedValue(summary)
    else client.getLatestSummary.mockResolvedValueOnce(summary)
  })
}

describe('SummaryPanel – button state (US-22 AC6, AC7)', () => {
  it('AC6: is disabled with an explanatory tooltip when the project has 0 transcripts', async () => {
    renderPanel(0)
    await flush()

    const button = screen.getByRole('button', { name: 'Generate summary' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', 'Add at least one transcript to generate a summary.')
    expect(button).toHaveAccessibleDescription(
      'Add at least one transcript to generate a summary.',
    )
  })

  it('AC6: is enabled when the project has at least one transcript', async () => {
    renderPanel(1)
    await flush()

    const button = screen.getByRole('button', { name: 'Generate summary' })
    expect(button).toBeEnabled()
    expect(button).not.toHaveAttribute('title')
  })

  it('AC7: clicking POSTs and shows a disabled "Generating…" button', async () => {
    client.startSummary.mockResolvedValue(makeSummary({ status: 'pending' }))
    renderPanel()
    await flush()

    await click(generateButton())

    expect(client.startSummary).toHaveBeenCalledWith(PROJECT_ID)
    const button = screen.getByRole('button', { name: 'Generating…' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
  })

  it('AC7: opening a project whose latest summary is running resumes "Generating…"', async () => {
    latestSequence(makeSummary({ status: 'running' }))
    renderPanel()
    await flush()

    expect(screen.getByRole('button', { name: 'Generating…' })).toBeDisabled()
    expect(client.startSummary).not.toHaveBeenCalled()
  })

  it('AC1: shows a clear message when the API answers 409 no_transcripts', async () => {
    client.startSummary.mockRejectedValue(apiError(409, 'No transcripts', 'no_transcripts'))
    renderPanel()
    await flush()

    await click(generateButton())

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Add at least one transcript before generating a summary.',
    )
    expect(screen.getByRole('button', { name: 'Generate summary' })).toBeEnabled()
  })
})

describe('SummaryPanel – polling (US-22 AC8)', () => {
  it('polls latest every 3 s while pending/running and stops at succeeded', async () => {
    client.startSummary.mockResolvedValue(makeSummary({ status: 'pending' }))
    latestSequence(null, makeSummary({ status: 'running' }), succeeded())
    renderPanel()
    await flush()
    expect(client.getLatestSummary).toHaveBeenCalledTimes(1) // on mount

    await click(generateButton())
    await advance(SUMMARY_POLL_MS - 1)
    expect(client.getLatestSummary).toHaveBeenCalledTimes(1)
    await advance(1)
    expect(client.getLatestSummary).toHaveBeenCalledTimes(2) // running
    expect(screen.getByRole('button', { name: 'Generating…' })).toBeDisabled()

    await advance(SUMMARY_POLL_MS)
    expect(client.getLatestSummary).toHaveBeenCalledTimes(3) // succeeded
    expect(client.getLatestSummary).toHaveBeenLastCalledWith(PROJECT_ID)
    expect(screen.getByRole('button', { name: 'Generate summary' })).toBeEnabled()

    await advance(SUMMARY_POLL_MS * 5)
    expect(client.getLatestSummary).toHaveBeenCalledTimes(3)
  })

  it('stops polling at failed', async () => {
    latestSequence(
      makeSummary({ status: 'running' }),
      makeSummary({ status: 'failed', error_code: 'provider_error' }),
    )
    renderPanel()
    await flush()

    await advance(SUMMARY_POLL_MS)
    expect(client.getLatestSummary).toHaveBeenCalledTimes(2)
    await advance(SUMMARY_POLL_MS * 5)
    expect(client.getLatestSummary).toHaveBeenCalledTimes(2)
  })

  it('stops polling on unmount', async () => {
    latestSequence(makeSummary({ status: 'running' }), makeSummary({ status: 'running' }))
    const { unmount } = renderPanel()
    await flush()
    await advance(SUMMARY_POLL_MS)
    expect(client.getLatestSummary).toHaveBeenCalledTimes(2)

    unmount()
    await advance(SUMMARY_POLL_MS * 5)

    expect(client.getLatestSummary).toHaveBeenCalledTimes(2)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('keeps polling after a failed poll request (e.g. a network blip)', async () => {
    client.getLatestSummary
      .mockResolvedValueOnce(makeSummary({ status: 'running' }))
      .mockRejectedValueOnce(apiError(0, 'Could not reach the server.'))
      .mockResolvedValue(succeeded())
    renderPanel()
    await flush()

    await advance(SUMMARY_POLL_MS)
    expect(screen.getByRole('button', { name: 'Generating…' })).toBeDisabled()
    await advance(SUMMARY_POLL_MS)

    expect(client.getLatestSummary).toHaveBeenCalledTimes(3)
    expect(screen.getByRole('button', { name: 'Generate summary' })).toBeEnabled()
  })
})

describe('SummaryPanel – failed state (US-22 AC9)', () => {
  it.each<[SummaryErrorCode | null, string]>([
    ['provider_timeout', 'The AI provider took too long. Try again.'],
    ['provider_error', 'The AI provider failed or is busy. Try again in a minute.'],
    ['interrupted', 'Generation was interrupted (the server restarted). Try again.'],
    [
      'internal_error',
      'The summary could not be generated because of an unexpected error. Try again.',
    ],
    [null, 'The summary could not be generated because of an unexpected error. Try again.'],
  ])('error_code %s shows a friendly message', async (code, message) => {
    latestSequence(makeSummary({ status: 'failed', error_code: code }))
    renderPanel()
    await flush()

    // The whole message is the friendly text: no raw error_code or provider text is shown.
    const alert = screen.getByRole('alert')
    expect(within(alert).getByText(message).textContent).toBe(message)
    expect(alert).toHaveTextContent(`${message}Retry`)
  })

  it('Retry POSTs again and shows "Generating…"', async () => {
    latestSequence(makeSummary({ status: 'failed', error_code: 'provider_error' }))
    client.startSummary.mockResolvedValue(makeSummary({ id: NEW_ID, status: 'pending' }))
    renderPanel()
    await flush()

    await click(screen.getByRole('button', { name: 'Retry' }))

    expect(client.startSummary).toHaveBeenCalledTimes(1)
    expect(client.startSummary).toHaveBeenCalledWith(PROJECT_ID)
    expect(screen.getByRole('button', { name: 'Generating…' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })
})

describe('SummaryPanel – succeeded summary (US-22 AC10, AC11, AC5)', () => {
  it('AC10: View summary renders the HTML in an iframe sandbox without scripts or same-origin', async () => {
    latestSequence(succeeded())
    renderPanel()
    await flush()

    const toggle = screen.getByRole('button', { name: 'View summary' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const frame = screen.getByTitle('Project summary')
    expect(frame.tagName).toBe('IFRAME')
    expect(frame).toHaveAttribute('sandbox')
    const sandbox = frame.getAttribute('sandbox') ?? ''
    expect(sandbox).not.toContain('allow-scripts')
    expect(sandbox).not.toContain('allow-same-origin')
    expect(frame).toHaveAttribute('srcdoc', HTML)
    expect(frame).not.toHaveAttribute('src')

    await click(toggle)
    expect(screen.queryByTitle('Project summary')).not.toBeInTheDocument()
  })

  it('AC11: the Download summary.html link points to the download endpoint', async () => {
    latestSequence(succeeded())
    renderPanel()
    await flush()

    const link = screen.getByRole('link', { name: 'Download summary.html' })
    expect(link).toHaveAttribute(
      'href',
      `/api/projects/${PROJECT_ID}/summaries/${SUMMARY_ID}/download`,
    )
    expect(link).toHaveAttribute('download', 'summary.html')
  })

  it('shows provider, model, counts and a truncation badge', async () => {
    latestSequence(succeeded({ truncated: true, transcript_count: 2, image_count: 1 }))
    renderPanel()
    await flush()

    expect(screen.getByText(/gemini \(gemini-3\.8-flash\)/)).toHaveTextContent(
      'Summary from 2026-11-11 · gemini (gemini-3.8-flash) · 2 transcripts, 1 screenshot',
    )
    expect(screen.getByText('Truncated content')).toBeInTheDocument()
  })

  it('opens the viewer automatically when a job I watched succeeds', async () => {
    latestSequence(makeSummary({ status: 'running' }), succeeded())
    renderPanel()
    await flush()
    expect(screen.queryByTitle('Project summary')).not.toBeInTheDocument()

    await advance(SUMMARY_POLL_MS)

    expect(screen.getByTitle('Project summary')).toHaveAttribute('srcdoc', HTML)
  })

  it('AC5: the old summary stays visible while regenerating and is replaced on success', async () => {
    const newHtml = '<!doctype html><p>New</p>'
    latestSequence(
      succeeded(),
      makeSummary({ id: NEW_ID, status: 'running' }),
      succeeded({ id: NEW_ID, html: newHtml }),
    )
    client.startSummary.mockResolvedValue(makeSummary({ id: NEW_ID, status: 'pending' }))
    renderPanel()
    await flush()

    await click(screen.getByRole('button', { name: 'Generate summary' }))
    await advance(SUMMARY_POLL_MS)

    expect(screen.getByRole('button', { name: 'Generating…' })).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Download summary.html' })).toHaveAttribute(
      'href',
      `/api/projects/${PROJECT_ID}/summaries/${SUMMARY_ID}/download`,
    )

    await advance(SUMMARY_POLL_MS)

    expect(screen.getByRole('link', { name: 'Download summary.html' })).toHaveAttribute(
      'href',
      `/api/projects/${PROJECT_ID}/summaries/${NEW_ID}/download`,
    )
    expect(screen.getByTitle('Project summary')).toHaveAttribute('srcdoc', newHtml)
  })

  it('AC5: the old summary stays available when the regeneration fails', async () => {
    latestSequence(
      succeeded(),
      makeSummary({ id: NEW_ID, status: 'failed', error_code: 'provider_timeout' }),
    )
    client.startSummary.mockResolvedValue(makeSummary({ id: NEW_ID, status: 'pending' }))
    renderPanel()
    await flush()

    await click(screen.getByRole('button', { name: 'Generate summary' }))
    await advance(SUMMARY_POLL_MS)

    expect(screen.getByRole('alert')).toHaveTextContent('The AI provider took too long.')
    expect(screen.getByRole('link', { name: 'Download summary.html' })).toHaveAttribute(
      'href',
      `/api/projects/${PROJECT_ID}/summaries/${SUMMARY_ID}/download`,
    )
  })
})

describe('SummaryPanel – privacy note (US-22 AC16)', () => {
  it('says content goes to the AI provider, Gemini free tier may use it, avoid sensitive data', async () => {
    renderPanel()
    await flush()

    const note = screen.getByText(/sends this project's transcripts and screenshots/)
    expect(note).toBeVisible()
    expect(note).toHaveTextContent('configured AI provider')
    expect(note).toHaveTextContent("Gemini's free tier may use data to improve Google products")
    expect(note).toHaveTextContent("Don't use it for sensitive content.")
  })
})
