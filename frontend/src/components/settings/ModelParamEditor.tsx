import { useEffect, useState } from 'react'
import type { ParameterDefinition, ParameterDefinition as ParamDef } from '../../schemas/modelSpec'
import { Slider } from '../ui/Slider'
import './settings.css'

export interface ModelParamEditorProps {
  /** 该 provider 的参数定义（来自后端 model_specs）。 */
  definitions: ReadonlyArray<ParamDef>
  /** 当前值（来自条目 param_overrides）。 */
  value: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
}

/** 滑条缺省步长：后端未给 step 时用它（步长是控件行为，不是业务阈值）。 */
const FALLBACK_STEP = 0.1

/** 滑条缺省上下界：仅在定义未约束时兜底，避免 range 退化成 0~0。 */
const FALLBACK_MIN = 0
const FALLBACK_MAX = 1

/** 取数值；缺省或类型不符时回退到后端给的 default_value，再退到 min。 */
function toNumber(raw: unknown, def: ParameterDefinition, min: number): number {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  const fallback = def.default_value
  return typeof fallback === 'number' && Number.isFinite(fallback) ? fallback : min
}

/**
 * 单模型参数编辑器（2026-09-17 模型管理迁移）。
 *
 * 严格按后端定义渲染控件：数值/整数 → 滑条、布尔 → 开关、其余 → 输入框。
 * **取值范围、枚举、是否原生下发一律读 `definitions`**——前端不内置第二份真相，
 * 也不做任何评分/推荐判定（MUST-08）。后端给出的错误信息直接展示，不在前端复算校验。
 */
export function ModelParamEditor({ definitions, value, onChange }: ModelParamEditorProps) {
  const [draft, setDraft] = useState<Record<string, unknown>>(value)

  useEffect(() => {
    setDraft(value)
  }, [value])

  const commit = (key: string, next: unknown) => {
    const merged = { ...draft, [key]: next }
    setDraft(merged)
    onChange(merged)
  }

  if (definitions.length === 0) {
    return <p className="settings-hint">该供应商暂无可调参数。</p>
  }

  const renderField = (def: ParameterDefinition) => {
    const inputId = `model-param-${def.name}`
    const label = def.unit !== '' ? `${def.label}（${def.unit}）` : def.label

    if (def.type === 'boolean') {
      return (
        <label key={def.name} className="settings-label" htmlFor={inputId}>
          <input
            id={inputId}
            type="checkbox"
            checked={value[def.name] === true}
            onChange={(event) => commit(def.name, event.currentTarget.checked)}
          />
          {label}
        </label>
      )
    }

    if (def.type === 'number' || def.type === 'integer') {
      const min = def.min_value ?? FALLBACK_MIN
      const max = def.max_value ?? FALLBACK_MAX
      const current = toNumber(value[def.name], def, min)
      return (
        <Slider
          key={def.name}
          label={label}
          value={current}
          min={min}
          max={max}
          step={def.step ?? (def.type === 'integer' ? 1 : FALLBACK_STEP)}
          onChange={(next) => commit(def.name, def.type === 'integer' ? Math.round(next) : next)}
        />
      )
    }

    return (
      <div key={def.name} className="settings-field">
        <label className="settings-label" htmlFor={inputId}>
          {label}
        </label>
        <input
          id={inputId}
          className="settings-input"
          value={typeof value[def.name] === 'string' ? (value[def.name] as string) : ''}
          placeholder={def.default_value == null ? '' : String(def.default_value)}
          onChange={(event) => commit(def.name, event.currentTarget.value)}
        />
        {def.description !== '' ? <span className="settings-hint">{def.description}</span> : null}
      </div>
    )
  }

  return <div className="model-param-editor">{definitions.map(renderField)}</div>
}
