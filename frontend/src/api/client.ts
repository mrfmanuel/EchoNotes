// Typed fetch wrapper for every operation in openapi.yaml.
// The base URL is '' so the SPA calls same-origin /api (Vite proxies it in development).

import type {
  DownloadFormat,
  ErrorBody,
  ErrorCode,
  Health,
  Project,
  ProjectCreate,
  ProjectDetail,
  ProjectUpdate,
  Screenshot,
  ScreenshotUpdate,
  ScreenshotUpload,
  Summary,
  Transcript,
  TranscriptionUpload,
  TranscriptSummary,
  TranscriptUpdate,
  Uuid,
  ValidationIssue,
} from './types'

/** Status used when the request never reached the server (network failure). */
export const NETWORK_ERROR_STATUS = 0

/** Error thrown for any non-2xx response or network failure. */
export class ApiError extends Error {
  readonly status: number
  readonly code: ErrorCode | undefined
  readonly detail: string | ValidationIssue[]

  constructor(status: number, detail: string | ValidationIssue[], code?: ErrorCode) {
    super(ApiError.describe(status, detail))
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }

  /** First human-readable message of the error (handles the 422 `detail` list). */
  get firstMessage(): string {
    if (typeof this.detail === 'string') return this.detail
    const first = this.detail.find((issue) => typeof issue.msg === 'string')
    return first?.msg ?? 'Invalid input'
  }

  private static describe(status: number, detail: string | ValidationIssue[]): string {
    const text = typeof detail === 'string' ? detail : 'Validation error'
    return status === NETWORK_ERROR_STATUS ? text : `HTTP ${status}: ${text}`
  }
}

export interface ApiClient {
  getHealth(): Promise<Health>
  listProjects(): Promise<Project[]>
  createProject(body: ProjectCreate): Promise<Project>
  getProject(projectId: Uuid): Promise<ProjectDetail>
  renameProject(projectId: Uuid, body: ProjectUpdate): Promise<Project>
  deleteProject(projectId: Uuid): Promise<void>
  listTranscriptions(projectId: Uuid): Promise<TranscriptSummary[]>
  createTranscription(projectId: Uuid, upload: TranscriptionUpload): Promise<Transcript>
  getTranscription(transcriptId: Uuid): Promise<Transcript>
  updateTranscription(transcriptId: Uuid, body: TranscriptUpdate): Promise<Transcript>
  deleteTranscription(transcriptId: Uuid): Promise<void>
  listScreenshots(projectId: Uuid): Promise<Screenshot[]>
  uploadScreenshot(projectId: Uuid, upload: ScreenshotUpload): Promise<Screenshot>
  updateScreenshot(screenshotId: Uuid, body: ScreenshotUpdate): Promise<Screenshot>
  deleteScreenshot(screenshotId: Uuid): Promise<void>
  /** URL of `downloadTranscription`, for `<a href download>`. */
  transcriptDownloadUrl(transcriptId: Uuid, format: DownloadFormat): string
  /** URL of `getScreenshotImage`, for `<img src>`. */
  screenshotImageUrl(screenshotId: Uuid): string
  /** URL of `exportProject`. */
  projectExportUrl(projectId: Uuid): string
  /** `exportProject`: the ZIP as a Blob plus the filename from `Content-Disposition` (or null). */
  exportProject(projectId: Uuid): Promise<ExportFile>
  /** `startSummary` (POST, 202): a new pending job, or the project's already active one. */
  startSummary(projectId: Uuid): Promise<Summary>
  /** `getLatestSummary`: the most recently created summary, or `null` when there is none (404). */
  getLatestSummary(projectId: Uuid): Promise<Summary | null>
  /** URL of `downloadSummary`, for `<a href download>`. */
  summaryDownloadUrl(projectId: Uuid, summaryId: Uuid): string
}

/** Result of `exportProject`. */
export interface ExportFile {
  blob: Blob
  filename: string | null
}

/** Filename from a `Content-Disposition` header (`filename*=UTF-8''…` or `filename="…"`). */
export function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const extended = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header)
  if (extended) {
    try {
      return decodeURIComponent(extended[1].trim())
    } catch {
      // Malformed encoding; fall back to the plain filename parameter.
    }
  }
  const plain = /filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;\s]+)/.exec(header)
  const name = plain?.[1] ?? plain?.[2]
  return name ? name.trim() : null
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

interface RequestOptions {
  method?: string
  json?: unknown
  form?: FormData
  /** Extra non-2xx statuses whose JSON body is a valid result (health 503). */
  okStatuses?: number[]
}

const enc = encodeURIComponent

async function parseErrorBody(response: Response): Promise<ErrorBody> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body) return body as ErrorBody
  } catch {
    // Non-JSON error body (e.g. a proxy page); fall through to the status text.
  }
  return { detail: response.statusText || 'Request failed' }
}

export function createApiClient(baseUrl = '', fetchImpl?: FetchLike): ApiClient {
  const doFetch: FetchLike = fetchImpl ?? ((input, init) => fetch(input, init))

  /** Sends the request and returns the accepted response, or throws `ApiError`. */
  async function send(path: string, options: RequestOptions = {}): Promise<Response> {
    const init: RequestInit = { method: options.method ?? 'GET', headers: {} }
    if (options.json !== undefined) {
      init.headers = { 'Content-Type': 'application/json' }
      init.body = JSON.stringify(options.json)
    } else if (options.form) {
      init.body = options.form
    }

    let response: Response
    try {
      response = await doFetch(`${baseUrl}${path}`, init)
    } catch {
      throw new ApiError(NETWORK_ERROR_STATUS, 'Could not reach the server.')
    }

    const accepted = response.ok || (options.okStatuses ?? []).includes(response.status)
    if (!accepted) {
      const body = await parseErrorBody(response)
      throw new ApiError(response.status, body.detail, body.code)
    }
    return response
  }

  async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const response = await send(path, options)
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  async function exportProject(projectId: Uuid): Promise<ExportFile> {
    const response = await send(`/api/projects/${enc(projectId)}/export`)
    let blob: Blob
    try {
      blob = await response.blob()
    } catch {
      throw new ApiError(NETWORK_ERROR_STATUS, 'The download was interrupted.')
    }
    return { blob, filename: filenameFromDisposition(response.headers.get('Content-Disposition')) }
  }

  async function getLatestSummary(projectId: Uuid): Promise<Summary | null> {
    try {
      return await request<Summary>(`/api/projects/${enc(projectId)}/summaries/latest`)
    } catch (error) {
      // US-22 AC2: 404 means the project never had a summary (or the project is gone).
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
  }

  return {
    getHealth: () => request<Health>('/api/health', { okStatuses: [503] }),
    listProjects: () => request<Project[]>('/api/projects'),
    createProject: (body) => request<Project>('/api/projects', { method: 'POST', json: body }),
    getProject: (projectId) => request<ProjectDetail>(`/api/projects/${enc(projectId)}`),
    renameProject: (projectId, body) =>
      request<Project>(`/api/projects/${enc(projectId)}`, { method: 'PATCH', json: body }),
    deleteProject: (projectId) =>
      request<void>(`/api/projects/${enc(projectId)}`, { method: 'DELETE' }),
    listTranscriptions: (projectId) =>
      request<TranscriptSummary[]>(`/api/projects/${enc(projectId)}/transcriptions`),
    createTranscription: (projectId, upload) => {
      const form = new FormData()
      form.append('file', upload.file, upload.file.name)
      // US-07 AC2: "Auto" means no language is sent.
      if (upload.language && upload.language !== 'auto') form.append('language', upload.language)
      if (upload.title) form.append('title', upload.title)
      return request<Transcript>(`/api/projects/${enc(projectId)}/transcriptions`, {
        method: 'POST',
        form,
      })
    },
    getTranscription: (transcriptId) =>
      request<Transcript>(`/api/transcriptions/${enc(transcriptId)}`),
    updateTranscription: (transcriptId, body) =>
      request<Transcript>(`/api/transcriptions/${enc(transcriptId)}`, {
        method: 'PATCH',
        json: body,
      }),
    deleteTranscription: (transcriptId) =>
      request<void>(`/api/transcriptions/${enc(transcriptId)}`, { method: 'DELETE' }),
    listScreenshots: (projectId) =>
      request<Screenshot[]>(`/api/projects/${enc(projectId)}/screenshots`),
    uploadScreenshot: (projectId, upload) => {
      const form = new FormData()
      form.append('file', upload.file, upload.file.name)
      if (upload.transcriptId) form.append('transcript_id', upload.transcriptId)
      return request<Screenshot>(`/api/projects/${enc(projectId)}/screenshots`, {
        method: 'POST',
        form,
      })
    },
    updateScreenshot: (screenshotId, body) =>
      request<Screenshot>(`/api/screenshots/${enc(screenshotId)}`, {
        method: 'PATCH',
        json: body,
      }),
    deleteScreenshot: (screenshotId) =>
      request<void>(`/api/screenshots/${enc(screenshotId)}`, { method: 'DELETE' }),
    transcriptDownloadUrl: (transcriptId, format) =>
      `${baseUrl}/api/transcriptions/${enc(transcriptId)}/download?format=${format}`,
    screenshotImageUrl: (screenshotId) => `${baseUrl}/api/screenshots/${enc(screenshotId)}/image`,
    projectExportUrl: (projectId) => `${baseUrl}/api/projects/${enc(projectId)}/export`,
    exportProject,
    startSummary: (projectId) =>
      request<Summary>(`/api/projects/${enc(projectId)}/summaries`, { method: 'POST' }),
    getLatestSummary,
    summaryDownloadUrl: (projectId, summaryId) =>
      `${baseUrl}/api/projects/${enc(projectId)}/summaries/${enc(summaryId)}/download`,
  }
}
