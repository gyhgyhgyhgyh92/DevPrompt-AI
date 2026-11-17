import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResponse, FlowSnapshotResponse, HistoryItemPayload } from '../../api/types'
import { useOptimizeStore } from '../../stores/useOptimizeStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { ProjectSidebar } from './ProjectSidebar'

function envelope<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', request_id: 'test-rid', data }
}

function jsonResponse(payload: unknown) {
  return { status: 200, headers: { get: () => null }, json: async () => payload }
}

type Handler = (input: string, method: string) => unknown

function stubFetch(handler: Handler) {
  const mock = vi.fn(async (input: string, init?: RequestInit) =>
    jsonResponse(envelope(handler(input, init?.method ?? 'GET'))),
  )
  vi.stubGlobal('fetch', mock)
  return mock
}

function item(overrides: Partial<HistoryItemPayload> & { session_id: string }): HistoryItemPayload {
  return {
    state: 'DONE',
    project: 'proj-a',
    project_root: '',
    updated_at: '2026-10-12T08:00:00Z',
    title: '会话A',
    pinned: false,
    ...overrides,
  }
}

function snapshot(): FlowSnapshotResponse {
  return {
    session_id: 's1',
    state: 'DONE',
    status: 'done',
    message: '',
    evidence_stale: false,
    reply_text: '',
    questions: [],
    cleared: [],
    variant: null,
  }
}

/** 默认路由：GET /history 返回列表，GET /result 返回快照。 */
function defaultHandler(items: readonly HistoryItemPayload[]): Handler {
  return (input, method) => {
    if (input.includes('/api/v1/result/')) return snapshot()
    if (input.includes('/api/v1/history')) {
      // 列表端点 2026-11-05 起返回分页包装对象（裸数组 → {items, has_more, limit, offset}）
      return method === 'GET' ? { items: [...items], has_more: false, limit: 50, offset: 0 } : null
    }
    return null
  }
}

function renderSidebar(onCollapse: () => void = vi.fn()) {
  return render(
    <MemoryRouter>
      <ProjectSidebar onCollapse={onCollapse} onSelect={vi.fn()} />
    </MemoryRouter>,
  )
}

function itemTitles(): string[] {
  return Array.from(document.querySelectorAll('[class*="project-sidebar__item-title"]')).map(
    (el) => el.textContent ?? '',
  )
}

beforeEach(() => {
  useHistoryStore.getState().reset()
  useOptimizeStore.getState().reset()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ProjectSidebar 分组与结构（Task 4）', () => {
  it('按项目分组渲染：组头（文件夹图标 + 组名）+ 条目 title', async () => {
    stubFetch(
      defaultHandler([
        item({ session_id: 's1', project: 'proj-a', title: '会话A' }),
        item({ session_id: 's2', project: 'proj-b', title: '会话B' }),
      ]),
    )
    renderSidebar()

    expect(await screen.findByText('会话A')).toBeTruthy()
    expect(screen.getByText('proj-a')).toBeTruthy()
    expect(screen.getByText('proj-b')).toBeTruthy()
    expect(document.querySelectorAll('section[class*="project-sidebar__group"]')).toHaveLength(2)
  })

  it('title 为空回退「项目名 · 状态」', async () => {
    stubFetch(
      defaultHandler([item({ session_id: 's1', project: 'proj-a', title: '', state: 'DONE' })]),
    )
    renderSidebar()

    expect(await screen.findByText('proj-a · DONE')).toBeTruthy()
  })

  it('置顶条目排前并带图钉标记', async () => {
    stubFetch(
      defaultHandler([
        item({
          session_id: 's1',
          title: '新会话',
          pinned: false,
          updated_at: '2026-10-12T08:00:00Z',
        }),
        item({
          session_id: 's2',
          title: '旧置顶',
          pinned: true,
          updated_at: '2026-10-01T08:00:00Z',
        }),
      ]),
    )
    renderSidebar()

    await screen.findByText('旧置顶')
    expect(itemTitles()).toEqual(['旧置顶', '新会话'])
    expect(screen.getByLabelText('已置顶')).toBeTruthy()
  })

  it('历史为空时渲染空态文案', async () => {
    stubFetch(defaultHandler([]))
    renderSidebar()

    expect(await screen.findByText('暂无历史会话')).toBeTruthy()
  })

  it('「＋ 新建会话」点击清空会话并回启动态', async () => {
    const user = userEvent.setup()
    stubFetch(defaultHandler([]))
    useOptimizeStore.getState().applySnapshot(snapshot())
    renderSidebar()

    await user.click(screen.getByRole('button', { name: /新建会话/ }))

    expect(useOptimizeStore.getState().sessionId).toBeNull()
  })

  it('选中会话与新建会话都回调 onSelect（窄屏据此自动收起抽屉）', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    stubFetch(defaultHandler([item({ session_id: 's1', title: '会话A' })]))
    render(
      <MemoryRouter>
        <ProjectSidebar onCollapse={vi.fn()} onSelect={onSelect} />
      </MemoryRouter>,
    )

    await user.click(await screen.findByText('会话A'))
    expect(onSelect).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: /新建会话/ }))
    expect(onSelect).toHaveBeenCalledTimes(2)
  })

  it('排序恒为置顶优先 → 时间倒序（无排序图标，2026-10-13 移除）', async () => {
    stubFetch(
      defaultHandler([
        item({
          session_id: 's1',
          title: '较新',
          pinned: false,
          updated_at: '2026-10-12T08:00:00Z',
        }),
        item({
          session_id: 's2',
          title: '置顶较旧',
          pinned: true,
          updated_at: '2026-10-01T08:00:00Z',
        }),
      ]),
    )
    renderSidebar()

    await screen.findByText('置顶较旧')
    expect(itemTitles()).toEqual(['置顶较旧', '较新'])
    expect(screen.queryByRole('button', { name: '排序' })).toBeNull()
    expect(screen.queryByRole('button', { name: '筛选' })).toBeNull()
  })

  it('头部仅保留「项目」+ 一键收纳按钮（图一，原 ⌄/排序/筛选已移除）', async () => {
    const onCollapse = vi.fn()
    stubFetch(defaultHandler([item({ session_id: 's1', title: '会话A' })]))
    renderSidebar(onCollapse)

    await screen.findByText('会话A')
    expect(screen.getByText('项目')).toBeTruthy()
    expect(document.querySelectorAll('[class*="project-sidebar__collapse"]')).toHaveLength(1)

    await userEvent.setup().click(screen.getByRole('button', { name: '收起侧边栏' }))
    expect(onCollapse).toHaveBeenCalledTimes(1)
  })
})

describe('ProjectSidebar 选中与 ⋮ 菜单（Task 5）', () => {
  it('点击条目同步高亮（不等待网络）并经 GET /result 载入结果', async () => {
    const user = userEvent.setup()
    const mock = stubFetch(defaultHandler([item({ session_id: 's1', title: '会话A' })]))
    renderSidebar()

    const row = (await screen.findByText('会话A')).closest('li')
    await user.click(screen.getByText('会话A'))

    expect(row?.className).toContain('project-sidebar__item-row--selected')
    expect(row?.querySelector('[class*="project-sidebar__item-icon"]')).not.toBeNull()
    await waitFor(() => {
      expect(mock.mock.calls.find(([input]) => input.includes('/api/v1/result/s1'))).toBeTruthy()
    })
  })

  it('未选中条目悬停即显示 ⋮，移出隐藏', async () => {
    const user = userEvent.setup()
    stubFetch(defaultHandler([item({ session_id: 's1', title: '会话A' })]))
    renderSidebar()

    await screen.findByText('会话A')
    expect(screen.queryByRole('button', { name: '更多操作' })).toBeNull()

    await user.hover(screen.getByText('会话A'))
    expect(screen.getByRole('button', { name: '更多操作' })).toBeTruthy()
  })

  it('⋮ 展开菜单 4 项', async () => {
    const user = userEvent.setup()
    stubFetch(defaultHandler([item({ session_id: 's1', title: '会话A' })]))
    renderSidebar()

    await screen.findByText('会话A')
    await user.click(screen.getByText('会话A'))
    await user.click(screen.getByRole('button', { name: '更多操作' }))

    expect(screen.getAllByRole('menuitem')).toHaveLength(4)
  })

  it('置顶经 PATCH pinned 持久化并刷新列表', async () => {
    const user = userEvent.setup()
    const mock = stubFetch(
      defaultHandler([item({ session_id: 's1', title: '会话A', pinned: false })]),
    )
    renderSidebar()

    await screen.findByText('会话A')
    await user.click(screen.getByText('会话A'))
    await user.click(screen.getByRole('button', { name: '更多操作' }))
    await user.click(screen.getByRole('menuitem', { name: /置顶任务/ }))

    await waitFor(() => {
      const call = mock.mock.calls.find(
        ([input, init]) => input.includes('/api/v1/history/s1') && init?.method === 'PATCH',
      )
      expect(String(call?.[1]?.body)).toContain('"pinned":true')
    })
  })

  it('重命名行内编辑 Enter 提交 PATCH title', async () => {
    const user = userEvent.setup()
    const mock = stubFetch(defaultHandler([item({ session_id: 's1', title: '会话A' })]))
    renderSidebar()

    await screen.findByText('会话A')
    await user.click(screen.getByText('会话A'))
    await user.click(screen.getByRole('button', { name: '更多操作' }))
    await user.click(screen.getByRole('menuitem', { name: /重命名/ }))

    const input = screen.getByRole('textbox', { name: '重命名会话' })
    await user.clear(input)
    await user.type(input, '新名称{Enter}')

    await waitFor(() => {
      const call = mock.mock.calls.find(
        ([url, init]) => url.includes('/api/v1/history/s1') && init?.method === 'PATCH',
      )
      expect(String(call?.[1]?.body)).toContain('"title":"新名称"')
    })
  })

  it('菜单删除先弹确认，确认后才 DELETE（2026-11-01 统一确认形态）', async () => {
    const user = userEvent.setup()
    const mock = stubFetch(defaultHandler([item({ session_id: 's1', title: '会话A' })]))
    renderSidebar()

    await screen.findByText('会话A')
    await user.click(screen.getByText('会话A'))
    await user.click(screen.getByRole('button', { name: '更多操作' }))
    await user.click(screen.getByRole('menuitem', { name: /删除任务/ }))

    expect(screen.getByRole('dialog', { name: '删除会话' })).toBeTruthy()
    expect(mock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)

    await user.click(screen.getByRole('button', { name: '删除会话' }))

    await waitFor(() => {
      const call = mock.mock.calls.find(
        ([url, init]) => url.includes('/api/v1/history/s1') && init?.method === 'DELETE',
      )
      expect(call).toBeTruthy()
    })
  })

  it('复制项目路径写入剪贴板并提示「已复制」', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    stubFetch(
      defaultHandler([
        item({
          session_id: 's1',
          title: '会话A',
          project: 'proj-a',
          project_root: '/ws/proj-a',
        }),
      ]),
    )
    renderSidebar()

    await screen.findByText('会话A')
    await user.click(screen.getByText('会话A'))
    await user.click(screen.getByRole('button', { name: '更多操作' }))
    await user.click(screen.getByRole('menuitem', { name: /复制项目路径/ }))

    expect(writeText).toHaveBeenCalledWith('/ws/proj-a')
    expect(await screen.findByText('已复制')).toBeTruthy()
  })

  it('project_root 为空时复制回退 basename（旧数据）', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    stubFetch(
      defaultHandler([
        item({ session_id: 's1', title: '会话A', project: 'proj-a', project_root: '' }),
      ]),
    )
    renderSidebar()

    await screen.findByText('会话A')
    await user.click(screen.getByText('会话A'))
    await user.click(screen.getByRole('button', { name: '更多操作' }))
    await user.click(screen.getByRole('menuitem', { name: /复制项目路径/ }))

    expect(writeText).toHaveBeenCalledWith('proj-a')
  })
})

describe('ProjectSidebar 项目级删除（2026-11-01）', () => {
  /** 列表按 project_root 分组；DELETE /history 返回删除条数（契约 ProjectDeleteResponse）。 */
  function projectHandler(items: readonly HistoryItemPayload[], deleted: number): Handler {
    return (input, method) => {
      if (input.includes('/api/v1/history')) {
        if (method === 'DELETE') return { deleted }
        return { items: [...items], has_more: false, limit: 50, offset: 0 }
      }
      return defaultHandler(items)(input, method)
    }
  }

  it('同名不同路径的项目分成两组，各自带删除入口', async () => {
    stubFetch(
      projectHandler(
        [
          item({ session_id: 's1', project: 'app', project_root: 'D:/a/app', title: '会话A' }),
          item({ session_id: 's2', project: 'app', project_root: 'D:/b/app', title: '会话B' }),
        ],
        0,
      ),
    )
    renderSidebar()

    await screen.findByText('会话A')

    expect(document.querySelectorAll('section[class*="project-sidebar__group"]')).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: '删除项目 app' })).toHaveLength(2)
  })

  it('点删除弹确认框并写明不删本地文件；取消不发请求', async () => {
    const user = userEvent.setup()
    const mock = stubFetch(
      projectHandler([item({ session_id: 's1', project: 'app', project_root: 'D:/a/app' })], 1),
    )
    renderSidebar()

    await user.click(await screen.findByRole('button', { name: '删除项目 app' }))

    expect(screen.getByRole('dialog', { name: '删除项目' }).textContent).toContain(
      '不会删除本地项目文件',
    )

    await user.click(screen.getByRole('button', { name: '取消' }))

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(mock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
  })

  it('确认后按 project_root 批量删除并刷新列表', async () => {
    const user = userEvent.setup()
    const mock = stubFetch(
      projectHandler([item({ session_id: 's1', project: 'app', project_root: 'D:/a/app' })], 2),
    )
    renderSidebar()

    await user.click(await screen.findByRole('button', { name: '删除项目 app' }))
    await user.click(screen.getByRole('button', { name: '删除项目' }))

    expect(await screen.findByText('已删除 2 条会话')).toBeTruthy()

    const deleteCall = mock.mock.calls.find(([, init]) => init?.method === 'DELETE')
    expect(String(deleteCall?.[0])).toContain(`project_root=${encodeURIComponent('D:/a/app')}`)
  })

  it('老数据无 project_root 时不提供删除入口（无法精确定位分组）', async () => {
    stubFetch(projectHandler([item({ session_id: 's1', project: 'proj-a', project_root: '' })], 0))
    renderSidebar()

    await screen.findByText('会话A')

    expect(screen.queryByRole('button', { name: /删除项目/ })).toBeNull()
  })
})
