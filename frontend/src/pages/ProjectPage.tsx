import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client'
import { useApi } from '../api/context'
import { genericErrorMessage } from '../api/errors'
import type { ProjectDetail, TranscriptSummary } from '../api/types'
import { ExportButton } from '../components/ExportButton'
import { ProjectHeader } from '../components/ProjectHeader'
import { ScreenshotGallery } from '../components/ScreenshotGallery'
import { SummaryPanel } from '../components/SummaryPanel'
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

/** A single project: rename/delete, audio upload/record, transcripts, screenshots, export. */
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

      <section id="project-screenshots" aria-labelledby="screenshots-heading">
        <h2 id="screenshots-heading">
          Screenshots <span className="count">({project.screenshots.length})</span>
        </h2>
        <ScreenshotGallery
          projectId={project.id}
          screenshots={project.screenshots}
          transcripts={project.transcripts}
          onChange={(screenshots) =>
            setData({ ...project, screenshots, screenshot_count: screenshots.length })
          }
        />
      </section>

      <section className="card export-bar" aria-labelledby="export-heading">
        <div className="export-intro">
          <h2 id="export-heading">Export</h2>
          <p className="hint">
            Download {pluralize(project.transcripts.length, 'transcript')} and{' '}
            {pluralize(project.screenshots.length, 'screenshot')} as one ZIP with a README index,
            or generate an AI summary as one HTML page.
          </p>
        </div>
        <ExportButton projectId={project.id} projectSlug={project.slug} />
        <SummaryPanel
          key={project.id}
          projectId={project.id}
          transcriptCount={project.transcripts.length}
        />
      </section>
    </div>
  )
}
