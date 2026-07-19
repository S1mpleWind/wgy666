/**
 * Project analysis logic — sync-time fallback analysis and backend response mapping.
 */
import type { RepositorySnapshot, ProjectStructureResponse } from '../api'
import type { ProjectStructureAnalysis } from '../ProjectStructureDetails'

const WEB_LANGUAGES = new Set(['typescript', 'javascript', 'tsx', 'vue', 'css', 'html'])
const SIGNIFICANT_LANGUAGE_SHARE = 0.1

function getPrimaryLanguage(snapshot: RepositorySnapshot) {
  if (snapshot.stats.primary_language) return snapshot.stats.primary_language
  return Object.entries(snapshot.stats.languages).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
}

function isEntryCandidate(path: string) {
  const normalized = path.toLowerCase()
  const segments = normalized.split('/')
  const fileName = segments.at(-1)
  const excludedDirectories = new Set([
    'doc', 'docs', 'test', 'tests', 'example', 'examples',
    'fixture', 'fixtures', 'sample', 'samples', '.github',
  ])
  if (segments.slice(0, -1).some((segment) => excludedDirectories.has(segment))) return false
  return Boolean(
    fileName &&
    [
      'main.py', 'app.py', 'server.py', 'manage.py',
      'index.js', 'index.ts', 'main.ts', 'main.tsx', 'app.tsx',
      'program.cs',
    ].includes(fileName),
  )
}

function inferProjectType(snapshot: RepositorySnapshot) {
  const languageEntries = Object.entries(snapshot.stats.languages)
  const totalBytes = languageEntries.reduce((total, [, bytes]) => total + Math.max(bytes, 0), 0)
  const languageShare = (names: Set<string>) =>
    totalBytes === 0
      ? 0
      : languageEntries.reduce(
          (total, [language, bytes]) => total + (names.has(language.toLowerCase()) ? Math.max(bytes, 0) : 0),
          0,
        ) / totalBytes

  const primaryLanguage = snapshot.stats.primary_language?.toLowerCase()
  const hasPython = primaryLanguage === 'python' || languageShare(new Set(['python'])) >= SIGNIFICANT_LANGUAGE_SHARE
  const hasFrontend = languageShare(WEB_LANGUAGES) >= SIGNIFICANT_LANGUAGE_SHARE

  if (hasPython && hasFrontend) return '全栈项目：Python 后端 + Web 前端'
  if (hasPython) return 'Python 后端或工具库项目'
  if (hasFrontend) return 'Web 前端或 Node.js 项目'
  if (languageEntries.length > 0) return `${getPrimaryLanguage(snapshot)} 为主的项目`
  return '暂未识别主要技术栈'
}

/** Local fallback analysis — runs synchronously from snapshot data. */
export function analyzeProject(snapshot: RepositorySnapshot): ProjectStructureAnalysis {
  const files = snapshot.files
  const categoryMap = new Map(snapshot.file_categories.map((item) => [item.category, item.count]))
  const directoryCounter = new Map<string, { count: number; sourceCount: number; categories: Map<string, number> }>()

  for (const file of files) {
    const directory = file.path.includes('/') ? file.path.split('/')[0] : '(root)'
    const current = directoryCounter.get(directory) ?? { count: 0, sourceCount: 0, categories: new Map<string, number>() }
    current.count += 1
    if (file.category === 'source_code') current.sourceCount += 1
    current.categories.set(file.category, (current.categories.get(file.category) ?? 0) + 1)
    directoryCounter.set(directory, current)
  }

  const topDirectories = Array.from(directoryCounter.entries())
    .map(([name, value]) => {
      const mainCategory = Array.from(value.categories.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'other'
      return { name, count: value.count, mainCategory, sourceCount: value.sourceCount }
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)

  const dependencyFiles = files.filter((file) => file.category === 'dependency')
  const testFiles = files.filter((file) => file.category === 'tests')
  const docFiles = files.filter((file) => file.category === 'documentation')
  const configFiles = files.filter((file) => file.category === 'configuration')
  const ciFiles = files.filter((file) => file.category === 'ci_cd')
  const sourceCount = categoryMap.get('source_code') ?? 0
  const entryFiles = files.filter((file) => file.category === 'source_code' && isEntryCandidate(file.path))
  const primaryLanguage = getPrimaryLanguage(snapshot)
  const analysisWarning =
    sourceCount === 0 && primaryLanguage
      ? `GitHub 语言统计显示主要语言为 ${primaryLanguage}，但当前文件样本未覆盖源码目录，建议扩大同步范围后再确认。`
      : null

  return {
    projectType: inferProjectType(snapshot),
    analyzedFileCount: files.length,
    analysisWarning,
    sourceCount,
    dependencyFiles,
    dependencyPackages: [],
    detectedFrameworks: [],
    testFiles,
    docFiles,
    configFiles,
    entryFiles,
    ciFiles,
    topDirectories,
    analysisSource: 'local_fallback' as const,
  }
}

// -- Backend response mapping helpers ---------------------------------------

function localizeProjectType(projectType: string) {
  const labels: Record<string, string> = {
    'Full-stack project: Python backend plus web frontend': '全栈项目：Python 后端 + Web 前端',
    'Python backend or tooling project': 'Python 后端或工具库项目',
    'Web frontend or Node.js project': 'Web 前端或 Node.js 项目',
    'Unknown primary stack': '暂未识别主要技术栈',
  }
  return labels[projectType] ?? projectType.replace('-first project', ' 为主的项目')
}

function localizeAnalysisWarning(warning: string) {
  if (warning.startsWith('GitHub reports ')) {
    const language = warning.match(/^GitHub reports (.+?) as/)?.[1] ?? '某种语言'
    return `GitHub 语言统计显示主要语言为 ${language}，但后端没有取得可分析的源码文件。`
  }
  if (warning.startsWith('Dependency manifests were found')) {
    return '已发现依赖清单，但未能解析出具体依赖条目。'
  }
  return warning
}

/** Map backend API response to the local ProjectStructureAnalysis shape. */
export function mapProjectAnalysis(response: ProjectStructureResponse): ProjectStructureAnalysis {
  return {
    projectType: localizeProjectType(response.project_type),
    analyzedFileCount: response.analyzed_file_count,
    analysisWarning: response.analysis_warning ? localizeAnalysisWarning(response.analysis_warning) : null,
    sourceCount: response.source_count,
    dependencyFiles: response.dependency_files,
    dependencyPackages: response.dependency_packages,
    detectedFrameworks: response.detected_frameworks,
    testFiles: response.test_files,
    docFiles: response.doc_files,
    configFiles: response.config_files,
    entryFiles: response.entry_files,
    ciFiles: response.ci_files,
    topDirectories: response.top_directories.map((item) => ({
      name: item.name,
      count: item.count,
      mainCategory: item.main_category,
      sourceCount: item.source_count,
    })),
    analysisSource: 'backend' as const,
  }
}
