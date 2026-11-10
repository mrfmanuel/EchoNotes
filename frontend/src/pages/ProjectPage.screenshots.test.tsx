import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
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
import { MAX_IMAGE_BYTES } from '../lib/validation'

const PATH = `/projects/${PROJECT_ID}`
const SHOT_ID = '44444444-4444-4444-8444-444444444444'
let client: MockApiClient

function image(name = 'slide.png', type = 'image/png', size?: number): File {
  const file = new File(['fake-image-bytes'], name, { type })
  if (size !== undefined) Object.defineProperty(file, 'size', { value: size })
  return file
}

interface FakeClipboardItem {
  kind: string
  type: string
  getAsFile: () => File | null
}

/** Dispatches a `paste` event whose clipboardData holds `files` (and optional plain text). */
function paste(target: Element,files: File[], text?: string): Event {
  const items: FakeClipboardItem[] = files.map((file) => ({
    kind: 'file',
    type: file.type,
    getAsFile: () => file,
  }))
  if (text !== undefined) items.push({ kind: 'string', type: 'text/plain', getAsFile: () => null })
  const event = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'clipboardData', { value: { items, files } })
  fireEvent(target, event)
  return event
}

async function renderLoaded() {
  // applyAccept: false so a wrong file type reaches our own validation (US-12 AC2).
  const user = userEvent.setup({ applyAccept: false })
  const view = renderApp(PATH, client)
  await screen.findByRole('heading', { name: /^Screenshots/ })
  return { user, ...view }
}

beforeEach(() => {
  client = createMockClient()
  client.getProject.mockResolvedValue(
    makeProjectDetail({ transcripts: [makeTranscript({ title: 'Week 1' })] }),
  )
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Screenshots – picker upload (US-12)', () => {
  it('US-12 AC1: uploads a picked image and shows it in the gallery', async () => {
    client.uploadScreenshot.mockResolvedValue(makeScreenshot({ id: SHOT_ID, filename: 'a.png' }))
    const { user } = await renderLoaded()

    const file = image('a.png')
    await user.upload(screen.getByLabelText('Add a screenshot'), file)

    expect(client.uploadScreenshot).toHaveBeenCalledWith(PROJECT_ID, {
      file,
      transcriptId: undefined,
    })
    const gallery = await screen.findByRole('list', { name: 'Screenshot gallery' })
    expect(within(gallery).getByRole('img', { name: 'a.png' })).toHaveAttribute(
      'src',
      `/api/screenshots/${SHOT_ID}/image`,
    )
    expect(screen.getByRole('heading', { name: 'Screenshots (1)' })).toBeInTheDocument()
  })

  it('US-12 AC2: rejects an unsupported type without calling the API', async () => {
    const { user } = await renderLoaded()

    await user.upload(screen.getByLabelText('Add a screenshot'), image('anim.gif', 'image/gif'))

    expect(screen.getByRole('alert')).toHaveTextContent(/PNG, JPEG or WebP/)
    expect(client.uploadScreenshot).not.toHaveBeenCalled()
  })

  it('US-12 AC2: rejects an image larger than 5 MB without calling the API', async () => {
    const { user } = await renderLoaded()

    const big = image('big.png', 'image/png', MAX_IMAGE_BYTES + 1)
    await user.upload(screen.getByLabelText('Add a screenshot'), big)

    expect(screen.getByRole('alert')).toHaveTextContent(/larger than 5 MB/)
    expect(client.uploadScreenshot).not.toHaveBeenCalled()
  })

  it('US-12 AC2: accepts an image of exactly 5 MB', async () => {
    client.uploadScreenshot.mockResolvedValue(makeScreenshot({ id: SHOT_ID }))
    const { user } = await renderLoaded()

    const edge = image('edge.webp', 'image/webp', MAX_IMAGE_BYTES)
    await user.upload(screen.getByLabelText('Add a screenshot'), edge)

    expect(client.uploadScreenshot).toHaveBeenCalledTimes(1)
  })

  it('US-12 AC2/AC3: shows a clear message when the API answers 415', async () => {
    client.uploadScreenshot.mockRejectedValue(
      apiError(415, 'Unsupported image type', 'unsupported_media_type'),
    )
    const { user } = await renderLoaded()

    await user.upload(screen.getByLabelText('Add a screenshot'), image('fake.png'))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This image type is not supported. Use a PNG, JPEG or WebP image.',
    )
    expect(screen.getByText(/no screenshots yet/i)).toBeInTheDocument()
  })

  it('US-12 AC2: shows a clear message when the API answers 413', async () => {
    client.uploadScreenshot.mockRejectedValue(apiError(413, 'Too large', 'image_too_large'))
    const { user } = await renderLoaded()

    await user.upload(screen.getByLabelText('Add a screenshot'), image())

    expect(await screen.findByRole('alert')).toHaveTextContent(/larger than 5 MB/)
  })

  it('US-14 AC2: shows the API message when the link is rejected with 422', async () => {
    client.uploadScreenshot.mockRejectedValue(
      apiError(422, 'transcript_id does not belong to this project', 'validation_error'),
    )
    const { user } = await renderLoaded()

    await user.upload(screen.getByLabelText('Add a screenshot'), image())

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The screenshot was rejected: transcript_id does not belong to this project',
    )
  })
})

describe('Screenshots – Ctrl+V paste (US-13)', () => {
  it('US-13 AC1: pasting an image while no text field is focused uploads it', async () => {
    client.uploadScreenshot.mockResolvedValue(makeScreenshot({ id: SHOT_ID }))
    await renderLoaded()

    const event = paste(document.body, [image('clip.png')])

    await waitFor(() => expect(client.uploadScreenshot).toHaveBeenCalledTimes(1))
    const [, upload] = client.uploadScreenshot.mock.calls[0]
    expect(upload.file.type).toBe('image/png')
    expect(event.defaultPrevented).toBe(true)
    expect(await screen.findByRole('list', { name: 'Screenshot gallery' })).toBeInTheDocument()
  })

  it('US-13 AC1: gives the generic clipboard name "image.png" a readable filename', async () => {
    client.uploadScreenshot.mockResolvedValue(makeScreenshot({ id: SHOT_ID }))
    await renderLoaded()

    paste(document.body, [image('image.png')])

    await waitFor(() => expect(client.uploadScreenshot).toHaveBeenCalledTimes(1))
    expect(client.uploadScreenshot.mock.calls[0][1].file.name).toBe('pasted-screenshot.png')
  })

  it('US-13 AC2: pasting without an image does nothing and shows no error', async () => {
    await renderLoaded()

    const event = paste(document.body, [], 'just text')

    expect(client.uploadScreenshot).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(false)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('US-13 AC1: pasting while typing in a text input does nothing', async () => {
    const { user } = await renderLoaded()
    await user.click(screen.getByRole('button', { name: 'Rename' }))
    const input = screen.getByLabelText('Project name')
    expect(input).toHaveFocus()

    const event = paste(input, [image('clip.png')])

    expect(client.uploadScreenshot).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(false)
  })

  it('US-13 AC1: pasting while a contenteditable element is focused does nothing', async () => {
    await renderLoaded()
    const editable = document.createElement('div')
    editable.contentEditable = 'true'
    // jsdom does not implement isContentEditable; emulate the browser.
    Object.defineProperty(editable, 'isContentEditable', { value: true })
    editable.tabIndex = 0
    document.body.appendChild(editable)
    editable.focus()

    paste(editable, [image('clip.png')])

    expect(client.uploadScreenshot).not.toHaveBeenCalled()
    editable.remove()
  })

  it('US-13: a pasted unsupported image type shows the type error without a request', async () => {
    await renderLoaded()

    paste(document.body, [image('clip.gif', 'image/gif')])

    expect(await screen.findByRole('alert')).toHaveTextContent(/PNG, JPEG or WebP/)
    expect(client.uploadScreenshot).not.toHaveBeenCalled()
  })
})

describe('Screenshots – link to a transcript (US-14)', () => {
  it('US-14 AC1: links the screenshot at upload time when a transcript is selected', async () => {
    client.uploadScreenshot.mockResolvedValue(
      makeScreenshot({ id: SHOT_ID, transcript_id: TRANSCRIPT_ID }),
    )
    const { user } = await renderLoaded()

    await user.selectOptions(screen.getByLabelText(/link new screenshots to/i), 'Week 1')
    const file = image()
    await user.upload(screen.getByLabelText('Add a screenshot'), file)

    expect(client.uploadScreenshot).toHaveBeenCalledWith(PROJECT_ID, {
      file,
      transcriptId: TRANSCRIPT_ID,
    })
  })

  it('US-14 AC1: links an existing screenshot afterwards (PATCH)', async () => {
    client.getProject.mockResolvedValue(
      makeProjectDetail({
        transcripts: [makeTranscript({ title: 'Week 1' })],
        screenshots: [makeScreenshot({ id: SHOT_ID, filename: 'a.png' })],
      }),
    )
    client.updateScreenshot.mockResolvedValue(
      makeScreenshot({ id: SHOT_ID, filename: 'a.png', transcript_id: TRANSCRIPT_ID }),
    )
    const { user } = await renderLoaded()

    const select = screen.getByLabelText('Linked transcript for a.png')
    await user.selectOptions(select, 'Week 1')

    expect(client.updateScreenshot).toHaveBeenCalledWith(SHOT_ID, { transcript_id: TRANSCRIPT_ID })
    await waitFor(() => expect(select).toHaveValue(TRANSCRIPT_ID))
  })

  it('US-14 AC1: unlinks a screenshot by choosing "Not linked"', async () => {
    client.getProject.mockResolvedValue(
      makeProjectDetail({
        transcripts: [makeTranscript({ title: 'Week 1' })],
        screenshots: [
          makeScreenshot({ id: SHOT_ID, filename: 'a.png', transcript_id: TRANSCRIPT_ID }),
        ],
      }),
    )
    client.updateScreenshot.mockResolvedValue(
      makeScreenshot({ id: SHOT_ID, filename: 'a.png', transcript_id: null }),
    )
    const { user } = await renderLoaded()

    const select = screen.getByLabelText('Linked transcript for a.png')
    expect(select).toHaveValue(TRANSCRIPT_ID)
    await user.selectOptions(select, 'Not linked')

    expect(client.updateScreenshot).toHaveBeenCalledWith(SHOT_ID, { transcript_id: null })
    await waitFor(() => expect(select).toHaveValue(''))
  })

  it('US-14 AC2: shows the API error and keeps the old link when PATCH answers 422', async () => {
    client.getProject.mockResolvedValue(
      makeProjectDetail({
        transcripts: [makeTranscript({ title: 'Week 1' })],
        screenshots: [makeScreenshot({ id: SHOT_ID, filename: 'a.png' })],
      }),
    )
    client.updateScreenshot.mockRejectedValue(
      apiError(422, 'Transcript not in this project', 'validation_error'),
    )
    const { user } = await renderLoaded()

    const select = screen.getByLabelText('Linked transcript for a.png')
    await user.selectOptions(select, 'Week 1')

    expect(await screen.findByRole('alert')).toHaveTextContent('Transcript not in this project')
    expect(select).toHaveValue('')
  })
})

describe('Screenshots – gallery and delete (US-15)', () => {
  beforeEach(() => {
    client.getProject.mockResolvedValue(
      makeProjectDetail({
        screenshots: [
          makeScreenshot({ id: SHOT_ID, filename: 'a.png' }),
          makeScreenshot({ id: '55555555-5555-4555-8555-555555555555', filename: 'b.png' }),
        ],
      }),
    )
  })

  it('shows an empty state when the project has no screenshots', async () => {
    client.getProject.mockResolvedValue(makeProjectDetail())
    await renderLoaded()

    expect(screen.getByText(/no screenshots yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Screenshot gallery' })).not.toBeInTheDocument()
  })

  it('US-15 AC1: shows a thumbnail grid of the screenshots', async () => {
    await renderLoaded()

    const gallery = screen.getByRole('list', { name: 'Screenshot gallery' })
    expect(within(gallery).getAllByRole('listitem')).toHaveLength(2)
    expect(within(gallery).getByRole('img', { name: 'b.png' })).toBeInTheDocument()
  })

  it('US-15 AC1: clicking a thumbnail opens the full image, Close and Escape close it', async () => {
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Open a.png' }))

    const dialog = screen.getByRole('dialog', { name: 'a.png' })
    expect(within(dialog).getByRole('img', { name: 'a.png' })).toHaveAttribute(
      'src',
      `/api/screenshots/${SHOT_ID}/image`,
    )
    expect(within(dialog).getByRole('button', { name: 'Close' })).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Open a.png' }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('US-15 AC1: closing the full image returns focus to the thumbnail that opened it', async () => {
    const { user } = await renderLoaded()
    const thumbnail = screen.getByRole('button', { name: 'Open b.png' })

    await user.click(thumbnail)
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(thumbnail).toHaveFocus()

    await user.click(thumbnail)
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(thumbnail).toHaveFocus()
  })

  it('US-15 AC2: deletes a screenshot after confirmation and removes it from the gallery', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    client.deleteScreenshot.mockResolvedValue(undefined)
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Delete a.png' }))

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('a.png'))
    expect(client.deleteScreenshot).toHaveBeenCalledWith(SHOT_ID)
    await waitFor(() =>
      expect(screen.queryByRole('img', { name: 'a.png' })).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('img', { name: 'b.png' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Screenshots (1)' })).toBeInTheDocument()
  })

  it('US-15 AC2: cancelling the confirmation deletes nothing', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Delete a.png' }))

    expect(client.deleteScreenshot).not.toHaveBeenCalled()
    expect(screen.getByRole('img', { name: 'a.png' })).toBeInTheDocument()
  })

  it('US-15 AC2: shows an error and keeps the screenshot when the delete fails', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    client.deleteScreenshot.mockRejectedValue(apiError(500, 'boom'))
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Delete a.png' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/HTTP 500/)
    expect(screen.getByRole('img', { name: 'a.png' })).toBeInTheDocument()
  })
})

describe('Export ZIP (US-16, #21)', () => {
  let clicked: { href: string; download: string }[]
  let createObjectURL: Mock<(blob: Blob) => string>
  let revokeObjectURL: Mock<(url: string) => void>

  beforeEach(() => {
    clicked = []
    createObjectURL = vi.fn(() => 'blob:export-1')
    revokeObjectURL = vi.fn()
    // jsdom has no object URLs and does not download; record what would be saved.
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push({ href: this.getAttribute('href') ?? '', download: this.download })
    })
  })

  function deferred<T>() {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((res) => {
      resolve = res
    })
    return { promise, resolve }
  }

  it('US-16 AC1: downloads the ZIP as <slug>.zip and revokes the object URL', async () => {
    const blob = new Blob(['zip'], { type: 'application/zip' })
    client.exportProject.mockResolvedValue({ blob, filename: null })
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Export ZIP' }))

    expect(client.exportProject).toHaveBeenCalledWith(PROJECT_ID)
    await waitFor(() =>
      expect(clicked).toEqual([{ href: 'blob:export-1', download: 'lecture-notes.zip' }]),
    )
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith('blob:export-1'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('US-16 AC1: uses the filename from Content-Disposition when the API sends one', async () => {
    client.exportProject.mockResolvedValue({ blob: new Blob(['zip']), filename: 'server-name.zip' })
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Export ZIP' }))

    await waitFor(() => expect(clicked[0]?.download).toBe('server-name.zip'))
  })

  it('#21 AC2: shows a busy "Preparing…" state while the ZIP is generated', async () => {
    const pending = deferred<{ blob: Blob; filename: string | null }>()
    client.exportProject.mockReturnValue(pending.promise)
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Export ZIP' }))

    const busy = screen.getByRole('button', { name: /preparing/i })
    expect(busy).toBeDisabled()
    expect(busy).toHaveAttribute('aria-busy', 'true')
    pending.resolve({ blob: new Blob(['zip']), filename: null })
    expect(await screen.findByRole('button', { name: 'Export ZIP' })).toBeEnabled()
  })

  it('#21 AC2: shows an error alert with a retry hint on a 500 and re-enables the button', async () => {
    client.exportProject.mockRejectedValue(apiError(500, 'Internal error'))
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Export ZIP' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The export failed (HTTP 500). Please try again in a moment.',
    )
    expect(screen.getByRole('button', { name: 'Export ZIP' })).toBeEnabled()
    expect(clicked).toEqual([])
  })

  it('#21 AC2: shows an error alert on a network failure', async () => {
    client.exportProject.mockRejectedValue(apiError(0, 'Could not reach the server.'))
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Export ZIP' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach the server/i)
    expect(screen.getByRole('button', { name: 'Export ZIP' })).toBeEnabled()
  })

  it('#21 AC2: explains a 404 (project deleted meanwhile)', async () => {
    client.exportProject.mockRejectedValue(apiError(404, 'Project not found', 'not_found'))
    const { user } = await renderLoaded()

    await user.click(screen.getByRole('button', { name: 'Export ZIP' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/no longer exists/)
  })

  it('US-16 AC3: the export is offered for an empty project too', async () => {
    client.getProject.mockResolvedValue(makeProjectDetail())
    await renderLoaded()

    expect(screen.getByRole('button', { name: 'Export ZIP' })).toBeEnabled()
    expect(screen.getByText(/0 transcripts and 0 screenshots/)).toBeInTheDocument()
  })
})
