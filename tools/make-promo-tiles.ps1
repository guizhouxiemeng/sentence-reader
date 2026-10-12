<#
  make-promo-tiles.ps1 —— 生成商店的两块宣传图。

  为什么用 PowerShell + System.Drawing，而不是像图标那样自己画 PNG：
      图标是纯几何图形，手写像素就够了。
      宣传图上要排中文，得有字体光栅化 —— 那是几百行的事，
      而 Windows 自带 System.Drawing 就能做，没必要重造。

  生成两张：
      store/tile-small-440x280.png      小宣传图（Edge 可选）
      store/tile-large-1400x560.png     大宣传图（Edge 可选）

  配色和扩展界面一致（#0f1115 底），这样放在商店页上不违和。
  文案只放一句 —— 宣传图是缩略图，字多了看不清。
#>

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $root 'store'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$iconPath = Join-Path $root 'plugin\icons\icon128.png'

function New-Tile {
  param(
    [int]$W, [int]$H, [string]$File,
    [int]$IconSize, [int]$IconX, [int]$IconY,
    [single]$TitleSize, [int]$TitleX, [int]$TitleY,
    [single]$SubSize, [int]$SubX, [int]$SubY,
    [string]$Title, [string]$Sub
  )

  $bmp = New-Object System.Drawing.Bitmap($W, $H)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit

  # 底色：和扩展界面一致
  $g.Clear([System.Drawing.Color]::FromArgb(15, 17, 21))

  # 右下角一块极淡的蓝色光晕，让画面不那么平
  $glow = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(16, 91, 141, 239))
  $g.FillEllipse($glow, ($W - [int]($H * 1.1)), ([int](-$H * 0.35)), ([int]($H * 1.1)), ([int]($H * 1.1)))

  # 图标
  if (Test-Path $iconPath) {
    $icon = [System.Drawing.Image]::FromFile($iconPath)
    $g.DrawImage($icon, $IconX, $IconY, $IconSize, $IconSize)
    $icon.Dispose()
  }

  $yahei = 'Microsoft YaHei'

  # 主标题
  $fTitle = New-Object System.Drawing.Font($yahei, $TitleSize, [System.Drawing.FontStyle]::Bold)
  $bTitle = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(230, 232, 238))
  $g.DrawString($Title, $fTitle, $bTitle, $TitleX, $TitleY)

  # 副标题
  $fSub = New-Object System.Drawing.Font($yahei, $SubSize)
  $bSub = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(154, 160, 166))
  $g.DrawString($Sub, $fSub, $bSub, $SubX, $SubY)

  $path = Join-Path $outDir $File
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)

  $fTitle.Dispose(); $bTitle.Dispose(); $fSub.Dispose(); $bSub.Dispose()
  $g.Dispose(); $bmp.Dispose()

  Write-Host ("  {0}  {1}x{2}  {3:N1} KB" -f $File, $W, $H, ((Get-Item $path).Length / 1KB))
}

# ---- 小宣传图 440x280 ----
New-Tile -W 440 -H 280 -File 'tile-small-440x280.png' `
  -IconSize 88 -IconX 36 -IconY 40 `
  -TitleSize 30 -TitleX 36 -TitleY 148 `
  -SubSize 15 -SubX 38 -SubY 198 `
  -Title '按句读' -Sub '读不懂就按一下空格'

# ---- 大宣传图 1400x560 ----
New-Tile -W 1400 -H 560 -File 'tile-large-1400x560.png' `
  -IconSize 168 -IconX 96 -IconY 96 `
  -TitleSize 62 -TitleX 96 -TitleY 296 `
  -SubSize 26 -SubX 100 -SubY 396 `
  -Title '按句读 · 阅读辅助' -Sub '按句高亮，读不懂就按一下空格。术语译名只采用外部查证结果。'

Write-Host ''
Write-Host '  宣传图已生成到 store/'
