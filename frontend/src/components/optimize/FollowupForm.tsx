import type { UnknownItemPayload } from '../../api/types'
import './optimize.css'

/** 多选答案的分隔符：与官方 AskUserQuestion 回填格式一致（`"a, b"` 单字符串）。 */
const MULTI_SEP = ', '

interface FollowupFormProps {
  /** 未知项清单（契约 questions[]，MUST-26 每项绑定具体未知）。 */
  questions: readonly UnknownItemPayload[]
  /** 已澄清清单（契约 cleared[]）。 */
  cleared: readonly string[]
  /** 快照状态镜像：'guardrail' 时显示软护栏裁决面板（渲染门，MUST-26）。 */
  status: string | null
  /** 提交中禁用一切按钮（MUST-15 禁重试语义）。 */
  isBusy: boolean
  /** 受控草稿：由 AskFlow 持有，便于头部统计「已答」。 */
  answers: Record<string, string>
  onAnswersChange: (answers: Record<string, string>) => void
  /** 软护栏裁决：继续追问 / 直接生成（guardrail_action 模式）。 */
  onGuardrail: (action: 'continue' | 'generate') => void
}

/** 选项点击 → 新答案值（单选替换，多选在已选集合里增删）。 */
function toggleChoice(
  item: UnknownItemPayload,
  label: string,
  current: string | undefined,
): string {
  if (!item.multi_select) return label
  const chosen = (current ?? '')
    .split(MULTI_SEP)
    .map((part) => part.trim())
    .filter((part) => part !== '')
  const next = chosen.includes(label) ? chosen.filter((part) => part !== label) : [...chosen, label]
  return next.join(MULTI_SEP)
}

function isChosen(item: UnknownItemPayload, label: string, current: string | undefined): boolean {
  if (current === undefined || current === '') return false
  if (!item.multi_select) return current === label
  return current
    .split(MULTI_SEP)
    .map((part) => part.trim())
    .includes(label)
}

/**
 * 反问表单（F-703/MUST-26）：形态对齐 CodeBuddy SDK 的 AskUserQuestion——
 * header 短标签 + 2~4 个选项（label + description）+ 可选多选 + 自由输入。
 *
 * 只负责「问题区」：外壳（遮罩/固定尺寸/底部按钮）由 AskDialog 提供，草稿由 AskFlow 持有。
 */
export function FollowupForm({
  questions,
  cleared,
  status,
  isBusy,
  answers,
  onAnswersChange,
  onGuardrail,
}: FollowupFormProps) {
  function setAnswer(key: string, value: string): void {
    onAnswersChange({ ...answers, [key]: value })
  }

  return (
    <div>
      {status === 'guardrail' ? (
        <div className="guardrail-banner">
          <p>软护栏触发：已澄清 {cleared.length} 项，请裁决继续追问或直接生成</p>
          <button
            type="button"
            className="button button--ghost"
            disabled={isBusy}
            onClick={() => onGuardrail('continue')}
          >
            继续追问
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={isBusy}
            onClick={() => onGuardrail('generate')}
          >
            直接生成（保守版）
          </button>
        </div>
      ) : null}

      {cleared.length > 0 ? (
        <p className="thread__chips">
          <span>已澄清：</span>
          {cleared.map((key) => (
            <span className="thread__chip" key={key}>
              {key}
            </span>
          ))}
        </p>
      ) : null}

      <ul className="clarify-list">
        {questions.map((item) => (
          <li className="clarify-card" key={item.key}>
            <div className="clarify-card__head">
              {item.header !== '' ? (
                <span className="clarify-card__header">{item.header}</span>
              ) : null}
              <span className="clarify-card__key">{item.key}</span>
              <span className="clarify-card__kind">{item.multi_select ? '多选' : '单选'}</span>
            </div>
            <p className="clarify-card__ask">{item.ask}</p>
            <p className="clarify-card__reason">{item.reason}</p>

            {(item.options ?? []).length > 0 ? (
              <div className="clarify-card__options" role="group" aria-label={item.ask}>
                {(item.options ?? []).map((option) => {
                  const chosen = isChosen(item, option.label, answers[item.key])
                  return (
                    <button
                      type="button"
                      key={option.label}
                      className={
                        chosen ? 'clarify-option clarify-option--chosen' : 'clarify-option'
                      }
                      aria-pressed={chosen}
                      disabled={isBusy}
                      onClick={() =>
                        setAnswer(item.key, toggleChoice(item, option.label, answers[item.key]))
                      }
                    >
                      <span className="clarify-option__mark" aria-hidden="true">
                        {item.multi_select ? (chosen ? '☑' : '☐') : chosen ? '◉' : '○'}
                      </span>
                      <span className="clarify-option__text">
                        <span className="clarify-option__label">{option.label}</span>
                        {option.description !== '' ? (
                          <span className="clarify-option__desc">{option.description}</span>
                        ) : null}
                      </span>
                    </button>
                  )
                })}
              </div>
            ) : null}

            {item.best_guess !== '' ? (
              <p className="clarify-card__guess">
                <span>当前最佳推断：{item.best_guess}</span>
                <button
                  type="button"
                  className="button button--ghost"
                  disabled={isBusy}
                  onClick={() => setAnswer(item.key, item.best_guess)}
                >
                  采用推断
                </button>
              </p>
            ) : null}

            <label className="field">
              <span>{'输入自定义回答'}</span>
              <input
                className="field__input"
                placeholder="输入自定义回答..."
                value={answers[item.key] ?? ''}
                onChange={(event) => setAnswer(item.key, event.target.value)}
              />
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}
