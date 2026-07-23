/**
 * ChatSidebar — LLM-powered repository Q&A agent sidebar.
 */
import { useState, useEffect, useRef } from 'react'
import type { FormEvent } from 'react'
import {
  AlertCircle, Bot, Loader2, Send, Sparkles, UserRound,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { askAssistant } from '../api'
import type { AssistantChatMessage, AssistantChatResponse, RepositorySnapshot } from '../api'
import '../component-css/ChatSidebar.css'

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
  }, [repositoryName])

  function selectPrompt(prompt: string) {
    setInput(prompt)
    window.requestAnimationFrame(() => inputRef.current?.focus())
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
                      <a href={citation.url} target="_blank" key={`${citation.type}-${citation.label}`}>
                        {citation.type}: {citation.label}
                      </a>
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
    </aside>
  )
}
