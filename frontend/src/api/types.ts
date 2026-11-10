// Types mirroring the schemas in openapi.yaml (components/schemas). Keep in sync with the contract.

/** UUID string (`format: uuid`). */
export type Uuid = string
/** ISO 8601 date-time string (`format: date-time`). */
export type DateTimeString = string

export interface Health {
  status: 'ok' | 'degraded'
  version: string
  database: 'ok' | 'error' | 'skipped'
}

export type ErrorCode =
  | 'not_found'
  | 'validation_error'
  | 'unsupported_media_type'
  | 'audio_too_large'
  | 'image_too_large'
  | 'provider_error'
  | 'provider_timeout'

/** FastAPI-style validation item inside a 422 `detail` list. */
export interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
  type?: string
  [key: string]: unknown
}

/** `Error` schema. */
export interface ErrorBody {
  detail: string | ValidationIssue[]
  code?: ErrorCode
}

/** `LanguageHint` schema. */
export type LanguageHint = 'auto' | 'en' | 'es' | 'pt'

export interface ProjectCreate {
  name: string
}

export type ProjectUpdate = ProjectCreate

export interface Project {
  id: Uuid
  name: string
  slug: string
  transcript_count: number
  screenshot_count: number
  created_at: DateTimeString
  updated_at: DateTimeString
}

export type TranscriptProvider = 'groq' | 'fake'

export interface TranscriptSummary {
  id: Uuid
  project_id: Uuid
  title: string
  slug: string
  language?: string | null
  duration_seconds?: number | null
  provider?: TranscriptProvider
  created_at: DateTimeString
  updated_at: DateTimeString
}

export interface Transcript extends TranscriptSummary {
  text: string
  source_filename?: string | null
}

/** At least one property is required by the API (`minProperties: 1`). */
export interface TranscriptUpdate {
  title?: string
  text?: string
}

export type ScreenshotContentType = 'image/png' | 'image/jpeg' | 'image/webp'

export interface Screenshot {
  id: Uuid
  project_id: Uuid
  transcript_id?: Uuid | null
  filename: string
  content_type: ScreenshotContentType
  size_bytes: number
  image_url: string
  created_at: DateTimeString
}

export interface ProjectDetail extends Project {
  transcripts: TranscriptSummary[]
  screenshots: Screenshot[]
}

/** Request body of `updateScreenshot` (link with an ID, unlink with `null`). */
export interface ScreenshotUpdate {
  transcript_id?: Uuid | null
}

export type DownloadFormat = 'md' | 'txt'

/** Multipart fields of `createTranscription`. */
export interface TranscriptionUpload {
  file: File
  language?: LanguageHint
  title?: string
}

/** Multipart fields of `uploadScreenshot`. */
export interface ScreenshotUpload {
  file: File
  transcriptId?: Uuid
}
