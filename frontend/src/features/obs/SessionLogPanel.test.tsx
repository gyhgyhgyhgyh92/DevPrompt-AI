import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getHistory, getSessionEvents } from '../../api/endpoints'
import { SessionLogPanel } from './SessionLogPanel'

vi.mock('../../api/endpoints', () => ({
  getHistory: vi.fn(),
  getSessionEvents: vi.fn(),
  openSessionStream: vi.fn(() => () => undefined),
}))

const EVENTS = [
  { seq: 1, type: 'thought', run_id: 'run-1', data: { text: '先看按钮实现' }, ts: 't1' },
  {
    seq: 2,
    type: 'action',
    run_id: 'run-1',
    data: { title: '读取文件', detail: 'src/ui/button.tsx' },
    ts: 't2',
  },
  { seq: 3, type: 'error', run_id: 'run-2', data: { message: '命令失败' }, ts: 't3' },
]

beforeEach(() => {
  vi.mocked(getHistory).mockResolvedValue({
    items: [
      {
        session_id: 's-1',
        state: 'DONE',
        project: 'demo',
        project_root: 'C:/demo',
        updated_at: '2026-11-13T00:00:00Z',
        title: '会话日志',
        pinned: false,
      },
    ],
    has_more: false,
    limit: 50,
    offset: 0,
  })
  vi.mocked(getSessionEvents).mockResolvedValue(EVENTS)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('SessionLogPanel', () => {
  it('按 run 分段渲染事件台账', async () => {
    render(<SessionLogPanel />)

    await waitFor(() => expect(getSessionEvents).toHaveBeenCalledWith('s-1', 1 << 30, 200))
    expect(screen.getByText('run run-1')).toBeTruthy()
    expect(screen.getByText('run run-2')).toBeTruthy()
    expect(screen.getByText('先看按钮实现')).toBeTruthy()
    expect(screen.getByText('读取文件 · src/ui/button.tsx')).toBeTruthy()
  })

  it('类型筛选只保留对应事件', async () => {
    const user = userEvent.setup()
    render(<SessionLogPanel />)
    await waitFor(() => expect(screen.getByText('命令失败')).toBeTruthy())

    await user.click(screen.getByRole('button', { name: 'thought' }))

    expect(screen.getByText('先看按钮实现')).toBeTruthy()
    expect(screen.queryByText('命令失败')).toBeNull()
  })

  it('点击事件展示完整 JSON', async () => {
    const user = userEvent.setup()
    render(<SessionLogPanel />)
    await waitFor(() => expect(screen.getByText('先看按钮实现')).toBeTruthy())

    await user.click(screen.getByText('先看按钮实现'))

    expect(screen.getAllByText(/先看按钮实现/).length).toBeGreaterThan(1)
  })
})
