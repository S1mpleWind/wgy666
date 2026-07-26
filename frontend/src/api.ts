/**
 * API client and TypeScript type definitions.
 *
 * These types mirror the backend Pydantic schemas in ``backend/app/schemas/``.
 * Keep them in sync when making changes on either side.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
  || `${window.location.protocol}//${window.location.hostname}:8000`

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
  source_contents?: RepositoryFileContent[]
  file_categories: CategorySummary[]
  issues: GitHubIssue[]
  issue_categories: CategorySummary[]
  pull_requests: PullRequestSummary[]
  recent_commits: CommitSummary[]
  source_revision: string | null
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
  line_start: number | null
  line_end: number | null
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
  version: string | null
}

export type CodeSymbol = {
  key: string
  name: string
  qualified_name: string
  kind: 'module' | 'class' | 'function' | 'method' | 'component' | 'dependency'
  path: string | null
  language: string
  line_start: number | null
  line_end: number | null
  parent_key: string | null
  fingerprint: string | null
  metadata: Record<string, unknown>
}

export type CodeRelation = {
  source: string
  target: string
  relation: 'contains' | 'imports' | 'calls' | 'tests'
  evidence_path: string | null
  evidence_line: number | null
  confidence: number
}

export type ApiRoute = {
  method: string
  route: string
  handler_key: string
  handler_name: string
  path: string
  line: number
}

export type TestMapping = {
  test_path: string
  source_paths: string[]
  confidence: number
  reason: string
}

export type ArchitectureDependency = ProjectDependency

export type ArchitectureHealthIssue = {
  code: string
  severity: 'info' | 'warning' | 'critical'
  title: string
  description: string
  evidence_paths: string[]
  suggestion: string
}

export type ArchitectureAnalysis = {
  repository: string
  revision: string
  generated_at: string
  parser_version: string
  coverage: {
    discovered_files: number
    indexed_files: number
    discovered_source_files: number
    parsed_source_files: number
    truncated_files: number
    file_coverage_percent: number
    parser_coverage_percent: number
    warnings: string[]
  }
  symbols: CodeSymbol[]
  relations: CodeRelation[]
  routes: ApiRoute[]
  test_mappings: TestMapping[]
  dependencies: ArchitectureDependency[]
  health: {
    score: number
    grade: string
    metrics: Record<string, number>
    issues: ArchitectureHealthIssue[]
  }
}

export type ImpactAnalysis = {
  repository: string
  revision: string
  seed_paths: string[]
  affected_files: string[]
  affected_symbols: CodeSymbol[]
  recommended_tests: TestMapping[]
  affected_routes: ApiRoute[]
  risk_score: number
  risk_level: string
  reasons: string[]
  nodes: Array<{ key: string; label: string; kind: string; path: string | null; depth: number; reason: string }>
  edges: Array<{ source: string; target: string; relation: string }>
}

export type ArchitectureHistoryItem = {
  revision: string
  generated_at: string
  symbol_count: number
  relation_count: number
  route_count: number
  health_score: number
}

export type ArchitectureDiff = {
  repository: string
  base_revision: string
  target_revision: string
  added_symbols: CodeSymbol[]
  removed_symbols: CodeSymbol[]
  changed_symbols: CodeSymbol[]
  added_routes: ApiRoute[]
  removed_routes: ApiRoute[]
  added_dependencies: ArchitectureDependency[]
  removed_dependencies: ArchitectureDependency[]
  health_score_delta: number
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

export type User = {
  id: string
  name: string
  email: string
  created_at: string
  updated_at: string
}

export type UserPayload = {
  name: string
  email: string
}

export type SystemConfig = {
  llm_api_base_url: string
  llm_model: string
  llm_api_key_configured: boolean
  github_token_configured: boolean
  github_webhook_secret_configured: boolean
}

export type SystemConfigUpdate = {
  llm_api_base_url?: string
  llm_model?: string
  llm_api_key?: string
  github_token?: string
  github_webhook_secret?: string
  clear_llm_api_key?: boolean
  clear_github_token?: boolean
  clear_github_webhook_secret?: boolean
}

async function userResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `用户请求失败：${response.status}`)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export async function fetchUsers(): Promise<User[]> {
  return userResponse(await fetch(`${API_BASE_URL}/api/users`))
}

export async function createUser(payload: UserPayload): Promise<User> {
  return userResponse(await fetch(`${API_BASE_URL}/api/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }))
}

export async function updateUser(userId: string, payload: Partial<UserPayload>): Promise<User> {
  return userResponse(await fetch(`${API_BASE_URL}/api/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }))
}

export async function deleteUser(userId: string): Promise<void> {
  return userResponse(await fetch(`${API_BASE_URL}/api/users/${userId}`, { method: 'DELETE' }))
}

export async function fetchSystemConfig(): Promise<SystemConfig> {
  return userResponse(await fetch(`${API_BASE_URL}/api/users/config`))
}

export async function updateSystemConfig(payload: SystemConfigUpdate): Promise<SystemConfig> {
  return userResponse(await fetch(`${API_BASE_URL}/api/users/config`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }))
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

export async function fetchArchitectureAnalysis(
  owner: string,
  name: string,
  revision?: string,
): Promise<ArchitectureAnalysis> {
  const query = revision ? `?revision=${encodeURIComponent(revision)}` : ''
  const response = await fetch(
    `${API_BASE_URL}/api/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/tools/architecture${query}`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to fetch architecture analysis: ${response.status}`)
  }
  return response.json()
}

export async function analyzeArchitectureImpact(
  owner: string,
  name: string,
  payload: { paths?: string[]; issue_text?: string; max_depth?: number },
): Promise<ImpactAnalysis> {
  const response = await fetch(
    `${API_BASE_URL}/api/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/tools/architecture/impact`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to analyze architecture impact: ${response.status}`)
  }
  return response.json()
}

export async function fetchArchitectureHistory(owner: string, name: string): Promise<ArchitectureHistoryItem[]> {
  const response = await fetch(
    `${API_BASE_URL}/api/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/tools/architecture/history`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to fetch architecture history: ${response.status}`)
  }
  return response.json()
}

export async function fetchArchitectureDiff(
  owner: string,
  name: string,
  baseRevision: string,
  targetRevision: string,
): Promise<ArchitectureDiff> {
  const query = new URLSearchParams({ base_revision: baseRevision, target_revision: targetRevision })
  const response = await fetch(
    `${API_BASE_URL}/api/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/tools/architecture/diff?${query}`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `Failed to compare architecture revisions: ${response.status}`)
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
