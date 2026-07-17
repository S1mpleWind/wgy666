import { useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Boxes,
  Braces,
  CheckCircle2,
  CircleDot,
  FileCode2,
  FileJson,
  FileText,
  Folder,
  GitBranch,
  Layers3,
  Network,
  Package,
  Play,
  Settings2,
  TestTube2,
  Workflow,
} from 'lucide-react'
import type { ClassifiedFile, ProjectDependency, RepositorySnapshot } from './api'
import './ProjectStructureDetails.css'

export type AnalysisSection = 'architecture' | 'directories' | 'dependencies' | 'entrypoints' | 'quality'

export type ProjectStructureAnalysis = {
  projectType: string
  analyzedFileCount: number
  analysisWarning: string | null
  sourceCount: number
  dependencyFiles: ClassifiedFile[]
  dependencyPackages: ProjectDependency[]
  detectedFrameworks: string[]
  testFiles: ClassifiedFile[]
  docFiles: ClassifiedFile[]
  configFiles: ClassifiedFile[]
  entryFiles: ClassifiedFile[]
  ciFiles: ClassifiedFile[]
  topDirectories: Array<{
    name: string
    count: number
    mainCategory: string
    sourceCount: number
  }>
  analysisSource: 'backend' | 'local_fallback'
}

type Props = {
  activeSection: AnalysisSection
  analysis: ProjectStructureAnalysis
  repository: RepositorySnapshot
  onBack: () => void
  onSelect: (section: AnalysisSection) => void
}

const sections: Array<{ id: AnalysisSection; label: string; icon: typeof Network }> = [
  { id: 'architecture', label: '架构图', icon: Network },
  { id: 'directories', label: '主要目录', icon: Boxes },
  { id: 'dependencies', label: '依赖文件', icon: Package },
  { id: 'entrypoints', label: '入口文件', icon: Play },
  { id: 'quality', label: '测试与文档', icon: TestTube2 },
]

const sectionCopy: Record<AnalysisSection, { title: string; description: string }> = {
  architecture: {
    title: '项目架构思维导图',
    description: '把目录、模块和工程支撑能力组织成可浏览的结构视图。',
  },
  directories: {
    title: '主要目录与职责',
    description: '按照目录层级和文件类别展示仓库组成，并给出职责推断。',
  },
  dependencies: {
    title: '依赖清单与关系',
    description: '集中查看依赖声明文件、技术生态和后续可解析的依赖关系。',
  },
  entrypoints: {
    title: '入口文件与识别依据',
    description: '按照文件名、目录位置和文件类别定位可能的程序入口。',
  },
  quality: {
    title: '测试、文档与工程化',
    description: '汇总测试、文档、配置和 CI/CD 文件，形成项目质量视图。',
  },
}

export function ProjectStructureDetails({ activeSection, analysis, repository, onBack, onSelect }: Props) {
  const copy = sectionCopy[activeSection]

  return (
    <section className="structure-page">
      <header className="structure-page-header">
        <button className="structure-back" type="button" onClick={onBack}>
          <ArrowLeft size={17} aria-hidden="true" />
          返回项目概览
        </button>
        <div className="structure-title-row">
          <div>
            <p className="structure-breadcrumb">{repository.identity.full_name} / 项目解析</p>
            <h2>{copy.title}</h2>
            <p>{copy.description}</p>
          </div>
          <span className="prototype-status">
            <CircleDot size={14} aria-hidden="true" />
            {analysis.analysisSource === 'backend' ? '后端实时解析' : '本地降级结果'}
          </span>
        </div>
        <nav className="structure-tabs" aria-label="项目结构详情">
          {sections.map((section) => {
            const Icon = section.icon
            return (
              <button
                className={activeSection === section.id ? 'active' : ''}
                key={section.id}
                type="button"
                onClick={() => onSelect(section.id)}
              >
                <Icon size={16} aria-hidden="true" />
                {section.label}
              </button>
            )
          })}
        </nav>
      </header>

      <div className="prototype-note">
        {analysis.analysisSource === 'backend'
          ? '当前结果由后端基于同步目录、已索引源码和依赖清单生成。'
          : '后端项目解析暂不可用，当前展示由同步快照生成的本地降级结果。'}
      </div>

      {activeSection === 'architecture' && <ArchitectureView analysis={analysis} repository={repository} onSelect={onSelect} />}
      {activeSection === 'directories' && <DirectoryView analysis={analysis} />}
      {activeSection === 'dependencies' && <DependencyView analysis={analysis} />}
      {activeSection === 'entrypoints' && <EntryPointView analysis={analysis} />}
      {activeSection === 'quality' && <QualityView analysis={analysis} />}
    </section>
  )
}

function ArchitectureView({ analysis, repository, onSelect }: { analysis: ProjectStructureAnalysis; repository: RepositorySnapshot; onSelect: (section: AnalysisSection) => void }) {
  const directories = displayDirectories(analysis)
  const sourceDirectories = directories.filter((item) => item.sourceCount > 0).slice(0, 3)
  const supportingDirectories = directories.filter((item) => item.sourceCount === 0).slice(0, 4)
  const dependencyHighlights = analysis.detectedFrameworks.length > 0
    ? analysis.detectedFrameworks
    : displayDependencies(analysis).map((file) => file.path)

  return (
    <div className="structure-stack">
      <section className="structure-panel architecture-panel">
        <div className="structure-panel-heading">
          <div>
            <p>Repository map</p>
            <h3>{repository.identity.name} 结构视图</h3>
          </div>
          <span>{analysis.analyzedFileCount} 个文件样本</span>
        </div>

        <div className="architecture-map">
          <div className="architecture-root">
            <GitBranch size={20} aria-hidden="true" />
            <strong>{repository.identity.name}</strong>
            <span>{analysis.projectType}</span>
          </div>
          <div className="architecture-branches">
            <ArchitectureBranch
              icon={<Layers3 size={19} />}
              title="核心源码"
              subtitle={`${analysis.sourceCount} 个源码文件`}
              items={sourceDirectories.map((item) => item.name)}
              onClick={() => onSelect('directories')}
            />
            <ArchitectureBranch
              icon={<Package size={19} />}
              title="依赖与运行"
              subtitle={`${analysis.dependencyFiles.length} 份依赖声明`}
              items={dependencyHighlights.slice(0, 4)}
              onClick={() => onSelect('dependencies')}
            />
            <ArchitectureBranch
              icon={<Settings2 size={19} />}
              title="工程支撑"
              subtitle={`${analysis.testFiles.length + analysis.docFiles.length + analysis.ciFiles.length} 个相关文件`}
              items={supportingDirectories.map((item) => item.name)}
              onClick={() => onSelect('quality')}
            />
          </div>
        </div>
      </section>

      <section className="structure-panel">
        <div className="structure-panel-heading">
          <div>
            <p>Analysis pipeline</p>
            <h3>自动化解析流程</h3>
          </div>
        </div>
        <div className="pipeline-grid">
          <PipelineStep number="01" title="同步目录树" text="读取 GitHub tree、README 与语言统计" />
          <PipelineStep number="02" title="规则分类" text="识别源码、依赖、测试、文档和配置" />
          <PipelineStep number="03" title="结构建模" text="聚合目录职责、入口候选和模块关系" />
          <PipelineStep number="04" title="可视化展示" text="生成架构图、目录树和工程质量视图" last />
        </div>
      </section>
    </div>
  )
}

function ArchitectureBranch({ icon, title, subtitle, items, onClick }: { icon: React.ReactNode; title: string; subtitle: string; items: string[]; onClick: () => void }) {
  return (
    <button className="architecture-branch" type="button" onClick={onClick}>
      <span className="branch-icon">{icon}</span>
      <span className="branch-copy">
        <strong>{title}</strong>
        <small>{subtitle}</small>
      </span>
      <span className="branch-items">
        {items.length > 0
          ? items.slice(0, 4).map((item) => <span key={item}>{item}</span>)
          : <span>暂无识别结果</span>}
      </span>
      <ArrowRight size={17} aria-hidden="true" />
    </button>
  )
}

function PipelineStep({ number, title, text, last = false }: { number: string; title: string; text: string; last?: boolean }) {
  return (
    <article className="pipeline-step">
      <span>{number}</span>
      <strong>{title}</strong>
      <p>{text}</p>
      {!last && <ArrowRight className="pipeline-arrow" size={18} aria-hidden="true" />}
    </article>
  )
}

function DirectoryView({ analysis }: { analysis: ProjectStructureAnalysis }) {
  const directories = displayDirectories(analysis)
  const maxCount = Math.max(...directories.map((item) => item.count), 1)
  const [selectedDirectoryName, setSelectedDirectoryName] = useState<string | null>(directories[0]?.name ?? null)
  const selectedDirectory = directories.find((directory) => directory.name === selectedDirectoryName) ?? directories[0] ?? null

  return (
    <div className="structure-split directory-view-layout">
      <section className="structure-panel directory-tree-panel">
        <div className="structure-panel-heading">
          <div><p>Directory mind map</p><h3>目录结构思维导图</h3></div>
          <span>{directories.length} 个主要目录</span>
        </div>
        <div className="directory-mindmap">
          <div className="directory-map-root">
            <span className="directory-root-icon"><GitBranch size={21} aria-hidden="true" /></span>
            <strong>repository/</strong>
            <span>{analysis.analyzedFileCount} 个文件样本</span>
            <small>{analysis.sourceCount} 个源码文件</small>
          </div>
          <div className="directory-map-branches" role="group" aria-label="主要目录节点">
            {directories.length === 0 && (
              <div className="directory-map-empty">
                <Folder size={19} aria-hidden="true" />
                <span>暂未识别到主要目录</span>
              </div>
            )}
            {directories.map((directory) => {
              const isSelected = selectedDirectory?.name === directory.name
              return (
                <button
                  aria-pressed={isSelected}
                  className={`directory-map-node${isSelected ? ' selected' : ''}`}
                  data-category={directory.mainCategory}
                  key={directory.name}
                  type="button"
                  onClick={() => setSelectedDirectoryName(directory.name)}
                >
                  <span className="directory-node-icon"><Folder size={18} aria-hidden="true" /></span>
                  <span className="directory-node-copy">
                    <strong title={directoryDisplayName(directory.name)}>{directoryDisplayName(directory.name)}</strong>
                    <small>{directoryDescription(directory.name, directory.mainCategory)}</small>
                  </span>
                  <span className="directory-node-meta">
                    <span>{directory.count} 个文件</span>
                    <span>{categoryLabel(directory.mainCategory)}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      </section>

      <section className="structure-panel">
        <div className="structure-panel-heading">
          <div><p>Responsibility inference</p><h3>目录职责推断</h3></div>
          {selectedDirectory && <span>当前：{directoryDisplayName(selectedDirectory.name)}</span>}
        </div>
        <div className="responsibility-list">
          {directories.length === 0 && <p className="muted">暂无可推断的目录职责</p>}
          {directories.map((directory) => (
            <article className={selectedDirectory?.name === directory.name ? 'selected' : ''} key={directory.name}>
              <div>
                <strong>{directoryDisplayName(directory.name)}</strong>
                <span>{directoryDescription(directory.name, directory.mainCategory)}</span>
              </div>
              <div className="responsibility-bar"><span style={{ width: `${Math.max((directory.count / maxCount) * 100, 8)}%` }} /></div>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}

function DependencyView({ analysis }: { analysis: ProjectStructureAnalysis }) {
  const dependencies = displayDependencies(analysis)
  const packageGroups = dependencyGroups(analysis.dependencyPackages)

  return (
    <div className="structure-stack">
      <section className="structure-panel">
        <div className="structure-panel-heading">
          <div><p>Dependency manifests</p><h3>依赖声明文件</h3></div>
          <span>{dependencies.length} 个已展示文件</span>
        </div>
        <div className="dependency-table">
          <div className="dependency-table-head"><span>文件</span><span>生态</span><span>用途</span><span>状态</span></div>
          {dependencies.map((file) => {
            const ecosystem = dependencyEcosystem(file.path)
            const packageCount = analysis.dependencyPackages.filter((item) => item.source_file === file.path).length
            const status = packageCount > 0
              ? `${packageCount} 项`
              : isLockFile(file.path) ? '版本锁定文件' : '未解析到条目'
            return (
              <div className="dependency-table-row" key={file.path}>
                <span><FileJson size={17} aria-hidden="true" /><strong>{file.path}</strong></span>
                <span>{ecosystem}</span>
                <span>{dependencyPurpose(file.path)}</span>
                <span className="dependency-status"><CheckCircle2 size={15} /> {status}</span>
              </div>
            )
          })}
          {dependencies.length === 0 && <p className="muted">暂未识别到依赖声明文件</p>}
        </div>
      </section>

      <section className="structure-panel dependency-map-panel">
        <div className="structure-panel-heading">
          <div><p>Dependency relationship view</p><h3>依赖分组</h3></div>
          <span>{analysis.dependencyPackages.length} 项已解析依赖</span>
        </div>
        <div className="dependency-map">
          <div className="dependency-source">
            <span className="dependency-source-icon"><FileJson size={20} aria-hidden="true" /></span>
            <strong>依赖清单</strong>
            <small>{dependencies.length} 个声明文件 · {analysis.dependencyPackages.length} 项依赖</small>
            <div className="dependency-source-files">
              {dependencies.length > 0
                ? dependencies.slice(0, 3).map((file) => <span key={file.path} title={file.path}>{file.path}</span>)
                : <span>暂未识别依赖声明</span>}
            </div>
          </div>
          <div className="dependency-groups">
            {packageGroups.map((group) => <DependencyGroup key={group.kind} kind={group.kind} title={group.title} items={group.items} />)}
            {packageGroups.length === 0 && (
              <div className="dependency-group-empty">
                <Package size={20} aria-hidden="true" />
                <div><strong>暂无依赖分组</strong><span>依赖声明存在时将在这里展示解析结果</span></div>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}

function DependencyGroup({ kind, title, items }: { kind: string; title: string; items: string[] }) {
  const Icon = kind === 'runtime_framework'
    ? Layers3
    : kind === 'data_interface'
      ? Braces
      : kind === 'development'
        ? Settings2
        : Package

  return (
    <article className="dependency-group-card" data-kind={kind}>
      <div className="dependency-group-heading">
        <span className="dependency-group-icon"><Icon size={18} aria-hidden="true" /></span>
        <div><strong>{title}</strong><small>{items.length} 项已识别</small></div>
      </div>
      <div className="dependency-package-list">
        {items.map((item) => <span key={item} title={item}><CircleDot size={10} aria-hidden="true" />{item}</span>)}
      </div>
    </article>
  )
}

function EntryPointView({ analysis }: { analysis: ProjectStructureAnalysis }) {
  const entrypoints = displayEntrypoints(analysis)

  return (
    <div className="structure-stack">
      <section className="structure-panel">
        <div className="structure-panel-heading">
          <div><p>Entry analysis</p><h3>入口识别链路</h3></div>
        </div>
        <div className="startup-flow">
          <FlowNode icon={<Play size={18} />} eyebrow="解析规则" title="文件名 + 目录位置 + 文件类别" />
          <FlowNode icon={<FileCode2 size={18} />} eyebrow="首选入口" title={entrypoints[0]?.path ?? '暂未识别'} />
          <FlowNode icon={<Workflow size={18} />} eyebrow="入口类型" title={entryType(entrypoints[0]?.path)} />
          <FlowNode icon={<Braces size={18} />} eyebrow="所属模块" title={entryModule(entrypoints[0]?.path)} />
        </div>
      </section>

      <section className="structure-panel">
        <div className="structure-panel-heading">
          <div><p>Entry candidates</p><h3>入口文件候选</h3></div>
          <span>{entrypoints.length} 个候选</span>
        </div>
        <div className="entrypoint-grid">
          {entrypoints.length === 0 && <p className="muted">暂未识别到符合规则的入口文件</p>}
          {entrypoints.map((file, index) => (
            <article key={file.path}>
              <span className="entry-rank">0{index + 1}</span>
              <FileCode2 size={20} aria-hidden="true" />
              <div><strong>{file.path}</strong><p>{entryReason(file.path)}</p></div>
              <span className="confidence-chip">规则优先级 {index + 1}</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}

function FlowNode({ icon, eyebrow, title }: { icon: React.ReactNode; eyebrow: string; title: string }) {
  return <article><span className="flow-icon">{icon}</span><small>{eyebrow}</small><strong>{title}</strong><ArrowRight size={18} aria-hidden="true" /></article>
}

function QualityView({ analysis }: { analysis: ProjectStructureAnalysis }) {
  const samples = [
    ...analysis.testFiles.slice(0, 3),
    ...analysis.docFiles.slice(0, 3),
    ...analysis.ciFiles.slice(0, 3),
    ...analysis.configFiles.slice(0, 3),
  ]

  return (
    <div className="structure-stack">
      <section className="quality-metrics">
        <QualityMetric icon={<TestTube2 size={20} />} label="测试文件" value={analysis.testFiles.length} note="单元测试与集成测试" />
        <QualityMetric icon={<FileText size={20} />} label="文档文件" value={analysis.docFiles.length} note="README 与项目文档" />
        <QualityMetric icon={<Settings2 size={20} />} label="配置文件" value={analysis.configFiles.length} note="运行和构建配置" />
        <QualityMetric icon={<GitBranch size={20} />} label="CI/CD" value={analysis.ciFiles.length} note="自动检查与发布" />
      </section>

      <div className="structure-split quality-detail-layout">
        <section className="structure-panel">
          <div className="structure-panel-heading"><div><p>Engineering files</p><h3>工程文件样本</h3></div></div>
          <div className="engineering-files">
            {samples.length === 0 && <p className="muted">暂无工程文件样本</p>}
            {samples.map((file) => (
              <div key={file.path}><FileText size={16} /><strong>{file.path}</strong><span>{categoryLabel(file.category)}</span></div>
            ))}
          </div>
        </section>
        <section className="structure-panel">
          <div className="structure-panel-heading"><div><p>Quality loop</p><h3>质量保障链路</h3></div></div>
          <div className="quality-loop">
            <span>代码提交</span><ArrowRight size={16} /><span>CI 检查</span><ArrowRight size={16} /><span>自动测试</span><ArrowRight size={16} /><span>文档构建</span>
          </div>
          <div className="quality-todos">
            <p><CheckCircle2 size={16} /> 已接通后端文件分类、依赖清单与入口规则解析</p>
            <p><CircleDot size={16} /> 下一步解析测试命令、覆盖率和工作流依赖</p>
            <p><CircleDot size={16} /> 后续关联失败测试与具体源码模块</p>
          </div>
        </section>
      </div>
    </div>
  )
}

function QualityMetric({ icon, label, value, note }: { icon: React.ReactNode; label: string; value: number; note: string }) {
  return <article><span>{icon}</span><div><small>{label}</small><strong>{value}</strong><p>{note}</p></div></article>
}

function displayDirectories(analysis: ProjectStructureAnalysis) {
  return analysis.topDirectories
}

function displayDependencies(analysis: ProjectStructureAnalysis): ClassifiedFile[] {
  return analysis.dependencyFiles.slice(0, 10)
}

function displayEntrypoints(analysis: ProjectStructureAnalysis): ClassifiedFile[] {
  return analysis.entryFiles.slice(0, 6)
}

function dependencyGroups(packages: ProjectDependency[]) {
  const labels: Record<string, string> = {
    runtime_framework: '运行框架',
    data_interface: '数据与接口',
    development: '开发工具',
    runtime: '其他运行依赖',
  }
  const grouped = new Map<string, string[]>()
  for (const dependency of packages) {
    const items = grouped.get(dependency.group) ?? []
    if (!items.includes(dependency.name)) items.push(dependency.name)
    grouped.set(dependency.group, items)
  }
  return ['runtime_framework', 'data_interface', 'development', 'runtime']
    .filter((group) => grouped.has(group))
    .map((group) => ({ kind: group, title: labels[group], items: (grouped.get(group) ?? []).slice(0, 8) }))
}

function categoryLabel(category: string) {
  const labels: Record<string, string> = {
    source_code: '源码模块', tests: '测试', documentation: '文档', configuration: '配置',
    ci_cd: 'CI/CD', dependency: '依赖配置', build: '构建', assets: '静态资源', data: '数据', other: '其他',
  }
  return labels[category] ?? category
}

function directoryDescription(name: string, category: string) {
  const normalized = name.toLowerCase()
  if (normalized.includes('prototype')) return '界面原型与演示实现'
  if (normalized.includes('front')) return '前端页面、交互组件与样式资源'
  if (normalized.includes('back') || normalized === 'app' || normalized === 'src') return '核心业务代码与应用模块'
  if (normalized.includes('test')) return '自动化测试与测试数据'
  if (normalized.includes('doc')) return '项目说明、设计和使用文档'
  if (normalized === '.github') return '工作流、Issue 模板与仓库配置'
  if (normalized === '(root)') return '项目级配置和启动文件'
  return `${categoryLabel(category)}相关文件`
}

function directoryDisplayName(name: string) {
  return name === '(root)' ? '根目录文件' : `${name}/`
}

function dependencyEcosystem(path: string) {
  const name = path.toLowerCase()
  if (name.includes('package')) return 'Node.js'
  if (name.includes('pyproject') || name.includes('requirements') || name.includes('uv.lock')) return 'Python'
  if (name.includes('cargo')) return 'Rust'
  if (name.includes('go.mod')) return 'Go'
  return '通用'
}

function dependencyPurpose(path: string) {
  const name = path.toLowerCase()
  if (name.includes('lock')) return '锁定可复现版本'
  if (name.includes('pyproject') || name.includes('package.json')) return '声明项目与依赖'
  if (name.includes('requirements')) return 'Python 依赖清单'
  return '构建或运行依赖'
}

function isLockFile(path: string) {
  const name = path.toLowerCase()
  return name.includes('lock') || name.endsWith('yarn.lock')
}

function entryReason(path: string) {
  const name = path.toLowerCase()
  if (name.endsWith('main.py')) return '包含后端应用创建与服务启动入口'
  if (name.endsWith('main.tsx') || name.endsWith('index.tsx')) return '负责挂载前端根组件'
  if (name.includes('router')) return '集中注册 API 路由和模块入口'
  if (name.endsWith('app.tsx')) return '前端页面结构和交互入口'
  return '文件名和目录位置符合入口规则'
}

function entryType(path?: string) {
  if (!path) return '暂未识别'
  const name = path.toLowerCase()
  if (name.endsWith('.py')) return 'Python 应用入口'
  if (name.endsWith('.tsx') || name.endsWith('.ts')) return 'Web 前端入口'
  if (name.endsWith('.js')) return 'Node.js 或 Web 入口'
  if (name.endsWith('.cs')) return '.NET 应用入口'
  return '通用应用入口'
}

function entryModule(path?: string) {
  if (!path) return '暂未识别'
  return path.split('/')[0] || '(root)'
}
