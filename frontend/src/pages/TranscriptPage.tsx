import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client'
import { useApi } from '../api/context'
import { genericErrorMessage } from '../api/errors'
import type { Screenshot, Transcript } from '../api/types'
import { LoadError, Loading, NotFound } from '../components/StatusViews'
import { TranscriptEditor } from '../components/TranscriptEditor'
import { useLoad } from '../lib/useLoad'

interface TranscriptView {
  transcript: Transcript
  projectName: string | null
  linkedScreenshots: Screenshot[]
}

function LinkedScreenshots({ screenshots }: { screenshots: Screenshot[] }) {
  if (screenshots.length === 0) {
    return <p className="hint">No screenshots are linked to this transcript.</p>
  }
  return (
    <ul className="thumb-grid" aria-label="Linked screenshots">
      {screenshots.map((shot) => (
        <li key={shot.id}>
          <a href={shot.image_url} target="_blank" rel="noreferrer" className="thumb">
            <img src={shot.image_url} alt={shot.filename} loading="lazy" />
          </a>
        </li>
      ))}
    </ul>
  )
}

/** One transcript: view, edit, copy, download, delete (US-08..US-11, US-14 AC3). */
export function TranscriptPage() {
  const { transcriptId = '' } = useParams()
  const api = useApi()
  const navigate = useNavigate()

  const { state, reload, setData } = useLoad<TranscriptView>(async () => {
    const transcript = await api.getTranscription(transcriptId)
    // Linked screenshots come from the project detail (grooming of #19). A failure here must not
    // hide the transcript itself.
    const project = await api.getProject(transcript.project_id).catch(() => null)
    return {
      transcript,
      projectName: project?.name ?? null,
      linkedScreenshots: (project?.screenshots ?? []).filter(
        (shot) => shot.transcript_id === transcript.id,
      ),
    }
  }, transcriptId)

  if (state.status === 'loading') return <Loading label="Loading transcript…" />
  if (state.status === 'error') {
    if (state.error instanceof ApiError && state.error.status === 404) {
      return <NotFound what="Transcript" />
    }
    return <LoadError message={genericErrorMessage(state.error)} onRetry={reload} />
  }

  const { transcript, projectName, linkedScreenshots } = state.data
  const projectPath = `/projects/${transcript.project_id}`

  return (
    <div className="page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Projects</Link>
        <span aria-hidden="true">/</span>
        <Link to={projectPath}>{projectName ?? 'Project'}</Link>
      </nav>

      <TranscriptEditor
        key={transcript.id}
        transcript={transcript}
        onSaved={(saved) => setData({ ...state.data, transcript: saved })}
        onDeleted={() => navigate(projectPath)}
      />

      <section aria-labelledby="linked-screenshots-heading">
        <h2 id="linked-screenshots-heading">Linked screenshots</h2>
        <LinkedScreenshots screenshots={linkedScreenshots} />
      </section>
    </div>
  )
}
