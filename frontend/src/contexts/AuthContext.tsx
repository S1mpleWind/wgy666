import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL
  || `${window.location.protocol}//${window.location.hostname}:8000`

export type AuthUser = {
  id: string
  name: string
  email: string
  role: string
  created_at: string
  updated_at: string
}

export type UserConfig = {
  llm_api_base_url: string
  llm_model: string
  llm_api_key_configured: boolean
  github_token_configured: boolean
  github_webhook_secret_configured: boolean
}

export type UserWithConfig = {
  user: AuthUser
  config: UserConfig
}

type AuthState = {
  user: AuthUser | null
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string) => Promise<void>
  logout: () => void
  fetchMyConfig: () => Promise<UserConfig>
  updateMyConfig: (payload: Record<string, unknown>) => Promise<UserConfig>
}

const AuthContext = createContext<AuthState | null>(null)

const TOKEN_KEY = 'issuescope_token'

function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function setStoredToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch { /* ignore */ }
}

async function authFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const token = getStoredToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? `请求失败：${response.status}`)
  }
  return response
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(getStoredToken)
  const [isLoading, setIsLoading] = useState(true)

  // Validate existing token on mount
  useEffect(() => {
    const stored = getStoredToken()
    if (!stored) {
      setIsLoading(false)
      return
    }
    authFetch('/api/auth/me')
      .then(res => res.json())
      .then((data: UserWithConfig) => {
        setUser(data.user)
        setToken(stored)
      })
      .catch(() => {
        setStoredToken(null)
        setToken(null)
        setUser(null)
      })
      .finally(() => setIsLoading(false))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
    })
    if (!response.ok) {
      const error = await response.json().catch(() => null)
      throw new Error(error?.detail ?? '登录失败')
    }
    const data: { access_token: string; user: AuthUser } = await response.json()
    setStoredToken(data.access_token)
    setToken(data.access_token)
    setUser(data.user)
  }, [])

  const register = useCallback(async (name: string, email: string, password: string) => {
    const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), email: email.trim().toLowerCase(), password }),
    })
    if (!response.ok) {
      const error = await response.json().catch(() => null)
      throw new Error(error?.detail ?? '注册失败')
    }
    const data: { access_token: string; user: AuthUser } = await response.json()
    setStoredToken(data.access_token)
    setToken(data.access_token)
    setUser(data.user)
  }, [])

  const logout = useCallback(() => {
    setStoredToken(null)
    setToken(null)
    setUser(null)
  }, [])

  const fetchMyConfig = useCallback(async (): Promise<UserConfig> => {
    const response = await authFetch('/api/users/me/config')
    return response.json()
  }, [])

  const updateMyConfig = useCallback(async (payload: Record<string, unknown>): Promise<UserConfig> => {
    const response = await authFetch('/api/users/me/config', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
    return response.json()
  }, [])

  const value = useMemo<AuthState>(() => ({
    user,
    token,
    isAuthenticated: !!user && !!token,
    isLoading,
    login,
    register,
    logout,
    fetchMyConfig,
    updateMyConfig,
  }), [user, token, isLoading, login, register, logout, fetchMyConfig, updateMyConfig])

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
