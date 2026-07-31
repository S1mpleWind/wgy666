import { useState, type FormEvent } from 'react'
import { AlertCircle, KeyRound, Loader2, LogIn, Mail, Sparkles, UserPlus, UserRound } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import '../component-css/LoginPage.css'

export function LoginPage() {
  const { login, register } = useAuth()
  const [isRegistering, setIsRegistering] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      if (isRegistering) {
        await register(name, email, password)
      } else {
        await login(email, password)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <span className="login-brand-icon"><Sparkles size={24} aria-hidden="true" /></span>
          <h1>IssueScope</h1>
          <p>Repository Intelligence Platform</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <h2>{isRegistering ? '创建账户' : '登录'}</h2>

          {isRegistering && (
            <label>
              <span><UserRound size={14} />姓名</span>
              <input
                required
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="输入姓名"
                autoComplete="name"
              />
            </label>
          )}

          <label>
            <span><Mail size={14} />邮箱</span>
            <input
              required
              type="email"
              maxLength={320}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
              autoComplete="email"
            />
          </label>

          <label>
            <span><KeyRound size={14} />密码</span>
            <input
              required
              type="password"
              minLength={6}
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isRegistering ? '至少 6 位密码' : '输入密码'}
              autoComplete={isRegistering ? 'new-password' : 'current-password'}
            />
          </label>

          {error && (
            <div className="login-error">
              <AlertCircle size={16} /><span>{error}</span>
            </div>
          )}

          <button className="primary-button login-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="spin" size={18} /> : isRegistering ? <UserPlus size={18} /> : <LogIn size={18} />}
            {isSubmitting ? '处理中...' : isRegistering ? '注册并登录' : '登录'}
          </button>
        </form>

        <p className="login-toggle">
          {isRegistering ? '已有账户？' : '还没有账户？'}
          <button
            type="button"
            className="link-button"
            onClick={() => { setIsRegistering(!isRegistering); setError(null) }}
          >
            {isRegistering ? '立即登录' : '创建账户'}
          </button>
        </p>
      </div>
    </div>
  )
}
