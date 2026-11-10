import { useTranslation } from 'react-i18next'
import type { ModelCapabilities } from '../../schemas/modelSpec'
import { makeS } from '../../utils/css'
import { formatWindow } from './ProviderSelect'
import styles from './settings.module.css'

const s = makeS(styles)

export interface ModelCapabilityBadgeProps {
  capabilities: ModelCapabilities
}

/**
 * 模型能力徽标（2026-09-17 模型管理迁移；迁自源项目 `ModelCapabilities` 展示层）。
 *
 * **纯展示组件**：三项能力与上下文长度全部来自后端下发的 `capabilities`，
 * 前端不做任何推断（MUST-08）——「未知」如实呈现为「未知」，不猜测。
 */
export function ModelCapabilityBadge({ capabilities }: ModelCapabilityBadgeProps) {
  const { t } = useTranslation()
  const items: ReadonlyArray<{ key: string; label: string; ok: boolean; hint: string }> = [
    {
      key: 'tools',
      label: t('settings.capability.tools'),
      ok: capabilities.supports_tools,
      hint: t('settings.capability.tools_hint'),
    },
    {
      key: 'reasoning',
      label: t('settings.capability.reasoning'),
      ok: capabilities.supports_reasoning,
      hint: t('settings.capability.reasoning_hint'),
    },
  ]

  return (
    <span className={s('model-cap')} aria-label={t('settings.capability.aria')}>
      {items.map((item) => (
        <span
          key={item.key}
          className={s(
            item.ok
              ? 'model-cap__badge model-cap__badge--on'
              : 'model-cap__badge model-cap__badge--off',
          )}
          title={item.hint}
        >
          {item.label}
        </span>
      ))}
      <span className={s('model-cap__badge model-cap__badge--info')}>
        {t('settings.capability.context', {
          length: formatWindow(capabilities.max_context_length) ?? t('settings.capability.unknown'),
        })}
      </span>
    </span>
  )
}
