/**
 * 桌面端自动更新桥（2026-11-27）。
 *
 * 主进程持有 electron-updater；渲染进程只读状态、触发动作。Web 形态没有此桥，
 * `isUpdateSupported()` 恒为 false，设置页按不支持渲染。
 */

import { isDesktopRuntime } from './nativeFolder'

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

export interface DesktopUpdatesBridge {
  getState(): Promise<UpdateState>
  check(): Promise<UpdateState>
  download(): Promise<UpdateState>
  install(): Promise<UpdateState>
  dismiss(): Promise<UpdateState>
  onState(callback: (state: UpdateState) => void): () => void
}

function updatesBridge(): DesktopUpdatesBridge | undefined {
  if (!isDesktopRuntime()) return undefined
  return window.devpromptDesktop?.updates
}

export function isUpdateSupported(): boolean {
  return updatesBridge() !== undefined
}

export function getUpdateState(): Promise<UpdateState | null> {
  const bridge = updatesBridge()
  return bridge === undefined ? Promise.resolve(null) : bridge.getState()
}

export function checkForUpdates(): Promise<UpdateState | null> {
  const bridge = updatesBridge()
  return bridge === undefined ? Promise.resolve(null) : bridge.check()
}

export function downloadUpdate(): Promise<UpdateState | null> {
  const bridge = updatesBridge()
  return bridge === undefined ? Promise.resolve(null) : bridge.download()
}

export function installUpdate(): Promise<UpdateState | null> {
  const bridge = updatesBridge()
  return bridge === undefined ? Promise.resolve(null) : bridge.install()
}

export function dismissUpdate(): Promise<UpdateState | null> {
  const bridge = updatesBridge()
  return bridge === undefined ? Promise.resolve(null) : bridge.dismiss()
}

export function subscribeUpdateState(callback: (state: UpdateState) => void): () => void {
  const bridge = updatesBridge()
  return bridge === undefined ? () => undefined : bridge.onState(callback)
}
