import type { DeliveryGatePayload } from '../../api/types'
import './optimize.css'

interface DeliveryGateCardProps {
  /** 后端给出的门禁结果；null 表示本轮未过门（进行中 / 反问中）。 */
  gate: DeliveryGatePayload | null | undefined
}

/**
 * 交付证据门卡片（2026-11-05 形态层）。
 *
 * **零判定**：色阶用后端给的 `tone`，文案用后端给的 `disclosure`，
 * 前端不把 status 映射成语义、不出现任何阈值（MUST-08 / MUST-33）。
 */
export function DeliveryGateCard({ gate }: DeliveryGateCardProps) {
  if (gate === null || gate === undefined || gate.status === '') return null

  return (
    <div className={`delivery-gate delivery-gate--${gate.tone}`} role="status">
      <span className="delivery-gate__status">{gate.status}</span>
      {gate.disclosure !== '' ? <p className="delivery-gate__text">{gate.disclosure}</p> : null}
    </div>
  )
}
