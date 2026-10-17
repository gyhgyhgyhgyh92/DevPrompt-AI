"""adapter 注册表：`adapter_kind` → 构造器。

设计要点：**零 `if adapter_kind == ...` 分支**。新增一种协议形态只需在
`_REGISTRY` 加一行，调用方与测试都不改（与 `domain/model_spec.PROVIDER_SPECS`
「新增 provider 只改数据」的哲学一致）。

原生形态（anthropic / gemini）的构造器在 `anthropic_native` / `gemini_native`
模块中，此处**惰性导入**——避免未安装 `anthropic` / `google-genai` 时仅因
import 本模块就失败（这两个依赖是可选安装的）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, TypeAlias

from agents.models.interface import Model
from openai import AsyncOpenAI

#: 构造器签名：`(model, client, **kwargs) -> Model`。
#: `**kwargs` 预留给原生形态所需的额外配置（如 anthropic 的 api_key）。
ModelBuilder: TypeAlias = Callable[..., Model]


def _build_openai_compat(model: str, client: AsyncOpenAI, **_kw: Any) -> Model:
    from devprompt_ai.harness.adapters.openai_compat import build_chat_completions_model

    return build_chat_completions_model(model, client)


def _build_openai_responses(model: str, client: AsyncOpenAI, **_kw: Any) -> Model:
    from devprompt_ai.harness.adapters.openai_responses import build_responses_model

    return build_responses_model(model, client)


def _build_anthropic_native(model: str, client: AsyncOpenAI, **kw: Any) -> Model:
    from devprompt_ai.harness.adapters.anthropic_native import build_anthropic_model

    return build_anthropic_model(model, client, **kw)  # type: ignore[no-any-return]


def _build_gemini_native(model: str, client: AsyncOpenAI, **kw: Any) -> Model:
    from devprompt_ai.harness.adapters.gemini_native import build_gemini_model

    return build_gemini_model(model, client, **kw)  # type: ignore[no-any-return]


_REGISTRY: Final[dict[str, ModelBuilder]] = {
    "openai_compat": _build_openai_compat,
    "openai_responses": _build_openai_responses,
    "anthropic_native": _build_anthropic_native,
    "gemini_native": _build_gemini_native,
}


def supported_adapter_kinds() -> tuple[str, ...]:
    """全部已登记的 adapter_kind（供测试断言「表里的 kind 都有构造器」）。"""
    return tuple(sorted(_REGISTRY))


def build_adapter(adapter_kind: str, model: str, client: AsyncOpenAI, **kwargs: Any) -> Model:
    """按 `adapter_kind` 构造 Model 实例。

    :raises KeyError: kind 未登记——这是**开发期错误**（PROVIDER_SPECS 与注册表不一致），
        故直接抛而非静默回落：静默回落会让用户以为在用原生协议，实际走了兼容层。
    """
    builder = _REGISTRY.get(adapter_kind)
    if builder is None:
        raise KeyError(
            f"未登记的 adapter_kind: {adapter_kind!r}；已登记：{supported_adapter_kinds()}"
        )
    return builder(model, client, **kwargs)


__all__ = ["ModelBuilder", "build_adapter", "supported_adapter_kinds"]
