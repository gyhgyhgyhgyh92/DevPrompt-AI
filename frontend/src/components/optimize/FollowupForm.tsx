import { useState } from 'react'
import type { UnknownItemPayload } from '../../api/types'
import './optimize.css'

interface FollowupFormProps {
  /** 未知项清单（契约 questions[]，MUST-26 每项绑定具体未知）。 */
  questions: readonly UnknownItemPayload[]
  /** 已澄清清单（契约 cleared[]）。 */
  cleared: readonly string[]
  /** 快照状态镜像：'guardrail' 时显示软护栏裁决面板（渲染门，MUST-26）。 */
  status: string | null
  /** 提交中禁用一切按钮（MUST-15 禁重试语义）。 */
  isBusy: boolean
  onSubmitAnswers: (answers: Record<string, string>) => void
  /** 逃生：直接生成（escape 模式，MUST-26 用户随时可逃生）。 */
  onEscape: () => void
  /** 软护栏裁决：继续追问 / 直接生成（guardrail_action 模式）。 */
  onGuardrail: (action: 'continue' | 'generate') => void
}

/** 反问表单（F-703/MUST-26）：澄清卡批量答复 + 逃生常驻 + 护栏裁决面板；答复为组件局部草稿。 */
export function FollowupForm({
  questions,
  cleared,
  status,
  isBusy,
  onSubmitAnswers,
  onEscape,
  onGuardrail,
}: FollowupFormProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({})

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
            直接生成
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
            <span className="clarify-card__key">{item.key}</span>
            <p className="clarify-card__reason">{item.reason}</p>
            <p className="clarify-card__guess">
              <span>当前最佳推断：{item.best_guess}</span>
              <button
                type="button"
                className="button button--ghost"
                disabled={isBusy}
                onClick={() => setAnswers((prev) => ({ ...prev, [item.key]: item.best_guess }))}
              >
                采用推断
              </button>
            </p>
            <label className="field">
              <span>答复</span>
              <input
                className="field__input"
                value={answers[item.key] ?? ''}
                onChange={(event) =>
                  setAnswers((prev) => ({ ...prev, [item.key]: event.target.value }))
                }
              />
            </label>
          </li>
        ))}
      </ul>
      <div className="thread__actions">
        <button
          type="button"
          className="button button--primary"
          disabled={isBusy}
          onClick={() => onSubmitAnswers(answers)}
        >
          提交答复
        </button>
        <button
          type="button"
          className="button button--ghost"
          disabled={isBusy}
          onClick={onEscape}
        >
          直接生成（A 保守版 + 待确认清单）
        </button>
      </div>
    </div>
  )
}
