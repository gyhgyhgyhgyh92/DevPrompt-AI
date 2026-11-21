import { contextBridge, ipcRenderer } from 'electron'

/**
 * 桌面壳暴露给渲染进程的桥（`window.devpromptDesktop`）。
 *
 * 前端 `api/nativeFolder.ts` 优先走此桥；无桥（Web 形态）时原样回落浏览器扩展链路。
 * contextIsolation 下只能传可结构化克隆的值，故只暴露函数与平台标识。
 */
const bridge = {
  /** 弹系统原生目录选择器；用户取消时 path 为空串（与扩展桥同构）。 */
  pickFolder: (): Promise<{ path: string }> => ipcRenderer.invoke('pick-folder'),
  platform: process.platform,
}

contextBridge.exposeInMainWorld('devpromptDesktop', bridge)
