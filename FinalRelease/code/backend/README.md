# GitHub Issue Analysis Backend

FastAPI service that syncs public GitHub repositories and classifies repository files and issues.

## Run

Start the project PostgreSQL service:

```powershell
docker compose up -d postgres
```

```powershell
$env:DATABASE_URL="postgresql+psycopg://wgy666:wgy666@127.0.0.1:5432/wgy666"
uv run uvicorn app.main:app --reload --port 8000
```

Optional environment:

```powershell
$env:GITHUB_TOKEN="ghp_xxx"
```

Using a token is recommended for higher GitHub API rate limits, but public repositories work without it.

If `DATABASE_URL` is not set, the backend falls back to an in-memory store. When it is set, the backend creates PostgreSQL tables automatically and persists repositories, snapshots, files, issues, pull requests, commits, and sync run records.

## Main Endpoints

- `GET /api/health`
- `POST /api/repositories/sync`
- `GET /api/repositories`
- `GET /api/repositories/{owner}/{name}`
- `POST /api/issues/analyze`
