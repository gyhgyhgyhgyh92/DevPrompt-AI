# Tasks · establish-phase2-baseline

> 严格限定在阶段二范围内（T2-1~T2-5）。每个任务收口 = 验收绿灯 + 一次 git 提交。
> 步骤细节（完整文件内容与命令）以 `doc-阶段/2026-10-04-阶段二-工程基线与环境准备-实施计划.md` 为唯一执行依据，本列表不复制代码。

- [x] Task 1: 子阶段 2A · 环境预检与工具验证（T2-5 前半）
  - [x] SubTask 1.1: 逐条执行 7 条版本检查命令（python/uv/rg/ctags/git/node/pnpm），记录版本
  - [x] SubTask 1.2: 缺失工具安装（需用户授权；winget/corepack/官方安装器），复检通过
  - [x] SubTask 1.3: 产出环境就绪清单（7 行，留痕于实施计划 1.4 节记录区）
  - 验收：7 项全 ✅；无 Python 3.14+/Node 18/非 Universal Ctags；ctags 输出含 "Universal Ctags"
  - 执行记录：ctags 初检缺失→经用户授权发现已有 winget portable 安装（Universal Ctags 6.1.0）并补用户 PATH 后复检通过；Node v24.14.0 经用户批准扩展约束（技术栈 §6.3 与架构文档 §1.1 已同步更新，CI 固定 22）；就绪清单留痕于实施计划 §1.5

- [x] Task 2: 子阶段 2B · 后端包结构与依赖基线（T2-1）
  - [x] SubTask 2.1: git 仓库初始化检查（`git rev-parse --is-inside-work-tree`，必要时 `git init`）
  - [x] SubTask 2.2: 创建 `.gitignore`（§2.5 清单原文）
  - [x] SubTask 2.3: 创建 `pyproject.toml`（仅 [project]/[build-system]/[project.scripts]，工具配置留给 Task 3）
  - [x] SubTask 2.4: `uv sync --no-install-project --extra dev` 生成 `.venv` 与 `uv.lock`
  - [x] SubTask 2.5: 写 `tests/test_smoke.py` 并运行确认红灯（ModuleNotFoundError）
  - [x] SubTask 2.6: 按 §4.8 批量创建目录骨架（33 命名模块空占位 + `__init__.py`），根 `__init__.py` 写文档字符串，`uv sync --extra dev` 后冒烟转绿（1 passed）
  - [x] SubTask 2.7: 创建 `.env.example`（F-003 键集 + §1.6 默认值，JEV_MODEL_ID=jev-1.13.0）
  - [x] SubTask 2.8: 提交 `build(config): 初始化后端包结构与依赖基线`（含 uv.lock/.env.example）
  - 验收：冒烟绿；目录树与 §4.8 逐文件一致；`git check-ignore .env .devprompt-ai/` 均命中
  - 执行记录：提交 `42581ec`。偏差 3 项（均与用户并发修订的文档对齐）：① 版本区间按宪法 MUST-24b 修正为 `openai-agents>=0.23.1,<1.0`、`typesafe-sdk>=0.7.2,<1.0`（PyPI 无 1.0，原区间致 uv 解析失败）；② 架构文档 §4.8 新增 `memory/session_store.py`（L1 改 MySQLSession），已补建，命名模块总数 52（原计划写 33 系主流程计数错误）；③ 依赖增补 aiomysql/PyMySQL、移除 postgres 组（技术栈 §6.2 已登记，L1/L3 改 MySQL）

- [x] Task 3: 子阶段 2C · Python 质量工具链（T2-2）
  - [x] SubTask 3.1: 向 `pyproject.toml` 追加 `[tool.ruff]`（line-length=100，select 九组含 ASYNC）/`[tool.mypy]`（strict，files=["src","tests"]）/`[tool.pytest.ini_options]`
  - [x] SubTask 3.2: 四项绿灯验证（ruff check / ruff format . 后 --check / mypy / pytest）
  - [x] SubTask 3.3: ASYNC 生效性探针：向 `common/process.py` 注入违规→ruff 非零→还原→归零
  - [x] SubTask 3.4: 提交 `build(config): 配置 Python 质量工具链`
  - 验收：四命令退出码全 0；探针红绿证据；select 九组齐全
  - 执行记录：提交 `80e70cf`。偏差 2 项：① 计划探针代码含 `# noqa` 注释压制了 F401 致初探未变红，修正探针（去 noqa）后 F401+ASYNC 规则均命中（exit 1），还原后归零——意图（证明规则组生效）达成；② Ruff 0.16 默认格式化 Markdown 内嵌代码块，首跑改写范围外文档示例，已还原并在 `[tool.ruff]` 追加 `extend-exclude=["*.md"]`（否则 format --check 持续红且殃及文档）；venv 实际 CPython 3.12.13（满足 ≥3.10）

- [x] Task 4: 子阶段 2D · 前端脚手架（T2-3）【与 Task 2/3 并行，最迟在 Task 5 前完成】
  - [x] SubTask 4.1: 创建 `frontend/package.json`（name/scripts/type:module/packageManager: pnpm@10.15.0，无依赖字段）
  - [x] SubTask 4.2: `pnpm add react@^19.3.0 react-dom@^19.3.0` 与 dev 依赖（typescript@~5.9.0/vite@^7.3.0/@vitejs/plugin-react@^5.1.0/eslint@^9/@eslint/js@^9/typescript-eslint@^8/prettier@^3/vitest@latest/openapi-typescript@latest），`pnpm install --frozen-lockfile` 验证
  - [x] SubTask 4.3: 创建 6 个配置文件（tsconfig.json/tsconfig.app.json/tsconfig.node.json/vite.config.ts/eslint.config.js/.prettierrc + .prettierignore）
  - [x] SubTask 4.4: 创建 4 个入口文件（index.html/src/main.tsx/src/App.tsx/src/smoke.test.ts）
  - [x] SubTask 4.5: 四项绿灯（typecheck/lint/format 后 format:check/test）
  - [x] SubTask 4.6: 提交 `build(web): 初始化前端脚手架`（含 pnpm-lock.yaml）
  - 验收：--frozen-lockfile 成功；四脚本全绿；package.json 无 Tailwind/组件库/Redux/React Query/Zustand；契约脚本位存在
  - 执行记录：提交 `14b8ce4`（由主流程统一提交，避免与后端线 git 并发竞争）。偏差 2 项：① 补装 `@types/react`/`@types/react-dom`（计划清单遗漏，React 19.3 无内置类型，typecheck 6 处 TS7016/TS7026）；② vitest 实际解析为 ^5.0.3、openapi-typescript ^7.13.0（latest 区间内）；tsc -b 产生的 *.tsbuildinfo 已由主流程补入 .gitignore（chore 提交）

- [x] Task 5: 子阶段 2E · CI 门禁骨架与架构约束检查（T2-4）【依赖 Task 3 + Task 4 合拢】
  - [x] SubTask 5.1: 创建 `scripts/check_architecture.py`（五类检查：domain import / service 反向 / SQL 越界 / 前端阈值 / 组件命名；类型注解完整）
  - [x] SubTask 5.2: Edit `pyproject.toml` 将 mypy `files` 扩容为 `["src","tests","scripts"]`，`uv run mypy` 复验零错误
  - [x] SubTask 5.3: 空仓库绿灯（检查脚本退出码 0）
  - [x] SubTask 5.4: 注入自测：向 `domain/retrieval/symbols.py` 注入 `import devprompt_ai.harness.runner` → 脚本退出码 1 且定位违规 → 还原 → 退出码 0
  - [x] SubTask 5.5: 创建 `.github/workflows/ci.yml`（backend/frontend/architecture 三 job，MUST-29 六项，契约冒烟以 hashFiles 条件守卫）
  - [x] SubTask 5.6: 本地等效验证 CI 全部命令（后端四 + 前端四 + 架构检查全绿）
  - [x] SubTask 5.7: 提交 `ci: 搭建 MUST-29 门禁骨架与架构约束检查`
  - 验收：注入红/还原绿证据留存；ci.yml 六项全覆盖且无 --no-verify/continue-on-error
  - 执行记录：提交 `721d86e`（3 文件，197 行）。mypy 扩容后 69 源文件零错误、无需修复脚本；注入自测三段证据完整（定位输出 `import 'devprompt_ai.harness.runner'` + 退出码 1 → 还原后 0 → ruff 无残留）；九条命令全绿。偏差：无，脚本与 ci.yml 逐字落地。

- [x] Task 6: 子阶段 2F · 出口验收与移交（T2-5 后半 + 真源 §3.4 门禁）【依赖 Task 5】
  - [x] SubTask 6.1: §D 第 1–4 项自检（python 版本 / `uv sync --frozen --extra dev` / rg / ctags）
  - [x] SubTask 6.2: 九条命令汇总复检并记录输出摘要（后端四 + 架构检查 + 前端四 + frozen 安装）
  - [x] SubTask 6.3: 更新实施真源文档（§1 阶段二状态行 ⬜→✅、§13 变更记录追加）与本计划 0.4 进度表（六格 ✅）
  - [x] SubTask 6.4: 提交 `docs: 阶段二出口验收通过并更新真源状态`，向用户移交（验收记录 + 人工待办：远端仓库/CI 首跑/分支保护 + 阶段三开工许可）
  - 验收：§D 1–4 全过；九命令全绿；真源状态已同步；任一失败即冻结上报（SHOULD-03）
  - 执行记录：提交 `80fd6bd`。§D 1–4 全过（ctags 当前 shell 需完整路径验证，已注明）；九命令全绿；真源状态行/变更记录/进度表三处已同步；真源文档与计划文档首次入库（+1635 行）。
  - **用户决策（2026-10-04 追加）**：① 技术栈文档 openai-agents 版本已修订为 `>=0.23.1,<1.0`（§4.5/§6.2/§6.4 三处，与宪法 MUST-24b 及 pyproject 一致，冲突记录关闭）；② **暂不创建远端仓库**——CI 工作流文件已就位但远端首跑、推送、分支保护（MUST-22）整体延后，待用户启动远程托管时一并处理；本地九条命令即为现行门禁。

# Task Dependencies

- Task 1 → Task 2、Task 4（环境就绪是两者的前置）
- Task 2 → Task 3（工具链验证对象是已安装的包）
- Task 4 与 Task 2/3 无依赖，可并行派发
- Task 3 + Task 4 → Task 5（CI 需要两端 lockfile 与绿灯命令）
- Task 5 → Task 6（出口验收复检 CI 全部命令）

# 宪法约束提醒（每任务通用）

- 提交格式 MUST-21：`type(scope): subject`，body 写为什么
- 禁止提交 MUST-23 清单内容；`uv.lock`/`pnpm-lock.yaml`/`.env.example` 必须提交
- 格式化交给工具（MUST-18），禁止手动调空格
- 版本冲突/规则冲突一律停止上报（附则），实施计划与宪法冲突时以宪法为准并记录冲突点
