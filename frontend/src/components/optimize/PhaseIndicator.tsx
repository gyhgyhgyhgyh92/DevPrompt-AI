/** 状态机 9 态展示顺序（后端 state.py FlowState 顺序）；仅用于步骤排布，转移逻辑唯一在后端（MUST-07）。 */
const FLOW_STEPS = [
  'INIT',
  'RETRIEVING',
  'PROBING',
  'ASKING',
  'CONFIRMING',
  'GENERATING',
  'RANKING',
  'DONE',
  'ABORTED',
] as const

interface PhaseIndicatorProps {
  /** 当前态镜像（后端 state 字符串），只高亮位置，不做任何转移判定。 */
  state: string
}

export function PhaseIndicator({ state }: PhaseIndicatorProps) {
  const currentIndex = FLOW_STEPS.findIndex((step) => step === state)

  return (
    <ol className="phase-indicator" aria-label="状态机步进器">
      {FLOW_STEPS.map((step, index) => {
        const isCurrent = step === state
        const isDone = index < currentIndex
        const modifier = isCurrent
          ? ' phase-indicator__step--current'
          : isDone
            ? ' phase-indicator__step--done'
            : ' phase-indicator__step--pending'
        return (
          <li
            key={step}
            className={`phase-indicator__step${modifier}`}
            aria-current={isCurrent ? 'step' : undefined}
          >
            {isDone ? `✓ ${step}` : step}
          </li>
        )
      })}
    </ol>
  )
}
