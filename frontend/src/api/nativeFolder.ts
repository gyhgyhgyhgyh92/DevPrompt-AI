/**
 * 系统原生文件夹选择器（2026-10-19）：经浏览器扩展 -> native messaging host ->
 * Windows 原生对话框，取回**绝对路径**。
 *
 * 为什么必须走扩展：浏览器的文件选择 API 刻意不暴露绝对路径，而 GET /project/scan
 * 需要绝对路径去服务端扫描。详见 browser-extension/README.md。
 */
import { errorMessage } from '../components/settings/errorMessage'

const SOURCE = 'devprompt-ai'
/** 原生对话框是用户驱动的模态交互，超时放宽（与历史实现一致）。 */
const PICK_TIMEOUT_MS = 310_000

/** 未装扩展 / 不支持时的统一文案：说清成因与补救。 */
export const NOT_INSTALLED_HINT =
  '未能调起系统文件夹选择器：需要安装 DevPrompt AI 原生文件夹选择器扩展' +
  '（仅 Chrome/Edge 系；先运行 pwsh -File scripts/install_native_picker.ps1，再在扩展页加载已解压的扩展）'

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

/** 把异常转成用户可读文案（与设置面板同一口径）。 */
export function nativePickErrorText(error: unknown): string {
  return errorMessage(error, '系统文件夹选择器不可用')
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
    return Promise.reject(new Error('非浏览器环境，无法调起系统文件夹选择器'))
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
        finish(() => reject(new Error(data.error ?? NOT_INSTALLED_HINT)))
        return
      }
      finish(() => resolve({ path: data.path ?? '' }))
    }
    const timer = setTimeout(() => finish(() => reject(new Error(NOT_INSTALLED_HINT))), timeoutMs)
    window.addEventListener('message', onMessage)
    window.postMessage(
      { source: SOURCE, kind: 'request', id, type: 'pick_folder' },
      window.location.origin,
    )
  })
}
