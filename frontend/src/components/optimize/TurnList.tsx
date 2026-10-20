import { useEffect, useRef, useState } from 'react'
import type { TurnDetailPayload, TurnSummaryPayload } from '../../api/types'
import { errorMessage } from '../settings/errorMessage'
import './optimize.css'

/** 一次最多铺开的轮次数：超过只渲染最近的，顶部提示省略（避免一次几十个请求）。 */
const MAX_TURNS = 20

interface TurnListProps {
  /** 轮次摘要（升序）；正文进入即并发拉取。 */
  turns: readonly TurnSummaryPayload[]
  /** 懒加载单轮全文（GET /turns/{turn_id}）。 */
  loadTurn: (turnId: string) => Promise<TurnDetailPayload>
}

/**
 * 多轮全文流（2026-10-20）：每轮完整铺开——用户原句靠右成气泡、助手结果靠左成块。
 * 历史轮不渲染思考过程与评分（后端未落库，禁止伪造）；纯展示，不做业务判定（MUST-08）。
 */
export function TurnList({ turns, loadTurn }: TurnListProps) {
  const [details, setDetails] = useState<Record<string, TurnDetailPayload>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const requestedRef = useRef<Set<string>>(new Set())

  const visible = turns.slice(-MAX_TURNS)
  const omitted = turns.length - visible.length

  useEffect(() => {
    const pending = visible.filter((turn) => !requestedRef.current.has(turn.turn_id))
    if (pending.length === 0) return undefined
    let cancelled = false
    for (const turn of pending) requestedRef.current.add(turn.turn_id)

    void Promise.allSettled(
      pending.map(async (turn) => ({ turnId: turn.turn_id, detail: await loadTurn(turn.turn_id) })),
    ).then((results) => {
      if (cancelled) return
      const nextDetails: Record<string, TurnDetailPayload> = {}
      const nextErrors: Record<string, string> = {}
      results.forEach((result, index) => {
        const turnId = pending[index]?.turn_id ?? ''
        if (result.status === 'fulfilled') nextDetails[turnId] = result.value.detail
        else nextErrors[turnId] = errorMessage(result.reason, '轮次加载失败')
      })
      setDetails((prev) => ({ ...prev, ...nextDetails }))
      setErrors((prev) => ({ ...prev, ...nextErrors }))
    })
    return () => {
      cancelled = true
    }
  }, [turns, loadTurn])

  if (turns.length === 0) return null

  return (
    <div className="thread">
      {omitted > 0 ? <p className="thread__omitted">更早 {omitted} 轮已省略</p> : null}
      {visible.map((turn) => {
        const detail = details[turn.turn_id]
        const failure = errors[turn.turn_id]
        return (
          <section className="thread__turn" key={turn.turn_id}>
            <div className="chat-stream__row chat-stream__row--user">
              <div className="chat-user-bubble">{detail?.input ?? turn.conclusion}</div>
            </div>
            <div className="chat-stream__row">
              <article className="chat-reply">
                <header className="chat-reply__head">
                  <span className="chat-reply__brand">DevPrompt AI</span>
                  <span className="thread__round">第 {turn.turn_index + 1} 轮</span>
                </header>

                {failure !== undefined ? <p className="chat-reply__error">{failure}</p> : null}
                {failure === undefined && detail === undefined ? (
                  <p className="thread__loading">加载中…</p>
                ) : null}

                {detail !== undefined ? (
                  <>
                    <p className="chat-reply__message">{detail.conclusion || turn.conclusion}</p>
                    {(detail.variants ?? []).map((variant) => (
                      <div className="thread__variant" key={variant.level}>
                        <p className="thread__variant-title">
                          {variant.title}
                          <span className="thread__level">{variant.level}</span>
                        </p>
                        <p className="thread__variant-body">{variant.body}</p>
                      </div>
                    ))}
                    {(detail.open_items ?? []).length > 0 ? (
                      <p className="thread__open">待确认：{(detail.open_items ?? []).join('；')}</p>
                    ) : null}
                  </>
                ) : null}
              </article>
            </div>
          </section>
        )
      })}
    </div>
  )
}
