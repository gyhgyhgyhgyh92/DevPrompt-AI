<#
.SYNOPSIS
  卸载 DevPrompt AI 原生文件夹选择器扩展的 native messaging host 注册。

.DESCRIPTION
  删除 Chrome / Edge 两处 HKCU 注册表项与生成的 host manifest。
  **不会**删除扩展本身（扩展由浏览器管理，需在扩展页手动移除）。
#>
[CmdletBinding()]
param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'

foreach ($path in @(
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts\devprompt_ai.pick_folder",
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\devprompt_ai.pick_folder"
  )) {
  if (Test-Path $path) {
    Remove-Item -Path $path -Recurse -Force
    Write-Host "已删除注册表项：$path"
  } else {
    Write-Host "跳过（不存在）：$path"
  }
}

$hostManifest = Join-Path $ProjectRoot 'browser-extension\native_host_manifest.json'
if (Test-Path $hostManifest) {
  Remove-Item $hostManifest -Force
  Write-Host "已删除：$hostManifest"
}

Write-Host ''
Write-Host '如需彻底移除扩展：浏览器扩展页 → 移除「DevPrompt AI 原生文件夹选择器」。'
