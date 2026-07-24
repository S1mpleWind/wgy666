import { useMemo, useState, useEffect, useCallback } from 'react'
import type { FormEvent } from 'react'
import {
  Activity, AlertCircle, ArrowRight, Bell, BookOpen, Bot, ChevronDown, CircleDot,
  Database, FolderGit, GitBranch, LayoutDashboard, Loader2, Network,
  RefreshCw, Search, Settings2, ShieldCheck, Sparkles, Star, Users,
} from 'lucide-react'
import './App.css'

import { fetchProjectStructure, fetchRepositoryList, fetchRepositorySnapshot, fetchWebhookConfig, fetchWebhookEventDetail, fetchWebhookEvents, syncRepository, updateWebhookEvent } from "./api"
import FaqPage from "./FaqPage"
import type { GitHubIssue, RepositoryListItem, RepositorySnapshot, WebhookEventDetail, WebhookEventItem } from './api'

import { ProjectStructureDetails } from './ProjectStructureDetails'
import type { AnalysisSection, ProjectStructureAnalysis } from './ProjectStructureDetails'

import { formatCategory, formatDate, formatTimeAgo } from './utils/format'
import { analyzeProject, mapProjectAnalysis } from './utils/projectAnalysis'

import { CompactList, CategoryBars, Metric, Panel } from './components/MetricCard'
import { NumberField } from './components/NumberField'
import { EmptyState } from './components/EmptyState'
import { IssueWorkflow } from './components/IssueWorkflow'
import { FileBrowser } from './components/FileBrowser'
import { ChatSidebar } from './components/ChatSidebar'
import { IssueDetailModal, IssueOverviewModal, SyncedIssueModal } from './components/IssueModals'
import { ProjectAnalysisPanel } from './components/ProjectAnalysisPanel'
import { UserManagement } from './components/UserManagement'

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

type WorkspaceSection = 'overview' | 'analysis' | 'issues' | 'agent' | 'faq' | 'users'

function App() {
  const [form, setForm] = useState(defaultForm)
  const [snapshot, setSnapshot] = useState<RepositorySnapshot | null>(null)
  const [repoList, setRepoList] = useState<RepositoryListItem[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [showInbox, setShowInbox] = useState(false)
  const [webhookConfig, setWebhookConfig] = useState<{ url: string; secret_configured: boolean } | null>(null)
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
      const events = await fetchWebhookEvents(20, snapshot?.identity.full_name)
      setWebhookEvents(events)
    } catch {
      // silently fail — inbox just stays empty
    } finally {
      setEventsLoading(false)
    }
  }, [snapshot?.identity.full_name])

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
      // Mark as read
      await updateWebhookEvent(event.event_id, 'read')
      setWebhookEvents(prev => prev.map(e =>
        e.event_id === event.event_id ? { ...e, is_read: true } : e
      ))
    } catch {
      setSelectedEvent(null)
    } finally {
      setEventDetailLoading(false)
    }
  }

  async function handleReadEvent(eventId: string) {
    try {
      await updateWebhookEvent(eventId, 'read')
      setWebhookEvents(prev => prev.map(e =>
        e.event_id === eventId ? { ...e, is_read: true } : e
      ))
    } catch { /* ignore */ }
  }

  async function handleDeleteEvent(eventId: string) {
    try {
      await updateWebhookEvent(eventId, 'delete')
      setWebhookEvents(prev => prev.filter(e => e.event_id !== eventId))
    } catch { /* ignore */ }
  }

  // Auto-poll for new notifications (updates the badge count).
  // Also refreshes snapshot when closed/reopened events are detected.
  const repoName = snapshot?.identity.full_name
  useEffect(() => {
    async function pollAndRefresh() {
      try {
        const events = await fetchWebhookEvents(20, repoName)
        setWebhookEvents(events)
        // If a closed/reopened event is detected, refresh the snapshot.
        if (snapshot && repoName && events.some(e => e.action === 'closed' || e.action === 'reopened')) {
          const snap = await fetchRepositorySnapshot(
            snapshot.identity.owner, snapshot.identity.name,
          )
          setSnapshot(snap)
        }
      } catch { /* ignore */ }
    }
    const poll = setInterval(pollAndRefresh, 30000)
    pollAndRefresh()
    return () => clearInterval(poll)
  }, [repoName])

  // -- Load synced repo list on mount + auto-select last one ----------------

  useEffect(() => {
    (async () => {
      try {
        const repos = await fetchRepositoryList()
        setRepoList(repos)
        if (repos.length > 0) {
          const last = localStorage.getItem('lastRepo') || `${repos[0].owner}/${repos[0].name}`
          const match = repos.find(r => `${r.owner}/${r.name}` === last)
          if (match) {
            const snap = await fetchRepositorySnapshot(match.owner, match.name)
            setSnapshot(snap)
            setForm(f => ({ ...f, url: match.html_url }))
          }
        }
      } catch { /* no cached repos */ }
    })()
  }, [])

  // -- Load synced repo list on mount + auto-select last one ----------------

  useEffect(() => {
    (async () => {
      try {
        const repos = await fetchRepositoryList()
        setRepoList(repos)
        if (repos.length > 0) {
          const last = localStorage.getItem('lastRepo') || `${repos[0].owner}/${repos[0].name}`
          const match = repos.find(r => `${r.owner}/${r.name}` === last)
          if (match) {
            const snap = await fetchRepositorySnapshot(match.owner, match.name)
            setSnapshot(snap)
            setForm(f => ({ ...f, url: match.html_url }))
          }
        }
      } catch { /* no cached repos */ }
    })()
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
      fetchRepositoryList().then(setRepoList).catch(() => {})
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

    if (section === 'users') {
      setAnalysisSection(null)
      return
    }

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

        {/* Repository selector */}
        {repoList.length > 1 && (
          <div className="repo-selector">
            <label style={{ fontSize: 11, color: '#6a747e', marginBottom: 4 }}>当前仓库</label>
            <select
              value={snapshot?.identity.full_name ?? ''}
              onChange={async (e) => {
                const [owner, name] = e.target.value.split('/')
                localStorage.setItem('lastRepo', e.target.value)
                const snap = await fetchRepositorySnapshot(owner, name)
                setSnapshot(snap)
                setForm(f => ({ ...f, url: snap.identity.html_url }))
              }}
            >
              {repoList.map(r => (
                <option key={r.full_name} value={r.full_name}>{r.full_name}</option>
              ))}
            </select>
          </div>
        )}
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
          <button aria-pressed={activeWorkspaceSection === 'faq'} className={activeWorkspaceSection === 'faq' ? 'active' : ''} type="button" onClick={() => handleWorkspaceNavigation('faq')}><BookOpen size={17} />FAQ 知识库</button>
          <button aria-pressed={activeWorkspaceSection === 'users'} className={activeWorkspaceSection === 'users' ? 'active' : ''} type="button" onClick={() => handleWorkspaceNavigation('users')}><Users size={17} />用户管理</button>
        </nav>

        <div className="sidebar-actions">
          <button className="ghost-button sidebar-action" onClick={() => setShowInbox(!showInbox)}>
            <span className="bell-wrapper">
              <Bell size={16} aria-hidden="true" />
              {webhookEvents.some(event => !event.is_read) && <span className="badge-dot" />}
            </span>
            通知
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
            <strong>{activeWorkspaceSection === 'users' ? '用户管理' : analysisSection ? '项目解析' : snapshot?.identity.name ?? '仓库工作台'}</strong>
          </div>
          <div className="top-actions">
            <span className="live-status"><span /> 前端在线</span>
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
                      <div className="inbox-item-actions">
                        <button disabled={event.is_read} onClick={(e) => { e.stopPropagation(); handleReadEvent(event.event_id); }}>
                          {event.is_read ? '已读' : '标为已读'}
                        </button>
                        <button className="delete-btn" onClick={(e) => { e.stopPropagation(); handleDeleteEvent(event.event_id); }}>
                          删除
                        </button>
                      </div>
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
                <input value={webhookConfig?.secret_configured ? '已在服务器配置' : '未配置'} readOnly disabled />
              </label>
              <p className="settings-hint">
                在 GitHub 仓库 Settings → Webhooks 中填入以上 URL，并使用服务器环境变量中配置的同一 Secret。
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

        {activeWorkspaceSection === 'users' ? (
          <UserManagement />
        ) : activeWorkspaceSection === 'faq' ? (
          snapshot ? (
            <FaqPage owner={snapshot.identity.owner} name={snapshot.identity.name} />
          ) : (
            <p className="muted" style={{ padding: 40, textAlign: 'center' }}>请先同步仓库以查看 FAQ</p>
          )
        ) : !snapshot ? (
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
              <CategoryBars summaries={snapshot.issue_categories} total={snapshot.issue_categories.reduce((s, c) => s + c.count, 0)} />
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

export default App
