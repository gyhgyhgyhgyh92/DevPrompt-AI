# Checklist

## 宪法级（每任务收口必过）
- [ ] ruff check + ruff format --check 全绿
- [ ] mypy strict 零错误
- [ ] pytest 全绿（基线 143+，逐任务递增）
- [ ] scripts/check_architecture.py 通过（ranking/recommend 判定仅存在于 domain/ranking/recommend.py；前端零阈值常量）
- [ ] 无新增第三方依赖（typesafe-sdk 走既有 jev extra；429 退避手写）
- [ ] 子代理零 git 操作；提交信息 type(scope) 符合 MUST-21；6F 提交含 BREAKING CHANGE footer

## 功能验收（对应 tasks.md 逐项）
- [ ] F-804 两条可执行验收落入功能清单，无空括号（T5-11①）
- [ ] FEATURE_TABLE 四维取值与 F-402 原文逐值一致
- [ ] 加权总分手工验算断言通过（SHOULD-10）
- [ ] MUST-27 五条优先级各有测试且命中即止（四情形 + 压序）
- [ ] 推荐不标时 reason 文案具体（无静默不标）
- [ ] 三套同次调用；A 无行号、C 含行号+token 出处+测试指令（F-302/303/304）
- [ ] 仅 A 档：单套输出 + 跳过打分与推荐 + 不计算 d（MUST-28）
- [ ] L3 五类更新规则单测通过；连续采纳 C 偏好移动；跳过回归 0.5（开放决策 #1 定稿公式）
- [ ] adoption_history 入库可查
- [ ] JEV_MODEL_ID 恒 jev-1.13.0（禁别名断言）；30000 截断记 state.truncated；429 指数退避
- [ ] Jev(mock) 与 fallback 输出结构逐字段一致（MUST-12）
- [ ] 无 key 全链路可跑（SHOULD-11）
- [ ] rank_components 进 RETRIEVING 主链；缓存键含阈值配置 hash（MUST-14）
- [ ] RANKING 态流转真实发生（状态机断言）
- [ ] GET /preference 返回 L3 真实向量；feedback 后向量变化
- [ ] PUT /preference 与 /history 维持 501/9004
- [ ] uvicorn 真实冒烟：optimize 三套+推荐标记；escape 单套 A 无 ranking

## 生死线与收口
- [ ] measure_ranking 100 条全量跑（5 仓 × 20 条）
- [ ] 报告标注「LLM 排序准确率」（不与 Jev 混用）
- [ ] 主流程复跑判定 ≥80%
- [ ] 失败案例逐条归因（eval/recall/report-ranking-*.md）
- [ ] 真源 §1 阶段五状态 + §13 变更记录更新
- [ ] F-202 三处空规格补全确认（T5-11②）
- [ ] <80% 时：停止、上报、等用户甲/乙裁决（MUST-25）——不得含糊继续
