/**
 * EmptyState — initial landing state shown before any repository is synced.
 */
import { ArrowRight, Loader2, Network } from 'lucide-react'
import '../component-css/EmptyState.css'

export function EmptyState({ isLoading }: { isLoading: boolean }) {
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
