"""OpenAI Responses API 形态（仅 OpenAI 官方端点默认使用）。

与 Chat Completions 的差异由 SDK 内部处理（`max_tokens` → `max_output_tokens` 等），
本模块只做统一构造入口。

注意：`frequency_penalty` / `presence_penalty` 在 Responses payload 中被 SDK 静默
丢弃——该事实已在 `domain/model_spec.ParameterDefinition.native_modes` 中登记，
UI 会据此显示「该参数在当前模式下不生效」，不在此处重复判断。
"""

from __future__ import annotations

from agents.models.interface import Model
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI

from devprompt_ai.domain.model_spec import ApiMode


def build_responses_model(
    model: str, client: AsyncOpenAI, *, api_mode: ApiMode = "responses"
) -> Model:
    """构造 Responses API 形态的 Model 实例。

    `model_is_explicit=True` 是 SDK 默认值，表示「用户明确指定了模型名」，
    避免 SDK 回落到环境变量里的默认模型。
    """
    if not model or not model.strip():
        raise ValueError("model 名不能为空")
    return OpenAIResponsesModel(model=model.strip(), openai_client=client, model_is_explicit=True)


__all__ = ["build_responses_model"]
