# DevPrompt AI v0.1.0

把一句模糊需求，变成带行号与 token 出处、可被 ripgrep 反向验证的工程级提示词。

## 安装包

| 平台 | 产物 |
|---|---|
| Windows 10+ (x64) | `DevPromptAI-0.1.0-win-x64.exe` |
| macOS 11+ (arm64) | `DevPromptAI-0.1.0-mac-arm64.dmg` |
| Linux (x86_64) | `DevPromptAI-0.1.0-linux-x86_64.AppImage` |

桌面端与 Web 形态共用同一份业务逻辑与 `~/.devprompt-ai` 数据，可交替使用。

## 未签名说明

项目未购买代码签名证书：

- **Windows**：首次运行可能见 SmartScreen「未知发布商」，点「更多信息 → 仍要运行」。
- **macOS**：`.dmg` 未签名未公证，首次打开需在「系统设置 → 隐私与安全性」中点「仍要打开」。

这属信誉警告而非病毒判定。

## 本次包含

- 桌面端首次正式发布，交付形态覆盖 Windows / macOS / Linux 三平台
- 桌面工作台：48px 活动栏 + 296px 会话侧栏 + 对话区 + 可折叠运行日志面板 + 状态栏
- 打包链路统一为 electron-builder（NSIS / DMG / AppImage），版本号唯一来源 `pyproject.toml`

## 许可

[MIT](https://github.com/gyhgyhgyhgyh92/DevPrompt-AI/blob/master/LICENSE) License。

