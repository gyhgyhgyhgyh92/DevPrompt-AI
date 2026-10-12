import { useEffect, useState } from 'react'
import { getHealth, putSettings } from '../../api/endpoints'
import type { SettingsResponse, SettingsUpdate } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { errorMessage } from './errorMessage'
import './settings.css'

/** 决策层取值（契约 ModelServiceSettings.decider）。 */
type Decider = SettingsResponse['model_service']['decider']

/**
 * 供应商分段（F-604）：value 即契约 ModelServiceSettings.provider 取值（双向绑定），
 * baseUrl 仅作切换分段时的预填；「自定义」不预填，保留用户已有 Base URL。
 */
const PROVIDERS: ReadonlyArray<{ value: string; label: string; baseUrl: string }> = [
  { value: 'DeepSeek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com' },
  { value: 'OpenAI 兼容', label: 'OpenAI 兼容', baseUrl: 'https://api.openai.com/v1' },
  { value: '自定义', label: '自定义', baseUrl: '' },
]

/** GET /health 的 LLM 配置检查位名称（后端检查项标识，非前端判定）。 */
const LLM_CHECK_NAME = 'llm_config'

interface ModelServiceForm {
  baseUrl: string
  apiKey: string
  modelId: string
  provider: string
  decider: Decider
  timeout: string
  temperature: string
  maxTokens: string
}

interface TestResultView {
  ok: boolean
  detail: string
}

/** 用后端视图初始化表单：密钥不回填（回显恒脱敏，MUST-19），调用参数空=不变。 */
function formFromSettings(settings: SettingsResponse): ModelServiceForm {
  const service = settings.model_service
  return {
    baseUrl: service.base_url,
    apiKey: '',
    modelId: service.model_id,
    provider: service.provider,
    decider: service.decider,
    timeout: String(service.timeout),
    temperature: service.temperature == null ? '' : String(service.temperature),
    maxTokens: service.max_tokens == null ? '' : String(service.max_tokens),
  }
}

/** 数字字段解析：空串 = 保持不变（undefined）；非法输入单独报错而非静默丢弃。 */
function readOptionalNumber(raw: string): { ok: true; value: number | undefined } | { ok: false } {
  const trimmed = raw.trim()
  if (trimmed === '') return { ok: true, value: undefined }
  const value = Number(trimmed)
  return Number.isFinite(value) ? { ok: true, value } : { ok: false }
}

/** 模型服务面板（F-604 模型服务标签页）：GET/PUT /settings 模型段 + 测试连接。 */
export function ModelServicePanel() {
  const settings = useSettingsStore((state) => state.settings)
  const setSettings = useSettingsStore((state) => state.setSettings)
  const [form, setForm] = useState<ModelServiceForm | null>(null)
  const [status, setStatus] = useState<{ ok: boolean; text: string }>({ ok: true, text: '' })
  const [testResult, setTestResult] = useState<TestResultView | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  useEffect(() => {
    if (settings) setForm(formFromSettings(settings))
  }, [settings])

  if (!settings || !form) {
    return <p className="settings-note">设置加载中…</p>
  }

  const maskedKey =
    settings.model_service.api_key_masked !== '' ? settings.model_service.api_key_masked : '未配置'
  // 分段高亮直接取 provider（双向绑定）；未匹配到已知分段时不高亮，不替用户猜测
  const activeProvider = form.provider

  const patchForm = (patch: Partial<ModelServiceForm>) =>
    setForm((prev) => (prev ? { ...prev, ...patch } : prev))

  /** 保存 = PUT /settings 模型段；api_key 仅在用户输入新值时回传明文（空 = 不变）。 */
  const saveForm = async (): Promise<boolean> => {
    const timeout = readOptionalNumber(form.timeout)
    const temperature = readOptionalNumber(form.temperature)
    const maxTokens = readOptionalNumber(form.maxTokens)
    if (!timeout.ok || !temperature.ok || !maxTokens.ok) {
      setStatus({ ok: false, text: '调用参数必须是数字' })
      return false
    }
    const model_service: NonNullable<SettingsUpdate['model_service']> = {
      base_url: form.baseUrl.trim(),
      model_id: form.modelId.trim(),
      provider: form.provider,
      decider: form.decider,
      timeout: timeout.value,
      temperature: temperature.value,
      max_tokens: maxTokens.value,
      api_key: form.apiKey === '' ? undefined : form.apiKey,
    }
    setIsBusy(true)
    try {
      const next = await putSettings({ model_service })
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
      <div className="settings-field">
        <span className="settings-label">供应商</span>
        <div className="settings-segment" role="group" aria-label="供应商">
          {PROVIDERS.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={activeProvider === item.value}
              className={
                activeProvider === item.value
                  ? 'settings-segment__item settings-segment__item--active'
                  : 'settings-segment__item'
              }
              onClick={() =>
                patchForm({
                  provider: item.value,
                  ...(item.baseUrl === '' ? {} : { baseUrl: item.baseUrl }),
                })
              }
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      <div className="settings-field">
        <label className="settings-label" htmlFor="settings-base-url">
          Base URL
        </label>
        <input
          id="settings-base-url"
          className="settings-input"
          value={form.baseUrl}
          onChange={(event) => patchForm({ baseUrl: event.currentTarget.value })}
        />
      </div>
      <div className="settings-field">
        <label className="settings-label" htmlFor="settings-api-key">
          API Key
        </label>
        <input
          id="settings-api-key"
          className="settings-input"
          type="password"
          autoComplete="off"
          placeholder={maskedKey}
          value={form.apiKey}
          onChange={(event) => patchForm({ apiKey: event.currentTarget.value })}
        />
        <span className="settings-hint">当前密钥：{maskedKey}（回显恒脱敏；留空则保持不变）</span>
      </div>
      <div className="settings-field">
        <label className="settings-label" htmlFor="settings-model-id">
          模型 ID
        </label>
        <input
          id="settings-model-id"
          className="settings-input"
          value={form.modelId}
          onChange={(event) => patchForm({ modelId: event.currentTarget.value })}
        />
      </div>
      <div className="settings-field">
        <label className="settings-label" htmlFor="settings-decider">
          决策层
        </label>
        <select
          id="settings-decider"
          className="settings-select"
          value={form.decider}
          onChange={(event) => patchForm({ decider: event.currentTarget.value as Decider })}
        >
          <option value="auto">auto（自动切换）</option>
          <option value="jev">jev（Jev 决策）</option>
          <option value="fallback">fallback（LLM 决策）</option>
        </select>
      </div>
      <div className="settings-grid">
        <div className="settings-field">
          <label className="settings-label" htmlFor="settings-timeout">
            超时（秒）
          </label>
          <input
            id="settings-timeout"
            className="settings-input"
            value={form.timeout}
            onChange={(event) => patchForm({ timeout: event.currentTarget.value })}
          />
        </div>
        <div className="settings-field">
          <label className="settings-label" htmlFor="settings-temperature">
            温度
          </label>
          <input
            id="settings-temperature"
            className="settings-input"
            value={form.temperature}
            onChange={(event) => patchForm({ temperature: event.currentTarget.value })}
          />
        </div>
        <div className="settings-field">
          <label className="settings-label" htmlFor="settings-max-tokens">
            max_tokens
          </label>
          <input
            id="settings-max-tokens"
            className="settings-input"
            value={form.maxTokens}
            onChange={(event) => patchForm({ maxTokens: event.currentTarget.value })}
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
