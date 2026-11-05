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

const ACTION_LABELS: Record<string, string> = {
  retrieve: '检索目标',
  probe: '研判取证',
  ask: '向你提问',
  generate: '生成方案',
  rank: '打分与推荐',
  deliver: '交付',
  abort: '中止本轮',
}

/** 毫秒转可读时长：1 秒以下保留毫秒，以上保留一位小数秒。 */
export function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

export function AgentTimeline({ step, action, elapsedMs }: AgentTimelineProps) {
  if (step === null && action === null) {
    return null
  }
  const label = action === null ? '决策中' : (ACTION_LABELS[action] ?? action)
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
