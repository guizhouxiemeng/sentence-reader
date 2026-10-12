﻿<#
  test-fresh.ps1 —— 用一个全新的浏览器配置启动，复现"新用户第一次装上"的状态。

  为什么需要：
      引导条只在"后端不可用"时出现。而自己的浏览器早就开好了内置模型的开关，
      所以看不到那个状态 —— 一个人不好测。

      这个脚本建一个临时配置目录（干净、没开过任何 flag），
      把扩展以"未打包扩展"的方式加载进去，于是得到真实的首次体验。

  不会碰你原来的浏览器配置。删掉那个临时目录就等于没发生过。

  用法：
      pwsh -File tools/test-fresh.ps1            默认 Edge
      pwsh -File tools/test-fresh.ps1 -Chrome    改用 Chrome
      pwsh -File tools/test-fresh.ps1 -Reset     先删掉上次的临时配置，从头再来
#>
param(
  [switch]$Chrome,
  [switch]$Reset
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$ext = Join-Path $root 'plugin'

if (-not (Test-Path (Join-Path $ext 'manifest.json'))) {
  Write-Host "  找不到扩展目录: $ext" -ForegroundColor Red
  exit 1
}

$profileDir = Join-Path $env:TEMP 'dsh-reading-fresh-profile'
if ($Reset -and (Test-Path $profileDir)) {
  Remove-Item $profileDir -Recurse -Force -ErrorAction SilentlyContinue
  Write-Host '  已清掉上次的临时配置' -ForegroundColor DarkGray
}
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

# ---- 找一个可用的浏览器 ----
# 注意：$env:ProgramFiles(x86) 里带括号，用 ${} 包起来才不会解析出错
$pf = $env:ProgramFiles
$pf86 = ${env:ProgramFiles(x86)}
$lad = $env:LOCALAPPDATA

if ($Chrome) {
  $cands = @(
    (Join-Path $pf 'Google\Chrome\Application\chrome.exe'),
    (Join-Path $pf86 'Google\Chrome\Application\chrome.exe'),
    (Join-Path $lad 'Google\Chrome\Application\chrome.exe')
  )
} else {
  $cands = @(
    (Join-Path $pf86 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $pf 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $lad 'Microsoft\Edge\Application\msedge.exe')
  )
}

$browser = $null
foreach ($c in $cands) {
  if ($c -and (Test-Path $c)) { $browser = $c; break }
}

if (-not $browser) {
  Write-Host '  没找到浏览器。试过这些位置:' -ForegroundColor Red
  foreach ($c in $cands) { Write-Host "    $c" -ForegroundColor DarkGray }
  exit 1
}

# ---- 组装启动参数 ----
# 变量名不要用 $args —— 那是 PowerShell 的自动变量，赋值会报错
$launchArgs = @(
  ('--user-data-dir="{0}"' -f $profileDir),
  '--no-first-run',
  '--no-default-browser-check',
  ('--load-extension="{0}"' -f $ext),
  '--new-window',
  'about:blank'
)

$line = '=' * 70
Write-Host ''
Write-Host $line -ForegroundColor Cyan
Write-Host ' 干净配置测试' -ForegroundColor Cyan
Write-Host $line -ForegroundColor Cyan
Write-Host ''
Write-Host "  浏览器    $browser"
Write-Host "  配置目录  $profileDir"
Write-Host "  扩展目录  $ext"
Write-Host ''
Write-Host ' 这个配置是全新的 —— 没开过任何 flag，正是审核员和新用户的状态。'
Write-Host ''
Write-Host ' 请检查这几项:' -ForegroundColor Yellow
Write-Host '   1. 工具栏上有没有图标（不是灰色拼图）'
Write-Host '   2. 点图标 -> 侧栏出现的是【引导条】，而不是一句报错'
Write-Host '   3. 点【怎么做】-> 出现开启内置模型的步骤'
Write-Host '   4. 点【打开 API 设置】-> 看到「后端状态: 还不行 …」'
Write-Host '   5. 切到某个云端后端、随便填个 key 保存'
Write-Host '      -> 状态变成「可以用」，引导条消失'
Write-Host '   6. 再把 key 清空保存'
Write-Host '      -> 引导条重新出现，这次说的是要填 key'
Write-Host ''
Write-Host ' 如果图标没出现（新版浏览器可能忽略 --load-extension）:' -ForegroundColor Yellow
Write-Host '   在这个新窗口里打开 edge://extensions（Chrome 用 chrome://extensions）'
Write-Host '   打开「开发人员模式」->「加载解压缩的扩展」-> 选这个目录:'
Write-Host "     $ext" -ForegroundColor White
Write-Host ''
Write-Host ' 测完直接关掉窗口即可。想彻底清掉临时配置:'
Write-Host '   pwsh -File tools/test-fresh.ps1 -Reset'
Write-Host ''

Start-Process -FilePath $browser -ArgumentList $launchArgs
