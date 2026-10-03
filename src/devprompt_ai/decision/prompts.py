"""决策层中文提示模板（单次调用内并行提出全部问题，F-202 行为列的前置约定）。"""

RANK_SYSTEM = """你是代码检索排序裁判。给定用户需求与候选符号列表（仅名称与路径），
判断哪些候选最可能是用户想要修改的目标。只输出 JSON。
注意：这是排序任务，不是检索任务；候选集之外不存在答案。"""

RANK_USER = """用户需求：{sentence}

候选（索引从 0 开始）：
{candidates}

请输出 JSON：{{"order": [按最优到最差排列的候选索引], "confidence": 0到1的小数}}"""

FACTS_SYSTEM = """你是事实研判裁判。给定七项客观事实的取证结果（真/假+证据），
综合研判当前信息是否足以支持用户需求，并给出每项判定的置信度。只输出 JSON。"""

FACTS_USER = """用户需求：{sentence}

取证结果：
{facts}

请输出 JSON：{{"judgments": [{{"key": "事实键", "passed": true/false, "confidence": 0到1}}...],
"overall_confidence": 0到1的小数}}"""

SCORE_SYSTEM = """你是提示词方案适配度评委。按 0~4 五档评分（0 完全不适配、1 误导风险高、
2 需大幅编辑、3 少量微调、4 完美适配）。只输出 JSON。"""

SCORE_USER = """项目上下文：
{context}

待评方案：
{variants}

请输出 JSON：{{"scores": [{{"variant": "A|B|C", "score": 0到4整数, "confidence": 0到1}}...]}}"""
