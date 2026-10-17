"""OpenAI Chat Completions 形态（绝大多数第三方厂商的唯一形态）。

薄封装：直接把 `OpenAIChatCompletionsModel` 包装成统一的构造入口，附带
「client 必须已就绪」的前置校验。协议细节全部由 SDK 处理。
"""

from __future__ import annotations

from agents.models.interface import Model
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from devprompt_ai.domain.model_spec import ApiMode


def build_chat_completions_model(
    model: str, client: AsyncOpenAI, *, api_mode: ApiMode = "chat_completions"
) -> Model:
    """构造 Chat Completions 形态的 Model 实例。

    :param model: 模型标识（用户填的 `model_id`）
    :param client: 已按当前 provider 配置好的 `AsyncOpenAI`（base_url/api_key）
    """
    if not model or not model.strip():
        raise ValueError("model 名不能为空")
    return OpenAIChatCompletionsModel(model=model.strip(), openai_client=client)


__all__ = ["build_chat_completions_model"]
