import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAdoptions, getHistory, getPreference, putPreference } from '../../api/endpoints'
import type { HistoryItemPayload, PreferenceVectorPayload } from '../../api/types'
import { usePreferenceStore } from '../../stores/usePreferenceStore'
import { MemoryPanel } from './MemoryPanel'

vi.mock('../../api/endpoints', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  getHealth: vi.fn(),
  getPreference: vi.fn(),
  putPreference: vi.fn(),
  getHistory: vi.fn(),
  clearAdoptions: vi.fn(),
}))

const vectorFixture: PreferenceVectorPayload = {
  detail_level: 0.3,
  include_diff: 0.7,
  specify_tests: 0.2,
  max_files_norm: 0.6,
}

const historyFixture: HistoryItemPayload[] = [
  {
    project: 'demo-repo',
    project_root: '/ws/demo-repo',
    session_id: 'sess-1',
    state: 'DONE',
    title: '会话一',
    pinned: false,
    updated_at: '2026-10-12T10:00:00Z',
  },
  {
    project: 'other-repo',
    project_root: '/ws/other-repo',
    session_id: 'sess-2',
    state: 'ASKING',
    title: '会话二',
    pinned: false,
    updated_at: '2026-10-12T11:00:00Z',
  },
]

beforeEach(() => {
  localStorage.clear()
  usePreferenceStore.setState({ vector: null, history: [] })
  vi.mocked(getPreference).mockResolvedValue(vectorFixture)
  vi.mocked(getHistory).mockResolvedValue(historyFixture)
  vi.mocked(putPreference).mockResolvedValue(vectorFixture)
  vi.mocked(clearAdoptions).mockResolvedValue({ cleared: 3 })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  Reflect.deleteProperty(URL, 'createObjectURL')
  Reflect.deleteProperty(URL, 'revokeObjectURL')
})

describe('MemoryPanel 长期记忆', () => {
  it('挂载拉取偏好与历史并渲染', async () => {
    render(<MemoryPanel />)

    await waitFor(() => expect(getPreference).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(getHistory).toHaveBeenCalledTimes(1))
    expect((screen.getByRole('slider', { name: '细节程度' }) as HTMLInputElement).value).toBe('0.3')
    expect(screen.getByText('demo-repo')).toBeTruthy()
    expect(screen.getByText('sess-2')).toBeTruthy()
  })

  it('滑条调整后保存调用 PUT /preference', async () => {
    const next: PreferenceVectorPayload = { ...vectorFixture, detail_level: 0.6 }
    vi.mocked(putPreference).mockResolvedValue(next)
    render(<MemoryPanel />)
    await waitFor(() => expect(screen.getByRole('slider', { name: '细节程度' })).toBeTruthy())

    fireEvent.change(screen.getByRole('slider', { name: '细节程度' }), { target: { value: '0.6' } })
    fireEvent.click(screen.getByRole('button', { name: '保存偏好' }))

    await waitFor(() => expect(putPreference).toHaveBeenCalledTimes(1))
    expect(vi.mocked(putPreference).mock.calls[0]?.[0]).toMatchObject({ detail_level: 0.6 })
    await waitFor(() => expect(usePreferenceStore.getState().vector).toEqual(next))
  })

  it('导出 JSON 组装 Blob 并触发下载', async () => {
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:mock-url')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', {
      value: createObjectURL,
      configurable: true,
      writable: true,
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: revokeObjectURL,
      configurable: true,
      writable: true,
    })
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined)
    render(<MemoryPanel />)
    await waitFor(() => expect(usePreferenceStore.getState().history.length).toBeGreaterThan(0))

    fireEvent.click(screen.getByRole('button', { name: '导出 JSON' }))

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1))
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
    const blob = createObjectURL.mock.calls[0]?.[0]
    expect(blob).toBeInstanceOf(Blob)
    const payload: unknown = JSON.parse(await blob!.text())
    expect(payload).toMatchObject({ preference: vectorFixture, history: historyFixture })
    clickSpy.mockRestore()
  })

  it('清空采纳历史需二次确认，确认后调 DELETE 清服务端并清本地', async () => {
    localStorage.setItem('devprompt:v1:sessions', '[]')
    localStorage.setItem('devprompt:v1:appearance', '{"theme":"dark"}')
    render(<MemoryPanel />)
    await waitFor(() => expect(usePreferenceStore.getState().history.length).toBeGreaterThan(0))

    fireEvent.click(screen.getByRole('button', { name: '清空采纳历史' }))
    expect(screen.getByRole('button', { name: '确认清空？' })).toBeTruthy()
    expect(clearAdoptions).not.toHaveBeenCalled()
    expect(localStorage.getItem('devprompt:v1:sessions')).toBe('[]')

    fireEvent.click(screen.getByRole('button', { name: '确认清空？' }))

    await waitFor(() => expect(clearAdoptions).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(usePreferenceStore.getState().history).toEqual([]))
    expect(localStorage.getItem('devprompt:v1:sessions')).toBeNull()
    expect(localStorage.getItem('devprompt:v1:appearance')).toBe('{"theme":"dark"}')
    expect(screen.getByText('暂无记录')).toBeTruthy()
    expect(screen.getByText('已清空 3 条')).toBeTruthy()
  })

  it('服务端清空失败时保留本地留存并提示错误', async () => {
    localStorage.setItem('devprompt:v1:sessions', '[]')
    vi.mocked(clearAdoptions).mockRejectedValue(new Error('采纳历史清空被拒绝'))
    render(<MemoryPanel />)
    await waitFor(() => expect(usePreferenceStore.getState().history.length).toBeGreaterThan(0))

    fireEvent.click(screen.getByRole('button', { name: '清空采纳历史' }))
    fireEvent.click(screen.getByRole('button', { name: '确认清空？' }))

    await waitFor(() => expect(screen.getByText('采纳历史清空被拒绝')).toBeTruthy())
    expect(localStorage.getItem('devprompt:v1:sessions')).toBe('[]')
    expect(usePreferenceStore.getState().history).toHaveLength(2)
  })

  it('加载失败只展示后端 message', async () => {
    vi.mocked(getPreference).mockRejectedValue(new Error('偏好服务不可用'))
    render(<MemoryPanel />)

    await waitFor(() => expect(screen.getByText('偏好服务不可用')).toBeTruthy())
  })
})
