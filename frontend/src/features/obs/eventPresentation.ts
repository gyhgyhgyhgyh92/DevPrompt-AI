/**
 * 会话事件的展示派生（2026-11-17 抽取，供 Session Log 视图与桌面运行日志面板共用）。
 *
 * 只读 data 里的展示字段做摘要，不改写事件本身，也不做任何业务判定（MUST-08）。
 */
import type { SessionEvent } from './useSessionEventStream'

/** 一条事件的可读摘要：只读 data 里的展示字段，缺省回退 JSON 片段。 */
export function summaryOf(event: SessionEvent): string {
  const data = event.data
  const pick = (...keys: string[]): string =>
    keys
      .map((key) => data[key])
      .filter((value) => typeof value === 'string' || typeof value === 'number')
      .join(' · ')
  switch (event.type) {
    case 'thought':
      return String(data.text ?? '')
    case 'action':
      return pick('title', 'detail') || pick('detail')
    case 'snapshot':
      return pick('status', 'state')
    case 'stop':
      return pick('status', 'state', 'stop_reason')
    case 'error':
      return pick('message')
    case 'approval.requested':
    case 'approval.resolved':
      return pick('title', 'kind', 'decision')
    case 'clarification.requested':
    case 'clarification.resolved':
      return pick('title', 'kind', 'answer')
    case 'agent.checkpoint':
      return pick('summary', 'stage', 'label')
    default:
      return JSON.stringify(data).slice(0, 200)
  }
}

/** 事件是否失败/中止（纯展示判定，与 Session Log 视图同口径）。 */
export function isFailedEvent(event: SessionEvent): boolean {
  const status = event.data.status
  return event.type === 'error' || status === 'failed' || status === 'aborted'
}

/** run_id 短标签（空 = 无 run）。 */
export function runLabel(runId: string): string {
  return runId === '' ? '—' : runId.slice(0, 8)
}
