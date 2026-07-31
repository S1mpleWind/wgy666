/**
 * Shared dashboard UI components — Metric card, Panel wrapper,
 * CategoryBars distribution, and CompactList link list.
 */
import type { ReactNode } from 'react'
import { formatCategory } from '../utils/format'
import type { CategorySummary } from '../api'
import '../component-css/MetricCard.css'

/* ── Metric ───────────────────────────────────────────────────────────── */

export function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
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

/* ── Panel ────────────────────────────────────────────────────────────── */

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      {children}
    </section>
  )
}

/* ── CategoryBars ─────────────────────────────────────────────────────── */

export function CategoryBars({ summaries, total }: { summaries: CategorySummary[]; total: number }) {
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

/* ── CompactList ──────────────────────────────────────────────────────── */

export function CompactList({ items }: { items: { key: string | number; title: string; meta: string; href: string }[] }) {
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
