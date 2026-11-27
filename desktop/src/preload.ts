import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'

/**
 * 桌面壳暴露给渲染进程的桥（`window.devpromptDesktop`）。
 *
 * 前端 `api/nativeFolder.ts` 优先走此桥；无桥（Web 形态）时原样回落浏览器扩展链路。
 * `updates` 是自动更新状态桥：主进程持有更新器，渲染进程只读状态与触发动作。
 * contextIsolation 下只能传可结构化克隆的值，故只暴露函数与平台标识。
 */
const bridge = {
  /** 弹系统原生目录选择器；用户取消时 path 为空串（与扩展桥同构）。 */
  pickFolder: (): Promise<{ path: string }> => ipcRenderer.invoke('pick-folder'),
  platform: process.platform,
  updates: {
    getState: (): Promise<unknown> => ipcRenderer.invoke('updates:get-state'),
    check: (): Promise<unknown> => ipcRenderer.invoke('updates:check'),
    download: (): Promise<unknown> => ipcRenderer.invoke('updates:download'),
    install: (): Promise<unknown> => ipcRenderer.invoke('updates:install'),
    dismiss: (): Promise<unknown> => ipcRenderer.invoke('updates:dismiss'),
    /** 订阅主进程状态；返回取消订阅函数（页面卸载时调用）。 */
    onState: (callback: (state: unknown) => void): (() => void) => {
      const listener = (_event: IpcRendererEvent, state: unknown): void => callback(state)
      ipcRenderer.on('updates:state', listener)
      return () => ipcRenderer.off('updates:state', listener)
    },
  },
}

contextBridge.exposeInMainWorld('devpromptDesktop', bridge)
