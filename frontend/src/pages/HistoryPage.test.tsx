import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse, HistoryItemPayload } from '../api/types'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { useHistoryStore } from '../stores/useHistoryStore'
import { HistoryPage } from './HistoryPage'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

function item(overrides: Partial<HistoryItemPayload> = {}): HistoryItemPayload {
  return {
    session_id: 'sess-1',
    state: 'DONE',
    project: 'D:/ws/repo',
    project_root: 'D:/ws/repo',
    title: '加个导出按钮',
    pinned: false,
    updated_at: '2026-10-12T08:00:00Z',
    ...overrides,
  }
}

/** 按 URL 尾部路由分派的 fetch 桩：history列表/ 单条写入 / result。 */
function stubFetch(
  handler: (url: string, init?: RequestInit) => { status?: number; data: unknown },
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const { status = 200, data } = handler(url, init)
    // 列表端点 2026-11-05 起返回分页包装对象；桩里统一把裸数组包起来，
    // 免得每个用例都手写四项分页字段。
    const payload =
      isHistoryList(url) && Array.isArray(data)
        ? { items: data, has_more: false, limit: 50, offset: 0 }
        : data
    return {
      status,
      headers: { get: () => null },
      json: async () => envelope(payload),
    }
  })
}

/** 分页列表载荷（2026-11-05：裸数组 → 包装对象）。 */
const listPayload = { items: [item()], has_more: false, limit: 50, offset: 0 }

/** 列表端点判定：分页后 URL 带查询串（?limit=…），单条写入不带。 */
function isHistoryList(url: string): boolean {
  return url.endsWith('/history') || url.includes('/history?')
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useHistoryStore.getState().reset()
  useOptimizeStore.getState().reset()
})

describe('HistoryPage 历史列表', () => {
  it('渲染 GET /history 列表（时间/state/项目名）', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch((url) => (isHistoryList(url) ? { data: listPayload } : { data: null })),
    )

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('DONE')).toBeTruthy()
    expect(screen.getByText('repo')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '历史记录' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '← 工作台' })).toBeTruthy()
  })

  it('列表为空时渲染空态文案', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch((url) => ({ data: isHistoryList(url) ? [] : null })),
    )

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('暂无历史记录')).toBeTruthy()
  })

  it('加载失败时渲染失败提示与手动重载入口（不自动重试）', async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error('network down')
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/历史记录加载失败/)).toBeTruthy()
    // 首轮失败后不得自行再发请求（MUST-15）
    expect(fetchMock).toHaveBeenCalledTimes(1)

    vi.stubGlobal(
      'fetch',
      stubFetch((url) => ({ data: isHistoryList(url) ? listPayload : null })),
    )
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('加个导出按钮')).toBeTruthy()
  })

  it('置顶条目排在未置顶之前，并渲染置顶标记', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch((url) => ({
        data: isHistoryList(url)
          ? [
              item({ session_id: 'a', title: '未置顶条目', updated_at: '2026-10-13T08:00:00Z' }),
              item({ session_id: 'b', title: '置顶条目', pinned: true }),
            ]
          : null,
      })),
    )

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    const titles = await screen.findAllByText(/条目$/)
    expect(titles.map((node) => node.textContent)).toEqual(['置顶条目', '未置顶条目'])
    expect(screen.getByLabelText('已置顶')).toBeTruthy()
  })

  it('打开菜单后可置顶：PATCH 成功后以服务端为准重拉列表', async () => {
    const calls: { url: string; method: string; body: unknown }[] = []
    let pinned = false
    vi.stubGlobal(
      'fetch',
      stubFetch((url, init) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body })
        if (method === 'PATCH') {
          pinned = true
          return { data: null }
        }
        return {
          data: isHistoryList(url) ? [item({ pinned })] : null,
        }
      }),
    )

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    await screen.findByText('加个导出按钮')
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '置顶任务' }))

    await waitFor(() => {
      const patch = calls.find((call) => call.method === 'PATCH')
      expect(patch?.url).toContain('/history/sess-1')
      expect(String(patch?.body)).toContain('"pinned":true')
    })
    expect(await screen.findByText('已置顶')).toBeTruthy()
    // 写操作后必须重拉（服务端权威），而非本地乐观改值
    expect(calls.filter((call) => call.method === 'GET').length).toBeGreaterThanOrEqual(2)
  })

  it('重命名：输入新标题后回车提交 PATCH title', async () => {
    const calls: { method: string; body: unknown }[] = []
    let title = '加个导出按钮'
    vi.stubGlobal(
      'fetch',
      stubFetch((url, init) => {
        const method = init?.method ?? 'GET'
        calls.push({ method, body: init?.body })
        if (method === 'PATCH') {
          title = '导出 CSV'
          return { data: null }
        }
        return { data: isHistoryList(url) ? [item({ title })] : null }
      }),
    )

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    await screen.findByText('加个导出按钮')
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '重命名' }))

    const input = screen.getByLabelText('重命名会话')
    fireEvent.change(input, { target: { value: '导出 CSV' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      const patch = calls.find((call) => call.method === 'PATCH')
      expect(String(patch?.body)).toContain('导出 CSV')
    })
    expect(await screen.findByText('已重命名')).toBeTruthy()
  })

  it('删除需确认弹窗，确认后调 DELETE 并复位主区当前会话', async () => {
    const calls: { url: string; method: string }[] = []
    let exists = true
    vi.stubGlobal(
      'fetch',
      stubFetch((url, init) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (method === 'DELETE') {
          exists = false
          return { data: null }
        }
        return { data: isHistoryList(url) && exists ? [item()] : [] }
      }),
    )
    // 主区正打开该会话
    useOptimizeStore.getState().applySnapshot({
      session_id: 'sess-1',
      state: 'DONE',
      status: 'done',
      message: '',
    } as never)

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    await screen.findByText('加个导出按钮')
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '删除任务' }))

    // 未确认前不得发出 DELETE
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: '删除会话' }))

    await waitFor(() => {
      expect(calls.some((call) => call.method === 'DELETE')).toBe(true)
    })
    expect(await screen.findByText('已删除')).toBeTruthy()
    expect(useOptimizeStore.getState().sessionId).toBeNull()
    expect(await screen.findByText('暂无历史记录')).toBeTruthy()
  })

  it('写操作失败时给出提示且不自动重试', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'PATCH') throw new Error('rejected')
      return {
        status: 200,
        headers: { get: () => null },
        json: async () =>
          envelope(
            isHistoryList(url) ? { items: [item()], has_more: false, limit: 50, offset: 0 } : null,
          ),
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    await screen.findByText('加个导出按钮')
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '置顶任务' }))

    expect(await screen.findByText('置顶操作失败')).toBeTruthy()
    // 失败后不得自行重发有副作用请求（MUST-15）
    const patchCalls = fetchMock.mock.calls.filter((call) => (call[1]?.method ?? 'GET') === 'PATCH')
    expect(patchCalls).toHaveLength(1)
  })

  it('点击「打开」载入会话结果到主区（GET /result）', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      stubFetch((url) => {
        calls.push(url)
        if (url.includes('/result/')) {
          return {
            data: { session_id: 'sess-1', state: 'DONE', status: 'done', message: '' },
          }
        }
        return { data: isHistoryList(url) ? [item()] : null }
      }),
    )

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    )

    await screen.findByText('加个导出按钮')
    fireEvent.click(screen.getByRole('button', { name: '打开' }))

    await waitFor(() => {
      expect(calls.some((url) => url.includes('/result/sess-1'))).toBe(true)
    })
    expect(useOptimizeStore.getState().sessionId).toBe('sess-1')
  })
})
