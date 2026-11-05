import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TurnDetailPayload, TurnSummaryPayload } from '../../api/types'
import { i18n } from '../../i18n'
import { useOptimizeStore } from '../../stores/useOptimizeStore'
import { errorMessage } from '../settings/errorMessage'
import { AssistantBlock } from './AssistantBlock'
import { TurnActions } from './TurnActions'
import './optimize.css'

interface TurnListProps {
  /** 轮次摘要（升序）；正文进入即并发拉取。 */
  turns: readonly TurnSummaryPayload[]
  /** 懒加载单轮全文（GET /turns/{turn_id}）。 */
  loadTurn: (turnId: string) => Promise<TurnDetailPayload>
  /** 是否还有更早的轮次（服务端 has_more）。 */
  hasMore: boolean
  /** 加载更早一页（服务端按 offset 从最新往回数）。 */
  onLoadEarlier: () => void
  /** 更早一页加载中（防重复点击）。 */
  loadingEarlier: boolean
  /** 以该轮为基线新开一轮。 */
  onContinueFrom: (turnId: string) => void
  /** 撤销到该轮（物理删除其后轮次；调用方负责确认与截断本地状态）。 */
  onRollbackTo: (turnId: string) => void
}

/**
 * 多轮全文流（2026-10-20）：每轮完整铺开——用户原句靠右成气泡、助手结果靠左成块。
 * 历史轮不渲染思考过程与评分（后端未落库，禁止伪造）；纯展示，不做业务判定（MUST-08）。
 *
 * 2026-11-05 全量对话流：助手块改用 `AssistantBlock`，与当前轮**同构**渲染
 * （动作序列 + 门禁卡片 + 方案卡 + 回答正文），轮级操作条含「以此轮继续」与「撤销到此轮」。
 */
export function TurnList({
  turns,
  loadTurn,
  hasMore,
  onLoadEarlier,
  loadingEarlier,
  onContinueFrom,
  onRollbackTo,
}: TurnListProps) {
  const { t } = useTranslation()
  const turnBodies = useOptimizeStore((s) => s.turnBodies)
  const setTurnBody = useOptimizeStore((s) => s.setTurnBody)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const requestedRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    const pending = turns.filter((turn) => !requestedRef.current.has(turn.turn_id))
    if (pending.length === 0) return undefined
    let cancelled = false
    for (const turn of pending) requestedRef.current.add(turn.turn_id)

    void Promise.allSettled(
      pending.map(async (turn) => ({ turnId: turn.turn_id, detail: await loadTurn(turn.turn_id) })),
    ).then((results) => {
      if (cancelled) return
      const nextErrors: Record<string, string> = {}
      results.forEach((result, index) => {
        const turnId = pending[index]?.turn_id ?? ''
        if (result.status === 'fulfilled') setTurnBody(turnId, result.value.detail)
        else nextErrors[turnId] = errorMessage(result.reason, i18n.t('turn.load_failed'))
      })
      setErrors((prev) => ({ ...prev, ...nextErrors }))
    })
    return () => {
      cancelled = true
    }
  }, [turns, loadTurn, setTurnBody])

  if (turns.length === 0 && !hasMore) return null

  return (
    <div className="thread">
      {hasMore ? (
        <button
          type="button"
          className="thread__more"
          onClick={onLoadEarlier}
          disabled={loadingEarlier}
        >
          {loadingEarlier ? t('turn.loading_earlier') : t('turn.load_earlier')}
        </button>
      ) : null}
      {turns.map((turn) => {
        const detail = turnBodies[turn.turn_id]
        return (
          <section className="thread__turn" key={turn.turn_id}>
            <div className="chat-stream__row chat-stream__row--user">
              <div className="chat-user-bubble">{detail?.input ?? turn.conclusion}</div>
            </div>
            <div className="chat-stream__row">
              <AssistantBlock
                header={<span className="thread__round">第 {turn.turn_index + 1} 轮</span>}
                steps={detail?.steps}
                variants={detail?.variants}
                message={detail?.conclusion || turn.conclusion}
                openItems={detail?.open_items}
                loading={detail === undefined}
                error={errors[turn.turn_id]}
              >
                <TurnActions
                  turnId={turn.turn_id}
                  onContinueFrom={onContinueFrom}
                  onRollbackTo={onRollbackTo}
                />
              </AssistantBlock>
            </div>
          </section>
        )
      })}
    </div>
  )
}
