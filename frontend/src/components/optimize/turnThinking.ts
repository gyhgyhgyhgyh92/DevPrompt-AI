/**
 * 阶段行构造（2026-11-15 抽出）：当前轮与历史轮共用同一套「阶段 → 行」映射。
 *
 * 当前轮按实时 state 高亮/收尾；历史轮的事件来自 run_events 重建，没有实时状态，
 * 全部按已完成渲染（isCurrent=false / isDone=true），也没问过就不伪造 ASKING 行。
 */
import type { ThinkingItem } from '../../schemas/stream'
import type { PhaseRow } from './PhaseLedger'

export const PHASES = [
  'INIT',
  'RETRIEVING',
  'PROBING',
  'ASKING',
  'CONFIRMING',
  'GENERATING',
  'DONE',
  'ABORTED',
] as const

export type Phase = (typeof PHASES)[number]

/** 状态的展示键与「这一步在做什么」说明键（文案在语言包，2026-11-06 多语言）。 */
export const PHASE_META: Record<Phase, { labelKey: string; hintKey: string }> = {
  INIT: { labelKey: 'chat.phase.INIT.label', hintKey: 'chat.phase.INIT.hint' },
  RETRIEVING: { labelKey: 'chat.phase.RETRIEVING.label', hintKey: 'chat.phase.RETRIEVING.hint' },
  PROBING: { labelKey: 'chat.phase.PROBING.label', hintKey: 'chat.phase.PROBING.hint' },
  ASKING: { labelKey: 'chat.phase.ASKING.label', hintKey: 'chat.phase.ASKING.hint' },
  CONFIRMING: { labelKey: 'chat.phase.CONFIRMING.label', hintKey: 'chat.phase.CONFIRMING.hint' },
  GENERATING: { labelKey: 'chat.phase.GENERATING.label', hintKey: 'chat.phase.GENERATING.hint' },
  DONE: { labelKey: 'chat.phase.DONE.label', hintKey: 'chat.phase.DONE.hint' },
  ABORTED: { labelKey: 'chat.phase.ABORTED.label', hintKey: 'chat.phase.ABORTED.hint' },
}

type Translate = (key: string, options?: Record<string, unknown>) => string

interface BuildPhaseRowsArgs {
  thinking: readonly ThinkingItem[]
  /** 当前流程状态（历史轮传 'DONE' 即可，仅用于无 phase 旧数据的兜底分组）。 */
  state: string
  translate: Translate
  /** true = 实时轮（高亮当前阶段、按 hadAsk 过滤反问阶段）；false = 历史轮。 */
  isLive: boolean
  /** 本轮是否问过（决定是否渲染 ASKING/CONFIRMING 两行）。 */
  hadAsk: boolean
}

export function buildPhaseRows({
  thinking,
  state,
  translate: t,
  isLive,
  hadAsk,
}: BuildPhaseRowsArgs): PhaseRow[] {
  const visiblePhases = isLive
    ? PHASES.filter((phase) => {
        if (phase === 'ASKING' || phase === 'CONFIRMING') return hadAsk
        if (phase === 'ABORTED') return state === 'ABORTED'
        return true
      })
    : PHASES.filter((phase) => thinking.some((item) => item.phase === phase))
  const currentIndex = isLive ? visiblePhases.findIndex((phase) => phase === state) : -1

  return visiblePhases.map((phase, index) => {
    const isCurrent = isLive && phase === state
    const isDone = isLive ? index < currentIndex : true
    const meta = PHASE_META[phase]
    // 没有缺口时，研判这一步给出「无需补充」的结论文案，而不是暗示存在缺口
    const hint = phase === 'PROBING' && !hadAsk ? t('chat.probe_complete') : t(meta.hintKey)
    // 无阶段标签的旧数据归到当前阶段，避免过程凭空消失
    const logs = thinking.filter((item) => (item.phase === '' ? state : item.phase) === phase)
    const phaseActions = logs.filter((item) => item.kind === 'action').length
    return {
      phase,
      label: t(meta.labelKey),
      hint,
      meta: phaseActions > 0 ? t('chat.action_count', { count: phaseActions }) : '',
      tag: isCurrent
        ? phase === 'DONE'
          ? t('chat.tag_done')
          : phase === 'ABORTED'
            ? t('chat.tag_aborted')
            : t('chat.tag_running')
        : null,
      isCurrent,
      isDone,
      logs,
    }
  })
}
