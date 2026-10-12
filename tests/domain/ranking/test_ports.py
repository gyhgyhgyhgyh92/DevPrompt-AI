"""F-402 端口契约测试：PreferenceStore Protocol 与 AdoptionRecord（无 I/O）。"""

import pytest

from devprompt_ai.domain.ranking.ports import AdoptionRecord, PreferenceStore


class _FakeStore:
    """满足 PreferenceStore 全部方法的最小实现（5D 的 SQLite 实现同签名）。"""

    async def load(self, user_id: str) -> dict[str, float]:
        return {}

    async def save(self, user_id: str, vector: dict[str, float]) -> None:
        return None

    async def record_adoption(self, rec: AdoptionRecord) -> None:
        return None

    async def clear_adoptions(self, user_id: str) -> int:
        return 0


class _PartialStore:
    """缺 record_adoption，不满足 Protocol。"""

    async def load(self, user_id: str) -> dict[str, float]:
        return {}


def test_preference_store_is_runtime_checkable() -> None:
    assert issubclass(_FakeStore, PreferenceStore)


def test_preference_store_rejects_partial_implementation() -> None:
    assert not issubclass(_PartialStore, PreferenceStore)


def test_adoption_record_holds_features() -> None:
    rec = AdoptionRecord(
        user_id="u1",
        session_id="s1",
        variant="C",
        edited=False,
        edited_text_ratio=0.0,  # 非编辑 = 0（F-503 语义）
        features={
            "detail_level": 0.9,
            "include_diff": 0.9,
            "specify_tests": 0.8,
            "max_files_norm": 1.0,
        },
    )
    assert rec.variant == "C"
    assert rec.edited is False
    assert rec.features["max_files_norm"] == 1.0
    with pytest.raises((AttributeError, TypeError)):
        rec.variant = "A"  # type: ignore[misc]  # frozen dataclass 不可变
