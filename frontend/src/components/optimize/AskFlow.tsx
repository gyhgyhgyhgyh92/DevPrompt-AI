import { useState } from 'react'
import type { UnknownItemPayload } from '../../api/types'
import { AskPanel } from './AskPanel'
import { FollowupForm } from './FollowupForm'

interface AskFlowProps {
  questions: readonly UnknownItemPayload[]
  cleared: readonly string[]
  status: string | null
  isBusy: boolean
  onSubmitAnswers: (answers: Record<string, string>) => void
  onEscape: () => void
  onGuardrail: (action: 'continue' | 'generate') => void
}

/**
 * 反问组合层（2026-10-20）：持有作答草稿，把「外壳」与「问题区」拼起来。
 *
 * 草稿放在这里而不是 store：它是弹层内两个子组件共享的临时状态（MUST-16
 * 组件局部状态不上提），上提会污染流程快照。
 */
export function AskFlow({
  questions,
  cleared,
  status,
  isBusy,
  onSubmitAnswers,
  onEscape,
  onGuardrail,
}: AskFlowProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const answered = questions.filter((item) => (answers[item.key] ?? '').trim() !== '').length
  const isGuardrail = status === 'guardrail'
  // 新一批问题到达时重挂载面板，把用户上一轮收起的折叠态复位为展开
  const questionsKey = questions.map((item) => item.key).join('|')

  return (
    <AskPanel
      key={questionsKey}
      total={questions.length}
      answered={answered}
      isBusy={isBusy}
      title={isGuardrail ? `软护栏：已澄清 ${cleared.length} 项，请裁决` : undefined}
      onSubmit={() => onSubmitAnswers(answers)}
      onEscape={onEscape}
    >
      <FollowupForm
        questions={questions}
        cleared={cleared}
        status={status}
        isBusy={isBusy}
        answers={answers}
        onAnswersChange={setAnswers}
        onGuardrail={onGuardrail}
      />
    </AskPanel>
  )
}
