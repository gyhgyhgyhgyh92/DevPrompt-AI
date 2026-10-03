"""子命令实现。"""


def cmd_init(path: str) -> int:
    """初始化项目目录。"""
    print(f"init {path}")
    return 0


def cmd_build(path: str) -> int:
    """构建项目。"""
    print(f"build {path}")
    return 0
