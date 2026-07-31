/**
 * IssueWorkflow — pipeline status overview for issue processing stages.
 */
import { ArrowRight, CheckCircle2, Workflow } from 'lucide-react'
import type { GitHubIssue } from '../api'
import '../component-css/IssueWorkflow.css'

export function IssueWorkflow({ issues, eventCount }: { issues: GitHubIssue[]; eventCount: number }) {
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
