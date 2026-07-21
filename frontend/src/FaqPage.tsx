import { useState, useEffect } from 'react'
import { BookOpen, Check, CheckCircle, Loader2, Plus, RefreshCw, Trash2, X } from 'lucide-react'

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

  async function loadFaq() {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE_URL}/api/faq`)
      if (res.ok) setEntries(await res.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadFaq() }, [])

  async function handleConfirm(id: number, confirmed: boolean) {
    await fetch(`${API_BASE_URL}/api/faq/${id}?action=${confirmed ? 'confirm' : 'unconfirm'}`, { method: 'PATCH' })
    loadFaq()
  }

  async function handleDelete(id: number) {
    await fetch(`${API_BASE_URL}/api/faq/${id}`, { method: 'DELETE' })
    loadFaq()
  }

  async function handleGenerate() {
    setGenerating(true)
    try {
      await fetch(`${API_BASE_URL}/api/faq/generate?owner=${owner}&name=${name}`, { method: 'POST' })
      loadFaq()
    } finally {
      setGenerating(false)
    }
  }

  async function handleAdd() {
    if (!newQuestion.trim() || !newAnswer.trim()) return
    await fetch(`${API_BASE_URL}/api/faq`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: newQuestion, answer: newAnswer }),
    })
    setShowAdd(false)
    setNewQuestion('')
    setNewAnswer('')
    loadFaq()
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
                  <button className="icon-button-sm" onClick={() => handleConfirm(entry.id, !entry.is_confirmed)} title={entry.is_confirmed ? '取消确认' : '确认'}>
                    {entry.is_confirmed ? <X size={14} /> : <Check size={14} />}
                  </button>
                  <button className="icon-button-sm" onClick={() => handleDelete(entry.id)} title="删除">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              <p className="faq-answer">{entry.answer}</p>
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
