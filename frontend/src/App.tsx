import { useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { AlertCircle, FolderGit, GitBranch, Loader2, RefreshCw, Search, Star } from 'lucide-react'
import './App.css'
import { syncRepository } from './api'
import type { CategorySummary, RepositorySnapshot } from './api'

/**
 * App — Single-page sync-and-dashboard application.
 */
 */

const defaultForm = {
  url: 'https://github.com/fastapi/fastapi',
  max_issues: 30,
  max_pull_requests: 15,
  max_commits: 12,
  max_tree_items: 600,
}

function App() {
  const [form, setForm] = useState(defaultForm)
  const [snapshot, setSnapshot] = useState<RepositorySnapshot | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // -- Sync form handler --------------------------------------------------

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsLoading(true)
    setError(null)

    try {
      const result = await syncRepository(form)
      setSnapshot(result)
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

  return (
    <main className="workspace">
      {/* -- Sidebar: sync form + module info ------------------------------- */}
      <aside className="sidebar">
        <div className="brand">
          <FolderGit size={28} aria-hidden="true" />
          <div>
            <h1>IssueScope</h1>
            <p>GitHub Issue Analysis</p>
          </div>
        </div>

        <form className="sync-form" onSubmit={handleSubmit}>
          <label>
            GitHub 仓库
            <input
              value={form.url}
              onChange={(event) => setForm({ ...form, url: event.target.value })}
              placeholder="https://github.com/owner/repo"
            />
          </label>

          <div className="field-grid">
            <NumberField label="Issues" value={form.max_issues} onChange={(value) => setForm({ ...form, max_issues: value })} />
            <NumberField label="PRs" value={form.max_pull_requests} onChange={(value) => setForm({ ...form, max_pull_requests: value })} />
            <NumberField label="Commits" value={form.max_commits} onChange={(value) => setForm({ ...form, max_commits: value })} />
            <NumberField label="Files" value={form.max_tree_items} onChange={(value) => setForm({ ...form, max_tree_items: value })} />
          </div>

          <button className="primary-button" disabled={isLoading} type="submit">
            {isLoading ? <Loader2 className="spin" size={18} aria-hidden="true" /> : <RefreshCw size={18} aria-hidden="true" />}
            同步仓库
          </button>
        </form>

        {error && (
          <div className="notice error">
            <AlertCircle size={18} aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        <section className="sidebar-section">
          <h2>当前模块边界</h2>
          <ul>
            <li>GitHub REST API 接入</li>
            <li>仓库文件规则分类</li>
            <li>Issue 初版规则分类</li>
            <li>后续数据库与 RAG 可替换接入</li>
          </ul>
        </section>
      </aside>

      {/* -- Main content: dashboard --------------------------------------- */}
      <section className="content">
        {!snapshot ? (
          <EmptyState isLoading={isLoading} />
        ) : (
          <>
            {/* Repository header */}
            <header className="repo-header">
              <div>
                <p className="eyebrow">Synced {formatDate(snapshot.synced_at)}</p>
                <h2>{snapshot.identity.full_name}</h2>
                <p className="description">{snapshot.description ?? 'No repository description.'}</p>
                <div className="topic-row">
                  {snapshot.topics.slice(0, 8).map((topic) => (
                    <span key={topic}>{topic}</span>
                  ))}
                </div>
              </div>
              <a className="ghost-button" href={snapshot.identity.html_url} target="_blank">
                <FolderGit size={18} aria-hidden="true" />
                GitHub
              </a>
            </header>

            {/* Metric cards */}
            <section className="metric-grid">
              <Metric icon={<Star size={18} />} label="Stars" value={snapshot.stats.stars.toLocaleString()} />
              <Metric icon={<GitBranch size={18} />} label="Forks" value={snapshot.stats.forks.toLocaleString()} />
              <Metric icon={<AlertCircle size={18} />} label="Open Issues" value={snapshot.stats.open_issues.toLocaleString()} />
              <Metric icon={<Search size={18} />} label="Indexed Files" value={snapshot.files.length.toLocaleString()} />
            </section>

            {/* Classification breakdowns */}
            <section className="two-column">
              <Panel title="Issue 分类">
                <CategoryBars summaries={snapshot.issue_categories} total={snapshot.issues.length} />
              </Panel>
              <Panel title="文件分类">
                <CategoryBars summaries={snapshot.file_categories} total={snapshot.files.length} />
              </Panel>
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

            {/* Issue list */}
            <Panel title="Issues">
              <div className="table">
                {snapshot.issues.slice(0, 12).map((issue) => (
                  <a className="table-row issue-row" href={issue.html_url} target="_blank" key={issue.number}>
                    <span className="number">#{issue.number}</span>
                    <span className="grow">{issue.title}</span>
                    <span className={`badge ${issue.classification.category}`}>{formatCategory(issue.classification.category)}</span>
                    <span className="confidence">{Math.round(issue.classification.confidence * 100)}%</span>
                  </a>
                ))}
              </div>
            </Panel>

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

            {/* File sample */}
            <Panel title="文件样本">
              <div className="file-list">
                {snapshot.files.slice(0, 24).map((file) => (
                  <div className="file-item" key={file.path}>
                    <span>{file.path}</span>
                    <span>{formatCategory(file.category)}</span>
                  </div>
                ))}
              </div>
            </Panel>
          </>
        )}
      </section>
    </main>
  )
}

// -- Shared UI components --------------------------------------------------

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
      {isLoading ? <Loader2 className="spin" size={36} aria-hidden="true" /> : <FolderGit size={42} aria-hidden="true" />}
      <h2>{isLoading ? '正在同步仓库' : '等待仓库同步'}</h2>
      <p>输入公开 GitHub 仓库地址后，这里会显示仓库信息、文件分类、Issue 分类、PR 和提交记录。</p>
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

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export default App
