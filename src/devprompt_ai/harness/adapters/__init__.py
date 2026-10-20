"""协议适配层：把不同 API 形态统一成 openai-agents 的 `Model` 接口。

分层理由（MUST-06）：`domain/model_spec.py` 只描述「这个 provider 用哪种形态、有哪些
参数约束」（纯数据）；本包负责「怎么把请求发出去、怎么把响应读回来」（I/O 与协议细节）。
二者分离使得新增一个 provider 通常只改数据表，而新增一种**协议形态**才需要动本包。

为什么需要本包：openai-agents 内置 `OpenAIChatCompletionsModel` 与 `OpenAIResponsesModel`
覆盖 OpenAI 系两种形态；Anthropic Messages 与 Gemini GenerateContent 的原生形态需自行
实现 `Model` 抽象（仅 2 个抽象方法，Runner 的工具循环与流式映射全部复用）。

**关键约束**：不得使用 `set_default_openai_api()` —— 那是进程级单例，Web 并发下按
provider 反复设置会相互覆盖（A 请求设 responses、B 请求设 chat_completions → 随机 4xx）。
本包一律**按调用构造 Model 实例**，无共享可变状态。
"""

from __future__ import annotations

from devprompt_ai.harness.adapters.registry import (
    adapter_kind_for,
    build_adapter,
    registered_api_modes,
    supported_adapter_kinds,
)

__all__ = [
    "adapter_kind_for",
    "build_adapter",
    "registered_api_modes",
    "supported_adapter_kinds",
]
