# DevPrompt AI v0.3.0

把一句模糊需求，变成带行号与 token 出处、可被 ripgrep 反向验证的工程级提示词。

## 安装包

| 平台 | 产物 | 版本 |
|---|---|---|
| Windows 10+ (x64) | `DevPromptAI-0.3.0-win-x64.exe` | v0.3.0 |
| macOS 11+ (arm64) | `DevPromptAI-0.3.0-mac-arm64.dmg` | v0.3.0 |
| Linux (x86_64) | `DevPromptAI-0.3.0-linux-x86_64.AppImage` | v0.3.0 |

三平台同步构建；**自动更新仅 Windows 提供**，macOS / Linux 仍靠手动覆盖安装。

0.2.0 及更早版本没有更新器，需手动安装 0.3.0 一次；之后 Windows 才会自动更新到更高版本。

桌面端与 Web 形态共用同一份业务逻辑与 `~/.devprompt-ai` 数据，可交替使用。

## 未签名说明

项目未购买代码签名证书：

- **Windows**：首次运行可能见 SmartScreen「未知发布商」，点「更多信息 → 仍要运行」。
- **macOS**：`.dmg` 未签名未公证，首次打开需在「系统设置 → 隐私与安全性」中点「仍要打开」。

这属信誉警告而非病毒判定。

## 本次包含

- **Windows 桌面端自动更新**：启动约 10 秒后检查、每 6 小时轮询，设置中心「关于与更新」可手动检查
- **镜像优先、GitHub 直连兜底**：`ghfast.top` → `ghproxy.net` → `gh-proxy.com` → GitHub；GitHub 可达时会交叉校验清单
- **确认后下载**：检查到新版本先提示，用户同意后下载；完成后提示立即重启安装
- **安装前保护**：停 sidecar 并等待退出，备份 `~/.devprompt-ai` 的数据库与 `settings.json`（保留 2 份）
- **更新状态入口**：设置中心「关于与更新」页与状态栏更新徽标
- **安全边界**：更新包未签名，只校验 `latest.yml` 的 SHA512；首次自动更新为全量，之后走 blockmap 差量
- 沿用 0.2.0 的反思经验库、澄清偏好采集、上下文压缩信号与自进化设置页

## 许可

[MIT](https://github.com/gyhgyhgyhgyh92/DevPrompt-AI/blob/master/LICENSE) License。
