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
import { makeS } from '../../utils/css'
import styles from './ChatStream.module.css'

const s = makeS(styles)

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
    <div className={s('agent-timeline')} role="status" aria-live="polite">
      <span className={s('agent-timeline__dot')} aria-hidden="true" />
      <span className={s('agent-timeline__label')}>{label}</span>
      {step !== null ? (
        <span className={s('agent-timeline__meta')}>{t('chat.agent_step', { step })}</span>
      ) : null}
      {elapsedMs !== null ? (
        <span className={s('agent-timeline__meta')}>{formatElapsed(elapsedMs)}</span>
      ) : null}
    </div>
  )
}
