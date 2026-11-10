import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useApi } from '../api/context'
import { genericErrorMessage } from '../api/errors'
import type { Transcript, TranscriptUpdate } from '../api/types'
import { formatDate, formatDuration, formatLanguage } from '../lib/format'
import { useUnsavedChangesWarning } from '../lib/useUnsavedChangesWarning'
import { validateTranscriptTitle } from '../lib/validation'

/** How long the "Copied" confirmation stays visible (US-09: about 2 s). */
export const COPIED_FEEDBACK_MS = 2000

type CopyState = 'idle' | 'copied' | 'failed'

interface TranscriptEditorProps {
  transcript: Transcript
  onSaved: (transcript: Transcript) => void
  onDeleted: () => void
}

function useCopyFeedback() {
  const [copyState, setCopyState] = useState<CopyState>('idle')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  async function copy(text: string): Promise<void> {
    window.clearTimeout(timer.current)
    try {
      await navigator.clipboard.writeText(text)
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
    timer.current = window.setTimeout(() => setCopyState('idle'), COPIED_FEEDBACK_MS)
  }

  return { copyState, copy }
}

export function TranscriptEditor({ transcript, onSaved, onDeleted }: TranscriptEditorProps) {
  const api = useApi()
  const [title, setTitle] = useState(transcript.title)
  const [text, setText] = useState(transcript.text)
  const [titleError, setTitleError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedNotice, setSavedNotice] = useState(false)
  const { copyState, copy } = useCopyFeedback()

  const changes: TranscriptUpdate = {}
  if (title.trim() !== transcript.title) changes.title = title.trim()
  if (text !== transcript.text) changes.text = text
  const dirty = Object.keys(changes).length > 0
  const { setBypass } = useUnsavedChangesWarning(dirty)

  async function onSave(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    const invalid = validateTranscriptTitle(title)
    setTitleError(invalid)
    if (invalid || !dirty) return
    setSaving(true)
    setError(null)
    try {
      const saved = await api.updateTranscription(transcript.id, changes)
      setTitle(saved.title)
      setText(saved.text)
      setSavedNotice(true)
      onSaved(saved)
    } catch (err) {
      setError(genericErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function onDelete(): Promise<void> {
    if (!window.confirm('Delete this transcript? Linked screenshots stay in the project.')) return
    setError(null)
    setBypass(true)
    try {
      await api.deleteTranscription(transcript.id)
      onDeleted()
    } catch (err) {
      setBypass(false)
      setError(genericErrorMessage(err))
    }
  }

  return (
    <form className="transcript" onSubmit={(event) => void onSave(event)} noValidate>
      <div className="field">
        <label htmlFor="transcript-title">Title</label>
        <input
          id="transcript-title"
          className="title-input"
          type="text"
          value={title}
          onChange={(event) => {
            setTitle(event.target.value)
            setSavedNotice(false)
          }}
          aria-invalid={titleError ? true : undefined}
          disabled={saving}
        />
        {titleError && (
          <p className="field-error" role="alert">
            {titleError}
          </p>
        )}
      </div>

      <dl className="meta" aria-label="Transcript details">
        <div>
          <dt>Created</dt>
          <dd>{formatDate(transcript.created_at)}</dd>
        </div>
        <div>
          <dt>Language</dt>
          <dd>{formatLanguage(transcript.language)}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd>{formatDuration(transcript.duration_seconds)}</dd>
        </div>
      </dl>

      <div className="field">
        <label htmlFor="transcript-text">Text</label>
        <textarea
          id="transcript-text"
          value={text}
          rows={14}
          onChange={(event) => {
            setText(event.target.value)
            setSavedNotice(false)
          }}
          disabled={saving}
        />
      </div>

      <div className="toolbar">
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={saving || !dirty}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
          <button type="button" className="btn" onClick={() => void copy(text)}>
            {copyState === 'copied' ? 'Copied' : 'Copy'}
          </button>
          <a className="btn" href={api.transcriptDownloadUrl(transcript.id, 'md')} download>
            Download .md
          </a>
          <a className="btn" href={api.transcriptDownloadUrl(transcript.id, 'txt')} download>
            Download .txt
          </a>
        </div>
        <button type="button" className="btn btn-danger" onClick={() => void onDelete()}>
          Delete transcript
        </button>
      </div>

      <div aria-live="polite" className="status-line">
        {dirty && (
          <span className="badge badge-warn">
            Unsaved changes (downloads use the saved version)
          </span>
        )}
        {!dirty && savedNotice && <span className="badge badge-ok">Saved</span>}
        {copyState === 'copied' && <span className="visually-hidden">Copied to clipboard</span>}
      </div>
      {copyState === 'failed' && (
        <p className="alert alert-error" role="alert">
          Could not copy. Select the text and copy it manually.
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
