import { useEffect, useState } from 'react'
import { getHistory, getPreference, putPreference } from '../../api/endpoints'
import type { PreferenceVectorPayload } from '../../api/types'
import { usePreferenceStore } from '../../stores/usePreferenceStore'
import { formatDateTime } from '../../utils/format'
import { Slider } from '../ui/Slider'
import { errorMessage } from './errorMessage'
import './settings.css'

/** L3 偏好四维（契约 PreferenceVectorPayload）：滑条只传值，取值合法性由后端 clip 兜底。 */
const PREFERENCE_DIMS: ReadonlyArray<{ key: keyof PreferenceVectorPayload; label: string }> = [
  { key: 'detail_level', label: '细节程度' },
  { key: 'include_diff', label: '包含 diff' },
  { key: 'specify_tests', label: '指定测试' },
  { key: 'max_files_norm', label: '涉及文件范围' },
]

/** 长期记忆面板（F-604 记忆标签页）：L3 四维微调 + 采纳/会话历史 + 导出与清空。 */
export function MemoryPanel() {
  const vector = usePreferenceStore((state) => state.vector)
  const history = usePreferenceStore((state) => state.history)
  const setVector = usePreferenceStore((state) => state.setVector)
  const setHistory = usePreferenceStore((state) => state.setHistory)
  const clearLocalHistory = usePreferenceStore((state) => state.clearLocalHistory)
  const [draft, setDraft] = useState<PreferenceVectorPayload | null>(null)
  const [status, setStatus] = useState<{ ok: boolean; text: string }>({ ok: true, text: '' })
  const [isBusy, setIsBusy] = useState(false)
  const [isConfirmingClear, setIsConfirmingClear] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const [nextVector, nextHistory] = await Promise.all([getPreference(), getHistory()])
        if (cancelled) return
        setVector(nextVector)
        setHistory(nextHistory)
      } catch (error) {
        if (!cancelled) setStatus({ ok: false, text: errorMessage(error, '记忆数据加载失败') })
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [setVector, setHistory])

  useEffect(() => {
    if (vector) setDraft(vector)
  }, [vector])

  const patchDraft = (key: keyof PreferenceVectorPayload, value: number) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const submit = async () => {
    if (!draft) return
    setIsBusy(true)
    try {
      const next = await putPreference(draft)
      setVector(next)
      setStatus({ ok: true, text: '偏好已保存' })
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error, '偏好保存失败') })
    } finally {
      setIsBusy(false)
    }
  }

  /** 导出 JSON：前端组装偏好向量 + 历史清单为 Blob 下载，不落任何后端端点。 */
  const exportJson = () => {
    const payload = JSON.stringify(
      { preference: vector, history, exported_at: new Date().toISOString() },
      null,
      2,
    )
    const url = URL.createObjectURL(new Blob([payload], { type: 'application/json' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'devprompt-memory-export.json'
    anchor.click()
    URL.revokeObjectURL(url)
    setStatus({ ok: true, text: '已导出本地 JSON' })
  }

  /** 清空采纳历史（双重确认）：后端暂无清空端点，仅清前端本地留存。 */
  const handleClearHistory = () => {
    if (!isConfirmingClear) {
      setIsConfirmingClear(true)
      return
    }
    clearLocalHistory()
    setIsConfirmingClear(false)
    setStatus({ ok: true, text: '已清空前端本地采纳历史留存' })
  }

  return (
    <section className="settings-panel" aria-label="长期记忆">
      <h3 className="settings-panel__title">长期记忆</h3>
      <p className="settings-panel__desc">
        更新规则：方案采纳后按档位与采纳方式更新四维偏好向量，未采纳维度按衰减系数 0.9 缓慢回落；
        规则由后端记忆层执行，此处仅只读展示。
      </p>
      {PREFERENCE_DIMS.map((dim) => (
        <Slider
          key={dim.key}
          label={dim.label}
          min={0}
          max={1}
          step={0.01}
          value={draft ? draft[dim.key] : 0}
          disabled={!draft || isBusy}
          onChange={(value) => patchDraft(dim.key, value)}
        />
      ))}
      <div className="settings-actions">
        <button
          type="button"
          className="settings-btn settings-btn--primary"
          disabled={!draft || isBusy}
          onClick={submit}
        >
          保存偏好
        </button>
        <button type="button" className="settings-btn" onClick={exportJson}>
          导出 JSON
        </button>
      </div>
      <h4 className="settings-panel__title">采纳与会话历史</h4>
      <table className="settings-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>仓库</th>
            <th>会话</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {history.map((item) => (
            <tr key={item.session_id}>
              <td>{formatDateTime(item.updated_at)}</td>
              <td>{item.project}</td>
              <td>{item.session_id}</td>
              <td>{item.state}</td>
            </tr>
          ))}
          {history.length === 0 ? (
            <tr>
              <td colSpan={4}>暂无记录</td>
            </tr>
          ) : null}
        </tbody>
      </table>
      <div className="settings-actions">
        <button
          type="button"
          className="settings-btn settings-btn--danger"
          onClick={handleClearHistory}
        >
          {isConfirmingClear ? '确认清空？' : '清空采纳历史'}
        </button>
        {isConfirmingClear ? (
          <button
            type="button"
            className="settings-btn"
            onClick={() => setIsConfirmingClear(false)}
          >
            取消
          </button>
        ) : null}
      </div>
      <p className="settings-note">服务端记录保留（清空接口待契约增补）</p>
      {status.text !== '' ? (
        <p
          className={
            status.ok
              ? 'settings-status settings-status--ok'
              : 'settings-status settings-status--error'
          }
        >
          {status.text}
        </p>
      ) : null}
    </section>
  )
}
