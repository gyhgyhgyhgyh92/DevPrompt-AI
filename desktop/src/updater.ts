/**
 * 桌面端自动更新服务（Windows / NSIS）。
 *
 * 设计约束（见 plan）：检查后先提示再下载；下载完成提示重启；未签名，不校验 Authenticode；
 * 更新前停 sidecar 并备份 ~/.devprompt-ai，安装失败不回滚（roll-forward）。
 *
 * 源选择放在 updateSources.ts（纯函数）；这里只负责 electron-updater 编排、对话框与日志。
 */

import { app, dialog, net } from 'electron'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { NsisUpdater, type UpdateInfo } from 'electron-updater'
import {
  buildSourceList,
  formatBytes,
  isAllowedUpdateHost,
  sameManifest,
  type UpdateSource,
} from './updateSources'

export type UpdatePhase =
  | 'idle'
  | 'checking'
  | 'available'
  | 'downloading'
  | 'downloaded'
  | 'installing'
  | 'up-to-date'
  | 'error'

export interface UpdateState {
  phase: UpdatePhase
  currentVersion: string
  /** 当前平台是否支持自动更新（本期仅 Windows）。 */
  supported: boolean
  availableVersion?: string
  releaseDate?: string
  sizeBytes?: number
  progressPercent?: number
  transferred?: number
  total?: number
  error?: string
  sourceId?: string
  lastCheckedAt?: string
}

export interface UpdateServiceOptions {
  /** 当前窗口；未创建时传 undefined，对话框与进度条会降级。 */
  getWindow: () => Electron.BrowserWindow | undefined
  /** 主进程实现：置 isQuitting、优雅停 sidecar 并等待退出；成功返回 true。 */
  stopSidecarForUpdate: () => Promise<boolean>
  /** 状态变化回调；main.ts 负责广播给渲染进程。 */
  onState: (state: UpdateState) => void
}

const CHECK_TIMEOUT_MS = 8_000
const FIRST_CHECK_DELAY_MS = 10_000
const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000
const CHECK_JITTER_MS = 5 * 60 * 1000
const SNOOZE_MS = 24 * 60 * 60 * 1000
const LOG_MAX_BYTES = 1_000_000
const BACKUP_KEEP = 2

interface ResolvedSource {
  source: UpdateSource
  manifest: string
}

type LogLevel = 'info' | 'warn' | 'error'

function stringify(value: unknown): string {
  if (typeof value === 'string') return value
  if (value instanceof Error) return value.stack ?? value.message
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function isZh(): boolean {
  return app.getLocale().toLowerCase().startsWith('zh')
}

export class UpdateService {
  private readonly options: UpdateServiceOptions
  private readonly logPath: string
  private state: UpdateState
  private sources: UpdateSource[]
  private devOverride: string | undefined
  private allowLoopback = false
  private firstTimer: NodeJS.Timeout | undefined
  private intervalTimer: NodeJS.Timeout | undefined
  private activeUpdater: NsisUpdater | undefined
  private activeSource: UpdateSource | undefined
  private activeInfo: UpdateInfo | undefined
  private checking = false
  private downloading = false
  private installing = false
  private prompting = false
  private snoozedVersion: string | undefined
  private snoozedUntil = 0
  private lastProgress = -1

  constructor(options: UpdateServiceOptions) {
    this.options = options
    this.sources = buildSourceList()
    this.logPath = path.join(app.getPath('logs'), 'updater.log')
    this.prepareLog()
    this.state = {
      phase: 'idle',
      currentVersion: app.getVersion(),
      supported: process.platform === 'win32',
    }
  }

  init(): void {
    if (process.platform !== 'win32') {
      this.log('info', '自动更新本期仅支持 Windows，跳过')
      return
    }
    const override = app.isPackaged ? undefined : process.env.DPROMPT_UPDATE_BASE_URL?.trim()
    this.devOverride = override === '' ? undefined : override
    this.allowLoopback = !app.isPackaged && this.devOverride !== undefined
    this.sources = buildSourceList(this.devOverride)

    // 开发态未显式指向本地更新源时不启动，避免把开发机当成可更新安装。
    if (!app.isPackaged && this.devOverride === undefined) {
      this.log('info', '未打包且未设置 DPROMPT_UPDATE_BASE_URL，跳过自动更新')
      return
    }

    this.firstTimer = setTimeout(() => void this.check(false), FIRST_CHECK_DELAY_MS)
    const interval = CHECK_INTERVAL_MS + Math.floor(Math.random() * CHECK_JITTER_MS)
    this.intervalTimer = setInterval(() => void this.check(false), interval)
    this.log(
      'info',
      `更新器启动：v${app.getVersion()}，源=${this.sources.map((source) => source.id).join(' → ')}`,
    )
  }

  dispose(): void {
    if (this.firstTimer !== undefined) clearTimeout(this.firstTimer)
    if (this.intervalTimer !== undefined) clearInterval(this.intervalTimer)
    this.firstTimer = undefined
    this.intervalTimer = undefined
  }

  getState(): UpdateState {
    return { ...this.state, currentVersion: app.getVersion() }
  }

  /** 手动检查（设置页）：只更新面板状态，不弹原生下载框。 */
  async check(manual: boolean): Promise<void> {
    if (this.checking || this.downloading || this.installing) return
    if (this.state.phase === 'downloaded') return
    if (!this.state.supported) {
      this.patchState({
        phase: 'error',
        error: isZh() ? '自动更新目前仅支持 Windows' : 'Auto-update is currently Windows-only',
      })
      return
    }
    if (!app.isPackaged && this.devOverride === undefined) {
      this.patchState({
        phase: 'error',
        error: isZh()
          ? '开发态未启用自动更新（设置 DPROMPT_UPDATE_BASE_URL 可联调）'
          : 'Auto-update is disabled in development (set DPROMPT_UPDATE_BASE_URL to test)',
      })
      return
    }

    this.checking = true
    this.patchState({ phase: 'checking', error: undefined, lastCheckedAt: new Date().toISOString() })
    try {
      const resolved = await this.resolveSource()
      if (resolved === null) {
        this.log('warn', '所有更新源均不可用')
        this.patchState({
          phase: 'error',
          error: isZh() ? '暂时无法检查更新' : 'Unable to check for updates',
        })
        return
      }

      const updater = this.createUpdater(resolved.source)
      this.activeUpdater = updater
      this.activeSource = resolved.source

      const result = await updater.checkForUpdates()
      if (result?.isUpdateAvailable !== true) {
        this.activeInfo = undefined
        this.patchState({
          phase: 'up-to-date',
          availableVersion: undefined,
          sizeBytes: undefined,
          progressPercent: undefined,
          error: undefined,
          sourceId: resolved.source.id,
        })
        return
      }

      this.activeInfo = result.updateInfo
      this.patchState({
        phase: 'available',
        availableVersion: result.updateInfo.version,
        releaseDate: result.updateInfo.releaseDate,
        sizeBytes: this.sizeOf(result.updateInfo),
        progressPercent: undefined,
        error: undefined,
        sourceId: resolved.source.id,
      })

      if (manual || this.isSnoozed(result.updateInfo.version)) return
      await this.promptDownload(result.updateInfo)
    } catch (error) {
      this.log('warn', `检查更新失败：${stringify(error)}`)
      this.patchState({ phase: 'error', error: this.errorText(error) })
    } finally {
      this.checking = false
    }
  }

  /** 用户确认后下载；下载完成由 update-downloaded 事件提示重启。 */
  async download(): Promise<void> {
    if (this.activeUpdater === undefined || this.activeInfo === undefined) return
    if (this.downloading || this.installing || this.state.phase !== 'available') return

    try {
      this.assertDownloadHosts(this.activeInfo)
    } catch (error) {
      this.log('error', `更新清单主机被拒绝：${stringify(error)}`)
      this.patchState({ phase: 'error', error: this.errorText(error) })
      await this.showError(
        isZh() ? '更新来源不受信任' : 'Untrusted update source',
        this.errorText(error),
      )
      return
    }

    this.downloading = true
    this.lastProgress = -1
    this.patchState({ phase: 'downloading', progressPercent: 0, error: undefined })
    try {
      await this.activeUpdater.downloadUpdate()
    } catch (error) {
      this.log('error', `下载更新失败：${stringify(error)}`)
      this.patchState({ phase: 'error', error: this.errorText(error) })
      await this.showError(
        isZh() ? '更新下载失败' : 'Update download failed',
        this.errorText(error),
      )
    } finally {
      this.downloading = false
    }
  }

  /** 下载完成后立即重启安装（应用内按钮 / 原生弹窗的「立即重启」都走这里）。 */
  async install(): Promise<void> {
    if (this.installing || this.activeUpdater === undefined) return
    if (this.state.phase !== 'downloaded') return

    this.installing = true
    this.patchState({ phase: 'installing', error: undefined })
    try {
      const stopped = await this.options.stopSidecarForUpdate()
      if (!stopped) {
        this.installing = false
        this.patchState({
          phase: 'downloaded',
          error: isZh()
            ? '后端服务未能退出，已取消安装；请重启应用后重试'
            : 'Backend did not exit; install cancelled. Restart the app and retry.',
        })
        await this.showError(
          isZh() ? '无法安装更新' : 'Unable to install update',
          isZh()
            ? '后端服务未能退出，已取消安装；请重启应用后重试。'
            : 'The backend did not exit. Restart the app and retry.',
        )
        return
      }

      this.backupUserData()
      this.log('info', `开始安装 v${this.state.availableVersion ?? ''}`)
      this.activeUpdater.quitAndInstall(true, true)
    } catch (error) {
      this.installing = false
      this.patchState({ phase: 'downloaded', error: this.errorText(error) })
      this.log('error', `安装更新失败：${stringify(error)}`)
      await this.showError(
        isZh() ? '安装更新失败' : 'Update install failed',
        this.errorText(error),
      )
    }
  }

  /** 用户选择「稍后」：24 小时内不再为同一版本弹原生下载框。 */
  dismiss(): void {
    const version = this.state.availableVersion
    if (version !== undefined) {
      this.snoozedVersion = version
      this.snoozedUntil = Date.now() + SNOOZE_MS
    }
  }

  // ---------- 源选择 ----------

  private async resolveSource(): Promise<ResolvedSource | null> {
    const github = this.sources.find((source) => source.id === 'github')
    const githubManifest =
      github === undefined ? Promise.resolve<string | null>(null) : this.fetchManifest(github.baseUrl)
    const mirrors = this.sources.filter((source) => source.id !== 'github')
    // 并行预取各镜像的清单：按序取第一个成功的源，最坏等待仍只有单次超时。
    const mirrorManifests = mirrors.map((source) => this.fetchManifest(source.baseUrl))

    for (const [index, source] of mirrors.entries()) {
      const manifest = await mirrorManifests[index]
      if (manifest === null || manifest === undefined) continue

      const authoritative = await githubManifest
      if (authoritative !== null && !sameManifest(authoritative, manifest)) {
        this.log('warn', `源 ${source.id} 的 latest.yml 与 GitHub 不一致，跳过`)
        continue
      }
      this.log(
        'info',
        `更新源=${source.id}${authoritative === null ? '（GitHub 不可达，未交叉校验）' : ''}`,
      )
      return { source, manifest }
    }

    const authoritative = await githubManifest
    if (authoritative === null || github === undefined) return null
    this.log('info', '更新源=github')
    return { source: github, manifest: authoritative }
  }

  private async fetchManifest(baseUrl: string): Promise<string | null> {
    const url = `${baseUrl}latest.yml?noCache=${Date.now().toString(36)}`
    try {
      // 用 Electron net 而不是 Node fetch：走 Chromium 网络栈，尊重系统代理设置。
      const response = await net.fetch(url, {
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS),
        headers: { accept: 'text/yaml, text/plain, */*' },
      })
      if (!response.ok) {
        this.log('info', `${baseUrl} 不可用：HTTP ${response.status}`)
        return null
      }
      const text = await response.text()
      return text.trim() === '' ? null : text
    } catch (error) {
      this.log('info', `${baseUrl} 不可用：${stringify(error)}`)
      return null
    }
  }

  private createUpdater(source: UpdateSource): NsisUpdater {
    const updater = new NsisUpdater({ provider: 'generic', url: source.baseUrl })
    updater.autoDownload = false
    updater.autoInstallOnAppQuit = false
    updater.allowDowngrade = false
    updater.allowPrerelease = false
    updater.forceDevUpdateConfig = this.devOverride !== undefined
    updater.logger = {
      info: (message) => this.log('info', stringify(message)),
      warn: (message) => this.log('warn', stringify(message)),
      error: (message) => this.log('error', stringify(message)),
      debug: (message) => this.log('info', `[debug] ${message}`),
    }

    updater.on('download-progress', (progress) => {
      const percent = Math.max(0, Math.min(100, Math.round(progress.percent)))
      this.getWindow()?.setProgressBar(percent / 100)
      if (percent === this.lastProgress) return
      this.lastProgress = percent
      this.patchState({
        phase: 'downloading',
        progressPercent: percent,
        transferred: progress.transferred,
        total: progress.total,
      })
    })

    updater.on('update-downloaded', (event) => {
      this.getWindow()?.setProgressBar(-1)
      this.activeInfo = event
      this.patchState({
        phase: 'downloaded',
        availableVersion: event.version,
        progressPercent: 100,
        error: undefined,
      })
      void this.promptInstall(event.version)
    })

    updater.on('update-cancelled', () => {
      this.getWindow()?.setProgressBar(-1)
      this.patchState({ phase: 'available', progressPercent: undefined })
    })

    updater.on('error', (error) => {
      this.log('error', `更新器错误：${stringify(error)}`)
      this.getWindow()?.setProgressBar(-1)
      if (this.installing) return
      this.patchState({ phase: 'error', error: this.errorText(error) })
    })

    return updater
  }

  // ---------- 下载与安装 ----------

  private assertDownloadHosts(info: UpdateInfo): void {
    if (this.activeSource === undefined) throw new Error('更新源缺失')
    const urls = info.files.map((file) => file.url)
    if (typeof info.path === 'string' && info.path !== '') urls.push(info.path)
    for (const raw of urls) {
      const resolved = new URL(raw, this.activeSource.baseUrl).toString()
      if (!isAllowedUpdateHost(resolved, this.allowLoopback)) {
        throw new Error(`更新文件域名不在白名单：${new URL(resolved).hostname}`)
      }
    }
  }

  private backupUserData(): void {
    const dataDir = path.join(os.homedir(), '.devprompt-ai')
    const backupRoot = path.join(dataDir, 'backups')
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    const target = path.join(backupRoot, `${this.state.currentVersion}-${stamp}`)
    const names = ['devprompt.db', 'devprompt.db-wal', 'devprompt.db-shm', 'settings.json']

    let copied = 0
    for (const name of names) {
      const from = path.join(dataDir, name)
      if (!fs.existsSync(from)) continue
      fs.mkdirSync(target, { recursive: true, mode: 0o700 })
      fs.copyFileSync(from, path.join(target, name))
      copied += 1
    }

    if (copied === 0) {
      this.log('warn', '没有可备份的数据文件')
      return
    }
    this.log('info', `已备份 ${copied} 个数据文件到 ${target}`)
    this.pruneBackups(backupRoot)
  }

  private pruneBackups(root: string): void {
    const entries = fs
      .readdirSync(root, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort()
      .reverse()
    for (const name of entries.slice(BACKUP_KEEP)) {
      fs.rmSync(path.join(root, name), { recursive: true, force: true })
    }
  }

  // ---------- 对话框 ----------

  private async promptDownload(info: UpdateInfo): Promise<void> {
    if (this.prompting || this.installing) return
    this.prompting = true
    try {
      const size = formatBytes(this.sizeOf(info))
      const zh = isZh()
      const { response } = await this.showMessage({
        type: 'info',
        buttons: [zh ? '下载' : 'Download', zh ? '稍后' : 'Later'],
        defaultId: 0,
        cancelId: 1,
        noLink: true,
        title: 'DevPrompt AI',
        message: zh
          ? `发现新版本 v${info.version}`
          : `Update v${info.version} is available`,
        detail: zh
          ? `当前 v${app.getVersion()}${size === '' ? '' : `，更新包约 ${size}`}。下载完成后可选择立即重启安装。`
          : `Current v${app.getVersion()}${size === '' ? '' : `, about ${size}`}. You can restart to install after download.`,
      })
      if (response === 0) await this.download()
      else this.dismiss()
    } finally {
      this.prompting = false
    }
  }

  private async promptInstall(version: string): Promise<void> {
    if (this.prompting || this.installing) return
    this.prompting = true
    try {
      const zh = isZh()
      const { response } = await this.showMessage({
        type: 'info',
        buttons: [zh ? '立即重启' : 'Restart now', zh ? '稍后' : 'Later'],
        defaultId: 0,
        cancelId: 1,
        noLink: true,
        title: 'DevPrompt AI',
        message: zh ? `更新 v${version} 已下载` : `Update v${version} is ready`,
        detail: zh
          ? '重启后完成安装；未保存的输入会丢失。'
          : 'Restart to finish installing; unsaved input will be lost.',
      })
      if (response === 0) await this.install()
    } finally {
      this.prompting = false
    }
  }

  private async showError(message: string, detail: string): Promise<void> {
    await this.showMessage({
      type: 'error',
      buttons: [isZh() ? '知道了' : 'OK'],
      noLink: true,
      title: 'DevPrompt AI',
      message,
      detail,
    })
  }

  private showMessage(
    options: Electron.MessageBoxOptions,
  ): Promise<Electron.MessageBoxReturnValue> {
    const window = this.getWindow()
    return window === undefined || window.isDestroyed()
      ? dialog.showMessageBox(options)
      : dialog.showMessageBox(window, options)
  }

  // ---------- 状态与日志 ----------

  private getWindow(): Electron.BrowserWindow | undefined {
    const window = this.options.getWindow()
    return window === undefined || window.isDestroyed() ? undefined : window
  }

  private patchState(patch: Partial<UpdateState>): void {
    this.state = { ...this.state, ...patch }
    this.options.onState(this.getState())
  }

  private sizeOf(info: UpdateInfo): number | undefined {
    const files = info.files ?? []
    const exe = files.find((file) => file.url.toLowerCase().endsWith('.exe')) ?? files[0]
    return exe?.size
  }

  private isSnoozed(version: string): boolean {
    return this.snoozedVersion === version && Date.now() < this.snoozedUntil
  }

  private errorText(error: unknown): string {
    const message = error instanceof Error ? error.message : String(error)
    return message.length > 240 ? `${message.slice(0, 240)}…` : message
  }

  private prepareLog(): void {
    try {
      fs.mkdirSync(path.dirname(this.logPath), { recursive: true })
      if (fs.existsSync(this.logPath) && fs.statSync(this.logPath).size > LOG_MAX_BYTES) {
        fs.renameSync(this.logPath, `${this.logPath}.1`)
      }
    } catch {
      // 日志不可写不应影响更新
    }
  }

  private log(level: LogLevel, message: string): void {
    const line = `${new Date().toISOString()} [${level}] ${message}\n`
    try {
      fs.appendFileSync(this.logPath, line, { encoding: 'utf8' })
    } catch {
      // 忽略：日志失败不影响更新
    }
    if (!app.isPackaged) process.stderr.write(line)
  }
}
