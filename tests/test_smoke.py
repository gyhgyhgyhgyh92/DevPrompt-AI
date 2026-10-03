"""打包冒烟测试：验证 src 布局安装后包可导入。"""


def test_package_importable() -> None:
    import devprompt_ai

    assert "DevPrompt AI" in (devprompt_ai.__doc__ or "")
