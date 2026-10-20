import { useEffect } from 'react'
import { subscribeProgress } from '../api/endpoints'
import { useOptimizeStore } from '../stores/useOptimizeStore'

/**
 * 后端 `/progress` 在这些状态下主动关流（见 routes.get_progress 的 return 条件）。
 * 收到它们即「流已正常结束」，必须主动 close，否则 EventSource 把流关闭当成
 * 连接失败触发 onerror，界面会显示 `SSE: error`（2026-10-20 实测）。
 */
const TERMINAL_STATUS: ReadonlySet<string> = new Set(['done', 'aborted', 'ask', 'guardrail'])
const TERMINAL_STATE: ReadonlySet<string> = new Set(['DONE', 'ABORTED'])

function isTerminalFrame(raw: string): boolean {
  try {
    const parsed = JSON.parse(raw) as { status?: unknown; state?: unknown }
    const status = typeof parsed.status === 'string' ? parsed.status : ''
    const state = typeof parsed.state === 'string' ? parsed.state : ''
    return TERMINAL_STATUS.has(status) || TERMINAL_STATE.has(state)
  } catch {
    return false
  }
}

/**
 * SSE 订阅（GET /progress/{flow_id}）。
 * MUST-15：close() 写在 effect cleanup；断流即关闭连接、不自动重连，重订由业务层显式决定。
 * 消息解析与状态更新统一在 store 内处理（MUST-16），本 hook 只做连接生命周期编排。
 */
export function useSSE(flowId: string | null): void {
  useEffect(() => {
    if (!flowId) {
      return undefined
    }

    let isFinished = false
    const close = subscribeProgress(flowId, {
      onOpen: () => useOptimizeStore.getState().setSseStatus('open'),
      onMessage: (data) => {
        useOptimizeStore.getState().applySseMessage(data)
        if (isFinished || !isTerminalFrame(data)) return
        // 流程已到终态：主动收尾，避免把「服务端关流」误判为连接错误
        isFinished = true
        close()
        useOptimizeStore.getState().setSseStatus('idle')
      },
      onError: () => {
        if (isFinished) return
        useOptimizeStore.getState().setSseStatus('error')
      },
    })
    useOptimizeStore.getState().setSseStatus('connecting')

    return () => {
      isFinished = true
      close()
      useOptimizeStore.getState().setSseStatus('idle')
    }
  }, [flowId])
}
