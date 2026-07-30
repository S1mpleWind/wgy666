import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  deleteUser: vi.fn(),
  fetchIntegrationStatus: vi.fn(),
  fetchUsageStats: vi.fn(),
  fetchUserConfig: vi.fn(),
  fetchUsers: vi.fn(),
  updateUser: vi.fn(),
  updateUserConfig: vi.fn(),
}))

const authMock = vi.hoisted(() => ({
  user: { id: 'user-1', name: 'Tester', email: 'tester@example.com', role: 'user' },
  logout: vi.fn(),
}))

vi.mock('../src/api', () => apiMocks)

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => authMock,
}))

import { UserManagement } from '../src/components/UserManagement'

describe('integration status and usage panel', () => {
  beforeEach(() => {
    authMock.user.role = 'user'
    apiMocks.fetchUserConfig.mockResolvedValue({
      llm_api_base_url: 'https://llm.example/v1',
      llm_model: 'test-model',
      llm_api_key_configured: true,
      github_token_configured: true,
      github_webhook_secret_configured: true,
    })
    apiMocks.fetchIntegrationStatus.mockResolvedValue({
      llm: { status: 'connected', message: 'API 可访问', checked_at: '2026-07-28T00:00:00Z', last_received_at: null },
      github: { status: 'connected', message: '已连接 GitHub：octocat', checked_at: '2026-07-28T00:00:00Z', last_received_at: null },
      webhook: { status: 'configured', message: 'Secret 已配置，尚未收到 GitHub Webhook。', checked_at: '2026-07-28T00:00:00Z', last_received_at: null },
    })
    apiMocks.fetchUsageStats.mockResolvedValue({
      llm_requests: 12,
      github_requests: 34,
      prompt_tokens: 1200,
      completion_tokens: 300,
      total_tokens: 1500,
      updated_at: '2026-07-28T00:00:00Z',
    })
    apiMocks.fetchUsers.mockResolvedValue([])
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('shows live integration states and accumulated usage', async () => {
    render(<UserManagement />)

    expect(await screen.findByText('API 可访问')).toBeTruthy()
    expect(screen.getByText('已连接 GitHub：octocat')).toBeTruthy()
    expect(screen.queryByText('Secret 已配置，尚未收到 GitHub Webhook。')).toBeNull()
    expect(screen.queryByText('Webhook Secret')).toBeNull()
    expect(screen.getByText('1,500')).toBeTruthy()
    expect(screen.getByText('34')).toBeTruthy()
    expect(apiMocks.fetchIntegrationStatus).toHaveBeenCalledTimes(1)
    expect(apiMocks.fetchUsageStats).toHaveBeenCalledTimes(1)
  })

  it('keeps unconfigured user fields blank and shows features as unavailable', async () => {
    apiMocks.fetchUserConfig.mockResolvedValue({
      llm_api_base_url: '',
      llm_model: '',
      llm_api_key_configured: false,
      github_token_configured: false,
      github_webhook_secret_configured: false,
    })
    apiMocks.fetchIntegrationStatus.mockResolvedValue({
      llm: { status: 'not_configured', message: '请配置完整的 API 地址、模型和 API Key。', checked_at: '2026-07-28T00:00:00Z', last_received_at: null },
      github: { status: 'not_configured', message: '尚未配置 GitHub Token。', checked_at: '2026-07-28T00:00:00Z', last_received_at: null },
      webhook: { status: 'not_configured', message: '尚未配置 Webhook Secret。', checked_at: '2026-07-28T00:00:00Z', last_received_at: null },
    })

    render(<UserManagement />)

    expect(await screen.findByText('请配置完整的 API 地址、模型和 API Key。')).toBeTruthy()
    expect((screen.getByPlaceholderText('https://api.example.com/v1') as HTMLInputElement).value).toBe('')
    expect((screen.getByPlaceholderText('模型名称') as HTMLInputElement).value).toBe('')
    expect(screen.getAllByText('未配置').length).toBeGreaterThanOrEqual(2)
  })

  it('labels administrator user actions with visible edit and delete text', async () => {
    authMock.user.role = 'admin'
    apiMocks.fetchUsers.mockResolvedValue([{
      id: 'user-2',
      name: 'Member',
      email: 'member@example.com',
      role: 'user',
      created_at: '2026-07-28T00:00:00Z',
      updated_at: '2026-07-28T00:00:00Z',
    }])

    render(<UserManagement />)

    const editButton = await screen.findByRole('button', { name: '编辑' })
    expect(editButton).toBeTruthy()
    expect(screen.getByRole('button', { name: '删除' })).toBeTruthy()
    expect(screen.getByRole('columnheader', { name: '操作' })).toBeTruthy()

    fireEvent.click(editButton)
    expect(screen.getByRole('button', { name: '取消编辑' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '保存编辑' })).toBeTruthy()
  })
})
