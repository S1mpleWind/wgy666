/**
 * FileBrowser — indexed file list with a code viewer overlay.
 */
import { useState } from 'react'
import { AlertCircle, FileCode2, Loader2, X } from 'lucide-react'

import { fetchFileContent as fetchFileContentApi } from '../api'
import type { ClassifiedFile, RepositoryFileContent } from '../api'
import '../component-css/FileBrowser.css'
import { formatCategory } from '../utils/format'
import { Panel } from './MetricCard'

export function FileBrowser({ files, owner, name }: { files: ClassifiedFile[]; owner: string; name: string }) {
  const [selectedFile, setSelectedFile] = useState<ClassifiedFile | null>(null)
  const [fileContent, setFileContent] = useState<RepositoryFileContent | null>(null)
  const [contentLoading, setContentLoading] = useState(false)
  const [contentError, setContentError] = useState<string | null>(null)

  async function handleFileClick(file: ClassifiedFile) {
    setSelectedFile(file)
    setContentLoading(true)
    setContentError(null)
    setFileContent(null)

    try {
      const content = await fetchFileContentApi(owner, name, file.path)
      setFileContent(content)
    } catch (exc) {
      setContentError(exc instanceof Error ? exc.message : '加载文件内容失败')
    } finally {
      setContentLoading(false)
    }
  }

  function closeViewer() {
    setSelectedFile(null)
    setFileContent(null)
    setContentError(null)
  }

  return (
    <Panel title={`源代码文件 · ${files.length} 个索引`}>
      <p className="muted" style={{ marginBottom: '0.75rem', fontSize: '0.85rem' }}>
        点击文件路径查看数据库中保存的完整源码内容
      </p>
      <div className="file-list file-browser-list">
        {files.map((file) => (
          <div
            className={`file-item ${selectedFile?.path === file.path ? 'file-item-active' : ''}`}
            key={file.path}
            onClick={() => handleFileClick(file)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') handleFileClick(file)
            }}
            role="button"
            tabIndex={0}
          >
            <span>{file.path}</span>
            <span>{formatCategory(file.category)}</span>
          </div>
        ))}
      </div>

      {selectedFile && (
        <div className="code-viewer-overlay" onClick={closeViewer}>
          <div className="code-viewer" onClick={(event) => event.stopPropagation()}>
            <header className="code-viewer-header">
              <div>
                <FileCode2 size={18} aria-hidden="true" />
                <div>
                  <strong>{selectedFile.path}</strong>
                  <span className="code-viewer-meta">
                    {formatCategory(selectedFile.category)}
                    {selectedFile.size != null && ` · ${(selectedFile.size / 1024).toFixed(1)} KB`}
                  </span>
                </div>
              </div>
              <button className="ghost-button" onClick={closeViewer} aria-label="关闭">
                <X size={18} />
              </button>
            </header>
            <div className="code-viewer-body">
              {contentLoading ? (
                <div className="code-viewer-loading">
                  <Loader2 className="spin" size={24} aria-hidden="true" />
                  <span>从数据库加载源码...</span>
                </div>
              ) : contentError ? (
                <div className="notice error">
                  <AlertCircle size={16} aria-hidden="true" />
                  <span>{contentError}</span>
                </div>
              ) : fileContent ? (
                <pre className="code-block">
                  <code>{fileContent.content}</code>
                </pre>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </Panel>
  )
}
