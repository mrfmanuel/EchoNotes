import { useState, type FormEvent } from 'react'
import { useApi } from '../api/context'
import { genericErrorMessage } from '../api/errors'
import type { Project } from '../api/types'
import { validateProjectName } from '../lib/validation'

interface ProjectHeaderProps {
  project: Project
  onRenamed: (project: Project) => void
  onDeleted: () => void
}

/** Project title with inline rename (US-03) and delete with confirmation (US-04). */
export function ProjectHeader({ project, onRenamed, onDeleted }: ProjectHeaderProps) {
  const api = useApi()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(project.name)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function startEditing(): void {
    setName(project.name)
    setError(null)
    setEditing(true)
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    const invalid = validateProjectName(name)
    if (invalid) {
      setError(invalid)
      return
    }
    setBusy(true)
    try {
      const updated = await api.renameProject(project.id, { name: name.trim() })
      onRenamed(updated)
      setEditing(false)
      setError(null)
    } catch (err) {
      // An API 422 is shown as the field error (its first message).
      setError(genericErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(): Promise<void> {
    const ok = window.confirm(
      `Delete the project "${project.name}" and all its transcripts and screenshots? ` +
        'This cannot be undone.',
    )
    if (!ok) return
    setBusy(true)
    try {
      await api.deleteProject(project.id)
      onDeleted()
    } catch (err) {
      setError(genericErrorMessage(err))
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <form className="page-header" onSubmit={(event) => void onSubmit(event)} noValidate>
        <div className="field grow">
          <label htmlFor="rename-project">Project name</label>
          <input
            id="rename-project"
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={error ? true : undefined}
            disabled={busy}
            autoFocus
          />
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Save
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      </form>
    )
  }

  return (
    <div className="page-header">
      <h1>{project.name}</h1>
      <div className="actions">
        <button type="button" className="btn" onClick={startEditing} disabled={busy}>
          Rename
        </button>
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => void onDelete()}
          disabled={busy}
        >
          Delete project
        </button>
      </div>
      {error && (
        <p className="alert alert-error full-width" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
