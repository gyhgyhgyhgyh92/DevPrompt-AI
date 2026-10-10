# 阶段二 · 工程基线与环境准备 Spec

> change-id: `establish-phase2-baseline`
> 上游依据：`doc-阶段/2026-10-04-阶段二-工程基线与环境准备-实施计划.md`（唯一执行真源）
> 执行优先级：`AGENTS.md`（宪法）> 实施计划 > 本 spec

## Why

项目目前仅有文档体系，无可提交代码的工程载体。按实施真源文档 §3，必须先建立后端包结构、质量工具链、前端脚手架与 CI 门禁骨架，阶段三（W1 检索层）才有物理容器与质量防线。本 spec 将阶段二的六个子阶段（2A~2F）转化为可验证的需求规格。

## What Changes

- 新增后端 Python 包骨架：`src/devprompt_ai/`（src 布局，按架构文档 §4.8 权威目录树，33 个命名模块空占位 + 各级 `__init__.py`）
- 新增 `pyproject.toml`（uv 管理，依赖版本区间按技术栈 §6.2，含 jev/postgres/dev 三个可选组）与 `uv.lock`
- 新增 `.gitignore`（严格按架构文档 §2.5 清单）与 `.env.example`（严格按 F-003 键集）
- 新增 Python 质量工具链配置：Ruff（`line-length=100`，规则组 E/W/F/I/N/UP/B/SIM/ASYNC）、mypy（`strict=true`）、pytest + pytest-asyncio
- 新增 `frontend/` 脚手架：Vite 7 + React 19.3 + TS 5.9（Project References）+ pnpm 10 + ESLint 9 flat config + prettier + Vitest + 契约脚本位（`gen:contract`/`check:contract`）
- 新增 `scripts/check_architecture.py`（架构约束静态检查：domain 依赖方向 / service 反向依赖 / SQL 越界 / 前端阈值常量 / 组件命名）与 `.github/workflows/ci.yml`（MUST-29 六项门禁，契约冒烟条件启用）
- 新增冒烟测试：`tests/test_smoke.py`（后端，TDD 先红后绿）与 `frontend/src/smoke.test.ts`（前端）
- 更新 `DevPrompt-AI-实施真源文档.md`：阶段二状态行 ⬜→✅、§13 变更记录追加
- **边界锁定（BREAKING 性质约束，违反即任务失败）**：
  - 不实现任何业务逻辑（`config.py`/`main.py`/`service.py`/`state.py` 等均为空占位）
  - 不引入 Zustand/React Router/Zod/组件库/Tailwind（阶段六才加装）
  - 不启动阶段三（W1 检索层）及后续阶段任何任务
  - 不新增技术栈文档未登记的依赖（宪法 MUST-04）

## Impact

- Affected specs：无既有 spec（本仓库首个 change）
- Affected code：
  - 新增：`.gitignore`、`pyproject.toml`、`uv.lock`、`.env.example`、`src/devprompt_ai/**`（空占位）、`tests/test_smoke.py`、`frontend/**`、`scripts/check_architecture.py`、`.github/workflows/ci.yml`
  - 修改：`DevPrompt-AI-实施真源文档.md`（仅状态行与变更记录，不动门禁数值与任务清单）
- 宪法冲突处理：实施过程中若发现实施计划与 `AGENTS.md` 冲突，以宪法为准，记录冲突点并暂停上报（用户执行约束 3）

## ADDED Requirements

### Requirement: 环境预检（2A）

执行体 SHALL 在实施开始前验证 7 项系统级工具（python、uv、rg、ctags、git、node、pnpm）版本满足技术栈 §6.3/§6.4 约束，并留痕「环境就绪清单」。

#### Scenario: 全部工具就绪
- **WHEN** 7 条版本命令（`python --version` 等）全部有输出且版本在约束区间内
- **THEN** 就绪清单记录 7 行（工具/版本/约束/结论）且全部 ✅，允许进入 2B/2D

#### Scenario: 工具缺失或版本不合规
- **WHEN** 任一命令无输出，或版本越界（Python 3.14+、Node 18、ctags 非 Universal Ctags 等）
- **THEN** 停止后续子阶段，上报缺失项与建议安装命令（winget/corepack/官方安装器），待用户授权后复检

### Requirement: 后端包结构与依赖基线（2B）

执行体 SHALL 建立 git 仓库基线与可安装可导入的后端 Python 包，目录树与架构文档 §4.8 逐文件一致，依赖经 uv 锁定。

#### Scenario: 冒烟测试先红后绿
- **WHEN** 依赖安装（`uv sync --no-install-project --extra dev`）后运行 `uv run pytest tests/test_smoke.py -v`，包尚未创建
- **THEN** 测试失败（ModuleNotFoundError）；创建 §4.8 骨架并 `uv sync --extra dev` 后复跑为 `1 passed`

#### Scenario: 目录树权威一致
- **WHEN** 骨架创建完成并逐文件比对 §4.8
- **THEN** 33 个命名模块零缺失、零多余；`interfaces/` 及各子包含打包必要的 `__init__.py`

#### Scenario: 敏感与私有文件被忽略
- **WHEN** 执行 `git check-ignore .env .devprompt-ai/`
- **THEN** 两者均被忽略；提交内容不含 MUST-23 违禁项；`uv.lock` 与 `.env.example` 已提交

### Requirement: Python 质量工具链（2C）

执行体 SHALL 在 `pyproject.toml` 配置 Ruff/mypy/pytest，使四项质量命令在空包上零错误，并证明 ASYNC 规则组真实生效。

#### Scenario: 四项绿灯
- **WHEN** 运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy`、`uv run pytest -v`
- **THEN** 四条命令退出码全部为 0

#### Scenario: 规则组生效性探针
- **WHEN** 向 `common/process.py` 临时注入违规代码（同步 subprocess + 未使用导入）并运行 `uv run ruff check .`
- **THEN** 退出码非 0（规则命中）；还原空文件后复跑恢复 0 错误

#### Scenario: 配置完备
- **WHEN** 读 `pyproject.toml` 的 `[tool.ruff.lint] select`
- **THEN** 九组规则齐全且含 `ASYNC`；mypy `strict = true` 生效

### Requirement: 前端脚手架（2D）

执行体 SHALL 建立 Vite 7 + React 19.3 + TS 5.9 前端工程，四项质量脚本全绿，契约脚本位冻结。

#### Scenario: 依赖可复现安装
- **WHEN** 执行 `pnpm install --frozen-lockfile`
- **THEN** 安装成功且 `pnpm-lock.yaml` 无 diff；依赖版本与 `pnpm add` 时的区间一致（react ^19.3.0、typescript ~5.9.0、vite ^7.3.0 等）

#### Scenario: 四项绿灯
- **WHEN** 运行 `pnpm typecheck`、`pnpm lint`、`pnpm format:check`、`pnpm test`
- **THEN** 四条命令退出码全部为 0（test 显示 1 passed）

#### Scenario: 排除清单合规
- **WHEN** 读 `frontend/package.json` 依赖
- **THEN** 不含 Tailwind/组件库/Redux/React Query/Zustand/React Router/Zod；`gen:contract` 与 `check:contract` 脚本存在但本阶段不运行（`../openapi.json` 由阶段六产出）

#### Scenario: TS 严格度
- **WHEN** 读 `tsconfig.app.json`
- **THEN** `strict` 与 `noUncheckedIndexedAccess` 同时开启；App.tsx 文件名与主导出名一致

### Requirement: CI 门禁骨架与架构约束检查（2E）

执行体 SHALL 交付架构约束静态检查脚本与 CI 工作流，覆盖 MUST-29 六项门禁，并以违规注入自测证明拦截能力。

#### Scenario: 空仓库检查通过
- **WHEN** 运行 `uv run python scripts/check_architecture.py`
- **THEN** 输出「架构约束检查通过。」且退出码 0；`uv run mypy` 对 scripts/ 零错误（需先扩容 mypy files 至 `["src","tests","scripts"]`）

#### Scenario: 违规注入自测
- **WHEN** 向 `domain/retrieval/symbols.py` 临时注入 `import devprompt_ai.harness.runner` 并运行检查脚本
- **THEN** 退出码 1 且输出违规定位；还原后复跑退出码 0

#### Scenario: MUST-29 覆盖度
- **WHEN** 对照宪法六项清单读 `.github/workflows/ci.yml`
- **THEN** Ruff Lint+Format / mypy / pytest / 前端 tsc+ESLint / 架构约束 / 契约冒烟六项均有对应 job-step；契约冒烟以 `hashFiles('openapi.json') != ''` 条件守卫（阶段六前自动跳过，属已声明边界）；无 `--no-verify`/`continue-on-error` 放行违规

#### Scenario: 本地等效验证
- **WHEN** 无 GitHub 远端时执行 CI 各 job 命令的本地等效序列
- **THEN** 后端四命令 + 前端四脚本 + 架构检查全部退出码 0

### Requirement: 出口验收与移交（2F）

执行体 SHALL 执行架构文档 §D 自检第 1–4 项与九条质量命令汇总复检，更新真源文档状态，形成阶段三开工许可。

#### Scenario: 出口门禁全过
- **WHEN** 执行 §D 第 1–4 项（python 版本 / `uv sync --frozen --extra dev` / rg / ctags）与九条命令汇总
- **THEN** 全部通过并留验收记录（含 2E 注入自测证据）

#### Scenario: 真源状态同步
- **WHEN** 门禁全过后更新 `DevPrompt-AI-实施真源文档.md`
- **THEN** §1 总览表阶段二状态行改为 ✅（含指向本实施计划的标注）、§13 变更记录追加一行、本计划 0.4 进度表六格更新为 ✅

#### Scenario: 失败即冻结
- **WHEN** 任一门禁项不通过
- **THEN** 冻结移交，按 SHOULD-03 上报（失败项/错误信息/推测原因/建议处置），不得带病放行

## MODIFIED Requirements

（无——本 change 不修改任何既有功能需求）

## REMOVED Requirements

（无）
