import { useEffect, useMemo, useState } from 'react'
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
  FileCode2,
  FileText,
  GitBranch,
  Maximize2,
  Minimize2,
  MousePointer2,
  Package,
  Play,
  TestTube2,
  Workflow,
} from 'lucide-react'
import type { RepositorySnapshot } from './api'
import type { AnalysisSection, ProjectStructureAnalysis } from './ProjectStructureDetails'

type GraphNodeCategory = 'repository' | 'source' | 'dependency' | 'quality' | 'directory' | 'framework' | 'entry' | 'test' | 'docs' | 'ci'

type ArchitectureNodeData = {
  label: string
  eyebrow: string
  metric: string
  detail: string
  category: GraphNodeCategory
  section?: AnalysisSection
}

type ArchitectureNode = Node<ArchitectureNodeData, 'architectureNode'>
type ArchitectureEdge = Edge

type Props = {
  analysis: ProjectStructureAnalysis
  repository: RepositorySnapshot
  onSelect: (section: AnalysisSection) => void
}

const nodeTypes = { architectureNode: ArchitectureGraphNode }

export function RepositoryArchitectureGraph({ analysis, repository, onSelect }: Props) {
  const graph = useMemo(() => buildArchitectureGraph(analysis, repository), [analysis, repository])
  const [nodes, setNodes, onNodesChange] = useNodesState<ArchitectureNode>(graph.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<ArchitectureEdge>(graph.edges)
  const [selectedNodeId, setSelectedNodeId] = useState('repository')
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    setNodes(graph.nodes)
    setEdges(graph.edges)
    setSelectedNodeId('repository')
  }, [graph, setEdges, setNodes])

  useEffect(() => {
    if (!expanded) return

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [expanded])

  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? nodes[0]
  const handleNodeClick: NodeMouseHandler<ArchitectureNode> = (_, node) => setSelectedNodeId(node.id)

  return (
    <div className={`repository-graph-shell ${expanded ? 'expanded' : ''}`}>
      <div className="repository-graph-toolbar">
        <div className="graph-legend" aria-label="架构图图例">
          <span><i className="legend-repository" />仓库</span>
          <span><i className="legend-capability" />能力分组</span>
          <span><i className="legend-evidence" />解析结果</span>
        </div>
        <div className="graph-toolbar-actions">
          <span><MousePointer2 size={13} />拖动节点，滚轮缩放</span>
          <button type="button" onClick={() => setExpanded((current) => !current)}>
            {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            {expanded ? '退出全屏' : '全屏查看'}
          </button>
        </div>
      </div>

      <div className="repository-graph-layout">
        <div className="repository-flow-canvas" aria-label={`${repository.identity.name} 项目架构关系图`}>
          <ReactFlow<ArchitectureNode, ArchitectureEdge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            fitView
            fitViewOptions={{ padding: 0.16 }}
            minZoom={0.35}
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
            <p>{selectedNode.data.eyebrow}</p>
            <h4>{selectedNode.data.label}</h4>
            <strong>{selectedNode.data.metric}</strong>
            <span>{selectedNode.data.detail}</span>
            {selectedNode.data.section && (
              <button type="button" onClick={() => onSelect(selectedNode.data.section!)}>
                查看对应分析
                <ArrowRight size={15} />
              </button>
            )}
          </aside>
        )}
      </div>
    </div>
  )
}

function ArchitectureGraphNode({ data, selected }: NodeProps<ArchitectureNode>) {
  return (
    <div className={`architecture-flow-node ${data.category} ${selected ? 'selected' : ''}`}>
      <Handle className="architecture-handle" type="target" position={Position.Left} />
      <span className="architecture-node-icon"><GraphIcon category={data.category} /></span>
      <span className="architecture-node-copy">
        <small>{data.eyebrow}</small>
        <strong>{data.label}</strong>
        <em>{data.metric}</em>
      </span>
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

  const addNode = (id: string, position: { x: number; y: number }, data: ArchitectureNodeData) => {
    nodes.push({ id, position, data, type: 'architectureNode' })
  }
  const addEdge = (source: string, target: string, animated = false) => {
    edges.push({
      id: `${source}-${target}`,
      source,
      target,
      animated,
      type: 'smoothstep',
      markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15, color: '#86a6c7' },
      style: { stroke: '#9ab4ce', strokeWidth: animated ? 2 : 1.5 },
    })
  }

  addNode('repository', { x: 0, y: 350 }, {
    label: repository.identity.name,
    eyebrow: 'Repository',
    metric: `${analysis.analyzedFileCount} 个文件样本`,
    detail: `${analysis.projectType}。默认分支为 ${repository.identity.default_branch}，当前视图由同步结果自动生成。`,
    category: 'repository',
  })

  const groups: Array<{ id: string; y: number; data: ArchitectureNodeData }> = [
    {
      id: 'source',
      y: 100,
      data: {
        label: '源码与入口',
        eyebrow: 'Core modules',
        metric: `${analysis.sourceCount} 个源码文件`,
        detail: '聚合主要源码目录和程序入口候选，用于理解系统的模块边界与启动路径。',
        category: 'source',
        section: 'directories',
      },
    },
    {
      id: 'dependency',
      y: 350,
      data: {
        label: '依赖与运行',
        eyebrow: 'Runtime',
        metric: `${analysis.dependencyPackages.length} 个依赖`,
        detail: `从 ${analysis.dependencyFiles.length} 份依赖清单中提取框架、运行库和开发工具。`,
        category: 'dependency',
        section: 'dependencies',
      },
    },
    {
      id: 'quality',
      y: 600,
      data: {
        label: '工程质量',
        eyebrow: 'Quality system',
        metric: `${analysis.testFiles.length + analysis.docFiles.length + analysis.ciFiles.length} 个支撑文件`,
        detail: '汇总测试、文档和 CI/CD 文件，展示项目的质量保障能力。',
        category: 'quality',
        section: 'quality',
      },
    },
  ]

  groups.forEach((group) => {
    addNode(group.id, { x: 290, y: group.y }, group.data)
    addEdge('repository', group.id, true)
  })

  const sourceDirectories = analysis.topDirectories
    .filter((directory) => directory.sourceCount > 0)
    .slice(0, 2)
  sourceDirectories.forEach((directory, index) => {
    const id = `directory-${index}`
    addNode(id, { x: 600, y: 20 + index * 105 }, {
      label: `${directory.name}/`,
      eyebrow: 'Source directory',
      metric: `${directory.count} 个文件`,
      detail: `其中包含 ${directory.sourceCount} 个源码文件，主要类别为 ${localizeCategory(directory.mainCategory)}。`,
      category: 'directory',
      section: 'directories',
    })
    addEdge('source', id)
  })

  if (analysis.entryFiles.length > 0) {
    addNode('entry', { x: 600, y: 230 }, {
      label: '入口文件候选',
      eyebrow: 'Entrypoints',
      metric: `${analysis.entryFiles.length} 个候选`,
      detail: analysis.entryFiles.slice(0, 2).map((file) => file.path).join('；'),
      category: 'entry',
      section: 'entrypoints',
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
      eyebrow: analysis.detectedFrameworks.includes(name) ? 'Detected framework' : 'Runtime dependency',
      metric: analysis.detectedFrameworks.includes(name) ? '已识别框架' : '依赖包',
      detail: `由后端解析依赖清单后识别，来源于仓库中的实际依赖声明。`,
      category: 'framework',
      section: 'dependencies',
    })
    addEdge('dependency', id)
  })

  const qualityNodes: Array<{ id: string; label: string; metric: string; detail: string; category: GraphNodeCategory }> = [
    { id: 'tests', label: '自动化测试', metric: `${analysis.testFiles.length} 个文件`, detail: '单元测试、集成测试与测试数据。', category: 'test' },
    { id: 'docs', label: '项目文档', metric: `${analysis.docFiles.length} 个文件`, detail: 'README、设计说明和使用文档。', category: 'docs' },
    { id: 'ci', label: 'CI/CD', metric: `${analysis.ciFiles.length} 个文件`, detail: '持续集成、自动检查和发布配置。', category: 'ci' },
  ]
  qualityNodes.forEach((item, index) => {
    addNode(item.id, { x: 600, y: 545 + index * 105 }, {
      ...item,
      eyebrow: 'Engineering evidence',
      section: 'quality',
    })
    addEdge('quality', item.id)
  })

  return { nodes, edges }
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

function graphNodeColor(category: GraphNodeCategory) {
  if (category === 'repository') return '#2368d9'
  if (['source', 'dependency', 'quality'].includes(category)) return '#14845a'
  return '#8ba9c7'
}
