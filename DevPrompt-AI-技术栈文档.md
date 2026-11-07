# DevPrompt AI · 技术栈文档

> 版本 v1.2 · 2026-11-07（**限定范围引入 Tailwind v4 与 motion**：仅用于 dev-only 的 `src/lab` 风格样张页，生产界面仍为 CSS + CSS Variables；批准人=项目所有者）
> 配套文档：`DevPrompt-AI-功能清单.md`（v1.1）
> 版本核实日期：2026-11-07（新增依赖经 `registry.npmmirror.com` 核实），其余条目仍为 2026-10-04 快照

---

## 摘要

| 维度 | 选型 |
|---|---|
| 前端框架 | React 19.3 + TypeScript 5.9 |
| 构建工具 | Vite 7 |
| 包管理器 | pnpm 10 |
| CSS 方案 | CSS + CSS Variables（生产界面）；Tailwind v4 **仅限 dev-only 样张页**（§1.4） |
| 状态管理 | Zustand 5 |
| UI 组件库 | **不引入**（详见 §2.3） |
| 动效 | 生产界面：纯 CSS；样张页：`motion` 14（§1.6） |
| 后端语言 | Python 3.13 |
| Web 框架 | FastAPI 0.136 |
| 数据库 | SQLite（Python 标准库 `sqlite3`，WAL 模式） |

**与常见前端项目的三处差异**（下文逐条论证）：生产界面不用 Tailwind、不用 UI 组件库、不用 React Query。

---

# 一、前端技术栈

## 1.1 框架

| 项 | 选型 | 版本要求 |
|---|---|---|
| 框架 | React | `^19.3.0` |
| 渲染器 | React DOM | `^19.3.0` |
| 语言 | TypeScript | `^5.9.0`，`strict: true` |

**版本说明**：React 19.3.0 发布于 2026-09-09，是当前 `latest`。19.2.x 与 19.1.x 仍在维护，但新项目直接上 19.3。

**用到的 React 19 特性**：

| 特性 | 用途 |
|---|---|
| `use()` | 在条件分支中读取 Context 与 Promise，避免 `useEffect` 取数 |
| `useOptimistic` | 采纳反馈的即时 UI 更新 |
| `startTransition` | 反问步骤切换时的平滑过渡 |
| Fragment refs | 三套方案卡片展开/收起时管理焦点 |
| Server Components | **不启用**（纯客户端 SPA，无 SSR 需求） |

**不用 Server Components 的理由**：本项目是本地工具，需要访问本地文件系统（ripgrep 执行在 Python 侧），不存在 SEO 需求，也不需要流式首屏。引入 RSC 会让「本地文件系统访问」这个核心能力与渲染模型打架。

**TypeScript 配置要点**：

- `strict: true`，禁用 `any`
- `noUncheckedIndexedAccess: true`（数组访问返回 `T | undefined`）
- 优先 `type` 而非 `interface`，除非需要声明合并
- 状态机状态用**可辨识联合**（discriminated union）表达，如 `phase: 'idle' | 'retrieving' | ...`

## 1.2 构建工具

| 项 | 选型 | 版本要求 |
|---|---|---|
| 构建工具 | Vite | `^7.3` |
| React 插件 | `@vitejs/plugin-react` | `^5.1` |
| 路径别名 | `vite-tsconfig-paths` | `^6.0` |
| 类型检查 | `tsc --noEmit` | 随 TS 版本 |

**不用 Webpack 的理由**：Vite 7 开发态基于原生 ES Module，冷启动与 HMR 均为毫秒级；生产构建用 Rollup + esbuild。Webpack 5 在这三条上均无优势，且配置复杂度显著更高。

**tsconfig 用 Project References 拆分**为 `tsconfig.app.json`（浏览器代码）与 `tsconfig.node.json`（构建配置），这是 Vite 官方模板的现行标准做法。

## 1.3 包管理器

| 项 | 选型 | 版本要求 |
|---|---|---|
| 包管理器 | pnpm | `^10.15` |

**理由**：

- 硬链接 store 节省磁盘（node_modules 内容寻址去重）
- 严格依赖解析，未声明的依赖无法被 import（避免幽灵依赖）
- `pnpm-lock.yaml` 锁版本，满足 §5 可复现要求

**不用 npm / yarn 的理由**：npm 的扁平化 node_modules 有幽灵依赖问题；Yarn Berry 的 PnP 模式与 Vite 的解析兼容性历史上出过问题，且生态工具链对 pnpm 支持最完整。

## 1.4 CSS 方案

| 项 | 生产界面 | `src/lab`（dev-only 样张页） |
|---|---|---|
| 方案 | **CSS Modules + CSS Variables**（2026-11-07 全量迁移） | Tailwind CSS v4（utility 仅做 token 桥接） |
| 预处理器 | 不使用 | 不使用 |
| CSS-in-JS | 不使用 | 不使用 |
| 样式入口 | 各组件 `Xxx.module.css` + `styles/tokens.css`（token 唯一来源） + `styles/global.css`（reset / 壳层 / 跨组件原语） | `src/lab/styles/lab.css` |

**设计 token 定义**：全部放在 `styles/tokens.css`，用 CSS Variables 表达；样张页不改这个文件，只在 `src/lab/styles/lab-tokens.css` 里**用同名变量覆盖**。

**这个选择与项目本身有呼应关系**：DevPrompt AI 的核心能力之一是识别被优化项目的设计 token（如 `--color-primary-500`）。用同一套 CSS Variables 机制实现自身 UI，既是自证也是约束——我们推荐的 token 命名规范，自己也在用。

**为什么生产界面不用 Tailwind**（结论不变）：本项目 UI 元素种类极少（约 17 个），不需要原子类来加速开发；工具类会让「三套方案并排对比」这类精细布局的意图被淹没在 class 字符串里。

**为什么样张页用 Tailwind v4**（2026-11-07 新增，MUST-04 逐级说明）：
- 第 1~3 级不成立：同一份内容要并排试**三套**视觉体系（描边策略、圆角、密度、字重全不同），用原生 CSS 需要三套并行样式表并在推翻时同步维护三处，改动成本远高于一次工具类重排；语言内置（CSS 变量）已用于「同一套骨架换 token」，但无法覆盖「骨架本身也不同」。
- 第 4 级不成立：项目内现成的只有手写 CSS，没有可组合的样式原语。
- 第 5 级的最小代价方案：`tailwindcss` + `@tailwindcss/vite`，**只导入 `theme` 与 `utilities` 两层、跳过 preflight**（避免全局重置既有 100+ 组件），并只被 `StyleLab.tsx` 引用，生产构建经 DCE 完全剔除（已在 `dist/assets` 检索 `StyleLab`/`data-lab-style`/`lab-surface` 均为 0 命中）。
- 边界：色值仍只存在于 CSS（token 覆盖），组件里只出现 `bg-surface` / `text-ink` 这类语义类，不出现字面色值。

**全站改版如何落地（2026-11-07 实测结论）**：S2「终端工具」全站换肤只改 `styles/tokens.css` 的变量值（品牌色改靛蓝族、中性面改冷灰递进、正文 13px、新增 `--text-micro/--text-meta` 与 `--color-running-*`），**115 处既有 `--color-primary-*` / `--brand*` 引用自动跟随**，未新增任何前端依赖、未改写既有组件 CSS 结构。这条路径验证了「token 唯一来源」的价值：换视觉不等于换技术栈。

**为什么不用 CSS-in-JS**：运行时开销与 SSR 兼容性问题（本项目不需要 SSR，但引入额外复杂度无收益）。

## 1.5 动效方案（2026-11-07 新增）

| 场景 | 方案 |
|---|---|
| 生产界面（悬停、展开、呼吸、光标） | 纯 CSS（`transition` / `@keyframes`），必须尊重 `prefers-reduced-motion` |
| 样张页的条目入场、阶段切换、摘要高度展开 | `motion` 14.10.0（React 版） |

**为什么样张页用 motion**：摘要展开需要「高度 auto + 布局动画」，CSS 需要预设具体高度，做不到内容自适应；条目入场在多条目并行时，纯 CSS 需要给每条编号 delay，改一处数据要同步改样式。项目内无等价封装（第 3 级不成立），故为**样张页专属依赖**。

**版本核实（MUST-24b，2026-11-07 经 registry.npmmirror.com 查询最新稳定版）**：

| 依赖 | 已装版本 | 查询时最新版 | 用途 |
|---|---|---|---|
| `tailwindcss` | 4.3.4 | 4.3.5 | 样张页 utility |
| `@tailwindcss/vite` | 4.3.4 | 4.3.5 | Vite 插件（构建期生成 CSS） |
| `motion` | 14.10.0 | 14.10.1 | 样张页布局/入场动画 |

> 采用「小版本固定」而非 `^`：这三个包只在样张页使用，升级收益低，固定版本可避免 lockfile 漂移带来构建差异；后续如需升级，先跑 `pnpm build` + `pnpm test` 再改版本号。

## 1.6 状态管理

| 项 | 选型 | 版本要求 |
|---|---|---|
| 全局状态 | Zustand | `^5.0` |
| 服务端状态 | **不引入专门库** | — |
| 本地状态 | React `useState` / `useReducer` | — |

**两个 store**：

| Store | 职责 |
|---|---|
| `useOptimizeStore` | 当前流程阶段、三套方案、评分明细、置信度、SSE 连接状态 |
| `usePreferenceStore` | 偏好向量、历史采纳记录 |

**为什么不用 Redux Toolkit**：本项目无跨页面复杂状态，slice/reducer/action 的三层结构是纯开销。Zustand 的 `create` 写法在 TypeScript 下类型推导更直接，且不需要 Provider 嵌套。

**为什么不用 React Query**：三个理由。

1. 流程是线性四阶段，请求时序可预测，不需要缓存层
2. SSE 进度流必须自行管理连接生命周期，与 React Query 的缓存模型不兼容
3. 引入后需要处理「哪些数据进缓存、哪些不进」的额外决策

**服务端状态的实际处理**：组件内自行 `fetch` + Zustand 存放结果。请求量极低（一次优化共 4–6 个请求），缓存策略优化收益为零。

**为什么不用 TanStack Router**：官方文档推荐它做类型安全的文件路由，但本项目只有 3 个页面，React Router 的 `createBrowserRouter` 已足够。TanStack Router 的类型优势在页面数增长后才显现。

## 1.7 路由

| 项 | 选型 | 版本要求 |
|---|---|---|
| 路由 | React Router | `^7`（库模式） |

三个路由：`/`（优化主页）、`/history`（历史记录）、`/preference`（偏好管理）。

**用库模式而非数据模式**：数据模式（`loader`）适合 SSR/SSG 场景，本项目不需要。

---

# 二、UI 组件库

## 2.1 结论

**不引入任何第三方 UI 组件库。**

自建组件共 10 个，全部位于 `frontend/src/components/`。

## 2.2 候选库评估

| 库 | 版本 | 评估结论 |
|---|---|---|
| Shadcn/ui | v2 | ⚠️ 最接近的选择，但**为本项目杀鸡用牛刀**。详见 §2.4 |
| Radix UI | — | 提供无样式基元（本项目不需要复杂交互基元） |
| Base UI | `^1.0` | 同上，2025-12 稳定版 |
| MUI / Ant Design | v7 / v5+ | ❌ Material/Ant 设计语言与本项目风格冲突，且体积庞大 |
| Headless UI | — | ❌ 仅 10+ 组件，覆盖不了需求 |
| daisyUI | v5 | ❌ 纯 CSS 插件，只服务 Tailwind 场景；本仓 Tailwind 仅限样张页，生产界面用不上 |
| HeroUI | v2 | ❌ npm 依赖模式，体积大，含 framer-motion |
| Mantine | v8 | ❌ 完整库（120+ 组件），远超需求 |

## 2.3 自建组件清单

| 组件 | 职责 | 复杂度 |
|---|---|---|
| `PromptCard` | 单套方案展示，可展开评分明细 | 中 |
| `RecommendBadge` | 【推荐】标记 + 置信度 | 低 |
| `FollowupForm` | 反问卡片，批量填写未确认项 | 中 |
| `ScoreDetail` | 评分明细（三信号 + 总分计算过程） | 低 |
| `ConfidenceNotice` | 置信度不足提示区 | 低 |
| `OptimizeInput` | 原句输入 + 项目路径选择 | 低 |
| `PhaseIndicator` | 流程阶段指示器 | 低 |
| `VariantTabs` | 三套方案切换（移动端） | 低 |
| `CopyButton` | 一键复制 | 低 |
| `PreferenceEditor` | 偏好向量编辑 | 中 |
| `SessionSidebar` | 会话侧栏（工作台左栏，T6-10 补） | 低 |
| `ContextPanel` | 上下文面板（工作台右栏，T6-10 补） | 低 |
| `SettingsModal` | 设置中心弹窗外壳（T6-10 补） | 中 |
| `ModelServicePanel` | 设置 · 模型服务（T6-10 补） | 中 |
| `AppearancePanel` | 设置 · 通用外观（T6-10 补） | 低 |
| `MemoryPanel` | 设置 · 长期记忆（T6-10 补） | 中 |
| `SecurityPanel` | 设置 · 流程与安全（T6-10 补） | 中 |

**总量约 17 个组件**（T6-10 核对补齐 6D 与设置中心七件；全清单以架构文档 §5.1 为唯一权威），全部无第三方基元依赖。这是判断「不需要组件库」的核心依据——多数 UI 组件库的复杂度是为了解决表格、日期选择器、复杂表单校验等本项目不存在的问题。

## 2.4 关于 Shadcn/ui 的说明

Shadcn/ui 在 2026 年是 React 生态最主流的选择（周下载量 500 万+），且**重要变更：2026 年 7 月起，新项目的默认基元从 Radix UI 切换为 Base UI**（Radix 仍可通过 `-b radix` 参数使用）。

**没有选择它的三个理由**：

1. **会把 Tailwind 带进生产界面**。Shadcn/ui 与 Tailwind v4 深度绑定（OKLCH 颜色、CSS-first 配置）。样张页引入的 Tailwind 是**限定范围**（§1.4：跳过 preflight、dev-only chunk、生产构建剔除）；用 Shadcn/ui 则必须让 Tailwind 接管生产界面的全部样式，等于放弃 §1.4 的 CSS Variables 决策。
2. **本项目组件规模有限（约 17 个，T6-10 校正）**。Shadcn/ui 的优势在 20+ 组件的大型表单/仪表盘场景才充分体现。本项目的组件逻辑简单，自己写反而更快。
3. **update 不自动到达**。复制粘贴模型意味着需手动跟踪上游变更。本项目组件少，维护成本可控，但这个成本换来的收益不足以覆盖 Tailwind 的代价。

**什么情况下应该改用它**：如果 Web 形态后续扩展出复杂筛选器、多行表格、日期范围选择等交互组件，届时 Shadcn/ui 的价值会凸显，应重新评估。

---

# 三、后端语言

## 3.1 选型

| 项 | 选型 |
|---|---|
| 语言 | **Python** |
| 最低版本 | **3.10**（`openai-agents` 的硬性要求） |
| 推荐版本 | **3.13** |
| 包管理 | `uv` 或 `pip` + `pyproject.toml` |

## 3.2 为什么是 Python

| 决定性因素 | 说明 |
|---|---|
| 生态锁定 | `openai-agents`、`pydantic` 均为 Python 优先或 Python 独占 |
| Web 框架 | FastAPI + Pydantic 是 Python 生态最成熟的异步 HTTP 组合 |
| 检索实现 | `subprocess` 调 ripgrep / ctags，Python 表达最直接 |
| 项目现状 | 你已有的工程经验（FastAPI / Vue / TS）可直接迁移 |

## 3.3 版本选择说明

**最低 3.10**：`openai-agents` 要求 `>=3.10`，且要求原生 `X | Y` 联合类型语法（3.10 引入）。

**推荐 3.13**：当前稳定版（3.13.5），free-threaded 模式已可用。**不建议上 3.14+**——3.14 较新，第三方依赖（尤其 `openai-agents` 依赖链）的兼容性验证还不充分。

## 3.4 并发模型

**Async-first 全栈**。

| 层 | 方案 |
|---|---|
| Web 框架 | `async def` 路由 |
| LLM 调用 | 异步 HTTP 客户端 |
| ripgrep 执行 | `asyncio.create_subprocess_exec` |
| 阻塞操作 | 放入线程池（`run_in_threadpool`） |

**关键约束**：请求路径上不得出现同步阻塞调用。ripgrep 与 ctags 是子进程，用异步子进程而非同步 `subprocess.run`；确实无法异步化的操作走线程池。

## 3.5 包管理

**优先 `uv`**（Rust 实现，解析与安装速度显著优于 pip），回退 `pip`。

依赖必须锁版本。FastAPI 仍是 0.x 版本，小版本会重命名内部 helper，锁定是必要的。

---

# 四、后端开发框架

## 4.1 选型

| 项 | 选型 | 版本要求 |
|---|---|---|
| Web 框架 | **FastAPI** | `^0.136` |
| ASGI 服务器 | Uvicorn | `^0.34` |
| 数据校验 | Pydantic v2 | `^2.10` |
| 测试 | pytest + pytest-asyncio + httpx | 最新稳定 |

## 4.2 FastAPI 核心特性与本项目用点

| 特性 | 在本项目的用点 |
|---|---|
| **自动 OpenAPI 3.1 生成** | 前端契约的**单一来源**。Pydantic 模型变更自动同步 API 文档，前端据此对齐类型（功能清单 F-705） |
| **类型驱动依赖注入** | `Depends` 注入配置、DB Session、当前 `user_id`。`Annotated[X, Depends(...)]` 写法避免重复声明 |
| **Pydantic v2 原生集成** | 请求/响应模型的校验与序列化。Rust 核心比 v1 快 5–50 倍 |
| **原生 async** | 与 `openai-agents` 的异步模型一致，SSE 推送天然支持 |
| **Starlette 中间件** | CORS、请求 ID 注入、耗时统计 |
| **自动交互式文档** | `/docs` 直接可用，联调期价值高 |

## 4.3 为什么不用其他框架

| 框架 | 不用的理由 |
|---|---|
| Flask | 同步模型，与 async LLM 调用链冲突；类型支持弱于 FastAPI |
| Django | 太重（ORM、Admin、模板系统全带），本项目只需 HTTP 层 + 两张表 |
| NestJS | 需 Node.js 生态，与 `openai-agents` 不兼容 |
| Gin / Echo | 同上，且本项目后端与决策层 SDK（`openai-agents`）要求同一语言 |
| Spring Boot | Java 生态，与决策层依赖不兼容 |

## 4.4 数据层

| 项 | 选型 | 说明 |
|---|---|---|
| 存储 | **SQLite**（单文件，WAL 模式） | 三个记忆层中的 L1（Session）与 L3（偏好向量），落 `DATA_DIR`（默认 `~/.devprompt-ai/devprompt.db`） |
| 驱动 | Python 标准库 `sqlite3` | **零第三方依赖**（MUST-04 第 2 级）；同步 API 经 `run_in_threadpool` 包异步（MUST-13 允许） |
| ORM | **不引入** | 两张表用原生 SQL 更直接（见下） |
| 迁移 | **暂不需要** | 表结构简单，`memory/schema.py` 启动时幂等建表 |

**为什么用 SQLite**（用户决策，2026-10-07 回改定稿；此前 2026-10-04 曾改 MySQL，经对比评估回改）：

- 本地工具即开即用：用户导入项目场景下记忆是「使用者本地数据」，零安装/零服务/零凭据，消除「MySQL 不可达即冻结」的部署风险
- MUST-04 第 2 级（标准库）优于第 4 级（第三方 aiomysql），且 aiomysql 0.x API 未稳定
- WAL 模式 + busy_timeout + CAS UPDATE 足以承载多请求并发写（MUST-11 乐观锁语义不变）
- 数据即文件：备份/迁移 = 复制文件；MUST-23 已将 `*.db` 排除出 Git
- 代价：多用户/远程部署需届时更换后端——`SessionStore` Protocol 已隔离，属配置级切换

**为什么不用 JSON 纯文件**：L3 偏好历史表（30 轮滑动平均、聚合查询）需要 SQL 能力，全量读写 JSON 会随历史增长而笨重；SQLite 兼得「零运维」与「查询能力」。

**为什么不用 MySQL / PostgreSQL**：单用户本地场景下提前支付独立数据库服务的运维成本，价值主张（本地工具）优先；多用户态确认后经 `SessionStore` Protocol 切换，影响面可控。

**为什么不用 ORM / Alembic**：两张表（`forge_sessions`、`preferences`）用原生 SQL 更直接；无生产部署需求，引入 ORM 与迁移框架属过早优化。SQL 只允许出现在 `memory/` 模块内（MUST-06）。

**L1 Session 落地方式**：`openai-agents` SDK 自带的 Session 实现（`SQLiteSession` / `AdvancedSQLiteSession` / `AsyncSQLiteSession`）面向**对话历史**（`get_items/add_items`），与本项目状态机快照（state/version/data）语义不匹配。因此 L1 走**自定义 `SQLiteSessionStore`**，落点 `memory/session_store.py`，经 `SessionStore` Protocol 由 service 注入。

**连接管理**：

- 每个读写操作在 `asyncio.to_thread` 中独立开连接（`sqlite3.connect(db_path, timeout=5)`），用完即关——避免跨线程共享连接的复杂度
- 首次使用时执行 `PRAGMA journal_mode=WAL` + `busy_timeout=5000` + 幂等建表（`memory/schema.py`）
- 写操作 CAS：`UPDATE ... WHERE session_id=? AND version=?`，0 行更新即版本冲突（6001）

## 4.5 决策层 SDK

| 项 | 选型 | 版本 | 说明 |
|---|---|---|---|
| Harness | `openai-agents` | `>=0.23.1,<1.0`（PyPI 实际最新 0.23.1，**尚未发布 1.0**，经 MUST-24b 核实） | Runner / Session / Guardrail / Tracing |

**`openai-agents` 关键约束**（写代码时必须遵守）：

| 约束 | 说明 |
|---|---|
| 只依赖 `Runner` | `AgentLoop` 在官方文档中仅为架构概念，**不是可导入的公开类** |
| **禁用** `set_default_openai_api` 全局开关 | 进程级单例；Web 并发下按 provider 反复设置会相互覆盖 → 随机 4xx。改为 `harness.llm.build_model()` **按调用构造 Model 实例**（2026-09-17） |
| API 形态按 provider 分流 | `chat_completions`（绝大多数第三方）/ `responses`（OpenAI 官方）/ `anthropic_messages` / `gemini_generate_content`，见 `domain/model_spec.ProviderSpec.api_mode` |
| 必须 `set_tracing_disabled(True)` | 第三方 API key 上传 OpenAI tracing 会返回 401 |

## 4.6 检索工具

| 项 | 选型 | 说明 |
|---|---|---|
| 全文检索 | ripgrep（`rg --json`） | 通过异步子进程调用 |
| 符号抽取 | universal-ctags | 生成符号表，支持增量更新 |
| 分词 | Python 内置 + 轻量库 | 中文按字符二元组，英文按驼峰/下划线拆分 |

**不用向量检索**：本项目检索目标是「精确的代码位置」，向量相似度对符号名匹配无优势，且引入索引维护成本。决策层（LLM 实现）的排序能力已覆盖语义相关性的判定需求。

## 4.7 Web 框架端点清单

原命令行框架节已随 CLI 形态废除（v1.1 BREAKING）删除，替换为 FastAPI 已实现的端点清单（`interfaces/api/routes.py`）。

**统一前缀**：`/api/v1`，统一响应信封 `ApiResponse`（code / message / data / request_id）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 环境自检：rg / ctags / git 版本、DB 文件可写、LLM 配置非空 |
| POST | `/optimize` | 启动优化流程，返回流程快照（有副作用，客户端禁重试） |
| GET | `/progress/{flow_id}` | SSE 进度流（1s 轮询推送快照，终态/反问/护栏后关闭） |
| POST | `/followup/{flow_id}` | 反问交互三模式（互斥）：answers / escape / guardrail_action |
| GET | `/result/{flow_id}` | 获取流程快照（含三套方案与评分） |
| POST | `/feedback` | 提交采纳反馈，写入 L3 偏好信号 |
| GET | `/preference` | 查询偏好向量 |
| PUT | `/preference` | 更新偏好向量（部分更新 + clip01 截断；T6-11 转正） |
| GET | `/history` | 历史会话摘要（脱敏：id/时间/state/项目名；T6-11 转正） |
| GET | `/project/scan` | 项目符号表扫描（符号总数 / 文件数 / 类型分布） |
| GET | `/project/browse` | 文件资源管理器数据源（页内）：path 空=驱动器列表；条目为目录（名称/修改日期），名称升序；可选 `q`=当前目录子树递归搜索（2026-10-13），条目附 `rel_parent` 相对父路径 |
| GET | `/settings` | 读取设置（模型服务脱敏 + 流程参数 + 锁定项；T6-11） |
| PUT | `/settings` | 更新设置（模型段 → settings.json 0600；流程段 → app_settings 表）；2026-10-13 增 `models`/`active_model_id` 多模型注册表段（整表替换 + 切换生效项） |
| DELETE | `/preference/adoptions` | 清空服务端采纳历史，返回清空条数（D-6F-4 关闭） |

## 4.8 配置管理

| 项 | 选型 |
|---|---|
| 配置读取 | Pydantic Settings |
| 优先级 | init > 环境变量 > 本地设置（settings.json + app_settings 表）> .env > 默认值 |
| 存储 | `.env`（不入库） + `.env.example`（入库）+ `settings.json`（0600，密钥唯一落盘处；含 `model_service` 生效配置段与 `models`/`active_model_id` 多模型注册表段） |

**存储路径配置**：`DB_PATH`（默认 `~/.devprompt-ai/devprompt.db`）经环境变量覆盖；数据目录不存在时启动自动创建。**前端构建产物路径**：`DEVPROMPT_FRONTEND_DIST`（空=回落仓库根 `frontend/dist`）指定打包部署时托管的 `dist` 目录（架构文档 §1.6）。**密钥边界（MUST-19 修订后，真源 §13 2026-10-12）**：API Key 仅可存本地 `settings.json`（0600）与 `.env`，不入 SQLite、不进日志，GET 回显恒脱敏。

---

# 五、工程化与质量保障

## 5.1 依赖锁定

| 层 | 文件 | 要求 |
|---|---|---|
| Python | `pyproject.toml` + `uv.lock` / `requirements.txt` | 精确锁定版本 |
| Node | `package.json` + `pnpm-lock.yaml` | 精确锁定版本 |

**FastAPI 仍是 0.x 版本**，小版本会重命名内部 helper，锁版本是必要的。

## 5.2 代码质量

| 工具 | 语言 | 用途 |
|---|---|---|
| Ruff | Python | Lint + Format（取代 flake8 + black + isort） |
| mypy | Python | 静态类型检查 |
| ESLint + typescript-eslint | TypeScript | Lint |
| prettier | TypeScript | Format |
| oxlint（可选） | TypeScript | 更快 lint，CI 可用其替代 ESLint |

**类型检查必须开启**。本项目有两处强依赖类型正确性的地方：状态机的可辨识联合、以及前后端契约的 Zod/Pydantic 对齐。类型检查是这两处的第一道防线。

## 5.3 测试

| 项 | 选型 | 说明 |
|---|---|---|
| Python 测试 | pytest + pytest-asyncio | 异步测试支持 |
| HTTP 测试 | httpx | 配合 FastAPI `TestClient` |
| 前端测试 | Vitest | 与 Vite 同源，配置零成本 |
| E2E 测试 | Playwright（**未采用**） | 流程恢复一致性测试（功能清单 F-804）；本项目从未引入 |
| Mock | 决策层 mock | 无外部决策服务时可完整测试 |

**Mock 策略**：决策层（LLM 单一实现）可 mock。W1 的准确率实测（功能清单 F-801）不依赖任何外部 API。

**未采用项澄清（MUST-24b 口径，不登记版本）**：Playwright（E2E，从未引入）、structlog（结构化日志，已由标准库 `logging` 替代，见架构文档 §4.1）、asyncpg（PostgreSQL 驱动，存储定稿 SQLite 后从未需要）——三者**未采用**。

## 5.4 CI 约束（架构级强制）

**CI 门禁以宪法 MUST-29 为准（唯一权威），本文档不重复罗列检查项。**

## 5.5 部署

| 环境 | 方式 |
|---|---|
| 开发 | Vite dev server（:5173）→ proxy → FastAPI（:8000） |
| 生产 | `vite build` → `dist/` → FastAPI 静态托管，**单端口对外** |

**单端口是关键决策**：避免 CORS 配置与本地 session 丢失，确保 HTTP API 与前端行为一致。

**生产单端口托管（T7-7）**：FastAPI 托管 `frontend/dist`（SPA 回退，`/api` 前缀不遮蔽）；产物目录默认取仓库根 `frontend/dist`，可用环境变量 `DEVPROMPT_FRONTEND_DIST` 覆盖（打包部署时指向实际 dist 路径）。

---

# 六、版本汇总表

## 6.1 前端

| 包 | 版本要求 |
|---|---|
| react / react-dom | `^19.3.0` |
| typescript | `^5.9.0` |
| vite | `^7.3` |
| @vitejs/plugin-react | `^5.1` |
| vite-tsconfig-paths | `^6.0` |
| zustand | `^5.0` |
| react-router | `^7` |
| zod | `^4` |
| i18next | `^26.7.2`（2026-11-06 F-209 多语言；版本经 npm registry 核实） |
| react-i18next | `^17.1.13`（peer: i18next ≥26.2 / react ≥16.8） |

> **MUST-04 第 5 级论证（F-209）**：React 无内置 i18n；标准库 `Intl` 只做日期/数字/复数格式化，
> 不做查表、插值与语言切换；项目内无封装（自建等于重写 i18next 核心子集）；已登记依赖均不含 i18n。
> 故按业主指定引入两个包，`pnpm-lock.yaml` 锁定。
| eslint | `^9` |
| prettier | `^3` |
| vitest | 最新稳定 |
| jsdom（dev） | `^30.1.2` |
| @testing-library/react（dev） | `^16.3.3` |
| @testing-library/dom（dev） | `^10.4.2` |
| @testing-library/user-event（dev） | `^14.6.7` |
| typescript-eslint（dev） | `^8.71.0` |
| @eslint/js（dev） | `^9.39.5` |
| openapi-typescript（dev） | `^7.13.0` |
| tailwindcss（dev，样张页专用） | `4.3.4` 固定（2026-11-07 核实；仅 `src/lab`） |
| @tailwindcss/vite（dev，样张页专用） | `4.3.4` 固定 |
| motion（样张页专用） | `14.10.0` 固定 |

**T6-3 前端工程基座新增 dev 依赖登记（2026-10-12，MUST-24b）**

版本号均经 npm 官方 registry 核实（`pnpm info <pkg> version`），并与 `frontend/pnpm-lock.yaml` 锁定版本一致：

| 包 | registry 最新 | 锁定版本 |
|---|---|---|
| jsdom | 30.1.2 | 30.1.2 |
| @testing-library/react | 16.3.3 | 16.3.3 |
| @testing-library/dom | 10.4.2 | 10.4.2 |
| @testing-library/user-event | 14.6.7 | 14.6.7 |
| typescript-eslint | 8.71.1 | 8.71.0（`^8.71.0` 区间内） |
| @eslint/js | 10.0.1 | 9.39.5（受 `eslint ^9` 约束，不跨主版本） |
| openapi-typescript | 7.13.0 | 7.13.0 |
| vitest | 5.0.4 | 5.0.4（对齐「最新稳定」要求） |
| vite-tsconfig-paths | 6.1.1 | 6.1.1（§6.1 原有 `^6.0`，未改要求） |

**选择理由（MUST-04：1–4 级能力不可替代，方落 5 级新增）**

| 依赖 | 为什么原生能力/已登记依赖不可替代 |
|---|---|
| jsdom | Vitest `environment: 'jsdom'` 的宿主环境本体，JS/TS 标准库无 DOM 实现；无它则组件测试只能跑 Node 环境，`@testing-library/react` 无法渲染 |
| @testing-library/react（含 peer @testing-library/dom） | React 19 已移除 `react-dom/test-utils`（含 `act` 移出），React 自身不提供测试渲染器；Testing Library 是 React 官方文档指向的组件测试标准 |
| @testing-library/user-event | 模拟真实用户事件链（指针/键盘/输入时序），`fireEvent` 无法覆盖交互语义；组件交互测试事实标准 |
| typescript-eslint + @eslint/js | ESLint 9 flat config 下解析 TS 语法与类型规则的官方实现，ESLint 核心不解析 TypeScript（§6.1 已列 eslint，二者为其配套） |
| openapi-typescript | F-705 契约管线指定工具（Pydantic → OpenAPI → TS 类型自动生成），属已登记技术决策，无标准库等价能力 |

已排除项连带确认：生产界面未引入 Tailwind / UI 组件库 / CSS-in-JS / Redux Toolkit / React Query（F-701），主题切换用 CSS Variables + `data-theme`，滑条/开关为自研组件。Tailwind v4 与 motion 仅存在于 dev-only 的 `src/lab`（§1.4/§1.5），生产构建已验证不含其代码与样式。

## 6.2 后端

| 包 | 版本要求 |
|---|---|
| python | `>=3.10`，推荐 `3.13` |
| fastapi | `^0.136` |
| uvicorn | `^0.34` |
| pydantic | `^2.10` |
| pydantic-settings | `^2.7` |
| openai-agents | `>=0.23.1,<1.0`（尚未发布 1.0，MUST-24b 核实） |
| pytest / pytest-asyncio / httpx | 最新稳定 |
| pytest-cov（dev） | `>=7.1,<8`（PyPI核实 7.1.0，MUST-24b）；用途=覆盖率实测（T7-1 / F-803） |

**2026-10-16 批次增量：零新依赖。** AI 对标优化（Batch 0~7）全部使用标准库与既有依赖实现：


| 能力 | 实现方式 | 为何不引依赖 |
|---|---|---|
| 跨平台子进程编排 | `scripts/runner.py`，标准库 `subprocess` + `shutil.which` | 逻辑不足 200 行；`concurrently` 之类为 Node 生态，与 uv + pnpm 双包管理无关 |
| 启动自愈| `memory/startup_safety_check.py`，标准库 `sqlite3` | `PRAGMA integrity_check` 是 SQLite 内建能力 |
| prompt 边界声明 | `domain/prompt_guard.py` 纯文本常量 + `json.dumps` | 无需模板引擎；引 Mustache 反而要处理其转义语义 |
| 前端错误码映射 | `schemas/errorCodes.ts` 静态对象 + 三段降级函数 | 一个查表 + 一个函数，引入 i18n 库不划算（本地工具无多语言需求） |

| 能力 | 实现方式 | 为何不引依赖 |
|---|---|---|
| 模型能力元数据 / API 形态 / 上下文窗口档位 | `domain/model_spec.py`，`dataclass(frozen)` + `Final` 静态表 | 纯数据表，第三方校验库只增加转译层（参数定义与校验已于 2026-09-17 随参数编辑区下线） |
| 危险键名防护 | 22 条元组 + 1 个正则 | 标准库 `re` 足够 |
| 配置归一化 | 纯函数 + `json` | 逻辑不足百行，迁移库的规则反而更难对齐 |

**2026-09-17 模型管理迁移增量：零新依赖。** 参数定义、安全校验、归一化全部用标准库与既有依赖实现。

**2026-11-05 内核重构增量：零新依赖。**

| 能力 | 实现方式 | 为何不引依赖 |
|---|---|---|
| 本轮目标锚点 | `domain/agent/anchor.py`，标准库 `re` + `dataclass` | 纯字符串抽取，无需 NLP 库 |
| 六维状态感知 | `domain/agent/sensorium.py`，标准库 `math` / `collections.Counter` | 输入全是会话内已有字段，无需遥测 SDK |
| 交付证据门 | `domain/delivery/gate.py`，纯判定函数 | 三态规则数十行，引规则引擎属过度设计 |
| 外环监督三态 | `domain/hooks/`，沿用既有 `asyncio.wait_for` 隔离模式 | 无需新的 hook 框架 |
| 缓存命中观测 | 读 `usage.prompt_tokens_details.cached_tokens` | SDK 已返回，无需自行计算或估算 |

**候选签名的外部依赖**：universal-ctags 6.1.0 支持 `--fields=+{signature}`（实测可用），
给出函数参数列表作为排序的判别性上下文。**老版 ctags 不认该字段会直接失败** → harness 侧捕获后
去掉该字段重试一次（降级为「候选不带签名」，即改造前行为），不引入任何新依赖。

**缓存观测的范围限制**：仅 OpenAI 兼容端点返回 `prompt_tokens_details.cached_tokens`；
Anthropic / Gemini 原生适配器不返回该字段，此时记 `None`——**不虚报 0**（0 与「无缓存」含义不同）。

**本次不做前缀缓存分层**：本项目的 `chat_structured` 是**独立单轮调用**，只有 system + user 两条消息——
system 本身已稳定、天然命中，user 每次都变、无法缓存。参照实现（天枢 99.3% 命中）依赖「多轮工具循环
每轮重发完整对话历史」，本项目无此形态，做 frozen/delta 分层只增复杂度、无收益。


## 6.3 外部工具（系统级依赖）

> **Windows shell约定（2026-10-16 确立）**：项目在 Windows + PowerShell 环境开发，
> 且 `uv` 与 `pnpm` 双包管理并存。两个已知陷阱与对策：
>
> | 陷阱 | 后果 | 对策 |
> |---|---|---|
> | `.npmrc` 设 `script-shell=pwsh.exe` | pwsh 把 `--format cjs,esm` 的逗号参数拆成数组，esbuild 报 `Invalid value "cjs esm"` | **保持 Windows 默认 cmd.exe** |
> | 直接 spawn `.cmd` 文件 | Windows 无法直接执行批处理 | 经 `ComSpec /d /s /c` 包装；`.exe`（uv/python/node）直接执行即可 |
>
> 平台差异集中在 `scripts/runner.py::get_runner_spec` 一个纯函数（`ComSpec||COMSPEC` 双写兜底、
> `/d`禁AutoRun、`/s` 修正引号剥离、`shell=False` 显式声明），其余代码零平台分支。
> 借鉴 prompt-optimizer `scripts/pnpm-runner.js`——该仓库实测踩过上述第一个坑。

| 工具 | 用途 | 备注 |
|---|---|---|
| ripgrep (`rg`) | 全文检索 | 必需 |
| universal-ctags | 符号抽取 | 必需 |
| Node.js | 前端构建 | `^20.19`、`^22.12` 或 `^24`（2026-10-04 实测 v24.14.0 兼容 Vite 7 engines `^20.19 \|\| >=22.12`；CI 固定 22） |
| pnpm | 包管理 | `^10.15` |
| git | L2 项目记忆 | 必需 |

## 6.4 关键版本约束汇总

| 约束 | 原因 |
|---|---|
| Python 不上 3.14+ | `openai-agents` 依赖链兼容性验证不充分 |
| FastAPI 必须锁版本 | 0.x 版本会重命名内部 helper |
| openai-agents 锁 `>=0.23.1,<1.0` | 尚未发布 1.0；0.x 阶段 minor 可能含破坏性变更，必须用 lockfile 锁具体版本（MUST-24b） |
| SQLite 用 WAL + busy_timeout | 多请求跨进程并发写（MUST-11）需要行级等待与 CAS 兜底 |
| React 19.3 而非更低版本 | 需 `use()` 与 `useOptimistic` |
| 生产界面不引入 Tailwind | 已决定生产用 CSS + CSS Variables；Shadcn/ui 依赖 Tailwind 接管全局样式。样张页（`src/lab`）为限定例外，见 §1.4 |

---

# 七、被明确排除的技术及理由

| 技术 | 排除理由 |
|---|---|
| Webpack | Vite 7 在冷启动、HMR、生产构建上均无劣势，配置复杂度更低 |
| Tailwind CSS（生产界面） | UI 元素仅约 17 个，工具类无收益；且是放弃 Shadcn/ui 的连带原因。样张页例外见 §1.4 |
| Redux Toolkit | 无复杂跨组件状态，三层结构是纯开销 |
| React Query | 请求时序可预测，SSE 需自管连接，缓存策略收益为零 |
| TanStack Router | 仅 3 个页面，React Router 足够 |
| Ant Design / MUI | 设计语言冲突，体积庞大 |
| pnpm 之外的包管理器 | 见 §1.3 |
| ORM + 迁移框架 | 两张表用原生 SQL，迁移框架属过早优化 |
| PostgreSQL | 单用户本地场景能力冗余；多用户态确认后经 `SessionStore` Protocol 评估 |
| MySQL | 同上（2026-10-07 回改 SQLite 定稿；`SessionStore` Protocol 保留多后端切换路径） |
| 向量数据库 | 检索目标是精确代码位置，向量相似度无优势 |
| Server Components | 本地工具需访问文件系统，无 SEO 需求 |
| CSS-in-JS | 无收益且引入运行时开销 |

---

# 八、与 Qoder Quest 的技术对比

作为参考，Qoder Quest（阿里）在技术选择上的公开信息：

| 维度 | Qoder Quest | DevPrompt AI | 差异原因 |
|---|---|---|---|
| 工具策略 | 主张「Bash 是终极工具，能用 Bash 就不建新工具」 | ripgrep + ctags 专用封装 | 本项目需要在 32k 预算下做精确压缩，通用 Bash 不够用 |
| 上下文管理 | 模型自主决定压缩时机（Agentic Context Management） | 确定性状态机 + 压缩发生在阶段边界 | 借鉴其思想，但本项目流程固定为四阶段，不需要模型判断压缩时机 |
| 动态提醒 | Reminder 机制动态注入上下文 | L2 项目记忆在阶段三注入 | 目标一致，机制不同 |
| SDK 形态 | 闭源，云端推理 | 私有代码库不上云 | 定位根本差异，不可调和 |
