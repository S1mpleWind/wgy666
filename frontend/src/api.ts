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

export type FreshnessMode = 'cache_first' | 'refresh_if_stale' | 'force_refresh'

export type AssistantChatMessage = {
  role: 'user' | 'assistant'
  content: string
}

export type AssistantToolCall = {
  name: string
  args: Record<string, unknown>
  summary: string
}

export type AssistantCitation = {
  type: string
  label: string
  url: string | null
  path: string | null
}

export type AssistantChatRequest = {
  owner: string
  name: string
  message: string
  freshness?: FreshnessMode
  history?: AssistantChatMessage[]
}

export type AssistantChatResponse = {
  answer: string
  repository: string
  used_cached_data: boolean
  tool_calls: AssistantToolCall[]
  citations: AssistantCitation[]
}

export type RepositoryFileContent = {
  id: number
  path: string
  category: string
  content: string
  size: number | null
  truncated: boolean
  synced_at: string | null
}

export type ProjectDependency = {
  name: string
  ecosystem: string
  group: string
  source_file: string
}

export type ProjectStructureResponse = {
  project_type: string
  analyzed_file_count: number
  analysis_warning: string | null
  source_count: number
  dependency_files: ClassifiedFile[]
  dependency_packages: ProjectDependency[]
  detected_frameworks: string[]
  test_files: ClassifiedFile[]
  doc_files: ClassifiedFile[]
  config_files: ClassifiedFile[]
  entry_files: ClassifiedFile[]
  ci_files: ClassifiedFile[]
  top_directories: Array<{
    name: string
    count: number
    main_category: string
    source_count: number
  }>
}

// -- API calls -------------------------------------------------------------

export type RepositoryListItem = {
  owner: string
  name: string
  full_name: string
  html_url: string
  description: string | null
  synced_at: string
  issue_count: number
  file_count: number
}

/** List synced repositories. */
export async function fetchRepositoryList(): Promise<RepositoryListItem[]> {
  const response = await fetch(`${API_BASE_URL}/api/repositories`)
  if (!response.ok) throw new Error(`Failed to list repos: ${response.status}`)
  return response.json()
}

/** Load a cached repository snapshot (no sync, instant). */
export async function fetchRepositorySnapshot(owner: string, name: string): Promise<RepositorySnapshot> {
  const response = await fetch(`${API_BASE_URL}/api/repositories/${owner}/${name}`)
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to load repo: ${response.status}`)
  }
  return response.json()
}

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

// -- Webhook event types ----------------------------------------------------

export type WebhookClassification = {
  category: string | null
  confidence: number | null
  reason: string | null
  suggested_action?: string | null
  signals?: string[]
  auto_reply_draft?: string | null
}

export type WebhookEventItem = {
  event_id: string
  event_type: string
  action: string
  repository: string
  issue_number: number
  issue_title?: string
  issue_state?: string
  issue_author?: string | null
  issue_labels?: string[]
  classification: WebhookClassification | null
  is_read: boolean
  received_at: string
}

export type WebhookEventDetail = WebhookEventItem & {
  issue_body: string | null
  issue_comments_count: number
  issue_html_url: string | null
}

// -- API calls -------------------------------------------------------------

/** Fetch public webhook configuration status from the backend. */
export async function fetchWebhookConfig(): Promise<{ url: string; secret_configured: boolean }> {
  const response = await fetch(`${API_BASE_URL}/api/webhooks/config`)

  if (!response.ok) {
    throw new Error(`Failed to fetch webhook config: ${response.status}`)
  }

  return response.json()
}

/** Fetch recent webhook events for the notification inbox. */
export async function fetchWebhookEvents(limit = 20, repository?: string): Promise<WebhookEventItem[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (repository) params.set('repository', repository)
  const response = await fetch(`${API_BASE_URL}/api/webhooks/events?${params}`)

  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to fetch events: ${response.status}`)
  }

  return response.json()
}

/** Fetch full detail for a single webhook event by event_id. */
export async function fetchWebhookEventDetail(eventId: string): Promise<WebhookEventDetail> {
  const response = await fetch(`${API_BASE_URL}/api/webhooks/events/${encodeURIComponent(eventId)}`)

  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to fetch event detail: ${response.status}`)
  }

  return response.json()
}

/** Trigger an auto-fix for a bug issue. Generates a PR via AgentHarness. */
export async function postAutoFix(eventId: string): Promise<{ status: string; pr_url: string; branch_name: string }> {
  const response = await fetch(`${API_BASE_URL}/api/webhooks/events/${encodeURIComponent(eventId)}/fix`, {
    method: 'POST',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to auto-fix: ${response.status}`)
  }
  return response.json()
}

/** Mark a webhook event as read or deleted. */
export async function updateWebhookEvent(eventId: string, action: 'read' | 'delete'): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/webhooks/events/${encodeURIComponent(eventId)}?action=${action}`, {
    method: 'PATCH',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to update event: ${response.status}`)
  }
}

/** Post the exact reply draft approved by the maintainer. */
export async function postWebhookReply(eventId: string, replyText: string): Promise<{ status: string; reply_text: string; comment_url: string; source?: string }> {
  const response = await fetch(`${API_BASE_URL}/api/webhooks/events/${encodeURIComponent(eventId)}/reply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reply_text: replyText }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to post reply: ${response.status}`)
  }

  return response.json()
}

/** Fetch all synced file contents for a repository. */
export async function fetchFileContents(owner: string, name: string): Promise<RepositoryFileContent[]> {
  const response = await fetch(
    `${API_BASE_URL}/api/repositories/${owner}/${name}/tools/file-contents`,
  )

  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to fetch file contents: ${response.status}`)
  }

  return response.json()
}

/** Fetch a single file's full content by path. */
export async function fetchFileContent(
  owner: string,
  name: string,
  path: string,
): Promise<RepositoryFileContent> {
  const response = await fetch(
    `${API_BASE_URL}/api/repositories/${owner}/${name}/tools/file-contents/${encodeURIComponent(path)}`,
  )

  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to fetch file content: ${response.status}`)
  }

  return response.json()
}

/** Fetch the backend's rule-based structure analysis for a synced repository. */
export async function fetchProjectStructure(
  owner: string,
  name: string,
): Promise<ProjectStructureResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/tools/project-structure?freshness=cache_first`,
  )

  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to fetch project structure: ${response.status}`)
  }

  return response.json()
}

/** Ask the repository assistant a question. */
export async function askAssistant(payload: AssistantChatRequest): Promise<AssistantChatResponse> {
  const response = await fetch(`${API_BASE_URL}/api/assistant/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      freshness: 'cache_first',
      history: [],
      ...payload,
    }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Request failed with ${response.status}`)
  }

  return response.json()
}
