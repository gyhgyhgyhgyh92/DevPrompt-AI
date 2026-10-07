"""F-203 探针问题定义：七项事实的未知项问法映射（纯逻辑）。"""

from __future__ import annotations

PROBE_ASK_TEXT: dict[str, str] = {
    "target_file_exists": "目标文件不存在——请确认正确的文件路径",
    "symbol_in_file": "目标符号未在文件中找到——请确认符号名（或给出定义位置）",
    "token_defined": "样式 token 未定义——请告知应使用的 token 名或其定义位置",
    "has_data_testid": "组件缺少 data-testid——是否需要补充？命名偏好？",
    "has_state_styles": "未见 hover/focus/active 多状态样式——是否需要覆盖？",
    "file_type_matches": "文件类型不在已知前端/样式类型内——请确认技术栈与文件类型",
    "test_file_exists": "未找到关联测试文件——是否需要同步新增？位置约定？",
}
