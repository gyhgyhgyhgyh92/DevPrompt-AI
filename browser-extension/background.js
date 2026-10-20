/**
 * 后台 service worker：扩展请求 -> native messaging host。
 *
 * Chrome 官方文档明确：sendNativeMessage / connectNative **在 content script 中不可用**，
 * 只能用于扩展页与 service worker；content script 要与原生程序通信必须经此转发。
 * 宿主进程：devprompt-ai-pick-folder.exe（stdio：4 字节小端长度 + JSON）。
 */
const HOST = 'devprompt_ai.pick_folder'

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const data = message
  if (data === null || typeof data !== 'object' || data.type !== 'pick_folder') return undefined
  chrome.runtime
    .sendNativeMessage(HOST, { type: data.type })
    .then((reply) => sendResponse({ ok: Boolean(reply && reply.ok), reply }))
    .catch((error) => sendResponse({ ok: false, error: String((error && error.message) || error) }))
  return true // 异步 sendResponse
})
