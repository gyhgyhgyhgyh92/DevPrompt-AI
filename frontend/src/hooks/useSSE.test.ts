import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { useSSE } from './useSSE'

interface MockMessageEvent {
  data: string
}

class MockEventSource {
  static readonly instances: MockEventSource[] = []
  readonly url: string
  isClosed = false
  onopen: (() => void) | null = null
  onmessage: ((event: MockMessageEvent) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  close(): void {
    this.isClosed = true
  }
}

const snapshotMessage = JSON.stringify({
  session_id: 'sess-1',
  state: 'GENERATING',
  status: 'ask',
  message: '',
})

beforeEach(() => {
  MockEventSource.instances.length = 0
  vi.stubGlobal('EventSource', MockEventSource)
  useOptimizeStore.getState().reset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useSSE 连接生命周期', () => {
  it('flowId 为空时不建连', () => {
    renderHook(() => useSSE(null))

    expect(MockEventSource.instances).toHaveLength(0)
    expect(useOptimizeStore.getState().sseStatus).toBe('idle')
  })

  it('建连后订阅 /api/v1/progress/{flow_id}，open 时置 open 态', () => {
    renderHook(() => useSSE('sess-1'))

    const instance = MockEventSource.instances[0]
    expect(instance?.url).toBe('/api/v1/progress/sess-1')
    expect(useOptimizeStore.getState().sseStatus).toBe('connecting')

    instance?.onopen?.()

    expect(useOptimizeStore.getState().sseStatus).toBe('open')
  })

  it('unmount 后调用 close（MUST-15：close 写在 effect cleanup）', () => {
    const { unmount } = renderHook(() => useSSE('sess-1'))

    unmount()

    expect(MockEventSource.instances[0]?.isClosed).toBe(true)
    expect(useOptimizeStore.getState().sseStatus).toBe('idle')
  })

  it('断流（onerror）即关闭且不自动重连，状态置 error', () => {
    renderHook(() => useSSE('sess-1'))

    MockEventSource.instances[0]?.onerror?.()

    expect(MockEventSource.instances[0]?.isClosed).toBe(true)
    expect(MockEventSource.instances).toHaveLength(1)
    expect(useOptimizeStore.getState().sseStatus).toBe('error')
  })

  it('消息经 store 处理：合法快照更新状态，畸形消息丢弃', () => {
    renderHook(() => useSSE('sess-1'))
    const instance = MockEventSource.instances[0]

    instance?.onmessage?.({ data: snapshotMessage })
    expect(useOptimizeStore.getState().state).toBe('GENERATING')

    instance?.onmessage?.({ data: 'not-json' })
    instance?.onmessage?.({ data: JSON.stringify({ state: 'DONE' }) })
    expect(useOptimizeStore.getState().state).toBe('GENERATING')
  })
})
