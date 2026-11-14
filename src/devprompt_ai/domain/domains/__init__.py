"""领域包模块对外出口（re-export，维持 domain 无 I/O 边界）。"""

from devprompt_ai.domain.domains.ports import (
    KNOWN_DOMAIN_IDS,
    DomainId,
    DomainPack,
    DomainVerdict,
)
from devprompt_ai.domain.domains.registry import all_packs, get_pack

__all__ = [
    "KNOWN_DOMAIN_IDS",
    "DomainId",
    "DomainPack",
    "DomainVerdict",
    "all_packs",
    "get_pack",
]
