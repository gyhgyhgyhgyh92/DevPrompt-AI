import { useEffect, useState } from 'react'
import type { PreferenceVectorPayload } from '../../api/types'
import { Slider } from '../ui/Slider'
import './PreferenceEditor.css'

/**
 * L3 偏好四维（契约 PreferenceVectorPayload），键序与后端PreferenceKey 一致。
 * 标签沿用设置中心 MemoryPanel 口径，保证同一维度在两处可读名称一致。
 */
const PREFERENCE_DIMS: ReadonlyArray<{ key: keyof PreferenceVectorPayload; label: string }> = [
  { key: 'detail_level', label: '细节程度' },
  { key: 'include_diff', label: '包含 diff' },
  { key: 'specify_tests', label: '指定测试' },
  { key: 'max_files_norm', label: '涉及文件范围' },
]

/** 四维取值域[0,1]（后端归一化范围）；step 为通用步进常量，非业务阈值（MUST-08）。 */
const VALUE_MIN = 0
const VALUE_MAX = 1
const VALUE_STEP = 0.01

export interface PreferenceEditorProps {
  /** 服务端当前生效向量（作为草稿初值与脏判定基准）。 */
  value: PreferenceVectorPayload
  /** 保存回调：父层负责调 PUT /preference 与回填（MUST-16：数据获取不在组件内）。 */
  onSave: (next: PreferenceVectorPayload) => void
  /** 保存进行中：禁用输入与保存按钮，禁重复提交（MUST-15）。 */
  isSaving: boolean
}

/**
 * 偏好向量编辑器（技术栈文档 §2.3 自建组件清单；F-702）。
 *
 * 采用**显式保存按钮**而非拖动即写：PUT 属有副作用端点，
 * 每次拖动触发一次请求既无必要也会放大失败面（MUST-15）。
 *
 * 边界：只做「取值传递 + 保存意图上报」，
 * 不做任何加权、评分或推荐判定——偏好如何影响推荐完全在后端（MUST-08）。
 */
export function PreferenceEditor({ value, onSave, isSaving }: PreferenceEditorProps) {
  const [draft, setDraft] = useState<PreferenceVectorPayload>(value)
  const [savedSnapshot, setSavedSnapshot] = useState<PreferenceVectorPayload>(value)

  // 服务端向量变更（如保存成功回填、父层重新加载）时重置草稿，避免显示陈旧编辑
  useEffect(() => {
    setDraft(value)
    setSavedSnapshot(value)
  }, [value])

  const isDirty = PREFERENCE_DIMS.some((dim) => draft[dim.key] !== savedSnapshot[dim.key])

  function handleChange(key: keyof PreferenceVectorPayload, next: number): void {
    setDraft((current) => ({ ...current, [key]: next }))
  }

  function handleReset(): void {
    setDraft(savedSnapshot)
  }

  return (
    <div className="preference-editor">
      {PREFERENCE_DIMS.map((dim) => (
        <Slider
          key={dim.key}
          label={dim.label}
          value={draft[dim.key]}
          min={VALUE_MIN}
          max={VALUE_MAX}
          step={VALUE_STEP}
          disabled={isSaving}
          onChange={(next) => handleChange(dim.key, next)}
        />
      ))}
      <div className="preference-editor__actions">
        <button
          type="button"
          className="button button--primary"
          disabled={!isDirty || isSaving}
          onClick={() => onSave(draft)}
        >
          {isSaving ? '保存中…' : '保存偏好'}
        </button>
        <button
          type="button"
          className="button button--ghost"
          disabled={!isDirty || isSaving}
          onClick={handleReset}
        >
          放弃修改
        </button>
      </div>
      <p className="preference-editor__note">
        偏好用于加权推荐中的「偏好匹配度」维度（后端计算），此处仅设定输入值。
      </p>
    </div>
  )
}
