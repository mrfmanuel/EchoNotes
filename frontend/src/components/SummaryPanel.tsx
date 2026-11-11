import { useCallback, useEffect, useId, useState } from 'react'
import { useApi } from '../api/context'
import { summaryFailureMessage, summaryRequestErrorMessage } from '../api/errors'
import type { Summary, SummaryStatus } from '../api/types'
import { formatDate, pluralize } from '../lib/format'

/** US-22 AC8: how often `GET .../summaries/latest` is polled while a job is active. */
export const SUMMARY_POLL_MS = 3000

/**
 * The summary HTML comes from an LLM, so it is untrusted even after server-side sanitizing.
 * An empty `sandbox` applies every restriction: no scripts, a unique (opaque) origin, no forms,
 * no popups, no top navigation (US-22 AC10).
 */
export const SUMMARY_IFRAME_SANDBOX = ''

export const SUMMARY_PRIVACY_NOTE =
  "Generating a summary sends this project's transcripts and screenshots to the configured AI " +
  "provider (Gemini's free tier may use data to improve Google products). Don't use it for " +
  'sensitive content.'

export const NO_TRANSCRIPTS_HINT = 'Add at least one transcript to generate a summary.'

function isActive(status: SummaryStatus): boolean {
  return status === 'pending' || status === 'running'
}

interface SummaryPanelProps {
  projectId: string
  transcriptCount: number
}

/**
 * "Generate summary" (US-22 AC6–AC11): starts a job, polls the latest summary every 3 s while it
 * is pending/running, shows failures with Retry, and shows the last succeeded summary in a
 * sandboxed iframe with a download link. Renders two blocks: the action (placed next to
 * "Export ZIP") and the details (full width below it).
 */
export function SummaryPanel({ projectId, transcriptCount }: SummaryPanelProps) {
  const api = useApi()
  const ids = useId()
  const [latest, setLatest] = useState<Summary | null>(null)
  // The last succeeded summary stays visible while a regeneration runs or after it fails (AC5).
  const [shown, setShown] = useState<Summary | null>(null)
  const [starting, setStarting] = useState(false)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [viewOpen, setViewOpen] = useState(false)
  const [pollRound, setPollRound] = useState(0)

  const apply = useCallback((summary: Summary | null) => {
    setLatest(summary)
    if (summary?.status === 'succeeded') setShown(summary)
  }, [])

  // AC7: on open, load the latest summary (an active one resumes the Generating… state).
  useEffect(() => {
    let mounted = true
    api.getLatestSummary(projectId).then(
      (summary) => mounted && apply(summary),
      (error: unknown) => mounted && setRequestError(summaryRequestErrorMessage(error)),
    )
    return () => {
      mounted = false
    }
  }, [api, projectId, apply])

  const polling = latest !== null && isActive(latest.status)

  // AC8: one poll every SUMMARY_POLL_MS while active; stops at a terminal state and on unmount.
  useEffect(() => {
    if (!polling) return undefined
    let cancelled = false
    const timer = setTimeout(() => {
      api.getLatestSummary(projectId).then(
        (summary) => {
          if (cancelled) return
          apply(summary)
          if (summary?.status === 'succeeded') setViewOpen(true)
          setPollRound((n) => n + 1)
        },
        // A failed poll (e.g. a network blip) is retried on the next round.
        () => !cancelled && setPollRound((n) => n + 1),
      )
    }, SUMMARY_POLL_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [api, projectId, polling, pollRound, apply])

  async function onGenerate(): Promise<void> {
    setRequestError(null)
    setStarting(true)
    try {
      apply(await api.startSummary(projectId))
    } catch (error) {
      setRequestError(summaryRequestErrorMessage(error))
    } finally {
      setStarting(false)
    }
  }

  const noTranscripts = transcriptCount < 1
  const generating = starting || polling
  const hintId = `${ids}-hint`
  const frameId = `${ids}-frame`

  return (
    <>
      <div className="summary-action">
        <button
          type="button"
          className="btn"
          onClick={() => void onGenerate()}
          disabled={noTranscripts || generating}
          aria-busy={generating}
          aria-describedby={noTranscripts ? hintId : undefined}
          title={noTranscripts ? NO_TRANSCRIPTS_HINT : undefined}
        >
          {generating ? (
            <>
              <span className="spinner" aria-hidden="true" /> Generating…
            </>
          ) : (
            'Generate summary'
          )}
        </button>
      </div>

      <div className="summary-details">
        <p className="hint">{SUMMARY_PRIVACY_NOTE}</p>
        {noTranscripts && (
          <p className="hint" id={hintId}>
            {NO_TRANSCRIPTS_HINT}
          </p>
        )}
        {generating && (
          <p className="status" role="status">
            Generating the AI summary. This can take up to a minute or two.
          </p>
        )}
        {requestError && (
          <p className="alert alert-error" role="alert">
            {requestError}
          </p>
        )}
        {latest?.status === 'failed' && !generating && (
          <div className="alert alert-error summary-failed" role="alert">
            <p>{summaryFailureMessage(latest.error_code)}</p>
            <button
              type="button"
              className="btn btn-small"
              onClick={() => void onGenerate()}
              disabled={noTranscripts}
            >
              Retry
            </button>
          </div>
        )}
        {shown && (
          <div className="summary-result">
            <p className="item-meta">
              Summary from {formatDate(shown.finished_at ?? shown.created_at)} ·{' '}
              {shown.model ? `${shown.provider} (${shown.model})` : shown.provider} ·{' '}
              {pluralize(shown.transcript_count, 'transcript')},{' '}
              {pluralize(shown.image_count, 'screenshot')}
              {shown.truncated && (
                <>
                  {' '}
                  <span className="badge badge-warn">Truncated content</span>
                </>
              )}
            </p>
            <div className="actions">
              <button
                type="button"
                className="btn btn-small"
                aria-expanded={viewOpen}
                aria-controls={frameId}
                onClick={() => setViewOpen((open) => !open)}
              >
                View summary
              </button>
              <a
                className="btn btn-small"
                href={api.summaryDownloadUrl(projectId, shown.id)}
                download="summary.html"
              >
                Download summary.html
              </a>
            </div>
            {viewOpen && (
              <iframe
                id={frameId}
                className="summary-frame"
                title="Project summary"
                sandbox={SUMMARY_IFRAME_SANDBOX}
                srcDoc={shown.html ?? ''}
              />
            )}
          </div>
        )}
      </div>
    </>
  )
}
