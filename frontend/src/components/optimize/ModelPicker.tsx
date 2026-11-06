import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { SettingsResponse } from '../../api/types'
import { findProvider, formatWindow } from '../settings/ProviderSelect'
import { Toggle } from '../ui/Toggle'
import './ConsoleInput.css'

/** provider 目录的入参类型直接取 `findProvider` 的签名，避免手抄一份可选性（MUST-17）。 */
type ProviderDirectory = Parameters<typeof findProvider>[0]
type ProviderEntry = NonNullable<ProviderDirectory>[number]
type ModelMetaEntry = NonNullable<ProviderEntry['models']>[number]

/** 单个模型可调的参数（按模型粒度，与后端注册表条目的两个字段一一对应）。 */
export interface ModelTuning {
  reasoning_effort?: string
  max_context_length?: number
}

export interface ModelPickerProps {
  /** 已配置条目（注册表全表）——配置在设置面板完成，这里只做选择与参数微调。 */
  entries: SettingsResponse['models']
  /** provider 目录（静态兜底：模型级登记项 → 厂商级）。 */
  providers?: ProviderDirectory
  /** 当前生效条目 id。 */
  activeId: string
  disabled?: boolean
  /** 切换生效条目（经 PUT /settings 的 active_model_id）。 */
  onSelect: (id: string) => void
  /** 改某条目的按模型参数：思考强度 / 上下文窗口档位。 */
  onTune: (id: string, patch: ModelTuning) => void
}

/** 该模型的可调参数（前端只取不算，MUST-08）。 */
interface TuningMeta {
  maxContextLength: number | null
  tiers: readonly number[]
  efforts: readonly string[]
  /** 官方标注的默认强度；空 = 取第一档 */
  defaultEffort: string
}

/** 首个非空数组（空数组视为「未登记」，让位给下一个候选）。 */
function firstFilled<T>(...values: (readonly T[] | undefined)[]): readonly T[] | undefined {
  return values.find((v) => v !== undefined && v.length > 0)
}

/**
 * 档位数据源两级回落：厂商目录的**模型级登记项**（按官方文档核实过的静态表）
 * → 厂商级。档位与强度必须严格来自官方数据，故无登记时整段不渲染，不编占位值。
 */
function resolveMeta(
  entry: SettingsResponse['models'][number],
  providers: ProviderDirectory,
): TuningMeta {
  const wanted = entry.model_id.trim().toLowerCase()
  const provider = findProvider(providers, entry.provider)
  const registered: ModelMetaEntry | undefined = provider?.models?.find(
    (m) => m.model_id.trim().toLowerCase() === wanted,
  )
  return {
    maxContextLength: registered?.max_context_length ?? provider?.max_context_length ?? null,
    tiers: firstFilled(registered?.context_window_tiers, provider?.context_window_tiers) ?? [],
    efforts: firstFilled(registered?.reasoning_efforts) ?? [],
    defaultEffort: registered?.default_effort ?? '',
  }
}

/** 选中项右侧的对勾（与参考图一致）。 */
function Check() {
  return (
    <span className="model-picker__check" aria-hidden="true">
      ✓
    </span>
  )
}

/**
 * 单个模型的参数面板（hover 弹出）。
 *
 * 三段式与参考图一致：**上下文长度** / **思考模式** 开关 / **思考强度**。
 * 未登记的段整段不渲染——厂商没给的数据宁可空着也不编占位值（MUST-24b）。
 *
 * 联动（2026-10-18）：思考强度**仅在思考模式开启时可点**，关闭即置灰；关闭时
 * 运行时不启用思考模式（后端对空值的语义是「不下发 reasoning 参数」）。
 */
function TuningPanel({
  meta,
  currentWindow,
  currentEffort,
  onPickWindow,
  onToggleMode,
  onPickEffort,
}: {
  meta: TuningMeta
  currentWindow: number | null
  currentEffort: string
  onPickWindow: (tokens: number) => void
  onToggleMode: (on: boolean) => void
  onPickEffort: (effort: string) => void
}) {
  const { t } = useTranslation()
  const windows: readonly number[] =
    meta.tiers.length > 0
      ? meta.tiers
      : meta.maxContextLength === null
        ? []
        : [meta.maxContextLength]
  const hasEfforts = meta.efforts.length > 0
  const modeOn = currentEffort !== ''
  if (windows.length === 0 && !hasEfforts) return null

  return (
    // 面板在模型项内部：点选项不应冒泡到「选中该模型」
    <div className="model-picker__panel" onClick={(event) => event.stopPropagation()}>
      {windows.length > 0 ? (
        <>
          <div className="model-picker__panel-title">{t('model.context_length')}</div>
          <ul className="model-picker__options">
            {windows.map((tokens) => (
              <li key={tokens}>
                <button
                  type="button"
                  className="model-picker__option"
                  aria-pressed={currentWindow === tokens}
                  // 只有一档时禁用：没有可选余地，禁用同时说明原因
                  disabled={windows.length <= 1}
                  onClick={() => onPickWindow(tokens)}
                >
                  <span>{formatWindow(tokens) ?? String(tokens)}</span>
                  {currentWindow === tokens ? <Check /> : null}
                </button>
              </li>
            ))}
          </ul>
          {windows.length <= 1 ? (
            <div className="model-picker__panel-title">{t('model.nominal_only')}</div>
          ) : null}
        </>
      ) : null}
      {hasEfforts ? (
        <>
          <div className="model-picker__panel-title model-picker__panel-title--split">
            <span>{t('model.thinking_mode')}</span>
            <Toggle label={t('model.thinking_mode')} checked={modeOn} onChange={onToggleMode} />
          </div>
          <div className="model-picker__panel-title">{t('model.thinking_effort')}</div>
          <ul className="model-picker__options">
            {meta.efforts.map((effort) => (
              <li key={effort}>
                <button
                  type="button"
                  className="model-picker__option"
                  aria-pressed={currentEffort === effort}
                  disabled={!modeOn}
                  title={modeOn ? undefined : t('model.effort_requires_mode')}
                  onClick={() => onPickEffort(effort)}
                >
                  <span>{effort}</span>
                  {currentEffort === effort ? <Check /> : null}
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  )
}

/**
 * 启动页模型选择器（2026-10-18 改造）。
 *
 * 只列**已配置**条目——配置在设置面板完成（选供应商 → 刷新 → 多选 → 保存）；这里负责
 * 选择生效模型 + 按模型粒度调思考模式/强度与上下文窗口。
 * **hover 某个条目**时从其右侧飞出该模型的参数面板，移开即隐藏。
 */
export function ModelPicker({
  entries,
  providers,
  activeId,
  disabled,
  onSelect,
  onTune,
}: ModelPickerProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const active = entries.find((m) => m.id === activeId) ?? entries[0]

  // 点空白 / Esc 收起；参数面板靠 hover 跟随，移开即消失
  useEffect(() => {
    if (!open) return
    const onDocClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="model-picker" ref={rootRef}>
      <button
        type="button"
        className="console-input__model-select"
        aria-label={t('model.aria_select')}
        aria-haspopup="true"
        aria-expanded={open}
        disabled={disabled || entries.length === 0}
        onClick={() => setOpen((prev) => !prev)}
      >
        {active?.model_id ?? t('model.not_configured')}
      </button>
      {open ? (
        <div className="model-picker__menu">
          {entries.map((entry) => {
            const meta = resolveMeta(entry, providers)
            return (
              <div
                key={entry.id}
                className="model-picker__item"
                onMouseEnter={() => setHoveredId(entry.id)}
                onMouseLeave={() => setHoveredId((prev) => (prev === entry.id ? null : prev))}
              >
                <button
                  type="button"
                  className="model-picker__pick"
                  aria-pressed={entry.id === active?.id}
                  onClick={() => {
                    setOpen(false)
                    setHoveredId(null)
                    onSelect(entry.id)
                  }}
                >
                  <span>{entry.model_id}</span>
                  {entry.id === active?.id ? <Check /> : null}
                </button>
                {hoveredId === entry.id ? (
                  <TuningPanel
                    meta={meta}
                    currentWindow={entry.max_context_length ?? meta.maxContextLength}
                    currentEffort={entry.reasoning_effort ?? ''}
                    onPickWindow={(tokens) => onTune(entry.id, { max_context_length: tokens })}
                    onToggleMode={(on) =>
                      // 开而未选强度：优先取官方标注的默认档（如 DeepSeek 文档写明默认为 high），
                      // 无登记默认值才取厂商列表第一档；都没有则不下发，交由厂商自己决定
                      onTune(entry.id, {
                        reasoning_effort: on
                          ? ((entry.reasoning_effort || meta.defaultEffort || meta.efforts[0]) ??
                            '')
                          : '',
                      })
                    }
                    onPickEffort={(effort) => onTune(entry.id, { reasoning_effort: effort })}
                  />
                ) : null}
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
