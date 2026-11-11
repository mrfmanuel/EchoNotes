// Types mirroring the schemas in openapi.yaml (components/schemas). Keep in sync with the contract.

/** UUID string (`format: uuid`). */
export type Uuid = string
/** ISO 8601 date-time string (`format: date-time`). */
export type DateTimeString = string

export interface Health {
  status: 'ok' | 'degraded'
  version: string
  database: 'ok' | 'error' | 'skipped'
  /** Deployed git SHA (full), or `unknown`. */
  commit: string
  environment: 'local' | 'dev' | 'prod'
}

export type ErrorCode =
  | 'not_found'
  | 'validation_error'
  | 'unsupported_media_type'
  | 'audio_too_large'
  | 'image_too_large'
  | 'provider_error'
  | 'provider_timeout'
  | 'no_transcripts'
  | 'summary_not_found'
  | 'summary_not_ready'

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

/** `Summary.status` (US-22). `pending` and `running` are active; the others are terminal. */
export type SummaryStatus = 'pending' | 'running' | 'succeeded' | 'failed'

/** Safe `Summary.error_code` values (US-22 AC18–AC19); never raw provider text. */
export type SummaryErrorCode = 'provider_error' | 'provider_timeout' | 'interrupted' | 'internal_error'

/** `Summary` schema: an AI-generated HTML project summary job (US-22). */
export interface Summary {
  id: Uuid
  project_id: Uuid
  status: SummaryStatus
  /** `gemini`, `groq` or `fake`. */
  provider: string
  /** The model that actually produced it (the fallback model when used). */
  model: string | null
  created_at: DateTimeString
  started_at: DateTimeString | null
  finished_at: DateTimeString | null
  error_code: SummaryErrorCode | null
  /** The content sent to the provider was capped. */
  truncated: boolean
  transcript_count: number
  image_count: number
  /** The full self-contained HTML document, only when `succeeded`. */
  html: string | null
}
