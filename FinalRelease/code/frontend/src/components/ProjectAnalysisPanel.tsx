/**
 * ProjectAnalysisPanel — project structure overview card with mindmap and detail grid.
 */
import type { ReactNode } from 'react'
import {
  AlertCircle, ArrowRight, Boxes, FileCode2, FileText, Package,
  Settings2, TestTube2,
} from 'lucide-react'

import type { AnalysisSection, ProjectStructureAnalysis } from '../ProjectStructureDetails'
import { formatProjectCategory } from '../utils/format'
import { Panel } from './MetricCard'
import '../component-css/ProjectAnalysisPanel.css'

/* ── MindmapNode ──────────────────────────────────────────────────────── */

function MindmapNode({ icon, label, value, onClick }: { icon: ReactNode; label: string; value: number; onClick: () => void }) {
  return (
    <button className="mindmap-node" type="button" onClick={onClick}>
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </button>
  )
}

/* ── AnalysisCard ─────────────────────────────────────────────────────── */

function AnalysisCard({ icon, title, items, emptyText = '暂无数据', onClick }: {
  icon: ReactNode
  title: string
  items: string[]
  emptyText?: string
  onClick: () => void
}) {
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

/* ── ProjectAnalysisPanel ─────────────────────────────────────────────── */

export function ProjectAnalysisPanel({ analysis, repositoryName, onOpen }: {
  analysis: ProjectStructureAnalysis
  repositoryName: string
  onOpen: (section: AnalysisSection) => void
}) {
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
