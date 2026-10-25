/**
 * DevPrompt AI 桌面壳主进程（仅 Windows）。
 *
 * 职责：拉起 Python sidecar → 解析 stdout 就绪协议 → 建窗加载 → 退出杀进程树。
 * 业务逻辑全在 sidecar（MUST-10 单一业务来源）：本文件只做进程编排与窗口管理。
 */

import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'

//: sidecar stdout 就绪协议前缀（与 src/devprompt_ai/desktop.py 对齐，改一处须改两处）
const READY_PREFIX = 'DPROMPT_READY'
const READY_TIMEOUT_MS = 30_000
//: Windows 上 child.kill() 不杀进程树，宽限后强杀（taskkill /T /F）
const KILL_GRACE_MS = 500

// ---------- 路径解析：打包态（Inno 安装目录）与开发态（仓库） ----------

const repoRoot = path.resolve(__dirname, '..', '..')

function sidecarExe(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'sidecar', 'devprompt-ai-desktop.exe')
    : path.join(repoRoot, '.venv', 'Scripts', 'devprompt-ai-desktop.exe')
}

function frontendDist(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'frontend-dist')
    : path.join(repoRoot, 'frontend', 'dist')
}

/** 安装包随附的检索工具（rg/ctags）；开发态不注入，走项目自带定位链。 */
function bundledTool(name: 'rg' | 'ctags'): string | undefined {
  const candidate = path.join(process.resourcesPath, 'tools', `${name}.exe`)
  return fs.existsSync(candidate) ? candidate : undefined
}

// ---------- sidecar 生命周期 ----------

let sidecar: ChildProcess | undefined
let isQuitting = false

function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

function killSidecar(): void {
  const child = sidecar
  if (!child || child.killed || child.exitCode !== null) return
  const pid = child.pid
  child.kill()
  if (pid === undefined) return
  setTimeout(() => {
    if (isAlive(pid)) {
      spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore' }).unref()
    }
  }, KILL_GRACE_MS)
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
    })
    sidecar = child

    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      killSidecar()
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
    minWidth: 1024,
    minHeight: 700,
    title: 'DevPrompt AI',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
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

// ---------- 应用装配 ----------

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
      await createWindow(port)
    } catch (err) {
      dialog.showErrorBox('DevPrompt AI 启动失败', err instanceof Error ? err.message : String(err))
      app.quit()
    }
  })

  app.on('window-all-closed', () => {
    app.quit()
  })

  app.on('before-quit', () => {
    isQuitting = true
    killSidecar()
  })
}
