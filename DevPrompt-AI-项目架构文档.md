# DevPrompt AI · 项目架构文档

> 版本 v1.1 · 2026-10-10（BREAKING：废除 CLI 形态，全面转向 Web-only 架构，批准人=项目所有者）
> 配套文档：`DevPrompt-AI-技术栈文档.md`、`DevPrompt-AI-功能清单.md`
> 适用范围：AI 辅助开发与团队协作

---

## 目录

- [第零章 架构总览](#第零章--架构总览)
- [第一部分 后端](#第一部分--后端)
  - [1. 环境与启动](#1-环境与启动)
  - [2. 全局规范](#2-全局规范)
  - [3. 接口一致性](#3-接口一致性)
  - [4. 核心支撑模块](#4-核心支撑模块)
- [第二部分 前端](#第二部分--前端)
  - [5. 目录结构](#5-目录结构)
  - [6. 状态管控](#6-状态管控)
  - [7. 组件标准](#7-组件标准)
  - [8. 请求封装](#8-请求封装)
- [第三部分 附录](#第三部分--附录)

---

# 第零章 · 架构总览

## 0.1 分层架构

DevPrompt AI 采用四层架构，依赖方向严格单向向下，不可逆向。

```
┌─────────────────────────────────────────────────────────────────┐
│  表现层  interfaces/                                               │
│  ┌──────────────────┐        ┌──────────────────┐               │
│  │  Web HTTP API    │        │  Web UI          │               │
│  │  FastAPI 薄壳    │        │  React 19 + Vite │               │
│  │  interfaces/api  │        │  frontend/       │               │
│  └────────┬─────────┘        └────────┬─────────┘               │
│           │  同一份业务契约            │  HTTP / SSE             │
└───────────┼───────────────────────────┼─────────────────────────┘
            │                           │
            └─────────────┬─────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  应用服务层  service.py + state.py          ← 唯一业务入口         │
│  ForgeService   optimize / ask_followup / rollback / settings      │
│  FlowState      优化流程状态机（持久化于 L1 Session）             │
│  职责：编排、状态推进、单一形态一致性保证                           │
└───────────────┬─────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  领域核心层  domain/                          ← 形态无关          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ retrieval│ │ decision │ │ generate │ │ ranking  │            │
│  │ 阶段一    │ │ 阶段二    │ │ 阶段三    │ │ 阶段四    │            │
│  │ rg+ctags │ │ Noul探针 │ │ 三套生成  │ │ 加权推荐  │            │
│  └──────────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘            │
└───────────────────┼─────────────┼────────────┼──────────────────┘
                    │             │            │
                    ▼             ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│  基础设施层  harness/ + memory/ + decision/                        │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐    │
│  │ harness/   │ │ memory/    │ │ decision/  │ │ config.py  │    │
│  │ Runner     │ │ L1/L2/L3   │ │ decider    │ │            │    │
│  │ Session    │ │ SQLite+Git │ │ fallback   │ │            │    │
│  │ Guardrail  │ │            │ │ port.py    │ │            │    │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## 0.2 模块依赖关系

```
                    ┌──────────────┐
                    │  interfaces  │  表现层（可依赖领域层）
                    └──────┬───────┘
                           │ 禁止反向依赖
                           ▼
    ┌──────────────┬───────┴───────┬──────────────┐
    │              │               │              │
    ▼              ▼               ▼              ▼
┌────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│service │   │  state   │   │    api   │   │ frontend  │
└───┬────┘   └────┬─────┘   └──────────┘   └──────────┘
    │             │
    ▼             ▼
┌─────────────────────────┐
│       domain/           │  纯领域逻辑，无 I/O
│  retrieval decision     │
│  generate   ranking     │
└────────┬────────────────┘
         │  仅通过 Protocol 交互
         ▼
┌─────────────────────────────┐
│  harness/ memory/ decision/ │  基础设施实现
└─────────────────────────────┘
```

## 0.3 三条不可违反的架构约束

以下三条由 CI 强制检查，违反即阻断合并。

| # | 约束 | 检查方式 |
|---|---|---|
| 1 | `domain/` 不得 import `interfaces/` 或 `harness/` | 静态导入检查 |
| 2 | `service.py` 不得反向 import `interfaces/` | 静态导入检查 |
| 3 | 前端不得出现阈值常量或业务判定分支 | ESLint 自定义规则 + grep |

**补充约束（硬性，与宪法 MUST-06 一致）**：`domain/` 必须是纯逻辑，不含任何 I/O。所有 I/O（子进程、HTTP、文件、数据库）经 Protocol 注入，落点见 §4.9。违反即阻断合并。

**架构约束补充表**（与上表并列，同样阻断）：

| # | 约束 | 检查方式 |
|---|---|---|
| 4 | `domain/` 不得 import 下层**实现模块**（`harness/process.py`、`decision/fallback.py` 等） | 静态导入检查 |
| 5 | SQL 只允许出现在 `memory/` 模块内 | 静态检查 |
| 6 | 组件文件名必须与主导出名一致 | 自定义检查 |
| 7 | 前端错误码映射表必须覆盖后端全部错误码 | 静态比对（N-7/M-10） |

**判定 `domain/` 是否违规的客观标准**：其单元测试可在脱离文件系统与网络的环境下运行。若某模块的测试必须真实起子进程或发请求，说明该模块混入了 I/O，违规。

## 0.4 状态机位置说明

状态机（`state.py`）在**应用服务层**，不在领域层。理由：状态推进属于用例编排，不是领域规则。同一状态机被 HTTP 层与前端共用（前端 store 仅为镜像），这是行为一致的根本保证。

---

# 第一部分 · 后端

## 1. 环境与启动

### 1.1 开发环境要求

| 组件 | 版本要求 | 用途 | 校验方式 |
|---|---|---|---|
| Python | `>=3.10`，推荐 `3.13` | 后端语言 | `python --version` |
| uv | 最新稳定 | 依赖管理（优先） | `uv --version` |
| Node.js | `^20.19`、`^22.12` 或 `^24`（2026-10-04 实测 v24.14.0 兼容 Vite 7 engines `^20.19 \|\| >=22.12`；CI 固定 22） | 前端构建 | `node --version` |
| pnpm | `^10.15` | 前端包管理 | `pnpm --version` |
| ripgrep (`rg`) | 最新 | 全文检索 | `rg --version` |
| universal-ctags | 最新 | 符号抽取 | `ctags --version` |
| git | `>=2.30` | L2 项目记忆 | `git --version` |
| SQLite 3.x | L1/L3 存储 | Python 标准库 `sqlite3`，库文件可写即通过 |

**不支持的版本**：Python 3.14+（`openai-agents` 依赖链兼容性验证不充分）、Node 18（Vite 7 最低要求）。

### 1.2 依赖安装

**后端**：

```bash
# 方式一：uv（推荐）
uv sync                                    # 按 uv.lock 精确安装
uv sync --all-extras                       # 全部可选依赖

# 方式二：pip
pip install -e ".[dev]"
```

**前端**：

```bash
cd frontend
pnpm install --frozen-lockfile             # 严格按 lockfile，CI 必用
```

### 1.3 可选依赖分组

```toml
[project.optional-dependencies]
dev = [
    "ruff>=0.14",
    "mypy>=1.13",
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.28",
]
```

### 1.4 本地启动

**开发态（前后端分离）**：

```bash
# 终端一：后端
uv run uvicorn devprompt_ai.interfaces.api.app:app --reload --port 8000

# 终端二：前端
cd frontend && pnpm dev                        # :5173，proxy 指向 :8000
```

**生产态（单端口）**：

```bash
cd frontend && pnpm build                      # 产物输出到 frontend/dist
uv run uvicorn devprompt_ai.interfaces.api.app:app --port 8000
# FastAPI 托管 dist/，单端口对外
```

### 1.5 部署流程

```
构建阶段
  1. uv sync --frozen --extra dev
  2. cd frontend && pnpm install --frozen-lockfile && pnpm build
  3. ruff check --fix && mypy
  4. pytest

发布阶段
  5. 打包为 wheel：uv build
  6. 部署到目标环境
  7. 环境变量由部署平台注入（不入库）
  8. 健康检查：GET /api/v1/health
```

**回滚策略**：保留上一版本 wheel；健康检查失败即回滚；L1/L2/L3 记忆数据向后兼容，不随版本回滚丢失。

**回滚可执行步骤（T7-7）**：

```
1. 升级前保留上一版本 wheel（dist/ 上一构建产物，勿覆盖）
2. 发现故障 → 重装上一版本 wheel：uv pip install --reinstall <上一版>.whl
3. 重启服务（uvicorn 重载）
4. GET /api/v1/health —— 失败（is_healthy=false 或不可达）即判定本次升级失败，
   回滚至上一版本 wheel 并再次重启；成功后保留新版本
L1/L2/L3 数据向后兼容，回滚无需数据迁移
```

### 1.6 环境变量

**LLM 供应商（必填）**：

| 变量 | 示例 | 说明 |
|---|---|---|
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容端点 |
| `LLM_API_KEY` | `sk-xxx` | 密钥 |
| `LLM_MODEL` | `deepseek-chat` | 模型 ID |

**推荐与阈值**：

| 变量 | 默认 | 说明 |
|---|---|---|
| `PREFER_ADAPT_WEIGHT` | 0.6 | 适配度权重 |
| `PREFER_HISTORY_WEIGHT` | 0.4 | 偏好权重 |
| `PREFER_HARD_THRESHOLD` | 0.5 | 推荐硬阈值 |
| `PREFER_SOFT_THRESHOLD` | 0.12 | 推荐软阈值 |
| `PREFER_MIN_CONFIDENCE` | 0.6 | 标推荐最低置信度 |
| `PREFER_LOW_CONFIDENCE` | 0.4 | 低置信度提示线 |

**流程控制**：

| 变量 | 默认 | 说明 |
|---|---|---|
| `FOLLOWUP_SOFT_ROUND_GUARD` | 10 | 反问软护栏：单流程追问轮数达此值时显式询问用户裁决（非静默终止） |
| `FOLLOWUP_COST_BUDGET` | 空 | 反问软护栏 LLM 成本预算（空=禁用） |
| `FACT_PROBE_THRESHOLD` | 0.75 | 事实探针通过线 |
| `MAX_STATE_TOKENS` | 30000 | 上下文装配预算下限；随档位放大至 160K |

**运行时**：

| 变量 | 默认 | 说明 |
|---|---|---|
| `APP_ENV` | `dev` | `dev` / `test` / `prod` |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_DIR` | `./.logs` | 日志目录 |
| `DATA_DIR` | `~/.devprompt-ai` | 本地数据目录（L1/L3 SQLite 数据库、检索缓存等） |
| `CORS_ORIGINS` | `http://localhost:5173` | 逗号分隔 |
| `DB_PATH` | `~/.devprompt-ai/devprompt.db` | SQLite 单文件库（L1/L3；WAL 模式，环境变量可覆盖） |
| `DEVPROMPT_FRONTEND_DIST` | 空 | 前端 `dist` 目录覆盖（打包部署时指向产物；缺省回落仓库根 `frontend/dist`） |

### 1.7 三环境配置差异

| 维度 | 开发 `dev` | 测试 `test` | 生产 `prod` |
|---|---|---|---|
| 日志级别 | `DEBUG` | `WARNING` | `INFO` |
| 日志输出 | 控制台彩色 | 内存捕获 | 文件（按日切分） |
| Tracing | 开启 | 关闭 | 关闭 |
| L1 Session | 真实 SQLite | 内存实现 | 真实 SQLite |
| 轮次记忆（forge_turns） | 真实 SQLite | 内存实现 | 真实 SQLite |
| 决策层 | LLM | LLM | LLM |
| CORS | 允许 `localhost:5173` | 仅本地 | 显式白名单 |
| 缓存 | 内存 | 禁用 | 内存 |
| 数据目录 | 项目内 `.devprompt-ai/` | 临时目录 | 环境变量指定 |
| 敏感信息日志 | 允许 | 允许 | **禁止** |

**生产环境特别约定**：

- 密钥环境变量优先；本地设置文件（0600）为唯一落盘处；不入库、不进日志（MUST-19 修订，真源 §13 2026-10-12）
- 错误响应不回传内部堆栈
- 敏感字段（路径、用户原句）在 INFO 级别不落盘

### 1.8 健康检查

`GET /api/v1/health` 返回依赖状态，供部署平台探活。

检查项：配置完整性、ripgrep 可用性、ctags 可用性、决策层可用性、SQLite 库文件可写（含 WAL 初始化）、LLM 端点连通性。

---

## 2. 全局规范

### 2.1 命名约定

**文件命名**：

| 类型 | 规则 | 示例 |
|---|---|---|
| Python 模块 | `snake_case` | `session_store.py` |
| Python 测试 | `test_<模块>.py` | `test_ranking.py` |
| Python 模板 | `snake_case` 存放于 `templates/` | `variant_b.py` |
| 前端组件 | `PascalCase.tsx` | `PromptCard.tsx` |
| 前端页面 | `PascalCase.tsx` | `OptimizePage.tsx` |
| 前端 Hook | `useXxx.ts` | `useOptimizeStore.ts` |
| 前端类型 | `PascalCase.ts` 或小写分组 | `optimize.ts` |
| 前端 Store | `useXxxStore.ts` | `useSettingsStore.ts` |
| 配置文件 | `lowercase` 或 `kebab-case` | `pyproject.toml`、`.env.example` |

**禁止**：文件名含中文、空格、特殊字符；同一目录下混用 `kebab-case` 与 `snake_case`。

**变量与函数命名**：

| 类别 | Python | TypeScript |
|---|---|---|
| 变量/常量 | `snake_case` | `camelCase` |
| 模块级常量 | `UPPER_SNAKE_CASE` | `UPPER_SNAKE_CASE` |
| 类名 | `PascalCase` | `PascalCase` |
| 函数/方法 | `snake_case` | `camelCase` |
| 私有成员 | `_leading_underscore` | `无前缀或 _`（TS 私有用 `private`） |
| 类型注解 | `PascalCase` | `PascalCase` |
| 接口响应模型 | `XxxResponse` / `XxxRequest` | 同左 |

**命名约束（CI 检查）**：

- 常量不得用 `let`/`var` 重新赋值
- React 组件文件名必须与主导出名一致
- Store 必须以 `use` 开头且返回 hook
- 布尔值命名用 `is` / `has` / `should` 前缀
- 禁止用 `get` 命名纯取值函数

### 2.2 代码风格与 Lint

**Python 工具链**：

| 工具 | 作用 | 关键配置 |
|---|---|---|
| Ruff | Lint + Format | `line-length = 100`，启用 `E`/`F`/`I`/`N`/`UP`/`B`/`SIM`/`ASYNC` |
| mypy | 静态类型 | `strict = true`，`disallow_untyped_defs = true` |

**必须启用的 Ruff 规则组**：

| 规则 | 覆盖 |
|---|---|
| `E` / `W` | pycodestyle 基础 |
| `F` | Pyflakes（未使用变量、未定义名称） |
| `I` | isort（导入顺序） |
| `N` | pep8-naming（命名约定） |
| `UP` | pyupgrade（现代化语法） |
| `B` | bugbear（常见陷阱） |
| `SIM` | flake8-simplify |
| `ASYNC` | 异步陷阱检测 |

`ASYNC` 组对本项目尤其重要——它专门检测「`async def` 中调用了同步阻塞函数」这类错误，是本项目最容易踩的坑。

**TypeScript 工具链**：

| 工具 | 作用 | 关键配置 |
|---|---|---|
| tsc | 类型检查 | `strict`、`noUncheckedIndexedAccess` |
| ESLint | Lint | flat config，`typescript-eslint` |
| prettier | Format | 与 ESLint 分工：ESLint 管逻辑，prettier 管格式 |

**强制规则**：

- Python：所有函数签名必须有完整类型注解
- TypeScript：禁用 `any`，未知类型用 `unknown` + 类型收窄
- TypeScript：`@typescript-eslint/no-explicit-any` 设为 error
- 双端：`domain/` 不得 import 上层（CI 检查）

**格式一致性**：格式化完全交给工具，**禁止在提交前手动调整空格与换行**。CI 检查 `ruff format --check` 与 `prettier --check`。

### 2.3 Git 提交规范

采用 Conventional Commits。

**格式**：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**type 字典**：

| type | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `refactor` | 重构（行为不变） |
| `perf` | 性能优化 |
| `docs` | 文档 |
| `test` | 测试 |
| `build` | 构建与依赖 |
| `ci` | CI 配置 |
| `chore` | 杂项 |
| `style` | 代码格式（不改变逻辑） |

**scope 字典**（与目录对应）：

| scope | 对应模块 |
|---|---|
| `retrieval` | `domain/retrieval/` |
| `decision` | `domain/decision/`、`decision/` |
| `generate` | `domain/generate/` |
| `ranking` | `domain/ranking/` |
| `memory` | `memory/` |
| `service` | `service.py`、`state.py` |
| `api` | `interfaces/api/` |
| `web` | `frontend/` |
| `harness` | `harness/` |
| `config` | `config.py` |

**示例**：

```
feat(ranking): 实现双阈值推荐标记

分差 ≥ 硬阈值且置信度达标时标记推荐；分差不足时输出原因文案。

Closes #23
```

**规则**：

- subject 用中文或英文均可，但**同一仓库内保持一致**
- subject 不超过 72 字符，动词开头，不加句号
- 影响行为变更的提交必须在 body 说明**为什么**而非**做了什么**
- 破坏性变更在 footer 标注 `BREAKING CHANGE:`

### 2.4 版本管理与分支模型

**语义化版本**：

```
主版本.次版本.修订版本
  ↑      ↑      ↑
  |      |      └─ 缺陷修复（patch）
  |      └──────── 新功能（minor）
  └─────────────── 破坏性变更（major）
```

**破坏性变更定义**（任一即算）：

- HTTP 接口路径或响应结构不兼容变更
- 状态机新增终态或状态含义变更
- 配置项删除或语义变更
- 存储格式变更导致旧数据不可读

**分支模型**：

```
main              受保护，发布分支
  │
  ├─ develop       集成分支（默认合并目标）
  │   │
  │   ├─ feature/<scope>-<简述>     新功能
  │   ├─ fix/<scope>-<简述>         缺陷修复
  │   ├─ refactor/<scope>-<简述>    重构
  │   └─ chore/<简述>               杂项
  │
  └─ (hotfix 从 main 切出)
      └─ hotfix/<简述>
```

| 分支 | 目标 | 保护策略 |
|---|---|---|
| `main` | 生产发布 | 禁止直推，必须 PR + 双人评审 |
| `develop` | 日常集成 | 禁止直推 |
| `feature/*` | `develop` | 合并前需 CI 全绿 + 至少一人评审 |
| `hotfix/*` | `main` | 可绕过 develop，合并后需回合 develop |

**CI 门禁**（`main` 与 `develop` 均强制）：**检查项以宪法 MUST-29 为准（唯一权威），本文档不重复罗列。**

**版本发布**：

- `develop` 累积到里程碑 → 合并到 `release/<版本号>` 分支
- `release` 分支只接受缺陷修复
- 验证通过 → 合并到 `main` 并打 tag
- `main` 合并回 `develop`

**禁止事项**：

- 禁止向 `main` 直推
- 禁止向 `develop` 直推
- 禁止对已推送的 feature 分支做 rebase（避免历史混乱）
- 禁止提交 `node_modules`、`dist`、`.env`、日志文件

### 2.5 .gitignore 约定

必须忽略：

```
.env
.env.local
.venv/
__pycache__/
*.py[cod]
node_modules/
frontend/dist/
.logs/
*.db
*.db-journal
.devprompt-ai/
coverage/
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

必须提交：

```
.env.example
uv.lock
pnpm-lock.yaml
frontend/src/schemas/openapi.generated.ts    # 契约类型，自动生成后入库
```

**`.devprompt-ai/` 为何必须忽略**：该目录承载 L1/L3 SQLite 数据库（`devprompt.db`）、检索缓存与符号表缓存等**本地私有状态**——入库会造成缓存污染与二进制 diff 噪声。跨成员共享的项目规范走 **Git notes**（`refs/notes/devprompt`），不受 `.gitignore` 影响。

---

## 3. 接口一致性

### 3.1 统一响应结构

**成功响应**：

```json
{
  "code": 0,
  "message": "ok",
  "data": { },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | int | 0 表示成功，非 0 为错误码 |
| `message` | string | 人类可读描述，成功固定为 `ok` |
| `data` | object \| null | 业务数据，失败时为 `null` |
| `request_id` | string | 链路追踪 ID，同时写入响应头 `X-Request-ID` |

**失败响应**：

```json
{
  "code": 2006,
  "message": "候选集超出上限",
  "data": null,
  "errors": [
    { "field": "candidates", "reason": "count_exceeded", "detail": "实际 31 条" }
  ],
  "request_id": "01HX..."
}
```

`errors` 字段可选，字段级校验失败时提供。

**约定**：

- HTTP 状态码表达**传输层与资源语义**（200/404/500）
- `code` 表达**业务语义**（0 成功，非 0 业务错误）
- 两者不混用：`code` 为 0 但 HTTP 500 是可能的（如后置处理失败但主流程已成功）

### 3.2 分页格式

**请求参数**：

| 参数 | 类型 | 必填 | 默认 | 限制 |
|---|---|---|---|---|
| `page` | int | 否 | 1 | ≥1 |
| `page_size` | int | 否 | 20 | 1–100 |

**响应结构**：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total_items": 137,
      "total_pages": 7,
      "has_next": true,
      "has_prev": false
    }
  },
  "request_id": "01HX..."
}
```

**约定**：分页响应必须携带完整分页信息，前端不需要二次计算。`total_items` 为 0 时 `total_pages` 也为 0 而非 1。

### 3.3 错误码体系

**编码结构**：`HTTP 类别(1位) + 模块(2位) + 具体错误(2位)`

| 首位 | 类别 | HTTP 映射 |
|---|---|---|
| 0 | 成功 | 2xx |
| 1 | 参数与校验 | 400 |
| 2 | 检索与取证 | 400 / 404 / 500 |
| 3 | 决策与置信度 | 200 / 422 / 429 / 503 |
| 4 | 生成 | 422 / 502 / 503 |
| 5 | 外部依赖 | 502 / 503 |
| 6 | 状态机与流程 | 404 / 409 |
| 9 | 系统内部 | 500 |

**错误码清单**：

| code | 含义 | HTTP | 可重试 |
|---|---|---|---|
| 0 | 成功 | 200 | — |
| 1001 | 缺少必填参数 | 400 | 否 |
| 1002 | 参数类型错误 | 400 | 否 |
| 1003 | 参数超出范围 | 400 | 否 |
| 1004 | 请求体格式错误 | 400 | 否 |
| 2001 | 项目路径不存在 | 404 | 否 |
| 2002 | 项目路径不可读 | 403 | 否 |
| 2003 | ripgrep 执行失败 | 500 | 是 |
| 2004 | ctags 执行失败 | 500 | 是 |
| 2005 | 候选集为空 | 422 | 否 |
| 2006 | 候选集超上限 | 400 | 否 |
| 3001 | 决策层不可用 | 503 | 是 |
| 3002 | 决策层返回置信度不足 | 200 | 否（业务提示） |
| 3003 | state 超出 token 上限 | 422 | 否 |
| 3004 | 决策层速率限制 | 429 | 是 |
| 4001 | 生成阶段失败 | 502 | 是 |
| 4002 | LLM 端点不可达 | 503 | 是 |
| 4003 | LLM 返回格式非法 | 502 | 是 |
| 5001 | 外部工具缺失 | 503 | 否 |
| 5011 | LLM 调用超时 | 503 | 是 |
| 5012 | 供应商速率限制（生成阶段） | 429 | 是 |
| 5013 | 供应商余额或配额不足 | 402 | 否 |
| 5014 | LLM 鉴权失败（api_key 无效） | 401 | 否 |
| 5015 | 上游服务异常（网络错误或 5xx） | 502 | 是 |
| 6001 | 非法状态转移 | 409 | 否 |
| 6002 | 反问软护栏触发，等待用户裁决（继续追问/直接生成） | 409 | 否 |
| 6003 | 流程 ID 不存在 | 404 | 否 |
| 9001 | 内部异常 | 500 | 否 |
| 9002 | 配置缺失 | 500 | 否 |

**错误响应必须包含**：`code`、`message`、`request_id`。`message` 使用中文且可操作（说明如何解决，不只是描述问题）。

**`code` 与 `message` 的分工**（N-7确立）：

| 字段 | 面向 | 约束 |
|---|---|---|
| `code` | **前端查表键** | 必须登记在 `domain/error_codes.py`（本节清单为其权威来源） |
| `message` | **日志与降级兜底** | 可含技术细节（类型名、路径片段）；前端仅在后端码未映射时回落展示 |

前端映射表 `frontend/src/schemas/errorCodes.ts` 必须覆盖本节全部码，由 `scripts/check_architecture.py::check_error_code_mapping` 强制（子集断言：前端可多不可少）。**理由**：后端新增码而前端漏映射时，用户会看到未经整理的原始 message——不崩溃，但正是要消除的体验缺口，且这种漂移不会引起任何测试失败。

### 3.4 异常处理规范

**全局异常处理器**：在 FastAPI 注册统一 handler，将领域异常映射为错误码。

**领域异常定义**（`domain/errors.py`）：

| 异常类 | 关联 code | 场景 |
|---|---|---|
| `RetrievalError` | 2001–2006 | 检索与取证失败 |
| `DecisionError` | 3001–3004 | 决策层失败 |
| `GenerationError` | 4001–4003 | 生成失败 |
| `StateError` | 6001–6003 | 状态机违规 |
| `ConfigurationError` | 9002 | 配置错误 |

**规则**：

- 领域层抛**语义异常**，不抛 HTTP 相关异常
- 异常必须携带 `code` 与 `context` 字典
- 外部调用异常必须**包装**为领域异常，不让第三方异常类型穿透到服务层
- 禁止裸 `except:`；禁止 `except Exception: pass`

### 3.5 接口版本管理

**URL 前缀**：`/api/v1`

**版本升级规则**：

| 变更类型 | 版本处理 |
|---|---|
| 新增可选字段 | 兼容，向后兼容，不升版本 |
| 新增接口 | 直接加入当前版本 |
| 新增必填字段 | 升次版本 |
| 删除字段 | 升次版本 |
| 字段类型变更 | 升次版本 |
| 字段语义变更（名称不变含义变） | **升主版本** |
| 状态机新增终态 | 升次版本 |

**废弃流程**：

1. 标记 `deprecated: true` 于 OpenAPI 定义
2. 响应头加 `Deprecation` 与 `Sunset` 头
3. 保留至少一个次版本周期
4. 日志记录调用方，移除前需确认无调用

**双版本并存期**：`v1` 与 `v2` 通过独立路由模块实现，共用 `service.py`，差异在 schema 层与视图层。

### 3.6 请求参数校验

**三层校验**：

| 层 | 手段 | 时机 |
|---|---|---|
| 格式校验 | Pydantic 字段类型与约束 | 请求进入时 |
| 业务校验 | 领域层显式检查 | 服务层调用前 |
| 跨字段校验 | Pydantic `model_validator` | 请求进入时 |

**Pydantic v2 约束示例**：

| 约束 | 写法 |
|---|---|
| 必填与范围 | `page_size: int = Field(20, ge=1, le=100)` |
| 枚举值 | `provider: Literal["custom", "openai", "deepseek"] = "custom"` |
| 字符串长度 | `sentence: str = Field(..., min_length=1, max_length=2000)` |
| 跨字段 | `@model_validator(mode="after")` |

**规则**：

- 所有入参必须有类型注解
- 字符串必须设 `max_length`，防止 state 无界增长
- 数值必须设 `ge` / `le`
- 枚举必须用 `Literal` 而非裸 `str`
- 校验失败由 Pydantic 自动转为 1001–1003 错误码

**决策 state 长度硬约束**：提交给决策层的文本必须预校验长度，超限在调用前截断并记日志，不依赖决策层侧报错。

### 3.7 接口文档生成

**自动生成**：FastAPI 自动产出 OpenAPI 3.1，路径 `/api/v1/openapi.json`，交互式文档 `/docs`。

**文档完备性要求**（CI 检查）：

| 要求 | 检查 |
|---|---|
| 所有路由有 `summary` | 缺失则文档不完整 |
| 所有路由有 `response_model` | 缺失则报告不完整 |
| 所有路由有 `description` | 缺失则告警 |
| 所有错误码有说明 | 在模块 docstring 中声明 |
| 响应模型全部字段有 `description` 或 `Field(description=...)` | 缺失则告警 |

**示例文档字符串**：

```python
@router.post(
    "/optimize",
    summary="启动提示词优化",
    description=(
        "启动一次优化流程。返回 flow_id 用于后续查询进度与结果。\n\n"
        "错误码：\n"
        "- 1001 缺少 sentence\n"
        "- 2001 project_path 不存在\n"
        "- 3004 决策层速率限制，可重试\n"
    ),
    response_model=OptimizeResponse,
)
```

---

## 4. 核心支撑模块

### 4.1 日志系统

**实现**：标准库 `logging`（固定事件名 + LogRecord extra 结构化字段）。

**为什么不用 structlog**（MUST-04 冲突裁决，真源 §13 2026-10-12）：原设计为 structlog，但其未安装且未登记技术栈（审查报告 §四）；标准库 logging（第 2 级）足以承载「固定事件名 + 结构化字段 + 脱敏」要求，依宪法优先原生能力采用标准库实现。事件全集与发射 API 见 `observability/logging.py`（T6-9）。

**配置**：

| 环境 | 格式 | 输出 | 级别 |
|---|---|---|---|
| dev | console（彩色） | stdout | DEBUG |
| test | 内存捕获 | pytest 捕获 | WARNING |
| prod | JSON | 文件，按日切分 | INFO |

**日志级别使用规范**：

| 级别 | 用于 | 示例 |
|---|---|---|
| DEBUG | 内部细节 | ripgrep 原始输出、检索耗时分解 |
| INFO | 关键节点 | 流程阶段切换、决策层切换、耗时汇总 |
| WARNING | 降级与异常情况 | 决策层调用失败、state 被截断、候选集偏少 |
| ERROR | 功能失败 | 阶段失败、LLM 不可达 |
| CRITICAL | 进程级问题 | 无法启动、配置缺失导致无法运行 |

**关键日志事件**（固定事件名，便于检索）：

| 事件名 | 触发时机 | 关键字段 |
|---|---|---|
| `flow.started` | 流程开始 | `flow_id`, `project_path` |
| `flow.completed` | 流程完成 | `flow_id`, `duration_ms`, `has_recommendation` |
| `retrieval.candidates` | 候选集生成 | `count`, `elapsed_ms` |
| `recommendation.made` | 标记推荐 | `variant`, `gap`, `confidence` |
| `recommendation.skipped` | 不标记 | `reason`, `gap` |
| `state.truncated` | state 截断 | `original_size`, `final_size` |
| `followup.guardrail` | 反问软护栏触发 | `rounds` / `cost` / `decision` |
| `followup.escaped` | 用户逃生选择「直接生成」 | `rounds` |

**必须记录**：请求 ID（贯穿全链路）、阶段耗时、决策层名称与切换原因、置信度数值、token 消耗。

**生产环境脱敏**：用户原句、完整文件路径在 INFO 级别不落盘，仅记录哈希或截断。密钥永不记录。

### 4.2 数据库连接

**存储选型**：SQLite 单文件（WAL 模式），落 `DATA_DIR`（默认 `~/.devprompt-ai/devprompt.db`）

**理由**（用户决策，2026-10-07 回改定稿；原 2026-10-04 曾定 MySQL，经对比评估回改）：本地工具即开即用（零安装/零服务/零凭据）、MUST-04 第 2 级标准库优于第三方驱动、WAL + CAS 足以承载多请求并发写。数据层已隔离在 `memory/` 内，多用户态确认后经 `SessionStore` Protocol 切换后端。

**连接配置**：

| 项 | 环境变量 | 默认 |
|---|---|---|
| 库文件路径 | `DB_PATH` | `~/.devprompt-ai/devprompt.db` |

**连接管理**：

- 每个读写操作在 `asyncio.to_thread` 中独立开连接（`sqlite3.connect(db_path, timeout=5)`），用完即关
- 首次使用执行 `PRAGMA journal_mode=WAL` + `busy_timeout=5000`，并经 `memory/schema.py` 幂等建表
- L1 Session 走自定义 `SQLiteSessionStore`（`memory/session_store.py`，经 `SessionStore` Protocol 注入——SDK 自带 Session 实现面向对话历史，语义不匹配）
- L2 项目笔记走 `memory/project_note_store.py` 封装，不向上层暴露连接对象或游标（L3 偏好向量已于 2026-10-21 整层移除，见 F-503）
- 写操作 CAS：`UPDATE ... WHERE session_id=? AND version=?`，0 行更新即版本冲突（6001，MUST-11）

**迁移策略**：

当前表结构简单且是本地工具，**不使用迁移框架**。`memory/schema.py` 启动时检查 schema 版本，不匹配则执行幂等迁移；无法迁移时**报错并保留旧库**，不静默重建。

**必须建表的表**（以 `memory/schema.py` 为准，2026-10-12 对齐修正）：

| 表 | 字段 |
|---|---|
| `forge_sessions`（L1 会话） | `session_id` (PK), `user_id`, `state`, `version`, `payload`, `updated_at` |
| ~~`preference_vectors`（L3 偏好向量）~~ | ~~2026-10-21 随偏好层移除~~ |
| ~~`adoption_history`（采纳历史表）~~ | ~~同上移除~~ |
| `app_settings`（流程参数，F-604） | `key` (PK), `value`, `updated_at` |
| `forge_turns`（轮次记忆，2026-10-20） | `turn_id` (PK), `session_id`+`turn_index` 唯一, `state`, `input`, `facts_json`, `clarifications_json`, `output_json`, `summary_json`, `usage_json` |
| `project_notes`（L2 结构化记忆） | `project_root`+`kind`+`key` (PK), `value`, `confidence`, `hit_count`, `last_hit_at`, `source` |

### 4.3 ORM 映射

**决策：不引入 ORM，用原生 SQL。**

理由：仅两张表、结构简单、无复杂关系查询。ORM 带来的模型定义、迁移、Session 管理成本远超收益。

**边界**：SQL 只允许出现在 `memory/` 模块内。`domain/` 与 `service.py` 不得出现任何 SQL 字符串。

**实现方式**：各 `memory/*.py` 存储模块提供明确的方法，不向上层暴露连接对象或游标。

```python
class SQLiteProjectNoteStore:
    """L2 项目笔记存储。所有 SQL 封装于此，上层不接触连接。"""

    async def upsert(self, note: ProjectNote) -> None: ...
    async def search(self, project_root: str, target_key: str) -> list[ProjectNote]: ...
    async def record_from_session(self, project_root: str, data: dict) -> None: ...
```

**事务规则**：

- 单表单条写入无需显式事务（autocommit）
- 批量写入必须显式事务
- 读取操作用只读连接
- 任何异常必须 rollback 并向上抛出

### 4.4 缓存策略

**采用两级缓存，均为进程内，无需 Redis。**

| 级别 | 缓存对象 | 生命周期 | 失效条件 |
|---|---|---|---|
| L1 符号表缓存 | 项目符号表与文件路径 | 进程内，TTL 1 小时 | 项目文件 mtime 变化 |
| L1 决策结果缓存 | (项目, 原句 hash) → 排序结果 | 进程内，TTL 30 分钟 | 项目变更、阈值配置变更 |

**缓存键设计**：

| 缓存 | 键 |
|---|---|
| 符号表 | `符号表:{项目绝对路径}:{mtime 摘要}` |
| 决策结果 | `决策:{项目路径}:{原句 sha256}:{阈值配置 hash}` |

**把阈值配置纳入键**是关键设计——调阈值后必须失效，否则会读到用旧阈值算出的推荐结果。

**失效策略**：

- 项目文件变更（检测根目录 mtime 变化）→ 清空符号表
- 配置热重载 → 清空决策结果缓存
- 达到 TTL → 自然过期

**不缓存的内容**：用户原句、LLM 生成的三套方案正文、决策层原始响应。理由：这三项体积大且与状态强相关，缓存收益低、失效复杂、正确性风险高。

**命中率埋点**：`cache.hit` / `cache.miss` 事件，日志可查，用于判断缓存是否真的有效。**连续低命中应考虑删掉缓存**——无效缓存只增加复杂度。

### 4.5 认证与权限控制

**当前状态：本地单用户，不启用认证。**

这是明确的设计决策，不是遗漏。`user_id` 恒为 `"local"`，`ForgeService` 方法签名已预留该参数。

**预留设计**（多用户态启用时生效）：

| 层 | 预留内容 | 位置 |
|---|---|---|
| 参数预留 | 所有服务方法首参为 `user_id` | `service.py` |
| 存储隔离 | 记忆层以 `user_id` 为键分区间 | `memory/` |
| 配置预留 | `AUTH_ENABLED` 开关 | `config.py` |

> **2026-10-16 注记**：原「中间件骨架 → `interfaces/web/middleware.py`」一行已移除。
> 该目录自项目确立 Web-only 架构起从未落地（7 个文件均为 0 字节空文件、无任何模块引用），
> 已按「目录树必须与实际实现一致」原则整体删除。启用多用户态时**重建**
> `interfaces/web/`（认证中间件 + `user_id` 解析 + deps 注入），而非恢复空文件。
> 延后决议与落地条件见实施真源文档延后登记表。

**未来启用时的方案**：

| 方案 | 适用 | 说明 |
|---|---|---|
| 简单 API Key | 团队内部使用 | 请求头携带，足够且成本最低 |
| JWT | 需要多端登录 | 含 refresh token 刷新流程 |
| 第三方 OAuth | 企业环境 | 对接既有身份系统 |

**建议**：先做 API Key，够用且不引入用户体系复杂度。

**权限模型**：本项目暂无角色区分需求（所有操作等价），因此**不设计 RBAC**。若后续需要区分「只读」与「可修改偏好」，再加两档角色即可。

**必须遵守的安全约定**（即便无认证也要守）：

- 密钥永不入日志
- 错误响应不回传堆栈
- 项目路径必须校验为真实存在的目录，拒绝路径穿越（`..`）
- 上传/读取的文件路径必须规范化后检查是否在允许范围内

### 4.6 定时任务

**当前无定时任务需求。** 不引入调度框架（Celery、APScheduler 等）。

**理由**：本项目是前台交互式工具，无周期性任务。若后续需要，只需两个场景：

| 可能的定时需求 | 实现方式 | 不引入框架的理由 |
|---|---|---|
| 符号表定期刷新 | 惰性刷新即可——访问时检查 mtime，无需定时器 | 惰性更简单，无需常驻任务 |
| 项目笔记置信度衰减 | 惰性计算即可——读取时按 90 天半衰公式计算 | 同上 |
| 日志清理 | 启动时清理一次 | 无需周期执行 |

**原则**：**惰性优于定时**。除非确实需要「即使无人使用也要执行」，否则用「访问时检查」替代定时任务。

**若将来必须引入**，选择轻量方案：APScheduler（进程内）或系统级 cron，**不引入 Celery**（需要 Broker，对单机工具是灾难）。

### 4.7 公共工具库

`common/` 目录存放无业务含义的纯工具。

**目录**：

| 文件 | 职责 | 关键内容 |
|---|---|---|
| `text.py` | 文本处理 | 中文按字符二元组分词、英文驼峰与下划线拆分、token 估算 |
| `hashing.py` | 哈希 | 原句归一化后 sha256、mtime 摘要 |
| `process.py` | 子进程管理 | ripgrep / ctags 的异步封装、超时、输出解析 |
| `cost.py` | 成本核算 | LLM token 用量归集与费用明细（F-805） |
| `secrets.py` | 密钥脱敏 | API Key 回显掩码（MUST-19，仅脱敏不落原值） |

> `files.py` / `time.py` / `types.py` 已于 2026-10-16 删除：三者自脚手架阶段起均为 0 字节空文件、
> 无任何引用方；所需能力分别由 `harness/process.py`（子进程与路径）、`common/cost.py`
> （耗时）与各域 `ports.py`（Protocol 定义）覆盖。新增前须先说明现有实现为何不足。

**工具库规则**：

| 规则 | 说明 |
|---|---|
| 纯函数优先 | 工具函数尽量无副作用 |
| 无业务语义 | 工具库**不得**包含任何 DevPrompt AI 的业务概念 |
| 可独立测试 | 每个工具有独立单元测试 |
| 无隐式 I/O | I/O 需显式传入路径，不自行决定访问目标 |
| 禁止万能 utils | 按职责拆分文件，不建 `utils.py` 大杂烩 |

**反例警示**：

```python
# 禁止：工具库中出现业务概念
def extract_candidates(files: list[str], intent: str) -> list[str]: ...  # 这是领域逻辑，属于 domain/retrieval/


# 正确：工具库只提供能力，不含业务判断
def split_identifier(name: str) -> tuple[str, str]:
    """将 SubmitButton 拆分为 (Submit, Button)"""
    ...
```

**进程执行规范**（`process.py` 专项）：

本项目大量调用外部工具，是最容易出性能与阻塞问题的地方。

| 规则 | 说明 |
|---|---|
| 一律异步 | 用 `asyncio.create_subprocess_exec`，禁止 `subprocess.run` |
| 必须设超时 | 每个外部调用都要有超时，默认 10 秒 |
| 禁止 shell=True | 避免注入风险与跨平台转义问题 |
| 输出显式编码 | 统一 UTF-8，`errors="replace"` |
| 僵尸进程清理 | 异常路径确保 `proc.kill()` + `await proc.wait()` |
| 阻塞操作入线程池 | 确实无法异步化的走 `run_in_threadpool` |

**Ruff 的 `ASYNC` 规则组专门检测这类陷阱，CI 中必须开启。**

### 4.8 后端目录结构

> **本节是后端目录结构的唯一权威定义。** 新增/删除/移动文件只需修改本节，其他文档的目录树为引用性说明。

```
src/devprompt_ai/
├── __init__.py
├── main.py                    ASGI 入口（再导出 `interfaces/api/app.py` 已创建的 app 实例，供 `uvicorn devprompt_ai.main:app`；另承载 `[project.scripts] devprompt-ai` 的 serve 入口）
├── service.py                 ForgeService 唯一业务入口
├── state.py                   优化流程状态机
├── config.py                  Pydantic Settings
├── domain/                    纯领域逻辑，无 I/O
│   ├── __init__.py
│   ├── errors.py              领域异常类型（码取自 error_codes）
│   ├── error_codes.py         集中错误码表（架构文档 §3.3 权威清单）
│   ├── model_spec.py          文本模型能力元数据 / API 形态 / 上下文窗口档位（纯领域表，25厂商）
│   ├── model/tuning.py        运行时模型参数归一（effort 词表 / Anthropic、Gemini thinking budget；纯函数，2026-11-10）
│   ├── model_migration.py     注册表条目归一化（读时补默认值，永不抛异常）
│   ├── prompt_guard.py        跨域共用 prompt 边界与安全声明（T-1~T-5）
│   ├── progress.py            思考过程文案（阶段进度纯函数 + ProgressSink Protocol；2026-10-19 供流式端点）
│   ├── context/build_context.py  多轮上下文装配（2026-10-20：分层预算 + 固定裁剪顺序 + summary_from_turn，纯函数）
│   ├── startup_report.py      启动自愈报告（类型 + 进程级状态）
│   ├── models.py              领域数据模型
│   ├── retrieval/
│   │   ├── ports.py           Protocol 定义（子进程 / 文件读取）
│   │   ├── symbols.py         符号表构建
│   │   ├── candidates.py      候选检索 + 词汇重排（I1–I3：BM25+RRF+路径权重，只调序不减候选）
│   │   ├── bm25.py            BM25 + RRF 融合名次（零依赖二次排序层；2026-11-08 接线）
│   │   ├── salience.py        路径权重（实现文件优先、测试/文档降权；2026-11-08 接线）
│   │   ├── physarum.py        访问强化（I6：边权衰减+强化纯函数；2026-11-08 接 repo_edges.weight）
│   │   ├── locate.py          全文定位
│   │   └── facts.py           事实取证（七项 + 适用性判定 + is_evidence_complete）
│   ├── agent/                  外环监督与状态感知（2026-11-05）
│   │   ├── ports.py            ActionPlanner 协议（下一步动作）
│   │   ├── action.py           动作枚举 + 步骤记录 + 循环预算（纯数据）
│   │   ├── convergence.py      三判据收敛检测（纯函数，命中即止）
│   │   ├── finish_gates.py     natural-finish 六道闸（A2：DELIVER 前拦截，只拦不加态；2026-11-08 接线）
│   │   ├── anchor.py           本轮目标锚点（抽取/追加合并/渲染，纯函数，内部状态）
│   │   ├── sensorium.py        六维状态感知（纯函数；pressure=max(相对,绝对)，策略映射 2026-11-08 接线）
│   │   └── memory.py           跨轮继承契约 TurnMemory（纯数据 + 序列化）
│   ├── decision/
│   │   ├── port.py            DecisionPort 协议
│   │   └── followup.py        自适应反问编排（具体未知驱动 + 软护栏裁决）
│   ├── delivery/
│   │   ├── __init__.py        包声明
│   │   ├── gate.py            交付证据门（GREEN/YELLOW/RED 三态，纯函数；只读证据不产出证据）
│   │   └── attribution.py     交付归属（E11：影响半径 × file 断言差集 → 三色；2026-11-08 接 gate）
│   ├── generate/
│   │   ├── ports.py           Protocol 定义（LLM 调用）
│   │   ├── variants.py        三套方案编排
│   │   ├── claims.py          断言对账（claims → 事实覆盖；未声明记 0 并标 undeclared）
│   │   └── templates/         A/B/C 模板（a_conservative↔A 保守 / b_standard↔B 标准 / c_thorough↔C 激进）
│   │       ├── a_conservative.py
│   │       ├── b_standard.py
│   │       ├── c_thorough.py
│   │       └── reply.py           纯回答模板（只出文字，不产方案）
│   ├── hooks/                  外环监督契约（2026-11-05：5 阶段 + 三态 verdict）
│   │   ├── types.py            HookPhase / HookContext / HookResult / Hook 协议
│   │   ├── pipeline.py         HookPipeline（halt 短路 / correct 合并 / 超时视为 allow）
│   │   └── builtin.py          内置 hook 实现
│   └── ranking/
│       ├── ports.py            Protocol 定义（偏好读写）
│       ├── ~~preference.py~~    偏好向量（2026-10-21 移除）
│       ├── score.py           加权总分
│       └── recommend.py       双阈值标记
├── decision/                  决策层实现（单一 LLM 实现）
│   ├── fallback.py            LLM 决策实现（原 JevDecider 已于 2026-10-15 移除）
│   └── prompts.py             决策问题模板
├── harness/
│   ├── adapters/            【2026-09-17】协议适配层（按 provider 分流 API 形态）
│   │   ├── __init__.py      build_adapter() + supported_adapter_kinds()
│   │   ├── base.py          Model 子类基类（api_mode 固定 + close 幂等）
│   │   ├── openai_compat.py     Chat Completions 形态（绝大多数第三方）
│   │   ├── openai_responses.py  Responses 形态（OpenAI 官方）
│   │   ├── anthropic_native.py  Anthropic Messages 原生（依赖 anthropic，可选 extra）
│   │   ├── gemini_native.py     Gemini GenerateContent 原生（依赖 google-genai，可选 extra）
│   │   └── registry.py      adapter_kind → 构造器
│   ├── llm.py               build_model(entry) 工厂：按调用构造 Model，**不用全局开关**                 多供应商客户端（openai-agents Runner/Agent 直接在此封装）
│   ├── guardrails.py          输出校验
│   ├── ask_tool.py            AskUserQuestion 工具定义与参数解析（2026-10-22：schema/解析/畸形降级/扩展字段 taskKind）
│   ├── trace.py               动作观测层（2026-10-20：包装 CommandRunner/FileReader，把真实 rg/读文件上报成卡片并脱敏；2026-11-08 接输出治理：超阈值落盘+摘要+回读 footer）
│   ├── process.py             检索 I/O Protocol 实现（CommandRunner/FileReader）+ 符号表编排（F-101）
│   ├── model_candidates.py    路由候选解析（G2：settings 注册表→候选链，routing_stats 60s 缓存；2026-11-08）
│   ├── output_store.py        工具输出落盘（C3：截断前存全量，1 小时过期；2026-11-08 接 trace 通道）
│   ├── output_summary.py      工具输出摘要（C1–C5：语义密度阈值/头尾策略/回读 footer；2026-11-08 接 trace 通道）
│   ├── repo_indexer.py        仓库索引器（I4：Python AST 符号图 + 反向依赖；2026-11-08 接 physarum 边权）
│   ├── overflow.py            超窗「压一次重发一次」（A8；2026-11-08 接生成路径）
│   └── summarize.py           LLM 摘要（B11：走 summarize 槽，失败回退确定性 handoff；2026-11-08 接压缩链路）
│   ├── dialog.py        原生文件夹选择器（native host 调用）              目录浏览 I/O（F-601 页内文件夹选择器数据源，GET /project/browse）
│   └── dialog.py              Windows 原生文件夹对话框（pwsh -STA，零新依赖）
├── memory/                    唯一允许出现 SQL 的模块
│   ├── schema.py              表结构与迁移（WAL 初始化 + 幂等建建表；含 forge_quarantine 隔离表）
│   ├── startup_safety_check.py 启动自愈（N-1：integrity_check → 坏行隔离 → 补齐缺表；永不抛异常）
│   ├── session_store.py       L1 会话存储（SQLiteSessionStore，经 SessionStore Protocol 注入；CAS 乐观锁）
│   ├── turn_store.py          多轮 turn（2026-10-20：append-only，(session_id, turn_index) 唯一索引即乐观锁）
│   ├── project_note_store.py  L2 结构化记忆（2026-10-20：top-K 检索 + 90 天衰减 + 命中回写）
│   ├── ~~preference_store.py~~（2026-10-21 移除）    L3 偏好向量
│   └── project_notes.py       L2 Git notes
├── runtime/                   多端运行时（2026-11-07；执行与连接解耦）
│   ├── bootstrap.py           装配单例（写锁→建库→checksum 校验→checkpoint sink 注入）
│   ├── runs.py                RunManager（run 生命周期 + 看门狗 + 终止原因结构化）
│   ├── events.py              EventBus（seq 事务内分配 + 重放/补帧）
│   ├── streams.py             SSE 订阅
│   ├── sessions.py            SessionPool（同会话单执行）
│   ├── lock.py                单写者文件锁
│   ├── interventions.py       审批代理（第一应答获胜）
│   ├── artifacts.py           工件回读（C3：id 校验 → output_store.read_by_id；2026-11-08）
│   └── coordinator.py         委派调度（K2：分池信号量+文件占位+去重；2026-11-08 接 _act_delegate）
├── common/                    纯工具，无业务语义
│   ├── text.py
│   ├── hashing.py
│   ├── process.py
│   ├── cost.py                LLM token/费用明细（F-805）
│   ├── envhint.py             配置缺失的可操作提示（N-8，只输出变量名与用途）
│   └── secrets.py             密钥脱敏（MUST-19）
├── interfaces/                表现层（Web HTTP 薄壳，零业务逻辑）
│   └── api/
│       ├── __init__.py        包声明（薄壳层约束说明）
│       ├── app.py             FastAPI 实例 + CORS + 统一异常渲染 + 缓存/安全响应头中间件（M-11）
│       ├── routes.py          路由薄壳（14 路径/17 操作；参数收拢 → 调 service → 渲染）
│       ├── schemas.py         Pydantic v2 请求/响应契约（XxxRequest/XxxResponse）
│       └── health.py          环境自检（rg/ctags/git、DB 可写、LLM 配置、storage_repair）
└── observability/
    └── logging.py             结构化事件日志（标准库，T6-9；11 个固定事件见 SHOULD-08）
```

---

# 第二部分 · 前端

### 4.9 Protocol 注入点（`domain/` 无 I/O 的实现前提）

`domain/` 层禁止任何 I/O（宪法 MUST-06）。实现方式是：领域层声明所需能力的 Protocol，基础设施层提供实现，由 `service.py` 组装时注入。

| Protocol 定义位置 | 协议方法 | 对应实现位置 | 用途 |
|---|---|---|---|
| `domain/retrieval/ports.py` | `CommandRunner.run(args) -> str` | `harness/process.py` | 执行 ripgrep / ctags |
| `domain/retrieval/ports.py` | `FileReader.read(path) -> str` | `harness/process.py` | 读取文件内容 |
| `domain/retrieval/ports.py` | `FileReader.exists(path) -> bool` | `harness/process.py` | 文件存在性检查 |
| `domain/decision/port.py` | `rank_components` / `probe_facts` / `score_prompts` | `decision/fallback.py` | 决策层三能力 |
| `domain/generate/ports.py` | `generate(prompt) -> str` | `harness/llm.py` | LLM 单次调用 |
| `domain/model_catalog/ports.py` | `ModelCatalogFetcher.fetch(base_url, api_key, timeout)` | `harness/models_client.py` | 拉厂商 `/models` 模型清单（2026-10-17） |

**注入位置**：`ForgeService.__init__` 接收全部 Protocol 实例，默认取生产实现，测试时注入 mock。

**验证方式**：单元测试中 `domain/` 各模块可脱离文件系统与网络独立运行——这是「无 I/O」的可检验标准，也是判定 `domain/` 是否违规的客观依据。

---

## 5. 目录结构

### 5.1 完整目录树

```
frontend/
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── vite.config.ts
├── eslint.config.js
├── .prettierrc
├── index.html
├── public/
│   └── favicon.svg
├── scripts/                  契约与校验脚本
│   ├── export-openapi.py     调 app.openapi() 导出（由 pytest 复用）
│   └── check-contract.mjs    Zod 与生成类型一致性校验
└── src/
    ├── main.tsx               入口
    ├── App.tsx                根组件 + 路由表 + 壳层样式（App.module.css）
    ├── router/
    │   └── index.tsx          路由定义与守卫
    ├── pages/                 路由级组件
    │   ├── OptimizePage.tsx
    │   ├── OptimizePage.module.css  工作台页面层样式（2026-11-07 从 global.css 迁出）
    │   ├── HistoryPage.tsx         历史页（F-702 独立可用：列表 + 置顶/重命名/删除/复制路径/打开会话）
    │   └── ~~PreferencePage.tsx~~  偏好页（2026-10-21 移除）
    ├── components/
    │   ├── ui/                通用展示组件
    │   │   ├── Toggle.tsx         开关（设置中心用）
    │   │   ├── Slider.tsx         滑条（偏好/设置共用）
    │   │   ├── ConfirmDialog.tsx  通用确认弹窗（2026-11-01：遮罩 + 标题 + 正文 + 取消/危险确认，Esc/焦点管理）
    │   │   └── BrandMark.tsx      品牌标识内联 SVG（2026-11-01：气泡 + 火花，颜色随主题 token）
    │   ├── optimize/          优化流程组件
    │   │   ├── ConsoleInput.tsx     启动页主视觉输入卡片（对话式重构；2026-11-01 输入随内容自动增高至 6 行；模型选择器见 ModelPicker）
    │   │   ├── ModelPicker.tsx       模型选择器（2026-10-18：只列已配置条目；hover 飞出按模型参数面板——上下文长度 / 思考模式 / 思考强度，强度在开关关闭时置灰；档位取自官方静态登记，各模型独立；2026-11-08 兼会话级热切换入口，POST /sessions/{id}/model）
    │   │   ├── nativeFolder.ts     原生文件夹选择器桥（2026-10-19：页面 postMessage → 扩展 content script → service worker → native host → 系统对话框）
    │   │   ├── ChatStream.tsx       对话流（用户气泡 → 回复块：步骤时间轴（每步下方挂过程）+ 方案正文；2026-10-20 移除目标定位/取证/操作栏）
    │   │   ├── TraceEntry.tsx       工具动作卡（2026-11-07 两形态：命令→终端块 `$`+exit 胶囊+可展开输出；读文件→瘦胶囊行；展示后端实测耗时）
    │   │   ├── PhaseLedger.tsx      执行账本（2026-11-07：每阶段一行 28px，状态字形 + 等宽大写阶段名 + 动作计数，替代 ✓●○ 进度列表）
    │   │   ├── TypewriterText.tsx   逐字呈现（2026-11-07：rAF 每帧 3 字 + 方块光标；只在增量增长时逐字，减少动效时整段）
    │   │   ├── TurnList.tsx         多轮全文流（2026-10-20：进入即并发拉取每轮正文，用户气泡右 / 助手块左；2026-11-05 去掉 20 轮硬顶改分页增量加载，正文进 store 常驻）
    │   │   ├── TurnActions.tsx     轮级操作条（2026-11-05：「以此轮继续」+「撤销到此轮」danger 二次确认）
    │   │   ├── DeliveryGateCard.tsx 交付证据门卡片（2026-11-05：色阶用后端 tone、文案用后端 disclosure，前端零判定）
    │   │   ├── AssistantBlock.tsx  助手块同构渲染器（2026-11-05：历史轮与当前轮共用，时间轴/门禁/方案/回答，缺什么省什么不伪造）
    │   │   ├── AskPanel.tsx         反问面板（2026-10-20 v2：内联于对话流、自适应高度、超 60vh 中部滚动、头尾固定；2026-11-01 头部改折叠栏，收起只留一行摘要）
    │   │   ├── AskFlow.tsx          反问组合层（持有作答草稿，拼装 AskDialog + FollowupForm，2026-10-20）
        │   │   ├── PromptCard.tsx
    │   │   ├── VariantTabs.tsx
    │   │   ├── RecommendBadge.tsx
    │   │   ├── ScoreDetail.tsx
    │   │   ├── ConfidenceNotice.tsx
    │   │   ├── FollowupForm.tsx
    │   │   └── CopyButton.tsx
    │   ├── history/           历史页组件
    │   │   ├── ProjectSidebar.tsx  固定侧边栏（图三：头部「项目」+一键收纳；2026-11-01 起按 project_root 分组，组头带项目级删除）
    │   │   └── SessionMenu.tsx     会话 ⋮ 菜单（置顶/复制路径/重命名/删除；2026-11-01 删除改为上抛，确认统一走 ConfirmDialog）
    │   ├── ~~preference/~~     偏好页组件（2026-10-21 移除）
    │   │   └── ~~PreferenceEditor.tsx~~ 四维偏好编辑器（2026-10-21 随偏好层移除）
    │   └── settings/          设置中心组件（F-604，模态面板）
    │       ├── SettingsModal.tsx      弹窗外壳 + 左侧四项导航
    │       ├── ModelServicePanel.tsx  供应商卡（F-604 供应商中心化：配一次 Base URL/API Key → 刷新模型列表 → 多选 → 一键保存；测试连接与删除均在供应商级）
    │       ├── AppearancePanel.tsx    通用外观（主题/语言/字体/行为开关）
    │       ├── ~~MemoryPanel.tsx~~     长期记忆（2026-10-21 随偏好层移除；设置中心剩外观/模型服务/安全三面板）
    │       └── SecurityPanel.tsx      流程与安全（护栏参数/锁定项/清除数据）
    ├── stores/                Zustand store
    │   ├── useOptimizeStore.ts
    │   ├── useHistoryStore.ts     会话历史（2026-10-21 由 usePreferenceStore 改名精简）
    │   └── useSettingsStore.ts    设置状态（含 localStorage 读写封装）
    ├── hooks/                 自定义 Hook
    │   ├── useSSE.ts
    │   ├── useRunStream.ts        多端运行流（2026-11-07：先 fetchLastSeq → POST /runs → 订阅 /stream；按 seq 去重补帧）
    │   ├── useRequest.ts
    │   └── useDebounce.ts
    ├── api/                   请求封装
    │   ├── client.ts          基础请求层
    │   ├── endpoints.ts       接口定义（2026-11-08 增 setSessionModel：F10 会话级模型热切换，禁重试）
    │   ├── protocol.ts        运行时帧契约（RunEventSchema 判别联合 + applyRunEvent，2026-11-07）
    │   ├── interceptors.ts    拦截器
    │   ├── errors.ts          错误处理
    │   └── types.ts           请求响应类型
    ├── schemas/               Zod 运行时校验 + 自动生成类型
    │   ├── openapi.generated.ts   自动生成，勿手改
    │   ├── common.ts
    │   ├── optimize.ts
    │   ├── stream.ts             思考过程流事件契约（thought / snapshot / error 判别联合，2026-10-19）
    │   ├── history.ts            历史会话契约（F-501；自 preference.ts 迁出，2026-11-06）
    │   ├── settings.ts           设置契约校验（F-604）
    │   └── errorCodes.ts         错误码 → i18n 键映射（F-209；文案在 i18n/locales，须覆盖后端全部码）
    ├── i18n/                  多语言（F-209，2026-11-06）
    │   ├── index.ts           i18next 初始化（资源同步 import；locale 取 appearance 真源）
    │   └── locales/           zh-CN.json / en.json（键集一致由 keys.test.ts 守卫）
    ├── styles/                全局层（token 唯一来源 + reset + 跨组件原语，2026-11-07 起组件样式一律 module）
    │   ├── tokens.css         CSS Variables 设计 token
    │   ├── global.css         reset、基础排版、跨组件原语（.button/.field/.ask-panel/…，故意不隔离）
    │   └── phases.css         阶段指示器样式
    ├── lab/                   风格样张页（**dev-only**，2026-11-07；生产构建 DCE 剔除）
    │   ├── StyleLab.tsx       样张页外壳（风格/配色/主题/流式变体/回放控制，URL 参数可回填）
    │   ├── StyleLab.test.tsx  冒烟：三列渲染、切换写 data 属性、回放推进与暂停
    │   ├── LabSwitcher.tsx    分段控件 + 回放控制 + 章节外壳
    │   ├── labCopy.ts         样张文案 zh/en（不进生产语言包）
    │   ├── demoStream.ts      假流式事件序列 + 回放 hook（不触网、不做判定）
    │   ├── types.ts           样张枚举（风格/配色/变体/构图）
    │   ├── utils.ts           class 拼接、WCAG 对比度实测、减少动效检测
    │   ├── styles/
    │   │   ├── lab.css           Tailwind 入口（跳过 preflight）+ @theme token 桥接
    │   │   ├── lab-tokens.css    3 风格 × 3 配色 × 明暗的 token 覆盖（同名变量，不改 tokens.css）
    │   │   └── lab-motion.css    光标 / 轨道流光 / shimmer / reduced-motion 降级
    │   └── specimens/         组件标本（启动页 / 对话线程 / 三种流式 / 工具卡 / 侧边栏 / 配色表）
    ├── utils/                 前端纯工具
    │   ├── format.ts
    │   ├── css.ts                  CSS Modules 类名映射（makeS：编辑期可读名 → 哈希名，DEV 告警漏迁）
    │   └── diff.ts
    ├── types/                 类型定义
    │   └── index.ts
    └── assets/                静态资源
        └── icons.svg
```

### 5.2 目录组织原则

| 目录 | 职责 | 依赖规则 |
|---|---|---|
| `pages/` | 路由级组件 | 只做编排，不含复杂逻辑 |
| `components/` | 可复用组件 | 不直接调用 API（除专用容器组件） |
| `stores/` | 全局状态 | 只存跨组件共享状态 |
| `hooks/` | 自定义逻辑 | 组合 store 与 api |
| `api/` | 请求层 | 只负责网络，不含 UI 逻辑 |
| `schemas/` | 校验 | 与 `api/types.ts` 严格对齐 |
| `utils/` | 纯函数 | 无副作用，无外部依赖 |
| `styles/` | 样式 | 只含 token 与全局样式 |

**依赖方向**（严格单向，不可逆向）：

```
pages  →  components  →  hooks  →  stores  →  api  →  schemas
  ↓         ↓            ↓         ↓        ↓
styles    types      utils     utils     utils
```

**禁止**：

- `components/` import `pages/`
- `api/` import 任何 `components/` 或 `stores/`
- `utils/` import 任何其他目录
- `schemas/` import `api/`（方向相反，会造成循环依赖）

### 5.3 命名规则

| 类型 | 规则 | 示例 |
|---|---|---|
| 页面组件 | `PascalCase` + `Page` | `OptimizePage.tsx` |
| 展示组件 | `PascalCase` | `PromptCard.tsx` |
| 自定义 Hook | `useXxx.ts` | `useSSE.ts` |
| Store | `useXxxStore.ts` | `useOptimizeStore.ts` |
| API 模块 | 小写单数 | `client.ts`、`endpoints.ts` |
| 类型定义 | `PascalCase` 或小写分组 | `optimize.ts` |
| 样式文件 | `kebab-case` | `phase-indicator.css` |
| CSS Module 类名 | `kebab-case` | `.prompt-card__title` |
| CSS Variables | `--` + 语义 + 层级 | `--color-primary-500` |
| 常量 | `UPPER_SNAKE_CASE` | `FOLLOWUP_SOFT_ROUND_GUARD` |

**CSS 类名采用 BEM**：`.block__element--modifier`

**文件与主导出名必须一致**：`PromptCard.tsx` 必须 `export function PromptCard` 或 `export default PromptCard`。CI 检查此规则，避免 import 时猜文件名。

### 5.4 静态资源与样式组织

| 类型 | 位置 | 说明 |
|---|---|---|
| 组件样式 | `ComponentName.module.css` | 与组件同目录，CSS Modules |
| 全局样式 | `styles/global.css` | 只含 reset 与基础排版 |
| 设计 token | `styles/tokens.css` | 全部 CSS Variables 定义 |
| 第三方库样式 | `styles/vendor.css` | 若将来引入，隔离在此 |
| 图片与图标 | `assets/` 或 `public/` | `assets/` 会被构建处理，`public/` 原样拷贝 |

**设计 token 命名规范**（与被优化项目的识别能力对应）：

```
--color-{语义}-{层级}        例如 --color-primary-500
--space-{倍数}               例如 --space-4
--text-{角色}-{尺寸}         例如 --text-body-md
--radius-{级别}              例如 --radius-md
--shadow-{级别}              例如 --shadow-sm
--font-{用途}-{字重}         例如 --font-body-regular
```

**明暗双主题**：通过 `:root` 与 `[data-theme="dark"]` 下的同名变量覆盖实现，组件内不出现任何硬编码颜色。

**视觉语言与颜色语义（2026-11-07 起，S2「终端工具」）**：

| 类别 | token | 允许出现的位置 |
|---|---|---|
| 强调（石墨靛蓝） | `--color-primary-500/700/900/soft`、`--brand*` | 主按钮、链接、选中竖线、聚焦环、当前阶段、推荐卡描边 |
| 成功 | `--color-success-500/-soft` | 完成对勾、复制成功、API 正常 |
| 进行中 | `--color-running-500/-soft` | 阶段状态点、「进行中」标签 |
| 告警 / 失败 | `--color-warning-*` / `--color-danger-*` | 披露条竖线、失败动作描边与 Exit code、破坏性操作 |

**绿色不再作为品牌色**：任何按钮底色、链接、选中态都不使用绿色（2026-11-07 所有者裁定）。

**排版与形状**：字号阶梯 `22 / 16 / 14 / 13 / 12 / 11`（`--text-display` … `--text-micro`），元信息一律 `--font-family-code` + 大写 + 字距（`--track-micro` / `--track-wide`）；圆角 `8 / 8 / 10 / 8`；**卡片零投影**，层级靠 1px 描边与表面递进建立，仅浮层（菜单 / 弹窗）使用 `--shadow-lg` / `--shadow-menu`。

> **2026-11-07 迁移完成**：上表的 `ComponentName.module.css` 已全量落地（10 个组件级样式文件 + `App.module.css` / `pages/OptimizePage.module.css` 壳层与页面层）。规则：
> - 组件用 `import styles from './X.module.css'` + `const s = makeS(styles)`（`src/utils/css.ts`）包装 className，编辑期类名保持 BEM 可读，运行时映射为哈希名；
> - **两层语义**：模块内定义的类被隔离；未定义的（`.button` / `.field` / `.ask-panel` 等跨组件原语，仍在 `styles/global.css`）原样透传——原语层是设计系统的一部分，故意不隔离；
> - **错位检查**：`python scripts/check_css_modules.py frontend/src` 校验「TSX 用到的类名 ⊆ 该组件导入的 module ∪ 全局层」，返回非零即失败（2026-11-07 迁移时据此抓到 25 处挂错文件的类）；
> - 壳层的跨文件钩子（`lab.css` 隐藏标题栏/侧边栏）改用 `data-shell / data-titlebar / data-drawer` 属性选择器，不依赖哈希类名；
> - 样张页依赖 `.lab-surface[data-lab-style=…]` 的**模块外**选择器继续用 `:global` 语义（lab 自身是 Tailwind 体系，不受影响）。

**样张页（`src/lab`）的样式例外（2026-11-07，批准人=项目所有者）**：

| 规则 | 说明 |
|---|---|
| 颜色单一来源不变 | 色值只存在于 CSS；`lab-tokens.css` 用 `[data-lab-style][data-lab-palette][data-theme]` 覆盖**既有变量名**，`styles/tokens.css` 一行不改，生产界面零视觉变化 |
| Tailwind 只做桥接 | `lab.css` 用 `@theme inline` 把 `--color-surface-base` 等映射成 `bg-surface` / `text-ink` / `border-line`；组件里只出现语义类，**不出现字面色值** |
| 跳过 preflight | 只导入 `tailwindcss/theme.css` + `tailwindcss/utilities.css`，避免全局 reset 波及既有 100+ 组件 |
| 主题信号唯一 | 仍以 `data-theme` 为准（嵌套节点可局部换主题，做法与 `AppearancePanel` 的主题预览一致），不引入 `class="dark"` 第二套信号 |
| 生产零残留 | 入口经 `import.meta.env.DEV` 守卫 + `lazy()` 动态导入；验收时对 `dist/assets` 检索 `StyleLab` / `data-lab-style` / `lab-surface` 必须 0 命中 |
| 文案不进生产语言包 | 样张文案集中在 `labCopy.ts`（zh/en 两套），不写进 `i18n/locales/*.json` |

**样张页同样受门的约束**：`check_architecture.py` 的 MUST-08 阈值扫描、`jsxScan.test.ts` 的中文文案扫描、`staticChecks.test.ts` 的 useShallow 扫描**均覆盖 `src/lab`**，不设豁免；因此样张源码里不出现 `0.5` 这类会被误判为阈值的字面量（Tailwind 的 `gap-0.5` 改用 `gap-[2px]`）。

---

## 6. 状态管控

### 6.1 全局与局部的边界

**判定标准（三问）**：

| 问题 | 若是 → |
|---|---|
| 是否被两个以上互不相关的组件读取？ | 考虑提升 |
| 是否有明确的生命周期事件（创建/结束）？ | 考虑提升 |
| 是否是服务端数据的缓存？ | 放 store，但不进持久化 |

**本项目划分**：

| 状态 | 归属 | 说明 |
|---|---|---|
| 当前流程阶段 | 全局（`useOptimizeStore`） | 多组件需感知 |
| 三套方案内容 | 全局 | 多组件需读取 |
| 评分明细 | 全局 | 评分组件需读取 |
| SSE 连接状态 | 全局（`useOptimizeStore`） | 跨页面共享 |
| 历史会话列表 | 全局（`useHistoryStore`） | 两页共享（2026-10-21 起承接原 usePreferenceStore 的持久职责） |
| 输入框内容 | **局部** | 只有输入组件关心 |
| 折叠展开状态 | **局部** | 每张卡片独立 |
| 评分明细是否展开 | **局部** | 每张卡片独立 |
| 加载中的 spinner | **局部** | 组件自己知道 |
| 表单草稿 | **局部** | 提交后即销毁 |

**反模式警告**：

- ❌ 把组件的 `isOpen` 塞进全局 store——每张卡片会互相干扰
- ❌ 把一次性提示放进 store——应该用局部 state 或 toast
- ❌ 复制服务端数据到多个 store——会导致不同步

### 6.2 Store 配置

**为什么选 Zustand**：本项目无跨页面复杂状态。Redux Toolkit 的 slice/reducer/action 三层结构是纯开销；Zustand 的 `create` 写法在 TypeScript 下类型推导更直接，且不需要 Provider 嵌套。

**约定**：

| 规则 | 说明 |
|---|---|
| 命名 | `useXxxStore` |
| 返回 hook | 必须返回 `() => UseXxxStore` 形式 |
| 不导出 action | 状态与 action 一律通过 hook 返回，不单独导出 |
| 不在 store 内 fetch | 数据获取在 `api/` 或 `hooks/`，store 只存结果 |
| 单一 store 单一职责 | 不把优化流程状态与偏好/采纳历史塞进同一 store |
| selector 必须精确 | 避免 `useStore()` 全量订阅导致多余渲染 |

**Store 结构示例**：

```typescript
// stores/useOptimizeStore.ts
import { create } from 'zustand'
import { useShallow } from 'zustand/react/shallow'

interface OptimizeState {
  flowId: string | null
  phase: Phase
  variants: PromptVariant[]
  ranking: RankingResult | null
  followups: FollowupItem[]
  sseStatus: 'idle' | 'connecting' | 'open' | 'error'
  isSubmitting: boolean
  setFlow: (flowId: string, phase: Phase) => void
  patchPhase: (phase: Phase) => void
  setVariants: (variants: PromptVariant[]) => void
  setRanking: (ranking: RankingResult) => void
  setFollowups: (items: FollowupItem[]) => void
  setSseStatus: (s: SseStatus) => void
  setSubmitting: (v: boolean) => void
  reset: () => void
}

export const useOptimizeStore = create<OptimizeState>()((set) => ({
  flowId: null,
  phase: 'idle',
  variants: [],
  ranking: null,
  followups: [],
  sseStatus: 'idle',
  isSubmitting: false,
  setFlow: (flowId, phase) => set({ flowId, phase }),
  patchPhase: (phase) => set({ phase }),
  setVariants: (variants) => set({ variants }),
  setRanking: (ranking) => set({ ranking }),
  setFollowups: (followups) => set({ followups }),
  setSseStatus: (sseStatus) => set({ sseStatus }),
  setSubmitting: (isSubmitting) => set({ isSubmitting }),
  reset: () => set({ ...initialState }),
}))
```

**组件中用 selector 精确订阅**：

```typescript
// 正确：只订阅需要的字段
const phase = useOptimizeStore((s) => s.phase)
const variants = useOptimizeStore((s) => s.variants)

// 多字段：必须用 useShallow，否则每次渲染都触发
const { variants, ranking } = useOptimizeStore(
  useShallow((s) => ({ variants: s.variants, ranking: s.ranking })),
)
```

**`useShallow` 是必写的**：直接返回对象字面量会导致每次渲染都认为状态变了，引发无限重渲染。这是 Zustand 最常见的误用。

### 6.3 状态模块化拆分

**两个 store，边界清晰**：

| Store | 负责 | 生命周期 |
|---|---|---|
| `useOptimizeStore` | 单次优化流程的全部状态 | 流程开始时创建，`reset()` 时清空 |
| `useSettingsStore` | 外观与流程参数（localStorage 持久化 + 后端 settings 视图） | 应用级，跨页面持久 |

**不拆第三个 store 的理由**：SSE 状态属于优化流程，不独立；表单草稿属于组件局部，不进 store。

**何时该拆**：当某个 store 的字段超过 15 个，或有两组字段的生命周期明显不同时。

**跨 store 操作**：

```typescript
// 允许：在 hook 中组合两个 store
export function useProjectLauncher() {
  const project = useOptimizeStore((s) => s.project)
  const setAppearance = useSettingsStore((s) => s.setAppearance)

  return (projectPath: string) => {
    setAppearance({ ...useSettingsStore.getState().appearance })   // 仅示例：跨 store 组合写法
    return projectPath
  }
}
```

**禁止**：store 之间互相 import 对方的 state 定义。需要跨 store 操作时在 hook 中组合。

### 6.4 状态持久化

**采用分级持久化，只持久化真正需要跨会话的数据。**

| 数据 | 持久化 | 位置 | 原因 |
|---|---|---|---|
| 历史记录 | ✅ 持久 | 后端 SQLite | 有查阅价值 |
| 当前流程阶段 | ⚠️ 部分 | 后端 L1 Session | 服务端持久，页面刷新后从后端恢复 |
| 三套方案内容 | ⚠️ 部分 | 后端 L1 Session | 同上 |
| 外观设置 | ✅ 持久 | `localStorage` | 主题/语言/字体即开即得 |
| 输入框草稿 | ✅ 持久 | `localStorage` | 防误刷新丢失 |
| SSE 连接状态 | ❌ 不持久 | 内存 | 连接状态刷新后必然重连 |
| 折叠展开状态 | ❌ 不持久 | 内存 | 纯 UI 偏好 |
| 评分展开状态 | ❌ 不持久 | 内存 | 同上 |

**关键设计**：流程状态的权威存储在**后端**。前端 store 只是镜像。这样页面刷新或服务重启后，能从后端恢复同一状态——这是流程可恢复的必要条件。

**localStorage 键命名规范**：

```
devprompt:v1:appearance        外观设置（主题/语言/字体；Zod 校验读取）
```

> 其余状态（草稿、最近项目等）权威存储在后端 L1 Session；客户端只镜像。
> 键前缀 `devprompt:v1:` 结构变更时可整体失效（useSettingsStore.STORAGE_PREFIX）。

统一前缀避免与其他应用冲突。所有 key 必须带版本前缀（如 `devprompt:v1:appearance`，2026-10-13 定稿），便于将来变更结构时安全失效；TTL 暂不强制、后续按需补。

**敏感数据不入 localStorage**：项目路径可存（原句不存，涉及用户代码内容）。

**统一读写封装**：

```typescript
// 前端 storage 工具（utils/storage.ts）
export const storage = {
  get<T>(key: string, fallback: T, schema: ZodSchema<T>): T {
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return fallback
      const parsed = JSON.parse(raw)
      const result = schema.safeParse(parsed)
      return result.success ? result.data : fallback
    } catch {
      return fallback
    }
  },
  set<T>(key: string, value: T): void {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // 配额满或隐私模式，静默失败
    }
  },
  remove(key: string): void {
    try { localStorage.removeItem(key) } catch { /* noop */ }
  },
}
```

**注意**：读取时用 Zod 校验。localStorage 内容可能被用户手动改坏，不能直接信任。

---

## 7. 组件标准

### 7.1 组件分层

| 层级 | 目录 | 职责 | 允许调用 API |
|---|---|---|---|
| 展示组件 | `components/ui/` | 只渲染 props，无内部逻辑 | ❌ |
| 功能组件 | `components/optimize/` 等 | 内部逻辑，接收 props | ❌ 只能传回调 |
| 容器组件 | `pages/` | 编排 store + API + 功能组件 | ✅ |

**规则**：只有 `pages/` 与自定义 hook 可以调用 API 层。展示组件与功能组件通过回调上抛事件。

### 7.2 命名与文件组织

| 规则 | 说明 |
|---|---|
| 文件名 = 主导出名 | `PromptCard.tsx` 导出 `PromptCard` |
| 单文件单组件 | 例外：紧耦合的小组件可同文件，但不跨职责 |
| 组件目录按功能划分 | `components/optimize/` 而非 `components/cards/` |
| 类型文件不与组件混放 | Props 类型定义在 `types/` 或与组件同文件底部 |

### 7.3 Props 定义

**强制 TypeScript 类型，禁止 `any`**：

```typescript
// 正确
interface PromptCardProps {
  variant: PromptVariant
  isRecommended: boolean
  confidence: number | null
  onAdopt: (variantKey: VariantKey) => void
  onCopy: (content: string) => void
  disabled?: boolean
}

// 错误：any 会让类型系统失效
interface PromptCardProps {
  variant: any          // ❌
  onAdopt: (v: any) => void  // ❌
}
```

**Props 规范**：

| 规则 | 说明 |
|---|---|
| 全部必填或有默认值 | 可选 prop 必须有默认值语义 |
| 禁止可变对象 | 传对象时类型为 `Readonly<T>` |
| 回调用 void 返回 | `(x: T) => void`，不返回 Promise |
| 布尔 prop 用 is/has/should 前缀 | `isRecommended`、`hasError` |
| 避免 boolean prop 过多 | 超过 3 个布尔 prop 说明组件该拆分 |
| 不传 `undefined` 依赖 | 用可选链处理，不用 `prop !== undefined` 判断 |

**可变数据**：

```typescript
// 正确：只读
interface Props {
  variants: readonly PromptVariant[]
}
```

### 7.4 组件通信

| 场景 | 方式 | 禁止 |
|---|---|---|
| 父 → 子 | Props | — |
| 子 → 父 | 回调 props | 子直接改父状态 |
| 兄弟组件 | 共同父级回调 | 兄弟间直接 import |
| 跨页面 | Store | 事件总线 |
| 深层嵌套 | 提升状态或用 Context | 逐层透传 5 层以上 |

**Ref 的使用边界**：

| 用途 | 允许 |
|---|---|
| 聚焦输入框 | ✅ |
| 滚动到元素 | ✅ |
| 测量尺寸 | ✅ |
| 绕过 React 直接改 DOM | ❌ |
| 读取组件内部状态 | ❌ 应提升为 prop 或 store |

**禁止全局事件总线**。跨组件通信只有两条路：提升状态，或走 store。事件总线让数据流向不可追踪，是 React 项目腐化的主因。

### 7.5 复用与组合

**组合优于配置**：

```typescript
// 正确：用 children 组合
<Card>
  <CardHeader title="方案 A" />
  <CardBody>{content}</CardBody>
</Card>

// 错误：用配置枚举硬编码
<Card type="variant" variant="a" showHeader showScore />
```

**复用门槛**：

| 重复次数 | 做法 |
|---|---|
| 出现 2 次 | 保持重复，不抽象 |
| 出现 3 次 | 抽取为组件 |
| 逻辑相似但 UI 不同 | 抽取 Hook，不抽组件 |

**判据**：抽取后如果需要加 3 个以上的布尔开关来适配不同场景，说明抽象错了——**抽 Hook 或保持重复**。

**自定义 Hook 抽逻辑，组件抽 UI**：

```typescript
// 抽 Hook：逻辑复用，UI 各异
// 置信度分级由后端算好，前端只渲染 —— 前端不得出现任何阈值常量
// （AGENTS.md MUST-08）
function useConfidenceBadge(level: ConfidenceLevel | null) {
  return { level, showWarning: level !== 'high' && level !== null }
}

// 后端返回的契约（ConfidenceLevel = 'high' | 'low' | 'unknown'）
// 阈值 0.6 / 0.4 全部在 domain/ranking/ 内判定，前端无感知

// 抽组件：UI 复用，逻辑封装
function ConfidenceNotice({ level, detail }: Props) { ... }
```

### 7.6 样式作用域

**方案**：CSS Modules + 设计 token。

**规则**：

| 规则 | 说明 |
|---|---|
| 组件样式一律 CSS Modules | 禁止全局样式表里写组件类名 |
| 类名用 BEM | `.card__title--active` |
| 颜色只从 token 取 | 禁止硬编码 `#0f172a` |
| 间距只从 token 取 | 禁止 `margin-top: 13px` |
| 禁止 `!important` | 除非第三方样式无法覆盖 |
| 层级用 z-index token | 禁止魔法数字 |
| 响应式用断点变量 | 不散落断点数值 |

**Token 消费示例**：

```css
/* PromptCard.module.css */
.card {
  background: var(--color-surface-1);
  border: 1px solid var(--color-border-primary);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
}

.card__title--recommended {
  color: var(--color-primary-600);
  font-weight: var(--font-weight-semibold);
}
```

**全局样式只允许**：CSS reset、基础排版、滚动条、`:root` token 定义。**任何组件样式不得进全局文件。**

### 7.7 组件文档

**强制要求**：所有对外组件必须有 TSDoc 注释。

```typescript
/**
 * 单个优化方案展示卡片。
 *
 * 显示方案标题、内容预览、评分摘要与推荐标记，支持展开查看完整内容
 * 与评分明细。
 *
 * @example
 * ```tsx
 * <PromptCard
 *   variant={variant}
 *   isRecommended={true}
 *   confidence={0.82}
 *   onAdopt={handleAdopt}
 *   onCopy={handleCopy}
 * />
 * ```
 */
interface PromptCardProps { ... }
```

**必须写注释的内容**：

| 对象 | 要求 |
|---|---|
| 所有 props 接口 | 说明用途与约束 |
| 复杂 Hook | 说明返回值语义与调用时机 |
| 不直观的逻辑 | 注释「为什么」而非「做了什么」 |
| 算法 | 说明时间复杂度与边界条件 |

**不需注释**：自解释的简单函数、直白的状态赋值。

**文档位置**：组件内 TSDoc（首选） + `docs/components.md` 汇总（可选）。

---

## 8. 请求封装

### 8.1 HTTP 客户端配置

**基础封装**：

```typescript
// api/client.ts
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

interface RequestOptions extends Omit<RequestInit, 'body'> {
  timeout?: number
  retries?: number
  skipAuth?: boolean
  dedupeKey?: string
}

class HttpClient {
  async request<T>(path: string, options: RequestOptions): Promise<T> { ... }

  get<T>(path: string, options?: RequestOptions) { ... }
  post<T>(path: string, body: unknown, options?: RequestOptions) { ... }
  put<T>(path: string, body: unknown, options?: RequestOptions) { ... }
}
```

**基础配置**：

| 项 | 值 | 说明 |
|---|---|---|
| baseURL | 环境变量，默认为空（同源） | 生产单端口同源，无需 CORS |
| timeout | 默认 30000ms | 长任务走 SSE，不用 HTTP |
| credentials | `same-origin` | 为将来 Cookie 鉴权预留 |
| headers | `Content-Type: application/json` | 仅 POST/PUT |
| 响应解析 | 先 `res.json()` 再 Zod 校验 | 不信任后端 |

**环境变量**：

| 变量 | 开发 | 生产 |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | 空（同源） |

Vite dev 通过 `server.proxy` 把 `/api` 转发到后端，因此开发时也可用同源路径。

### 8.2 拦截器

**请求拦截链**：

| 顺序 | 处理 |
|---|---|
| 1 | 附加请求 ID（用于全链路追踪） |
| 2 | 附加鉴权凭证（若启用） |
| 3 | 序列化请求体 |
| 4 | 附加追踪头 |

**响应拦截链**：

| 顺序 | 处理 |
|---|---|
| 1 | 读取 `X-Request-ID` 存入错误上下文 |
| 2 | 按状态码分流（2xx 正常、其余抛错） |
| 3 | Zod 校验响应结构 |
| 4 | 归一化为内部类型 |

**Zod 校验是硬要求**：

```typescript
// 不信任后端返回
const parsed = OptimizeResponseSchema.safeParse(json)
if (!parsed.success) {
  logger.error('响应结构不符合契约', {
    issues: parsed.error.issues,
    requestId,
  })
  throw new ApiError(9000, '服务返回格式异常', { requestId })
}
return parsed.data
```

**这与后端 F-705 的三条防线配套**：Pydantic 是单一来源 → Zod 运行时校验 → CI 冒烟测试。少任何一环，契约漂移都会逃过检查。

### 8.3 统一错误处理

**错误分类**：

| 类型 | 触发 | 处理策略 |
|---|---|---|
| `NetworkError` | fetch 失败 | 可重试，提示检查网络 |
| `TimeoutError` | 超时 | 可重试，提示重试 |
| `ApiError` | 后端返回错误码 | 按码处理 |
| `ValidationError` | Zod 校验失败 | 不重试，属契约破坏 |
| `CancelError` | 主动取消 | 静默，不提示 |

**按错误码分支处理**：

| 错误码 | 前端行为 |
|---|---|
| 2005 候选集为空 | 显示引导，指引用户补充组件名 |
| 3002 置信度不足 | 显示 `ConfidenceNotice`，不标记推荐 |
| 3004 决策层速率限制 | 提示稍后重试，禁用提交按钮几秒 |
| 4002 LLM 不可达 | 提示检查 LLM 配置 |
| 6001 非法状态转移 | 刷新状态，提示重新开始 |
| 9001 内部异常 | 显示 requestId，便于排查 |

**统一错误出口**：

```typescript
// 组件不直接 try/catch，用 hook
const { optimize, error, isLoading } = useOptimize()

// 错误由 hook 内部归一化为 { code, message, requestId, action }
```

**错误信息展示原则**：显示后端 `message`（中文可操作），**不显示堆栈**。`requestId` 复制按钮便于用户反馈。

### 8.4 重试机制

**只对幂等且可重试的请求重试**。

| 场景 | 可重试 | 策略 |
|---|---|---|
| GET 请求 | ✅ | 指数退避，最多 2 次 |
| 429 速率限制 | ✅ | 按 `Retry-After` 头等待 |
| 5xx 错误 | ✅ | 指数退避，最多 2 次 |
| POST 优化请求 | ❌ | 有副作用，重试会产生重复流程 |
| 4xx 参数错误 | ❌ | 重试无意义 |

**退避算法**：

```
delay = base * 2^attempt + random(0, 100)
base = 500ms
最大延迟 5 秒
```

**必须带抖动**：无抖动的指数退避在并发场景会造成请求风暴。

**流式请求（SSE）不重试**：断流后由业务层显式决定是否重连，避免静默重复。

### 8.5 Token 刷新

**当前无鉴权，此逻辑预留但未启用。**

**预留设计**：

```typescript
// api/interceptors.ts（预留，auth 启用时生效）
let refreshPromise: Promise<string> | null = null

async function refreshToken(): Promise<string> {
  // 单例模式：并发请求共享同一个刷新
  if (!refreshPromise) {
    refreshPromise = doRefresh().finally(() => { refreshPromise = null })
  }
  return refreshPromise
}
```

**关键设计：单例刷新**。多个请求同时发现 token 过期时，只触发一次刷新，其余请求等待同一个 Promise。若不做单例，会并发发起多个刷新请求，其中部分可能用旧 token，导致刷新循环。

**刷新失败处理**：清空凭证 → 跳转登录（或本地模式则提示配置缺失）→ 清除相关缓存。

**存储位置**：token 存内存变量，刷新 token 存 `localStorage`。**access token 不存 localStorage**——这是 XSS 防护的基本要求。

**何时启用**：`AUTH_ENABLED=true` 时启用，见 §4.5。

### 8.6 请求取消与并发控制

**必须支持取消**：用户可能切换页面或重置流程，未完成的请求应立即中止。

```typescript
// hooks/useRequest.ts
function useAbortableRequest() {
  const controllerRef = useRef<AbortController | null>(null)

  const run = useCallback(async (fn: (signal: AbortSignal) => Promise<void>) => {
    controllerRef.current?.abort()      // 取消上一个
    const controller = new AbortController()
    controllerRef.current = controller
    try {
      await fn(controller.signal)
    } catch (e) {
      if (e.name === 'AbortError') return   // 静默处理
      throw e
    }
  }, [])

  const cancel = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
  }, [])

  return { run, cancel }
}
```

**并发控制策略**：

| 场景 | 策略 |
|---|---|
| 同一按钮的多次点击 | 禁用按钮 + AbortController |
| 切换页面 | 组件卸载时 `useEffect` cleanup 中 abort |
| 重新开始流程 | abort 全部未完成请求 |
| 输入框实时查询 | 防抖 300ms + abort 前一次 |

**SSE 连接的取消**：

```typescript
useEffect(() => {
  const es = new EventSource(`${BASE}/progress/${flowId}`)
  return () => es.close()    // 卸载时必须关闭，否则连接泄漏
}, [flowId])
```

**连接泄漏检查**：SSE 连接的 `close()` 必须在 effect cleanup 中。开发时通过 `http://localhost:8000` 观察连接数是否随切换页面累积。

### 8.7 去重与幂等

**请求去重**：

```typescript
// 相同 key 的在途请求共享同一个 Promise
const inflight = new Map<string, Promise<unknown>>()
```

适用场景：多个组件同时请求同一份数据（如历史列表被工作台与历史页读取）。

**幂等控制**：

| 操作 | 幂等 | 处理 |
|---|---|---|
| `GET /history` | ✅ | 去重 |
| `POST /optimize` | ❌ | 禁用重复提交 |
| `PUT /settings` | ✅ | 允许重试 |
| `POST /runs` | ❌ | 禁用重复提交 |

**`POST /optimize` 的防重**：提交后立即 `setSubmitting(true)`，请求结束前按钮禁用。**不靠时间戳去重**——时钟不可靠。

### 8.8 接口类型定义规范

**决策：TS 类型自动生成，Zod schema 手工。**

**单一来源**：后端 Pydantic 生成 OpenAPI，前端 TS 类型由 `openapi-typescript` **自动派生**，生成产物 `src/schemas/openapi.generated.ts` 入库。

**理由**：手工同步依赖人工纪律，无法保证「后端改字段前端必报错」，必然漂移。自动生成使契约防线可验证。

**目录分层**：

| 文件 | 内容 | 生成方式 |
|---|---|---|
| `schemas/openapi.generated.ts` | 全部接口类型 | **自动生成，勿手改** |
| `schemas/common.ts` | 通用 Zod 结构（分页、错误） | 手工，须与生成类型一致 |
| `schemas/optimize.ts` | 优化相关 Zod schema | 手工，须与生成类型一致 |
| `api/types.ts` | 请求响应类型 | 与 schema 对齐 |

**规则**：

| 规则 | 说明 |
|---|---|
| 类型与 schema 配对 | 每个响应类型有对应 Zod schema |
| 后端是唯一来源 | 字段定义以 Pydantic 为准 |
| 不用 `any` | 未知类型用 `unknown` + 收窄 |
| 枚举用字面量联合 | `type Phase = 'idle' \| 'retrieving' \| ...` |
| 可选字段显式 | `field?: T` 而非 `field: T \| null`（除非后端真会返 null） |
| 不重复定义 | 共享类型放 `common.ts`，不在各文件重复 |

**契约检查脚本**（CI 强制）：

```bash
# 1. 从后端源码导出 OpenAPI（无需启动服务）
#    在后端测试中调用 app.openapi() 导出到 frontend/openapi.json
pytest tests/test_openapi_export.py

# 2. 生成 TS 类型
cd frontend && pnpm gen:contract

# 3. 校验：生成产物与入库版本一致（不一致说明后端有字段变更未重新生成）
pnpm check:contract
```

**关键改进**：导出 OpenAPI **不依赖运行中的服务**（由后端测试导出），因此可在 CI 中执行。`scripts/` 目录需补入 §5.1 前端目录树。

**后端字段变更时前端必须报错**——这是契约防线的最终保障。

---

# 第三部分 · 附录

## A. 单一 Web 形态保证

| 环节 | 保证方式 |
|---|---|
| 业务逻辑 | 只有 `service.py` 一份，HTTP 层与前端都只调用它 |
| 状态机 | 同一份 `state.py`，状态存后端 L1 |
| 记忆 | 同一套 `memory/`，反馈提交立即生效 |
| 配置 | 同一份 `config.py`，环境变量统一 |
| 验证 | 契约冒烟测试 + 流程恢复一致性测试（功能清单 F-804） |

**破坏一致性的典型做法（禁止）**：

- ❌ HTTP 层（`interfaces/api/`）写一份评分逻辑，`service.py` 里再写一份
- ❌ 前端自己算总分
- ❌ HTTP 层自定义阈值
- ❌ HTTP 层走缓存、service 不走

## B. 架构约束检查清单

CI 中由脚本强制：

| 检查项 | 违反后果 |
|---|---|
| `domain/` 不 import `interfaces/` 或 `harness/` | 阻断 |
| `service.py` 不 import `interfaces/` | 阻断 |
| 前端无阈值常量 | 阻断 |
| SQL 只出现在 `memory/` | 阻断 |
| `common/` 无业务概念 | 告警 |
| 组件文件名与主导出名一致 | 阻断 |
| 所有路由有 `response_model` | 阻断 |
| 契约冒烟测试通过 | 阻断 |

## C. 文档与代码的对应关系

| 文档 | 回答的问题 | 更新时机 |
|---|---|---|
| 技术栈文档 | 用什么，为什么 | 技术选型变更时 |
| 功能清单 | 做什么，怎么验收 | 功能增删时 |
| 项目架构文档（本篇） | 怎么写代码，遵守什么规范 | 规范变更时 |

**冲突时以代码为准**，但必须同步更新对应文档。文档与代码不一致比没有文档更危险。

## D. 环境自检清单

新环境搭建后按此顺序验证：

| # | 检查 | 命令或方法 | 期望 |
|---|---|---|---|
| 1 | Python 版本 | `python --version` | ≥3.10 |
| 2 | 后端依赖 | `uv sync` | 成功 |
| 3 | ripgrep | `rg --version` | 有输出 |
| 4 | ctags | `ctags --version` | 有输出 |
| 5 | LLM 配置 | `GET /api/v1/health`（需先完成第 6 步启动） | `llm_config` 项通过 |
| 6 | 后端启动 | `uv run uvicorn devprompt_ai.interfaces.api.app:app --port 8000` | 端口监听 |
| 7 | 决策层配置 | 检查决策层为单一 LLM 实现（原 Jev 检查已于 2026-10-15 移除） | LLM 决策层可用 |
| 8 | 前端依赖 | `cd frontend && pnpm install` | 成功 |
| 9 | 前端启动 | `cd frontend && pnpm dev` | 页面可访问 |
| 10 | 健康检查 | `GET /api/v1/health` | `is_healthy` 为 true |
| 11 | Lint 全绿 | `uv run ruff check . && cd frontend && pnpm lint` | 无错误 |
| 12 | 类型检查 | `uv run mypy . && cd frontend && pnpm typecheck` | 无错误 |
| 13 | 测试 | `uv run pytest` | 全部通过 |

## E. 全局禁止事项

| 类别 | 禁止 |
|---|---|
| 依赖 | 引入未在技术栈文档登记的库；使用 `pip install` 全局安装 |
| 数据 | 密钥入库；用户原句写入日志（生产）；在 localStorage 存 access token |
| 架构 | `domain/` 含 I/O；前端含业务判定；SQL 出现在 `memory/` 之外 |
| 风格 | 硬编码颜色与间距；`!important`；魔法数字 |
| 提交 | 直推 `main`/`develop`；提交 `.env`、`node_modules`、日志 |
| 代码 | 裸 `except:`；`subprocess.run` 在 async 路径；`any` 类型 |
| 流程 | 跳过 CI 直接合并；契约变更不同步前端类型 |
