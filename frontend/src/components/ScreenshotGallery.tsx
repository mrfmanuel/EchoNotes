import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { useApi } from '../api/context'
import { genericErrorMessage, screenshotErrorMessage } from '../api/errors'
import type { Screenshot, TranscriptSummary } from '../api/types'
import { formatBytes } from '../lib/format'
import { usePastedImage } from '../lib/paste'
import { IMAGE_ACCEPT, validateImageFile } from '../lib/validation'

interface ScreenshotGalleryProps {
  projectId: string
  screenshots: Screenshot[]
  transcripts: TranscriptSummary[]
  /** Called with the new list after every successful upload, link change or delete. */
  onChange: (screenshots: Screenshot[]) => void
}

interface TranscriptSelectProps {
  id: string
  value: string
  transcripts: TranscriptSummary[]
  disabled?: boolean
  onChange: (transcriptId: string) => void
}

/** `<select>` of the project's transcripts; the empty value means "not linked". */
function TranscriptSelect({ id, value, transcripts, disabled, onChange }: TranscriptSelectProps) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">Not linked</option>
      {transcripts.map((transcript) => (
        <option key={transcript.id} value={transcript.id}>
          {transcript.title}
        </option>
      ))}
    </select>
  )
}

interface ImageViewerProps {
  screenshot: Screenshot
  onClose: () => void
}

/** Full-size view of one screenshot (US-15 AC1). Closes with Escape, the button or the backdrop. */
function ImageViewer({ screenshot, onClose }: ImageViewerProps) {
  const closeButton = useRef<HTMLButtonElement>(null)

  // Move focus into the dialog and give it back to the opener (the thumbnail) on close.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeButton.current?.focus()
    return () => opener?.focus()
  }, [])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div className="viewer-backdrop" onClick={onClose}>
      <div
        className="viewer"
        role="dialog"
        aria-modal="true"
        aria-label={screenshot.filename}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="viewer-bar">
          <span className="item-title">{screenshot.filename}</span>
          <div className="actions">
            <a className="btn" href={screenshot.image_url} target="_blank" rel="noreferrer">
              Open in new tab
            </a>
            <button ref={closeButton} type="button" className="btn" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
        <img className="viewer-image" src={screenshot.image_url} alt={screenshot.filename} />
      </div>
    </div>
  )
}

interface ScreenshotCardProps {
  screenshot: Screenshot
  transcripts: TranscriptSummary[]
  busy: boolean
  onOpen: () => void
  onLink: (transcriptId: string) => void
  onDelete: () => void
}

function ScreenshotCard(props: ScreenshotCardProps) {
  const { screenshot, transcripts, busy, onOpen, onLink, onDelete } = props
  const selectId = useId()
  return (
    <li className="shot-card">
      <button
        type="button"
        className="thumb thumb-button"
        onClick={onOpen}
        aria-label={`Open ${screenshot.filename}`}
      >
        <img src={screenshot.image_url} alt={screenshot.filename} loading="lazy" />
      </button>
      <div className="shot-body">
        <span className="shot-name" title={screenshot.filename}>
          {screenshot.filename}
        </span>
        <span className="item-meta">{formatBytes(screenshot.size_bytes)}</span>
        <label htmlFor={selectId} className="visually-hidden">
          Linked transcript for {screenshot.filename}
        </label>
        <TranscriptSelect
          id={selectId}
          value={screenshot.transcript_id ?? ''}
          transcripts={transcripts}
          disabled={busy}
          onChange={onLink}
        />
        <button
          type="button"
          className="btn btn-danger btn-small"
          onClick={onDelete}
          disabled={busy}
          aria-label={`Delete ${screenshot.filename}`}
        >
          Delete
        </button>
      </div>
    </li>
  )
}

/** Screenshots of a project: picker, Ctrl+V paste, link to a transcript, gallery, delete. */
export function ScreenshotGallery(props: ScreenshotGalleryProps) {
  const { projectId, screenshots, transcripts, onChange } = props
  const api = useApi()
  const ids = useId()
  const fileInput = useRef<HTMLInputElement>(null)
  const [linkTo, setLinkTo] = useState('')
  const [uploading, setUploading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [viewing, setViewing] = useState<Screenshot | null>(null)
  const closeViewer = useCallback(() => setViewing(null), [])

  async function upload(file: File): Promise<void> {
    const invalid = validateImageFile(file)
    if (invalid) {
      setError(invalid)
      return
    }
    setError(null)
    setUploading(true)
    try {
      const created = await api.uploadScreenshot(projectId, {
        file,
        transcriptId: linkTo || undefined,
      })
      onChange([...screenshots, created])
    } catch (err) {
      setError(screenshotErrorMessage(err))
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  usePastedImage((file) => void upload(file), !uploading)

  async function link(screenshot: Screenshot, transcriptId: string): Promise<void> {
    setError(null)
    setBusyId(screenshot.id)
    try {
      const updated = await api.updateScreenshot(screenshot.id, {
        transcript_id: transcriptId || null,
      })
      onChange(screenshots.map((shot) => (shot.id === updated.id ? updated : shot)))
    } catch (err) {
      setError(screenshotErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  async function remove(screenshot: Screenshot): Promise<void> {
    if (!window.confirm(`Delete the screenshot "${screenshot.filename}"? This cannot be undone.`)) {
      return
    }
    setError(null)
    setBusyId(screenshot.id)
    try {
      await api.deleteScreenshot(screenshot.id)
      onChange(screenshots.filter((shot) => shot.id !== screenshot.id))
    } catch (err) {
      setError(genericErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="screenshots">
      <div className="card shot-upload" aria-busy={uploading}>
        <div className="field">
          <label htmlFor={`${ids}-file`}>Add a screenshot</label>
          <input
            ref={fileInput}
            id={`${ids}-file`}
            type="file"
            accept={IMAGE_ACCEPT}
            disabled={uploading}
            onChange={(event) => {
              const chosen = event.target.files?.[0]
              if (chosen) void upload(chosen)
            }}
          />
          <p className="hint">
            PNG, JPEG or WebP, up to 5 MB. You can also paste an image with Ctrl+V (Cmd+V) anywhere
            on this page.
          </p>
        </div>
        <div className="field">
          <label htmlFor={`${ids}-link`}>Link new screenshots to (optional)</label>
          <TranscriptSelect
            id={`${ids}-link`}
            value={linkTo}
            transcripts={transcripts}
            disabled={uploading}
            onChange={setLinkTo}
          />
        </div>
        {uploading && (
          <p className="status" role="status">
            <span className="spinner" aria-hidden="true" /> Uploading screenshot…
          </p>
        )}
        {error && (
          <p className="alert alert-error" role="alert">
            {error}
          </p>
        )}
      </div>

      {screenshots.length === 0 ? (
        <div className="empty-state">
          <p>No screenshots yet. Pick an image above or paste one with Ctrl+V.</p>
        </div>
      ) : (
        <ul className="thumb-grid shot-grid" aria-label="Screenshot gallery">
          {screenshots.map((shot) => (
            <ScreenshotCard
              key={shot.id}
              screenshot={shot}
              transcripts={transcripts}
              busy={busyId === shot.id}
              onOpen={() => setViewing(shot)}
              onLink={(transcriptId) => void link(shot, transcriptId)}
              onDelete={() => void remove(shot)}
            />
          ))}
        </ul>
      )}

      {viewing && <ImageViewer screenshot={viewing} onClose={closeViewer} />}
    </div>
  )
}
