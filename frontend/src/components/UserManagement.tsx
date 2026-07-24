import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { AlertCircle, Check, KeyRound, Loader2, Pencil, Plus, RefreshCw, Save, Trash2, UserRound, Users, Webhook, X } from 'lucide-react'

import { createUser, deleteUser, fetchSystemConfig, fetchUsers, updateSystemConfig, updateUser } from '../api'
import type { SystemConfig, SystemConfigUpdate, User } from '../api'
import '../component-css/UserManagement.css'

const emptyForm = { name: '', email: '' }
const emptySecrets = { llm_api_key: '', github_token: '', github_webhook_secret: '' }

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

export function UserManagement() {
  const [users, setUsers] = useState<User[]>([])
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState(emptyForm)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [config, setConfig] = useState<SystemConfig | null>(null)
  const [configForm, setConfigForm] = useState({ llm_api_base_url: '', llm_model: '', ...emptySecrets })
  const [configLoading, setConfigLoading] = useState(true)
  const [configSaving, setConfigSaving] = useState(false)
  const [configSaved, setConfigSaved] = useState(false)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setUsers(await fetchUsers())
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  useEffect(() => {
    fetchSystemConfig()
      .then((value) => {
        setConfig(value)
        setConfigForm((current) => ({
          ...current,
          llm_api_base_url: value.llm_api_base_url,
          llm_model: value.llm_model,
        }))
      })
      .catch((requestError) => setError(errorMessage(requestError)))
      .finally(() => setConfigLoading(false))
  }, [])

  async function handleConfigSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setConfigSaving(true)
    setConfigSaved(false)
    setError(null)
    const payload: SystemConfigUpdate = {
      llm_api_base_url: configForm.llm_api_base_url,
      llm_model: configForm.llm_model,
    }
    if (configForm.llm_api_key) payload.llm_api_key = configForm.llm_api_key
    if (configForm.github_token) payload.github_token = configForm.github_token
    if (configForm.github_webhook_secret) payload.github_webhook_secret = configForm.github_webhook_secret
    try {
      setConfig(await updateSystemConfig(payload))
      setConfigForm((current) => ({ ...current, ...emptySecrets }))
      setConfigSaved(true)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setConfigSaving(false)
    }
  }

  async function clearSecret(field: 'llm_api_key' | 'github_token' | 'github_webhook_secret') {
    const labels = { llm_api_key: 'LLM API Key', github_token: 'GitHub Token', github_webhook_secret: 'Webhook Secret' }
    if (!window.confirm(`确定清除 ${labels[field]} 吗？`)) return
    setConfigSaving(true)
    setError(null)
    try {
      const clearField = `clear_${field}` as keyof SystemConfigUpdate
      setConfig(await updateSystemConfig({ [clearField]: true }))
      setConfigSaved(true)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setConfigSaving(false)
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const user = await createUser(form)
      setUsers((current) => [...current, user])
      setForm(emptyForm)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setSaving(false)
    }
  }

  function startEditing(user: User) {
    setEditingId(user.id)
    setEditForm({ name: user.name, email: user.email })
    setError(null)
  }

  async function handleUpdate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!editingId) return
    setSaving(true)
    setError(null)
    try {
      const user = await updateUser(editingId, editForm)
      setUsers((current) => current.map((item) => item.id === user.id ? user : item))
      setEditingId(null)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(user: User) {
    if (!window.confirm(`确定删除用户“${user.name}”吗？`)) return
    setDeletingId(user.id)
    setError(null)
    try {
      await deleteUser(user.id)
      setUsers((current) => current.filter((item) => item.id !== user.id))
      if (editingId === user.id) setEditingId(null)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <section className="user-management">
      <header className="user-page-header">
        <div>
          <span className="eyebrow">系统管理</span>
          <h2><Users size={22} aria-hidden="true" />用户管理</h2>
          <p>维护可使用 IssueScope 的用户资料。</p>
        </div>
        <button className="ghost-button" type="button" onClick={loadUsers} disabled={loading}>
          <RefreshCw className={loading ? 'spin' : ''} size={16} aria-hidden="true" />刷新
        </button>
      </header>

      <form className="integration-config" onSubmit={handleConfigSave}>
        <div className="config-section-heading">
          <span><KeyRound size={18} aria-hidden="true" /></span>
          <div><h3>问答与 GitHub 配置</h3><p>保存后立即生效，并在后端重启后保留。</p></div>
          {configSaved && <span className="config-saved"><Check size={14} />已保存</span>}
        </div>

        {configLoading ? (
          <div className="config-loading"><Loader2 className="spin" size={20} />正在读取配置</div>
        ) : (
          <div className="config-fields">
            <label className="config-wide">
              LLM API 地址
              <input required type="url" value={configForm.llm_api_base_url} onChange={(event) => setConfigForm({ ...configForm, llm_api_base_url: event.target.value })} placeholder="https://api.example.com/v1" />
            </label>
            <label>
              模型
              <input required value={configForm.llm_model} onChange={(event) => setConfigForm({ ...configForm, llm_model: event.target.value })} placeholder="模型名称" />
            </label>
            <SecretField label="LLM API Key" configured={config?.llm_api_key_configured ?? false} value={configForm.llm_api_key} onChange={(value) => setConfigForm({ ...configForm, llm_api_key: value })} onClear={() => clearSecret('llm_api_key')} />
            <SecretField label="GitHub Token" configured={config?.github_token_configured ?? false} value={configForm.github_token} onChange={(value) => setConfigForm({ ...configForm, github_token: value })} onClear={() => clearSecret('github_token')} />
            <SecretField label="Webhook Secret" configured={config?.github_webhook_secret_configured ?? false} value={configForm.github_webhook_secret} onChange={(value) => setConfigForm({ ...configForm, github_webhook_secret: value })} onClear={() => clearSecret('github_webhook_secret')} icon="webhook" />
          </div>
        )}

        <div className="config-actions">
          <p>密钥不会显示在页面或接口响应中；留空会保留当前值。</p>
          <button className="primary-button" type="submit" disabled={configLoading || configSaving}>
            {configSaving ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
            保存配置
          </button>
        </div>
      </form>

      <form className="user-create-form" onSubmit={handleCreate}>
        <div className="user-form-title">
          <span><Plus size={17} aria-hidden="true" /></span>
          <div><strong>新增用户</strong><small>邮箱在系统中不可重复</small></div>
        </div>
        <label>
          姓名
          <input required maxLength={100} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="输入用户姓名" />
        </label>
        <label>
          邮箱
          <input required type="email" maxLength={320} value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} placeholder="name@example.com" />
        </label>
        <button className="primary-button" type="submit" disabled={saving}>
          {saving && !editingId ? <Loader2 className="spin" size={17} /> : <Plus size={17} />}
          添加用户
        </button>
      </form>

      {error && <div className="notice error"><AlertCircle size={18} /><span>{error}</span></div>}

      <section className="user-list-section">
        <div className="user-list-heading">
          <div><h3>用户列表</h3><p>{users.length} 位用户</p></div>
        </div>

        {loading ? (
          <div className="user-list-state"><Loader2 className="spin" size={22} /><span>正在加载用户</span></div>
        ) : users.length === 0 ? (
          <div className="user-list-state"><UserRound size={25} /><strong>暂无用户</strong></div>
        ) : (
          <div className="user-table-wrap">
            <table className="user-table">
              <thead><tr><th>用户</th><th>邮箱</th><th>创建时间</th><th><span className="sr-only">操作</span></th></tr></thead>
              <tbody>
                {users.map((user) => editingId === user.id ? (
                  <tr key={user.id} className="editing-row">
                    <td colSpan={4}>
                      <form className="user-edit-form" onSubmit={handleUpdate}>
                        <input aria-label="姓名" required maxLength={100} value={editForm.name} onChange={(event) => setEditForm({ ...editForm, name: event.target.value })} />
                        <input aria-label="邮箱" required type="email" maxLength={320} value={editForm.email} onChange={(event) => setEditForm({ ...editForm, email: event.target.value })} />
                        <div className="row-actions">
                          <button className="icon-button-sm save" type="submit" disabled={saving} title="保存"><Check size={15} /></button>
                          <button className="icon-button-sm" type="button" onClick={() => setEditingId(null)} title="取消"><X size={15} /></button>
                        </div>
                      </form>
                    </td>
                  </tr>
                ) : (
                  <tr key={user.id}>
                    <td><span className="user-avatar">{user.name.slice(0, 1).toUpperCase()}</span><strong>{user.name}</strong></td>
                    <td>{user.email}</td>
                    <td>{new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(user.created_at))}</td>
                    <td><div className="row-actions">
                      <button className="icon-button-sm" type="button" onClick={() => startEditing(user)} title="编辑用户"><Pencil size={14} /></button>
                      <button className="icon-button-sm danger" type="button" onClick={() => handleDelete(user)} disabled={deletingId === user.id} title="删除用户">
                        {deletingId === user.id ? <Loader2 className="spin" size={14} /> : <Trash2 size={14} />}
                      </button>
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  )
}

type SecretFieldProps = {
  label: string
  configured: boolean
  value: string
  onChange: (value: string) => void
  onClear: () => void
  icon?: 'webhook'
}

function SecretField({ label, configured, value, onChange, onClear, icon }: SecretFieldProps) {
  return (
    <label className="secret-field">
      <span className="secret-label">
        <span>{icon === 'webhook' ? <Webhook size={14} /> : <KeyRound size={14} />}{label}</span>
        <span className={configured ? 'secret-status configured' : 'secret-status'}>{configured ? '已配置' : '未配置'}</span>
      </span>
      <span className="secret-input-row">
        <input type="password" autoComplete="new-password" value={value} onChange={(event) => onChange(event.target.value)} placeholder={configured ? '输入新值以替换' : '输入密钥'} />
        {configured && <button type="button" className="clear-secret" onClick={onClear} title={`清除 ${label}`}><X size={15} /></button>}
      </span>
    </label>
  )
}
