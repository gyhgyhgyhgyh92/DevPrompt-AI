# DevPrompt AI 桌面壳（Electron + Python sidecar，Windows / macOS / Linux）

把 Web 形态的 DevPrompt AI 包成可安装的桌面应用。业务逻辑零改动：桌面壳只负责
**拉起 sidecar、开窗、原生对话框、进程清理**，served 的就是
`devprompt_ai.interfaces.api.app:app` 同一实例（MUST-10 单一业务来源）。

```
Electron 主进程（desktop/src/main.ts）
  ├─ spawn devprompt-ai-desktop[.exe]（PyInstaller one-dir，resources/sidecar/）
  │    └─ 127.0.0.1 随机端口起 uvicorn，stdout 单行 DPROMPT_READY {"port": N}
  ├─ BrowserWindow 加载 http://127.0.0.1:<port>（/api/v1 相对路径天然同源）
  ├─ preload contextBridge 暴露 window.devpromptDesktop.pickFolder()
  │    └─ 前端 api/nativeFolder.ts 优先走桥，无桥回落浏览器扩展链路
  └─ 退出杀进程树（kill → 500ms 宽限 → Windows taskkill /T /F；POSIX 杀进程组）
```

## 界面形态（Trae 式工作台，2026-11-17）

桌面形态不再是「网页套壳」，而是一套**桌面工作台**骨架；Web 形态维持原布局不变。

```
┌────────────────────────────────────────────────────────────┐
│ ◉ DevPrompt AI      [项目路径 chip]        ●API 正常   ⚙    │ 48px 品牌栏
├────┬───────────────┬───────────────────────────────────────┤
│ ▣  │ 项目          │                                       │
│ ☰  │ ＋ 新建会话   │        对话工作区（960px 宽列）        │ 48px 活动栏
│ ◎  │ ▸ project-a   │                                       │ + 296px 侧栏
│    │   会话 1      │   用户气泡 / AI 回复块                 │
│ ⚙  │   会话 2      │   ────────────────────                │
│    │               │   [ 输入胶囊 820px          ↑ ]        │
├────┴───────────────┴───────────────────────────────────────┤
│ 运行日志 ▾  seq 128 · action · rg 命中 3 行            ▸ 240px │ 底部面板（可折叠）
├────────────────────────────────────────────────────────────┤
│ D:/ws/repo  │ sess-3f2a  DONE  ●SSE  │ api.deepseek  ●正常 │ 22px 状态栏
└────────────────────────────────────────────────────────────┘
```

| 区块 | 位置 | 职责 | 实现 |
|---|---|---|---|
| 活动栏 | 左侧 48px | 对话 / 历史 / 可观测性 / 设置 四个入口 | `frontend/src/components/desktop/DesktopActivityRail.tsx` |
| 二级侧栏 | 296px | 项目与历史会话列表 | 复用 `ProjectSidebar`（桌面态宽度覆盖） |
| 主区 | 弹性 | 对话工作台 | 复用 `OptimizePage`（桌面态列宽 960px / 输入胶囊 820px） |
| 运行日志 | 底部 240px，可折叠 | 实时会话事件流 | `DesktopBottomPanel.tsx`（复用 `useSessionEventStream`） |
| 状态栏 | 底部 22px | 项目路径 / 会话短码 / 状态机态 / SSE / API / 当前模型 | `DesktopStatusBar.tsx` |

**形态判定**：`frontend/src/api/nativeFolder.ts` 的 `isDesktopRuntime()`——判据是
preload 桥 `window.devpromptDesktop` 的**存在性**（不做 UA/平台嗅探）。桥在即桌面，
桥不在即 Web。外壳以 `data-shell="desktop" | "web"` 分支，桌面专属 chrome 只在桌面形态
进 DOM（故运行日志的 SSE 订阅在 Web 形态根本不会发生）。

**视觉基调**：Trae 的「背景色块分层 + 发丝描边」用本项目既有 token 表达
（`--color-surface-base/raised` 三级表面、`--divider` / `--color-border-subtle` 描边、
`--hover` / `--selected` 交互底色），**未新增任何色值变量**，配色体系与字体基调不变。

## 前置

| 工具 | 版本 | 用途 |
|---|---|---|
| Node.js | ≥ 22.12（实测 24.14） | 壳构建 |
| pnpm | ≥ 10.15 | 壳依赖管理 |
| uv | 任意 | Python 依赖 / PyInstaller |
| ripgrep / universal-ctags | 任意 | 随包检索工具；缺任一则打包失败 |

Electron 二进制经 npmmirror 下载（本机网络无法直连 GitHub，`desktop/.npmrc` 已配
`electron_mirror`）；pnpm 10 默认不跑依赖安装脚本，`package.json` 的
`pnpm.onlyBuiltDependencies` 已为 electron 开白名单。

> Inno Setup 已不再需要：安装包改由 electron-builder 产出（Windows 用 NSIS
> target，与原 Inno Setup 等价且免去 Windows-only 工具依赖）。

## 打包（electron-builder）

`desktop/electron-builder.yml` 一份配置产出三个目标：

| 平台 | target | 产物名 |
|---|---|---|
| Windows x64 | nsis | `DevPromptAI-<version>-win-x64.exe` |
| macOS arm64 | dmg | `DevPromptAI-<version>-mac-arm64.dmg` |
| Linux x86_64 | AppImage | `DevPromptAI-<version>-linux-x86_64.AppImage` |

产物名与官网下载区的直链严格一致，改动须同步 `website/src/lib/links.ts`。

**未签名**：项目未购买代码签名证书。macOS 的 dmg 不签名、不公证（`identity: null`、
`notarize: false`），首次打开需用户在「系统设置 → 隐私与安全性」放行；Windows 首次运行
有 SmartScreen 提示。构建时设 `CSC_IDENTITY_AUTO_DISCOVERY=false` 可避免探测证书失败。

**产物名与内容由 CI 保证**：`PyInstaller 不能交叉编译`，sidecar 必须各平台本机构建，
三平台安装包由 `.github/workflows/release.yml` 的 matrix 并行产出。

## 开发态跑壳（不需要安装包）

```powershell
# 一次性准备
uv sync --extra dev                      # 生成 .venv/Scripts/devprompt-ai-desktop.exe
pnpm -C frontend build                   # 壳开发态直接读仓库 frontend/dist
pnpm -C desktop install                  # 下载 Electron 二进制（经镜像）
pnpm -C desktop start                    # tsc 编译 + 起 Electron 窗口
```

开发态下 sidecar 取 `.venv/Scripts/devprompt-ai-desktop.exe`（POSIX 为 `.venv/bin/`），
rg/ctags 走 `common/process.py` 的既有定位链（PATH → 环境变量 → 平台常见安装目录扫描），
不需要打包。

## 冒烟与打包

```bash
# 只验证打包后的 sidecar 能跑（模拟安装态环境变量，不等安装包）
uv run python desktop/scripts/smoke-sidecar.py

# 完整流水线：前端构建 → 壳编译 → PyInstaller sidecar → 检索工具随包 → 安装包
uv run python desktop/scripts/build-desktop.py
# 产物：desktop/dist/packages/
```

版本号唯一来源是 `pyproject.toml` 的 `version`，由 PyInstaller spec 读取（不手抄）。
`desktop/dist/` 与 `.tmp/` 已在 .gitignore，二进制产物不入库（MUST-23）。

## 安装包布局（electron-builder 产出）

```
DevPrompt AI.exe / DevPrompt AI.app / DevPrompt AI   # Electron 运行时
resources/
  app.asar                         # 壳本体（main/preload + electron-updater 等生产依赖）
  frontend-dist/                   # 前端构建产物（与 Web 版同一份）
  sidecar/                         # PyInstaller one-dir（exe + _internal/）
  tools/                           # rg[.exe] + ctags[.exe]（构建时收集）
```

Windows 安装位置 `{localappdata}\Programs\DevPrompt AI`（每用户，免 UAC）；
macOS 为 `/Applications` 下的 `.app`；Linux AppImage 免安装，`chmod +x` 后直接运行。
覆盖安装仍可作为升级/回退手段；Windows 0.3.0 起改用自动更新（见下）。

## 自动更新（Windows，2026-11-27）

- 仅 Windows x64、stable 通道；macOS/Linux 仍靠手动覆盖安装（macOS 未签名，Squirrel.Mac 不能工作）。
- 检查节奏：窗口就绪 10 秒后首次检查，之后每 6 小时（带抖动）；设置中心「关于与更新」可手动检查。
- 源顺序：`ghfast.top` → `ghproxy.net` → `gh-proxy.com` → GitHub 直连；每源 8 秒超时，GitHub 可达时交叉校验 `latest.yml` 的 version/sha512。
- 交互：发现新版本先弹窗询问；下载完成再询问「立即重启 / 稍后」，不会静默安装。
- 安装前：停 sidecar（等待退出，失败则 `taskkill /T /F`）；备份 `~/.devprompt-ai` 的 DB 与 `settings.json`（保留 2 份）；再以 `--updated /S` 静默覆盖安装。
- 回滚：只做 roll-forward（发更高版本修复）；保留最近 2 个版本的安装包，必要时手动覆盖并按需恢复备份。
- 安全边界：更新包未签名，只校验 `latest.yml` 的 SHA512；镜像与 GitHub 的清单会交叉校验，但无法防御镜像两侧同时被投毒。
- 发布：`.github/workflows/release.yml` 在 stable tag 上更新 `updates` 预发布 tag（`latest.yml` + exe + blockmap）。`updates` 是自动更新指针，请勿手动下载。
- 本地联调：非打包态设置 `DPROMPT_UPDATE_BASE_URL=http://127.0.0.1:9000/`（仅此环境变量生效），并在 `desktop/dev-app-update.yml` 放同源 `provider/url`；目录里放 `latest.yml` 与安装包。
- 打包态静默安装验收必须走真实 `updates` tag：先发布 0.3.0 并安装，再发布 0.3.1 验证检查/下载/重启；本地 URL 覆盖只对非打包态生效。

## 已知边界

- **macOS/Linux 无自动更新**：Windows 才有更新器；macOS 需先购买签名证书并产出 zip 才能接 Squirrel.Mac
- **无代码签名与公证**：Windows 有 SmartScreen 提示，macOS 需用户手动放行
- **无应用图标**：暂用 Electron 默认图标（frontend 只有 favicon.svg，转换 .ico/icns 未做）
- **sidecar 异常进程残留**：若主进程被任务管理器强杀，sidecar 可能残留占着 DB；
  极端情况需手动结束 `devprompt-ai-desktop` 进程
