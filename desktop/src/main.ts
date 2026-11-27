/**
 * DevPrompt AI 桌面壳主进程（Windows / macOS / Linux）。
 *
 * 职责：拉起 Python sidecar → 解析 stdout 就绪协议 → 建窗加载 → 退出杀进程树。
 * 业务逻辑全在 sidecar（MUST-10 单一业务来源）：本文件只做进程编排与窗口管理。
 */

import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { UpdateService } from './updater'

//: sidecar stdout 就绪协议前缀（与 src/devprompt_ai/desktop.py 对齐，改一处须改两处）
const READY_PREFIX = 'DPROMPT_READY'
const READY_TIMEOUT_MS = 30_000
//: 更新安装前必须等 sidecar 真正退出（Windows 文件占用）；先优雅、后强杀
const STOP_GRACE_MS = 3_000
const STOP_FORCE_MS = 2_000

// ---------- 平台判定 ----------
const IS_WINDOWS = process.platform === 'win32'
const IS_MACOS = process.platform === 'darwin'

/** 可执行文件名：Windows 带 .exe，POSIX 不带（PyInstaller 产物规则）。 */
function exeName(stem: string): string {
  return IS_WINDOWS ? `${stem}.exe` : stem
}

// ---------- 路径解析：打包态（安装目录）与开发态（仓库） ----------

const repoRoot = path.resolve(__dirname, '..', '..')

function sidecarExe(): string {
  const stem = exeName('devprompt-ai-desktop')
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'sidecar', stem)
  }
  //: 虚拟环境可执行目录：Windows 是 Scripts，POSIX 是 bin
  const venvBin = IS_WINDOWS ? path.join('.venv', 'Scripts') : path.join('.venv', 'bin')
  return path.join(repoRoot, venvBin, stem)
}

function frontendDist(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'frontend-dist')
    : path.join(repoRoot, 'frontend', 'dist')
}

/** 安装包随附的检索工具（rg/ctags）；开发态不注入，走项目自带定位链。 */
function bundledTool(name: 'rg' | 'ctags'): string | undefined {
  const candidate = path.join(process.resourcesPath, 'tools', exeName(name))
  return fs.existsSync(candidate) ? candidate : undefined
}

// ---------- sidecar 生命周期 ----------

let sidecar: ChildProcess | undefined
let isQuitting = false

/** 等待子进程退出；超时返回 false，不抛错。 */
function waitForExit(child: ChildProcess, timeoutMs: number): Promise<boolean> {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true)
  return new Promise<boolean>((resolve) => {
    let settled = false
    const finish = (value: boolean): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      child.off('exit', onExit)
      resolve(value)
    }
    const onExit = (): void => finish(true)
    const timer = setTimeout(() => finish(false), timeoutMs)
    child.once('exit', onExit)
    // 监听器挂上之前已经退出：exitCode/signalCode 已落值，直接结束等待。
    if (child.exitCode !== null || child.signalCode !== null) finish(true)
  })
}

let stopPromise: Promise<boolean> | undefined

/** 停 sidecar：先优雅退出，宽限后未退出再 taskkill /T /F 或杀进程组。 */
function stopSidecar(): Promise<boolean> {
  if (stopPromise !== undefined) return stopPromise
  stopPromise = (async (): Promise<boolean> => {
    const child = sidecar
    if (child === undefined || child.exitCode !== null || child.signalCode !== null) return true
    const pid = child.pid
    try {
      child.kill()
    } catch {
      //: 已经退出时忽略
    }
    if (await waitForExit(child, STOP_GRACE_MS)) return true
    if (pid === undefined) return true
    if (IS_WINDOWS) {
      //: Windows 无进程组概念，用 taskkill /T /F 强杀整棵树
      spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore' }).unref()
    } else {
      //: POSIX 下 sidecar 以 detached 启动、自成进程组，杀负 pid 即杀整组
      try {
        process.kill(-pid, 'SIGKILL')
      } catch {
        //: 进程组已消失，忽略
      }
    }
    return waitForExit(child, STOP_FORCE_MS)
  })().finally(() => {
    stopPromise = undefined
  })
  return stopPromise
}

function startSidecar(): Promise<number> {
  const exe = sidecarExe()
  if (!fs.existsSync(exe)) {
    return Promise.reject(new Error(`未找到 sidecar 可执行文件：${exe}`))
  }

  const env: NodeJS.ProcessEnv = { ...process.env }
  env.DEVPROMPT_FRONTEND_DIST = frontendDist()
  const rg = bundledTool('rg')
  const ctags = bundledTool('ctags')
  if (rg !== undefined) env.DPROMPT_RG_PATH = rg
  if (ctags !== undefined) env.DPROMPT_CTAGS_PATH = ctags

  return new Promise<number>((resolve, reject) => {
    let buffer = ''
    let settled = false

    const child = spawn(exe, [], {
      cwd: path.dirname(exe),
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      //: POSIX 需 detached 自成进程组，退出时才能整组杀掉；Windows 需隐藏控制台窗
      detached: !IS_WINDOWS,
      windowsHide: IS_WINDOWS,
    })
    sidecar = child

    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      void stopSidecar()
      reject(new Error(`sidecar 未在 ${READY_TIMEOUT_MS / 1000} 秒内就绪`))
    }, READY_TIMEOUT_MS)

    // stdout 只有单行就绪协议（sidecar 保证）；access 日志走 stderr 转发到本进程
    child.stdout?.on('data', (chunk: Buffer) => {
      if (settled) return
      buffer += chunk.toString('utf8')
      const nl = buffer.indexOf('\n')
      if (nl === -1) return
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      if (!line.startsWith(READY_PREFIX)) return
      try {
        const port = (JSON.parse(line.slice(READY_PREFIX.length).trim()) as { port: number }).port
        if (!Number.isInteger(port) || port <= 0) {
          throw new Error(`ready 协议端口非法：${String(port)}`)
        }
        settled = true
        clearTimeout(timer)
        resolve(port)
      } catch (err) {
        settled = true
        clearTimeout(timer)
        reject(err instanceof Error ? err : new Error('ready 协议解析失败'))
      }
    })

    child.stderr?.on('data', (chunk: Buffer) => {
      process.stderr.write(`[sidecar] ${chunk.toString('utf8')}`)
    })

    child.on('exit', (code) => {
      if (!settled) {
        settled = true
        clearTimeout(timer)
        reject(new Error(`sidecar 提前退出（exit=${code ?? 'null'}）`))
        return
      }
      // 就绪后死亡：服务异常须给用户可操作提示，而非留在空白窗口里
      if (!isQuitting) {
        dialog.showErrorBox('DevPrompt AI', `后端服务已退出（exit=${code ?? 'null'}），应用将关闭。`)
        app.quit()
      }
    })
  })
}

// ---------- 窗口 ----------

let mainWindow: BrowserWindow | undefined

async function createWindow(port: number): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    // 最小尺寸容纳桌面工作台全量 chrome：48px 活动栏 + 296px 二级侧栏 + 主区
    minWidth: 1100,
    minHeight: 720,
    title: 'DevPrompt AI',
    autoHideMenuBar: true,
    // 窗口底色 = 前端画布色（--color-surface-base 浅色值），消除加载期白闪
    backgroundColor: '#ebeff5',
    // 先隐藏，内容渲染完成后再显示，避免看到未上色的空窗
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })
  mainWindow.on('closed', () => {
    mainWindow = undefined
  })
  await mainWindow.loadURL(`http://127.0.0.1:${port}`)
}

// ---------- IPC：原生文件夹选择 ----------

ipcMain.handle('pick-folder', async (): Promise<{ path: string }> => {
  const options: Electron.OpenDialogOptions = {
    title: '选择项目文件夹（本地）',
    properties: ['openDirectory'],
  }
  const result =
    mainWindow !== undefined
      ? await dialog.showOpenDialog(mainWindow, options)
      : await dialog.showOpenDialog(options)
  if (result.canceled || result.filePaths.length === 0) {
    return { path: '' }
  }
  return { path: result.filePaths[0] ?? '' }
})

// ---------- 自动更新 ----------

let updateService: UpdateService | undefined

/** 更新安装前：置 isQuitting 并等待 sidecar 退出；失败回滚标志。 */
async function stopSidecarForUpdate(): Promise<boolean> {
  isQuitting = true
  const stopped = await stopSidecar()
  if (!stopped) isQuitting = false
  return stopped
}

function registerUpdateIpc(service: UpdateService): void {
  ipcMain.handle('updates:get-state', () => service.getState())
  ipcMain.handle('updates:check', async () => {
    await service.check(true)
    return service.getState()
  })
  ipcMain.handle('updates:download', async () => {
    await service.download()
    return service.getState()
  })
  ipcMain.handle('updates:install', async () => {
    await service.install()
    return service.getState()
  })
  ipcMain.handle('updates:dismiss', () => {
    service.dismiss()
    return service.getState()
  })
}

// ---------- 应用装配 ----------

//: 已就绪的 sidecar 端口；macOS 关闭窗口后应用仍驻留，需据此重建窗口
let sidecarPort: number | undefined

// 单实例：二次启动聚焦既有窗口，不起第二个 sidecar（MUST-11 串行写入的另一道保险）
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow === undefined) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  })

  void app.whenReady().then(async () => {
    try {
      const port = await startSidecar()
      sidecarPort = port
      updateService = new UpdateService({
        getWindow: () => mainWindow,
        stopSidecarForUpdate,
        onState: (state) => {
          if (mainWindow !== undefined && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('updates:state', state)
          }
        },
      })
      registerUpdateIpc(updateService)
      await createWindow(port)
      updateService.init()
    } catch (err) {
      dialog.showErrorBox('DevPrompt AI 启动失败', err instanceof Error ? err.message : String(err))
      app.quit()
    }
  })

  app.on('window-all-closed', () => {
    //: macOS 惯例：关闭所有窗口后应用仍驻留，可从 Dock 重新打开
    if (!IS_MACOS) app.quit()
  })

  if (IS_MACOS) {
    app.on('activate', async () => {
      //: macOS：Dock 点击应用图标时重建窗口
      if (mainWindow !== undefined || sidecarPort === undefined) return
      await createWindow(sidecarPort)
    })
  }

  app.on('before-quit', () => {
    isQuitting = true
    updateService?.dispose()
    void stopSidecar()
  })
}
