/**
 * API client and TypeScript type definitions.
 *
 * These types mirror the backend Pydantic schemas in ``backend/app/schemas/``.
 * Keep them in sync when making changes on either side.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// -- Types (mirrors backend/app/schemas/) ---------------------------------

export type CategorySummary = {
  category: string
  count: number
}

export type IssueClassification = {
  category: string
  confidence: number
  reason: string
  suggested_action: string
  signals: string[]
}

export type GitHubIssue = {
  number: number
  title: string
  state: string
  html_url: string
  author: string | null
  labels: string[]
  comments: number
  classification: IssueClassification
  updated_at: string | null
}

export type ClassifiedFile = {
  path: string
  category: string
  size: number | null
}

export type PullRequestSummary = {
  number: number
  title: string
  state: string
  html_url: string
  author: string | null
  updated_at: string | null
}

export type CommitSummary = {
  sha: string
  message: string
  author: string | null
  html_url: string | null
  committed_at: string | null
}

export type RepositorySnapshot = {
  identity: {
    owner: string
    name: string
    full_name: string
    html_url: string
    default_branch: string
  }
  description: string | null
  stats: {
    stars: number
    forks: number
    watchers: number
    open_issues: number
    size_kb: number
    primary_language: string | null
    languages: Record<string, number>
  }
  topics: string[]
  readme: string | null
  files: ClassifiedFile[]
  file_categories: CategorySummary[]
  issues: GitHubIssue[]
  issue_categories: CategorySummary[]
  pull_requests: PullRequestSummary[]
  recent_commits: CommitSummary[]
  synced_at: string
}

export type SyncRepositoryPayload = {
  url: string
  max_issues: number
  max_pull_requests: number
  max_commits: number
  max_tree_items: number
}

// -- API calls -------------------------------------------------------------

/** Trigger a full repository sync: fetch → classify → cache. */
export async function syncRepository(payload: SyncRepositoryPayload): Promise<RepositorySnapshot> {
  const response = await fetch(`${API_BASE_URL}/api/repositories/sync`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Request failed with ${response.status}`)
  }

  return response.json()
}

