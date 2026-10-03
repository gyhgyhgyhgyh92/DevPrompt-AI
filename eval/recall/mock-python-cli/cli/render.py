"""终端渲染工具。"""


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """渲染 ASCII 表格。"""
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    lines = [" | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    lines.append("-+-".join("-" * w for w in widths))
    for row in rows:
        lines.append(" | ".join(c.ljust(widths[i]) for i, c in enumerate(row)))
    return "\n".join(lines)
