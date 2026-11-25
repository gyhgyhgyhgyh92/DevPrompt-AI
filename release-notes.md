# DevPrompt AI v0.2.0

把一句模糊需求，变成带行号与 token 出处、可被 ripgrep 反向验证的工程级提示词。

## 安装包

| 平台 | 产物 | 版本 |
|---|---|---|
| Windows 10+ (x64) | `DevPromptAI-0.2.0-win-x64.exe` | v0.2.0 |
| macOS 11+ (arm64) | `DevPromptAI-0.1.0-mac-arm64.dmg` | v0.1.0 |
| Linux (x86_64) | `DevPromptAI-0.1.0-linux-x86_64.AppImage` | v0.1.0 |

本次仅重新构建并发布 Windows 包；macOS / Linux 沿用 v0.1.0 的安装包，功能与本版 Windows 包存在差异。

桌面端与 Web 形态共用同一份业务逻辑与 `~/.devprompt-ai` 数据，可交替使用。

## 未签名说明

项目未购买代码签名证书：

- **Windows**：首次运行可能见 SmartScreen「未知发布商」，点「更多信息 → 仍要运行」。
- **macOS**：`.dmg` 未签名未公证，首次打开需在「系统设置 → 隐私与安全性」中点「仍要打开」。

这属信誉警告而非病毒判定。

## 本次包含

- **反思经验库**：接入 agentmemory，生成前注入历史经验，跨会话复用已验证的方案
- **澄清偏好采集**：回答归类为选项 / 多选 / 默认 / 自由输入并记账，不记录答案原文
- **上下文压缩信号**：压缩决策接入缓存命中率与上下文压力
- **设置中心「自进化」页**：新增经验库配置与侧车连通状态
- **反思离线度量**：指标聚合模块 + 批量跑批脚本，可量化字段完整率与重复自省率
- 沿用 v0.1.0 打包链路（electron-builder），版本号唯一来源 `pyproject.toml`

## 许可

[MIT](https://github.com/gyhgyhgyhgyh92/DevPrompt-AI/blob/master/LICENSE) License。
