# Checklist

## 宪法级（每任务收口必过）
- [ ] ruff check + ruff format --check 全绿（后端改动任务）
- [ ] mypy strict 零错误（后端改动任务）
- [ ] pytest 全绿（基线 257+1 skipped，逐任务递增）
- [ ] 前端 tsc / eslint / vitest / pnpm build / check:contract 五脚本全绿（前端改动任务）
- [ ] scripts/check_architecture.py 通过（业务判定仅 domain/ranking/recommend.py；前端零阈值常量）
- [ ] 无新增第三方依赖超出技术栈 §6.1（MUST-04；如需必须先上报更新技术栈文档）
- [ ] 提交信息 type(scope) 符合 MUST-21；6A 提交含 MUST-19 条文修订 BREAKING 标注与批准记录
- [ ] 子代理零 git 操作，主流程串行提交与门禁复验

## 功能验收（对应 tasks.md 逐项）
- [x] /settings 契约冻结（10 路径/12 操作），openapi 两次导出 diff 为零
- [x] PUT /settings 密钥落本地设置文件（0600），SQLite 与日志中无密钥，GET 回显恒脱敏
- [x] PUT /preference 转正：clip01 校验生效，PUT 后 GET 返回更新值
- [x] GET /history 转正：脱敏返回（id/时间/state/项目名），无原句明文
- [x] 十固定事件接线（标准库 logging，依 MUST-04 裁决替代 structlog）；生产 INFO 级不落盘原句与完整路径
- [x] MUST-19 宪法措辞修订落地（env > settings 文件），三份配套文档同步
- [x] 前端目录树与 §5.1 diff 为零（含 components/settings 组、useSettingsStore、schemas/settings.ts）
- [x] tokens.css 全 CSS Variables；data-theme 切换机制可用
- [x] check:contract 通过（openapi.generated.ts 自动生成，Zod 与生成类型一致）
- [x] 三 store 齐备；SSE 消息 store 内处理；close() 写 effect cleanup（单测断言）
- [x] 畸形响应被 Zod 拒绝且不重试（MUST-15）
- [x] 无 `useStore(s => ({...}))` 违规形态（MUST-16）
- [x] 三页面可访问、路由切换正常、刷新后流程状态不丢失（GET /result 恢复）
- [x] OptimizePage 三栏工作台布局成型；步进器仅镜像 9 态（MUST-07）
- [x] 上下文面板只读渲染目标定位/取证事实/L3 向量（快照契约已补 target/facts）
- [ ] 五核心组件齐备：推荐徽章仅 marked=true 渲染；不标记时 reason 文案具体（MUST-27）
- [ ] FollowupForm 澄清卡四要素 + 逃生常驻 + 软护栏裁决面板（MUST-26）
- [ ] mock e2e 六路径全 PASS（正常三套/反问/逃生/护栏继续/护栏逃生/刷新恢复）
- [x] 设置中心四标签页可操作；保存后 GET 回读一致；主题即时生效且刷新保持
- [x] 密钥任何界面状态不出现明文（type=password + 回显脱敏）
- [x] 候选上限锁定项 disabled 且标注「宪法 MUST-09 锁定」
- [x] 前端 grep 0.12|0.5|threshold 零命中（MUST-08）
- [ ] 记忆三层逐层关闭验证通过（空 L1/空 L2/中性 L3，流程失败才判 FAIL）
- [ ] 组件清单四文档 diff 为零（以 §5.1 为权威，T6-10）
- [ ] §4.2 表清单含采纳历史表

## W4 出口门禁（Task 7 收口必过）
- [ ] 门禁 1：Web 全栈行为一致（前端产物 + HTTP 层走通完整流程；同一份 service/state/memory/config；HTTP 层零业务逻辑）
- [ ] 门禁 2：记忆三层生效（逐层关闭验证通过；真实冒烟中 L3 向量经反馈更新可观测）
- [ ] 门禁 3：设置中心可用（F-604 验收全过；/settings 契约冒烟通过）
- [ ] 门禁 4：前端质量（五脚本绿 + 组件测试全绿 + T6-7 零阈值检查通过）
- [ ] 门禁 5：契约一致（check:contract 绿 10 路径/12 操作；Zod 与生成类型一致）
- [ ] 门禁 6：文档一致（组件清单四文档 diff 为零；实施计划 §7 有执行留痕）
- [ ] 真源 §1 阶段六状态行 + §13 变更记录更新
- [ ] 真实 LLM 端到端冒烟证据留存（W4 出口）
- [ ] 出口门禁任一不达标 → 停止上报，不得含糊进入阶段七
- [ ] 全部通过后上报项目所有者签收
