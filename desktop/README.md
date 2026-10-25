# DevPrompt AI 桌面壳（Electron + Python sidecar，仅 Windows）

把 Web 形态的 DevPrompt AI 包成可安装的桌面应用。业务逻辑零改动：桌面壳只负责
**拉起 sidecar、开窗、原生对话框、进程清理**，served 的就是
`devprompt_ai.interfaces.api.app:app` 同一实例（MUST-10 单一业务来源）。

```
Electron 主进程（desktop/src/main.ts）
  ├─ spawn devprompt-ai-desktop.exe（PyInstaller one-dir，resources/sidecar/）
  │    └─ 127.0.0.1 随机端口起 uvicorn，stdout 单行 DPROMPT_READY {"port": N}
  ├─ BrowserWindow 加载 http://127.0.0.1:<port>（/api/v1 相对路径天然同源）
  ├─ preload contextBridge 暴露 window.devpromptDesktop.pickFolder()
  │    └─ 前端 api/nativeFolder.ts 优先走桥，无桥回落浏览器扩展链路
  └─ 退出杀进程树（kill → 500ms 宽限 → taskkill /T /F）
```

## 前置

| 工具 | 版本 | 用途 |
|---|---|---|
| Node.js | ≥ 22.12（实测 24.14） | 壳构建 |
| pnpm | ≥ 10.15 | 壳依赖管理 |
| uv | 任意 | Python 依赖 / PyInstaller |
| Inno Setup | 7.1.0（官网核实） | **仅打包安装器需要**；开发态跑壳不需要 |

Electron 二进制经 npmmirror 下载（本机网络无法直连 GitHub，`desktop/.npmrc` 已配
`electron_mirror`）；pnpm 10 默认不跑依赖安装脚本，`package.json` 的
`pnpm.onlyBuiltDependencies` 已为 electron 开白名单。

## 开发态跑壳（不需要安装包）

```powershell
# 一次性准备
uv sync --extra dev                      # 生成 .venv/Scripts/devprompt-ai-desktop.exe
pnpm -C frontend build                   # 壳开发态直接读仓库 frontend/dist
pnpm -C desktop install                  # 下载 Electron 二进制（经镜像）
pnpm -C desktop start                    # tsc 编译 + 起 Electron 窗口
```

开发态下 sidecar 取 `.venv/Scripts/devprompt-ai-desktop.exe`，rg/ctags 走
`common/process.py` 的既有定位链（PATH → 环境变量 → WinGet/编辑器目录扫描），
不需要打包。

## 冒烟与打包

```powershell
# 只验证打包后的 sidecar 能跑（模拟安装态环境变量，不等安装包）
pwsh -File desktop/scripts/smoke-sidecar.ps1

# 完整流水线：前端构建 → 壳编译 → PyInstaller sidecar → staging → Inno 安装包
pwsh -File desktop/scripts/build-desktop.ps1
# 产物：desktop/dist/installer/DevPromptAISetup-<version>.exe
```

版本号唯一来源是 `pyproject.toml` 的 `version`，由构建脚本注入 Inno（不手抄）。
`desktop/dist/` 与 `.tmp/` 已在 .gitignore，二进制产物不入库（MUST-23）。

## 安装包布局（staging → {app}）

```
DevPrompt AI.exe                  # Electron 运行时（重命名）
resources/
  app/                            # 壳本体（package.json + main.js + preload.js）
  frontend-dist/                  # 前端构建产物（与 Web 版同一份）
  sidecar/                        # PyInstaller one-dir（exe + _internal/）
  tools/                          # rg.exe + ctags.exe（构建时收集）
```

安装位置 `{localappdata}\Programs\DevPrompt AI`（`PrivilegesRequired=lowest`，
免 UAC）。覆盖安装即升级：固定 AppId + 固定安装目录，重跑安装包原地覆盖。
卸载时顺带清理 `resources\sidecar\.logs`（sidecar 的 LOG_DIR 默认相对其 CWD）。

## 已知边界

- **仅 Windows**：原生对话框、rg/ctags 收集、PyInstaller 产物均按 Windows 制作
- **无自动更新**：升级靠重跑安装包覆盖安装（用户已裁定 YAGNI）
- **无代码签名**：SmartScreen 会拦未知发布方，内部工具需用户点「仍要运行」
- **无应用图标**：暂用 Electron 默认图标（frontend 只有 favicon.svg，转换 .ico 未做）
- **sidecar 异常进程残留**：若主进程被任务管理器强杀，sidecar 可能残留占着 DB；
  覆盖安装时 Inno 的 CloseApplications 只对带窗口的进程生效，极端情况需手动结束
  `devprompt-ai-desktop.exe`
