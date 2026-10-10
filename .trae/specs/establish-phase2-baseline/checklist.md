# Checklist · establish-phase2-baseline

> 逐项对应 spec.md 的 ADDED Requirements 与实施计划各子阶段验收表。全部勾选后方可视为阶段二完成。
> 勾选时间：2026-10-04。标注 ✅✅ 的项为主流程亲自复验（非仅采信子代理报告）。

## 2A 环境预检

- [x] 7 条版本命令（python/uv/rg/ctags/git/node/pnpm）全部有输出且退出码 0 ✅✅（主流程直测）
- [x] 版本满足技术栈 §6.3/§6.4 约束（Python ≥3.10 非 3.14+、git ≥2.30、Node ^20.19/^22.12 非 18、pnpm ^10.15）✅✅（Node 经用户批准扩展至 ^24，两文档已同步；CI 固定 22）
- [x] `ctags --version` 输出含 "Universal Ctags"（非 Exuberant）✅✅（Universal Ctags 6.1.0，winget portable 路径已入用户 PATH）
- [x] 环境就绪清单 7 行已留痕（实施计划 §1.5）

## 2B 后端包结构

- [x] `uv sync --extra dev` 成功，`uv.lock` 已生成并提交（2F 复检 `uv sync --frozen` 通过且 lockfile 无变化）
- [x] TDD 留痕：冒烟测试先红（ModuleNotFoundError）后绿（1 passed）
- [x] 目录树与架构文档 §4.8 逐文件一致：52 个命名模块零缺失、零多余，各级 `__init__.py` 齐全（含用户并发新增的 memory/session_store.py；实施计划原写「33 个」系计数错误，已在 tasks.md 记录更正）
- [x] 根 `__init__.py` 文档字符串含 "DevPrompt AI"；其余占位模块为空文件（无任何业务实现）
- [x] `.gitignore` 与 §2.5 清单一致；`git check-ignore .env .devprompt-ai/` 均命中 ✅✅（另补 *.tsbuildinfo）
- [x] `.env.example` 键集与 F-003 一致（含 JEV_MODEL_ID=jev-1.13.0，权重和 0.6+0.4）✅✅
- [x] 提交信息符合 MUST-21：`build(config): 初始化后端包结构与依赖基线` + body 写为什么（42581ec）

## 2C Python 工具链

- [x] `pyproject.toml` 含 `[tool.ruff]`（line-length=100）/ `[tool.ruff.lint]`（select=E,W,F,I,N,UP,B,SIM,ASYNC）/ `[tool.mypy]`（strict=true）/ `[tool.pytest.ini_options]`
- [x] `uv run ruff check .` 退出码 0
- [x] `uv run ruff format --check .` 退出码 0（69 files）
- [x] `uv run mypy` 退出码 0（strict 生效，69 source files）
- [x] `uv run pytest -v` 退出码 0 ✅✅（主流程复跑 1 passed）
- [x] ASYNC 探针：注入违规后 ruff 非零退出，还原空文件后归零（证据留存；计划原探针含 `# noqa` 压制了 F401，修正探针后 F401+ASYNC 规则均命中——偏差已记录）
- [x] 提交信息：`build(config): 配置 Python 质量工具链`（80e70cf）

## 2D 前端脚手架

- [x] `pnpm install --frozen-lockfile` 成功且 lockfile 无 diff
- [x] 依赖版本符合技术栈 §6.1（react ^19.3.0、typescript ~5.9.3、vite ^7.3.6、@vitejs/plugin-react ^5.2.0、eslint ^9.39、prettier ^3.9）✅✅
- [x] `pnpm typecheck` / `pnpm lint` / `pnpm format:check` / `pnpm test` 四条退出码全 0（test 1 passed）
- [x] `tsconfig.app.json` 同时开启 `strict` 与 `noUncheckedIndexedAccess` ✅✅
- [x] `package.json` scripts 含 `gen:contract` 与 `check:contract`（本阶段不运行）✅✅
- [x] 依赖排除清单合规：无 Tailwind/组件库/Redux Toolkit/React Query/Zustand/React Router/Zod ✅✅（补装 @types/react、@types/react-dom 系计划遗漏的类型声明包，已记录）
- [x] `App.tsx` 文件名与主导出名一致（§5.3）
- [x] `pnpm-lock.yaml` 已提交；提交信息：`build(web): 初始化前端脚手架`（14b8ce4）

## 2E CI 门禁骨架

- [x] `scripts/check_architecture.py` 存在，含五类检查（domain import / service 反向 / SQL 越界 / 前端阈值 / 组件命名），全函数类型注解完整（721d86e，131 行）
- [x] mypy `files` 已扩容为 `["src","tests","scripts"]` 且 `uv run mypy` 零错误
- [x] 空仓库运行检查脚本：输出「架构约束检查通过。」退出码 0 ✅✅（主流程复跑 exit 0）
- [x] 注入自测：`import devprompt_ai.harness.runner` 注入后退出码 1 且输出违规定位；还原后退出码 0（证据留存）
- [x] `.github/workflows/ci.yml` 覆盖 MUST-29 六项：Ruff Lint+Format / mypy / pytest / 前端 tsc+ESLint / 架构约束 / 契约冒烟 ✅✅
- [x] 契约冒烟以 `hashFiles('openapi.json') != ''` 条件守卫（阶段六前自动跳过）✅✅
- [x] ci.yml 无 `--no-verify`、无 `continue-on-error` 放行违规 ✅✅（grep 零命中）
- [x] 本地等效验证：后端四命令 + 前端四脚本 + 架构检查全部退出码 0（九条全绿）
- [x] 提交信息：`ci: 搭建 MUST-29 门禁骨架与架构约束检查`（721d86e）

## 2F 出口验收与移交

- [x] §D 第 1–4 项通过（python 3.13.14 / `uv sync --frozen --extra dev` 成功且 lockfile 无变化 / rg 15.0.0 / Universal Ctags 6.1.0——当前 shell 需完整路径或新开终端）
- [x] 九条质量命令汇总复检全绿且输出摘要已记录
- [x] `DevPrompt-AI-实施真源文档.md` §1 阶段二状态行已更新为 ✅（含指向实施计划的标注）✅✅
- [x] 实施真源文档 §13 变更记录已追加一行
- [x] 实施计划 0.4 进度追踪表六格已更新为 ✅ ✅✅
- [x] 移交清单完整：验收记录 + 人工待办（远端仓库/CI 首跑/分支保护）+ 阶段三开工许可（见最终交付报告）
- [x] 提交信息：`docs: 阶段二出口验收通过并更新真源状态`（80fd6bd）
- [x] 边界锁定复核：`src/devprompt_ai/` 内除根 `__init__.py` 文档字符串与工具链配置外无任何业务代码；未引入未登记依赖（aiomysql/PyMySQL 已由用户登记进技术栈 §6.2；@types/* 为类型声明包已记录）；未触碰阶段三任务

## 全局合规

- [x] 全部提交符合 MUST-21 格式且 body 写明为什么（6 个提交逐一核验）✅✅
- [x] 无 MUST-23 违禁内容入库（.env/node_modules/dist/*.db/.logs/.devprompt-ai/*.tsbuildinfo 均被忽略）✅✅
- [x] 未使用 `--no-verify`；未手动调整格式（MUST-18）
- [x] 实施过程中如发现计划与宪法冲突：已记录冲突点并暂停上报（记录项：技术栈 §4.5/§6.2 仍写 `openai-agents ^1.0`，与宪法 MUST-24b（PyPI 实际 0.23.1，无 1.0）冲突；pyproject 已按宪法采用 `>=0.23.1,<1.0` 并经 uv sync 验证，文档修订待用户批准——见最终报告「待用户处理」）
