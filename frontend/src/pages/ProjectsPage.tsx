import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { useApi } from '../api/context'
import { genericErrorMessage } from '../api/errors'
import type { Project } from '../api/types'
import { LoadError, Loading } from '../components/StatusViews'
import { formatDate, pluralize } from '../lib/format'
import { useLoad } from '../lib/useLoad'
import { validateProjectName } from '../lib/validation'

/** Newest update first (US-02 AC1); the API already sorts, this keeps the UI stable. */
function byUpdatedDesc(a: Project, b: Project): number {
  return b.updated_at.localeCompare(a.updated_at)
}

function CreateProjectForm() {
  const api = useApi()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    const invalid = validateProjectName(name)
    if (invalid) {
      setError(invalid)
      return
    }
    setError(null)
    setSaving(true)
    try {
      const project = await api.createProject({ name: name.trim() })
      navigate(`/projects/${project.id}`)
    } catch (err) {
      // An API 422 is shown as the field error (its first message).
      setError(genericErrorMessage(err))
      setSaving(false)
    }
  }

  return (
    <form className="card create-form" onSubmit={(event) => void onSubmit(event)} noValidate>
      <div className="field">
        <label htmlFor="new-project-name">New project name</label>
        <div className="inline-field">
          <input
            id="new-project-name"
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Lecture notes"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? 'new-project-error' : undefined}
            disabled={saving}
          />
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Creating…' : 'Create project'}
          </button>
        </div>
        {error && (
          <p id="new-project-error" className="field-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </form>
  )
}

function ProjectList({ projects }: { projects: Project[] }) {
  if (projects.length === 0) {
    return (
      <div className="empty-state">
        <h2>No projects yet</h2>
        <p>Create your first project above to start turning audio into notes.</p>
      </div>
    )
  }
  return (
    <ul className="item-list" aria-label="Projects">
      {[...projects].sort(byUpdatedDesc).map((project) => (
        <li key={project.id} className="item">
          <Link to={`/projects/${project.id}`} className="item-title">
            {project.name}
          </Link>
          <span className="item-meta">
            {pluralize(project.transcript_count, 'transcript')} ·{' '}
            {pluralize(project.screenshot_count, 'screenshot')} · updated{' '}
            {formatDate(project.updated_at)}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** Home page: list and create projects (US-01, US-02). */
export function ProjectsPage() {
  const api = useApi()
  const { state, reload } = useLoad(() => api.listProjects(), 'projects')

  return (
    <div className="page">
      <h1>Projects</h1>
      <CreateProjectForm />
      <section aria-labelledby="projects-heading">
        <h2 id="projects-heading" className="visually-hidden">
          Your projects
        </h2>
        {state.status === 'loading' && <Loading label="Loading projects…" />}
        {state.status === 'error' && (
          <LoadError message={genericErrorMessage(state.error)} onRetry={reload} />
        )}
        {state.status === 'ready' && <ProjectList projects={state.data} />}
      </section>
    </div>
  )
}
