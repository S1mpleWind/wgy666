/**
 * ChatSidebar — LLM-powered repository Q&A agent sidebar.
 */
import { useState, useEffect, useRef } from 'react'
import type { FormEvent } from 'react'
import {
  AlertCircle, Bot, ExternalLink, FileCode2, Loader2, Send, Sparkles, UserRound, X,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { askAssistant, fetchFileContent } from '../api'
import type {
  AssistantChatMessage, AssistantChatResponse, AssistantCitation, RepositoryFileContent, RepositorySnapshot,
} from '../api'
import '../component-css/ChatSidebar.css'
import '../component-css/FileBrowser.css'

type ChatThreadMessage = AssistantChatMessage & {
  toolCalls?: AssistantChatResponse['tool_calls']
  citations?: AssistantChatResponse['citations']
  usedCachedData?: boolean
}

export function ChatSidebar({
  snapshot, focusRequest, highlighted,
}: {
  snapshot: RepositorySnapshot | null
  focusRequest: number
  highlighted: boolean
}) {
  const [messages, setMessages] = useState<ChatThreadMessage[]>([
    {
      role: 'assistant',
      content: '同步仓库后，可以问我项目结构、Issue、测试文件、依赖、README 或最近活动。',
    },
  ])
  const [input, setInput] = useState('')
  const [isAsking, setIsAsking] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)
  const [selectedCitation, setSelectedCitation] = useState<AssistantCitation | null>(null)
  const [citationContent, setCitationContent] = useState<RepositoryFileContent | null>(null)
  const [citationLoading, setCitationLoading] = useState(false)
  const [citationError, setCitationError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const repositoryName = snapshot?.identity.full_name ?? null

  useEffect(() => {
    if (focusRequest > 0) inputRef.current?.focus()
  }, [focusRequest])

  useEffect(() => {
    setMessages([
      {
        role: 'assistant',
        content: repositoryName
          ? `已切换到 ${repositoryName}，可以继续提问。`
          : '同步仓库后，可以问我 Issue、README 或最近活动。',
      },
    ])
    setInput('')
    setChatError(null)
    closeCitation()
  }, [repositoryName])

  useEffect(() => {
    if (!selectedCitation) return undefined

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') closeCitation()
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedCitation])

  function selectPrompt(prompt: string) {
    setInput(prompt)
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  function closeCitation() {
    setSelectedCitation(null)
    setCitationContent(null)
    setCitationError(null)
    setCitationLoading(false)
  }

  async function openCitation(citation: AssistantCitation) {
    if (!snapshot || !citation.path) return

    setSelectedCitation(citation)
    setCitationContent(null)
    setCitationError(null)
    setCitationLoading(true)

    try {
      const content = await fetchFileContent(
        snapshot.identity.owner,
        snapshot.identity.name,
        citation.path,
      )
      setCitationContent(content)
    } catch (exc) {
      setCitationError(exc instanceof Error ? exc.message : '加载引用代码失败')
    } finally {
      setCitationLoading(false)
    }
  }

  function githubFileUrl(citation: AssistantCitation) {
    if (!snapshot || !citation.path) return snapshot?.identity.html_url ?? '#'
    const encodedPath = citation.path.split('/').map(encodeURIComponent).join('/')
    const lineAnchor = citation.line_start
      ? `#L${citation.line_start}${citation.line_end && citation.line_end !== citation.line_start ? `-L${citation.line_end}` : ''}`
      : ''
    return `${snapshot.identity.html_url}/blob/${encodeURIComponent(snapshot.identity.default_branch)}/${encodedPath}${lineAnchor}`
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!snapshot || !input.trim() || isAsking) return

    const question = input.trim()
    const history = messages
      .filter((message) => message.role === 'user' || message.role === 'assistant')
      .slice(-8)
      .map(({ role, content }) => ({ role, content }))

    const userMessage: ChatThreadMessage = { role: 'user', content: question }
    setMessages((current) => [...current, userMessage])
    setInput('')
    setIsAsking(true)
    setChatError(null)

    try {
      const response = await askAssistant({
        owner: snapshot.identity.owner,
        name: snapshot.identity.name,
        message: question,
        freshness: 'cache_first',
        history,
      })
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: response.answer,
          toolCalls: response.tool_calls,
          citations: response.citations,
          usedCachedData: response.used_cached_data,
        },
      ])
    } catch (exc) {
      setChatError(exc instanceof Error ? exc.message : '问答失败')
    } finally {
      setIsAsking(false)
    }
  }

  return (
    <aside className={`chat-sidebar ${highlighted ? 'highlighted' : ''}`} id="repository-agent">
      <header className="chat-header">
        <div>
          <span className="agent-mark"><Bot size={18} aria-hidden="true" /></span>
          <div>
            <h2>Repository Agent</h2>
            <p>{snapshot ? `正在分析 ${snapshot.identity.full_name}` : '等待仓库上下文'}</p>
          </div>
        </div>
        <span className={`agent-state ${snapshot ? 'ready' : ''}`}>
          <span />{snapshot ? 'Ready' : 'Standby'}
        </span>
      </header>

      <div className="quick-prompts" aria-label="快捷问题">
        {['项目入口在哪？', '解释核心架构', '有哪些高风险 Issue？'].map((prompt) => (
          <button disabled={!snapshot || isAsking} key={prompt} type="button" onClick={() => selectPrompt(prompt)}>
            {prompt}
          </button>
        ))}
      </div>

      <div className="chat-thread">
        {messages.map((message, index) => (
          <article className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
            <div className="chat-avatar">
              {message.role === 'assistant' ? <Bot size={16} aria-hidden="true" /> : <UserRound size={16} aria-hidden="true" />}
            </div>
            <div className="chat-bubble">
              <div className="chat-content markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>
              {message.toolCalls && message.toolCalls.length > 0 && (
                <div className="tool-strip">
                  {message.toolCalls.map((tool) => (
                    <span key={`${index}-${tool.name}`}>{tool.name}</span>
                  ))}
                </div>
              )}
              {message.citations && message.citations.length > 0 && (
                <div className="citation-list">
                  {message.citations.slice(0, 5).map((citation) => (
                    citation.url ? (
                      <a href={citation.url} rel="noreferrer" target="_blank" key={`${citation.type}-${citation.label}`}>
                        {citation.type}: {citation.label}
                      </a>
                    ) : citation.path ? (
                      <button
                        className="citation-button"
                        key={`${citation.type}-${citation.label}`}
                        onClick={() => openCitation(citation)}
                        title={`查看 ${citation.path}`}
                        type="button"
                      >
                        <FileCode2 size={12} aria-hidden="true" />
                        {citation.type}: {citation.label}
                      </button>
                    ) : (
                      <span key={`${citation.type}-${citation.label}`}>
                        {citation.type}: {citation.label}
                      </span>
                    )
                  ))}
                </div>
              )}
              {typeof message.usedCachedData === 'boolean' && (
                <span className="cache-note">{message.usedCachedData ? 'cache used' : 'synced before answer'}</span>
              )}
            </div>
          </article>
        ))}
        {isAsking && (
          <article className="chat-message assistant">
            <div className="chat-avatar">
              <Bot size={16} aria-hidden="true" />
            </div>
            <div className="chat-bubble loading">
              <Loader2 className="spin" size={16} aria-hidden="true" />
              正在调用仓库工具...
            </div>
          </article>
        )}
      </div>

      {chatError && (
        <div className="notice error chat-error">
          <AlertCircle size={16} aria-hidden="true" />
          <span>{chatError}</span>
        </div>
      )}

      <form className="chat-form" onSubmit={handleAsk}>
        <div className="chat-composer">
          <input
            ref={inputRef}
            disabled={!snapshot || isAsking}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={snapshot ? '向仓库提问，回答将附带来源…' : '请先同步仓库'}
          />
          <button disabled={!snapshot || isAsking || !input.trim()} type="submit" aria-label="发送问题">
            <Send size={17} aria-hidden="true" />
          </button>
        </div>
        <p><Sparkles size={12} />回答基于同步仓库数据，重要结论会标注来源</p>
      </form>

      {selectedCitation && (
        <div className="code-viewer-overlay" onMouseDown={closeCitation}>
          <section
            aria-label={`${selectedCitation.path} 引用代码`}
            aria-modal="true"
            className="code-viewer citation-code-viewer"
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <header className="code-viewer-header">
              <div>
                <FileCode2 size={18} aria-hidden="true" />
                <div>
                  <strong>{selectedCitation.path}</strong>
                  <span className="code-viewer-meta">
                    问答引用
                    {selectedCitation.line_start && ` · 第 ${selectedCitation.line_start}${selectedCitation.line_end ? `-${selectedCitation.line_end}` : ''} 行`}
                  </span>
                </div>
              </div>
              <div className="citation-viewer-actions">
                <a href={githubFileUrl(selectedCitation)} rel="noreferrer" target="_blank">
                  <ExternalLink size={15} aria-hidden="true" />
                  GitHub
                </a>
                <button className="ghost-button" onClick={closeCitation} aria-label="关闭引用代码">
                  <X size={18} />
                </button>
              </div>
            </header>
            <div className="code-viewer-body">
              {citationLoading ? (
                <div className="code-viewer-loading">
                  <Loader2 className="spin" size={24} aria-hidden="true" />
                  <span>正在读取引用代码...</span>
                </div>
              ) : citationError ? (
                <div className="citation-viewer-error">
                  <div className="notice error">
                    <AlertCircle size={16} aria-hidden="true" />
                    <span>{citationError}</span>
                  </div>
                  <a href={githubFileUrl(selectedCitation)} rel="noreferrer" target="_blank">
                    前往 GitHub 查看文件 <ExternalLink size={14} aria-hidden="true" />
                  </a>
                </div>
              ) : citationContent ? (
                <div className="citation-code-lines" role="list">
                  {citationContent.content.split('\n').map((line, index) => {
                    const lineNumber = index + 1
                    const highlightedLine = Boolean(
                      selectedCitation.line_start
                      && lineNumber >= selectedCitation.line_start
                      && lineNumber <= (selectedCitation.line_end ?? selectedCitation.line_start),
                    )
                    return (
                      <div className={highlightedLine ? 'highlighted' : ''} key={lineNumber} role="listitem">
                        <span aria-hidden="true">{lineNumber}</span>
                        <code>{line || ' '}</code>
                      </div>
                    )
                  })}
                </div>
              ) : null}
            </div>
          </section>
        </div>
      )}
    </aside>
  )
}
