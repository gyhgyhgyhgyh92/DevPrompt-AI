<#
.SYNOPSIS
  打包桌面端 Python sidecar（PyInstaller one-dir）并收集 rg.exe / ctags.exe。

.DESCRIPTION
  两步：
  1. uv run pyinstaller 打 desktop/pyinstaller/sidecar.spec
     → desktop/dist/sidecar-dist/devprompt-ai-desktop/（exe + _internal/）
  2. 收集 rg.exe / ctags.exe → desktop/dist/sidecar-dist/tools/
     安装后由 Electron 主进程经 DPROMPT_RG_PATH / DPROMPT_CTAGS_PATH 注入 sidecar
     环境，命中 common/process.py 解析链第 2 级，零业务改动。

  二进制收集顺序（与 common/process.py 的解析链对齐）：
  PATH → WinGet Links → WorkBuddy 内置 vendor → DPROMPT_<NAME>_PATH 环境变量。
  都没有则明确报错——缺 rg 的安装包检索直接不可用，比构建失败更难排查。

  二进制产物一律不进 git（MUST-23）；desktop/dist/ 已在 .gitignore。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..' '..')).Path
$distPath = Join-Path $repoRoot 'desktop\dist\sidecar-dist'
$toolsDir = Join-Path $distPath 'tools'

# ---- 1. PyInstaller 打包 ------------------------------------------------------
Write-Host '==> [1/2] PyInstaller 打包 sidecar（one-dir）'
Push-Location $repoRoot
try {
  uv run pyinstaller --noconfirm --clean `
    --distpath $distPath `
    --workpath (Join-Path $repoRoot '.tmp\pyinstaller-work') `
    'desktop\pyinstaller\sidecar.spec'
} finally {
  Pop-Location
}

$sidecarExe = Join-Path $distPath 'devprompt-ai-desktop\devprompt-ai-desktop.exe'
if (-not (Test-Path $sidecarExe)) {
  Write-Error "PyInstaller 产物缺失：$sidecarExe"
}

# ---- 2. 收集 rg / ctags -------------------------------------------------------
function Resolve-Tool([string]$name) {
  $exe = "$name.exe"
  # ① PATH
  $cmd = Get-Command $exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  # ② WinGet Links
  $wingetLink = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\$exe"
  if (Test-Path $wingetLink) { return $wingetLink }
  # ③ WorkBuddy 内置 vendor（本开发机实测位置；其他构建机通常走①②）
  $wbRoot = Join-Path $env:LOCALAPPDATA 'Programs\WorkBuddy'
  if (Test-Path $wbRoot) {
    $hit = Get-ChildItem $wbRoot -Filter $exe -Recurse -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }
  # ④ 显式环境变量
  $envPath = [Environment]::GetEnvironmentVariable("DPROMPT_$($name.ToUpper())_PATH")
  if ($envPath -and (Test-Path $envPath)) { return $envPath }
  return $null
}

Write-Host '==> [2/2] 收集检索工具（rg / ctags）'
New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
$installHints = @{ rg = 'BurntSushi.ripgrep.MSVC'; ctags = 'UniversalCtags.Ctags' }
foreach ($tool in 'rg', 'ctags') {
  $src = Resolve-Tool $tool
  if (-not $src) {
    Write-Error @"
未找到 $tool.exe。安装包必须随附检索工具，否则桌面端符号表检索不可用。
安装：winget install $($installHints[$tool])
或设置 DPROMPT_$($tool.ToUpper())_PATH 指向完整路径后重跑本脚本。
"@
  }
  Copy-Item $src (Join-Path $toolsDir "$tool.exe") -Force
  Write-Host "  收集 $tool <- $src"
}

$sizeMb = [math]::Round((Get-ChildItem $distPath -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "==> sidecar 就绪：$distPath（约 $sizeMb MB）"
