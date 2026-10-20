import type { RankingViewPayload, UnknownItemPayload, VariantPayload } from '../../api/types'
import type { ThinkingItem } from '../../schemas/stream'
import { AskFlow } from './AskFlow'
import { ConfidenceNotice } from './ConfidenceNotice'
import { VariantTabs } from './VariantTabs'
import './ChatStream.css'

const PHASES = [
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

/** 状态的中文名与「这一步在做什么」（2026-10-20：前端全中文，过程可读）。 */
const PHASE_META: Record<(typeof PHASES)[number], { label: string; hint: string }> = {
  INIT: { label: '初始化', hint: '建立会话与轮次，核对参数' },
  RETRIEVING: { label: '检索代码', hint: '扫描符号表，候选压到 25 条' },
  PROBING: { label: '研判信息', hint: '七项取证，判断信息是否足够' },
  ASKING: { label: '等待确认', hint: '存在信息缺口，等你回答' },
  CONFIRMING: { label: '整理答复', hint: '重新研判，缺口是否补齐' },
  GENERATING: { label: '生成方案', hint: '一次调用产出 1~3 套方案' },
  RANKING: { label: '评估推荐', hint: '按适配度与偏好打分、标推荐' },
  DONE: { label: '已完成', hint: '结果已产出' },
  ABORTED: { label: '已中止', hint: '异常或连接断开，会话已安全关闭' },
}

interface PhaseLogProps {
  items: readonly ThinkingItem[]
}

/** 某一阶段下方的过程：文字段落 + 真实工具卡片（2026-10-20）。 */
function PhaseLog({ items }: PhaseLogProps) {
  if (items.length === 0) return null
  return (
    <ul className="chat-reply__phase-log">
      {items.map((item) => (
        <li key={item.id}>
          {item.kind === 'text' ? (
            <p className="chat-reply__phase-text">{item.text}</p>
          ) : (
            <div className="chat-reply__phase-card">
              <span className="chat-reply__phase-card-title">{item.title}</span>
              <code className="chat-reply__phase-card-detail">{item.detail}</code>
              {item.scope !== '' ? (
                <span className="chat-reply__phase-card-scope">{item.scope}</span>
              ) : null}
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}

interface ChatStreamProps {
  /** 当前态镜像（后端 9 态字符串）；仅展示不判定（MUST-07）。 */
  state: string
  /** 快照状态镜像（ask / done / guardrail / aborted）。 */
  status: string | null
  /** 会话原句（用户气泡内容；提交时本地记录，恢复的旧会话可能为空）。 */
  sentence: string
  /** 思考过程时间线（带阶段标签，按阶段挂到对应步骤下）。 */
  thinking: readonly ThinkingItem[]
  /** 思考流进行中：正文区暂不渲染反问/结果。 */
  isThinking: boolean
  message: string
  questions: readonly UnknownItemPayload[]
  cleared: readonly string[]
  variants: readonly VariantPayload[]
  ranking: RankingViewPayload | null
  elapsedSeconds: number | null
  errorMessage: string | null
  isBusy: boolean
  onSubmitAnswers: (answers: Record<string, string>) => void
  onEscape: () => void
  onGuardrail: (action: 'continue' | 'generate') => void
}

/**
 * 正式界面对话流（2026-10-20 v2）：
 * 用户气泡 → 回复块（品牌行 + 步骤时间轴（每步下方挂过程）+ 分隔线 + 正文）。
 *
 * 按用户要求移除了目标定位、取证事实、采纳/跳过操作栏与底部图标行——只留可直接发给
 * Agent 的提示词正文。纯展示组件：不做评分/阈值/推荐判定（MUST-08）。
 */
export function ChatStream({
  state,
  status,
  sentence,
  thinking,
  isThinking,
  message,
  questions,
  cleared,
  variants,
  ranking,
  elapsedSeconds,
  errorMessage,
  isBusy,
  onSubmitAnswers,
  onEscape,
  onGuardrail,
}: ChatStreamProps) {
  const isResult = status === 'done' || status === 'aborted'
  const currentIndex = PHASES.findIndex((phase) => phase === state)

  return (
    <div className="chat-stream">
      {sentence.trim() !== '' ? (
        <div className="chat-stream__row chat-stream__row--user">
          <div className="chat-user-bubble">{sentence}</div>
        </div>
      ) : null}

      <article className="chat-reply" aria-label="AI 回复">
        <header className="chat-reply__head">
          <span className="chat-reply__brand">DevPrompt AI</span>
          {elapsedSeconds !== null ? (
            <span className="chat-reply__elapsed">耗时 {elapsedSeconds}s</span>
          ) : null}
        </header>

        <ol className="chat-reply__phases" aria-label="执行过程">
          {PHASES.map((phase, index) => {
            const isDone = index < currentIndex
            const isCurrent = phase === state
            const metaItem = PHASE_META[phase]
            // 无阶段标签的旧数据归到当前阶段，避免过程凭空消失
            const logs = thinking.filter(
              (item) => (item.phase === '' ? state : item.phase) === phase,
            )
            return (
              <li
                key={phase}
                className={
                  isCurrent
                    ? 'chat-reply__phase chat-reply__phase--current'
                    : isDone
                      ? 'chat-reply__phase chat-reply__phase--done'
                      : 'chat-reply__phase'
                }
                aria-current={isCurrent ? 'step' : undefined}
              >
                <div className="chat-reply__phase-head">
                  <span className="chat-reply__phase-mark" aria-hidden="true">
                    {isDone ? '✓' : isCurrent ? '●' : '○'}
                  </span>
                  <span className="chat-reply__phase-label">{metaItem.label}</span>
                  <span className="chat-reply__phase-hint">{metaItem.hint}</span>
                  {isCurrent ? (
                    <span className="chat-reply__phase-tag">
                      {phase === 'DONE' ? '已完成' : phase === 'ABORTED' ? '已中止' : '进行中'}
                    </span>
                  ) : null}
                </div>
                <PhaseLog items={logs} />
              </li>
            )
          })}
        </ol>

        <hr className="chat-reply__divider" />

        <div className="chat-reply__body">
          {errorMessage !== null ? <p className="chat-reply__error">{errorMessage}</p> : null}

          {isThinking ? null : isResult ? (
            <>
              {message !== '' ? <p className="chat-reply__message">{message}</p> : null}
              <ConfidenceNotice ranking={ranking} />
              <VariantTabs variants={variants} ranking={ranking} />
            </>
          ) : (
            <AskFlow
              questions={questions}
              cleared={cleared}
              status={status}
              isBusy={isBusy}
              onSubmitAnswers={onSubmitAnswers}
              onEscape={onEscape}
              onGuardrail={onGuardrail}
            />
          )}
        </div>
      </article>
    </div>
  )
}
