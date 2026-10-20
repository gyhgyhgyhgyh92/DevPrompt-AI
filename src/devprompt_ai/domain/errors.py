"""领域异常体系（架构文档 §3.4）：语义异常，不携带 HTTP 概念。

外部调用异常必须包装为本体系异常，禁止第三方异常穿透到服务层。

错误码的权威清单在同包的 `error_codes.py`（架构文档 §3.3）；本模块只负责异常类型，
各类默认 code 引用该清单，避免同一码在两处定义而漂移。
"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.error_codes import registered


class DevPromptError(Exception):
    """领域异常基类：code 为 §3.3 错误码，context 为结构化上下文。"""

    code: int = registered(9001)

    def __init__(
        self, message: str, *, code: int | None = None, context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.context: dict[str, Any] = context or {}


class RetrievalError(DevPromptError):
    """检索与取证失败（2001–2006）。"""

    # code 允许位置传参：计划测试以 RetrievalError("x", 2001) 形式断言（最小修复，见偏差记录）
    def __init__(
        self, message: str, code: int = registered(2003), context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, context=context)


class DecisionError(DevPromptError):
    """决策层失败（3001–3004）。"""

    def __init__(
        self, message: str, code: int = registered(3001), context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, context=context)


class GenerationError(DevPromptError):
    """生成失败（4001–4003）。"""

    def __init__(
        self, message: str, code: int = registered(4001), context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, context=context)


class StateError(DevPromptError):
    """状态机违规（6001–6003）。"""

    def __init__(
        self, message: str, code: int = registered(6001), context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, context=context)


class ConfigurationError(DevPromptError):
    """配置错误（9002）。"""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=registered(9002), context=context)


class CatalogFetchError(DevPromptError):
    """模型目录拉取失败（5021）：端点不支持 / 鉴权失败 / 限流 / 超时。

    与其它外部依赖错误分开成类，是为了让 service 能**捕获它并回落旧列表**——
    拉不到模型清单不是致命错误（用户已配的条目仍可用），不该冒泡成 500。

    码刻意取 5021 而非 501x：5011–5015 是用户裁定的「LLM 调用失败」集合。
    """

    def __init__(
        self, message: str, code: int = registered(5021), context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, context=context)
