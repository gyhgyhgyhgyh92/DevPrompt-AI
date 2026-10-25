<#
.SYNOPSIS
  冒烟测试打包后的 sidecar 可执行文件（模拟安装态环境变量）。

.DESCRIPTION
  跑 desktop/dist/sidecar-dist/devprompt-ai-desktop/devprompt-ai-desktop.exe：
  1. 按安装态注入 DEVPROMPT_FRONTEND_DIST / DPROMPT_RG_PATH / DPROMPT_CTAGS_PATH；
  2. 等 stdout 出现 DPROMPT_READY 行（30s 超时）；
  3. 打 /api/v1/health，断言 is_healthy 且 rg/ctags/llm_config 三项 ok；
  4. 杀进程树，退出码非零即失败。

  这是 PyInstaller 产物的守门测试：hidden imports 漏一个只会在运行时崩，
  构建成功不代表能跑（MUST-02 输出验证）。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..' '..')).Path
$exe = Join-Path $repoRoot 'desktop\dist\sidecar-dist\devprompt-ai-desktop\devprompt-ai-desktop.exe'
if (-not (Test-Path $exe)) {
  Write-Error "sidecar 可执行文件不存在：$exe（先跑 desktop/scripts/build-sidecar.ps1）"
}

# 安装态由 Electron 主进程注入这三个变量（Start-Process 无 -Env 参数，
# 用进程级环境变量传递，子进程继承——与主进程 spawn 的机制一致）
$env:DEVPROMPT_FRONTEND_DIST = Join-Path $repoRoot 'frontend\dist'
$env:DPROMPT_RG_PATH = Join-Path $repoRoot 'desktop\dist\sidecar-dist\tools\rg.exe'
$env:DPROMPT_CTAGS_PATH = Join-Path $repoRoot 'desktop\dist\sidecar-dist\tools\ctags.exe'

$stamp = Get-Random
$outLog = Join-Path $env:TEMP "sidecar-smoke-$stamp.log"
$errLog = "$outLog.err"

Write-Host "==> 启动 sidecar：$exe"
$proc = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden `
  -RedirectStandardOutput $outLog -RedirectStandardError $errLog

$port = $null
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  if (Test-Path $outLog) {
    $line = Get-Content $outLog -ErrorAction SilentlyContinue |
      Where-Object { $_ -like 'DPROMPT_READY*' } | Select-Object -First 1
    if ($line) { $port = ($line -split ' ', 2)[1] | ConvertFrom-Json | ForEach-Object { $_.port }; break }
  }
  if ($proc.HasExited) { break }
}

try {
  if ($null -eq $port) {
    Write-Host '--- stderr ---'
    if (Test-Path $errLog) { Get-Content $errLog | Select-Object -Last 25 }
    Write-Error '未收到 DPROMPT_READY 行（30s 超时或进程提前退出）'
  }
  Write-Host "==> ready，端口 $port"

  $health = (Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/v1/health" -UseBasicParsing -TimeoutSec 15).Content |
    ConvertFrom-Json
  if (-not $health.data.is_healthy) { Write-Error "is_healthy=false：$($health | ConvertTo-Json -Compress)" }
  foreach ($name in 'rg', 'ctags', 'llm_config') {
    $check = $health.data.checks | Where-Object { $_.name -eq $name }
    if (-not $check -or -not $check.ok) { Write-Error "health 检查项 $name 未通过" }
    Write-Host "  $name ok: $($check.detail)"
  }

  $root = Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 15
  if ($root.StatusCode -ne 200) { Write-Error "前端托管失败：HTTP $($root.StatusCode)" }
  Write-Host '  前端 dist 托管 ok'

  # stdout 必须只有协议行：主进程按行解析，混入任何输出都会破坏协议
  # @() 强制数组：单行时 Get-Content 返回标量字符串，[0] 会取到字符而非行
  $stdoutLines = @(Get-Content $outLog | Where-Object { $_.Trim() -ne '' })
  if ($stdoutLines.Count -ne 1 -or -not $stdoutLines[0].StartsWith('DPROMPT_READY')) {
    Write-Error "stdout 被污染（应只有一行 ready 协议）：$($stdoutLines -join ' | ')"
  }
  Write-Host '  stdout 协议纯净 ok'

  Write-Host '==> sidecar 冒烟通过'
} finally {
  Remove-Item Env:DEVPROMPT_FRONTEND_DIST -ErrorAction SilentlyContinue
  Remove-Item Env:DPROMPT_RG_PATH -ErrorAction SilentlyContinue
  Remove-Item Env:DPROMPT_CTAGS_PATH -ErrorAction SilentlyContinue
  if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    if (-not $proc.HasExited) {
      & taskkill /pid $proc.Id /T /F 2>$null | Out-Null
    }
  }
}
