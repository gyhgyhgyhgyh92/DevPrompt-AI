"""MUST-20 路径穿越防护：safe_join 的正反用例。"""

from devprompt_ai.domain.retrieval.paths import safe_join


def test_normal_relative_path_joins() -> None:
    """正常仓库相对路径必须放行（防止防护过严）。"""
    assert safe_join("D:/proj", "src/a.ts") == "D:/proj/src/a.ts"
    assert safe_join("D:\\proj", "src\\a.ts") == "D:/proj/src/a.ts"


def test_parent_traversal_is_rejected() -> None:
    assert safe_join("D:/proj", "../../etc/passwd") == ""
    assert safe_join("D:/proj", "src/../../outside.ts") == ""


def test_absolute_path_is_rejected() -> None:
    assert safe_join("D:/proj", "/etc/passwd") == ""


def test_windows_drive_path_is_rejected() -> None:
    assert safe_join("D:/proj", "C:/Windows/system32/config") == ""


def test_empty_root_rejects_parent_traversal() -> None:
    """root 缺省时只接受不以 .. 开头的相对路径。"""
    assert safe_join("", "../a.ts") == ""
    assert safe_join(".", "../a.ts") == ""
    assert safe_join(".", "src/a.ts") == "src/a.ts"
