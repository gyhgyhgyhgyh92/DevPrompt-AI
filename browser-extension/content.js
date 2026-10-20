/**
 * 内容脚本：页面世界 <-> 扩展隔离世界的桥。
 *
 * 浏览器的文件选择 API 刻意不暴露绝对路径（showDirectoryPicker 只给 dirHandle，
 * webkitdirectory 只给相对路径），而本项目 GET /project/scan 需要绝对路径去
 * os.scandir，故唯一可行链路是「页面 -> 扩展 -> native messaging host -> 原生对话框」。
 * 页面拿不到 chrome.*，故用 window.postMessage 与本脚本通信。
 *
 * 注意：**content script 不能直接调 sendNativeMessage**（Chrome 官方文档：仅扩展页与
 * service worker 可用），必须转发给 background.js。
 *
 * 协议（source 标记与页面共用，避免与其他 postMessage 混淆）：
 *   页面 -> 扩展: { source, kind: 'request',  id, type: 'pick_folder' }
 *   扩展 -> 页面: { source, kind: 'response', id, ok, path?, error? }
 */
const SOURCE = 'devprompt-ai'

// 页面 -> 扩展：转给 background service worker（由它 sendNativeMessage）
window.addEventListener('message', (event) => {
  if (event.source !== window) return
  const data = event.data
  if (data === null || typeof data !== 'object' || data.source !== SOURCE) return
  if (data.kind !== 'request' || typeof data.id !== 'string') return
  chrome.runtime.sendMessage({ type: data.type }, (reply) => {
    const host = reply && reply.reply ? reply.reply : null
    window.postMessage(
      {
        source: SOURCE,
        kind: 'response',
        id: data.id,
        ok: Boolean(reply && reply.ok),
        path: typeof (host && host.path) === 'string' ? host.path : '',
        error: host && typeof host.error === 'string' ? host.error : String((reply && reply.error) || 'native host 未返回结果'),
      },
      window.location.origin,
    )
  })
})
