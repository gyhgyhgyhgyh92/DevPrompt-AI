import { useEffect, useState } from 'react'
import { getHealth, putSettings } from '../../api/endpoints'
import type { SettingsResponse, SettingsUpdate } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { errorMessage } from './errorMessage'
import './settings.css'

/**
 * 供应商选项（F-604）：value 即契约 ModelEntryUpdate.provider 取值，
 * baseUrl 仅作切换时的预填；「自定义」不预填，保留用户已有 Base URL。
 */
const PROVIDERS: ReadonlyArray<{ value: string; label: string; baseUrl: string }> = [
  { value: 'DeepSeek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com' },
  { value: 'OpenAI 兼容', label: 'OpenAI 兼容', baseUrl: 'https://api.openai.com/v1' },
  { value: '自定义', label: '自定义', baseUrl: '' },
]

/** GET /health 的 LLM 配置检查位名称（后端检查项标识，非前端判定）。 */
const LLM_CHECK_NAME = 'llm_config'

/** 单条模型草稿（F-604 多模型注册表）：id=null 为尚未保存的新条目；apiKey 空=保留原密钥。 */
interface ModelEntryDraft {
  key: string
  id: string | null
  label: string
  provider: string
  baseUrl: string
  apiKey: string
  masked: string
  modelId: string
}

/** 全局调用参数草稿（不进注册表，仍写 model_service 段）。 */
interface GlobalForm {
  timeout: string
  temperature: string
  maxTokens: string
}

let draftSeq = 0

/** 由后端视图构造草稿：密钥不回填（回显恒脱敏，MUST-19）。 */
function draftsFromSettings(settings: SettingsResponse): ModelEntryDraft[] {
  return settings.models.map((m) => ({
    key: m.id,
    id: m.id,
    label: m.label,
    provider: m.provider,
    baseUrl: m.base_url,
    apiKey: '',
    masked: m.api_key_masked,
    modelId: m.model_id,
  }))
}

function globalFromSettings(settings: SettingsResponse): GlobalForm {
  const s = settings.model_service
  return {
    timeout: String(s.timeout),
    temperature: s.temperature == null ? '' : String(s.temperature),
    maxTokens: s.max_tokens == null ? '' : String(s.max_tokens),
  }
}

/** 数字字段解析：空串 = 保持不变（undefined）；非法输入单独报错而非静默丢弃。 */
function readOptionalNumber(raw: string): { ok: true; value: number | undefined } | { ok: false } {
  const trimmed = raw.trim()
  if (trimmed === '') return { ok: true, value: undefined }
  const value = Number(trimmed)
  return Number.isFinite(value) ? { ok: true, value } : { ok: false }
}

/**
 * 模型服务面板（F-604 模型服务标签页，2026-10-13 改为模型列表管理）：
 * 顶部维护多模型注册表（新增/编辑/删除/设为当前，整表经 PUT /settings 落库）；
 * 底部保留全局调用参数（超时/温度/max_tokens）与「测试连接」。
 */
export function ModelServicePanel() {
  const settings = useSettingsStore((state) => state.settings)
  const setSettings = useSettingsStore((state) => state.setSettings)
  const [drafts, setDrafts] = useState<ModelEntryDraft[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [globalForm, setGlobalForm] = useState<GlobalForm | null>(null)
  const [status, setStatus] = useState<{ ok: boolean; text: string }>({ ok: true, text: '' })
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  useEffect(() => {
    if (!settings) return
    setDrafts(draftsFromSettings(settings))
    setActiveId(settings.models.find((m) => m.is_active)?.id ?? null)
    setGlobalForm(globalFromSettings(settings))
  }, [settings])

  if (!settings || !globalForm) {
    return <p className="settings-note">设置加载中…</p>
  }

  const patchDraft = (key: string, patch: Partial<ModelEntryDraft>) =>
    setDrafts((prev) => prev.map((d) => (d.key === key ? { ...d, ...patch } : d)))

  const addDraft = () => {
    draftSeq += 1
    setDrafts((prev) => [
      ...prev,
      {
        key: `new-${draftSeq}`,
        id: null,
        label: '',
        provider: PROVIDERS[0]?.value ?? '',
        baseUrl: PROVIDERS[0]?.baseUrl ?? '',
        apiKey: '',
        masked: '',
        modelId: '',
      },
    ])
  }

  const removeDraft = (key: string) => {
    setDrafts((prev) => {
      const target = prev.find((d) => d.key === key)
      if (target?.id !== null && target?.id === activeId) setActiveId(null)
      return prev.filter((d) => d.key !== key)
    })
  }

  /** 保存 = PUT /settings：models 整表 + active_model_id + 全局参数；密钥仅在输入新值时回传明文。 */
  const saveForm = async (): Promise<boolean> => {
    const timeout = readOptionalNumber(globalForm.timeout)
    const temperature = readOptionalNumber(globalForm.temperature)
    const maxTokens = readOptionalNumber(globalForm.maxTokens)
    if (!timeout.ok || !temperature.ok || !maxTokens.ok) {
      setStatus({ ok: false, text: '调用参数必须是数字' })
      return false
    }
    if (drafts.some((d) => d.modelId.trim() === '')) {
      setStatus({ ok: false, text: '每个模型条目都必须填写模型 ID' })
      return false
    }
    const models: NonNullable<SettingsUpdate['models']> = drafts.map((d) => ({
      ...(d.id === null ? {} : { id: d.id }),
      label: d.label.trim(),
      provider: d.provider,
      base_url: d.baseUrl.trim(),
      model_id: d.modelId.trim(),
      ...(d.apiKey === '' ? {} : { api_key: d.apiKey }),
    }))
    const model_service: NonNullable<SettingsUpdate['model_service']> = {
      timeout: timeout.value,
      temperature: temperature.value,
      max_tokens: maxTokens.value,
    }
    setIsBusy(true)
    try {
      const next = await putSettings({
        models,
        ...(activeId === null ? {} : { active_model_id: activeId }),
        model_service,
      })
      setSettings(next)
      setStatus({ ok: true, text: '已保存' })
      return true
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error, '保存失败') })
      return false
    } finally {
      setIsBusy(false)
    }
  }

  /** 测试连接（D-6F-2 口径）：先 PUT 保存，再读 GET /health 的 LLM 配置检查位呈现结果。 */
  const testConnection = async () => {
    const saved = await saveForm()
    if (!saved) return
    setIsBusy(true)
    try {
      const health = await getHealth()
      const check = health.checks.find((item) => item.name === LLM_CHECK_NAME)
      setTestResult(
        check
          ? { ok: check.ok, detail: check.detail }
          : { ok: false, detail: '健康检查未包含 LLM 配置检查项，信息不足（待上报 D-6F-2）' },
      )
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error, '健康检查失败') })
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <section className="settings-panel" aria-label="模型服务">
      <h3 className="settings-panel__title">模型服务</h3>
      <p className="settings-panel__desc">
        维护已配置的模型（启动页下拉即列出这些条目）；「设为当前」的条目生效于后续生成调用。
      </p>
      <div className="settings-model-list" aria-label="模型列表">
        {drafts.length === 0 ? (
          <p className="settings-note">尚未配置任何模型，点击「新增模型」开始。</p>
        ) : null}
        {drafts.map((draft) => (
          <div key={draft.key} className="settings-model-row">
            <div className="settings-model-row__head">
              <span className="settings-model-row__title">
                {draft.label.trim() !== '' ? draft.label : draft.modelId || '新模型'}
              </span>
              {draft.id !== null && draft.id === activeId ? (
                <span className="settings-model-badge">当前</span>
              ) : null}
              <span className="settings-model-row__spacer" />
              <button
                type="button"
                className="settings-btn settings-btn--small"
                disabled={draft.id === null || draft.id === activeId}
                title={draft.id === null ? '保存后可设为当前' : undefined}
                onClick={() => draft.id !== null && setActiveId(draft.id)}
              >
                设为当前
              </button>
              <button
                type="button"
                className="settings-btn settings-btn--small settings-btn--danger"
                onClick={() => removeDraft(draft.key)}
              >
                删除
              </button>
            </div>
            <div className="settings-grid">
              <div className="settings-field">
                <label className="settings-label" htmlFor={`${draft.key}-label`}>
                  显示名称
                </label>
                <input
                  id={`${draft.key}-label`}
                  className="settings-input"
                  value={draft.label}
                  placeholder="留空则自动生成（供应商 · 模型 ID）"
                  onChange={(event) => patchDraft(draft.key, { label: event.currentTarget.value })}
                />
              </div>
              <div className="settings-field">
                <label className="settings-label" htmlFor={`${draft.key}-provider`}>
                  供应商
                </label>
                <select
                  id={`${draft.key}-provider`}
                  className="settings-select"
                  value={draft.provider}
                  onChange={(event) => {
                    const value = event.currentTarget.value
                    const preset = PROVIDERS.find((p) => p.value === value)
                    patchDraft(draft.key, {
                      provider: value,
                      ...(preset && preset.baseUrl !== '' ? { baseUrl: preset.baseUrl } : {}),
                    })
                  }}
                >
                  {PROVIDERS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="settings-field">
                <label className="settings-label" htmlFor={`${draft.key}-base-url`}>
                  Base URL
                </label>
                <input
                  id={`${draft.key}-base-url`}
                  className="settings-input"
                  value={draft.baseUrl}
                  onChange={(event) =>
                    patchDraft(draft.key, { baseUrl: event.currentTarget.value })
                  }
                />
              </div>
              <div className="settings-field">
                <label className="settings-label" htmlFor={`${draft.key}-model-id`}>
                  模型 ID
                </label>
                <input
                  id={`${draft.key}-model-id`}
                  className="settings-input"
                  value={draft.modelId}
                  onChange={(event) =>
                    patchDraft(draft.key, { modelId: event.currentTarget.value })
                  }
                />
              </div>
              <div className="settings-field">
                <label className="settings-label" htmlFor={`${draft.key}-api-key`}>
                  API Key
                </label>
                <input
                  id={`${draft.key}-api-key`}
                  className="settings-input"
                  type="password"
                  autoComplete="off"
                  placeholder={draft.masked !== '' ? draft.masked : '未配置'}
                  value={draft.apiKey}
                  onChange={(event) => patchDraft(draft.key, { apiKey: event.currentTarget.value })}
                />
                <span className="settings-hint">
                  当前密钥：{draft.masked !== '' ? draft.masked : '未配置'}
                  （回显恒脱敏；留空则保持不变）
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="settings-actions">
        <button type="button" className="settings-btn" disabled={isBusy} onClick={addDraft}>
          新增模型
        </button>
      </div>

      <h3 className="settings-panel__title">全局调用参数</h3>
      <div className="settings-grid">
        <div className="settings-field">
          <label className="settings-label" htmlFor="settings-timeout">
            超时（秒）
          </label>
          <input
            id="settings-timeout"
            className="settings-input"
            value={globalForm.timeout}
            onChange={(event) =>
              setGlobalForm({ ...globalForm, timeout: event.currentTarget.value })
            }
          />
        </div>
        <div className="settings-field">
          <label className="settings-label" htmlFor="settings-temperature">
            温度
          </label>
          <input
            id="settings-temperature"
            className="settings-input"
            value={globalForm.temperature}
            onChange={(event) =>
              setGlobalForm({ ...globalForm, temperature: event.currentTarget.value })
            }
          />
        </div>
        <div className="settings-field">
          <label className="settings-label" htmlFor="settings-max-tokens">
            max_tokens
          </label>
          <input
            id="settings-max-tokens"
            className="settings-input"
            value={globalForm.maxTokens}
            onChange={(event) =>
              setGlobalForm({ ...globalForm, maxTokens: event.currentTarget.value })
            }
          />
        </div>
      </div>
      <div className="settings-actions">
        <button
          type="button"
          className="settings-btn settings-btn--primary"
          disabled={isBusy}
          onClick={saveForm}
        >
          保存
        </button>
        <button type="button" className="settings-btn" disabled={isBusy} onClick={testConnection}>
          测试连接
        </button>
      </div>
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
      {testResult ? (
        <p
          className={
            testResult.ok
              ? 'settings-status settings-status--ok'
              : 'settings-status settings-status--error'
          }
        >
          {testResult.ok ? 'LLM 配置检查通过' : 'LLM 配置检查未通过'}：{testResult.detail}
        </p>
      ) : null}
    </section>
  )
}
