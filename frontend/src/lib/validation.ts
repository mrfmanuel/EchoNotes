// Client-side validation that mirrors the API rules (the API stays the authority).

export const PROJECT_NAME_MAX = 100
export const TRANSCRIPT_TITLE_MAX = 200
/** 25 MB with MB = 1024² bytes (docs/product-spec.md §3.4.1). */
export const MAX_AUDIO_BYTES = 25 * 1024 * 1024
export const AUDIO_EXTENSIONS = ['mp3', 'wav', 'm4a', 'ogg', 'webm'] as const
export const AUDIO_ACCEPT = AUDIO_EXTENSIONS.map((ext) => `.${ext}`).join(',')

/** Returns an error message, or null when the (trimmed) project name is valid. */
export function validateProjectName(name: string): string | null {
  const trimmed = name.trim()
  if (trimmed.length === 0) return 'Enter a project name.'
  if (trimmed.length > PROJECT_NAME_MAX) {
    return `The name must be at most ${PROJECT_NAME_MAX} characters.`
  }
  return null
}

/** Returns an error message, or null when the (trimmed) transcript title is valid. */
export function validateTranscriptTitle(title: string): string | null {
  const trimmed = title.trim()
  if (trimmed.length === 0) return 'Enter a title.'
  if (trimmed.length > TRANSCRIPT_TITLE_MAX) {
    return `The title must be at most ${TRANSCRIPT_TITLE_MAX} characters.`
  }
  return null
}

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.')
  return dot === -1 ? '' : filename.slice(dot + 1).toLowerCase()
}

/** Returns an error message, or null when the file may be uploaded for transcription. */
export function validateAudioFile(file: File): string | null {
  const ext = extensionOf(file.name)
  if (!(AUDIO_EXTENSIONS as readonly string[]).includes(ext)) {
    return 'This file type is not supported. Use an mp3, wav, m4a, ogg or webm file.'
  }
  if (file.size > MAX_AUDIO_BYTES) {
    return 'The file is larger than 25 MB. Choose a smaller file.'
  }
  return null
}
