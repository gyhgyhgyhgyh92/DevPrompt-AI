"""系统原生文件夹选择器的 I/O 实现（供 native messaging host 调用）。

经 common.process.run_command 唯一子进程通道（MUST-13）；
Windows 经 PowerShell 7（pwsh）调用 Windows Forms FolderBrowserDialog——需 STA
线程（pwsh -STA）；用户取消输出空串。超时 300s：用户驱动模态交互，长于默认
10s（MUST-13 显式设值）。非 Windows 抛 DevPromptError（9001，明确文案）。

2026-10-13 曾作为 `POST /project/pick` 的后端实现，同日按用户裁定删除（对话卡记录 f949121）；
2026-10-19 按用户新裁定以**浏览器扩展 + native messaging** 方式重新
引入（见 native_host.py），本模块不再绑定任何 HTTP 路由。
"""

from __future__ import annotations

import os

from devprompt_ai.common.process import run_command
from devprompt_ai.domain.errors import DevPromptError

PICK_DIALOG_TIMEOUT = 300.0
"""系统对话框等待超时（秒）：用户驱动模态，显式放宽；超时由 run_command 杀进程。"""

# 单 argv 传参（create_subprocess_exec 无 shell）：脚本内只用单引号，避免引号转义歧义
# 置顶机制：uvicorn 为无窗口后台进程，Windows 前台锁定（ForegroundLockTimeout）拦截其
# 子进程的窗口激活——对话框会藏在浏览器等其他窗口后面，用户误以为失败（真实用户实测
# 暴露）。以隐藏的 TopMost owner 承载模态对话框（owned 窗口随 owner 处于顶层 band），
# 强制其显示在最前，无需依赖激活权限。
# stdout 编码：pwsh 的 [Console]::OutputEncoding 跟随 console 代码页——有 console 时为
# UTF-8，而 Chrome（GUI 进程）拉起本宿主时**没有 console**，退化为系统代码页 936，中文路径
# 经 run_command 的 UTF-8 解码变成 U+FFFD（用户实测：D:\前端作业 → 乱码）。故显式指定。
_UTF8_STDOUT = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
_PS_SCRIPT = (
    _UTF8_STDOUT + "Add-Type -AssemblyName System.Windows.Forms; "
    "$owner = New-Object System.Windows.Forms.Form; "
    "$owner.FormBorderStyle = 'None'; $owner.ShowInTaskbar = $false; "
    "$owner.TopMost = $true; $owner.Opacity = 0; $owner.Size = '1,1'; "
    "$owner.StartPosition = 'Manual'; $owner.Location = '-10000,-10000'; "
    "$owner.Show(); "
    "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
    "$d.Description = '选择项目文件夹（本地）'; $d.UseDescriptionForTitle = $true; "
    "if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) "
    "{ [Console]::Out.Write($d.SelectedPath) }"
)


async def pick_folder_dialog() -> str:
    """弹系统原生目录选择器：返回所选绝对路径；用户取消返回空串。

    非 Windows 平台当前不支持（架构定位 Windows 本地工具），抛明确文案而非静默。
    """
    if os.name != "nt":
        raise DevPromptError("系统文件夹选择器当前仅支持 Windows", code=9001)
    out = await run_command(
        ["pwsh", "-NoProfile", "-STA", "-Command", _PS_SCRIPT],
        timeout=PICK_DIALOG_TIMEOUT,
    )
    return out.strip()
