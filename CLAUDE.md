# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A course project (A8 GitHub仓库问答与Issue分析系统) — a GitHub Issue analysis platform that syncs public GitHub repositories, classifies files and issues via rules, and displays results in a web UI. This is a **scaffold/groundwork** for a multi-person team project; see [docs/iteration-plan.md](docs/iteration-plan.md) for the full roadmap.

**Key constraint:** The project will later need PostgreSQL, pgvector, Celery, RAG, LLM integration, and multi-Agent workflows — design every new module with a clear adapter/interface boundary so those can slot in without rewriting.

## Commands

### Backend (Python / FastAPI / uv)

```bash
cd backend

# Run dev server (hot-reload, port 8000)
uv run uvicorn app.main:app --reload --port 8000

# Run tests (when they exist)
uv run pytest

# Add a dependency
uv add <package>

# Lint/type-check
uv run ruff check
uv run mypy .
```

### Frontend (React / Vite / TypeScript / npm)

```bash
cd frontend

# Install dependencies
npm install

# Dev server (hot-reload, port 5173)
npm run dev

# Type-check + production build
npm run build

# Lint
npm run lint           # uses oxlint
```

### Environment

- `GITHUB_TOKEN` — optional, set to a GitHub personal access token for higher API rate limits.
- `VITE_API_BASE_URL` — defaults to `http://localhost:8000`, set if backend runs on a different port.

## Architecture

### Backend (`backend/app/`)

```
backend/
└── app/
    ├── main.py                 # FastAPI app factory, CORS middleware, router registration
    ├── core/config.py          # Pydantic-settings config (GitHub token, API URL, CORS origins)
    ├── api/routes/
    │   ├── health.py           # GET /api/health
    │   ├── repositories.py    # POST /api/repositories/sync, GET /api/repositories, GET /api/repositories/{owner}/{name}
    │   └── issues.py          # POST /api/issues/analyze (standalone issue classification)
    ├── schemas/
    │   ├── repository.py      # RepositorySnapshot, RepositoryStats, FileCategory, ClassifiedFile, etc.
    │   └── issue.py           # IssueCategory, IssueClassification, GitHubIssue, IssueAnalysisRequest
    ├── services/
    │   ├── repository_url.py  # URL parser → RepositoryRef (owner/name)
    │   ├── github_client.py   # httpx-based GitHub REST API client (repo, languages, README, tree, issues, PRs, commits)
    │   ├── repository_sync.py # Orchestrates GitHub fetch → file classification → issue classification → RepositorySnapshot
    │   ├── file_classifier.py # Rule-based file type classifier (SOURCE, TEST, DOCS, CONFIG, CI_CD, DEPENDENCY, etc.)
    │   └── issue_classifier.py# Keyword-based issue categorizer (BUG, FEATURE_REQUEST, QUESTION, DUPLICATE, etc.)
    └── storage/
        └── memory.py           # In-memory dict-backed store (save/get/list) — designed for future DB swap
```

**Key design decisions:**
- **Storage is an adapter.** `InMemoryRepositoryStore` lives behind a simple `save/get/list` interface in `app/storage/memory.py`. Replace it with PostgreSQL without touching services or routes.
- **Classifiers are rule-based** but return structured `IssueClassification` / `FileCategory` types. They can be extended with an LLM pass without changing callers.
- **GitHub API client** is an async context manager using `httpx.AsyncClient`. Rate-limit errors surface as `GitHubClientError` with status codes.
- **Sync is synchronous-request based** (no background queue yet). Long-running syncs block the HTTP request — Celery/Redis will be added later.

### Frontend (`frontend/src/`)

```
frontend/src/
├── main.tsx            # React root mount
├── App.tsx             # Single-page app: form → sync → display dashboard
├── App.css             # All component styles (sidebar, panels, bars, tables)
├── index.css           # Global resets and fonts
└── api.ts              # Fetch-based API client + TypeScript types mirroring backend schemas
```

- Single page (no routing yet). A sidebar form triggers `POST /api/repositories/sync`, the response populates a dashboard with: repo header, metric cards, issue/file classification bars, language distribution, README excerpt, issue list, recent PRs/commits, and file sample.
- All backend data types are mirrored in TypeScript in [api.ts](frontend/src/api.ts).
- Uses `lucide-react` for icons, no component library — raw CSS in `App.css`.

### Project docs (`docs/`)

- `iteration-plan.md` — full roadmap: 4 iterations, team roles, MoSCoW priorities, UI prototypes plan, tech selection, risk register. This is the canonical planning document.
- `ai-prompts.md` — record of AI-assisted decisions made during scaffold creation.
- `任务` — aspirational tech stack and team division for the full project (includes Tailwind CSS, PostgreSQL, pgvector, Celery, RAG, multi-Agent — NOT yet implemented).

## Important Design Principles

1. **Schema-first.** Backend Pydantic models in `app/schemas/` define the API contract. Frontend types in `api.ts` mirror them. Always update both sides.
2. **Extensibility over completeness.** The current scaffold uses rule-based classifiers and in-memory storage; every component is designed to be swapped for a more sophisticated version (LLM classifier → RAG, memory → DB, sync → Celery task).
3. **Error surface.** `GitHubClientError` carries both a message and an HTTP status code; routes catch it and return appropriate HTTP errors. No silent failures on GitHub API calls.
4. **Branch conventions:** `main` is stable; work in feature branches (`feature/...`, `docs/...`) and merge via PR with review.
