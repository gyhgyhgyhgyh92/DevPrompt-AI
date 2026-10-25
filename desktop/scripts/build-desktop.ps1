<#
.SYNOPSIS
  构建 DevPrompt AI 桌面端安装包（Electron 壳 + Python sidecar，Inno Setup 打包）。

.DESCRIPTION
  一次到位：
  1. 前端构建（pnpm build）→ frontend/dist（同一份产物，Web 形态也在用）
  2. 壳编译（tsc -b）→ desktop/dist/*.js
  3. PyInstaller 打 sidecar + 收集 rg/ctags（build-sidecar.ps1）
  4. 组装 staging 目录：
       <stage>\DevPrompt AI.exe        （Electron 运行时重命名）
       <stage>\resources\app\           （壳 package.json + main/preload.js）
       <stage>\resources\frontend-dist\ （前端产物）
       <stage>\resources\sidecar\       （PyInstaller one-dir 产物）
       <stage>\resources\tools\         （rg.exe / ctags.exe）
  5. iscc 编译安装包 → desktop/dist/installer/DevPromptAISetup-<version>.exe

  版本号唯一来源：pyproject.toml 的 version（MUST-24b：不手抄版本号）。
  前置：Inno Setup 已安装（iscc 在 PATH 或常见安装位置）；Electron 二进制已下载
  （desktop/node_modules/electron/dist/electron.exe，pnpm install 时经 npmmirror 下载）。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..' '..')).Path
$desktopDir = Join-Path $repoRoot 'desktop'
$stage = Join-Path $desktopDir 'dist\stage'

# ---- 版本号（唯一来源 pyproject.toml）-----------------------------------------
$versionMatch = Select-String -Path (Join-Path $repoRoot 'pyproject.toml') -Pattern '^version\s*=\s*"([^"]+)"'
if (-not $versionMatch) { Write-Error '无法从 pyproject.toml 读取 version' }
$version = $versionMatch.Matches[0].Groups[1].Value
Write-Host "==> 版本：$version"

# ---- 1. 前端构建 --------------------------------------------------------------
Write-Host '==> [1/5] 前端构建'
pnpm -C (Join-Path $repoRoot 'frontend') build
if ($LASTEXITCODE -ne 0) { Write-Error '前端构建失败' }

# ---- 2. 壳编译 ----------------------------------------------------------------
Write-Host '==> [2/5] 壳编译（tsc）'
pnpm -C $desktopDir build
if ($LASTEXITCODE -ne 0) { Write-Error '壳编译失败' }

# ---- 3. sidecar ---------------------------------------------------------------
Write-Host '==> [3/5] sidecar 打包（PyInstaller + 工具收集）'
& (Join-Path $desktopDir 'scripts\build-sidecar.ps1')

# ---- 4. 组装 staging ----------------------------------------------------------
Write-Host '==> [4/5] 组装 staging'
$electronDist = Join-Path $desktopDir 'node_modules\electron\dist'
if (-not (Test-Path (Join-Path $electronDist 'electron.exe'))) {
  Write-Error "Electron 二进制缺失：$electronDist\electron.exe（先执行 pnpm -C desktop install，需经 npmmirror 下载）"
}
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item (Join-Path $electronDist '*') $stage -Recurse -Force
Rename-Item (Join-Path $stage 'electron.exe') 'DevPrompt AI.exe'

# resources\app：Electron 应用本体（main 指向编译产物）
# 只收编译产物文件：desktop/dist 下同时躺着 stage/ 与 sidecar-dist/ 等构建产物，
# dist\* 通配会把它们一起搬进 app（实测踩坑），故按 *.js / *.js.map 显式收
$appDir = Join-Path $stage 'resources\app'
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
Get-ChildItem (Join-Path $desktopDir 'dist') -File |
  Where-Object { $_.Extension -in '.js', '.js.map' } |
  Copy-Item -Destination $appDir -Force
@{ name = 'devprompt-ai'; main = 'main.js'; version = $version } |
  ConvertTo-Json |
  Out-File (Join-Path $appDir 'package.json') -Encoding utf8

Copy-Item (Join-Path $repoRoot 'frontend\dist') (Join-Path $stage 'resources\frontend-dist') -Recurse -Force
Copy-Item (Join-Path $desktopDir 'dist\sidecar-dist\devprompt-ai-desktop') (Join-Path $stage 'resources\sidecar') -Recurse -Force
Copy-Item (Join-Path $desktopDir 'dist\sidecar-dist\tools') (Join-Path $stage 'resources\tools') -Recurse -Force

# ---- 5. iscc 编译安装包 -------------------------------------------------------
Write-Host '==> [5/5] Inno Setup 编译安装包'
function Resolve-Iscc {
  $cmd = Get-Command iscc -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'),
    'C:\Program Files\Inno Setup 7\ISCC.exe',
    'C:\Program Files (x86)\Inno Setup 7\ISCC.exe',
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }
  Write-Error '未找到 Inno Setup 编译器（iscc）。安装：winget install JRSoftware.InnoSetup，或从 jrsoftware.org 下载安装包手动安装后重试。'
}
$iscc = Resolve-Iscc
Write-Host "  iscc: $iscc"

Push-Location (Join-Path $desktopDir 'installer')
try {
  & $iscc 'devprompt.iss' "/DMyAppVersion=$version"
  if ($LASTEXITCODE -ne 0) { Write-Error "iscc 失败（exit=$LASTEXITCODE）" }
} finally {
  Pop-Location
}

$installer = Join-Path $desktopDir "dist\installer\DevPromptAISetup-$version.exe"
if (-not (Test-Path $installer)) { Write-Error "安装包未生成：$installer" }
$sizeMb = [math]::Round((Get-Item $installer).Length / 1MB, 1)
Write-Host "==> 安装包就绪：$installer（$sizeMb MB）"
