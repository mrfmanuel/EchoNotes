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

/** 5 MB with MB = 1024² bytes (docs/product-spec.md §3.4.1). */
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const
const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'webp']
export const IMAGE_ACCEPT = [...IMAGE_TYPES, '.png', '.jpg', '.jpeg', '.webp'].join(',')

/**
 * Returns an error message, or null when the image may be uploaded as a screenshot (US-12).
 * Uses the browser's MIME type, or the extension when the browser did not report one; the API
 * checks the magic bytes anyway.
 */
export function validateImageFile(file: File): string | null {
  const supported = file.type
    ? (IMAGE_TYPES as readonly string[]).includes(file.type)
    : IMAGE_EXTENSIONS.includes(extensionOf(file.name))
  if (!supported) return 'This image type is not supported. Use a PNG, JPEG or WebP image.'
  if (file.size > MAX_IMAGE_BYTES) return 'The image is larger than 5 MB. Choose a smaller image.'
  return null
}
