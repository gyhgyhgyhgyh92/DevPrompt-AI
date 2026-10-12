import { useEffect } from 'react'
import { subscribeProgress } from '../api/endpoints'
import { useOptimizeStore } from '../stores/useOptimizeStore'

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

    const close = subscribeProgress(flowId, {
      onOpen: () => useOptimizeStore.getState().setSseStatus('open'),
      onMessage: (data) => useOptimizeStore.getState().applySseMessage(data),
      onError: () => useOptimizeStore.getState().setSseStatus('error'),
    })
    useOptimizeStore.getState().setSseStatus('connecting')

    return () => {
      close()
      useOptimizeStore.getState().setSseStatus('idle')
    }
  }, [flowId])
}
