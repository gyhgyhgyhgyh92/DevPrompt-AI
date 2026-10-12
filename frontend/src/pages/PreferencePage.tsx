import { useEffect } from 'react'
import { Link } from 'react-router'
import { getPreference } from '../api/endpoints'
import { usePreferenceStore } from '../stores/usePreferenceStore'

/** L3 偏好四维键（后端 PreferenceKey 顺序）；纯展示条，编辑 UI 归设置中心 MemoryPanel。 */
const PREFERENCE_KEYS = ['detail_level', 'include_diff', 'specify_tests', 'max_files_norm'] as const

/** 偏好管理页（F-702）：GET /preference 四维展示骨架。 */
export function PreferencePage() {
  const vector = usePreferenceStore((s) => s.vector)

  useEffect(() => {
    getPreference()
      .then((preference) => usePreferenceStore.getState().setVector(preference))
      .catch(() => {
        // 加载失败保持空态，不重试（MUST-15）
      })
  }, [])

  return (
    <section className="workspace">
      <div className="workspace__thread">
        <h1>偏好管理</h1>
        <Link to="/">← 工作台</Link>
        {vector ? (
          <div>
            {PREFERENCE_KEYS.map((key) => {
              const percent = Math.round(vector[key] * 100)
              return (
                <div className="vector-bar" key={key}>
                  <span className="vector-bar__label">{key}</span>
                  <span className="vector-bar__track">
                    <span className="vector-bar__fill" style={{ inlineSize: `${percent}%` }} />
                  </span>
                  <span className="vector-bar__value">{percent}%</span>
                </div>
              )
            })}
          </div>
        ) : (
          <p className="context-panel__empty">暂无偏好数据</p>
        )}
      </div>
    </section>
  )
}
