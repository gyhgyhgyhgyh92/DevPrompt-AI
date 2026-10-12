# Tasks

> 权威依据：本目录 spec.md（5 图 + 4 项澄清裁定）。任务边界严格限定「前端对话式重构 + 会话管理契约增补」，不启动阶段七任务。
> 每任务完成后立即验证对应验收标准，零错误才进下一任务；子代理零 git 操作，主流程串行提交。

- [x] Task 1: 后端会话管理契约增补（title/pinned/PATCH/DELETE）—— 305 passed（+17）
  - [x] 1.1 `memory/session_store.py`：`list_recent` 返回 title（custom_title 优先，否则原句截断 ≤40 字）与 pinned（读 payload，无 DDL 变更——最小改动）；排序 pinned 优先 + updated_at 倒序；新增 `delete(session_id)`（每操作独立连接，MUST-06 SQL 限 memory/）
  - [x] 1.2 `domain/models.py`：SessionSummary 增 `title: str`、`pinned: bool`；SessionStore Protocol 增 `delete`
  - [x] 1.3 `service.py`：`rename_session` / `pin_session` / `delete_session`（薄封装 + 归属校验 6003，`_load_owned`）
  - [x] 1.4 `schemas.py` + `routes.py`：HistoryItemPayload 增 title/pinned；新增 `PATCH /history/{session_id}`（HistoryUpdateRequest: title?/pinned?，None=不变，空更新 422）与 `DELETE /history/{session_id}`；X-Request-ID 透传沿用
  - [x] 1.5 测试：store 集成（截断/置顶排序/重命名/删除幂等）+ 路由（PATCH/DELETE 200、未知 id 6003）+ openapi 重生成（12 路径/15 操作）与计数测试更新
  - [x] 1.6 门禁（ruff/mypy/pytest/架构检查/契约冒烟）+ 提交 `feat(api)`
- [x] Task 2: 设计 token 与全局样式基线（依赖：无，可先行）—— 146 用例全绿
  - [x] 2.1 `styles/tokens.css`：默认浅色主题为第一视觉（对照图一~五色板）；深色主题保留可切换（`data-theme` 切换不废除）；品牌由蓝改绿
  - [x] 2.2 排版与断点基线：字号/行高/间距按图；断点 360/768/1024/1440/1920（移动优先，`--bp-*` 新增）
  - [x] 2.3 `styles/global.css`：页面级重置与布局容器（`--sidebar-width` 接入）
  - [x] 2.4 门禁（typecheck/lint/test/build）+ 提交 `feat(web)`
- [x] Task 3: 启动页居中主视觉卡片（图一 1:1，依赖 Task 2）—— ConsoleInput 7 用例
  - [x] 3.1 `components/optimize/ConsoleInput.tsx`（新组件）：居中卡片（max-width 720）+ 固定文案区 + 工具行（发送按钮 + 模型名只读 + 选择文件夹）+ 项目路径选择行
  - [x] 3.2 移除清单落实：无 ＋附件/手动审批/文件类型图标/麦克风/音频/「本地」任何元素（测试逐项断言零存在）
  - [x] 3.3 固定文案逐字；模型名读 `useSettingsStore`；发送禁用防重（MUST-15）；选择文件夹 → 项目路径
  - [x] 3.4 交互优化：输入自适应高度；初始态与结果区切换
  - [x] 3.5 测试（≥6）+ 提交 `feat(web)`
- [x] Task 4: 左侧固定侧边栏（图三 1:1，依赖 Task 1 + Task 2）—— ProjectSidebar 13 用例
  - [x] 4.1 `components/history/ProjectSidebar.tsx`：固定定位、顶部「项目」+ 排序/筛选图标；旧 SessionSidebar 已删除
  - [x] 4.2 分组渲染：项目分组（文件夹图标 + 组名灰字）+ 条目（title）；悬停态；分组收展（筛选图标切换）
  - [x] 4.3 数据接线：`GET /history`（title/pinned）；空态；「＋新建会话」入口（列表上方轻量按钮）
  - [x] 4.4 测试（≥6）+ 提交 `feat(web)`
- [x] Task 5: 条目选中与 ⋮ 菜单（图四 1:1，依赖 Task 4）—— SessionMenu 4 用例
  - [x] 5.1 选中态：点击同步高亮（<100ms 不等待网络）+ 左侧图标 + ⋮；选中后经 `GET /result` 异步加载（不阻塞高亮）
  - [x] 5.2 `SessionMenu`：4 项（置顶/复制路径/重命名/删除红字）；视觉对齐；Esc/外点关闭；键盘可达
  - [x] 5.3 功能接线：置顶 PATCH 排前；重命名内联编辑 PATCH；删除二次确认 DELETE；复制路径 clipboard + toast（注：当前复制 basename，全路径随 Task 6 前置小修提供 project_root 字段后接续）
  - [x] 5.4 测试（≥8）+ 提交 `feat(web)`
- [x] Task 6: 正式界面对话流（图五 1:1，依赖 Task 2 + Task 4）—— ChatStream 用例 + mock e2e 六路径（提交 2be3843）
  - [x] 6.1 `components/optimize/ChatStream.tsx` 骨架：用户消息气泡（右对齐浅灰圆角块）+ AI 回复块（小图标 + DevPrompt 标识 + 耗时/状态折叠行 + 分隔线 + 正文 + 操作栏[复制/重试/反馈/由 AI 生成]）
  - [x] 6.2 方案组嵌入：PromptCard/VariantTabs/RecommendBadge/ScoreDetail/ConfidenceNotice/上下文信息（目标定位/取证事实）重排进回复正文；追问卡 FollowupForm 以回复块形式呈现（MUST-26/27/08 全保留）
  - [x] 6.3 底部建议胶囊：承载 采纳 A/B/C / 编辑后采纳 / 跳过（`POST /feedback`）；操作栏按钮接线（复制/重试/反馈）
  - [x] 6.4 耗时折叠行：映射流程状态 + 耗时（替代 PhaseIndicator 信息位，MUST-07 只镜像）；ASKING/护栏态对话式呈现
  - [x] 6.5 mock e2e 六路径更新（对话流断言）：正常三套/反问/逃生/护栏继续/护栏逃生/刷新恢复 + 视觉属性断言（气泡底色/分隔线存在/「由 AI 生成」）
  - [x] 6.6 测试（≥10）+ 提交 `feat(web)`
- [x] Task 7: 响应式适配与废弃清理（依赖 Task 3/5/6）—— 前端 182 用例（+App 抽屉 4 用例）
  - [x] 7.1 响应式：360/768/1024/1440/1920 五档断言（<768 侧边栏抽屉 + 汉堡 + 遮罩；卡片与对话流在窄屏单列；无横向溢出）
  - [x] 7.2 清理：删除不兼容旧组件（PhaseIndicator/SessionSidebar 旧实现/ContextPanel 若已融入）、废弃 CSS/未用导出与资源；grep 残留引用零命中
  - [x] 7.3 全量门禁：前端五脚本 + 后端四门禁 + `check:contract`（12 路径/15 操作）+ 架构约束（前端零阈值）+ T6-7 复验
  - [x] 7.4 文档收口：UI 设计文档增补「对话式重构定稿」章节（引用 5 图与裁定）；真源 §13 留痕；提交 `docs(spec)`

# Task Dependencies

- Task 1（后端契约）与 Task 2（样式基线）∥ 可并行
- Task 3 依赖 Task 2；Task 4 依赖 Task 1 + Task 2
- Task 5 依赖 Task 4；Task 6 依赖 Task 2 + Task 4（与 Task 5 可并行）
- Task 7 依赖 Task 3/5/6 全部合流
- 任何实现细节歧义（如菜单图标选择、动画曲线）→ 立即上报用户，不得臆测
- 严禁启动阶段七任务；不新增第三方依赖（MUST-04）