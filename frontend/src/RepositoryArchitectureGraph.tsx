import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from '@xyflow/react'
import type { Edge, Node, NodeMouseHandler, NodeProps } from '@xyflow/react'
import {
  ArrowRight,
  Boxes,
  ChevronDown,
  ChevronRight,
  Code2,
  FileCode2,
  FileText,
  GitBranch,
  LoaderCircle,
  Maximize2,
  Minimize2,
  MousePointer2,
  Package,
  Play,
  TestTube2,
  Workflow,
  X,
} from 'lucide-react'
import { fetchFileContent } from './api'
import type { ClassifiedFile, RepositoryFileContent, RepositorySnapshot } from './api'
import type { AnalysisSection, ProjectStructureAnalysis } from './ProjectStructureDetails'

type GraphNodeCategory = 'repository' | 'source' | 'dependency' | 'quality' | 'directory' | 'framework' | 'entry' | 'test' | 'docs' | 'ci'
type GraphFocusState = 'default' | 'active' | 'related' | 'muted'

type ArchitectureNodeData = {
  label: string
  eyebrow: string
  metric: string
  detail: string
  category: GraphNodeCategory
  section?: AnalysisSection
  parentId?: string
  expandable?: boolean
  collapsed?: boolean
  focusState?: GraphFocusState
  fileOptions?: ClassifiedFile[]
}

type ArchitectureNode = Node<ArchitectureNodeData, 'architectureNode'>
type ArchitectureEdge = Edge

type Props = {
  analysis: ProjectStructureAnalysis
  repository: RepositorySnapshot
  onSelect: (section: AnalysisSection) => void
}

type PreviewState = {
  file: ClassifiedFile
  content: RepositoryFileContent | null
  loading: boolean
  error: string | null
}

const GraphActionsContext = createContext({ toggleGroup: (_id: string) => {} })
const nodeTypes = { architectureNode: ArchitectureGraphNode }

export function RepositoryArchitectureGraph({ analysis, repository, onSelect }: Props) {
  const graph = useMemo(() => buildArchitectureGraph(analysis, repository), [analysis, repository])
  const [nodes, setNodes, onNodesChange] = useNodesState<ArchitectureNode>(graph.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<ArchitectureEdge>(graph.edges)
  const [selectedNodeId, setSelectedNodeId] = useState('repository')
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set())
  const [expanded, setExpanded] = useState(false)
  const [preview, setPreview] = useState<PreviewState | null>(null)

  useEffect(() => {
    setNodes(graph.nodes)
    setEdges(graph.edges)
    setSelectedNodeId('repository')
    setCollapsedGroups(new Set())
    setPreview(null)
  }, [graph, setEdges, setNodes])

  useEffect(() => {
    if (!expanded && !preview) return

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (preview) setPreview(null)
      else setExpanded(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [expanded, preview])

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsedGroups((current) => {
      const next = new Set(current)
      if (next.has(groupId)) next.delete(groupId)
      else next.add(groupId)
      return next
    })
    const selected = nodes.find((node) => node.id === selectedNodeId)
    if (selected?.data.parentId === groupId) setSelectedNodeId(groupId)
  }, [nodes, selectedNodeId])

  const focus = useMemo(
    () => buildFocusState(nodes, edges, selectedNodeId),
    [edges, nodes, selectedNodeId],
  )

  const displayNodes = useMemo(() => nodes.map((node) => ({
    ...node,
    hidden: node.data.parentId ? collapsedGroups.has(node.data.parentId) : false,
    data: {
      ...node.data,
      collapsed: collapsedGroups.has(node.id),
      focusState: focus.nodeStates.get(node.id) ?? 'default',
    },
  })), [collapsedGroups, focus.nodeStates, nodes])

  const displayEdges = useMemo(() => edges.map((edge) => {
    const child = nodes.find((node) => node.id === edge.target)
    const hidden = child?.data.parentId ? collapsedGroups.has(child.data.parentId) : false
    const isFocused = focus.edgeIds.has(edge.id)
    const hasFocus = selectedNodeId !== 'repository'
    return {
      ...edge,
      hidden,
      animated: isFocused,
      style: {
        stroke: isFocused ? '#2368d9' : '#9ab4ce',
        strokeWidth: isFocused ? 2.5 : 1.5,
        opacity: hasFocus && !isFocused ? 0.16 : 1,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 15,
        height: 15,
        color: isFocused ? '#2368d9' : '#86a6c7',
      },
    }
  }), [collapsedGroups, edges, focus.edgeIds, nodes, selectedNodeId])

  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? nodes[0]
  const selectedPath = useMemo(
    () => selectedNode ? buildNodePath(selectedNode.id, nodes, edges) : [],
    [edges, nodes, selectedNode],
  )
  const handleNodeClick: NodeMouseHandler<ArchitectureNode> = (_, node) => {
    setSelectedNodeId(node.id)
    if (node.data.section) onSelect(node.data.section)
  }

  const openFilePreview = useCallback(async (file: ClassifiedFile) => {
    setPreview({ file, content: null, loading: true, error: null })
    try {
      const content = await fetchFileContent(repository.identity.owner, repository.identity.name, file.path)
      setPreview({ file, content, loading: false, error: null })
    } catch (error) {
      setPreview({
        file,
        content: null,
        loading: false,
        error: error instanceof Error ? error.message : '文件内容加载失败',
      })
    }
  }, [repository.identity.name, repository.identity.owner])

  const collapseAll = () => {
    const groupIds = nodes.filter((node) => node.data.expandable).map((node) => node.id)
    setCollapsedGroups(new Set(groupIds))
    setSelectedNodeId('repository')
  }

  return (
    <GraphActionsContext.Provider value={{ toggleGroup }}>
      <div className={`repository-graph-shell ${expanded ? 'expanded' : ''}`}>
        <div className="repository-graph-toolbar">
          <div className="graph-legend" aria-label="架构图图例">
            <span><i className="legend-repository" />仓库</span>
            <span><i className="legend-capability" />能力分组</span>
            <span><i className="legend-evidence" />解析结果</span>
          </div>
          <div className="graph-toolbar-actions">
            <span><MousePointer2 size={13} />点击卡片进入对应分析</span>
            <button type="button" onClick={collapsedGroups.size > 0 ? () => setCollapsedGroups(new Set()) : collapseAll}>
              {collapsedGroups.size > 0 ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
              {collapsedGroups.size > 0 ? '全部展开' : '收起分组'}
            </button>
            <button type="button" onClick={() => setExpanded((current) => !current)}>
              {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
              {expanded ? '退出全屏' : '全屏查看'}
            </button>
          </div>
        </div>

        <div className="repository-graph-layout">
          <div className="repository-flow-canvas" aria-label={`${repository.identity.name} 项目架构关系图`}>
            <ReactFlow<ArchitectureNode, ArchitectureEdge>
              nodes={displayNodes}
              edges={displayEdges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={handleNodeClick}
              fitView
              fitViewOptions={{ padding: 0.14, minZoom: 0.5 }}
              minZoom={0.4}
              maxZoom={1.8}
              nodesConnectable={false}
              deleteKeyCode={null}
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#cbdbea" />
              <MiniMap
                pannable
                zoomable
                nodeColor={(node) => graphNodeColor((node.data as ArchitectureNodeData).category)}
                nodeStrokeWidth={2}
                maskColor="rgba(235, 241, 247, 0.72)"
              />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>

          {selectedNode && (
            <aside className="graph-inspector" aria-live="polite">
              <div className={`graph-inspector-icon ${selectedNode.data.category}`}>
                <GraphIcon category={selectedNode.data.category} />
              </div>
              <div className="graph-inspector-path" aria-label="节点路径">
                {selectedPath.map((label, index) => (
                  <span key={`${label}-${index}`}>{label}</span>
                ))}
              </div>
              <p>{selectedNode.data.eyebrow}</p>
              <h4>{selectedNode.data.label}</h4>
              <strong>{selectedNode.data.metric}</strong>
              <span>{selectedNode.data.detail}</span>

              {selectedNode.data.fileOptions && selectedNode.data.fileOptions.length > 0 && (
                <div className="graph-related-files">
                  <div><Code2 size={14} /><strong>关联文件</strong></div>
                  {selectedNode.data.fileOptions.slice(0, 4).map((file) => (
                    <button type="button" key={file.path} onClick={() => void openFilePreview(file)} title={file.path}>
                      <FileCode2 size={14} />
                      <span>{file.path}</span>
                      <ArrowRight size={13} />
                    </button>
                  ))}
                </div>
              )}

              {selectedNode.data.section && (
                <button className="graph-inspector-action" type="button" onClick={() => onSelect(selectedNode.data.section!)}>
                  查看对应分析
                  <ArrowRight size={15} />
                </button>
              )}
            </aside>
          )}
        </div>
      </div>

      {preview && (
        <div className="graph-code-overlay" role="presentation" onMouseDown={() => setPreview(null)}>
          <section className="graph-code-viewer" role="dialog" aria-modal="true" aria-label={`${preview.file.path} 源码预览`} onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div>
                <span>关联源码预览</span>
                <strong>{preview.file.path}</strong>
              </div>
              <button type="button" onClick={() => setPreview(null)} aria-label="关闭源码预览"><X size={18} /></button>
            </header>
            <div className="graph-code-body">
              {preview.loading && <div className="graph-code-status"><LoaderCircle className="spin" size={22} />正在读取数据库中的文件内容…</div>}
              {preview.error && <div className="graph-code-status error">{preview.error}</div>}
              {preview.content && <pre><code>{preview.content.content}</code></pre>}
            </div>
            {preview.content && (
              <footer>
                <span>{formatFileCategory(preview.content.category)}</span>
                <span>{preview.content.truncated ? '内容已截断' : '完整内容'}</span>
              </footer>
            )}
          </section>
        </div>
      )}
    </GraphActionsContext.Provider>
  )
}

function ArchitectureGraphNode({ id, data }: NodeProps<ArchitectureNode>) {
  const { toggleGroup } = useContext(GraphActionsContext)
  return (
    <div className={`architecture-flow-node ${data.category} is-${data.focusState ?? 'default'}`}>
      <Handle className="architecture-handle" type="target" position={Position.Left} />
      <span className="architecture-node-icon"><GraphIcon category={data.category} /></span>
      <span className="architecture-node-copy">
        <small>{data.eyebrow}</small>
        <strong>{data.label}</strong>
        <em>{data.metric}</em>
      </span>
      {data.expandable && (
        <button
          className="architecture-node-toggle nodrag"
          type="button"
          title={data.collapsed ? `展开${data.label}` : `收起${data.label}`}
          aria-label={data.collapsed ? `展开${data.label}` : `收起${data.label}`}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation()
            toggleGroup(id)
          }}
        >
          {data.collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        </button>
      )}
      <Handle className="architecture-handle" type="source" position={Position.Right} />
    </div>
  )
}

function GraphIcon({ category }: { category: GraphNodeCategory }) {
  const icons: Record<GraphNodeCategory, typeof GitBranch> = {
    repository: GitBranch,
    source: FileCode2,
    dependency: Package,
    quality: Workflow,
    directory: Boxes,
    framework: Package,
    entry: Play,
    test: TestTube2,
    docs: FileText,
    ci: Workflow,
  }
  const Icon = icons[category]
  return <Icon size={18} aria-hidden="true" />
}

function buildArchitectureGraph(analysis: ProjectStructureAnalysis, repository: RepositorySnapshot) {
  const nodes: ArchitectureNode[] = []
  const edges: ArchitectureEdge[] = []
  const indexedFiles: ClassifiedFile[] = (repository.source_contents ?? []).map((file) => ({
    path: file.path,
    category: file.category,
    size: file.size,
  }))
  const indexedPaths = new Set(indexedFiles.map((file) => file.path))
  const onlyIndexed = (files: ClassifiedFile[]) => files.filter((file) => indexedPaths.has(file.path))

  const addNode = (id: string, position: { x: number; y: number }, data: ArchitectureNodeData) => {
    nodes.push({ id, position, data, type: 'architectureNode' })
  }
  const addEdge = (source: string, target: string) => {
    edges.push({ id: `${source}-${target}`, source, target, type: 'smoothstep' })
  }

  addNode('repository', { x: 0, y: 350 }, {
    label: repository.identity.name,
    eyebrow: '仓库根节点',
    metric: `${analysis.analyzedFileCount} 个文件样本`,
    detail: `${analysis.projectType}。默认分支为 ${repository.identity.default_branch}，当前视图由同步结果自动生成。`,
    category: 'repository',
    section: 'architecture',
  })

  const groups: Array<{ id: string; y: number; data: ArchitectureNodeData }> = [
    {
      id: 'source',
      y: 100,
      data: {
        label: '源码与入口',
        eyebrow: '能力分组',
        metric: `${analysis.sourceCount} 个源码文件`,
        detail: '聚合主要源码目录和程序入口候选，用于理解系统的模块边界与启动路径。',
        category: 'source',
        section: 'directories',
        expandable: true,
      },
    },
    {
      id: 'dependency',
      y: 350,
      data: {
        label: '依赖与运行',
        eyebrow: '能力分组',
        metric: `${analysis.dependencyPackages.length} 个依赖`,
        detail: `从 ${analysis.dependencyFiles.length} 份依赖清单中提取框架、运行库和开发工具。`,
        category: 'dependency',
        section: 'dependencies',
        expandable: true,
        fileOptions: onlyIndexed(analysis.dependencyFiles),
      },
    },
    {
      id: 'quality',
      y: 600,
      data: {
        label: '工程质量',
        eyebrow: '能力分组',
        metric: `${analysis.testFiles.length + analysis.docFiles.length + analysis.ciFiles.length} 个支撑文件`,
        detail: '汇总测试、文档和 CI/CD 文件，展示项目的质量保障能力。',
        category: 'quality',
        section: 'quality',
        expandable: true,
      },
    },
  ]

  groups.forEach((group) => {
    addNode(group.id, { x: 290, y: group.y }, group.data)
    addEdge('repository', group.id)
  })

  const sourceDirectories = analysis.topDirectories
    .filter((directory) => directory.sourceCount > 0)
    .slice(0, 2)
  sourceDirectories.forEach((directory, index) => {
    const id = `directory-${index}`
    const directoryFiles = indexedFiles
      .filter((file) => file.category === 'source_code' && file.path.startsWith(`${directory.name}/`))
      .slice(0, 4)
    addNode(id, { x: 600, y: 20 + index * 105 }, {
      label: `${directory.name}/`,
      eyebrow: '源码目录',
      metric: `${directory.count} 个文件`,
      detail: `其中包含 ${directory.sourceCount} 个源码文件，主要类别为 ${localizeCategory(directory.mainCategory)}。`,
      category: 'directory',
      section: 'directories',
      parentId: 'source',
      fileOptions: directoryFiles,
    })
    addEdge('source', id)
  })

  if (analysis.entryFiles.length > 0) {
    addNode('entry', { x: 600, y: 230 }, {
      label: '入口文件候选',
      eyebrow: '启动路径',
      metric: `${analysis.entryFiles.length} 个候选`,
      detail: analysis.entryFiles.slice(0, 2).map((file) => file.path).join('；'),
      category: 'entry',
      section: 'entrypoints',
      parentId: 'source',
      fileOptions: onlyIndexed(analysis.entryFiles),
    })
    addEdge('source', 'entry')
  }

  const dependencyNames = analysis.detectedFrameworks.length > 0
    ? analysis.detectedFrameworks
    : [...new Set(analysis.dependencyPackages.map((dependency) => dependency.name))]
  dependencyNames.slice(0, 2).forEach((name, index) => {
    const id = `framework-${index}`
    addNode(id, { x: 600, y: 335 + index * 105 }, {
      label: name,
      eyebrow: analysis.detectedFrameworks.includes(name) ? '已识别框架' : '运行依赖',
      metric: analysis.detectedFrameworks.includes(name) ? '技术栈证据' : '依赖包',
      detail: '由后端解析仓库中的真实依赖声明后识别。',
      category: 'framework',
      section: 'dependencies',
      parentId: 'dependency',
      fileOptions: onlyIndexed(analysis.dependencyFiles),
    })
    addEdge('dependency', id)
  })

  const qualityNodes: Array<{ id: string; label: string; metric: string; detail: string; category: GraphNodeCategory; files: ClassifiedFile[] }> = [
    { id: 'tests', label: '自动化测试', metric: `${analysis.testFiles.length} 个文件`, detail: '单元测试、集成测试与测试数据。', category: 'test', files: onlyIndexed(analysis.testFiles) },
    { id: 'docs', label: '项目文档', metric: `${analysis.docFiles.length} 个文件`, detail: 'README、设计说明和使用文档。', category: 'docs', files: onlyIndexed(analysis.docFiles) },
    { id: 'ci', label: 'CI/CD', metric: `${analysis.ciFiles.length} 个文件`, detail: '持续集成、自动检查和发布配置。', category: 'ci', files: onlyIndexed(analysis.ciFiles) },
  ]
  qualityNodes.forEach((item, index) => {
    addNode(item.id, { x: 600, y: 545 + index * 105 }, {
      label: item.label,
      metric: item.metric,
      detail: item.detail,
      category: item.category,
      eyebrow: '工程证据',
      section: 'quality',
      parentId: 'quality',
      fileOptions: item.files,
    })
    addEdge('quality', item.id)
  })

  return { nodes, edges }
}

function buildFocusState(nodes: ArchitectureNode[], edges: ArchitectureEdge[], selectedNodeId: string) {
  const nodeStates = new Map<string, GraphFocusState>()
  const edgeIds = new Set<string>()
  if (selectedNodeId === 'repository') {
    nodes.forEach((node) => nodeStates.set(node.id, 'default'))
    return { nodeStates, edgeIds }
  }

  const related = new Set([selectedNodeId])
  let currentId = selectedNodeId
  while (currentId !== 'repository') {
    const parentEdge = edges.find((edge) => edge.target === currentId)
    if (!parentEdge) break
    related.add(parentEdge.source)
    edgeIds.add(parentEdge.id)
    currentId = parentEdge.source
  }

  const selected = nodes.find((node) => node.id === selectedNodeId)
  if (selected?.data.expandable) {
    edges.filter((edge) => edge.source === selectedNodeId).forEach((edge) => {
      related.add(edge.target)
      edgeIds.add(edge.id)
    })
  }

  nodes.forEach((node) => {
    if (node.id === selectedNodeId) nodeStates.set(node.id, 'active')
    else if (related.has(node.id)) nodeStates.set(node.id, 'related')
    else nodeStates.set(node.id, 'muted')
  })
  return { nodeStates, edgeIds }
}

function buildNodePath(nodeId: string, nodes: ArchitectureNode[], edges: ArchitectureEdge[]) {
  const labels: string[] = []
  let currentId: string | undefined = nodeId
  while (currentId) {
    const node = nodes.find((item) => item.id === currentId)
    if (node) labels.unshift(node.data.label)
    currentId = edges.find((edge) => edge.target === currentId)?.source
  }
  return labels
}

function localizeCategory(category: string) {
  const labels: Record<string, string> = {
    source_code: '源码',
    tests: '测试',
    documentation: '文档',
    configuration: '配置',
    ci_cd: 'CI/CD',
    dependency: '依赖配置',
  }
  return labels[category] ?? category.replaceAll('_', ' ')
}

function formatFileCategory(category: string) {
  return localizeCategory(category)
}

function graphNodeColor(category: GraphNodeCategory) {
  if (category === 'repository') return '#2368d9'
  if (['source', 'dependency', 'quality'].includes(category)) return '#14845a'
  return '#8ba9c7'
}
