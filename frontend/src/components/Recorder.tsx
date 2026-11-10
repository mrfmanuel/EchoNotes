import { useEffect, useRef, useState } from 'react'
import { formatDuration } from '../lib/format'
import {
  DENIED_MESSAGE,
  NO_MICROPHONE_MESSAGE,
  UNSUPPORTED_MESSAGE,
  isRecordingSupported,
  pickMimeType,
  recordingFile,
} from '../lib/recording'

type RecorderStatus = 'idle' | 'starting' | 'recording'

interface RecorderProps {
  /** Called with the finished recording (not called on Cancel). */
  onRecorded: (file: File) => void
  disabled?: boolean
}

export function Recorder({ onRecorded, disabled = false }: RecorderProps) {
  const [supported] = useState(isRecordingSupported)
  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const cancelledRef = useRef(false)
  const onRecordedRef = useRef(onRecorded)

  useEffect(() => {
    onRecordedRef.current = onRecorded
  }, [onRecorded])

  useEffect(() => {
    if (status !== 'recording') return
    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 250)
    return () => window.clearInterval(timer)
  }, [status])

  // Release the microphone if the component unmounts mid-recording; nothing is uploaded.
  useEffect(
    () => () => {
      cancelledRef.current = true
      const recorder = recorderRef.current
      if (recorder && recorder.state !== 'inactive') recorder.stop()
      streamRef.current?.getTracks().forEach((track) => track.stop())
    },
    [],
  )

  function releaseStream(): void {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }

  function stopEverything(cancel: boolean): void {
    cancelledRef.current = cancel
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    else releaseStream()
  }

  async function start(): Promise<void> {
    setError(null)
    setStatus('starting')
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (err) {
      const denied = err instanceof DOMException && err.name === 'NotAllowedError'
      setError(denied ? DENIED_MESSAGE : NO_MICROPHONE_MESSAGE)
      setStatus('idle')
      return
    }
    streamRef.current = stream
    const mimeType = pickMimeType()
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
    const chunks: Blob[] = []
    cancelledRef.current = false
    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    recorder.onstop = () => {
      releaseStream()
      recorderRef.current = null
      setStatus('idle')
      setElapsed(0)
      if (!cancelledRef.current && chunks.length > 0) {
        onRecordedRef.current(recordingFile(chunks, recorder.mimeType || mimeType))
      }
    }
    recorderRef.current = recorder
    recorder.start()
    setElapsed(0)
    setStatus('recording')
  }

  if (!supported) {
    return (
      <div className="recorder">
        <button type="button" className="btn" disabled>
          Record
        </button>
        <p className="hint" role="note">
          {UNSUPPORTED_MESSAGE}
        </p>
      </div>
    )
  }

  return (
    <div className="recorder">
      {status === 'recording' ? (
        <>
          <span className="recording-indicator" aria-live="polite">
            <span className="recording-dot" aria-hidden="true" />
            Recording <time aria-label="Elapsed time">{formatDuration(elapsed)}</time>
          </span>
          <button type="button" className="btn btn-primary" onClick={() => stopEverything(false)}>
            Stop
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => stopEverything(true)}>
            Cancel
          </button>
        </>
      ) : (
        <button
          type="button"
          className="btn"
          onClick={() => void start()}
          disabled={disabled || status === 'starting'}
        >
          {status === 'starting' ? 'Waiting for microphone…' : 'Record'}
        </button>
      )}
      {error && (
        <p className="hint hint-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
