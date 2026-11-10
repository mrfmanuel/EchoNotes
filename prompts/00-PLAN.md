# EchoNotes — Final Project plan (AI Dev Tools Zoomcamp 2026, Project 2)

Deadline: **Mon 16 Nov 2026, 23:00** (course platform) — plus 3 peer reviews.
Submission form: GitHub link, Commit ID, learning-in-public links (optional), hours spent, FAQ PR (optional), certificate name.

## The app
Audio-to-text notebook. Users create **projects** (one "folder" each), upload or record audio, get a
transcript (Groq Whisper API), copy it, download it as `.md` / `.txt`, attach screenshots
(upload or Ctrl+V paste), and export a whole project as a ZIP with a folder structure.

Stack: FastAPI + SQLAlchemy/Alembic + Postgres · React (Vite, TS) · Docker Compose · GitHub Actions · Render (dev + prod).

## Claude Code prompts (4 long prompts)

| # | File | Covers rubric criteria | Manual steps for Manuel before/after |
|---|------|------------------------|--------------------------------------|
| P1 | `P1-foundation.md` | Problem description, Product spec + public tracker, Agent team, Context mgmt, CI on PRs | Before: tools installed, `gh auth login`. After: skim spec (Cowork reviews too) |
| P2 | `P2-build-app.md` | Application, Testing, Containerization (+ tracker evidence via PRs) | Before: Groq API key in `.env` |
| P3 | `P3-deploy-cicd.md` | Deployment, CI/CD (dev auto + prod manual + rollback) | Before/during: Render + DB setup, GitHub secrets |
| P4 | `P4-observability-oncall.md` | Observability, Alert on user impact, On-call agent, final rubric audit | After: demo screenshots, submit |

Cowork (this chat) in parallel: reviews the repo against the rubric after each prompt, writes the next
prompt, guides the manual web steps (GitHub, Groq, Render/Neon), and prepares the submission + peer reviews.

## Target score (pass = 10/24)
Problem 2 · Spec 2 · Agent team 2 · Context 2 · App 2 · Testing 2 · Containers 2 · Deploy 2 · CI/CD 2–3 · Observability 1–2 · Alert 1 · On-call 0–2 → realistic 20+.
