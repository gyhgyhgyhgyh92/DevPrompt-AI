# DevPrompt AI

> 把一句模糊的需求，变成**带行号与token 出处、可被 ripgrep 反向验证**的工程级提示词。

本地运行的 Web 工具。给定一个代码仓库与一句自然语言需求，它会先**检索定位**（符号表 → 候选集 → 全文定位 → 七项事实验证），信息不足时**反问澄清**，最后产出 **A/B/C 三套**信息完备度递进的提示词方案，并给出**诚实的推荐标记**。

---

## 核心特点

| | |
|---|---|
| **取证优先** | 不编造。候选集硬上限 25 条、仅含符号名与路径不含代码正文；七项事实逐项验证真伪并附证据 |
| **按需追问** | 由「具体未知项」驱动批量反问；**信息充足时不提问**（七项取证全过即丢弃模型给出的问题直接生成），已答项按语义归一化去重、同一话题不再追问；随时可「直接生成」走保守路径 |
| **不越级输出** | 信息只够 A 档就只出 A 档。C 档才给行号，且要求行号必须真实存在，否则降级表述 |
| **诚实推荐** | 置信度优先于分差：置信度不足时**不标推荐**并说明原因，绝不假装确定 |
| **评分可解释** | 总分即适配度（0~1，模型按五维打分后归一化），不用不可解释的加权魔数；置信度门禁（0.6 / 0.4）与分差双阈值（0.12 / 0.5）都写死在领域层并有表驱动测试 |
| **过程可见** | 检索与取证的真实命令、命中行数与输出摘要逐条展示（路径与 stderr 均脱敏）；检索失败也会留下一张带 `Exit code` 的失败卡片，不会静默；结束后整组收成一行摘要，可展开回看 |
| **本地优先** | 单进程本地服务，SQLite 单文件存储，密钥只落 0600 文件不进库不进日志 |
| **可验证锚点** | C 档方案给出的路径与行号来自真实取证，可直接 `rg -n` 复核 |

---

## 快速启动

### 前置要求

| 工具 | 版本 | 用途 |
|---|---|---|
| [Python](https://www.python.org/) | ≥ 3.10（推荐 3.13） | 后端运行时 |
| [uv](https://docs.astral.sh/uv/) | 任意 | Python 依赖管理 |
| [Node.js](https://nodejs.org/) | ≥ 20.19 或 ≥ 22.12（Vite 7 引擎要求，实测 24.x 可用） | 前端构建 |
| [pnpm](https://pnpm.io/) | ≥ 10.15（实测 10.33） | 前端依赖管理 |
| [ripgrep](https://github.com/BurntSushi/ripgrep) | 任意 | 代码检索（**必需**） |
| [universal-ctags](https://github.com/universal-ctags/ctags) | 任意 | 符号表构建（**必需**） |

> **不必手工配置 PATH**：项目会依次尝试 ①系统 PATH → ②环境变量
> `DPROMPT_RG_PATH` / `DPROMPT_CTAGS_PATH` → ③WinGet 与编辑器内置工具目录扫描，
> 自动定位这两个可执行文件。找不到时会在启动自检（`GET /api/v1/health`）中报告并给出安装指引。
> 桌面安装包已随附这两个二进制（`resources\tools\`），终端用户无需安装。

> **已验证环境**（2026-10-22，Windows）：uv 0.11.28 · Node v24.14.0 · pnpm 10.33.0 ·
> ripgrep 15.0.0 · Universal Ctags 6.1.0。下文命令均在该环境端到端跑通：
> `uv sync` → `pnpm build` → 启动后 `GET /api/v1/health` 六项检查全绿。

### 三步启动

> 已初始化过的机器（`.venv` 与 `frontend/node_modules` 均已存在）可跳过第 2、3 步，
> 直接进入下方「启动」；`.env` 已配置好模型服务时无需任何额外步骤。

```powershell
# 1. 配置（复制后填入你的模型服务信息）
copy .env.example .env

# 2. 安装依赖（后端 + 前端）
uv sync --frozen --extra dev
cd frontend; pnpm install --frozen-lockfile; cd ..

# 3. 构建前端产物（后端会单端口托管它）
cd frontend; pnpm build; cd ..
```

### 启动

```powershell
# 生产形态：单端口同时提供 API 与前端
uv run devprompt-ai
```

打开 <http://127.0.0.1:8000> 即可使用。

> 也可以 `uv run devprompt-ai --open` 自动打开浏览器，或 `--port 9000` 换端口，
> `--host 0.0.0.0` 供局域网访问。

---

## 开发模式

前后端分离热更新，**需两个终端**：

```powershell
# 终端 1：后端（普通启动；见下方关于 --reload 的说明）
uv run devprompt-ai
```

```powershell
# 终端 2：前端（Vite 热更新，/api 自动代理到 8000）
cd frontend
pnpm dev
```

打开 <http://localhost:5173>。前端 dev server 会把 `/api` 代理到后端 8000 端口。

> ⛔ **Windows 下 `--reload` 已被拒绝**：uvicorn 的热重载会把 asyncio 事件循环切成
> Selector，子进程随之不可用——`rg` / `ctags` / `git` 版本探测抛 `NotImplementedError`
> （启动体检三项变黄）、符号表扫描失效、原生文件夹选择器弹不出来。
> 因此 Windows 上带 `--reload` 启动会直接报错退出（退出码 2）；后端改完手动重启即可，
> 前端热更新交给 Vite。

> ⚠️ 端口必须一致：`main.py` 的 `DEFAULT_PORT` 与 `frontend/vite.config.ts` 的 proxy
> 目标同为 8000，改一侧需同步另一侧（有测试 `test_default_port_matches_vite_dev_proxy` 兜底）。

---

## 桌面端（Windows 安装包）

把同一套前端与后端打进一个可安装的桌面应用：安装后从开始菜单或桌面图标双击启动，
独立窗口承载完整界面，无需终端、无需浏览器、无需装 ripgrep/ctags。
业务逻辑与 Web 版**完全同一份**，两边共用 `~/.devprompt-ai` 数据，可交替使用。

### 用户使用

1. 获取 `desktop/dist/installer/DevPromptAISetup-<version>.exe`（由开发者构建产出）
2. 双击安装（每用户安装到 `%LOCALAPPDATA%\Programs\DevPrompt AI`，免 UAC；
   升级 = 重跑新安装包覆盖安装）
3. 首次运行若见 SmartScreen「未知发布方」提示，点「更多信息 → 仍要运行」
   （内部工具未购买代码签名证书，属信誉警告而非病毒判定）

### 开发者构建

```powershell
# 前置：Node ≥22.12 / pnpm ≥10.15 / uv / Inno Setup 7（iscc）
# Electron 二进制经 npmmirror 下载（desktop/.npmrc 已配镜像）

# 一条命令：前端构建 → 壳编译 → PyInstaller sidecar → staging → 安装包
pwsh -File desktop/scripts/build-desktop.ps1
# 产物：desktop/dist/installer/DevPromptAISetup-<version>.exe（版本号读 pyproject.toml）

# 只验证打包后的 sidecar 能跑（不等安装包，模拟安装态环境变量）
pwsh -File desktop/scripts/smoke-sidecar.ps1
```

架构、开发态跑壳、已知边界（无自动更新 / 无代码签名 / 无应用图标）见
`desktop/README.md`；桌面端需求条目 F-905-1~4 见功能清单。

---

## 首次使用

1. **配置模型**——启动后进「⚙ 设置 → 模型服务」，按供应商配置一次：
   - 选供应商、填 Base URL（如 `https://api.deepseek.com/v1`）与 API Key
     （只写入本地设置文件，0600 权限，不入库不进日志，回显恒脱敏）
   - 点「刷新模型列表」拉取该端点的可用模型，勾选需要的模型并保存
   - 启动页的模型下拉里选择当前生效项，可对该模型微调上下文窗口与思考强度

   也可以直接写进 `.env` 的 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`。

2. **选择项目目录**——启动卡片点「选择文件夹（本地）」，浏览并选定代码仓库根目录。

3. **描述需求**——用一句话说明想改什么，例如：
   > 把提交按钮改成 primary-500 主色，并补一个导出 CSV 的次要按钮

4. **回答反问**（如触发）——工具会列出它**具体不确定的项**，逐条回答即可。
   信息足够时直接出结果；想跳过就点「直接生成」（走 A 档保守路径）。

5. **取用结果**——每套方案都有「复制」按钮，C 档还附带可直接 `rg -n` 复核的路径与行号；
   服务端会把本轮结论写入会话历史，供侧边栏回看与多轮追加。

---

## 常用命令

| 命令 | 说明 |
|---|---|
| `uv run devprompt-ai` | 启动服务（单端口托管前端） |
| `.\.venv\Scripts\devprompt-ai.exe` | 同一入口的直接调用形式（uv 托管解释器异常时的兜底） |
| `uv run devprompt-ai --reload` | 源码变更自动重载（**Windows 下被拒绝、退出码 2，见「开发模式」**） |
| `uv run pytest` | 后端测试 |
| `uv run ruff check .` / `uv run ruff format .` | 后端 lint / 格式化 |
| `uv run mypy` | 后端类型检查 |
| `uv run python scripts/check_architecture.py` | 架构约束检查（7 项） |
| `cd frontend && pnpm dev` | 前端 dev server |
| `cd frontend && pnpm test` | 前端测试 |
| `cd frontend && pnpm check:contract` | 契约一致性校验 |
| `uv run python scripts/smoke_provider.py` | 供应商能力冒烟（遍历模型注册表） |
| `uv build` | 产出 wheel |

---

## 配置说明

完整清单见 `.env.example`。最关键的三项：

| 变量 | 必填 | 说明 |
|---|---|---|
| `LLM_BASE_URL` | ✅ | OpenAI 兼容端点，如 `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | ✅ | 模型服务密钥 |
| `LLM_MODEL` | ✅ | 模型标识 |

配置加载优先级：**进程环境变量 > 本地设置（设置中心写入的 `~/.devprompt-ai/settings.json`）> `.env` 文件 > 默认值**。
在设置中心改的配置会覆盖 `.env`，排查「改了 `.env` 没生效」时先看设置中心。

### 数据存放

| 内容 | 位置 |
|---|---|
| 会话（L1）、轮次（turn）与结论 | `~/.devprompt-ai/devprompt.db`（SQLite，WAL） |
| 模型配置与 API Key | `~/.devprompt-ai/settings.json`（0600） |
| 前端外观等本地设置 | 浏览器 localStorage（`devprompt:v1:` 前缀） |

启动时会自动体检数据库：结构缺失自动补建，损坏行移入 `forge_quarantine` 隔离表（**不删除**，修复报告可在 `/api/v1/health` 查看）。

---

## 项目结构

```
src/devprompt_ai/
├── main.py            ASGI 入口（console script：devprompt-ai）
├── service.py         ForgeService —— 唯一业务入口
├── state.py           优化流程状态机（9 态）
├── config.py          配置加载
├── domain/            纯领域逻辑（无 I/O）
│   ├── retrieval/     符号表 / 候选检索 / 全文定位 / 事实验证
│   ├── decision/      决策端口 / 事实探针 / 自适应反问
│   ├── generate/      三套方案编排与 A/B/C 模板
│   ├── ranking/       适配度归一 / 置信度门禁 / 双阈值推荐
│   ├── error_codes.py 集中错误码表
│   └── prompt_guard.py prompt 边界与注入防护
├── harness/           LLM 客户端 / 子进程 / 目录浏览
├── memory/            SQLite 存储 + 启动自愈
└── interfaces/api/    HTTP 薄壳（零业务逻辑）

frontend/src/
├── pages/             OptimizePage（主工作台）/ HistoryPage（历史会话）
├── components/        optimize（对话流 / 反问面板 / 输入卡片）/ settings / history / ui（通用件）
├── stores/            Zustand（optimize / settings / history）
├── hooks/             useSSE（进度流）、其它通用 hooks
├── schemas/           Zod 校验 + 契约生成类型 + 错误码文案表
└── api/               endpoints / client（统一请求与 SSE 帧解析）

desktop/               Electron 桌面壳（仅 Windows，2026-10-22）
├── src/main.ts        spawn sidecar / 解析就绪协议 / 建窗 / 单实例 / 退出杀树
├── src/preload.ts     contextBridge：window.devpromptDesktop.pickFolder()
├── pyinstaller/       sidecar 打包规格（one-dir + 版本资源）
├── installer/         Inno Setup 安装脚本
└── scripts/           build-sidecar / build-desktop / smoke-sidecar
```

架构规范、接口定义与错误码清单见 `DevPrompt-AI-项目架构文档.md`；开发约定见 `AGENTS.md`。

---

## 已知限制

| 限制 | 说明 |
|---|---|
| 无远端仓库，MUST-22 无技术强制力 | 仓库当前仅本地单仓库（`git remote -v` 为空），「main 禁止直推 + PR 双人评审」无法由平台强制执行，所有门禁均为本地等效验证；建立远端仓库并开启分支保护后此条自动失效 |
| 浏览器扩展仅 Chromium 系 | 原生文件夹选择器依赖 Chromium 系扩展 + native messaging；Firefox 未适配，未装扩展时没有回退入口 |
| 后端改代码需手动重启 | Windows 下 `--reload` 被拒绝（见「开发模式」），其余平台可用 |

---

## 常见问题

**Q：提示「找不到 ripgrep / ctags」**
项目会自动扫描 PATH、`DPROMPT_*_PATH` 环境变量与 WinGet/编辑器内置目录，多数情况
开箱即用。仍找不到时安装一个即可（Windows：`winget install BurntSushi.ripgrep.MSVC`
与 `winget install UniversalCtags.Ctags`）；或用环境变量指定完整路径：
```powershell
$env:DPROMPT_RG_PATH = "C:\path\to\rg.exe"
```

**Q：改了 `.env` 但不生效**
检查是否在设置中心改过配置——本地设置优先级高于 `.env`。

**Q：提示「LLM 调用超时」**
调大 `.env` 的 `LLM_TIMEOUT`（默认 60 秒）；C 档三套方案输出较长时尤其需要。

**Q：提示「服务商余额或配额不足」**
模型服务账户余额不足，充值后重试。

**Q：检索不到目标组件**
工具会反问确认。也可在需求里直接给出组件名或文件路径，能显著提高一次命中率。

**Q：端口被占用**
`uv run devprompt-ai --port 9000`；若同时改前端 dev proxy，记得同步 `vite.config.ts`。

**Q：接口返回 `405 Method Not Allowed`（例如答复反问时）**
说明**正在跑的后端进程是旧版本**，新路由没注册，请求落到单端口托管前端的静态兜底上（StaticFiles 只接受 GET/HEAD）。核验方式：

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/openapi.json).paths.PSObject.Properties.Name
# 最新版本应有 15 条，含 /api/v1/followup/{flow_id}/stream
```

确认后重启后端即可；前端 Vite dev（5173）不用动。

**Q：`uv run` 报 `无法遍历该路径，因为它包含不受信任的装入点 (os error 448)`**
uv 托管的 Python 安装目录被系统判定为不可遍历（常见于安全软件或目录被移动）。两种绕法：

```powershell
uv run --no-managed-python devprompt-ai        # 改用系统 Python
.\.venv\Scripts\devprompt-ai.exe               # 完全绕过 uv
```

---

## 许可证

内部项目，版权归项目所有者所有。
