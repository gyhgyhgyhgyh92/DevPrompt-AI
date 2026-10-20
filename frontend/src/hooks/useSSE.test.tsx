import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SseHandlers } from '../api/client'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { useSSE } from './useSSE'

const handlersRef: { current: SseHandlers | null } = { current: null }
const closeSpy = vi.fn()

vi.mock('../api/endpoints', () => ({
  subscribeProgress: (_flowId: string, handlers: SseHandlers) => {
    handlersRef.current = handlers
    return closeSpy
  },
}))

function snapshot(overrides: Record<string, unknown>): string {
  return JSON.stringify({
    session_id: 's1',
    state: 'DONE',
    status: 'done',
    message: '',
    questions: [],
    cleared: [],
    variants: [],
    ranking: null,
    ...overrides,
  })
}

beforeEach(() => {
  closeSpy.mockClear()
  handlersRef.current = null
  useOptimizeStore.getState().reset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('useSSE 生命周期', () => {
  it('收到终态帧主动关闭，不把「服务端关流」误标为 error', () => {
    renderHook(() => useSSE('s1'))
    act(() => handlersRef.current?.onOpen?.())
    expect(useOptimizeStore.getState().sseStatus).toBe('open')

    act(() => handlersRef.current?.onMessage?.(snapshot({})))
    expect(closeSpy).toHaveBeenCalledTimes(1)
    expect(useOptimizeStore.getState().sseStatus).toBe('idle')

    // 关闭后 EventSource 仍可能补一次 onerror：不得再翻成 error
    act(() => handlersRef.current?.onError?.())
    expect(useOptimizeStore.getState().sseStatus).toBe('idle')
  })

  it('ask / guardrail 也算终态（后端在这两个状态下关流）', () => {
    renderHook(() => useSSE('s1'))
    act(() => handlersRef.current?.onMessage?.(snapshot({ state: 'ASKING', status: 'ask' })))
    expect(closeSpy).toHaveBeenCalledTimes(1)
    expect(useOptimizeStore.getState().sseStatus).toBe('idle')
  })

  it('非终态帧不关闭连接', () => {
    renderHook(() => useSSE('s1'))
    act(() => handlersRef.current?.onOpen?.())
    act(() => handlersRef.current?.onMessage?.('not-json'))

    expect(closeSpy).not.toHaveBeenCalled()
    expect(useOptimizeStore.getState().sseStatus).toBe('open')
  })

  it('未收到终态就报错 → 标记 error', () => {
    renderHook(() => useSSE('s1'))
    act(() => handlersRef.current?.onOpen?.())
    act(() => handlersRef.current?.onError?.())

    expect(useOptimizeStore.getState().sseStatus).toBe('error')
  })

  it('flowId 为空时不订阅', () => {
    renderHook(() => useSSE(null))
    expect(handlersRef.current).toBeNull()
    expect(useOptimizeStore.getState().sseStatus).toBe('idle')
  })
})
