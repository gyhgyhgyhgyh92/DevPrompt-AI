import './optimize.css'

interface TurnActionsProps {
  /** 轮次 id（继续时作为基线轮传给后端；撤销时作为保留边界）。 */
  turnId: string
  /** 以该轮为基线新开一轮。 */
  onContinueFrom: (turnId: string) => void
  /** 撤销到该轮：物理删除其后轮次（破坏性操作，此处二次确认）。 */
  onRollbackTo?: (turnId: string) => void
  /** 生成中禁用（避免并发提交）。 */
  disabled?: boolean
}

/**
 * 轮级操作条（2026-11-05 形态层）。
 *
 * - 「以此轮继续」= 以该轮为基线**新开一轮**，历史轮一条不少。
 * - 「撤销到此轮」= **物理删除**其后的轮次（用户裁定，MUST-32 修订：撤销是显式
 *   用户操作，允许删除但必须留痕）。破坏性动作在入口二次确认，文案明示后果。
 */
export function TurnActions({
  turnId,
  onContinueFrom,
  onRollbackTo,
  disabled = false,
}: TurnActionsProps) {
  return (
    <div className="turn-actions">
      <button
        type="button"
        className="turn-actions__btn"
        onClick={() => onContinueFrom(turnId)}
        disabled={disabled}
        title="以这一轮的方案为起点，重新生成一轮"
      >
        以此轮继续
      </button>
      {onRollbackTo !== undefined ? (
        <button
          type="button"
          className="turn-actions__btn turn-actions__btn--danger"
          onClick={() => {
            // 二次确认：物理删除不可恢复。文案同时说明保留范围。
            if (window.confirm('撤销到这一轮？其后的所有轮次将被永久删除，且无法恢复。')) {
              onRollbackTo(turnId)
            }
          }}
          disabled={disabled}
          title="回到这一轮完成时的状态，删除其后的所有轮次"
        >
          撤销到此轮
        </button>
      ) : null}
    </div>
  )
}
