import { ApiError, NETWORK_ERROR_STATUS } from './client'

const RETRY_HINT = 'Please try again in a moment.'

/** User-facing message for a failed transcription upload (US-05 AC2–AC4). */
export function transcriptionErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return `Something went wrong. ${RETRY_HINT}`
  switch (error.status) {
    case NETWORK_ERROR_STATUS:
      return 'Could not reach the server. Check your connection and try again.'
    case 404:
      return 'This project no longer exists. Go back to the projects list.'
    case 413:
      return 'The file is larger than 25 MB. Choose a smaller file or a shorter recording.'
    case 415:
      return 'This file type is not supported. Use an mp3, wav, m4a, ogg or webm file.'
    case 422:
      return `The upload was rejected: ${error.firstMessage}`
    case 502:
      return `The transcription service returned an error. ${RETRY_HINT}`
    case 504:
      return 'The transcription service timed out. Try again, or use a shorter recording.'
    default:
      return `Something went wrong (HTTP ${error.status}). ${RETRY_HINT}`
  }
}

/** Generic user-facing message for any other failed request. */
export function genericErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Something went wrong. Please try again.'
  if (error.status === NETWORK_ERROR_STATUS) {
    return 'Could not reach the server. Check your connection and try again.'
  }
  if (error.status === 404) return 'Not found. It may have been deleted.'
  if (error.status === 422) return error.firstMessage
  return `Something went wrong (HTTP ${error.status}). Please try again.`
}

/** User-facing message for a failed project export (US-16, #21 AC2). */
export function exportErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return 'This project no longer exists, so it cannot be exported.'
  }
  if (error instanceof ApiError && error.status === NETWORK_ERROR_STATUS) {
    return `The export failed: could not reach the server. ${RETRY_HINT}`
  }
  const status = error instanceof ApiError ? ` (HTTP ${error.status})` : ''
  return `The export failed${status}. ${RETRY_HINT}`
}

/** User-facing message for a failed screenshot upload or link change (US-12 AC2, US-14 AC2). */
export function screenshotErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413) return 'The image is larger than 5 MB. Choose a smaller image.'
    if (error.status === 415) {
      return 'This image type is not supported. Use a PNG, JPEG or WebP image.'
    }
    if (error.status === 422) {
      return `The screenshot was rejected: ${error.firstMessage}`
    }
  }
  return genericErrorMessage(error)
}
