import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getModelCatalog, putSettings, refreshModelCatalog } from '../../api/endpoints'
import type { ModelCatalogItem } from '../../schemas/settings'
import type { SettingsResponse, SettingsUpdate } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import type { ModelCapabilities } from '../../schemas/modelSpec'
import { ApiModeSelect } from './ApiModeSelect'
import { ModelCapabilityBadge } from './ModelCapabilityBadge'
import { findProvider, ProviderSelect } from './ProviderSelect'
import { errorMessage } from './errorMessage'
import styles from './settings.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

/**
 * 供应商中心化配置面板（2026-10-18 重构，F-604 模型服务标签页）。
 *
 * 配置单位从「模型条目」上移到「供应商」：每个供应商配一次 `Base URL` + `API Key`，
 * 刷新拿到该端点可用的 `model_id` 列表，**多选勾选**后一键保存——勾选列表就是该供应商
 * 的生效模型集合（未勾选的条目随 `models` 整表替换被删除，用户裁定）。
 *
 * 两个易混概念：`provider_configs` 是用户自己配置的供应商（可写，密钥脱敏回显）；
 * `settings.providers` 是后端静态厂商目录（只读，驱动供应商下拉与档位数据）。
 * 供应商清单**不硬编码**（2026-09-17 W8）——写死一份必然与后端漂移。
 */

/** 供应商草稿：`id` 由前端预生成（新供应商也要有 id，条目才能在同一次请求里引用它）。 */
interface ProviderDraft {
  key: string
  id: string
  provider: string
  baseUrl: string
  apiKey: string
  masked: string
  /** 勾选的 model_id 集合 = 该供应商的生效模型集合。 */
  selected: string[]
  /** 勾选项的按模型参数（key = model_id）。 */
  perModel: Record<string, { apiMode: string }>
}

/** 已存条目（渲染能力徽标与「当前」标记）。 */
interface ModelRow {
  id: string
  providerId: string
  modelId: string
  isActive: boolean
  capabilities: ModelCapabilities
  apiMode: string
}

type Catalog = { models: ModelCatalogItem[]; warning: string | null; fetched_at: string | null }

const EMPTY_CATALOG: Catalog = { models: [], warning: null, fetched_at: null }

/** 未知能力时的兜底（后端保证下发，`.default()` 只在老数据缺字段时生效）。 */
const FALLBACK_CAPABILITIES: ModelCapabilities = {
  supports_tools: true,
  supports_reasoning: false,
  max_context_length: null,
}

let draftSeq = 0

/** 预生成供应商引用键：条目必须在同一次请求里引用它，故 id 由前端先给。 */
function newProviderId(): string {
  draftSeq += 1
  return `p-new-${draftSeq}`
}

function providerDraftsFrom(settings: SettingsResponse): ProviderDraft[] {
  const models = settings.models ?? []
  return (settings.provider_configs ?? []).map((p) => {
    const owned = models.filter((m) => m.provider_id === p.id)
    return {
      key: p.id,
      id: p.id,
      provider: p.provider,
      baseUrl: p.base_url,
      apiKey: '',
      masked: p.api_key_masked,
      selected: owned.map((m) => m.model_id),
      perModel: Object.fromEntries(owned.map((m) => [m.model_id, { apiMode: m.api_mode ?? '' }])),
    }
  })
}

function modelRowsFrom(settings: SettingsResponse): ModelRow[] {
  return (settings.models ?? []).map((m) => ({
    id: m.id,
    providerId: m.provider_id,
    modelId: m.model_id,
    isActive: m.is_active,
    capabilities: m.capabilities ?? FALLBACK_CAPABILITIES,
    apiMode: m.api_mode ?? '',
  }))
}

/**
 * draft → PUT /settings 载荷。
 *
 * `reasoning_effort` / `max_context_length` **刻意不下发**：这两项按模型粒度在启动页
 * 配置（hover 模型下拉的面板），后端对缺省值的语义是「沿用同 id 旧值」，故这里保存
 * 不会覆盖它们。`api_key` 空值同样表示沿用——前端只有脱敏值（MUST-19）。
 */
function buildPayload(drafts: ProviderDraft[], rows: ModelRow[]): NonNullable<SettingsUpdate> {
  const rowIndex = new Map(rows.map((r) => [`${r.providerId}|${r.modelId}`, r]))
  const models: NonNullable<SettingsUpdate['models']> = []
  for (const draft of drafts) {
    for (const modelId of draft.selected) {
      const existing = rowIndex.get(`${draft.id}|${modelId}`)
      models.push({
        ...(existing === undefined ? {} : { id: existing.id }),
        provider_id: draft.id,
        model_id: modelId,
        api_mode: draft.perModel[modelId]?.apiMode ?? existing?.apiMode ?? '',
      })
    }
  }
  return {
    provider_configs: drafts.map((d) => ({
      id: d.id,
      provider: d.provider,
      base_url: d.baseUrl.trim(),
      ...(d.apiKey === '' ? {} : { api_key: d.apiKey }),
    })),
    models,
  }
}

/** 模型服务面板：按供应商配置凭据 → 刷新模型列表 → 多选 → 一键保存。 */
export function ModelServicePanel() {
  const { t } = useTranslation()
  const settings = useSettingsStore((state) => state.settings)
  const setSettings = useSettingsStore((state) => state.setSettings)
  const [drafts, setDrafts] = useState<ProviderDraft[]>([])
  const [rows, setRows] = useState<ModelRow[]>([])
  const [status, setStatus] = useState<{ ok: boolean; text: string }>({ ok: true, text: '' })
  const [isBusy, setIsBusy] = useState(false)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; detail: string }>>(
    {},
  )
  const [catalogs, setCatalogs] = useState<Record<string, Catalog>>({})
  const [refreshingKeys, setRefreshingKeys] = useState<Record<string, boolean>>({})

  useEffect(() => {
    if (!settings) return
    setDrafts(providerDraftsFrom(settings))
    setRows(modelRowsFrom(settings))
  }, [settings])

  // 进面板先读已落库的目录快照（不联网）：否则模型多选列表一片空白，用户以为没配好。
  const savedIds = (settings?.provider_configs ?? []).map((p) => p.id).join(',')
  useEffect(() => {
    if (savedIds === '') return
    let cancelled = false
    void Promise.all(
      savedIds.split(',').map((providerId) =>
        getModelCatalog(providerId).then(
          (result) => ({ providerId, result }),
          (error: unknown) => ({ providerId, error }),
        ),
      ),
    ).then((outcomes) => {
      if (cancelled) return
      setCatalogs((prev) => {
        const next = { ...prev }
        for (const o of outcomes) {
          // 只填空白：刷新按钮拿到的现场数据比快照新，不能被慢一步的快照覆盖
          if (next[o.providerId] !== undefined) continue
          next[o.providerId] =
            'error' in o
              ? {
                  models: [],
                  warning: errorMessage(o.error, t('settings.model.load_list_failed')),
                  fetched_at: null,
                }
              : {
                  models: o.result.models,
                  warning: o.result.warning ?? null,
                  fetched_at: o.result.fetched_at ?? null,
                }
        }
        return next
      })
    })
    return () => {
      cancelled = true
    }
  }, [savedIds])

  if (!settings) {
    return <p className={s('settings-note')}>{t('settings.loading')}</p>
  }

  const providerDirectory = settings.providers ?? []
  const catalogFor = (key: string): Catalog => catalogs[key] ?? EMPTY_CATALOG
  const isRefreshing = (key: string) => refreshingKeys[key] === true

  const patchDraft = (key: string, patch: Partial<ProviderDraft>) =>
    setDrafts((prev) => prev.map((d) => (d.key === key ? { ...d, ...patch } : d)))

  const toggleModel = (key: string, modelId: string) =>
    setDrafts((prev) =>
      prev.map((d) =>
        d.key === key
          ? {
              ...d,
              selected: d.selected.includes(modelId)
                ? d.selected.filter((m) => m !== modelId)
                : [...d.selected, modelId],
            }
          : d,
      ),
    )

  const setApiMode = (key: string, modelId: string, apiMode: string) =>
    setDrafts((prev) =>
      prev.map((d) =>
        d.key === key ? { ...d, perModel: { ...d.perModel, [modelId]: { apiMode } } } : d,
      ),
    )

  const addProvider = () => {
    const id = newProviderId()
    setDrafts((prev) => [
      ...prev,
      {
        key: id,
        id,
        provider: '',
        baseUrl: '',
        apiKey: '',
        masked: '',
        selected: [],
        perModel: {},
      },
    ])
  }

  /** 删除供应商：级联——它下面的条目随 `models` 整表替换一起消失（用户裁定）。 */
  const removeProvider = (key: string) => {
    const count = drafts.find((d) => d.key === key)?.selected.length ?? 0
    if (
      count > 0 &&
      !window.confirm(
        `删除该供应商会一并删除其下 ${count} 个已勾选模型（凭据也没了，条目留着也调不通）。确认删除？`,
      )
    ) {
      return
    }
    setDrafts((prev) => prev.filter((d) => d.key !== key))
  }

  /** 保存整表：`provider_configs` 为权威列表（未出现的被删除），`models` 只含勾选项。 */
  const saveAll = async (): Promise<boolean> => {
    if (drafts.some((d) => d.provider.trim() === '' || d.baseUrl.trim() === '')) {
      setStatus({ ok: false, text: t('settings.model.need_provider') })
      return false
    }
    setIsBusy(true)
    try {
      const next = await putSettings(buildPayload(drafts, rows))
      setSettings(next)
      setStatus({ ok: true, text: t('settings.model.saved') })
      return true
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error, t('settings.model.save_failed')) })
      return false
    } finally {
      setIsBusy(false)
    }
  }

  /**
   * 刷新模型列表 = 真实网络探测 `GET {base_url}/models`（带该供应商自己的 Key）。
   * 必须先保存：后端按 `provider_id` 从 settings.json 取密钥，新供应商没落盘就取不到。
   */
  const refreshCatalog = async (key: string) => {
    const draft = drafts.find((d) => d.key === key)
    if (draft === undefined) return
    const saved = await saveAll()
    if (!saved) return
    setRefreshingKeys((prev) => ({ ...prev, [key]: true }))
    try {
      const result = await refreshModelCatalog(draft.id)
      setCatalogs((prev) => ({
        ...prev,
        [key]: {
          models: result.models,
          warning: result.warning ?? null,
          fetched_at: result.fetched_at ?? null,
        },
      }))
      setStatus({
        ok: !result.warning,
        text: result.warning ?? `已获取 ${result.models.length} 个模型`,
      })
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error, t('settings.model.refresh_failed')) })
    } finally {
      setRefreshingKeys((prev) => ({ ...prev, [key]: false }))
    }
  }

  /**
   * 测试连接（2026-10-18 移到供应商级）：探测的是「端点 + 密钥是否可用」，与模型无关，
   * 放在每个条目一行只会给出重复且误导的结果。复用刷新端点，零新增端点。
   */
  const testConnection = async (key: string) => {
    const draft = drafts.find((d) => d.key === key)
    if (draft === undefined) return
    // 同样必须先保存：后端按 provider_id 从 settings.json 取密钥（MUST-19），
    // 刚新增还没落盘的供应商探测必然报「供应商不存在」。
    if (!(await saveAll())) return
    setRefreshingKeys((prev) => ({ ...prev, [key]: true }))
    try {
      const result = await refreshModelCatalog(draft.id)
      setTestResults((prev) => ({
        ...prev,
        [key]: result.warning
          ? { ok: false, detail: result.warning }
          : { ok: true, detail: t('settings.model.connect_ok') },
      }))
    } catch (error) {
      setTestResults((prev) => ({
        ...prev,
        [key]: { ok: false, detail: errorMessage(error, t('settings.model.connect_failed')) },
      }))
    } finally {
      setRefreshingKeys((prev) => ({ ...prev, [key]: false }))
    }
  }

  return (
    <section className={s('settings-panel')} aria-label={t('settings.tab.model-service')}>
      <h3 className={s('settings-panel__title')}>{t('settings.tab.model-service')}</h3>
      <p className={s('settings-panel__desc')}>{t('settings.model.lead')}</p>
      <div className={s('settings-model-list')} aria-label={t('settings.model.provider_list')}>
        {drafts.length === 0 ? (
          <p className={s('settings-note')}>{t('settings.model.empty_hint')}</p>
        ) : null}
        {drafts.map((draft) => {
          const pickedProvider = findProvider(providerDirectory, draft.provider)
          const catalog = catalogFor(draft.key)
          const rowByModel = new Map(
            rows.filter((r) => r.providerId === draft.id).map((r) => [r.modelId, r]),
          )
          return (
            <div key={draft.key} className={s('settings-model-row')}>
              <div className={s('settings-model-row__head')}>
                <span className={s('settings-model-row__title')}>
                  {pickedProvider?.label ?? draft.provider ?? t('settings.model.new_provider')}
                </span>
                <span className={s('settings-model-badge')}>{draft.selected.length} 个模型</span>
                <span className={s('settings-model-row__spacer')} />
                <button
                  type="button"
                  className={s('settings-btn settings-btn--small settings-btn--danger')}
                  onClick={() => removeProvider(draft.key)}
                >
                  {t('settings.model.delete_provider')}
                </button>
              </div>
              <div className={s('settings-grid')}>
                <div className={s('settings-field')}>
                  <label className={s('settings-label')} htmlFor={`${draft.key}-provider`}>
                    {t('settings.provider.aria')}
                  </label>
                  <ProviderSelect
                    providers={providerDirectory}
                    value={draft.provider}
                    onChange={(value) => {
                      const picked = findProvider(providerDirectory, value)
                      patchDraft(draft.key, {
                        provider: value,
                        ...(picked && picked.base_url !== '' ? { baseUrl: picked.base_url } : {}),
                      })
                    }}
                  />
                </div>
                <div className={s('settings-field')}>
                  <label className={s('settings-label')} htmlFor={`${draft.key}-base-url`}>
                    Base URL
                  </label>
                  <input
                    id={`${draft.key}-base-url`}
                    className={s('settings-input')}
                    value={draft.baseUrl}
                    onChange={(event) =>
                      patchDraft(draft.key, { baseUrl: event.currentTarget.value })
                    }
                  />
                  {pickedProvider?.base_url === '' ? (
                    <span className={s('settings-hint')}>
                      {t('settings.model.endpoint_unknown')}
                    </span>
                  ) : null}
                </div>
                <div className={s('settings-field')}>
                  <label className={s('settings-label')} htmlFor={`${draft.key}-api-key`}>
                    API Key
                  </label>
                  <input
                    id={`${draft.key}-api-key`}
                    className={s('settings-input')}
                    type="password"
                    autoComplete="off"
                    placeholder={
                      draft.masked !== '' ? draft.masked : t('settings.model.not_configured')
                    }
                    value={draft.apiKey}
                    onChange={(event) =>
                      patchDraft(draft.key, { apiKey: event.currentTarget.value })
                    }
                  />
                  <span className={s('settings-hint')}>
                    {t('settings.model.current_key')}：
                    {draft.masked !== '' ? draft.masked : t('settings.model.not_configured')}
                    （回显恒脱敏；留空则保持不变）
                  </span>
                </div>
              </div>
              <div className={s('settings-actions')}>
                <button
                  type="button"
                  className={s('settings-btn')}
                  disabled={isBusy || isRefreshing(draft.key)}
                  onClick={() => void refreshCatalog(draft.key)}
                  title={
                    catalog.fetched_at
                      ? `${t('settings.model.last_refresh')}：${catalog.fetched_at}`
                      : t('settings.model.never_refreshed')
                  }
                >
                  {isRefreshing(draft.key)
                    ? t('settings.model.refreshing')
                    : t('settings.model.refresh')}
                </button>
                <button
                  type="button"
                  className={s('settings-btn')}
                  disabled={isBusy || isRefreshing(draft.key)}
                  onClick={() => void testConnection(draft.key)}
                >
                  {isRefreshing(draft.key) ? t('settings.model.testing') : t('settings.model.test')}
                </button>
              </div>
              {testResults[draft.key] ? (
                <p
                  className={s(
                    testResults[draft.key]?.ok
                      ? 'settings-status settings-status--ok'
                      : 'settings-status settings-status--error',
                  )}
                >
                  {testResults[draft.key]?.detail}
                </p>
              ) : null}
              {catalog.warning ? (
                <span className={s('settings-error')} role="alert">
                  {catalog.warning}
                </span>
              ) : null}
              <div className={s('settings-field')}>
                <div className={s('settings-label')}>{t('settings.model.available')}</div>
                {catalog.models.length === 0 ? (
                  <span className={s('settings-hint')}>{t('settings.model.refresh_first')}</span>
                ) : (
                  <ul className={s('provider-model-list')}>
                    {catalog.models.map((item) => {
                      const checked = draft.selected.includes(item.model_id)
                      const row = rowByModel.get(item.model_id)
                      return (
                        <li key={item.model_id} className={s('provider-model-list__item')}>
                          <label className={s('provider-model-list__label')}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleModel(draft.key, item.model_id)}
                            />
                            <span className={s('provider-model-list__name')}>{item.model_id}</span>
                            {row?.isActive ? (
                              <span className={s('settings-model-badge')}>
                                {t('settings.model.current')}
                              </span>
                            ) : null}
                            {row !== undefined ? (
                              <ModelCapabilityBadge capabilities={row.capabilities} />
                            ) : null}
                          </label>
                          {checked ? (
                            <ApiModeSelect
                              id={`${draft.key}-${item.model_id}-api-mode`}
                              supported={pickedProvider?.supported_api_modes ?? []}
                              value={draft.perModel[item.model_id]?.apiMode ?? row?.apiMode ?? ''}
                              defaultMode={pickedProvider?.default_api_mode ?? 'chat_completions'}
                              onModeChange={(apiMode) =>
                                setApiMode(draft.key, item.model_id, apiMode)
                              }
                            />
                          ) : null}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <div className={s('settings-actions')}>
        <button type="button" className={s('settings-btn')} disabled={isBusy} onClick={addProvider}>
          {t('settings.model.add_provider')}
        </button>
        <button
          type="button"
          className={s('settings-btn settings-btn--primary')}
          disabled={isBusy}
          onClick={() => void saveAll()}
        >
          {t('settings.model.save')}
        </button>
      </div>
      {status.text !== '' ? (
        <p
          className={s(
            status.ok
              ? 'settings-status settings-status--ok'
              : 'settings-status settings-status--error',
          )}
        >
          {status.text}
        </p>
      ) : null}
    </section>
  )
}
