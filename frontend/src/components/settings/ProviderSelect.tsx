import { useEffect, useState } from 'react'
import type { ProviderDirectoryEntry } from '../../schemas/settings'

/** 契约侧类型（api/types.ts 由 openapi 生成），比 Zod 推断更贴近服务端实际下发。 */
type ProviderEntry = Omit<
  ProviderDirectoryEntry,
  'supported_api_modes' | 'context_window_tiers' | 'models'
> & {
  supported_api_modes?: string[] | undefined
  /** 上下文窗口档位；契约里可选（老数据无此字段） */
  context_window_tiers?: number[] | undefined
  /** 模型级目录（窗口/档位/思考强度均按模型粒度）；老数据无此字段 */
  models?:
    | ReadonlyArray<{
        model_id: string
        label?: string
        max_context_length?: number | null
        context_window_tiers?: number[]
        reasoning_efforts?: string[]
        default_effort?: string
      }>
    | undefined
}

export interface ProviderSelectProps {
  /** 后端下发的 provider 目录（契约 SettingsResponse.providers）。 */
  providers: ReadonlyArray<ProviderEntry> | undefined
  /** 当前选中的 provider id。 */
  value: string
  onChange: (id: string) => void
  disabled?: boolean
  /** 仅显示当前 provider（新增条目时未选定前的占位）。 */
  placeholder?: string
}

/** 默认占位文案（不预设厂商，用户自选）。 */
const PLACEHOLDER = '选择供应商…'

/**
 * 供应商下拉（2026-09-17 多供应商扩展 W8）。
 *
 * **数据源为后端 provider 目录**，前端不内置第二份厂商清单——厂商清单会随发版过期，
 * 且前端写死一份必然与后端漂移。目录里的 `base_url` 为空表示该厂商官方端点
 * **未登记**（逐个查证不到时如实留空），此时由 Base URL 输入框旁提示用户自填。
 */
export function ProviderSelect({
  providers,
  value,
  onChange,
  disabled,
  placeholder = PLACEHOLDER,
}: ProviderSelectProps) {
  return (
    <select
      className="settings-select"
      value={value}
      disabled={disabled}
      aria-label="供应商"
      onChange={(event) => onChange(event.currentTarget.value)}
    >
      <option value="">{placeholder}</option>
      {(providers ?? []).map((item) => (
        <option key={item.id} value={item.id}>
          {item.label}
          {item.base_url === '' ? '（端点未登记）' : ''}
        </option>
      ))}
    </select>
  )
}

/**
 * 按 id 取 provider 目录条目；找不到返回 undefined。
 *
 * 前端 provider id 与后端 key 同源（都来自目录），故直接查表；
 * 查不到说明条目来自旧数据（后端已按 `resolve_provider_key` 兜底），返回 undefined
 * 让调用方显示「未知供应商」而不是猜一个。
 */
export function findProvider(
  providers: ReadonlyArray<ProviderEntry> | undefined,
  id: string,
): ProviderEntry | undefined {
  if (!providers) return undefined
  const needle = id.trim().toLowerCase().replace(/\s+/g, '')
  if (needle === '') return undefined
  return (
    providers.find((p) => p.id.toLowerCase() === needle) ??
    providers.find((p) => p.id.toLowerCase().includes(needle))
  )
}

/** 上下文窗口的人类可读形式（1K / 1M）；未知返回 null 由调用方决定展示。 */
export function formatWindow(tokens: number | null | undefined): string | null {
  if (typeof tokens !== 'number' || tokens <= 0) return null
  if (tokens >= 1_000_000) return `${Math.round(tokens / 100_000) / 10}M`
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}K`
  return String(tokens)
}

/** 供外部复用的钩子：目录变化时保持选中项有效（条目被删则回落到空）。 */
export function useValidProvider(
  providers: ReadonlyArray<ProviderEntry> | undefined,
  current: string,
): string {
  const [value, setValue] = useState(current)
  useEffect(() => {
    if (current && findProvider(providers, current)) setValue(current)
  }, [providers, current])
  return value
}
