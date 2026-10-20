<#
.SYNOPSIS
  安装 DevPrompt AI 原生文件夹选择器扩展的 native messaging host。

.DESCRIPTION
  做三件事（可重复执行，幂等）：
  1. 校验 venv 里的 devprompt-ai-pick-folder.exe 存在（不存在则提示先跑 uv sync）；
  2. 用 browser-extension/manifest.json 的 key（RSA 公钥）算出固定的扩展 ID，
     生成 host manifest（allowed_origins 只放这个 ID）；
  3. 写 Chrome 与 Edge 两处 HKCU 注册表。

  浏览器不允许程序自动装扩展，故最后打印一步人工操作。

.EXAMPLE
  pwsh -File scripts/install_native_picker.ps1
#>
[CmdletBinding()]
param(
  # 扩展目录（相对仓库根或绝对路径）
  [string]$ExtensionDir = (Join-Path $PSScriptRoot '..' 'browser-extension'),
  # 项目根（用于定位 .venv 与 host manifest 输出位置）
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
  # 直接指定扩展 ID（从 chrome://extensions 复制）。不传则由 manifest 的 key 推算（参数名不能与内部变量同名，PowerShell 变量大小写不敏感）。
  [string]$PinnedExtensionId = ''
)

$ErrorActionPreference = 'Stop'

# ---- 1. 前置校验：host 可执行文件必须已由 uv sync 生成 --------------------------
$venvScripts = Join-Path $ProjectRoot '.venv\Scripts'
$hostExe = Join-Path $venvScripts 'devprompt-ai-pick-folder.exe'
if (-not (Test-Path $hostExe)) {
  Write-Error @"
未找到 host 可执行文件：
  $hostExe

它由 pyproject 的 [project.scripts] 生成，请先执行：
  cd '$ProjectRoot'
  uv sync
（若提示无法替换 devprompt-ai.exe，说明本地服务还在运行，请先停掉它再重跑。）
"@
}

# ---- 2. 从 manifest 的 key 算扩展 ID -----------------------------------------
$manifestPath = Join-Path $ExtensionDir 'manifest.json'
if (-not (Test-Path $manifestPath)) { Write-Error "未找到扩展 manifest：$manifestPath" }
$manifest = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

$key = $manifest.key
if (-not $ExtensionId -and (-not $key -or $key -eq 'REPLACE_WITH_PUBLIC_KEY')) {
  Write-Error @"
manifest.json 的 key 尚未填入真实公钥（当前值：'$key'）。

扩展 ID 必须稳定，否则 host manifest 的 allowed_origins 无法预写。生成方式：
  1) openssl genrsa -out pick_folder.pem 2048
  2) openssl rsa -in pick_folder.pem -pubout -outform DER | openssl base64 -A
  3) 把输出填入 manifest.json 的 key 字段（公钥，可公开；私钥只留本地不提交）
"@
}

# Chrome 扩展 ID 算法：DER 公钥的 SHA256 前 16 字节，每字节映射到 'a'..'p'
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
  $der = [Convert]::FromBase64String($key)
  $hash = $sha.ComputeHash($der)
} finally {
  $sha.Dispose()
}
$alphabet = 'abcdefghijklmnop'
$idBuilder = New-Object System.Text.StringBuilder
for ($i = 0; $i -lt 16; $i++) {
  [void]$idBuilder.Append($alphabet[$hash[$i] -band 0x0F])
}
$derivedId = $idBuilder.ToString()
# 显式指定以它为准：浏览器里实际加载的 ID 才算数
if ($PinnedExtensionId -ne '') {
  $extensionId = $PinnedExtensionId
  Write-Host "扩展 ID：$extensionId（参数指定）"
} else {
  $extensionId = $derivedId
  Write-Host "扩展 ID：$extensionId（由 manifest 的 key 推算）"
}

# ---- 3. 生成 host manifest ----------------------------------------------------
$hostManifestDir = Join-Path $ProjectRoot 'browser-extension'
$hostManifestPath = Join-Path $hostManifestDir 'native_host_manifest.json'
$hostManifest = [ordered]@{
  name                 = 'devprompt_ai.pick_folder'
  description          = 'DevPrompt AI native folder picker (system folder browser dialog)'
  path                 = $hostExe
  type                 = 'stdio'
  allowed_origins      = @("chrome-extension://$extensionId/")
}
$hostManifest | ConvertTo-Json -Depth 5 | Out-File -FilePath $hostManifestPath -Encoding utf8
Write-Host "已写 host manifest：$hostManifestPath"

# ---- 4. 写注册表（Chrome + Edge，HKCU，无需管理员）-----------------------------
foreach ($vendor in @(
    @{ Name = 'Google\Chrome'; Path = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\devprompt_ai.pick_folder" },
    @{ Name = 'Microsoft\Edge'; Path = "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\devprompt_ai.pick_folder" }
  )) {
  if (-not (Test-Path $vendor.Path)) { New-Item -Path $vendor.Path -Force | Out-Null }
  Set-Item -Path $vendor.Path -Value $hostManifestPath
  Write-Host "已注册 $($vendor.Name)"
}

# ---- 5. 人工步骤：浏览器不允许程序自动安装扩展 --------------------------------
Write-Host ''
Write-Host '下一步（需人工操作一次）：'
Write-Host '  1) Chrome/Edge 打开 chrome://extensions（或 edge://extensions）'
Write-Host '  2) 右上角开启「开发者模式」'
Write-Host "  3) 点「加载已解压的扩展程序」，选择目录：$ExtensionDir"
Write-Host '  4) 回到应用点「选择文件夹（本地）」即可弹出系统原生对话框'
Write-Host ''
Write-Host "[重要] 打开 chrome://extensions 确认该扩展的 ID 是否为：$extensionId"
Write-Host '       若不是（比如曾在 key 字段有效之前加载过，Chrome 会按目录路径派生旧 ID）：'
Write-Host '       先「移除」扩展，再重新「加载已解压的扩展程序」。'
Write-Host ''
Write-Host '卸载：pwsh -File scripts/uninstall_native_picker.ps1'
