# DevPrompt AI 原生文件夹选择器扩展

把启动页「选择文件夹（本地）」接到 **Windows 原生文件夹选择对话框**。

## 为什么需要扩展

浏览器的文件选择 API **刻意不暴露绝对路径**：

- `showDirectoryPicker()` 只返回 `dirHandle`——"For security reasons the full path
  will not be revealed"；
- `<input type="file" webkitdirectory>` 只给 `webkitRelativePath`（单文件给
  `C:\fakepath\...`）。

而本项目的 `GET /project/scan` 需要**绝对路径**去服务端扫描符号表，所以纯前端方案
不可行。唯一可行链路是：

```
页面 ──postMessage──▶ content script ──sendMessage──▶ service worker
                                                        │ sendNativeMessage
                                                        ▼
                                        devprompt-ai-pick-folder.exe
                                        （stdio：4 字节小端长度 + JSON）
                                                        │ FolderBrowserDialog
                                                        ▼
                                              Windows 原生对话框
```

> Chrome 官方文档明确：`sendNativeMessage` / `connectNative` **在 content script 中
> 不可用**，只能用于扩展页与 service worker，故必须经 service worker 转发一跳。

## 安装

```powershell
# 1) 生成 host 可执行文件（若尚未生成）
cd "D:\Works\DevPrompt AI"; uv sync

# 2) 写入 host manifest + Chrome/Edge 注册表（幂等，可重复执行）
pwsh -File scripts/install_native_picker.ps1
```

第 2 步会打印扩展 ID，并提示**唯一需要人工操作的一步**（浏览器不允许程序自动安装扩展）：

1. 打开 `chrome://extensions`（Edge 用 `edge://extensions`）
2. 右上角开启「开发者模式」
3. 点「加载已解压的扩展程序」，选择本目录（`browser-extension/`）

## `manifest.json` 的 `key` 字段

`key` 是扩展的 **RSA 公钥**（base64 DER），用于**固定扩展 ID**——否则「加载已解压」的
ID 会随目录路径变化，安装脚本就无法把 `allowed_origins` 预写进 host manifest。

生成方式：

```powershell
openssl genrsa -out pick_folder.pem 2048
openssl rsa -in pick_folder.pem -pubout -outform DER | openssl base64 -A
# 把输出填入 manifest.json 的 key；私钥只留本地，不要提交
```

扩展 ID 的算法（安装脚本已实现）：公钥 DER 的 SHA256 前 16 字节，每字节映射到 `a`–`p`。

## 卸载

```powershell
pwsh -File scripts/uninstall_native_picker.ps1
```

扩展本身需在扩展页手动移除。

## 已知边界

- **仅 Chromium 系**（Chrome / Edge / Brave 等）可用；Firefox 的 host 注册表位置与
  `allowed_origins` 形态不同，本方案未适配。
- 弹出的对话框是 **OS 窗口**（桌面级），会脱离浏览器视口——这是原生对话框的固有形态。
- 未装扩展 / 非 Chromium 浏览器时，前端给出明确文案提示，**没有回退入口**（页内资源
  管理器已按用户裁定下线）。
