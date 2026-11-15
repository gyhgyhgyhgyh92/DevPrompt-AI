/**
 * 系统原生文件夹选择器（2026-10-19）：经浏览器扩展 -> native messaging host ->
 * Windows 原生对话框，取回**绝对路径**。
 *
 * 为什么必须走扩展：浏览器的文件选择 API 刻意不暴露绝对路径，而 GET /project/scan
 * 需要绝对路径去服务端扫描。详见 browser-extension/README.md。
 */
import { errorMessage } from '../components/settings/errorMessage'
import { i18n } from '../i18n'

const SOURCE = 'devprompt-ai'
/** 原生对话框是用户驱动的模态交互，超时放宽（与历史实现一致）。 */
const PICK_TIMEOUT_MS = 310_000

/** 未装扩展 / 不支持时的统一文案：说清成因与补救（取当前界面语言）。 */
export function notInstalledHint(): string {
  return i18n.t('native_picker.not_installed')
}

export interface NativePickResult {
  /** 用户选中的绝对路径；取消时为空串。 */
  path: string
}

interface BridgeResponse {
  source?: string
  kind?: string
  id?: string
  ok?: boolean
  path?: string
  error?: string
}

let seq = 0

/** 扩展注入标记（content script 写在共享 DOM 上，见 browser-extension/content.js）。 */
const READY_ATTR = 'data-devprompt-native'

/**
 * 扩展桥是否已就绪（扩展 content script 已注入本页）。
 *
 * 用于**点击前**的同步探测：扩展未加载/未启用/页面未刷新时，postMessage
 * 无人应答，请求会悬挂到超时——此时应立即给出可执行提示，而非长时间空转。
 */
export function isNativeBridgeReady(): boolean {
  if (typeof document === 'undefined') return false
  return document.documentElement?.getAttribute(READY_ATTR) === '1'
}

/** 扩展缺席时的提示（取当前界面语言）。 */
export function nativeBridgeMissingHint(): string {
  return i18n.t('native_picker.extension_missing')
}

/** 把异常转成用户可读文案（与设置面板同一口径）。 */
export function nativePickErrorText(error: unknown): string {
  return errorMessage(error, i18n.t('native_picker.unavailable'))
}

/**
 * 通过扩展调起系统原生文件夹选择器。
 *
 * @returns 选中路径；用户取消返回 `{ path: '' }`。
 * @throws 未装扩展 / 非 Chromium 浏览器 / 宿主无响应（超时），文案含补救步骤。
 */
export function pickFolderViaNative(
  timeoutMs: number = PICK_TIMEOUT_MS,
): Promise<NativePickResult> {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error(i18n.t('native_picker.no_browser')))
  }
  seq += 1
  const id = 'pick-' + Date.now() + '-' + seq
  return new Promise<NativePickResult>((resolve, reject) => {
    let settled = false
    const finish = (fn: () => void): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      window.removeEventListener('message', onMessage)
      fn()
    }
    const onMessage = (event: MessageEvent): void => {
      if (event.source !== window) return
      const data = event.data as BridgeResponse | null
      if (data === null || data === undefined) return
      if (data.source !== SOURCE || data.kind !== 'response' || data.id !== id) return
      if (data.ok !== true) {
        finish(() => reject(new Error(data.error ?? notInstalledHint())))
        return
      }
      finish(() => resolve({ path: data.path ?? '' }))
    }
    const timer = setTimeout(() => finish(() => reject(new Error(notInstalledHint()))), timeoutMs)
    window.addEventListener('message', onMessage)
    window.postMessage(
      { source: SOURCE, kind: 'request', id, type: 'pick_folder' },
      window.location.origin,
    )
  })
}
