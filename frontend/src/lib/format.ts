import type { Health } from '../api/types'

const SHORT_COMMIT_LENGTH = 7
const UNKNOWN_COMMIT = 'unknown'

/** `v0.1.0 · a1b2c3d · dev` (US-17 AC4). An `unknown` (or empty) commit is shown as `unknown`. */
export function formatBuildInfo(health: Pick<Health, 'version' | 'commit' | 'environment'>): string {
  const commit =
    health.commit && health.commit !== UNKNOWN_COMMIT
      ? health.commit.slice(0, SHORT_COMMIT_LENGTH)
      : UNKNOWN_COMMIT
  return `v${health.version} · ${commit} · ${health.environment}`
}

const LANGUAGE_NAMES: Record<string, string> = {
  en: 'English',
  es: 'Spanish',
  pt: 'Portuguese',
}

/** `YYYY-MM-DD` (UTC), the same date format as the `.md` download. */
export function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? 'unknown' : date.toISOString().slice(0, 10)
}

/** `m:ss`, or `unknown` when the provider did not return a duration. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return 'unknown'
  const total = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return `${minutes}:${rest.toString().padStart(2, '0')}`
}

/** Human-readable language name for an ISO-639-1 code. */
export function formatLanguage(code: string | null | undefined): string {
  if (!code) return 'unknown'
  return LANGUAGE_NAMES[code] ?? code
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`
}

/** `512 B`, `12.3 KB`, `4.5 MB` (1 KB = 1024 bytes, like the upload limits). */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return 'unknown'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
