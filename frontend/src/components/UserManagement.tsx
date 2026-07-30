import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Activity, AlertCircle, BarChart3, Check, GitBranch, KeyRound, Loader2, LogOut, Pencil, RefreshCw, Save, Shield, Trash2, UserRound, Users, X } from 'lucide-react'

import { deleteUser, fetchIntegrationStatus, fetchUsageStats, fetchUserConfig, fetchUsers, updateUser, updateUserConfig } from '../api'
import type { IntegrationConnection, IntegrationStatus, SystemConfig, SystemConfigUpdate, UsageStats, User } from '../api'
import { useAuth } from '../contexts/AuthContext'
import '../component-css/UserManagement.css'

const emptyForm = { name: '', email: '' }
const emptySecrets = { llm_api_key: '', github_token: '' }

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

export function UserManagement() {
  const { user: currentUser, logout } = useAuth()
  const isAdmin = currentUser?.role === 'admin'

  const [users, setUsers] = useState<User[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState(emptyForm)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [config, setConfig] = useState<SystemConfig | null>(null)
  const [configForm, setConfigForm] = useState({ llm_api_base_url: '', llm_model: '', ...emptySecrets })
  const [configLoading, setConfigLoading] = useState(true)
  const [configSaving, setConfigSaving] = useState(false)
  const [configSaved, setConfigSaved] = useState(false)
  const [integrationStatus, setIntegrationStatus] = useState<IntegrationStatus | null>(null)
  const [usage, setUsage] = useState<UsageStats | null>(null)
  const [checkingConnections, setCheckingConnections] = useState(false)

  const loadUsers = useCallback(async () => {
    if (!isAdmin) return
    setLoading(true)
    setError(null)
    try {
      setUsers(await fetchUsers())
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }, [isAdmin])

  useEffect(() => {
    if (isAdmin) loadUsers()
  }, [isAdmin, loadUsers])

  useEffect(() => {
    fetchUserConfig()
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

  const loadIntegrationOverview = useCallback(async () => {
    setCheckingConnections(true)
    try {
      setIntegrationStatus(await fetchIntegrationStatus())
    } catch (requestError) {
      setError(errorMessage(requestError))
    }
    try {
      setUsage(await fetchUsageStats())
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setCheckingConnections(false)
    }
  }, [])

  useEffect(() => {
    loadIntegrationOverview()
  }, [loadIntegrationOverview])

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
    try {
      setConfig(await updateUserConfig(payload))
      setConfigForm((current) => ({ ...current, ...emptySecrets }))
      setConfigSaved(true)
      await loadIntegrationOverview()
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setConfigSaving(false)
    }
  }

  async function clearSecret(field: 'llm_api_key' | 'github_token') {
    const labels = { llm_api_key: 'LLM API Key', github_token: 'GitHub Token' }
    if (!window.confirm(`确定清除 ${labels[field]} 吗？`)) return
    setConfigSaving(true)
    setError(null)
    try {
      const clearField = `clear_${field}` as keyof SystemConfigUpdate
      setConfig(await updateUserConfig({ [clearField]: true }))
      setConfigSaved(true)
      await loadIntegrationOverview()
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setConfigSaving(false)
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
    if (user.id === currentUser?.id) {
      setError('不能删除自己的账户。')
      return
    }
    if (!window.confirm(`确定删除用户"${user.name}"吗？`)) return
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
          <p>维护个人配置{isAdmin ? '并管理用户资料' : ''}。</p>
        </div>
        <div className="header-actions">
          {currentUser && (
            <span className="current-user-badge">
              <span className="user-avatar-sm">{currentUser.name.slice(0, 1).toUpperCase()}</span>
              {currentUser.name}
              {isAdmin && <span className="admin-badge"><Shield size={12} />管理员</span>}
            </span>
          )}
          {isAdmin && (
            <button className="ghost-button" type="button" onClick={loadUsers} disabled={loading}>
              <RefreshCw className={loading ? 'spin' : ''} size={16} aria-hidden="true" />刷新
            </button>
          )}
          <button className="ghost-button" type="button" onClick={logout}>
            <LogOut size={16} aria-hidden="true" />退出登录
          </button>
        </div>
      </header>

      {/* Per-user config section */}
      <form className="integration-config" onSubmit={handleConfigSave}>
        <div className="config-section-heading">
          <span><KeyRound size={18} aria-hidden="true" /></span>
          <div>
            <h3>我的问答与 GitHub 配置</h3>
            <p>此配置仅对你生效，独立于其他用户。</p>
          </div>
          <button className="connection-check-button" type="button" onClick={loadIntegrationOverview} disabled={checkingConnections}>
            <RefreshCw className={checkingConnections ? 'spin' : ''} size={14} />
            {checkingConnections ? '检测中' : '检测连接'}
          </button>
          {configSaved && <span className="config-saved"><Check size={14} />已保存</span>}
        </div>

        {configLoading ? (
          <div className="config-loading"><Loader2 className="spin" size={20} />正在读取配置</div>
        ) : (
          <div className="config-fields">
            <label className="config-wide">
              LLM API 地址
              <input type="url" value={configForm.llm_api_base_url} onChange={(event) => setConfigForm({ ...configForm, llm_api_base_url: event.target.value })} placeholder="https://api.example.com/v1" />
            </label>
            <label>
              模型
              <input value={configForm.llm_model} onChange={(event) => setConfigForm({ ...configForm, llm_model: event.target.value })} placeholder="模型名称" />
            </label>
            <SecretField label="LLM API Key" configured={config?.llm_api_key_configured ?? false} value={configForm.llm_api_key} onChange={(value) => setConfigForm({ ...configForm, llm_api_key: value })} onClear={() => clearSecret('llm_api_key')} />
            <SecretField label="GitHub Token" configured={config?.github_token_configured ?? false} value={configForm.github_token} onChange={(value) => setConfigForm({ ...configForm, github_token: value })} onClear={() => clearSecret('github_token')} />
          </div>
        )}

        <div className="connection-grid" aria-label="集成连接状态">
          <ConnectionCard label="LLM API" icon={<Activity size={17} />} connection={integrationStatus?.llm} loading={checkingConnections} />
          <ConnectionCard label="GitHub" icon={<GitBranch size={17} />} connection={integrationStatus?.github} loading={checkingConnections} />
        </div>

        <div className="config-actions">
          <p>密钥不会显示在页面或接口响应中；留空会保留当前值。</p>
          <button className="primary-button" type="submit" disabled={configLoading || configSaving}>
            {configSaving ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
            保存配置
          </button>
        </div>
      </form>

      <section className="usage-panel">
        <div className="usage-heading">
          <span><BarChart3 size={18} /></span>
          <div>
            <h3>API 请求与 Token 用量</h3>
            <p>统计当前账号发起的外部请求，Token 数据以模型服务返回值为准。</p>
          </div>
          <button className="ghost-button" type="button" onClick={loadIntegrationOverview} disabled={checkingConnections}>
            <RefreshCw className={checkingConnections ? 'spin' : ''} size={14} />刷新
          </button>
        </div>
        <div className="usage-grid">
          <UsageMetric label="LLM 请求" value={usage?.llm_requests} />
          <UsageMetric label="GitHub 请求" value={usage?.github_requests} />
          <UsageMetric label="输入 Token" value={usage?.prompt_tokens} />
          <UsageMetric label="输出 Token" value={usage?.completion_tokens} />
          <UsageMetric label="总 Token" value={usage?.total_tokens} emphasized />
        </div>
        <p className="usage-updated">{usage?.updated_at ? `最近统计：${new Date(usage.updated_at).toLocaleString('zh-CN')}` : '暂时没有请求记录'}</p>
      </section>

      {error && <div className="notice error"><AlertCircle size={18} /><span>{error}</span></div>}

      {/* User list — admin only */}
      {isAdmin && (
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
                <thead><tr><th>用户</th><th>邮箱</th><th>角色</th><th>创建时间</th><th>操作</th></tr></thead>
                <tbody>
                  {users.map((user) => editingId === user.id ? (
                    <tr key={user.id} className="editing-row">
                      <td colSpan={5}>
                        <form className="user-edit-form" onSubmit={handleUpdate}>
                          <input aria-label="姓名" required maxLength={100} value={editForm.name} onChange={(event) => setEditForm({ ...editForm, name: event.target.value })} />
                          <input aria-label="邮箱" required type="email" maxLength={320} value={editForm.email} onChange={(event) => setEditForm({ ...editForm, email: event.target.value })} />
                          <div className="row-actions">
                            <button className="icon-button-sm user-action-button cancel-edit" type="button" onClick={() => setEditingId(null)} disabled={saving}>
                              <X size={14} />取消编辑
                            </button>
                            <button className="icon-button-sm user-action-button save-edit" type="submit" disabled={saving}>
                              {saving ? <><Loader2 className="spin" size={14} />保存中</> : <><Check size={15} />保存编辑</>}
                            </button>
                          </div>
                        </form>
                      </td>
                    </tr>
                  ) : (
                    <tr key={user.id}>
                      <td><span className="user-avatar">{user.name.slice(0, 1).toUpperCase()}</span><strong>{user.name}</strong></td>
                      <td>{user.email}</td>
                      <td>
                        {user.role === 'admin' ? (
                          <span className="role-badge admin"><Shield size={11} />管理员</span>
                        ) : (
                          <span className="role-badge user">普通用户</span>
                        )}
                      </td>
                      <td>{new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(user.created_at))}</td>
                      <td><div className="row-actions">
                        <button className="icon-button-sm user-action-button edit" type="button" onClick={() => startEditing(user)} title="编辑用户"><Pencil size={14} />编辑</button>
                        <button className="icon-button-sm user-action-button danger" type="button" onClick={() => handleDelete(user)} disabled={deletingId === user.id || user.id === currentUser?.id} title={user.id === currentUser?.id ? '不能删除自己' : '删除用户'}>
                          {deletingId === user.id ? <><Loader2 className="spin" size={14} />删除中</> : <><Trash2 size={14} />删除</>}
                        </button>
                      </div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </section>
  )
}

type SecretFieldProps = {
  label: string
  configured: boolean
  value: string
  onChange: (value: string) => void
  onClear: () => void
}

function SecretField({ label, configured, value, onChange, onClear }: SecretFieldProps) {
  return (
    <label className="secret-field">
      <span className="secret-label">
        <span><KeyRound size={14} />{label}</span>
        <span className={configured ? 'secret-status configured' : 'secret-status'}>{configured ? '已配置' : '未配置'}</span>
      </span>
      <span className="secret-input-row">
        <input type="password" autoComplete="new-password" value={value} onChange={(event) => onChange(event.target.value)} placeholder={configured ? '输入新值以替换' : '输入密钥'} />
        {configured && <button type="button" className="clear-secret" onClick={onClear} title={`清除 ${label}`}><X size={15} /></button>}
      </span>
    </label>
  )
}

function ConnectionCard({ label, icon, connection, loading }: {
  label: string
  icon: ReactNode
  connection?: IntegrationConnection
  loading: boolean
}) {
  const status = loading ? 'checking' : connection?.status ?? 'not_configured'
  const labels = {
    checking: '检测中',
    connected: '已联通',
    configured: '待验证',
    failed: '连接异常',
    not_configured: '未配置',
  }
  return (
    <div className={`connection-card ${status}`}>
      <span className="connection-icon">{loading ? <Loader2 className="spin" size={17} /> : icon}</span>
      <div>
        <strong>{label}</strong>
        <p>{loading ? '正在检测连接…' : connection?.message ?? '等待检测'}</p>
        {connection?.last_received_at && <small>最近事件：{new Date(connection.last_received_at).toLocaleString('zh-CN')}</small>}
      </div>
      <span className="connection-badge">{labels[status]}</span>
    </div>
  )
}

function UsageMetric({ label, value, emphasized = false }: { label: string; value?: number; emphasized?: boolean }) {
  return (
    <div className={`usage-metric ${emphasized ? 'emphasized' : ''}`}>
      <span>{label}</span>
      <strong>{value === undefined ? '—' : value.toLocaleString()}</strong>
    </div>
  )
}
