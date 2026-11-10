import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiProvider } from '../api/ApiProvider'
import type { Transcript } from '../api/types'
import { DENIED_MESSAGE, UNSUPPORTED_MESSAGE } from '../lib/recording'
import { MAX_AUDIO_BYTES } from '../lib/validation'
import { apiError, createMockClient, makeTranscript, PROJECT_ID, type MockApiClient } from '../test/mockClient'
import { UploadForm } from './UploadForm'

/** Minimal MediaRecorder stand-in: emits one chunk and fires onstop when stopped. */
class FakeMediaRecorder {
  static isTypeSupported = vi.fn((type: string) => type.startsWith('audio/webm'))
  static last: FakeMediaRecorder | null = null
  state: RecordingState = 'inactive'
  mimeType: string
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null

  constructor(_stream: MediaStream, options?: MediaRecorderOptions) {
    this.mimeType = options?.mimeType ?? 'audio/webm'
    FakeMediaRecorder.last = this
  }

  start(): void {
    this.state = 'recording'
  }

  stop(): void {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['audio-bytes'], { type: this.mimeType }) })
    this.onstop?.()
  }
}

let client: MockApiClient
let onCreated: ReturnType<typeof vi.fn<(transcript: Transcript) => void>>
let trackStop: ReturnType<typeof vi.fn>
let getUserMedia: ReturnType<typeof vi.fn>

function setMediaDevices(value: unknown): void {
  Object.defineProperty(navigator, 'mediaDevices', { value, configurable: true })
}

function renderForm() {
  return render(
    <ApiProvider client={client}>
      <UploadForm projectId={PROJECT_ID} onCreated={onCreated} />
    </ApiProvider>,
  )
}

function audio(name = 'talk.mp3', size?: number): File {
  const file = new File(['abc'], name, { type: 'audio/mpeg' })
  if (size !== undefined) Object.defineProperty(file, 'size', { value: size })
  return file
}

beforeEach(() => {
  client = createMockClient()
  onCreated = vi.fn()
  trackStop = vi.fn()
  getUserMedia = vi.fn(() => Promise.resolve({ getTracks: () => [{ stop: trackStop }] }))
  vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
  setMediaDevices({ getUserMedia })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  setMediaDevices(undefined)
})

describe('UploadForm – file upload (US-05)', () => {
  it('accepts mp3/wav/m4a/ogg/webm in the file picker', () => {
    renderForm()

    expect(screen.getByLabelText('Audio file')).toHaveAttribute(
      'accept',
      '.mp3,.wav,.m4a,.ogg,.webm',
    )
  })

  it('US-05 AC1: shows "Transcribing…" while uploading, then reports the new transcript', async () => {
    let resolve: (t: Transcript) => void = () => {}
    client.createTranscription.mockReturnValue(new Promise((r) => (resolve = r)))
    const user = userEvent.setup()
    renderForm()

    const file = audio()
    await user.upload(screen.getByLabelText('Audio file'), file)
    await user.click(screen.getByRole('button', { name: 'Upload and transcribe' }))

    expect(screen.getByRole('status')).toHaveTextContent('Transcribing…')
    expect(screen.getByRole('button', { name: 'Upload and transcribe' })).toBeDisabled()
    expect(client.createTranscription).toHaveBeenCalledWith(PROJECT_ID, {
      file,
      language: 'auto',
    })

    const transcript = makeTranscript()
    await act(async () => resolve(transcript))
    expect(onCreated).toHaveBeenCalledWith(transcript)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('US-05 AC3: a file over 25 MB is rejected client-side and no request is sent', async () => {
    const user = userEvent.setup()
    renderForm()

    await user.upload(screen.getByLabelText('Audio file'), audio('big.mp3', MAX_AUDIO_BYTES + 1))
    expect(screen.getByRole('alert')).toHaveTextContent('larger than 25 MB')

    await user.click(screen.getByRole('button', { name: 'Upload and transcribe' }))
    expect(client.createTranscription).not.toHaveBeenCalled()
  })

  it('US-05 AC2: another file type is rejected client-side and no request is sent', async () => {
    const user = userEvent.setup({ applyAccept: false })
    renderForm()

    await user.upload(screen.getByLabelText('Audio file'), new File(['x'], 'notes.txt'))
    await user.click(screen.getByRole('button', { name: 'Upload and transcribe' }))

    expect(screen.getByRole('alert')).toHaveTextContent('not supported')
    expect(client.createTranscription).not.toHaveBeenCalled()
  })

  it('asks for a file when submitting without one', async () => {
    const user = userEvent.setup()
    renderForm()

    await user.click(screen.getByRole('button', { name: 'Upload and transcribe' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Choose an audio file first.')
  })

  it.each([
    [415, 'unsupported_media_type', /file type is not supported/],
    [413, 'audio_too_large', /larger than 25 MB/],
    [502, 'provider_error', /transcription service returned an error.*try again/i],
    [504, 'provider_timeout', /timed out.*try again/i],
  ] as const)(
    'US-05 AC2–AC4: API %i (%s) shows a clear error with a hint',
    async (status, code, message) => {
      client.createTranscription.mockRejectedValue(apiError(status, 'x', code))
      const user = userEvent.setup()
      renderForm()

      await user.upload(screen.getByLabelText('Audio file'), audio())
      await user.click(screen.getByRole('button', { name: 'Upload and transcribe' }))

      expect(await screen.findByRole('alert')).toHaveTextContent(message)
      expect(onCreated).not.toHaveBeenCalled()
      // Retry: the form is usable again.
      expect(screen.getByRole('button', { name: 'Upload and transcribe' })).toBeEnabled()
    },
  )
})

describe('UploadForm – language hint (US-07)', () => {
  it('US-07 AC1: offers Auto (default), English, Spanish and Portuguese', () => {
    renderForm()

    const select = screen.getByLabelText('Language')
    expect(select).toHaveValue('auto')
    expect(Array.from((select as HTMLSelectElement).options).map((o) => o.value)).toEqual([
      'auto',
      'en',
      'es',
      'pt',
    ])
  })

  it('US-07 AC2: sends the chosen language with the upload', async () => {
    client.createTranscription.mockResolvedValue(makeTranscript())
    const user = userEvent.setup()
    renderForm()

    await user.selectOptions(screen.getByLabelText('Language'), 'pt')
    const file = audio('aula.ogg')
    await user.upload(screen.getByLabelText('Audio file'), file)
    await user.click(screen.getByRole('button', { name: 'Upload and transcribe' }))

    expect(client.createTranscription).toHaveBeenCalledWith(PROJECT_ID, { file, language: 'pt' })
  })
})

describe('Recorder (US-06)', () => {
  it('US-06 AC1: Record then Stop uploads recording-<timestamp>.webm with the language', async () => {
    client.createTranscription.mockResolvedValue(makeTranscript())
    const user = userEvent.setup()
    renderForm()

    await user.selectOptions(screen.getByLabelText('Language'), 'es')
    await user.click(screen.getByRole('button', { name: 'Record' }))
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true })
    await user.click(await screen.findByRole('button', { name: 'Stop' }))

    await waitFor(() => expect(client.createTranscription).toHaveBeenCalledTimes(1))
    const [projectId, upload] = client.createTranscription.mock.calls[0]
    expect(projectId).toBe(PROJECT_ID)
    expect(upload.language).toBe('es')
    expect(upload.file.name).toMatch(/^recording-[\dTZ-]+\.webm$/)
    expect(upload.file.type).toBe('audio/webm')
    expect(trackStop).toHaveBeenCalled()
  })

  it('US-06 AC2: shows the elapsed time while recording', async () => {
    renderForm()
    vi.useFakeTimers()

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Record' })))
    expect(screen.getByLabelText('Elapsed time')).toHaveTextContent('0:00')

    act(() => vi.advanceTimersByTime(3_000))
    expect(screen.getByLabelText('Elapsed time')).toHaveTextContent('0:03')
  })

  it('US-06 AC2: Cancel stops recording and uploads nothing', async () => {
    const user = userEvent.setup()
    renderForm()

    await user.click(screen.getByRole('button', { name: 'Record' }))
    await user.click(await screen.findByRole('button', { name: 'Cancel' }))

    expect(FakeMediaRecorder.last?.state).toBe('inactive')
    expect(trackStop).toHaveBeenCalled()
    expect(client.createTranscription).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Record' })).toBeInTheDocument()
  })

  it('US-06 AC3: unsupported browser explains why and file upload still works', async () => {
    vi.stubGlobal('MediaRecorder', undefined)
    client.createTranscription.mockResolvedValue(makeTranscript())
    const user = userEvent.setup()
    renderForm()

    expect(screen.getByRole('button', { name: 'Record' })).toBeDisabled()
    expect(screen.getByText(UNSUPPORTED_MESSAGE)).toBeInTheDocument()

    await user.upload(screen.getByLabelText('Audio file'), audio())
    await user.click(screen.getByRole('button', { name: 'Upload and transcribe' }))
    expect(client.createTranscription).toHaveBeenCalledTimes(1)
  })

  it('US-06 AC3: denied microphone permission shows an explanation', async () => {
    getUserMedia.mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    const user = userEvent.setup()
    renderForm()

    await user.click(screen.getByRole('button', { name: 'Record' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(DENIED_MESSAGE)
    expect(screen.getByLabelText('Audio file')).toBeEnabled()
    expect(client.createTranscription).not.toHaveBeenCalled()
  })
})
