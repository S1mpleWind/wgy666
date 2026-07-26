import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
} from '@xyflow/react'
import type { Edge, Node, NodeMouseHandler } from '@xyflow/react'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Code2,
  FileCode2,
  GitCommit,
  GitCompareArrows,
  LoaderCircle,
  Network,
  Play,
  Radar,
  Route,
  ShieldCheck,
  TestTube2,
  X,
} from 'lucide-react'
import {
  analyzeArchitectureImpact,
  fetchArchitectureAnalysis,
  fetchArchitectureDiff,
  fetchArchitectureHistory,
  fetchFileContent,
} from './api'
import type {
  ArchitectureAnalysis,
  ArchitectureDiff,
  ArchitectureHistoryItem,
  CodeSymbol,
  ImpactAnalysis,
  RepositoryFileContent,
  RepositorySnapshot,
} from './api'
import './AdvancedArchitectureViews.css'

export type AdvancedArchitectureSection = 'semantic' | 'impact' | 'health' | 'evolution'

type Props = {
  section: AdvancedArchitectureSection
  repository: RepositorySnapshot
}

type SourcePreview = {
  symbol: CodeSymbol
  content: RepositoryFileContent | null
  loading: boolean
  error: string | null
}

export function AdvancedArchitectureView({ section, repository }: Props) {
  const [analysis, setAnalysis] = useState<ArchitectureAnalysis | null>(null)
  const [history, setHistory] = useState<ArchitectureHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      fetchArchitectureAnalysis(repository.identity.owner, repository.identity.name),
      fetchArchitectureHistory(repository.identity.owner, repository.identity.name),
    ])
      .then(([nextAnalysis, nextHistory]) => {
        if (cancelled) return
        setAnalysis(nextAnalysis)
        setHistory(nextHistory)
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '架构分析加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [repository.identity.name, repository.identity.owner, repository.synced_at])

  if (loading) {
    return (
      <div className="advanced-state">
        <LoaderCircle className="spin" size={24} aria-hidden="true" />
        <div><strong>正在解析源码语义</strong><span>提取符号、调用、路由和测试映射…</span></div>
      </div>
    )
  }
  if (error || !analysis) {
    return (
      <div className="advanced-state error">
        <AlertTriangle size={24} aria-hidden="true" />
        <div><strong>架构分析暂不可用</strong><span>{error ?? '请重新同步仓库后重试。'}</span></div>
      </div>
    )
  }

  if (section === 'semantic') return <SemanticArchitecture analysis={analysis} repository={repository} />
  if (section === 'impact') return <ImpactRadar analysis={analysis} repository={repository} />
  if (section === 'health') return <ArchitectureHealth analysis={analysis} />
  return <ArchitectureEvolution analysis={analysis} history={history} repository={repository} />
}

function SemanticArchitecture({ analysis, repository }: { analysis: ArchitectureAnalysis; repository: RepositorySnapshot }) {
  const graph = useMemo(() => buildSemanticGraph(analysis, repository.identity.name), [analysis, repository.identity.name])
  const symbolByKey = useMemo(() => new Map(analysis.symbols.map((symbol) => [symbol.key, symbol])), [analysis.symbols])
  const [selected, setSelected] = useState<CodeSymbol | null>(null)
  const [preview, setPreview] = useState<SourcePreview | null>(null)

  const handleNodeClick: NodeMouseHandler = (_, node) => {
    setSelected(symbolByKey.get(node.id) ?? null)
  }
  const openSource = async (symbol: CodeSymbol) => {
    if (!symbol.path) return
    setPreview({ symbol, content: null, loading: true, error: null })
    try {
      const content = await fetchFileContent(repository.identity.owner, repository.identity.name, symbol.path)
      setPreview({ symbol, content, loading: false, error: null })
    } catch (reason) {
      setPreview({ symbol, content: null, loading: false, error: reason instanceof Error ? reason.message : '源码加载失败' })
    }
  }

  return (
    <div className="advanced-stack">
      <div className="advanced-metrics">
        <Metric label="源码模块" value={analysis.health.metrics.module_count ?? 0} icon={Code2} />
        <Metric label="语义关系" value={analysis.relations.length} icon={Network} />
        <Metric label="API 路由" value={analysis.routes.length} icon={Route} />
        <Metric label="测试映射" value={analysis.test_mappings.length} icon={TestTube2} />
      </div>
      <section className="advanced-panel semantic-panel">
        <div className="advanced-heading">
          <div><p>Source semantic graph</p><h3>源码语义架构图</h3></div>
          <span>解析器 v{analysis.parser_version}</span>
        </div>
        <div className="semantic-layout">
          <div className="advanced-flow">
            <ReactFlow
              nodes={graph.nodes}
              edges={graph.edges}
              onNodeClick={handleNodeClick}
              fitView
              fitViewOptions={{ padding: 0.16, minZoom: 0.35 }}
              minZoom={0.25}
              maxZoom={1.8}
              nodesConnectable={false}
              nodesDraggable={false}
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={22} size={1.1} color="#c7d8e8" />
              <MiniMap pannable zoomable nodeColor={(node) => String(node.style?.borderColor ?? '#8ca8c4')} maskColor="rgba(238,244,249,.7)" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <aside className="semantic-inspector">
            {selected ? (
              <>
                <span className={`symbol-kind ${selected.kind}`}>{symbolKindLabel(selected.kind)}</span>
                <h4>{selected.name}</h4>
                <code>{selected.qualified_name}</code>
                <dl>
                  <div><dt>语言</dt><dd>{selected.language}</dd></div>
                  <div><dt>位置</dt><dd>{selected.path ?? '外部依赖'}</dd></div>
                  <div><dt>行号</dt><dd>{lineRange(selected)}</dd></div>
                </dl>
                {selected.path && (
                  <button className="advanced-primary" type="button" onClick={() => void openSource(selected)}>
                    <FileCode2 size={15} />查看源码证据
                  </button>
                )}
              </>
            ) : (
              <div className="advanced-empty compact">
                <Network size={24} />
                <strong>选择图中节点</strong>
                <span>可查看模块、类、函数的真实文件位置。</span>
              </div>
            )}
          </aside>
        </div>
      </section>
      <AnalysisCoverage analysis={analysis} />
      {preview && <SourcePreviewDialog preview={preview} onClose={() => setPreview(null)} />}
    </div>
  )
}

function ImpactRadar({ analysis, repository }: { analysis: ArchitectureAnalysis; repository: RepositorySnapshot }) {
  const sourcePaths = useMemo(() => [...new Set(analysis.symbols.filter((item) => item.kind === 'module' && item.path).map((item) => item.path!))].sort(), [analysis.symbols])
  const [path, setPath] = useState(sourcePaths[0] ?? '')
  const [issueText, setIssueText] = useState('')
  const [depth, setDepth] = useState(2)
  const [result, setResult] = useState<ImpactAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const graph = useMemo(() => result ? buildImpactGraph(result) : { nodes: [], edges: [] }, [result])

  const run = async () => {
    if (!path && !issueText.trim()) {
      setError('请选择一个源码文件，或输入 Issue 描述。')
      return
    }
    setLoading(true)
    setError(null)
    try {
      setResult(await analyzeArchitectureImpact(repository.identity.owner, repository.identity.name, {
        paths: path ? [path] : [],
        issue_text: issueText.trim() || undefined,
        max_depth: depth,
      }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '变更影响分析失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="advanced-stack">
      <section className="advanced-panel">
        <div className="advanced-heading">
          <div><p>Change impact radar</p><h3>Issue 变更影响雷达</h3></div>
          <span>规则推导，非 LLM 猜测</span>
        </div>
        <div className="impact-form">
          <label><span>分析起点</span><select value={path} onChange={(event) => setPath(event.target.value)}><option value="">仅使用 Issue 描述</option>{sourcePaths.map((item) => <option value={item} key={item}>{item}</option>)}</select></label>
          <label><span>关系展开层数</span><select value={depth} onChange={(event) => setDepth(Number(event.target.value))}>{[1, 2, 3, 4].map((item) => <option value={item} key={item}>{item} 层</option>)}</select></label>
          <label className="issue-input"><span>Issue 描述（可选）</span><textarea value={issueText} onChange={(event) => setIssueText(event.target.value)} placeholder="例如：修改认证路由后，哪些模块和测试需要回归？" /></label>
          <button className="advanced-primary impact-run" type="button" disabled={loading} onClick={() => void run()}>{loading ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}{loading ? '正在计算' : '开始分析'}</button>
        </div>
        {error && <div className="inline-error"><AlertTriangle size={15} />{error}</div>}
      </section>

      {!result ? (
        <div className="advanced-empty">
          <Radar size={31} />
          <strong>从文件或 Issue 出发计算影响范围</strong>
          <span>系统会沿导入、调用和测试关系，找到受影响文件、API 与回归测试。</span>
        </div>
      ) : (
        <>
          <div className="impact-summary">
            <div className={`risk-orb ${result.risk_level}`}><strong>{result.risk_score}</strong><span>{riskLabel(result.risk_level)}</span></div>
            <Metric label="影响文件" value={result.affected_files.length} icon={FileCode2} />
            <Metric label="影响路由" value={result.affected_routes.length} icon={Route} />
            <Metric label="建议测试" value={result.recommended_tests.length} icon={TestTube2} />
          </div>
          <section className="advanced-panel impact-result-grid">
            <div className={`impact-flow ${graph.nodes.length <= 3 ? 'compact' : ''}`}>
              <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView fitViewOptions={{ padding: 0.2, minZoom: 0.4 }} minZoom={0.3} nodesConnectable={false} nodesDraggable={false} proOptions={{ hideAttribution: true }}>
                <Background variant={BackgroundVariant.Dots} gap={22} size={1.1} color="#c7d8e8" />
                <Controls showInteractive={false} />
              </ReactFlow>
            </div>
            <div className="impact-evidence">
              <h4>分析结论</h4>
              <ul>{result.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
              <h4>回归测试</h4>
              {result.recommended_tests.length ? result.recommended_tests.slice(0, 8).map((item) => <div className="evidence-row" key={item.test_path}><TestTube2 size={14} /><span><strong>{item.test_path}</strong><small>{item.reason} · {Math.round(item.confidence * 100)}%</small></span></div>) : <p>暂无明确测试映射，需手动补充回归范围。</p>}
            </div>
          </section>
        </>
      )}
    </div>
  )
}

function ArchitectureHealth({ analysis }: { analysis: ArchitectureAnalysis }) {
  const health = analysis.health
  return (
    <div className="advanced-stack">
      <section className="advanced-panel health-hero">
        <div className={`health-score grade-${health.grade.toLowerCase()}`}><strong>{health.score}</strong><span>{health.grade} 级</span></div>
        <div className="health-copy"><p>Architecture health</p><h3>架构健康检查</h3><span>结果来自循环导入、模块耦合、文件体量、测试映射和解析覆盖率等确定性规则。</span></div>
        <div className="health-bars"><CoverageBar label="文件内容覆盖" value={analysis.coverage.file_coverage_percent} /><CoverageBar label="语义解析覆盖" value={analysis.coverage.parser_coverage_percent} /></div>
      </section>
      <div className="advanced-metrics health-metrics">
        <Metric label="模块" value={health.metrics.module_count ?? 0} icon={Code2} />
        <Metric label="内部导入" value={health.metrics.internal_import_count ?? 0} icon={Network} />
        <Metric label="循环依赖" value={health.metrics.cycle_count ?? 0} icon={GitCompareArrows} />
        <Metric label="未映射测试" value={health.metrics.untested_module_count ?? 0} icon={TestTube2} />
      </div>
      <section className="advanced-panel">
        <div className="advanced-heading"><div><p>Actionable findings</p><h3>检查结果与修复建议</h3></div><span>{health.issues.length} 项发现</span></div>
        {health.issues.length === 0 ? <div className="health-clean"><CheckCircle2 size={25} /><div><strong>当前规则未发现明显架构问题</strong><span>建议继续保持测试映射和依赖边界。</span></div></div> : <div className="health-findings">{health.issues.map((issue) => <article className={`health-finding ${issue.severity}`} key={issue.code}><div className="finding-icon">{issue.severity === 'critical' ? <AlertTriangle size={19} /> : issue.severity === 'warning' ? <Radar size={19} /> : <ShieldCheck size={19} />}</div><div><div className="finding-title"><strong>{issue.title}</strong><span>{severityLabel(issue.severity)}</span></div><p>{issue.description}</p><small>建议：{issue.suggestion}</small>{issue.evidence_paths.length > 0 && <div className="finding-paths">{issue.evidence_paths.slice(0, 6).map((path) => <code key={path}>{path}</code>)}</div>}</div></article>)}</div>}
      </section>
      {analysis.coverage.warnings.length > 0 && <section className="advanced-panel coverage-warnings"><h3>分析边界</h3>{analysis.coverage.warnings.map((warning) => <p key={warning}><AlertTriangle size={14} />{warning}</p>)}</section>}
    </div>
  )
}

function ArchitectureEvolution({ analysis, history, repository }: { analysis: ArchitectureAnalysis; history: ArchitectureHistoryItem[]; repository: RepositorySnapshot }) {
  const ordered = useMemo(() => [...history].sort((a, b) => new Date(a.generated_at).getTime() - new Date(b.generated_at).getTime()), [history])
  const commits = useMemo(
    () => [...repository.recent_commits].sort((a, b) => new Date(a.committed_at ?? 0).getTime() - new Date(b.committed_at ?? 0).getTime()),
    [repository.recent_commits],
  )
  const analyzedRevisions = useMemo(() => new Set(history.map((item) => item.revision)), [history])
  const [baseRevision, setBaseRevision] = useState(ordered.at(-2)?.revision ?? '')
  const [targetRevision, setTargetRevision] = useState(ordered.at(-1)?.revision ?? analysis.revision)
  const [diff, setDiff] = useState<ArchitectureDiff | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!baseRevision || !targetRevision || baseRevision === targetRevision) {
      setDiff(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchArchitectureDiff(repository.identity.owner, repository.identity.name, baseRevision, targetRevision)
      .then((value) => { if (!cancelled) setDiff(value) })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : '版本差异加载失败') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [baseRevision, repository.identity.name, repository.identity.owner, targetRevision])

  return (
    <div className="advanced-stack">
      <section className="advanced-panel">
        <div className="advanced-heading"><div><p>Architecture evolution</p><h3>Git 提交与架构演化</h3></div><span>{commits.length} 次近期提交 · {history.length} 个架构快照</span></div>
        <p className="evolution-note">下方展示仓库真实 Git 提交；带“已分析”标记的提交保存了完整架构快照，可进行符号、路由和依赖差异比较。</p>
        {commits.length > 0 ? (
          <div className="history-timeline commit-timeline">
            {commits.map((commit, index) => {
              const analyzed = [...analyzedRevisions].some((revision) => revision === commit.sha || revision.startsWith(commit.sha) || commit.sha.startsWith(revision))
              return <article className={`history-point commit-point ${analyzed ? 'analyzed' : ''}`} key={commit.sha}><span className="history-dot" /><small>{commit.committed_at ? new Date(commit.committed_at).toLocaleString('zh-CN') : '时间未知'}</small><div className="commit-revision"><GitCommit size={14} /><strong>{shortRevision(commit.sha)}</strong>{analyzed && <em>已分析</em>}</div><p title={commit.message}>{commit.message.split('\n')[0]}</p><footer><span>{commit.author ?? '未知作者'}</span></footer>{index < commits.length - 1 && <ArrowRight size={16} />}</article>
            })}
          </div>
        ) : <div className="advanced-empty compact"><GitCommit size={25} /><strong>暂无 Git 提交记录</strong><span>重新同步仓库并提高提交获取数量后即可展示。</span></div>}
      </section>
      {ordered.length >= 2 ? <section className="advanced-panel"><div className="advanced-heading compact-heading"><div><p>Snapshot comparison</p><h3>架构快照对比</h3></div><span>仅列出完整分析快照</span></div><div className="version-picker"><label><span>基准版本</span><select value={baseRevision} onChange={(event) => setBaseRevision(event.target.value)}>{ordered.map((item) => <option value={item.revision} key={item.revision}>{shortRevision(item.revision)} · {new Date(item.generated_at).toLocaleString('zh-CN')}</option>)}</select></label><GitCompareArrows size={21} /><label><span>目标版本</span><select value={targetRevision} onChange={(event) => setTargetRevision(event.target.value)}>{ordered.map((item) => <option value={item.revision} key={item.revision}>{shortRevision(item.revision)} · {new Date(item.generated_at).toLocaleString('zh-CN')}</option>)}</select></label></div>{loading && <div className="advanced-state inline"><LoaderCircle className="spin" size={20} />正在比较架构快照…</div>}{error && <div className="inline-error"><AlertTriangle size={15} />{error}</div>}{diff && <DiffReport diff={diff} />}</section> : <section className="advanced-panel"><div className="advanced-empty compact"><GitCompareArrows size={25} /><strong>架构快照不足</strong><span>Git 提交已经展示，但精确架构差异需要至少两次不同提交的仓库同步。</span></div></section>}
    </div>
  )
}

function DiffReport({ diff }: { diff: ArchitectureDiff }) {
  const groups = [
    { label: '新增符号', value: diff.added_symbols.length, tone: 'added' },
    { label: '修改符号', value: diff.changed_symbols.length, tone: 'changed' },
    { label: '删除符号', value: diff.removed_symbols.length, tone: 'removed' },
    { label: '路由变化', value: diff.added_routes.length + diff.removed_routes.length, tone: 'route' },
    { label: '依赖变化', value: diff.added_dependencies.length + diff.removed_dependencies.length, tone: 'dependency' },
  ]
  return <div className="diff-report"><div className="diff-metrics">{groups.map((item) => <div className={item.tone} key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>)}<div className={diff.health_score_delta >= 0 ? 'added' : 'removed'}><span>健康度变化</span><strong>{diff.health_score_delta > 0 ? '+' : ''}{diff.health_score_delta}</strong></div></div><div className="diff-lists"><DiffList title="新增或修改" symbols={[...diff.added_symbols, ...diff.changed_symbols]} empty="没有新增或修改的符号" /><DiffList title="删除" symbols={diff.removed_symbols} empty="没有删除的符号" /></div></div>
}

function DiffList({ title, symbols, empty }: { title: string; symbols: CodeSymbol[]; empty: string }) {
  return <div><h4>{title}</h4>{symbols.length ? symbols.slice(0, 12).map((symbol) => <div className="diff-row" key={`${symbol.key}-${symbol.fingerprint}`}><Code2 size={14} /><span><strong>{symbol.name}</strong><small>{symbol.path ?? symbol.qualified_name}</small></span></div>) : <p>{empty}</p>}</div>
}

function AnalysisCoverage({ analysis }: { analysis: ArchitectureAnalysis }) {
  return <section className="advanced-panel coverage-panel"><div><p>Analysis coverage</p><h3>分析覆盖度</h3></div><CoverageBar label="已索引文件" value={analysis.coverage.file_coverage_percent} /><CoverageBar label="支持语言解析" value={analysis.coverage.parser_coverage_percent} /><span>{analysis.coverage.parsed_source_files}/{analysis.coverage.discovered_source_files} 个源码文件已完成语义解析</span></section>
}

function CoverageBar({ label, value }: { label: string; value: number }) {
  return <div className="coverage-bar"><div><span>{label}</span><strong>{value.toFixed(1)}%</strong></div><i><b style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></i></div>
}

function Metric({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Code2 }) {
  return <article className="advanced-metric"><span><Icon size={18} /></span><div><small>{label}</small><strong>{value}</strong></div></article>
}

function SourcePreviewDialog({ preview, onClose }: { preview: SourcePreview; onClose: () => void }) {
  const lines = preview.content?.content.split('\n') ?? []
  const start = Math.max(1, (preview.symbol.line_start ?? 1) - 8)
  const end = Math.min(lines.length, (preview.symbol.line_end ?? preview.symbol.line_start ?? 1) + 12)
  return <div className="advanced-source-overlay" role="presentation" onMouseDown={onClose}><section className="advanced-source-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><header><div><span>{preview.symbol.kind}</span><strong>{preview.symbol.path}</strong></div><button type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button></header>{preview.loading && <div className="advanced-state"><LoaderCircle className="spin" size={21} />正在读取源码…</div>}{preview.error && <div className="inline-error">{preview.error}</div>}{preview.content && <pre>{lines.slice(start - 1, end).map((line, index) => { const number = start + index; const active = number >= (preview.symbol.line_start ?? 0) && number <= (preview.symbol.line_end ?? 0); return <code className={active ? 'active' : ''} key={number}><span>{number}</span>{line || ' '}</code> })}</pre>}<footer>{preview.content?.truncated && <span>该文件在同步时被截断</span>}<strong>{lineRange(preview.symbol)}</strong></footer></section></div>
}

function buildSemanticGraph(analysis: ArchitectureAnalysis, repositoryName: string): { nodes: Node[]; edges: Edge[] } {
  const degree = new Map<string, number>()
  analysis.relations.forEach((edge) => { degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1); degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1) })
  const modules = analysis.symbols.filter((item) => item.kind === 'module').sort((a, b) => (degree.get(b.key) ?? 0) - (degree.get(a.key) ?? 0)).slice(0, 8)
  const moduleKeys = new Set(modules.map((item) => item.key))
  const childCount = new Map<string, number>()
  const children = analysis.symbols
    .filter((item) => item.parent_key && moduleKeys.has(item.parent_key) && item.kind !== 'module')
    .sort((a, b) => (degree.get(b.key) ?? 0) - (degree.get(a.key) ?? 0))
    .filter((item) => {
      const count = childCount.get(item.parent_key!) ?? 0
      childCount.set(item.parent_key!, count + 1)
      return count < 2
    })
    .slice(0, 16)
  const selectedKeys = new Set([...moduleKeys, ...children.map((item) => item.key)])
  const moduleGap = 142
  const nodes: Node[] = [{ id: 'repository-root', position: { x: 20, y: Math.max(50, ((modules.length - 1) * moduleGap) / 2) }, data: { label: repositoryName }, style: graphNodeStyle('repository') }]
  modules.forEach((item, index) => nodes.push({ id: item.key, position: { x: 330, y: index * moduleGap }, data: { label: compactGraphPath(item.path ?? item.name) }, style: graphNodeStyle('module') }))
  const childrenByParent = new Map<string, CodeSymbol[]>()
  children.forEach((child) => childrenByParent.set(child.parent_key!, [...(childrenByParent.get(child.parent_key!) ?? []), child]))
  modules.forEach((module, moduleIndex) => {
    const items = childrenByParent.get(module.key) ?? []
    items.forEach((item, childIndex) => nodes.push({ id: item.key, position: { x: 720, y: moduleIndex * moduleGap + (childIndex - (items.length - 1) / 2) * 62 }, data: { label: `${symbolKindLabel(item.kind)} · ${compactGraphName(item.name)}` }, style: graphNodeStyle(item.kind) }))
  })
  const edges: Edge[] = modules.map((item) => ({ id: `root-${item.key}`, source: 'repository-root', target: item.key, type: 'smoothstep', style: { stroke: '#9db5ca' } }))
  analysis.relations.filter((item) => selectedKeys.has(item.source) && selectedKeys.has(item.target)).forEach((item, index) => edges.push({ id: `semantic-${index}-${item.source}-${item.target}`, source: item.source, target: item.target, type: 'smoothstep', label: relationLabel(item.relation), markerEnd: { type: MarkerType.ArrowClosed, color: relationColor(item.relation) }, style: { stroke: relationColor(item.relation), strokeWidth: item.relation === 'contains' ? 1.4 : 2 }, labelStyle: { fontSize: 10, fill: '#5f6d79' } }))
  return { nodes, edges }
}

function buildImpactGraph(result: ImpactAnalysis): { nodes: Node[]; edges: Edge[] } {
  const byDepth = new Map<number, typeof result.nodes>()
  result.nodes.forEach((node) => byDepth.set(node.depth, [...(byDepth.get(node.depth) ?? []), node]))
  const nodes: Node[] = []
  const visibleGroups = [...byDepth.entries()].sort(([a], [b]) => a - b).map(([depth, items]) => [depth, items.slice(0, 9)] as const)
  const maxRows = Math.max(1, ...visibleGroups.map(([, items]) => items.length))
  visibleGroups.forEach(([depth, items]) => items.forEach((item, index) => nodes.push({ id: item.key, position: { x: depth * 320, y: ((maxRows - items.length) * 88) / 2 + index * 88 }, data: { label: item.path ? `${compactGraphName(item.label)}\n${compactGraphPath(item.path)}` : compactGraphName(item.label) }, style: graphNodeStyle(depth === 0 ? 'seed' : item.kind) })))
  const visible = new Set(nodes.map((node) => node.id))
  const edges: Edge[] = result.edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)).map((edge, index) => ({ id: `impact-${index}`, source: edge.source, target: edge.target, type: 'smoothstep', label: relationLabel(edge.relation.replace('reverse_', '')), animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: '#2d6cdf' }, style: { stroke: '#7ba4d6', strokeWidth: 1.8 }, labelStyle: { fontSize: 9 } }))
  return { nodes, edges }
}

function graphNodeStyle(kind: string) {
  const palette = kind === 'repository' || kind === 'seed' ? ['#e8f2ff', '#2d6cdf'] : kind === 'module' ? ['#eef8f3', '#218657'] : kind === 'dependency' ? ['#fff6dc', '#b7791f'] : ['#ffffff', '#8aa9c7']
  return { width: kind === 'repository' ? 190 : 250, minHeight: 54, display: 'grid', placeContent: 'center', border: `1px solid ${palette[1]}`, borderLeft: `4px solid ${palette[1]}`, borderRadius: 7, background: palette[0], color: '#202a33', fontSize: 11, fontWeight: 700, lineHeight: 1.35, padding: '9px 12px', whiteSpace: 'pre-line' as const, overflowWrap: 'anywhere' as const, wordBreak: 'break-word' as const, textAlign: 'center' as const, boxShadow: '0 5px 14px rgba(31,48,67,.07)' }
}

function compactGraphPath(path: string) {
  const parts = path.split('/')
  const compact = parts.length > 3 ? `…/${parts.slice(-3).join('/')}` : path
  return compact.length > 46 ? `${compact.slice(0, 43)}…` : compact
}

function compactGraphName(name: string) { return name.length > 34 ? `${name.slice(0, 31)}…` : name }

function symbolKindLabel(kind: string) { return ({ module: '模块', class: '类', function: '函数', method: '方法', component: '组件', dependency: '外部依赖' } as Record<string, string>)[kind] ?? kind }
function relationLabel(relation: string) { return ({ contains: '包含', imports: '导入', calls: '调用', tests: '测试' } as Record<string, string>)[relation] ?? relation }
function relationColor(relation: string) { return ({ contains: '#99aec2', imports: '#2d6cdf', calls: '#7b61b7', tests: '#218657' } as Record<string, string>)[relation] ?? '#7e95aa' }
function severityLabel(severity: string) { return severity === 'critical' ? '高风险' : severity === 'warning' ? '待关注' : '提示' }
function riskLabel(level: string) { return level === 'high' ? '高风险' : level === 'medium' ? '中风险' : '低风险' }
function lineRange(symbol: CodeSymbol) { return symbol.line_start ? `L${symbol.line_start}${symbol.line_end && symbol.line_end !== symbol.line_start ? `-L${symbol.line_end}` : ''}` : '未记录' }
function shortRevision(revision: string) { return revision.startsWith('sync-') ? revision : revision.slice(0, 8) }
