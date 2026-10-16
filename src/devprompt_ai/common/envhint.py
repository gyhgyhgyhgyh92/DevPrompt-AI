"""启动配置问题的可操作提示（纯工具层，无业务语义）。

为什么需要：配置缺失原本只抛一句 `ConfigurationError("权重之和必须为 1.0")`，
用户看不出「缺哪个变量、去哪填」。本模块把问题清单渲染成逐条可执行的中文提示。

安全边界（MUST-19）：**只输出变量名与用途，绝不输出任何值**。调用方负责保证
传入的描述文本本身不含密钥。
"""

from __future__ import annotations

from collections.abc import Sequence

#: 提示尾部统一给出的修复入口（本地单用户形态，架构文档 §1.6）
_WHERE = "请在 .env 文件或应用设置中心填写"

#: 环境变量名 → 缺失后的影响说明（供 AppConfig.validate 引用）
ENV_PURPOSE: dict[str, str] = {
    "LLM_BASE_URL": "LLM 端点地址，缺失则无法调用模型",
    "LLM_API_KEY": "模型服务密钥，缺失则无法调用模型",
    "LLM_MODEL": "模型标识，缺失则无法调用模型",
}


def render_env_hint(problems: Sequence[tuple[str, str]]) -> str:
    """把「(变量名, 说明)」清单渲染为多行提示。

    :param problems: 每项为 ``(变量名, 该项的问题说明)``；变量名可为非环境变量
        的概念名（如"权重配置"），由调用方决定措辞
    :return: 多行中文提示；``problems`` 为空时返回空串
    """
    if not problems:
        return ""
    lines = [f"配置检查未通过，共发现 {len(problems)} 个问题："]
    for name, detail in problems:
        lines.append(f"  - {name}：{detail}")
    lines.append(_WHERE)
    return "\n".join(lines)
