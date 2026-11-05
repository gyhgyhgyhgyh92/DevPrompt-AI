/**
 * agentic 循环进度条（2026-11-04 星型拓扑）。
 *
 * 背景：一次循环可能跑数十秒到数分钟。此前用户只能盯着一条不动的进度条，
 * 无法区分「在推进」与「卡死」。后端在 status === 'running' 时随每次动作推送
 * agent_step / agent_action / agent_elapsed_ms，这里只做展示。
 *
 * MUST-08：本组件不含任何阈值判断或推荐逻辑，动作名到文案的映射是纯展示字典。
 */

interface AgentTimelineProps {
  /** 已执行动作数；null 表示当前不是 agentic 运行态。 */
  step: number | null
  /** 最近一个动作名（后端 AgentAction 值）。 */
  action: string | null
  /** 本轮已耗时毫秒。 */
  elapsedMs: number | null
}

import { useTranslation } from 'react-i18next'

/** 动作名 → 语言包键（纯展示字典；文案在 chat.action.*）。 */
const ACTION_KEYS: Record<string, string> = {
  retrieve: 'chat.action.retrieve',
  probe: 'chat.action.probe',
  ask: 'chat.action.ask',
  generate: 'chat.action.generate',
  rank: 'chat.action.rank',
  deliver: 'chat.action.deliver',
  abort: 'chat.action.abort',
}

/** 毫秒转可读时长：1 秒以下保留毫秒，以上保留一位小数秒。 */
export function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

export function AgentTimeline({ step, action, elapsedMs }: AgentTimelineProps) {
  const { t } = useTranslation()
  if (step === null && action === null) {
    return null
  }
  // 未知动作名原样展示（不吞信息），null 才是「决策中」。
  const actionKey = action === null ? undefined : ACTION_KEYS[action]
  const label =
    action === null ? t('chat.deciding') : actionKey === undefined ? action : t(actionKey)
  return (
    <div
      className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300"
      role="status"
      aria-live="polite"
    >
      <span
        className="inline-block h-2 w-2 animate-pulse rounded-full bg-sky-500"
        aria-hidden="true"
      />
      <span className="font-medium">{label}</span>
      {step !== null && <span className="text-slate-400">第 {step} 步</span>}
      {elapsedMs !== null && (
        <span className="ml-auto tabular-nums text-slate-400">{formatElapsed(elapsedMs)}</span>
      )}
    </div>
  )
}
