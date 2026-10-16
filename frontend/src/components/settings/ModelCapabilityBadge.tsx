import type { ModelCapabilities } from '../../schemas/modelSpec'
import './settings.css'

export interface ModelCapabilityBadgeProps {
  capabilities: ModelCapabilities
}

/** 上下文长度的展示单位（1K/1M），避免界面出现七位数。 */
function formatContextLength(value: number | null | undefined): string {
  if (typeof value !== 'number' || value <= 0) return '未知'
  if (value >= 1_000_000) return `${Math.round(value / 100_000) / 10}M`
  if (value >= 1000) return `${Math.round(value / 1000)}K`
  return String(value)
}

/**
 * 模型能力徽标（2026-09-17 模型管理迁移；迁自源项目 `ModelCapabilities` 展示层）。
 *
 * **纯展示组件**：三项能力与上下文长度全部来自后端下发的 `capabilities`，
 * 前端不做任何推断（MUST-08）——「未知」如实呈现为「未知」，不猜测。
 */
export function ModelCapabilityBadge({ capabilities }: ModelCapabilityBadgeProps) {
  const items: ReadonlyArray<{ label: string; ok: boolean; hint: string }> = [
    {
      label: '工具调用',
      ok: capabilities.supports_tools,
      hint: '该模型可调用函数工具',
    },
    {
      label: '推理',
      ok: capabilities.supports_reasoning,
      hint: '该模型具备推理能力',
    },
  ]

  return (
    <span className="model-cap" aria-label="模型能力">
      {items.map((item) => (
        <span
          key={item.label}
          className={
            item.ok
              ? 'model-cap__badge model-cap__badge--on'
              : 'model-cap__badge model-cap__badge--off'
          }
          title={item.hint}
        >
          {item.label}
        </span>
      ))}
      <span className="model-cap__badge model-cap__badge--info">
        上下文 {formatContextLength(capabilities.max_context_length)}
      </span>
    </span>
  )
}
