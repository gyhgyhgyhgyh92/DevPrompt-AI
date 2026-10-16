"""决策层中文提示模板（单次调用内并行提出全部问题，F-202 行为列的前置约定）。

M-7 接入：三类 system 提示均带 T-2 任务边界声明（防裁判越权「顺手回答用户问题」）；
FACTS_SYSTEM 另加 T-3 Non-Goals（明确不评价代码质量、不提重构建议）。
证据字段（用户需求 / 候选 / 取证结果）统一经 `build_evidence_block` 包裹（M-5）——
候选符号名与取证证据均来自被检索的真实代码，其中的字符串可能含指令性文本。
"""

from devprompt_ai.domain.prompt_guard import (
    NON_GOALS_PROBING,
    TASK_NOT_EXECUTE,
    build_evidence_block,
)

RANK_SYSTEM = f"""你是代码检索排序裁判。给定用户需求与候选符号列表（仅名称与路径），
判断哪些候选最可能是用户想要修改的目标。只输出 JSON。
注意：这是排序任务，不是检索任务；候选集之外不存在答案。

{TASK_NOT_EXECUTE}"""

RANK_USER = """请输出 JSON：{{"order": [按最优到最差排列的候选索引], "confidence": 0到1的小数}}

{evidence}"""

FACTS_SYSTEM = f"""你是事实研判裁判。给定七项客观事实的取证结果（真/假+证据），
综合研判当前信息是否足以支持用户需求，并给出每项判定的置信度。只输出 JSON。

{TASK_NOT_EXECUTE}

{NON_GOALS_PROBING}"""

FACTS_USER = """请输出 JSON：
{{"judgments": [{{"key": "事实键", "passed": true/false, "confidence": 0到1}}...],
 "overall_confidence": 0到1的小数}}

{evidence}"""

SCORE_SYSTEM = f"""你是提示词方案适配度评委。按 0~4 五档评分（0 完全不适配、1 误导风险高、
2 需大幅编辑、3 少量微调、4 完美适配）。只输出 JSON。

{TASK_NOT_EXECUTE}"""

SCORE_USER = """请输出 JSON：
{{"scores": [{{"variant": "A|B|C", "score": 0到4整数, "confidence": 0到1}}...]}}

{evidence}"""


def rank_evidence(sentence: str, candidates: str) -> str:
    """排序任务的证据块（M-5）。"""
    return build_evidence_block({"用户需求": sentence, "候选符号": candidates})


def facts_evidence(sentence: str, facts: str) -> str:
    """事实研判任务的证据块（M-5）。"""
    return build_evidence_block({"用户需求": sentence, "取证结果": facts})


def score_evidence(context: str, variants: str) -> str:
    """打分任务的证据块（M-5）。"""
    return build_evidence_block({"项目上下文": context, "待评方案": variants})
