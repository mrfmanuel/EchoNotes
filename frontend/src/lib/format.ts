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
