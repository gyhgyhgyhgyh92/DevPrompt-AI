"""领域异常与错误码测试。"""

from devprompt_ai.domain.errors import (
    ConfigurationError,
    DecisionError,
    DevPromptError,
    GenerationError,
    RetrievalError,
    StateError,
)


def test_error_carries_code_and_context() -> None:
    err = ConfigurationError("权重和必须为 1.0", {"weights": [0.7, 0.4]})
    assert isinstance(err, DevPromptError)
    assert err.code == 9002
    assert err.context == {"weights": [0.7, 0.4]}
    assert "1.0" in str(err)


def test_error_code_ranges() -> None:
    assert ConfigurationError("x").code == 9002
    assert DecisionError("x", 3001).code == 3001
    assert GenerationError("x", 4003).code == 4003
    assert RetrievalError("x", 2001).code == 2001
    assert StateError("x", 6001).code == 6001


def test_subclasses_are_devprompt_error() -> None:
    for cls in (ConfigurationError, DecisionError, GenerationError, RetrievalError, StateError):
        assert issubclass(cls, DevPromptError)
