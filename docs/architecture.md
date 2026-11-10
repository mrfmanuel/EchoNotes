# Architecture

> Status: target architecture agreed in M1. The skeleton (health endpoint and placeholder page) exists. Features arrive in M2.

## Overview

```mermaid
flowchart LR
    B[Browser<br/>React SPA] -- "/api/* JSON + multipart" --> A[FastAPI app]
    A -- SQLAlchemy --> P[(Postgres<br/>projects, transcripts,<br/>screenshots bytea)]
    A -- "Transcriber interface" --> T{provider}
    T -->|groq| G[Groq Whisper API<br/>whisper-large-v3-turbo]
    T -->|fake| F[Deterministic fake]
    A -. "OTLP (M4)" .-> O[(Telemetry backend)]
```

- **One container in production.** The Docker image builds the React app (`frontend/dist`). FastAPI serves it as static files and falls back to `index.html` for client routes. `/api/*` is the API. No CORS is needed in prod.
- **Local development.** `docker compose up --build` starts the app and Postgres. For frontend work, `npm run dev` (Vite on :5173) proxies `/api` to uvicorn on :8000.

## Backend (`backend/`)

| Layer | Module (planned) | Responsibility |
|---|---|---|
| API | `app/api/*.py` | FastAPI routers, request validation, HTTP errors |
| Services | `app/services/*.py` | Business rules: slugs, upload validation, export building |
| Transcription | `app/transcription/` | `Transcriber` protocol, `GroqTranscriber`, `FakeTranscriber`, factory chosen by `TRANSCRIBER_PROVIDER` |
| Persistence | `app/db/` (+ `alembic/`) | Async SQLAlchemy 2 models and session (`get_session` dependency), psycopg 3 driver; Alembic migrations in `backend/alembic/` |
| Settings | `app/config.py` | `pydantic-settings`, reads process env vars only (see `.env.example`); `DATABASE_URL` `postgres://`/`postgresql://` is normalized to `postgresql+psycopg://` |
| Logging | `app/logging.py`, `app/middleware.py` | JSON logs, `X-Request-ID` middleware, one access line per request (see [observability.md](observability.md#logging-m2)) |
| SPA | `app/spa.py` | When `STATIC_DIR` holds the built SPA (set in the Docker image): `/assets/*` static, `index.html` fallback for non-`/api` GETs, unknown `/api/*` stays JSON 404. Registered last in `create_app()` |

The backend version lives only in `backend/pyproject.toml`; `app/__init__.py` reads it with `importlib.metadata`.

### Transcriber interface

```python
class Transcriber(Protocol):
    name: str
    async def transcribe(self, audio: bytes, filename: str, content_type: str,
                         language: str | None) -> TranscriptionResult: ...

@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None
    duration_seconds: float | None
```

- **groq**: `POST {GROQ_BASE_URL}/audio/transcriptions` (multipart: `file`, `model=whisper-large-v3-turbo`, `response_format=verbose_json`, `temperature=0`, optional `language`) with `Authorization: Bearer $GROQ_API_KEY` and a timeout. Errors map to `502` and timeouts to `504`.
- **fake**: returns a deterministic text derived from the filename and the byte length (for example `"[fake transcript] lecture.m4a (12345 bytes)"`), the language hint (or `en`) and a duration computed from the size. It needs no network.

### Data model

```mermaid
erDiagram
    PROJECT ||--o{ TRANSCRIPT : contains
    PROJECT ||--o{ SCREENSHOT : contains
    TRANSCRIPT |o--o{ SCREENSHOT : "optionally linked"
    PROJECT {
        uuid id PK
        string name
        string slug UK
        timestamptz created_at
        timestamptz updated_at
    }
    TRANSCRIPT {
        uuid id PK
        uuid project_id FK
        string title
        string slug
        text text
        string language
        float duration_seconds
        string provider
        string source_filename
        timestamptz created_at
        timestamptz updated_at
    }
    SCREENSHOT {
        uuid id PK
        uuid project_id FK
        uuid transcript_id FK "nullable, ON DELETE SET NULL"
        string filename
        string content_type
        int size_bytes
        bytea data
        timestamptz created_at
    }
```

- `ON DELETE CASCADE` from project to transcripts and screenshots, and `ON DELETE SET NULL` from transcript to screenshot.
- List endpoints never select `screenshot.data` (they load metadata only).

## Frontend (`frontend/`)

- Vite + React 19 + TypeScript (strict), React Router v7 (data router, so `useBlocker` can warn about unsaved changes). No UI framework: one small CSS design system in `src/index.css` (CSS variables, light + dark via `prefers-color-scheme`, responsive down to 360px).
- `src/api/types.ts` mirrors the `openapi.yaml` schemas. `src/api/client.ts` is a typed fetch wrapper for **every** operation (base URL `''`, so the SPA calls same-origin `/api`) and throws `ApiError { status, code, detail }`. Components get the client from `ApiProvider` / `useApi()` (`src/api/context.ts`), so tests inject a mock.
- Routes (`src/routes.tsx`): `/` → `ProjectsPage` (list, create), `/projects/:projectId` → `ProjectPage` (rename/delete, upload/record with language hint, transcript list; screenshot gallery, paste handler and Export ZIP are added by #20/#21 in the marked section), `/transcripts/:transcriptId` → `TranscriptPage` (edit, copy, download `.md`/`.txt` via `<a href download>` to the API, delete, linked screenshots).
- Recording uses `MediaRecorder` (`audio/webm;codecs=opus` with a fallback to `audio/ogg`) and uploads `recording-<timestamp>.webm|ogg`. Audio files are checked client-side (extension, 25 MB) before any request.

## Cross-cutting

- **Privacy:** audio is held in memory only for the request. Logs contain IDs, sizes and status codes, never content (see [observability.md](observability.md)).
- **Errors:** JSON `{"detail": "...", "code": "..."}` as defined in `openapi.yaml`.
- **Config:** 12-factor env vars only.
