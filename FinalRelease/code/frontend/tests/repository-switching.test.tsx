import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RepositoryListItem, RepositorySnapshot, WebhookEventItem } from '../src/api'

const apiMocks = vi.hoisted(() => ({
  fetchProjectStructure: vi.fn(),
  fetchRepositoryList: vi.fn(),
  fetchRepositorySnapshot: vi.fn(),
  fetchWebhookEvents: vi.fn(),
}))

vi.mock('../src/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../src/api')>(),
  ...apiMocks,
}))

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, isLoading: false }),
}))

import App from '../src/App'

const repositories: RepositoryListItem[] = [
  {
    owner: 'team',
    name: 'one',
    full_name: 'team/one',
    html_url: 'https://github.com/team/one',
    description: null,
    synced_at: '2026-07-27T00:00:00Z',
    issue_count: 0,
    file_count: 0,
  },
  {
    owner: 'team',
    name: 'two',
    full_name: 'team/two',
    html_url: 'https://github.com/team/two',
    description: null,
    synced_at: '2026-07-27T00:00:00Z',
    issue_count: 0,
    file_count: 0,
  },
]

function snapshot(name: string): RepositorySnapshot {
  return {
    identity: {
      owner: 'team',
      name,
      full_name: `team/${name}`,
      html_url: `https://github.com/team/${name}`,
      default_branch: 'main',
    },
    description: null,
    stats: {
      stars: 0,
      forks: 0,
      watchers: 0,
      open_issues: 0,
      size_kb: 0,
      primary_language: null,
      languages: {},
    },
    topics: [],
    readme: null,
    files: [],
    file_categories: [],
    issues: [],
    issue_categories: [],
    pull_requests: [],
    recent_commits: [],
    source_revision: null,
    synced_at: '2026-07-27T00:00:00Z',
  }
}

async function settleEffects() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('repository switching and polling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    apiMocks.fetchRepositoryList.mockResolvedValue(repositories)
    apiMocks.fetchRepositorySnapshot.mockImplementation(async (_owner: string, name: string) => snapshot(name))
    apiMocks.fetchWebhookEvents.mockResolvedValue([])
    apiMocks.fetchProjectStructure.mockRejectedValue(new Error('not relevant to polling'))
  })

  afterEach(() => {
    cleanup()
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('loads the repository list and initial snapshot only once', async () => {
    render(<App />)
    await settleEffects()

    expect(apiMocks.fetchRepositoryList).toHaveBeenCalledTimes(1)
    expect(apiMocks.fetchRepositorySnapshot).toHaveBeenCalledTimes(1)
    expect(apiMocks.fetchRepositorySnapshot).toHaveBeenCalledWith('team', 'one')
  })

  it('switches once and waits 30 seconds before the next poll', async () => {
    render(<App />)
    await settleEffects()

    apiMocks.fetchRepositorySnapshot.mockClear()
    apiMocks.fetchWebhookEvents.mockClear()

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'team/two' } })
    await settleEffects()

    expect(apiMocks.fetchRepositorySnapshot).toHaveBeenCalledTimes(1)
    expect(apiMocks.fetchRepositorySnapshot).toHaveBeenCalledWith('team', 'two')
    expect(apiMocks.fetchWebhookEvents).toHaveBeenCalledTimes(1)
    expect(apiMocks.fetchWebhookEvents).toHaveBeenLastCalledWith(20, 'team/two')

    await act(async () => vi.advanceTimersByTimeAsync(29_999))
    expect(apiMocks.fetchWebhookEvents).toHaveBeenCalledTimes(1)

    await act(async () => vi.advanceTimersByTimeAsync(1))
    expect(apiMocks.fetchWebhookEvents).toHaveBeenCalledTimes(2)
  })

  it('refreshes a closed issue once without starting an immediate request loop', async () => {
    render(<App />)
    await settleEffects()

    apiMocks.fetchRepositorySnapshot.mockClear()
    apiMocks.fetchWebhookEvents.mockClear()
    apiMocks.fetchWebhookEvents.mockResolvedValue([
      { action: 'closed' } as WebhookEventItem,
    ])

    await act(async () => vi.advanceTimersByTimeAsync(30_000))
    await settleEffects()

    expect(apiMocks.fetchWebhookEvents).toHaveBeenCalledTimes(1)
    expect(apiMocks.fetchRepositorySnapshot).toHaveBeenCalledTimes(1)
    expect(apiMocks.fetchRepositorySnapshot).toHaveBeenCalledWith('team', 'one')

    await act(async () => vi.advanceTimersByTimeAsync(29_999))
    expect(apiMocks.fetchWebhookEvents).toHaveBeenCalledTimes(1)
    expect(apiMocks.fetchRepositorySnapshot).toHaveBeenCalledTimes(1)
  })

  it('does not let a slow response from the old repository undo a switch', async () => {
    render(<App />)
    await settleEffects()

    const oldRefresh = deferred<RepositorySnapshot>()
    apiMocks.fetchRepositorySnapshot.mockImplementation(async (_owner: string, name: string) => {
      if (name === 'one') return oldRefresh.promise
      return snapshot(name)
    })
    apiMocks.fetchWebhookEvents.mockResolvedValue([
      { action: 'closed' } as WebhookEventItem,
    ])

    act(() => vi.advanceTimersByTime(30_000))
    await settleEffects()

    const selector = screen.getByRole('combobox') as HTMLSelectElement
    fireEvent.change(selector, { target: { value: 'team/two' } })
    await settleEffects()
    expect(selector.value).toBe('team/two')

    await act(async () => {
      oldRefresh.resolve(snapshot('one'))
      await oldRefresh.promise
    })
    await settleEffects()

    expect(selector.value).toBe('team/two')
    expect(screen.getByText('team/two', { selector: '.sync-card-heading strong' })).toBeTruthy()
  })
})
