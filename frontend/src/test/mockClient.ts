import { vi, type Mock } from 'vitest'
import { ApiError, createApiClient, type ApiClient } from '../api/client'
import type {
  ErrorCode,
  Project,
  ProjectDetail,
  Screenshot,
  Summary,
  Transcript,
} from '../api/types'

type Method = Exclude<
  keyof ApiClient,
  'transcriptDownloadUrl' | 'screenshotImageUrl' | 'projectExportUrl' | 'summaryDownloadUrl'
>

export type MockApiClient = ApiClient & { [K in Method]: Mock<ApiClient[K]> }

/**
 * Every API method is a vi.fn() that rejects until a test mocks it; URL builders are real.
 * Exception: `getLatestSummary` resolves `null` ("no summary yet"), because every project page
 * render calls it and most project page tests are not about summaries.
 */
export function createMockClient(): MockApiClient {
  const real = createApiClient('')
  const notMocked = (name: string) =>
    vi.fn(() => Promise.reject(new Error(`${name} not mocked in this test`)))
  return {
    getHealth: notMocked('getHealth'),
    listProjects: notMocked('listProjects'),
    createProject: notMocked('createProject'),
    getProject: notMocked('getProject'),
    renameProject: notMocked('renameProject'),
    deleteProject: notMocked('deleteProject'),
    listTranscriptions: notMocked('listTranscriptions'),
    createTranscription: notMocked('createTranscription'),
    getTranscription: notMocked('getTranscription'),
    updateTranscription: notMocked('updateTranscription'),
    deleteTranscription: notMocked('deleteTranscription'),
    listScreenshots: notMocked('listScreenshots'),
    uploadScreenshot: notMocked('uploadScreenshot'),
    updateScreenshot: notMocked('updateScreenshot'),
    deleteScreenshot: notMocked('deleteScreenshot'),
    exportProject: notMocked('exportProject'),
    startSummary: notMocked('startSummary'),
    getLatestSummary: vi.fn(() => Promise.resolve(null)),
    transcriptDownloadUrl: real.transcriptDownloadUrl,
    screenshotImageUrl: real.screenshotImageUrl,
    projectExportUrl: real.projectExportUrl,
    summaryDownloadUrl: real.summaryDownloadUrl,
  } as MockApiClient
}

export function apiError(status: number, detail = 'error', code?: ErrorCode): ApiError {
  return new ApiError(status, detail, code)
}

export const PROJECT_ID = '11111111-1111-4111-8111-111111111111'
export const TRANSCRIPT_ID = '22222222-2222-4222-8222-222222222222'

export function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: PROJECT_ID,
    name: 'Lecture notes',
    slug: 'lecture-notes',
    transcript_count: 0,
    screenshot_count: 0,
    created_at: '2026-11-01T10:00:00Z',
    updated_at: '2026-11-01T10:00:00Z',
    ...overrides,
  }
}

export function makeProjectDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return { ...makeProject(), transcripts: [], screenshots: [], ...overrides }
}

export function makeTranscript(overrides: Partial<Transcript> = {}): Transcript {
  return {
    id: TRANSCRIPT_ID,
    project_id: PROJECT_ID,
    title: 'Week 1',
    slug: 'week-1',
    language: 'es',
    duration_seconds: 125,
    provider: 'fake',
    created_at: '2026-11-02T09:30:00Z',
    updated_at: '2026-11-02T09:30:00Z',
    text: 'Hola a todos.',
    source_filename: 'week-1.mp3',
    ...overrides,
  }
}

export function makeScreenshot(overrides: Partial<Screenshot> = {}): Screenshot {
  const id = overrides.id ?? '33333333-3333-4333-8333-333333333333'
  return {
    id,
    project_id: PROJECT_ID,
    transcript_id: null,
    filename: 'slide.png',
    content_type: 'image/png',
    size_bytes: 1234,
    image_url: `/api/screenshots/${id}/image`,
    created_at: '2026-11-02T09:31:00Z',
    ...overrides,
  }
}

export const SUMMARY_ID = '44444444-4444-4444-8444-444444444444'

export function makeSummary(overrides: Partial<Summary> = {}): Summary {
  return {
    id: SUMMARY_ID,
    project_id: PROJECT_ID,
    status: 'pending',
    provider: 'fake',
    model: null,
    created_at: '2026-11-11T10:00:00Z',
    started_at: null,
    finished_at: null,
    error_code: null,
    truncated: false,
    transcript_count: 1,
    image_count: 0,
    html: null,
    ...overrides,
  }
}
