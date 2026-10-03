"""领域异常体系（架构文档 §3.4）：语义异常，不携带 HTTP 概念。

外部调用异常必须包装为本体系异常，禁止第三方异常穿透到服务层。
"""

from __future__ import annotations

from typing import Any


class DevPromptError(Exception):
    """领域异常基类：code 为 §3.3 错误码，context 为结构化上下文。"""

    code: int = 9001

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
        self, message: str, code: int = 2003, context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, context=context)


class DecisionError(DevPromptError):
    """决策层失败（3001–3004）。"""

    def __init__(
        self, message: str, code: int = 3001, context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, context=context)


class GenerationError(DevPromptError):
    """生成失败（4001–4003）。"""

    def __init__(
        self, message: str, code: int = 4001, context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, context=context)


class StateError(DevPromptError):
    """状态机违规（6001–6003）。"""

    def __init__(
        self, message: str, code: int = 6001, context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, context=context)


class ConfigurationError(DevPromptError):
    """配置错误（9002）。"""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=9002, context=context)
