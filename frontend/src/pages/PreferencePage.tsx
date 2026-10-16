import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { getPreference, putPreference } from '../api/endpoints'
import type { PreferenceVectorPayload } from '../api/types'
import { PreferenceEditor } from '../components/preference/PreferenceEditor'
import { usePreferenceStore } from '../stores/usePreferenceStore'
import './PreferencePage.css'

/** toast 显示时长（自研轻量提示）。 */
const TOAST_DURATION_MS = 2000

/**
 * 偏好管理页（F-702 独立可用）：GET /preference 读取 + 四维滑杆编辑 + PUT /preference 保存。
 *
 * 2026-10-16 补全：此前仅只读进度条，编辑必须去设置中心。
 * 现在页面内即可完成「读取 → 调整 → 保存」全链路，**不依赖设置中心**。
 *
 * 边界：仅做「参数收拢 → 调 api → 渲染」，零业务判定（MUST-08/10）；
 * 保存成功以服务端返回向量回填，保证显示与服务端一致；
 * 失败仅提示不自动重试（MUST-15）。
 */
export function PreferencePage() {
  const vector = usePreferenceStore((s) => s.vector)
  const [isLoading, setIsLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(async () => {
    setIsLoading(true)
    setLoadFailed(false)
    try {
      const preference = await getPreference()
      usePreferenceStore.getState().setVector(preference)
    } catch {
      // 读取失败保留空态 + 显式失败提示，不自动重试（MUST-15）
      setLoadFailed(true)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(
    () => () => {
      if (toastTimer.current !== null) clearTimeout(toastTimer.current)
    },
    [],
  )

  function showToast(text: string): void {
    setToast(text)
    if (toastTimer.current !== null) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS)
  }

  async function handleSave(next: PreferenceVectorPayload): Promise<void> {
    setIsSaving(true)
    try {
      const saved = await putPreference(next)
      // 以服务端返回值为准回填（契约返回完整向量），避免本地残留未生效的草稿
      usePreferenceStore.getState().setVector(saved)
      showToast('偏好已保存')
    } catch {
      showToast('保存失败')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <section className="workspace">
      <div className="workspace__thread">
        <div className="preference-page__head">
          <h1>偏好管理</h1>
          <Link to="/">← 工作台</Link>
        </div>

        {isLoading ? <p className="context-panel__empty">加载中…</p> : null}

        {!isLoading && loadFailed ? (
          <div className="preference-page__notice">
            <p className="context-panel__empty">偏好读取失败，请检查服务是否运行。</p>
            <button type="button" className="button" onClick={() => void load()}>
              重新加载
            </button>
          </div>
        ) : null}

        {!isLoading && !loadFailed && vector !== null ? (
          <PreferenceEditor
            value={vector}
            isSaving={isSaving}
            onSave={(next) => void handleSave(next)}
          />
        ) : null}
      </div>

      {toast !== null ? (
        <div className="project-sidebar__toast" role="status">
          {toast}
        </div>
      ) : null}
    </section>
  )
}
