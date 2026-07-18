import { useMemo, useState, useEffect, useCallback, useRef } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Activity, AlertCircle, ArrowRight, Bell, Bot, Boxes, CheckCircle2, ChevronDown, CircleDot, Database, FileCode2, FileText, FolderGit, GitBranch, LayoutDashboard, Loader2, Network, Package, RefreshCw, Search, Send, Settings2, ShieldCheck, Sparkles, Star, TestTube2, UserRound, Workflow, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

import { askAssistant, fetchFileContent as fetchFileContentApi, fetchProjectStructure, fetchWebhookConfig, fetchWebhookEventDetail, fetchWebhookEvents, postWebhookReply, syncRepository } from './api'
import type { AssistantChatMessage, AssistantChatResponse, CategorySummary, ClassifiedFile, GitHubIssue, ProjectStructureResponse, RepositoryFileContent, RepositorySnapshot, WebhookEventDetail, WebhookEventItem } from './api'
import { ProjectStructureDetails } from './ProjectStructureDetails'
import type { AnalysisSection, ProjectStructureAnalysis } from './ProjectStructureDetails'
/**
 * App — Single-page sync-and-dashboard application.
 */

const defaultForm = {
  url: 'https://github.com/S1mpleWind/wgy666',
  max_issues: 30,
  max_pull_requests: 15,
  max_commits: 12,
  max_tree_items: 600,
}

type WorkspaceSection = 'overview' | 'analysis' | 'issues' | 'agent'

function App() {
  const [form, setForm] = useState(defaultForm)
  const [snapshot, setSnapshot] = useState<RepositorySnapshot | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [showInbox, setShowInbox] = useState(false)
  const [webhookConfig, setWebhookConfig] = useState<{ url: string; secret: string } | null>(null)
  const [webhookEvents, setWebhookEvents] = useState<WebhookEventItem[]>([])
  const [eventsLoading, setEventsLoading] = useState(false)
  const [analysisSection, setAnalysisSection] = useState<AnalysisSection | null>(null)
  const [projectAnalysis, setProjectAnalysis] = useState<ProjectStructureAnalysis | null>(null)
  const [showIssueDetail, setShowIssueDetail] = useState(false)
  const [selectedEvent, setSelectedEvent] = useState<WebhookEventDetail | null>(null)
  const [eventDetailLoading, setEventDetailLoading] = useState(false)
  const [selectedIssue, setSelectedIssue] = useState<GitHubIssue | null>(null)
  const [showIssueOverview, setShowIssueOverview] = useState(false)
  const [activeWorkspaceSection, setActiveWorkspaceSection] = useState<WorkspaceSection>('overview')
  const [chatFocusRequest, setChatFocusRequest] = useState(0)

  // -- Notification inbox --------------------------------------------------

  const loadEvents = useCallback(async () => {
    setEventsLoading(true)
    try {
      const events = await fetchWebhookEvents(20)
      setWebhookEvents(events)
    } catch {
      // silently fail — inbox just stays empty
    } finally {
      setEventsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (showInbox) {
      loadEvents()
    }
  }, [showInbox, loadEvents])

  useEffect(() => {
    if (showSettings) {
      fetchWebhookConfig().then(setWebhookConfig).catch(() => {})
    }
  }, [showSettings])

  // -- Issue detail from inbox click ---------------------------------

  async function handleInboxItemClick(event: WebhookEventItem) {
    setSelectedEvent(null)
    setShowIssueDetail(true)
    setEventDetailLoading(true)
    try {
      const detail = await fetchWebhookEventDetail(event.event_id)
      setSelectedEvent(detail)
    } catch {
      setSelectedEvent(null)
    } finally {
      setEventDetailLoading(false)
    }
  }

  // Auto-poll for new notifications (updates the badge count).
  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const events = await fetchWebhookEvents(20)
        setWebhookEvents(events)
      } catch { /* ignore */ }
    }, 30000)
    // Initial fetch
    fetchWebhookEvents(20).then(setWebhookEvents).catch(() => {})
    return () => clearInterval(poll)
  }, [])

  // -- Sync form handler --------------------------------------------------

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsLoading(true)
    setError(null)
    setProjectAnalysis(null)

    try {
      const result = await syncRepository(form)
      setSnapshot(result)
      setAnalysisSection(null)
      const fallback = analyzeProject(result)
      setProjectAnalysis(fallback)

      try {
        const response = await fetchProjectStructure(result.identity.owner, result.identity.name)
        setProjectAnalysis(mapProjectAnalysis(response))
      } catch {
        setProjectAnalysis({
          ...fallback,
          analysisWarning: fallback.analysisWarning ?? '后端项目解析暂不可用，当前显示本地降级结果。',
        })
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '同步失败')
    } finally {
      setIsLoading(false)
    }
  }

  // Derive top 5 languages from the language byte-count map.
  const topLanguages = useMemo(() => {
    if (!snapshot) return []
    return Object.entries(snapshot.stats.languages)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
  }, [snapshot])

  useEffect(() => {
    if (analysisSection) window.scrollTo({ top: 0, behavior: 'auto' })
  }, [analysisSection])

  function handleWorkspaceNavigation(section: WorkspaceSection) {
    setActiveWorkspaceSection(section)

    if (section === 'agent') {
      setChatFocusRequest((current) => current + 1)
      if (window.innerWidth <= 1020) {
        window.requestAnimationFrame(() => {
          document.getElementById('repository-agent')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        })
      }
      return
    }

    if (!snapshot) {
      window.requestAnimationFrame(() => {
        document.querySelector<HTMLInputElement>('.sync-card input')?.focus()
      })
      return
    }

    if (section === 'analysis' && projectAnalysis) {
      setAnalysisSection('architecture')
      return
    }

    setAnalysisSection(null)
    const targetId = section === 'issues' ? 'issue-intelligence' : 'overview'
    window.requestAnimationFrame(() => {
      document.getElementById(targetId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  return (
    <main className="workspace">
      {/* -- Sidebar: sync form + module info ------------------------------- */}
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><Sparkles size={20} aria-hidden="true" /></span>
          <div>
            <h1>IssueScope</h1>
            <p>Repository Intelligence</p>
          </div>
        </div>

        <form className="sync-form sync-card" onSubmit={handleSubmit}>
          <div className="sync-card-heading">
            <div>
              <span>仓库上下文</span>
              <strong>{snapshot?.identity.full_name ?? '连接 GitHub 仓库'}</strong>
            </div>
            <span className={`connection-dot ${snapshot ? 'ready' : ''}`} title={snapshot ? '仓库已同步' : '等待同步'} />
          </div>
          <label>
            仓库地址
            <div className="input-with-icon">
              <FolderGit size={16} aria-hidden="true" />
              <input
                value={form.url}
                onChange={(event) => setForm({ ...form, url: event.target.value })}
                placeholder="https://github.com/owner/repo"
              />
            </div>
          </label>

          <details className="sync-options">
            <summary>
              同步范围
              <ChevronDown size={15} aria-hidden="true" />
            </summary>
            <div className="field-grid">
              <NumberField label="Issues" value={form.max_issues} onChange={(value) => setForm({ ...form, max_issues: value })} />
              <NumberField label="PRs" value={form.max_pull_requests} onChange={(value) => setForm({ ...form, max_pull_requests: value })} />
              <NumberField label="Commits" value={form.max_commits} onChange={(value) => setForm({ ...form, max_commits: value })} />
              <NumberField label="Files" value={form.max_tree_items} onChange={(value) => setForm({ ...form, max_tree_items: value })} />
            </div>
          </details>

          <button className="primary-button sync-button" disabled={isLoading} type="submit">
            {isLoading ? <Loader2 className="spin" size={18} aria-hidden="true" /> : <RefreshCw size={18} aria-hidden="true" />}
            {isLoading ? '正在建立上下文' : snapshot ? '重新同步' : '同步并分析'}
          </button>
        </form>

        <nav className="workspace-nav" aria-label="工作台导航">
          <p>工作台</p>
          <button aria-pressed={activeWorkspaceSection === 'overview'} className={activeWorkspaceSection === 'overview' ? 'active' : ''} type="button" onClick={() => handleWorkspaceNavigation('overview')}><LayoutDashboard size={17} />仓库概览</button>
          <button aria-pressed={activeWorkspaceSection === 'analysis'} className={activeWorkspaceSection === 'analysis' ? 'active' : ''} type="button" onClick={() => handleWorkspaceNavigation('analysis')}><Network size={17} />项目解析</button>
          <button aria-pressed={activeWorkspaceSection === 'issues'} className={activeWorkspaceSection === 'issues' ? 'active' : ''} type="button" onClick={() => handleWorkspaceNavigation('issues')}><Activity size={17} />Issue 智能分析</button>
          <button aria-pressed={activeWorkspaceSection === 'agent'} className={activeWorkspaceSection === 'agent' ? 'active' : ''} type="button" onClick={() => handleWorkspaceNavigation('agent')}><Bot size={17} />仓库问答</button>
        </nav>

        <div className="sidebar-actions">
          <button className="ghost-button sidebar-action" onClick={() => setShowInbox(!showInbox)}>
            <Bell size={16} aria-hidden="true" />
            通知
            {webhookEvents.length > 0 && <span className="badge-count">{webhookEvents.length}</span>}
          </button>
          <button className="ghost-button sidebar-action" onClick={() => setShowSettings(!showSettings)}>
            <Settings2 size={16} aria-hidden="true" />
            配置
          </button>
        </div>

        {error && (
          <div className="notice error">
            <AlertCircle size={18} aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        <section className="sidebar-section">
          <div className="system-status">
            <span className="status-icon"><Database size={16} aria-hidden="true" /></span>
            <div><strong>技术原型环境</strong><small>API、Webhook 与项目解析已接入</small></div>
            <CircleDot size={14} aria-hidden="true" />
          </div>
        </section>
      </aside>

      {/* -- Main content: dashboard --------------------------------------- */}
      <section className="content">
        {/* Top bar with actions (always visible) */}
        <div className="top-bar">
          <div className="breadcrumb">
            <span>IssueScope</span>
            <ArrowRight size={14} aria-hidden="true" />
            <strong>{analysisSection ? '项目解析' : snapshot?.identity.name ?? '仓库工作台'}</strong>
          </div>
          <div className="top-actions">
            <span className="live-status"><span /> 前端在线</span>
            <button className={`icon-button ${showInbox ? 'active' : ''}`} onClick={() => setShowInbox(!showInbox)} title="通知">
              <Bell size={19} aria-hidden="true" />
              {webhookEvents.length > 0 && <span className="badge-count">{webhookEvents.length}</span>}
            </button>
            <button className={`icon-button ${showSettings ? 'active' : ''}`} onClick={() => setShowSettings(!showSettings)} title="配置">
              <Settings2 size={19} aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Modal overlays */}
        {showInbox && (
          <div className="modal-overlay" onClick={() => setShowInbox(false)}>
            <section className="modal inbox-panel" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>通知</h3>
                <button className="icon-button" onClick={() => setShowInbox(false)}>&#x2715;</button>
              </div>
              {eventsLoading ? (
                <p className="muted inbox-empty">加载中...</p>
              ) : webhookEvents.length === 0 ? (
                <p className="muted inbox-empty">暂无通知</p>
              ) : (
                <div className="inbox-list">
                  {webhookEvents.map((event) => (
                    <button
                      className="inbox-item"
                      key={event.event_id}
                      onClick={() => handleInboxItemClick(event)}
                    >
                      <div className="inbox-item-header">
                        <span className={`badge ${event.classification?.category ?? ''}`}>
                          {formatCategory(event.classification?.category ?? 'unknown')}
                        </span>
                        <span className="inbox-time">{formatTimeAgo(event.received_at)}</span>
                      </div>
                      <span className="inbox-item-title">
                        {event.repository}#{event.issue_number}
                        {event.issue_title ? ` · ${event.issue_title.slice(0, 60)}` : ''}
                      </span>
                      {event.classification?.reason && (
                        <p className="inbox-item-reason">{event.classification.reason}</p>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        {showSettings && (
          <div className="modal-overlay" onClick={() => setShowSettings(false)}>
            <section className="modal settings-panel" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>Webhook 配置</h3>
                <button className="icon-button" onClick={() => setShowSettings(false)}>&#x2715;</button>
              </div>
              <label>
                Webhook URL
                <input value={webhookConfig?.url ?? '加载中...'} readOnly disabled />
              </label>
              <label>
                GitHub Webhook Secret
                <input value={webhookConfig?.secret || '(未配置)'} readOnly disabled />
              </label>
              <p className="settings-hint">
                在 GitHub 仓库 Settings → Webhooks 中填入以上 URL 和 Secret 以启用自动监听。
              </p>
            </section>
          </div>
        )}

        {/* Issue detail modal */}
        {showIssueDetail && (
          <div className="modal-overlay" onClick={() => setShowIssueDetail(false)}>
            <section className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
              {eventDetailLoading ? (
                <>
                  <div className="modal-header">
                    <h3>加载中...</h3>
                    <button className="icon-button" onClick={() => setShowIssueDetail(false)}>&#x2715;</button>
                  </div>
                  <p className="muted" style={{ textAlign: 'center', padding: '20px 0' }}>正在加载 Issue 详情...</p>
                </>
              ) : selectedEvent ? (
                <IssueDetailModal
                  event={selectedEvent}
                  onClose={() => setShowIssueDetail(false)}
                />
              ) : (
                <>
                  <div className="modal-header">
                    <h3>无法加载 Issue 详情</h3>
                    <button className="icon-button" onClick={() => setShowIssueDetail(false)}>&#x2715;</button>
                  </div>
                  <p className="muted" style={{ textAlign: 'center', padding: '20px 0' }}>该事件可能已过期。</p>
                </>
              )}
            </section>
          </div>
        )}

        {/* ← Issue overview modal */}
        {showIssueOverview && snapshot && (
          <div className="modal-overlay" onClick={() => setShowIssueOverview(false)}>
            <section className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
              <IssueOverviewModal
                issues={snapshot.issues}
                onSelect={(issue) => { setShowIssueOverview(false); setSelectedIssue(issue); }}
                onClose={() => setShowIssueOverview(false)}
              />
            </section>
          </div>
        )}

        {/* ← Synced issue detail modal */}
        {selectedIssue && (
          <div className="modal-overlay" onClick={() => setSelectedIssue(null)}>
            <section className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
              <SyncedIssueModal
                issue={selectedIssue}
                onClose={() => setSelectedIssue(null)}
              />
            </section>
          </div>
        )}

        {!snapshot ? (
          <EmptyState isLoading={isLoading} />
        ) : (
          <>
            {analysisSection && projectAnalysis ? (
              <ProjectStructureDetails
                activeSection={analysisSection}
                analysis={projectAnalysis}
                repository={snapshot}
                onBack={() => setAnalysisSection(null)}
                onSelect={setAnalysisSection}
              />
            ) : (
              <>
            {/* Repository header */}
            <header className="repo-header" id="overview">
              <div className="repo-identity">
                <span className="repo-avatar"><FolderGit size={24} aria-hidden="true" /></span>
                <div>
                <div className="repo-meta-line">
                  <span className="repo-visibility"><ShieldCheck size={13} />已建立安全上下文</span>
                  <span>同步于 {formatDate(snapshot.synced_at)}</span>
                </div>
                <h2>{snapshot.identity.full_name}</h2>
                <p className="description">{snapshot.description ?? 'No repository description.'}</p>
                <div className="topic-row">
                  {snapshot.topics.slice(0, 8).map((topic) => (
                    <span key={topic}>{topic}</span>
                  ))}
                </div>
                </div>
              </div>
              <div className="repo-actions">
                <span className="branch-chip"><GitBranch size={14} />{snapshot.identity.default_branch}</span>
                <a className="ghost-button" href={snapshot.identity.html_url} target="_blank">
                  <FolderGit size={17} aria-hidden="true" />在 GitHub 查看
                </a>
              </div>
            </header>

            {/* Metric cards */}
            <section className="metric-grid">
              <Metric icon={<Star size={18} />} label="Stars" value={snapshot.stats.stars.toLocaleString()} />
              <Metric icon={<GitBranch size={18} />} label="Forks" value={snapshot.stats.forks.toLocaleString()} />
              <Metric icon={<AlertCircle size={18} />} label="Open Issues" value={snapshot.stats.open_issues.toLocaleString()} />
              <Metric icon={<Search size={18} />} label="Indexed Files" value={snapshot.files.length.toLocaleString()} />
            </section>

            {/* Issues summary panel */}
            <section className="panel issues-summary" id="issue-intelligence">
              <div className="panel-header-with-actions">
                <h3>Issues</h3>
                <button className="ghost-button" onClick={() => setShowIssueOverview(true)}>
                  详情 ↗
                </button>
              </div>
              <div className="issues-summary-grid">
                <div className="issues-summary-card">
                  <strong>{snapshot.issues.filter(i => i.state === 'open').length}</strong>
                  <span>Open</span>
                </div>
                <div className="issues-summary-card closed">
                  <strong>{snapshot.issues.filter(i => i.state === 'closed').length}</strong>
                  <span>Closed</span>
                </div>
              </div>
              <CategoryBars summaries={snapshot.issue_categories} total={snapshot.issues.filter(i => i.state === 'open').length} />
              <IssueWorkflow issues={snapshot.issues} eventCount={webhookEvents.length} />
            </section>

            {/* Language distribution + README */}
            <section className="two-column">
              <Panel title="语言分布">
                <CategoryBars summaries={topLanguages.map(([category, count]) => ({ category, count }))} total={topLanguages.reduce((sum, [, count]) => sum + count, 0)} />
              </Panel>
              <Panel title="README 摘要">
                <p className="readme">{snapshot.readme ? snapshot.readme.slice(0, 700) : 'README not found.'}</p>
              </Panel>
            </section>

            {projectAnalysis && (
              <div id="project-analysis">
                <ProjectAnalysisPanel
                  analysis={projectAnalysis}
                  repositoryName={snapshot.identity.name}
                  onOpen={setAnalysisSection}
                />
              </div>
            )}

            {/* Recent PRs and commits */}
            <section className="two-column">
              <Panel title="近期 PR">
                <CompactList
                  items={snapshot.pull_requests.slice(0, 8).map((item) => ({
                    key: item.number,
                    title: `#${item.number} ${item.title}`,
                    meta: `${item.state} · ${item.author ?? 'unknown'}`,
                    href: item.html_url,
                  }))}
                />
              </Panel>
              <Panel title="近期提交">
                <CompactList
                  items={snapshot.recent_commits.slice(0, 8).map((item) => ({
                    key: item.sha,
                    title: item.message,
                    meta: `${item.sha} · ${item.author ?? 'unknown'}`,
                    href: item.html_url ?? snapshot.identity.html_url,
                  }))}
                />
              </Panel>
            </section>

            {/* File sample with source code viewer */}
            <FileBrowser
              files={snapshot.files.slice(0, 100)}
              owner={snapshot.identity.owner}
              name={snapshot.identity.name}
            />
              </>
            )}
          </>
        )}
      </section>
      <ChatSidebar
        focusRequest={chatFocusRequest}
        highlighted={activeWorkspaceSection === 'agent'}
        snapshot={snapshot}
      />
    </main>
  )
}

// -- Shared UI components --------------------------------------------------

type ProjectAnalysis = ProjectStructureAnalysis

function ProjectAnalysisPanel({ analysis, repositoryName, onOpen }: { analysis: ProjectAnalysis; repositoryName: string; onOpen: (section: AnalysisSection) => void }) {
  return (
    <Panel title="项目结构概览">
      <div className="analysis-layout">
        <div className="analysis-summary">
          <p className="analysis-kicker">
            {analysis.analysisSource === 'backend' ? '后端规则解析 · 非 AI' : '本地降级解析 · 非 AI'}
          </p>
          <h4>{analysis.projectType}</h4>
          <p className="analysis-description">
            基于同步目录、文件类型、已索引源码和依赖清单生成项目结构视图，
            为仓库问答、模块理解和 Issue 定位提供上下文。
          </p>
          <p className="analysis-basis">
            当前基于 {analysis.analyzedFileCount} 个去重后的可用文件进行分析。
          </p>
          {analysis.analysisWarning && (
            <div className="analysis-warning" role="status">
              <AlertCircle size={17} aria-hidden="true" />
              <span>{analysis.analysisWarning}</span>
            </div>
          )}
          <div className="analysis-chips">
            <span>{analysis.sourceCount} 个源码文件</span>
            <span>{analysis.dependencyFiles.length} 个依赖配置文件</span>
            <span>{analysis.testFiles.length} 个测试文件</span>
            <span>{analysis.docFiles.length} 个文档文件</span>
          </div>
        </div>

        <div className="mindmap" aria-label="项目结构概览图">
          <button className="mindmap-center" type="button" onClick={() => onOpen('architecture')}>
            <strong>{repositoryName}</strong>
            <span>结构概览</span>
            <small>查看完整架构图</small>
          </button>
          <MindmapNode label="源码模块" value={analysis.sourceCount} icon={<FileCode2 size={16} />} onClick={() => onOpen('architecture')} />
          <MindmapNode label="依赖配置" value={analysis.dependencyFiles.length + analysis.configFiles.length} icon={<Package size={16} />} onClick={() => onOpen('dependencies')} />
          <MindmapNode label="测试" value={analysis.testFiles.length} icon={<TestTube2 size={16} />} onClick={() => onOpen('quality')} />
          <MindmapNode label="文档" value={analysis.docFiles.length} icon={<FileText size={16} />} onClick={() => onOpen('quality')} />
          <MindmapNode label="CI/CD" value={analysis.ciFiles.length} icon={<Settings2 size={16} />} onClick={() => onOpen('quality')} />
        </div>
      </div>

      <div className="analysis-grid">
        <AnalysisCard
          icon={<Boxes size={18} />}
          title="主要目录"
          items={analysis.topDirectories.map((item) => `${item.name} · ${item.count} 个文件 · ${formatProjectCategory(item.mainCategory)}`)}
          onClick={() => onOpen('directories')}
        />
        <AnalysisCard
          icon={<Package size={18} />}
          title="依赖文件"
          items={analysis.dependencyFiles.slice(0, 6).map((file) => file.path)}
          emptyText="暂未识别到依赖文件"
          onClick={() => onOpen('dependencies')}
        />
        <AnalysisCard
          icon={<FileCode2 size={18} />}
          title="入口文件候选"
          items={analysis.entryFiles.slice(0, 6).map((file) => file.path)}
          emptyText="暂未识别到明显入口文件"
          onClick={() => onOpen('entrypoints')}
        />
        <AnalysisCard
          icon={<TestTube2 size={18} />}
          title="测试与文档"
          items={[
            `测试文件：${analysis.testFiles.length} 个`,
            `文档文件：${analysis.docFiles.length} 个`,
            `配置文件：${analysis.configFiles.length} 个`,
          ]}
          onClick={() => onOpen('quality')}
        />
      </div>
    </Panel>
  )
}

function MindmapNode({ icon, label, value, onClick }: { icon: ReactNode; label: string; value: number; onClick: () => void }) {
  return (
    <button className="mindmap-node" type="button" onClick={onClick}>
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </button>
  )
}

function AnalysisCard({ icon, title, items, emptyText = '暂无数据', onClick }: { icon: ReactNode; title: string; items: string[]; emptyText?: string; onClick: () => void }) {
  return (
    <button className="analysis-card" type="button" onClick={onClick}>
      <h4>
        {icon}
        {title}
        <ArrowRight className="analysis-card-arrow" size={16} aria-hidden="true" />
      </h4>
      {items.length === 0 ? (
        <p className="muted">{emptyText}</p>
      ) : (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </button>
  )
}

type ChatThreadMessage = AssistantChatMessage & {
  toolCalls?: AssistantChatResponse['tool_calls']
  citations?: AssistantChatResponse['citations']
  usedCachedData?: boolean
}

function ChatSidebar({ snapshot, focusRequest, highlighted }: { snapshot: RepositorySnapshot | null; focusRequest: number; highlighted: boolean }) {
  const [messages, setMessages] = useState<ChatThreadMessage[]>([
    {
      role: 'assistant',
      content: '同步仓库后，可以问我项目结构、Issue、测试文件、依赖、README 或最近活动。',
    },
  ])
  const [input, setInput] = useState('')
  const [isAsking, setIsAsking] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (focusRequest > 0) inputRef.current?.focus()
  }, [focusRequest])

  function selectPrompt(prompt: string) {
    setInput(prompt)
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!snapshot || !input.trim() || isAsking) return

    const question = input.trim()
    const history = messages
      .filter((message) => message.role === 'user' || message.role === 'assistant')
      .slice(-8)
      .map(({ role, content }) => ({ role, content }))

    const userMessage: ChatThreadMessage = { role: 'user', content: question }
    setMessages((current) => [...current, userMessage])
    setInput('')
    setIsAsking(true)
    setChatError(null)

    try {
      const response = await askAssistant({
        owner: snapshot.identity.owner,
        name: snapshot.identity.name,
        message: question,
        freshness: 'refresh_if_stale',
        history,
      })
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: response.answer,
          toolCalls: response.tool_calls,
          citations: response.citations,
          usedCachedData: response.used_cached_data,
        },
      ])
    } catch (exc) {
      setChatError(exc instanceof Error ? exc.message : '问答失败')
    } finally {
      setIsAsking(false)
    }
  }

  return (
    <aside className={`chat-sidebar ${highlighted ? 'highlighted' : ''}`} id="repository-agent">
      <header className="chat-header">
        <div>
          <span className="agent-mark"><Bot size={18} aria-hidden="true" /></span>
          <div>
            <h2>Repository Agent</h2>
            <p>{snapshot ? `正在分析 ${snapshot.identity.full_name}` : '等待仓库上下文'}</p>
          </div>
        </div>
        <span className={`agent-state ${snapshot ? 'ready' : ''}`}>
          <span />{snapshot ? 'Ready' : 'Standby'}
        </span>
      </header>

      <div className="quick-prompts" aria-label="快捷问题">
        {['项目入口在哪？', '解释核心架构', '有哪些高风险 Issue？'].map((prompt) => (
          <button disabled={!snapshot || isAsking} key={prompt} type="button" onClick={() => selectPrompt(prompt)}>
            {prompt}
          </button>
        ))}
      </div>

      <div className="chat-thread">
        {messages.map((message, index) => (
          <article className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
            <div className="chat-avatar">
              {message.role === 'assistant' ? <Bot size={16} aria-hidden="true" /> : <UserRound size={16} aria-hidden="true" />}
            </div>
            <div className="chat-bubble">
              <div className="chat-content markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>
              {message.toolCalls && message.toolCalls.length > 0 && (
                <div className="tool-strip">
                  {message.toolCalls.map((tool) => (
                    <span key={`${index}-${tool.name}`}>{tool.name}</span>
                  ))}
                </div>
              )}
              {message.citations && message.citations.length > 0 && (
                <div className="citation-list">
                  {message.citations.slice(0, 5).map((citation) => (
                    citation.url ? (
                      <a href={citation.url} target="_blank" key={`${citation.type}-${citation.label}`}>
                        {citation.type}: {citation.label}
                      </a>
                    ) : (
                      <span key={`${citation.type}-${citation.label}`}>
                        {citation.type}: {citation.label}
                      </span>
                    )
                  ))}
                </div>
              )}
              {typeof message.usedCachedData === 'boolean' && (
                <span className="cache-note">{message.usedCachedData ? 'cache used' : 'synced before answer'}</span>
              )}
            </div>
          </article>
        ))}
        {isAsking && (
          <article className="chat-message assistant">
            <div className="chat-avatar">
              <Bot size={16} aria-hidden="true" />
            </div>
            <div className="chat-bubble loading">
              <Loader2 className="spin" size={16} aria-hidden="true" />
              正在调用仓库工具...
            </div>
          </article>
        )}
      </div>

      {chatError && (
        <div className="notice error chat-error">
          <AlertCircle size={16} aria-hidden="true" />
          <span>{chatError}</span>
        </div>
      )}

      <form className="chat-form" onSubmit={handleAsk}>
        <div className="chat-composer">
          <input
            ref={inputRef}
            disabled={!snapshot || isAsking}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={snapshot ? '向仓库提问，回答将附带来源…' : '请先同步仓库'}
          />
          <button disabled={!snapshot || isAsking || !input.trim()} type="submit" aria-label="发送问题">
            <Send size={17} aria-hidden="true" />
          </button>
        </div>
        <p><Sparkles size={12} />回答基于同步仓库数据，重要结论会标注来源</p>
      </form>
    </aside>
  )
}

type NumberFieldProps = {
  label: string
  value: number
  onChange: (value: number) => void
}

function NumberField({ label, value, onChange }: NumberFieldProps) {
  return (
    <label>
      {label}
      <input
        min={0}
        type="number"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  )
}

function EmptyState({ isLoading }: { isLoading: boolean }) {
  return (
    <div className="empty-state">
      <span className="empty-visual">
        {isLoading ? <Loader2 className="spin" size={34} aria-hidden="true" /> : <Network size={34} aria-hidden="true" />}
      </span>
      <span className="empty-kicker">Repository intelligence workspace</span>
      <h2>{isLoading ? '正在构建仓库上下文' : '从一个 GitHub 仓库开始'}</h2>
      <p>{isLoading ? '正在同步代码、Issue、提交记录并生成项目结构分析。' : '连接仓库后，项目结构、Issue 分析、活动记录和智能问答会在同一个工作台中展开。'}</p>
      <div className="empty-steps">
        <span><strong>01</strong>同步数据</span>
        <ArrowRight size={15} />
        <span><strong>02</strong>解析项目</span>
        <ArrowRight size={15} />
        <span><strong>03</strong>智能协作</span>
      </div>
    </div>
  )
}

function IssueWorkflow({ issues, eventCount }: { issues: GitHubIssue[]; eventCount: number }) {
  const classified = issues.filter((issue) => issue.classification?.category).length
  const actionReady = issues.filter((issue) => ['bug', 'feature_request'].includes(issue.classification?.category)).length
  const needsReply = issues.filter((issue) => ['question', 'info_needed', 'duplicate'].includes(issue.classification?.category)).length

  const stages = [
    { label: '事件接入', value: eventCount || issues.length, note: 'Webhook / 同步', complete: issues.length > 0 },
    { label: '自动分类', value: classified, note: '规则与 LLM', complete: classified > 0 },
    { label: '回复建议', value: needsReply, note: '等待维护者确认', complete: needsReply > 0 },
    { label: '修复候选', value: actionReady, note: '定位代码与方案', complete: actionReady > 0 },
  ]

  return (
    <div className="issue-workflow">
      <div className="workflow-heading">
        <div><Workflow size={17} /><strong>Issue 处理流水线</strong></div>
        <span>自动化状态概览</span>
      </div>
      <div className="workflow-stages">
        {stages.map((stage, index) => (
          <div className={`workflow-stage ${stage.complete ? 'complete' : ''}`} key={stage.label}>
            <span className="stage-index">{stage.complete ? <CheckCircle2 size={17} /> : String(index + 1).padStart(2, '0')}</span>
            <div><strong>{stage.label}</strong><small>{stage.note}</small></div>
            <b>{stage.value}</b>
            {index < stages.length - 1 && <ArrowRight className="stage-arrow" size={16} />}
          </div>
        ))}
      </div>
    </div>
  )
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <article className="metric">
      <span className="metric-icon">{icon}</span>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
      </div>
    </article>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      {children}
    </section>
  )
}

function CategoryBars({ summaries, total }: { summaries: CategorySummary[]; total: number }) {
  if (summaries.length === 0 || total === 0) {
    return <p className="muted">暂无数据</p>
  }

  return (
    <div className="bars">
      {summaries.map((summary) => {
        const percent = Math.round((summary.count / total) * 100)
        return (
          <div className="bar-row" key={summary.category}>
            <div>
              <span>{formatCategory(summary.category)}</span>
              <span>{summary.count}</span>
            </div>
            <div className="bar-track">
              <span style={{ width: `${Math.max(percent, 4)}%` }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CompactList({ items }: { items: { key: string | number; title: string; meta: string; href: string }[] }) {
  if (items.length === 0) {
    return <p className="muted">暂无数据</p>
  }

  return (
    <div className="compact-list">
      {items.map((item) => (
        <a href={item.href} target="_blank" key={item.key}>
          <strong>{item.title}</strong>
          <span>{item.meta}</span>
        </a>
      ))}
    </div>
  )
}

// -- Formatting helpers ----------------------------------------------------

function formatCategory(category: string) {
  return category.replaceAll('_', ' ')
}

function formatProjectCategory(category: string) {
  const labels: Record<string, string> = {
    source_code: '源码',
    tests: '测试',
    documentation: '文档',
    configuration: '配置',
    ci_cd: 'CI/CD',
    dependency: '依赖配置',
    build: '构建',
    assets: '静态资源',
    data: '数据',
    other: '其他',
  }
  return labels[category] ?? category.replaceAll('_', ' ')
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function formatTimeAgo(value: string) {
  const diff = Date.now() - new Date(value).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  return `${days} 天前`
}

function analyzeProject(snapshot: RepositorySnapshot): ProjectAnalysis {
  const files = snapshot.files
  const categoryMap = new Map(snapshot.file_categories.map((item) => [item.category, item.count]))
  const directoryCounter = new Map<string, { count: number; sourceCount: number; categories: Map<string, number> }>()

  for (const file of files) {
    const directory = file.path.includes('/') ? file.path.split('/')[0] : '(root)'
    const current = directoryCounter.get(directory) ?? { count: 0, sourceCount: 0, categories: new Map<string, number>() }
    current.count += 1
    if (file.category === 'source_code') current.sourceCount += 1
    current.categories.set(file.category, (current.categories.get(file.category) ?? 0) + 1)
    directoryCounter.set(directory, current)
  }

  const topDirectories = Array.from(directoryCounter.entries())
    .map(([name, value]) => {
      const mainCategory = Array.from(value.categories.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'other'
      return { name, count: value.count, mainCategory, sourceCount: value.sourceCount }
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)

  const dependencyFiles = files.filter((file) => file.category === 'dependency')
  const testFiles = files.filter((file) => file.category === 'tests')
  const docFiles = files.filter((file) => file.category === 'documentation')
  const configFiles = files.filter((file) => file.category === 'configuration')
  const ciFiles = files.filter((file) => file.category === 'ci_cd')
  const sourceCount = categoryMap.get('source_code') ?? 0
  const entryFiles = files.filter((file) => file.category === 'source_code' && isEntryCandidate(file.path))
  const primaryLanguage = getPrimaryLanguage(snapshot)
  const analysisWarning = sourceCount === 0 && primaryLanguage
    ? `GitHub 语言统计显示主要语言为 ${primaryLanguage}，但当前文件样本未覆盖源码目录，建议扩大同步范围后再确认。`
    : null

  return {
    projectType: inferProjectType(snapshot),
    analyzedFileCount: files.length,
    analysisWarning,
    sourceCount,
    dependencyFiles,
    dependencyPackages: [],
    detectedFrameworks: [],
    testFiles,
    docFiles,
    configFiles,
    entryFiles,
    ciFiles,
    topDirectories,
    analysisSource: 'local_fallback',
  }
}

function mapProjectAnalysis(response: ProjectStructureResponse): ProjectAnalysis {
  return {
    projectType: localizeProjectType(response.project_type),
    analyzedFileCount: response.analyzed_file_count,
    analysisWarning: response.analysis_warning ? localizeAnalysisWarning(response.analysis_warning) : null,
    sourceCount: response.source_count,
    dependencyFiles: response.dependency_files,
    dependencyPackages: response.dependency_packages,
    detectedFrameworks: response.detected_frameworks,
    testFiles: response.test_files,
    docFiles: response.doc_files,
    configFiles: response.config_files,
    entryFiles: response.entry_files,
    ciFiles: response.ci_files,
    topDirectories: response.top_directories.map((item) => ({
      name: item.name,
      count: item.count,
      mainCategory: item.main_category,
      sourceCount: item.source_count,
    })),
    analysisSource: 'backend',
  }
}

function localizeProjectType(projectType: string) {
  const labels: Record<string, string> = {
    'Full-stack project: Python backend plus web frontend': '全栈项目：Python 后端 + Web 前端',
    'Python backend or tooling project': 'Python 后端或工具库项目',
    'Web frontend or Node.js project': 'Web 前端或 Node.js 项目',
    'Unknown primary stack': '暂未识别主要技术栈',
  }
  return labels[projectType] ?? projectType.replace('-first project', ' 为主的项目')
}

function localizeAnalysisWarning(warning: string) {
  if (warning.startsWith('GitHub reports ')) {
    const language = warning.match(/^GitHub reports (.+?) as/)?.[1] ?? '某种语言'
    return `GitHub 语言统计显示主要语言为 ${language}，但后端没有取得可分析的源码文件。`
  }
  if (warning.startsWith('Dependency manifests were found')) {
    return '已发现依赖清单，但未能解析出具体依赖条目。'
  }
  return warning
}

const WEB_LANGUAGES = new Set(['typescript', 'javascript', 'tsx', 'vue', 'css', 'html'])
const SIGNIFICANT_LANGUAGE_SHARE = 0.1

function inferProjectType(snapshot: RepositorySnapshot) {
  const languageEntries = Object.entries(snapshot.stats.languages)
  const totalBytes = languageEntries.reduce((total, [, bytes]) => total + Math.max(bytes, 0), 0)
  const languageShare = (names: Set<string>) => totalBytes === 0
    ? 0
    : languageEntries.reduce(
        (total, [language, bytes]) => total + (names.has(language.toLowerCase()) ? Math.max(bytes, 0) : 0),
        0,
      ) / totalBytes
  const primaryLanguage = snapshot.stats.primary_language?.toLowerCase()
  const hasPython = primaryLanguage === 'python' || languageShare(new Set(['python'])) >= SIGNIFICANT_LANGUAGE_SHARE
  const hasFrontend = languageShare(WEB_LANGUAGES) >= SIGNIFICANT_LANGUAGE_SHARE

  if (hasPython && hasFrontend) return '全栈项目：Python 后端 + Web 前端'
  if (hasPython) return 'Python 后端或工具库项目'
  if (hasFrontend) return 'Web 前端或 Node.js 项目'
  if (languageEntries.length > 0) return `${getPrimaryLanguage(snapshot)} 为主的项目`
  return '暂未识别主要技术栈'
}

function getPrimaryLanguage(snapshot: RepositorySnapshot) {
  if (snapshot.stats.primary_language) return snapshot.stats.primary_language
  return Object.entries(snapshot.stats.languages).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
}

function isEntryCandidate(path: string) {
  const normalized = path.toLowerCase()
  const segments = normalized.split('/')
  const fileName = segments.at(-1)
  const excludedDirectories = new Set(['doc', 'docs', 'test', 'tests', 'example', 'examples', 'fixture', 'fixtures', 'sample', 'samples', '.github'])
  if (segments.slice(0, -1).some((segment) => excludedDirectories.has(segment))) return false
  return Boolean(
    fileName &&
    [
      'main.py',
      'app.py',
      'server.py',
      'manage.py',
      'index.js',
      'index.ts',
      'main.ts',
      'main.tsx',
      'app.tsx',
      'program.cs',
    ].includes(fileName)
  )
}

function FileBrowser({ files, owner, name }: { files: ClassifiedFile[]; owner: string; name: string }) {
  const [selectedFile, setSelectedFile] = useState<ClassifiedFile | null>(null)
  const [fileContent, setFileContent] = useState<RepositoryFileContent | null>(null)
  const [contentLoading, setContentLoading] = useState(false)
  const [contentError, setContentError] = useState<string | null>(null)

  async function handleFileClick(file: ClassifiedFile) {
    setSelectedFile(file)
    setContentLoading(true)
    setContentError(null)
    setFileContent(null)

    try {
      const content = await fetchFileContentApi(owner, name, file.path)
      setFileContent(content)
    } catch (exc) {
      setContentError(exc instanceof Error ? exc.message : '加载文件内容失败')
    } finally {
      setContentLoading(false)
    }
  }

  function closeViewer() {
    setSelectedFile(null)
    setFileContent(null)
    setContentError(null)
  }

  return (
    <Panel title={`源代码文件 · ${files.length} 个索引`}>
      <p className="muted" style={{ marginBottom: '0.75rem', fontSize: '0.85rem' }}>
        点击文件路径查看数据库中保存的完整源码内容
      </p>
      <div className="file-list file-browser-list">
        {files.map((file) => (
          <div
            className={`file-item ${selectedFile?.path === file.path ? 'file-item-active' : ''}`}
            key={file.path}
            onClick={() => handleFileClick(file)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') handleFileClick(file)
            }}
            role="button"
            tabIndex={0}
          >
            <span>{file.path}</span>
            <span>{formatCategory(file.category)}</span>
          </div>
        ))}
      </div>

      {selectedFile && (
        <div className="code-viewer-overlay" onClick={closeViewer}>
          <div className="code-viewer" onClick={(event) => event.stopPropagation()}>
            <header className="code-viewer-header">
              <div>
                <FileCode2 size={18} aria-hidden="true" />
                <div>
                  <strong>{selectedFile.path}</strong>
                  <span className="code-viewer-meta">
                    {formatCategory(selectedFile.category)}
                    {selectedFile.size != null && ` · ${(selectedFile.size / 1024).toFixed(1)} KB`}
                  </span>
                </div>
              </div>
              <button className="ghost-button" onClick={closeViewer} aria-label="关闭">
                <X size={18} />
              </button>
            </header>
            <div className="code-viewer-body">
              {contentLoading ? (
                <div className="code-viewer-loading">
                  <Loader2 className="spin" size={24} aria-hidden="true" />
                  <span>从数据库加载源码...</span>
                </div>
              ) : contentError ? (
                <div className="notice error">
                  <AlertCircle size={16} aria-hidden="true" />
                  <span>{contentError}</span>
                </div>
              ) : fileContent ? (
                <pre className="code-block">
                  <code>{fileContent.content}</code>
                </pre>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </Panel>
  )
}

// -- Issue Detail Modal (from UI prototype) --------------------------------

type IssueDetailModalProps = {
  event: WebhookEventDetail
  onClose: () => void
}

function IssueDetailModal({ event, onClose }: IssueDetailModalProps) {
  const [replyStatus, setReplyStatus] = useState<'idle' | 'posting' | 'done' | 'error'>('idle')
  const [replyUrl, setReplyUrl] = useState('')
  const classification = event.classification
  const ghUrl = `https://github.com/${event.repository}/issues/${event.issue_number}`
  const cat = classification?.category ?? ''

  async function handleConfirmReply() {
    setReplyStatus('posting')
    try {
      const result = await postWebhookReply(event.event_id)
      setReplyUrl(result.comment_url)
      setReplyStatus('done')
    } catch {
      setReplyStatus('error')
    }
  }

  const categoryLabels: Record<string, { icon: string; title: string }> = {
    bug:           { icon: '🐛', title: '缺陷报告' },
    feature_request: { icon: '💡', title: '功能请求' },
    question:      { icon: '❓', title: '使用咨询' },
    documentation: { icon: '📖', title: '文档问题' },
    duplicate:     { icon: '🔁', title: '重复 Issue' },
    info_needed:   { icon: '📋', title: '信息不足' },
    invalid:       { icon: '🚫', title: '无效 Issue' },
    maintenance:   { icon: '🔧', title: '维护事项' },
    unknown:       { icon: '🤔', title: '未分类' },
  }

  const labelInfo = categoryLabels[cat]

  return (
    <div className="issue-detail">
      <div className="modal-header">
        <h3>Issue #{event.issue_number}</h3>
        <button className="icon-button" onClick={onClose}>&#x2715;</button>
      </div>

      <div className="issue-detail-header">
        <div className="issue-number">
          #{event.issue_number} · {event.issue_state} · {event.issue_author ?? 'unknown'}
          {event.issue_labels && event.issue_labels.length > 0 && (
            <> · 标签: {event.issue_labels.join(', ')}</>
          )}
        </div>
        <h3>{event.issue_title}</h3>
      </div>

      {classification && classification.category && (
        <div className="classification-detail">
          <h4>
            {labelInfo?.icon ?? ''} {labelInfo?.title ?? formatCategory(cat)}
            <span className={`badge ${cat}`}>
              {formatCategory(cat)}
            </span>
            {classification.confidence != null && (
              <span className="confidence-text">
                置信度 {Math.round(classification.confidence * 100)}%
              </span>
            )}
          </h4>
          {classification.reason && (
            <div className="classification-row">
              <span className="label">分析理由</span>
              <div className="value"><p>{classification.reason}</p></div>
            </div>
          )}
          {classification.confidence != null && (
            <div className="classification-row">
              <span className="label">置信度</span>
              <div className="value">
                <div className="confidence-bar">
                  <span style={{ width: `${Math.round(classification.confidence * 100)}%` }} />
                </div>
              </div>
            </div>
          )}

          {classification.signals && classification.signals.length > 0 && (
            <div className="classification-row">
              <span className="label">识别信号</span>
              <div className="value">
                <div className="signal-list">
                  {classification.signals.map((s) => (
                    <span className="signal-tag" key={s}>{s}</span>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── LLM auto-reply draft + confirm button ── */}
      {classification?.auto_reply_draft && (
        <div className="auto-reply-section">
          <h4>🤖 自动回复草稿</h4>
          <div className="issue-body">{classification.auto_reply_draft}</div>
          {replyStatus === 'idle' && (
            <button className="primary-button" onClick={handleConfirmReply} style={{ marginTop: 8 }}>
              确认回复
            </button>
          )}
          {replyStatus === 'posting' && (
            <button className="primary-button" disabled style={{ marginTop: 8 }}>
              正在生成回复...
            </button>
          )}
          {replyStatus === 'done' && (
            <div style={{ marginTop: 8, fontSize: 13, color: '#18794e' }}>
              回复已发布 →
              <a href={replyUrl} target="_blank" style={{ marginLeft: 4 }}>查看评论</a>
            </div>
          )}
          {replyStatus === 'error' && (
            <div style={{ marginTop: 8, fontSize: 13, color: '#b42318' }}>
              回复发布失败。
              <button className="ghost-button" onClick={handleConfirmReply} style={{ marginLeft: 8, minHeight: 30, padding: '0 10px' }}>
                重试
              </button>
            </div>
          )}
        </div>
      )}

      <div className="issue-detail-links">
        <a className="ghost-button" href={ghUrl} target="_blank">
          ↗ 在 GitHub 上查看 #{event.issue_number}
        </a>
      </div>
    </div>
  )
}

// ── Issue Overview Modal (open/closed lists) -----------------------------

function IssueOverviewModal({ issues, onSelect, onClose }: {
  issues: GitHubIssue[]
  onSelect: (issue: GitHubIssue) => void
  onClose: () => void
}) {
  const open = issues.filter(i => i.state === 'open')
  const closed = issues.filter(i => i.state === 'closed')

  return (
    <div className="issue-detail">
      <div className="modal-header">
        <h3>全部 Issues</h3>
        <button className="icon-button" onClick={onClose}>&#x2715;</button>
      </div>

      <h4 style={{ margin: '12px 0 6px', fontSize: 14 }}>Open ({open.length})</h4>
      <div className="table" style={{ marginBottom: 20 }}>
        {open.map(issue => (
          <button className="table-row issue-row" key={issue.number} onClick={() => onSelect(issue)}>
            <span className="number">#{issue.number}</span>
            <span className="grow">{issue.title}</span>
            <span className={`badge ${issue.classification.category}`}>{formatCategory(issue.classification.category)}</span>
            <span className="confidence">{Math.round(issue.classification.confidence * 100)}%</span>
          </button>
        ))}
        {open.length === 0 && <p className="muted" style={{ padding: 12 }}>暂无 open issue</p>}
      </div>

      <h4 style={{ margin: '12px 0 6px', fontSize: 14 }}>Closed ({closed.length})</h4>
      <div className="table">
        {closed.map(issue => (
          <button className="table-row issue-row" key={issue.number} onClick={() => onSelect(issue)}>
            <span className="number">#{issue.number}</span>
            <span className="grow">{issue.title}</span>
            <span className="muted" style={{ fontSize: 12 }}>{issue.updated_at ? formatDate(issue.updated_at) : ''}</span>
          </button>
        ))}
        {closed.length === 0 && <p className="muted" style={{ padding: 12 }}>暂无 closed issue</p>}
      </div>
    </div>
  )
}

// ── Synced Issue Detail Modal (from main dashboard) -----------------------

type SyncedIssueModalProps = {
  issue: GitHubIssue
  onClose: () => void
}

function SyncedIssueModal({ issue, onClose }: SyncedIssueModalProps) {
  const c = issue.classification
  const ghUrl = issue.html_url

  const categoryIcons: Record<string, string> = {
    bug: '🐛', feature_request: '💡', question: '❓',
    documentation: '📖', duplicate: '🔁', info_needed: '📋',
    invalid: '🚫', maintenance: '🔧', unknown: '🤔',
  }

  return (
    <div className="issue-detail">
      <div className="modal-header">
        <h3>#{issue.number}</h3>
        <button className="icon-button" onClick={onClose}>&#x2715;</button>
      </div>

      <div className="issue-detail-header">
        <div className="issue-number">
          #{issue.number} · {issue.state} · {issue.author ?? 'unknown'}
          {issue.labels.length > 0 && <> · 标签: {issue.labels.join(', ')}</>}
        </div>
        <h3>{issue.title}</h3>
      </div>

      <div className="classification-detail">
        <h4>
          {categoryIcons[c.category] ?? '🤔'} {formatCategory(c.category)}
          <span className={`badge ${c.category}`}>{formatCategory(c.category)}</span>
          <span className="confidence-text">置信度 {Math.round(c.confidence * 100)}%</span>
        </h4>
        <div className="classification-row">
          <span className="label">分析理由</span>
          <div className="value"><p>{c.reason}</p></div>
        </div>
        <div className="classification-row">
          <span className="label">置信度</span>
          <div className="value">
            <div className="confidence-bar"><span style={{ width: `${Math.round(c.confidence * 100)}%` }} /></div>
          </div>
        </div>
        {c.signals.length > 0 && (
          <div className="classification-row">
            <span className="label">识别信号</span>
            <div className="value">
              <div className="signal-list">{c.signals.map(s => <span className="signal-tag" key={s}>{s}</span>)}</div>
            </div>
          </div>
        )}
      </div>

      <div className="issue-detail-links">
        <a className="ghost-button" href={ghUrl} target="_blank">
          ↗ 在 GitHub 上查看 #{issue.number}
        </a>
      </div>
    </div>
  )
}

export default App
