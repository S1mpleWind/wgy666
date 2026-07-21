/**
 * IssueModals — three modal components for issue detail display.
 *
 * - IssueDetailModal: webhook-triggered issue detail with auto-reply
 * - IssueOverviewModal: list of all open / closed issues
 * - SyncedIssueModal: detail for a sync-sourced issue
 */
import { useState } from 'react'
import { postAutoFix, postWebhookReply } from '../api'
import type { GitHubIssue, WebhookEventDetail } from '../api'
import { formatCategory, formatDate } from '../utils/format'
import '../component-css/IssueModals.css'

/* ── IssueDetailModal ─────────────────────────────────────────────────── */

type IssueDetailModalProps = {
  event: WebhookEventDetail
  onClose: () => void
}

function IssueDetailModal({ event, onClose }: IssueDetailModalProps) {
  const [replyStatus, setReplyStatus] = useState<'idle' | 'posting' | 'done' | 'error'>('idle')
  const [replyUrl, setReplyUrl] = useState('')
  const [replySource, setReplySource] = useState<string | undefined>(undefined)
  const [fixStatus, setFixStatus] = useState<'idle' | 'posting' | 'done' | 'error'>('idle')
  const [fixUrl, setFixUrl] = useState('')
  const [replyError, setReplyError] = useState('')
  const [fixError, setFixError] = useState('')
  const classification = event.classification
  const ghUrl = `https://github.com/${event.repository}/issues/${event.issue_number}`
  const cat = classification?.category ?? ''

  async function handleConfirmReply() {
    setReplyStatus('posting')
    setReplyError('')
    try {
      const result = await postWebhookReply(event.event_id)
      setReplyUrl(result.comment_url)
      setReplySource(result.source)
      setReplyStatus('done')
    } catch (exc) {
      setReplyError(exc instanceof Error ? exc.message : '回复失败')
      setReplyStatus('error')
    }
  }

  async function handleConfirmFix() {
    setFixStatus('posting')
    setFixError('')
    try {
      const result = await postAutoFix(event.event_id)
      setFixUrl(result.pr_url)
      setFixStatus('done')
    } catch (exc) {
      setFixError(exc instanceof Error ? exc.message : '修复失败')
      setFixStatus('error')
    }
  }

  const categoryLabels: Record<string, { icon: string; title: string }> = {
    bug:              { icon: '🐛', title: '缺陷报告' },
    feature_request:  { icon: '💡', title: '功能请求' },
    question:         { icon: '❓', title: '使用咨询' },
    documentation:    { icon: '📖', title: '文档问题' },
    duplicate:        { icon: '🔁', title: '重复 Issue' },
    info_needed:      { icon: '📋', title: '信息不足' },
    invalid:          { icon: '🚫', title: '无效 Issue' },
    maintenance:      { icon: '🔧', title: '维护事项' },
    unknown:          { icon: '🤔', title: '未分类' },
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
              {replySource && (
                <span style={{ marginLeft: 8, fontSize: 11, color: '#6a747e' }}>
                  （来源: {replySource === 'faq' ? 'FAQ 知识库' : 'LLM Agent'})
                </span>
              )}
            </div>
          )}
          {replyStatus === 'error' && (
            <div style={{ marginTop: 8, fontSize: 13, color: '#b42318' }}>
              回复发布失败。{replyError && <span style={{ marginLeft: 4, fontSize: 11, color: "#6a747e" }}>({replyError})</span>}
              <button className="ghost-button" onClick={handleConfirmReply} style={{ marginLeft: 8, minHeight: 30, padding: '0 10px' }}>
                重试
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Auto-fix button for bug issues ── */}
      {cat === 'bug' && (
        <div className="auto-reply-section" style={{ borderColor: '#f0c030' }}>
          <h4 style={{ color: '#b8860b' }}>🔧 自动修复</h4>
          {fixStatus === 'idle' && (
            <button className="primary-button" onClick={handleConfirmFix} style={{ marginTop: 8 }}>
              确认修复并提 PR
            </button>
          )}
          {fixStatus === 'posting' && (
            <button className="primary-button" disabled style={{ marginTop: 8 }}>
              正在分析并生成修复...
            </button>
          )}
          {fixStatus === 'done' && (
            <div style={{ marginTop: 8, fontSize: 13, color: '#18794e' }}>
              PR 已创建 →
              <a href={fixUrl} target="_blank" style={{ marginLeft: 4 }}>查看 PR</a>
            </div>
          )}
          {fixStatus === 'error' && (
            <div style={{ marginTop: 8, fontSize: 13, color: '#b42318' }}>
              自动修复失败。{fixError && <span style={{ marginLeft: 4, fontSize: 11, color: "#6a747e" }}>({fixError})</span>}
              <button className="ghost-button" onClick={handleConfirmFix} style={{ marginLeft: 8, minHeight: 30, padding: '0 10px' }}>
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

/* ── IssueOverviewModal ───────────────────────────────────────────────── */

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

/* ── SyncedIssueModal ─────────────────────────────────────────────────── */

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

export { IssueDetailModal, IssueOverviewModal, SyncedIssueModal }
