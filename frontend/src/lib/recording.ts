/** Preferred container first (docs/architecture.md: webm/opus with an ogg fallback). */
const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/ogg',
]

export const UNSUPPORTED_MESSAGE =
  'Recording is not supported in this browser. You can still upload an audio file.'
export const DENIED_MESSAGE =
  'Microphone access was denied. Allow it in your browser settings, ' +
  'or upload an audio file instead.'
export const NO_MICROPHONE_MESSAGE = 'Could not access a microphone. Upload an audio file instead.'

export function isRecordingSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.MediaRecorder !== 'undefined' &&
    typeof navigator.mediaDevices?.getUserMedia === 'function'
  )
}

export function pickMimeType(): string {
  if (typeof MediaRecorder.isTypeSupported !== 'function') return ''
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? ''
}

/** Builds `recording-<timestamp>.<webm|ogg>` so the API accepts the upload (#18). */
export function recordingFile(chunks: Blob[], recorderMime: string, now = new Date()): File {
  const ext = recorderMime.includes('ogg') ? 'ogg' : 'webm'
  const stamp = now.toISOString().replace(/[:.]/g, '-')
  return new File(chunks, `recording-${stamp}.${ext}`, { type: `audio/${ext}` })
}
