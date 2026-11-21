import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { putSettings, testMcpServer } from '../../api/endpoints'
import type { McpServerUpdate, SkillView } from '../../schemas/settings'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { makeS } from '../../utils/css'
import styles from './settings.module.css'

const s = makeS(styles)

type Draft = { name: string; description: string; body: string }
type ServerDraft = {
  name: string
  transport: 'stdio' | 'sse' | 'streamable-http'
  command: string
  url: string
}

const emptySkill: Draft = { name: '', description: '', body: '' }
const emptyServer: ServerDraft = { name: '', transport: 'stdio', command: '', url: '' }

/** 扩展页（2026-11-21）：Skill 双形态 + MCP Server 配置，数据全部走后端 GET/PUT /settings。 */
export function ExtensionsPanel() {
  const { t } = useTranslation()
  const settings = useSettingsStore((state) => state.settings)
  const setSettings = useSettingsStore((state) => state.setSettings)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [skill, setSkill] = useState<Draft>(emptySkill)
  const [server, setServer] = useState<ServerDraft>(emptyServer)
  const [riskAccepted, setRiskAccepted] = useState(false)
  const [probe, setProbe] = useState<Record<string, string>>({})

  // 契约里带默认值的字段在生成的类型中是可选的；这里补成必填，避免下游到处判空。
  const skills = (settings?.skills?.items ?? []).map((item) => ({
    ...item,
    skill_id: item.skill_id ?? '',
    description: item.description ?? '',
    domains: item.domains ?? [],
    enabled: item.enabled ?? true,
    source: item.source ?? 'dir',
  }))
  const dirs = settings?.skills?.dirs ?? []
  const servers = (settings?.mcp_servers ?? []).map((item) => ({
    ...item,
    args: item.args ?? [],
    env: item.env ?? {},
    headers: item.headers ?? {},
    tool_allowlist: item.tool_allowlist ?? [],
  }))
  const customSkills = skills.filter((item) => item.source === 'custom')

  async function persist(body: Parameters<typeof putSettings>[0], okText: string): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const next = await putSettings(body)
      setSettings(next)
      setNotice(okText)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.extensions.failed'))
    } finally {
      setBusy(false)
    }
  }

  async function saveSkills(next: SkillView[]): Promise<void> {
    await persist(
      {
        skills: next.map((item) => ({
          skill_id: item.skill_id || null,
          name: item.name,
          description: item.description,
          body: '',
          domains: item.domains,
          enabled: item.enabled,
        })),
      },
      t('settings.extensions.saved'),
    )
  }

  async function addSkill(): Promise<void> {
    if (!skill.name.trim()) return
    const next: SkillView = {
      skill_id: '',
      name: skill.name.trim(),
      description: skill.description,
      source: 'custom',
      domains: [],
      enabled: true,
    }
    await saveSkills([...customSkills, next])
    setSkill(emptySkill)
  }

  async function saveServers(next: McpServerUpdate[]): Promise<void> {
    await persist({ mcp_servers: next }, t('settings.extensions.saved'))
  }

  async function addServer(): Promise<void> {
    if (!server.name.trim() || !riskAccepted) return
    const draft: McpServerUpdate = {
      name: server.name.trim(),
      transport: server.transport,
      command: server.transport === 'stdio' ? server.command : '',
      args: [],
      env: {},
      url: server.transport === 'stdio' ? '' : server.url,
      headers: {},
      enabled: true,
      tool_allowlist: [],
    }
    await saveServers([...servers, draft])
    setServer(emptyServer)
    setRiskAccepted(false)
  }

  async function toggleServer(index: number): Promise<void> {
    const next = servers.map((item, i) =>
      i === index ? { ...item, enabled: !item.enabled } : item,
    )
    await saveServers(next)
  }

  async function removeServer(index: number): Promise<void> {
    await saveServers(servers.filter((_item, i) => i !== index))
  }

  async function probeServer(index: number): Promise<void> {
    const item = servers[index]
    if (!item) return
    setProbe((prev) => ({ ...prev, [item.id]: t('settings.extensions.testing') }))
    try {
      const result = await testMcpServer({
        id: item.id,
        name: item.name,
        transport: item.transport,
        command: item.command,
        args: item.args,
        env: {},
        url: item.url,
        headers: {},
        enabled: true,
        tool_allowlist: item.tool_allowlist,
      })
      setProbe((prev) => ({
        ...prev,
        [item.id]: result.ok
          ? t('settings.extensions.tools', { count: result.tools.length })
          : result.error,
      }))
    } catch (err) {
      setProbe((prev) => ({
        ...prev,
        [item.id]: err instanceof Error ? err.message : t('settings.extensions.failed'),
      }))
    }
  }

  return (
    <section className={s('settings-panel')}>
      <h3 className={s('settings-panel__title')}>{t('settings.extensions.title')}</h3>
      <p className={s('settings-panel__desc')}>{t('settings.extensions.desc')}</p>
      {error ? <p className={s('settings-status settings-status--error')}>{error}</p> : null}
      {notice ? <p className={s('settings-status settings-status--ok')}>{notice}</p> : null}

      <div className={s('ext-section')}>
        <h4 className={s('ext-section__title')}>{t('settings.extensions.skills')}</h4>
        <p className={s('settings-hint')}>
          {dirs.length > 0
            ? t('settings.extensions.dirs', { dirs: dirs.join(' · ') })
            : t('settings.extensions.no_dirs')}
        </p>
        {skills.length === 0 ? (
          <p className={s('settings-hint')}>{t('settings.extensions.no_skills')}</p>
        ) : (
          <ul className={s('ext-list')}>
            {skills.map((item) => (
              <li key={`${item.source}-${item.skill_id || item.name}`} className={s('ext-item')}>
                <span className={s(`ext-badge ext-badge--${item.source}`)}>
                  {item.source === 'dir'
                    ? t('settings.extensions.from_dir')
                    : t('settings.extensions.from_custom')}
                </span>
                <span className={s('ext-item__name')}>{item.name}</span>
                <span className={s('ext-item__desc')}>{item.description}</span>
                {item.source === 'custom' ? (
                  <button
                    type="button"
                    className={s('settings-btn settings-btn--small settings-btn--danger')}
                    disabled={busy}
                    onClick={() => void saveSkills(customSkills.filter((x) => x !== item))}
                  >
                    {t('settings.extensions.delete')}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        <div className={s('settings-grid')}>
          <label className={s('settings-field')}>
            <span className={s('settings-label')}>{t('settings.extensions.skill_name')}</span>
            <input
              className={s('settings-input')}
              value={skill.name}
              onChange={(event) => setSkill({ ...skill, name: event.target.value })}
            />
          </label>
          <label className={s('settings-field')}>
            <span className={s('settings-label')}>{t('settings.extensions.skill_desc')}</span>
            <input
              className={s('settings-input')}
              value={skill.description}
              onChange={(event) => setSkill({ ...skill, description: event.target.value })}
            />
          </label>
        </div>
        <div className={s('settings-actions')}>
          <button
            type="button"
            className={s('settings-btn settings-btn--primary')}
            disabled={busy || !skill.name.trim()}
            onClick={() => void addSkill()}
          >
            {t('settings.extensions.add_skill')}
          </button>
        </div>
      </div>

      <div className={s('ext-section')}>
        <h4 className={s('ext-section__title')}>{t('settings.extensions.mcp')}</h4>
        {servers.length === 0 ? (
          <p className={s('settings-hint')}>{t('settings.extensions.no_servers')}</p>
        ) : (
          <ul className={s('ext-list')}>
            {servers.map((item, index) => (
              <li key={item.id || item.name} className={s('ext-item ext-item--server')}>
                <span className={s('ext-badge')}>{item.transport}</span>
                <span className={s('ext-item__name')}>{item.name}</span>
                <span
                  className={s(`ext-dot ${item.enabled ? 'ext-dot--on' : 'ext-dot--off'}`)}
                  title={
                    item.enabled
                      ? t('settings.extensions.enabled')
                      : t('settings.extensions.disabled')
                  }
                />
                <button
                  type="button"
                  className={s('settings-btn settings-btn--small')}
                  disabled={busy}
                  onClick={() => void toggleServer(index)}
                >
                  {item.enabled
                    ? t('settings.extensions.disable')
                    : t('settings.extensions.enable')}
                </button>
                <button
                  type="button"
                  className={s('settings-btn settings-btn--small')}
                  disabled={busy}
                  onClick={() => void probeServer(index)}
                >
                  {t('settings.extensions.test')}
                </button>
                <button
                  type="button"
                  className={s('settings-btn settings-btn--small settings-btn--danger')}
                  disabled={busy}
                  onClick={() => void removeServer(index)}
                >
                  {t('settings.extensions.delete')}
                </button>
                {probe[item.id] ? (
                  <span className={s('settings-hint')}>{probe[item.id]}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        <div className={s('settings-grid')}>
          <label className={s('settings-field')}>
            <span className={s('settings-label')}>{t('settings.extensions.server_name')}</span>
            <input
              className={s('settings-input')}
              value={server.name}
              onChange={(event) => setServer({ ...server, name: event.target.value })}
            />
          </label>
          <label className={s('settings-field')}>
            <span className={s('settings-label')}>{t('settings.extensions.transport')}</span>
            <select
              className={s('settings-select')}
              value={server.transport}
              onChange={(event) =>
                setServer({ ...server, transport: event.target.value as ServerDraft['transport'] })
              }
            >
              <option value="stdio">stdio</option>
              <option value="sse">sse</option>
              <option value="streamable-http">streamable-http</option>
            </select>
          </label>
          {server.transport === 'stdio' ? (
            <label className={s('settings-field')}>
              <span className={s('settings-label')}>{t('settings.extensions.command')}</span>
              <input
                className={s('settings-input')}
                value={server.command}
                onChange={(event) => setServer({ ...server, command: event.target.value })}
              />
            </label>
          ) : (
            <label className={s('settings-field')}>
              <span className={s('settings-label')}>{t('settings.extensions.url')}</span>
              <input
                className={s('settings-input')}
                value={server.url}
                onChange={(event) => setServer({ ...server, url: event.target.value })}
              />
            </label>
          )}
        </div>

        {server.transport === 'stdio' ? (
          <label className={s('ext-risk')}>
            <input
              type="checkbox"
              checked={riskAccepted}
              onChange={(event) => setRiskAccepted(event.target.checked)}
            />
            {t('settings.extensions.risk')}
          </label>
        ) : null}

        <div className={s('settings-actions')}>
          <button
            type="button"
            className={s('settings-btn settings-btn--primary')}
            disabled={
              busy || !server.name.trim() || (server.transport === 'stdio' && !riskAccepted)
            }
            onClick={() => void addServer()}
          >
            {t('settings.extensions.add_server')}
          </button>
        </div>
      </div>
    </section>
  )
}
