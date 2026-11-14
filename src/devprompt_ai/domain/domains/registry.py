"""领域包注册表（纯查表，零 I/O）。

新增领域包三步：packs/ 下新增包文件 → 在此注册 → i18n 补 name/directives/sections
文案（tests/domain/domains/test_registry.py 会强制四包键在两语言齐全）。
"""

from __future__ import annotations

from typing import Final

from devprompt_ai.domain.domains.packs.av import av_pack
from devprompt_ai.domain.domains.packs.code import code_pack
from devprompt_ai.domain.domains.packs.creative import creative_pack
from devprompt_ai.domain.domains.packs.data import data_pack
from devprompt_ai.domain.domains.packs.finance import finance_pack
from devprompt_ai.domain.domains.packs.game import game_pack
from devprompt_ai.domain.domains.packs.learning import learning_pack
from devprompt_ai.domain.domains.packs.legal import legal_pack
from devprompt_ai.domain.domains.packs.life import life_pack
from devprompt_ai.domain.domains.packs.marketing import marketing_pack
from devprompt_ai.domain.domains.packs.medical import medical_pack
from devprompt_ai.domain.domains.packs.operations import operations_pack
from devprompt_ai.domain.domains.packs.translation import translation_pack
from devprompt_ai.domain.domains.packs.visual import visual_pack
from devprompt_ai.domain.domains.packs.work import work_pack
from devprompt_ai.domain.domains.ports import DomainPack

#: 注册顺序即确定性路由的词表匹配优先顺序与 UI 展示顺序。
_PACKS: Final[dict[str, DomainPack]] = {
    pack.id: pack
    for pack in (
        code_pack(),
        work_pack(),
        life_pack(),
        creative_pack(),
        visual_pack(),
        learning_pack(),
        data_pack(),
        marketing_pack(),
        translation_pack(),
        legal_pack(),
        medical_pack(),
        finance_pack(),
        game_pack(),
        av_pack(),
        operations_pack(),
    )
}


def get_pack(domain: str) -> DomainPack:
    """按 id 取包；未知 id 立即抛错（调用方须保证来源为 KNOWN_DOMAIN_IDS）。"""
    return _PACKS[domain]


def all_packs() -> tuple[DomainPack, ...]:
    """全部已注册领域包，注册顺序返回。"""
    return tuple(_PACKS.values())
