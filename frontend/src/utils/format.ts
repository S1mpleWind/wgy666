/**
 * Formatting utility functions
 */

export function formatCategory(category: string) {
  return category.replaceAll('_', ' ')
}

export function formatProjectCategory(category: string) {
  const labels: Record<string, string> = {
    source_code: '源码',
    tests: '测试',
    documentation: '文档',
    configuration: '配置',
    ci_cd: 'CI/CD',
    dependency: '依赖配置',
    build: '构建',
    assets: '静态资源',
    data: '数据',
    other: '其他',
  }
  return labels[category] ?? category.replaceAll('_', ' ')
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function formatTimeAgo(value: string) {
  const diff = Date.now() - new Date(value).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  return `${days} 天前`
}
