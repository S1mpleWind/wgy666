import { useCallback, useState, useEffect } from 'react'
import { BookOpen, Loader2, Plus, RefreshCw } from 'lucide-react'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type FaqEntry = {
  id: number
  question: string
  answer: string
  keywords: string[]
  hit_count: number
  is_confirmed: boolean
  related_issue_ids: number[]
  created_at: string
}

export default function FaqPage({ owner, name }: { owner: string; name: string }) {
  const [entries, setEntries] = useState<FaqEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [newQuestion, setNewQuestion] = useState('')
  const [newAnswer, setNewAnswer] = useState('')
  const [faqError, setFaqError] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editQuestion, setEditQuestion] = useState('')
  const [editAnswer, setEditAnswer] = useState('')

  const loadFaq = useCallback(async () => {
    setLoading(true)
    setFaqError('')
    try {
      const params = new URLSearchParams({ owner, name })
      const res = await fetch(`${API_BASE_URL}/api/faq?${params}`)
      if (!res.ok) throw new Error(await responseError(res, 'FAQ 加载失败'))
      setEntries(await res.json())
    } catch (error) {
      setFaqError(error instanceof Error ? error.message : 'FAQ 加载失败')
    } finally {
      setLoading(false)
    }
  }, [owner, name])

  useEffect(() => { loadFaq() }, [loadFaq])

  async function handleConfirm(id: number, confirmed: boolean) {
    const params = new URLSearchParams({ owner, name, action: confirmed ? 'confirm' : 'unconfirm' })
    const response = await fetch(`${API_BASE_URL}/api/faq/${id}?${params}`, { method: 'PATCH' })
    if (!response.ok) {
      setFaqError(await responseError(response, 'FAQ 更新失败'))
      return
    }
    await loadFaq()
  }

  async function handleEdit(id: number, question: string, answer: string) {
    const params = new URLSearchParams({ owner, name, action: 'edit' })
    const response = await fetch(`${API_BASE_URL}/api/faq/${id}?${params}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, answer }),
    })
    if (!response.ok) {
      setFaqError(await responseError(response, 'FAQ 编辑失败'))
      return
    }
    setEditingId(null)
    setEditQuestion('')
    setEditAnswer('')
    await loadFaq()
  }

  async function handleDelete(id: number) {
    const params = new URLSearchParams({ owner, name })
    const response = await fetch(`${API_BASE_URL}/api/faq/${id}?${params}`, { method: 'DELETE' })
    if (!response.ok) {
      setFaqError(await responseError(response, 'FAQ 删除失败'))
      return
    }
    await loadFaq()
  }

  async function handleGenerate() {
    setGenerating(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/faq/generate?owner=${owner}&name=${name}`, { method: 'POST' })
      if (!response.ok) throw new Error(await responseError(response, 'FAQ 自动生成失败'))
      const data = await response.json()
      await loadFaq()
      if (data.reason) {
        setFaqError(data.reason)
      }
    } catch (error) {
      setFaqError(error instanceof Error ? error.message : 'FAQ 自动生成失败')
    } finally {
      setGenerating(false)
    }
  }

  async function handleAdd() {
    if (!newQuestion.trim() || !newAnswer.trim()) return
    const params = new URLSearchParams({ owner, name })
    const response = await fetch(`${API_BASE_URL}/api/faq?${params}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: newQuestion, answer: newAnswer }),
    })
    if (!response.ok) {
      setFaqError(await responseError(response, 'FAQ 保存失败'))
      return
    }
    setShowAdd(false)
    setNewQuestion('')
    setNewAnswer('')
    await loadFaq()
  }

  return (
    <div className="faq-page">
      <div className="faq-header">
        <h2><BookOpen size={20} /> FAQ 知识库</h2>
        <div className="faq-actions">
          <button className="ghost-button" onClick={() => setShowAdd(!showAdd)}>
            <Plus size={16} /> 手动添加
          </button>
          <button className="ghost-button" onClick={handleGenerate} disabled={generating}>
            {generating ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            自动生成
          </button>
        </div>
      </div>

      {faqError && <div className="notice error">{faqError}</div>}

      {showAdd && (
        <div className="faq-add-form">
          <input placeholder="问题" value={newQuestion} onChange={e => setNewQuestion(e.target.value)} />
          <textarea placeholder="回答" value={newAnswer} onChange={e => setNewAnswer(e.target.value)} rows={3} />
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="primary-button" onClick={handleAdd}>保存</button>
            <button className="ghost-button" onClick={() => setShowAdd(false)}>取消</button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="muted">加载中...</p>
      ) : entries.length === 0 ? (
        <p className="muted">暂无 FAQ 条目。点击「自动生成」从已关闭 Issue 中总结，或手动添加。</p>
      ) : (
        <div className="faq-list">
          {entries.map(entry => (
            <div key={entry.id} className={`faq-item ${entry.is_confirmed ? '' : 'unconfirmed'}`}>
              <div className="faq-item-header">
                <strong>{entry.question}</strong>
                <div className="faq-item-meta">
                  {!entry.is_confirmed && <span className="badge" style={{ background: '#fff4d6', color: '#946200' }}>待确认</span>}
                  <span style={{ fontSize: 11, color: '#6a747e' }}>命中 {entry.hit_count} 次</span>
                  <button className="ghost-button" style={{ minHeight: 28, padding: '0 4px', fontSize: 11 }} onClick={() => handleConfirm(entry.id, !entry.is_confirmed)}>
                    {entry.is_confirmed ? '取消确认' : '确认'}
                  </button>
                  <button className="ghost-button" style={{ minHeight: 28, padding: '0 4px', fontSize: 11 }} onClick={() => { setEditingId(entry.id); setEditQuestion(entry.question); setEditAnswer(entry.answer); }}>
                    编辑
                  </button>
                  <button className="ghost-button" style={{ minHeight: 28, padding: '0 4px', fontSize: 11 }} onClick={() => handleDelete(entry.id)}>
                    删除
                  </button>
                </div>
              </div>
              {editingId === entry.id ? (
                <div className="faq-add-form" style={{ marginTop: 8 }}>
                  <input value={editQuestion} onChange={e => setEditQuestion(e.target.value)} placeholder="问题" />
                  <textarea value={editAnswer} onChange={e => setEditAnswer(e.target.value)} placeholder="回答" rows={3} />
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button className="primary-button" onClick={() => handleEdit(entry.id, editQuestion, editAnswer)}>保存</button>
                    <button className="ghost-button" onClick={() => setEditingId(null)}>取消</button>
                  </div>
                </div>
              ) : (
                <p className="faq-answer">{entry.answer}</p>
              )}
              {entry.related_issue_ids && entry.related_issue_ids.length > 0 && (
                <div className="faq-related">
                  关联 Issue: {entry.related_issue_ids.map(id => `#${id}`).join(', ')}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

async function responseError(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => null)
  return body?.detail ?? `${fallback}（${response.status}）`
}

