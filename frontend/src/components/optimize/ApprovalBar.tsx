import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { answerIntervention } from '../../api/endpoints'
import { useOptimizeStore } from '../../stores/useOptimizeStore'
import styles from './optimize.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

/**
 * MCP 工具审批条（2026-11-21）：后端在等待裁决，超时按拒绝处理。
 * 只做「允许/拒绝」两态——审批不提供自由文本，避免误当成澄清问题回答。
 */
export function ApprovalBar() {
  const { t } = useTranslation()
  const approval = useOptimizeStore((state) => state.pendingApproval)
  const clear = useOptimizeStore((state) => state.clearApproval)
  const [busy, setBusy] = useState(false)

  if (!approval) return null

  async function respond(decision: 'approve' | 'deny'): Promise<void> {
    if (!approval) return
    setBusy(true)
    try {
      await answerIntervention(approval.requestId, decision)
    } catch {
      // 裁决失败（超时/已被其它端处理）只收起本地条，错误由流程帧体现
    } finally {
      setBusy(false)
      clear()
    }
  }

  return (
    <div className={s('approval-bar')} role="alert">
      <span className={s('approval-bar__text')}>
        {t('optimize.approval.prompt', { tool: approval.tool })}
      </span>
      <button
        type="button"
        className={s('approval-bar__btn')}
        disabled={busy}
        onClick={() => void respond('approve')}
      >
        {t('optimize.approval.approve')}
      </button>
      <button
        type="button"
        className={s('approval-bar__btn approval-bar__btn--deny')}
        disabled={busy}
        onClick={() => void respond('deny')}
      >
        {t('optimize.approval.deny')}
      </button>
    </div>
  )
}
