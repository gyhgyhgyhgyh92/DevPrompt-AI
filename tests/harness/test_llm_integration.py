"""真实端点集成冒烟（F-004 验收的最小形态；无环境变量自动 skip）。"""

import os

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.decision.fallback import LLMFallbackDecider
from devprompt_ai.domain.models import Candidate

pytestmark = pytest.mark.skipif(
    not (os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_MODEL")),
    reason="需要 LLM_BASE_URL/LLM_MODEL（真实端点冒烟）",
)


async def test_rank_smoke_against_real_endpoint() -> None:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    cands = [
        Candidate(
            name="SubmitButton", path="src/ui/Button.tsx", line=1, score=2.0, source="symbol"
        ),
        Candidate(name="UserList", path="src/user/List.tsx", line=1, score=1.0, source="symbol"),
    ]
    out = await LLMFallbackDecider(cfg).rank_components("把提交按钮颜色改为 primary-500", cands)
    assert sorted(out.order) == [0, 1]
    assert 0.0 <= out.confidence <= 1.0
