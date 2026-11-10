import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client'
import { useApi } from '../api/context'
import { genericErrorMessage } from '../api/errors'
import type { ProjectDetail, TranscriptSummary } from '../api/types'
import { ProjectHeader } from '../components/ProjectHeader'
import { LoadError, Loading, NotFound } from '../components/StatusViews'
import { UploadForm } from '../components/UploadForm'
import { formatDate, formatDuration, formatLanguage, pluralize } from '../lib/format'
import { useLoad } from '../lib/useLoad'

function TranscriptList({ transcripts }: { transcripts: TranscriptSummary[] }) {
  if (transcripts.length === 0) {
    return (
      <div className="empty-state">
        <p>No transcripts yet. Upload or record audio above to create the first one.</p>
      </div>
    )
  }
  return (
    <ul className="item-list" aria-label="Transcripts">
      {transcripts.map((transcript) => (
        <li key={transcript.id} className="item">
          <Link to={`/transcripts/${transcript.id}`} className="item-title">
            {transcript.title}
          </Link>
          <span className="item-meta">
            {formatDate(transcript.created_at)} · {formatLanguage(transcript.language)} ·{' '}
            {formatDuration(transcript.duration_seconds)}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** A single project: rename/delete, upload or record audio, transcripts list. */
export function ProjectPage() {
  const { projectId = '' } = useParams()
  const api = useApi()
  const navigate = useNavigate()
  const { state, reload, setData } = useLoad(() => api.getProject(projectId), projectId)

  if (state.status === 'loading') return <Loading label="Loading project…" />
  if (state.status === 'error') {
    if (state.error instanceof ApiError && state.error.status === 404) {
      return <NotFound what="Project" />
    }
    return <LoadError message={genericErrorMessage(state.error)} onRetry={reload} />
  }

  const project: ProjectDetail = state.data

  return (
    <div className="page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Projects</Link>
      </nav>
      <ProjectHeader
        project={project}
        onRenamed={(renamed) => setData({ ...project, ...renamed })}
        onDeleted={() => navigate('/')}
      />

      <section className="card" aria-labelledby="new-transcript-heading">
        <h2 id="new-transcript-heading">New transcript</h2>
        <UploadForm
          projectId={project.id}
          onCreated={(transcript) => navigate(`/transcripts/${transcript.id}`)}
        />
      </section>

      <section aria-labelledby="transcripts-heading">
        <h2 id="transcripts-heading">
          Transcripts <span className="count">({project.transcripts.length})</span>
        </h2>
        <TranscriptList transcripts={project.transcripts} />
      </section>

      {/*
        ===== PR-G PLACEHOLDER (#20 / #21): screenshot gallery, Ctrl+V paste handler and the
        "Export ZIP" button (api.projectExportUrl) go in this section. Keep the section id. =====
      */}
      <section id="project-screenshots" aria-labelledby="screenshots-heading">
        <h2 id="screenshots-heading">Screenshots</h2>
        <p className="hint">
          {pluralize(project.screenshots.length, 'screenshot')} in this project. The gallery and
          ZIP export are coming soon.
        </p>
      </section>
    </div>
  )
}
