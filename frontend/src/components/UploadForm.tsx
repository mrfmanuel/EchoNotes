import { useId, useRef, useState, type FormEvent } from 'react'
import { useApi } from '../api/context'
import { transcriptionErrorMessage } from '../api/errors'
import type { LanguageHint, Transcript } from '../api/types'
import { AUDIO_ACCEPT, validateAudioFile } from '../lib/validation'
import { Recorder } from './Recorder'

const LANGUAGE_OPTIONS: { value: LanguageHint; label: string }[] = [
  { value: 'auto', label: 'Auto-detect' },
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Spanish' },
  { value: 'pt', label: 'Portuguese' },
]

interface UploadFormProps {
  projectId: string
  /** Called once the API returned the new transcript. */
  onCreated: (transcript: Transcript) => void
}

/** Upload or record audio and transcribe it (US-05, US-06, US-07). */
export function UploadForm({ projectId, onCreated }: UploadFormProps) {
  const api = useApi()
  const ids = useId()
  const fileInput = useRef<HTMLInputElement>(null)
  const [language, setLanguage] = useState<LanguageHint>('auto')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function transcribe(audio: File): Promise<void> {
    const invalid = validateAudioFile(audio)
    if (invalid) {
      setError(invalid)
      return
    }
    setError(null)
    setBusy(true)
    try {
      const transcript = await api.createTranscription(projectId, { file: audio, language })
      setFile(null)
      if (fileInput.current) fileInput.current.value = ''
      onCreated(transcript)
    } catch (err) {
      setError(transcriptionErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function onFileChange(chosen: File | null): void {
    setFile(chosen)
    setError(chosen ? validateAudioFile(chosen) : null)
  }

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    if (!file) {
      setError('Choose an audio file first.')
      return
    }
    void transcribe(file)
  }

  return (
    <form className="upload-form" onSubmit={onSubmit} aria-busy={busy} noValidate>
      <div className="field">
        <label htmlFor={`${ids}-language`}>Language</label>
        <select
          id={`${ids}-language`}
          value={language}
          onChange={(event) => setLanguage(event.target.value as LanguageHint)}
          disabled={busy}
        >
          {LANGUAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor={`${ids}-file`}>Audio file</label>
        <input
          ref={fileInput}
          id={`${ids}-file`}
          type="file"
          accept={AUDIO_ACCEPT}
          onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
          disabled={busy}
        />
        <p className="hint">mp3, wav, m4a, ogg or webm, up to 25 MB.</p>
      </div>

      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          Upload and transcribe
        </button>
        <span className="actions-separator">or</span>
        <Recorder onRecorded={(recording) => void transcribe(recording)} disabled={busy} />
      </div>

      {busy && (
        <p className="status" role="status">
          <span className="spinner" aria-hidden="true" /> Transcribing… this can take a minute.
        </p>
      )}
      {error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
