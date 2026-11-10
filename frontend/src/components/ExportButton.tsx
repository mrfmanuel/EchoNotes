import { useState } from 'react'
import { useApi } from '../api/context'
import { exportErrorMessage } from '../api/errors'
import { saveBlob } from '../lib/download'

interface ExportButtonProps {
  projectId: string
  projectSlug: string
}

/** "Export ZIP" (US-16): fetches the ZIP, shows a busy state, saves it, reports errors (#21). */
export function ExportButton({ projectId, projectSlug }: ExportButtonProps) {
  const api = useApi()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onExport(): Promise<void> {
    setError(null)
    setBusy(true)
    try {
      const { blob, filename } = await api.exportProject(projectId)
      saveBlob(blob, filename ?? `${projectSlug}.zip`)
    } catch (err) {
      setError(exportErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="export-action">
      <button
        type="button"
        className="btn btn-primary"
        onClick={() => void onExport()}
        disabled={busy}
        aria-busy={busy}
      >
        {busy ? (
          <>
            <span className="spinner" aria-hidden="true" /> Preparing…
          </>
        ) : (
          'Export ZIP'
        )}
      </button>
      {error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
