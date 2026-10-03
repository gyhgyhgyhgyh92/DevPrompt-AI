"""mock-python-cli 命令入口。"""


def main() -> int:
    """CLI 主入口。"""
    args = parse_args()
    if args.command == "init":
        return cmd_init(args.path)
    return cmd_build(args.path)


def parse_args() -> object:
    """解析命令行参数。"""
    import argparse

    parser = argparse.ArgumentParser(prog="mockcli")
    parser.add_argument("command", choices=["init", "build"])
    parser.add_argument("--path", default=".")
    return parser.parse_args()
