"""系统原生文件夹选择器（「选择文件夹（本地）」I/O 实现，POST /project/pick）。

经 common.process.run_command 唯一子进程通道（MUST-13）；
Windows 经 PowerShell 7（pwsh）调用 Windows Forms FolderBrowserDialog——需 STA
线程（pwsh -STA）；用户取消输出空串。超时 300s：用户驱动模态交互，长于默认
10s（MUST-13 显式设值）。非 Windows 抛 DevPromptError（9001，明确文案）。
"""

from __future__ import annotations

import os

from devprompt_ai.common.process import run_command
from devprompt_ai.domain.errors import DevPromptError

PICK_DIALOG_TIMEOUT = 300.0
"""系统对话框等待超时（秒）：用户驱动模态，显式放宽；超时由 run_command 杀进程。"""

# 单 argv 传参（create_subprocess_exec 无 shell）：脚本内只用单引号，避免引号转义歧义
_PS_SCRIPT = (
    "Add-Type -AssemblyName System.Windows.Forms; "
    "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
    "$d.Description = '选择项目文件夹（本地）'; $d.UseDescriptionForTitle = $true; "
    "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
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
