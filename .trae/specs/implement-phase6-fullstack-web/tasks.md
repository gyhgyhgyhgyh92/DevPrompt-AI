# Tasks

> 对应实施计划 6A~6G（权威：`doc-阶段/2026-10-12-阶段六-W4全栈Web与记忆完善-实施计划.md` §3）。
> 每任务完成后立即验证对应验收标准（实施计划 §3 各子阶段「验收标准」），零错误才进下一任务。

- [x] Task 1: 6A 契约冻结与后端补全（T6-2 + T6-9 + T6-11 后端）：10 路径/12 操作契约 + openapi 导出 + 十固定事件（MUST-04 裁决：标准库 logging 替代 structlog）
  - [x] 1.1 定义 `/settings` Pydantic 契约（SettingsResponse/SettingsUpdate；api_key 仅脱敏形态；候选上限 25 不入 settings）；扩展 AppConfig 加载链 env > settings.json（0600）；按真源 §13 批准记录修订宪法 MUST-19 措辞（与三份配套文档同步，BREAKING 标注）
  - [x] 1.2 routes/schemas 落 GET+PUT /settings 薄壳（模型服务→设置文件，流程参数→SQLite app_settings 表）；PUT /preference 转正（preference_store.save + clip01 校验）；GET /history 转正（session store list，脱敏不返回原句）
  - [x] 1.3 十固定事件接线（flow.started/completed、decider.switched、recommendation.made/skipped、state.truncated、followup.guardrail、followup.escaped、cache.hit/miss；MUST-04 裁决走标准库 logging）；测试断言生产 INFO 级不落盘原句与完整路径
  - [x] 1.4 scripts/export-openapi.py + pytest 调 app.openapi() 导出 openapi.json 入库；两次导出 diff 为零（契约冻结证据）
  - [x] 1.5 门禁（ruff/mypy/pytest/架构检查/契约冒烟）+ 提交 `feat(api)`
- [x] Task 2: 6B 前端工程基座（T6-3）：Vite 工程 + tokens.css + check:contract 管线
  - [x] 2.1 pnpm create vite（react-ts）+ 技术栈 §6.1 依赖安装（提交 pnpm-lock.yaml，MUST-24 frozen）；禁 Tailwind/组件库/Redux/React Query
  - [x] 2.2 按 §5.1 建目录骨架（router/pages/components{ui,optimize,history,preference,settings}/stores/hooks/api/schemas/styles/utils/types/assets），空模块占位导出保证 tsc 通过
  - [x] 2.3 styles/tokens.css：设计 token 全 CSS Variables（品牌蓝/中性面板/暗色优先/语义色），data-theme 切换机制预留
  - [x] 2.4 scripts/check-contract.mjs：openapi-typescript 生成 openapi.generated.ts（入库勿手改）→ check:contract = 重新生成 + git diff --exit-code
  - [x] 2.5 Vitest 冒烟用例 + ESLint/Prettier 配置 + 四脚本接入 CI + 提交 `feat(web)`
- [x] Task 3: 6C 状态管理与 API 层（T6-6）：三 store + api 层 + useSSE（依赖 Task 2）
  - [x] 3.1 api/ 五文件（client 信封解包/request_id 透传、endpoints、interceptors、errors、types；SSE 订阅封装、超时与中止）
  - [x] 3.2 schemas/ 手写 Zod（optimize/preference/settings/common），必须与 openapi.generated.ts 对齐；校验失败不重试（MUST-15）
  - [x] 3.3 useOptimizeStore：流程快照/三套/ranking 视图；SSE 消息 store 内处理；断流不自动重连；恢复 = GET /result/{flow_id}
  - [x] 3.4 usePreferenceStore（向量+采纳历史）与 useSettingsStore（后端设置 + localStorage 外观项，键前缀 devprompt:v1: + Zod 读取校验）
  - [x] 3.5 useSSE：EventSource 生命周期，close() 写 effect cleanup（单测断言 unmount 关闭）
  - [x] 3.6 单测 ≥15 用例（SSE cleanup/畸形响应拒绝等）+ MUST-16 静态检查（useShallow）+ 提交 `feat(web)`——实际 53 用例全绿（1 冒烟 + 52 新增）
- [x] Task 4: 6D 三页面与工作台布局（T6-4）：三路由 + OptimizePage 三栏（依赖 Task 3）
  - [x] 4.1 路由表 + AppShell（标题栏：logo/项目 chip/API 状态 pill/⚙ 设置入口占位；三栏骨架容器）——BrowserRouter 切换兑现 6B 注记
  - [x] 4.2 OptimizePage 三态容器（输入→反问→结果，由 FlowSnapshot.status ask/done/guardrail 驱动）
  - [x] 4.3 会话侧栏（历史会话列表 + DONE/ASKING 徽章 + 新建会话；数据源 GET /history）
  - [x] 4.4 上下文面板（目标定位 symbol@path:line、取证事实 ✓ 列表、L3 偏好四维条——只读渲染）——快照契约补 target/facts 字段后接线
  - [x] 4.5 PhaseIndicator 步进器（9 态镜像，MUST-07）；HistoryPage / PreferencePage 骨架接数据
  - [x] 4.6 Testing Library 渲染冒烟 + 三页路由测试 + 提交 `feat(web)`——OptimizePage/History/Preference/PhaseIndicator/ContextPanel 共 18+4 用例
- [x] Task 5: 6F 设置中心 UI（T6-11 前端）：SettingsModal 四标签页（依赖 Task 3，与 Task 4 并行）
  - [x] 5.1 SettingsModal 外壳（模态 + 左侧四项导航 + Esc/✕ 关闭 + 焦点管理）
  - [x] 5.2 ModelServicePanel：供应商分段/脱敏密钥输入（输入新值才回传明文）/模型 ID/决策层下拉/调用参数三字段；「测试连接」= PUT 后读 GET /health 的 LLM 检查位（D-6F-2 复用检查位）
  - [x] 5.3 AppearancePanel：主题三态（缩略预览）→ localStorage devprompt:v1:appearance + data-theme 即时生效；语言（English 占位禁用）/代码字体/启动恢复/桌面通知 Toggle
  - [x] 5.4 MemoryPanel：L3 四维滑条（PUT /preference，超界后端 clip 兜底）+ 更新规则只读说明 + 采纳历史表格（GET /history）+ 导出 JSON + 清空（danger 双重确认，本地范围假设已标注）
  - [x] 5.5 SecurityPanel：护栏轮数/成本预算（PUT /settings）+ 候选上限 25 锁定只读（标注「宪法 MUST-09 锁定」）+ 遥测开关 + 清除本地数据（双重确认）
  - [x] 5.6 组件测试 ≥15 用例 + 提交 `feat(web)`——实际 32 用例（SettingsModal 7/面板 21/控件 4）
- [ ] Task 6: 6E 核心组件与流程联调（T6-5 + T6-7）：五核心组件 + mock e2e（依赖 Task 4）
  - [ ] 6.1 PromptCard + VariantTabs（A/B/C 三卡对比、推荐卡品牌边框、等宽代码区；渲染后端 body 不加工）
  - [ ] 6.2 RecommendBadge（仅 marked=true 渲染，含 confidence）+ ScoreDetail（展开 fit/pref/total，全取 ranking 视图）
  - [ ] 6.3 ConfidenceNotice：不标记时展示后端 reason 文案，不静默（MUST-27）
  - [ ] 6.4 FollowupForm：澄清卡 ×N（key/reason/best_guess 一键采用/输入框）+「直接生成」逃生常驻 + 软护栏裁决面板（guardrail_action 双选项）；answers 模式一次批量
  - [ ] 6.5 mock e2e 六路径（mock api 层返回，不 mock store 内部）：正常三套/反问答复/逃生/护栏继续/护栏逃生/刷新恢复
  - [ ] 6.6 T6-7 职责边界检查（grep 0.12|0.5|threshold 零命中 + 架构约束脚本）+ 组件测试 ≥20 + 提交 `feat(web)`
- [ ] Task 7: 6G 记忆注入与出口验收（T6-8 + T6-10 + W4 门禁）：（依赖 Task 5 + Task 6）
  - [ ] 7.1 三层记忆逐层关闭验证：空 L1 / 空 L2 / 中性 L3 注入，断言流程完成且行为符合预期（流程失败才判 FAIL，行为退化非缺陷；D-6G-3）
  - [ ] 7.2 真实 LLM 端到端冒烟一次（DeepSeek：输入→反问→三套→推荐→反馈→L3 变化），作为 W4 出口证据
  - [ ] 7.3 T6-10：组件清单四文档比对修正（以架构文档 §5.1 为权威）；§4.2 表清单确认含采纳历史表
  - [ ] 7.4 全栈联调：uvicorn + pnpm build 产物静态服务，走通一次完整流程
  - [ ] 7.5 W4 出口门禁六项逐项核对（实施计划 §3 6G 验收表）→ 更新真源 §1 阶段六行 + §13 变更记录 + 本计划 §7 执行留痕 → 提交 → 上报项目所有者签收

# Task Dependencies

- Task 2 依赖 Task 1（10 路径/12 操作契约冻结后生成前端类型）
- Task 3 依赖 Task 2
- Task 4 ∥ Task 5（并行，均依赖 Task 3）
- Task 6 依赖 Task 4
- Task 7 依赖 Task 5 + Task 6
- 任何任务触发不确定项（D-6A-1 history list 表结构变更 / D-6F-2 测试连接端点 / D-6G-3 记忆关闭失败）→ 暂停上报，不得擅自决定
- 严禁启动阶段七任务（T7-1 覆盖率、T7-2 恢复一致性等）
