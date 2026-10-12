# 阶段六 W4 全栈 Web 与记忆完善 Spec

> 权威依据：`doc-阶段/2026-10-12-阶段六-W4全栈Web与记忆完善-实施计划.md` v1.0（子阶段 6A~6G）
> 真源任务：T6-1~T6-11 · UI 设计真源：`doc-阶段/2026-10-12-阶段六-前端UI原型与设置中心设计.md`
> 本 spec 是实施计划的执行化增量描述；**与实施计划冲突时以实施计划为准**，与宪法冲突时以宪法为准并暂停上报。

## Why

阶段五（W3）已收口（257 测试全绿，MUST-25 生死线经「方案甲」裁决授权继续），但产品仍无 Web 前端（`frontend/` 不存在）、契约缺 `/settings` 端点、`PUT /preference` 与 `GET /history` 仍为 501/9004。W4 出口门禁（Web 全栈可用 + 记忆三层生效 + 设置中心可用）无法达成，需按实施计划交付全栈 Web 与记忆完善。

## What Changes

- **6A 后端补全**：新增 `GET+PUT /settings`（契约 10 路径/12 操作）；`PUT /preference` 与 `GET /history` 从 501/9004 转正；十固定事件接线（MUST-04 裁决：标准库 logging 替代计划中的 structlog）；openapi 导出管线；**BREAKING**——MUST-19 宪法措辞修订为「环境变量优先；密钥不入库、不进日志」（批准记录：真源 §13 2026-10-12），`AppConfig` 加载链 env > settings 文件
- **6B 前端工程基座**：Vite + React 19.3 + TS 5.9 脚手架（技术栈 §6.1，禁 Tailwind/组件库/Redux/React Query）；§5.1 目录树逐目录建立；`tokens.css` 设计 token；check:contract 契约管线
- **6C 状态管理与 API 层**：api 五文件 + 三 store（useOptimizeStore/usePreferenceStore/useSettingsStore）+ useSSE（close 写 effect cleanup）+ 全响应 Zod 校验
- **6D 三页面与工作台布局**：`/` OptimizePage 三栏工作台（会话侧栏/流程线程/上下文面板）+ `/history` + `/preference` + AppShell（含 ⚙ 设置入口）
- **6E 核心组件与流程联调**：PromptCard/RecommendBadge/FollowupForm/ScoreDetail/ConfidenceNotice 等 + mock e2e 六路径 + T6-7 前端零阈值检查
- **6F 设置中心 UI**：SettingsModal 四标签页（模型服务/通用外观/长期记忆/流程与安全）
- **6G 记忆注入与出口验收**：三层记忆逐层关闭验证 + T6-10 四文档组件清单一致 + W4 出口门禁六项

## Impact

- Affected specs: F-601~F-604（HTTP/界面/反馈/设置中心）、F-701~F-707（前端工程/页面/组件/HTTP/契约/状态/边界）、F-501/F-504（记忆注入）、F-005（可观测性）
- Affected code: `src/devprompt_ai/interfaces/api/`（routes/schemas）、`config.py`、`memory/`（settings 持久化）、`scripts/export-openapi.py`（新增）、`frontend/`（全新）、`AGENTS.md`（MUST-19 修订）

## ADDED Requirements

### Requirement: 设置端点 GET+PUT /settings

系统 SHALL 提供设置读写端点（统一前缀 `/api/v1`，薄壳零业务逻辑 MUST-10）：模型服务配置（base_url、api_key、model_id、decider、timeout、temperature、max_tokens）写本地设置文件（0600 权限）；流程参数（followup_soft_round_guard、followup_cost_budget、telemetry）写 SQLite。候选集上限 25 为宪法常量不入 settings，仅锁定项只读下发。

#### Scenario: 保存并回读模型配置

- **WHEN** `PUT /settings` 提交含 api_key 的模型服务配置，随后 `GET /settings`
- **THEN** 密钥落本地设置文件（SQLite 与日志中无密钥），GET 回显恒脱敏 `sk-••••` + 尾 4 位

#### Scenario: 契约冒烟

- **WHEN** 契约冒烟测试对 12 个操作（10 路径）逐一调用
- **THEN** 全部独立可调；openapi 两次导出 diff 为零

### Requirement: 设置中心 UI（四标签页）

前端 SHALL 提供 SettingsModal（标题栏 ⚙ 入口，模态 + 左侧四项导航）：模型服务（供应商/脱敏密钥/测试连接）、通用外观（主题三态/语言/字体/行为开关，localStorage `devprompt:v1:` 前缀 + Zod 校验）、长期记忆（L3 滑条/采纳历史/导出/清空）、流程与安全（护栏参数/候选上限 25 锁定只读/遥测/清除数据）。

#### Scenario: 锁定项不可编辑

- **WHEN** 打开流程与安全标签页
- **THEN** 候选集上限项 disabled 且标注「宪法 MUST-09 锁定」，值恒 25

#### Scenario: 主题即时生效

- **WHEN** 切换主题三态并刷新页面
- **THEN** `data-theme` 立即生效且刷新后保持（localStorage 持久化）

### Requirement: 前端工程基座

系统 SHALL 提供 Vite + React 19.3 + TS 5.9 工程（依赖与技术栈 §6.1 完全一致，lockfile 提交 MUST-24）：§5.1 目录树（含 components/settings 组、useSettingsStore、schemas/settings.ts）逐目录建立、tokens.css 全 CSS Variables、check:contract 管线（openapi-typescript 自动生成 + git diff --exit-code 阻断漏更）。

#### Scenario: 工程门禁

- **WHEN** 运行 pnpm build / tsc / eslint / vitest / check:contract
- **THEN** 五个脚本退出码全 0，目录树与 §5.1 diff 为零

### Requirement: 状态管理与 API 层

系统 SHALL 提供 api 五文件 + 三 store + useSSE：统一信封解包（code=0 取 data）、request_id 透传、SSE 消息在 store 内处理（MUST-16）、断流不自动重连（MUST-15）、畸形响应被 Zod 拒绝且不重试、恢复路径走 `GET /result/{flow_id}`（服务端权威）。

#### Scenario: SSE 生命周期

- **WHEN** 组件 unmount
- **THEN** EventSource `close()` 在 effect cleanup 中执行（单测断言通过）

### Requirement: 三页面与工作台布局

系统 SHALL 提供三路由页面 + OptimizePage 三栏工作台（会话侧栏/对话式流程线程/上下文面板，按 UI 设计文档 §1.1）：状态机步进器仅镜像后端 9 态（MUST-07 只渲染不判定）、上下文面板只读渲染目标定位/取证事实/L3 向量、刷新后流程状态经 `GET /result` 恢复不丢失。

#### Scenario: 刷新恢复

- **WHEN** 流程进行中刷新 `/` 页面
- **THEN** 服务端权威恢复流程状态，三套方案与评分内容一致

### Requirement: 核心交互组件与职责边界

系统 SHALL 提供五核心组件（PromptCard/RecommendBadge/FollowupForm/ScoreDetail/ConfidenceNotice）+ optimize 组其余组件：推荐徽章仅 `marked=true` 时渲染、不标记时展示后端 reason 文案不静默（MUST-27）、澄清卡四要素（key/reason/best_guess/输入）+ 逃生常驻 + 软护栏裁决面板（MUST-26）。前端零阈值常量零判定分支（MUST-08）。

#### Scenario: 逃生路径

- **WHEN** ASKING 态点击「直接生成」
- **THEN** 经 `POST /followup/{flow_id}` escape 模式提交，单套 A 无 ranking，埋点 followup.escaped

### Requirement: 记忆三层逐层关闭验证

系统 SHALL 在测试中分别以空 L1 / 空 L2 / 中性 L3 注入，断言流程完成且行为符合该层缺失时的预期（L3 中性 → 推荐仍由后端判定不异常；行为退化非缺陷，流程失败才判 FAIL）。

#### Scenario: 逐层关闭

- **WHEN** 分别关闭 L1/L2/L3 后执行完整流程
- **THEN** 流程均完成，各层缺失的预期行为可观测（如 L1 关闭→反问可能重复问已知项）

## MODIFIED Requirements

### Requirement: PUT /preference（501 转正）

原 501/9004 端点 SHALL 转正为真实写入：接 `preference_store.save`，向量 clip01 校验，PUT 后 GET 返回更新值，超界值被 clip。**理由**：阶段五 6.4 维持 501 遗留，转正归 6A 以便契约一次冻结。

### Requirement: GET /history（501 转正）

原 501/9004 端点 SHALL 转正为 session store list（脱敏：仅 id/时间/state/项目名，不返回原句明文 MUST-19）。若 list 需新增 SQL 表结构变更 → 触发 D-6A-1 暂停上报。

### Requirement: MUST-19 密钥来源（宪法措辞修订，已获批）

宪法 MUST-19「只从环境变量读取」SHALL 修订为「**环境变量优先；密钥不入库、不进日志**」，`AppConfig` 加载链为 **env > 本地设置文件**（settings.json，0600）。批准记录：真源 §13 2026-10-12；修订随 6A 提交并同步三份配套文档（附则要求）。
