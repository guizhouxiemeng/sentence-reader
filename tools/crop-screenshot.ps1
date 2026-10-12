<#
  crop-screenshot.ps1 —— 把用户拍的截图裁成商店要求的 1280x800。

  为什么需要处理：
      商店要求截图正好是 1280x800（或 640x400）。
      随手拍的图比例不会正好 —— 用户这张是 2549x1398，比例 1.82，
      而 1280x800 是 1.60。

  【关键：裁，不要拉】
      1.82 -> 1.60 如果直接缩放，画面会横向压扁，字都变形了。
      必须裁掉一部分宽度。

  裁哪里：
      这张图左边是 ACM 网站自己的导航栏（Introduction / Vision And ... 那一列），
      信息价值最低；右边是讲解卡片，是重点。
      所以【主要从左边裁】，右边只裁一点点。

  用法：
      powershell -File tools/crop-screenshot.ps1 -In <原图> -Out <输出>
#>
param(
  [Parameter(Mandatory=$true)][string]$In,
  [Parameter(Mandatory=$true)][string]$Out,
  [int]$TargetW = 1280,
  [int]$TargetH = 800,
  # 裁剪量里分给左边的比例。1.0 = 全从左边裁。
  #  第一版用了 0.83，结果右边把"导出讲解"按钮切掉了一角 ——
  #  右边是讲解卡片，信息密度最高，不该动它。
  [double]$LeftBias = 1.0
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

if (-not (Test-Path $In)) { Write-Host "  找不到原图: $In"; exit 1 }

$src = [System.Drawing.Image]::FromFile((Resolve-Path $In))
$sw = $src.Width; $sh = $src.Height
$ratio = $TargetW / $TargetH

Write-Host ("  原图      {0}x{1}  比例 {2:N2}" -f $sw, $sh, ($sw / $sh))
Write-Host ("  目标      {0}x{1}  比例 {2:N2}" -f $TargetW, $TargetH, $ratio)

# 算出裁剪框：尽量保留高度，从宽度上裁
$cropH = $sh
$cropW = [int][math]::Round($cropH * $ratio)
if ($cropW -gt $sw) {
  # 宽度不够，改成从高度上裁（这张图不会走到这里，但别的图可能会）
  $cropW = $sw
  $cropH = [int][math]::Round($cropW / $ratio)
}

$cut = $sw - $cropW
# 默认全从左边裁：左边是网站自己的导航栏，价值最低；
#  右边是讲解卡片，信息密度最高，不该动。
$cutLeft = [int][math]::Round($cut * $LeftBias)
$cutRight = $cut - $cutLeft

Write-Host ("  裁剪      去掉左边 {0}px，右边 {1}px  ->  {2}x{3}" -f $cutLeft, $cutRight, $cropW, $cropH)

$dst = New-Object System.Drawing.Bitmap($TargetW, $TargetH)
$g = [System.Drawing.Graphics]::FromImage($dst)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality

$srcRect = New-Object System.Drawing.Rectangle($cutLeft, 0, $cropW, $cropH)
$dstRect = New-Object System.Drawing.Rectangle(0, 0, $TargetW, $TargetH)
$g.DrawImage($src, $dstRect, $srcRect, [System.Drawing.GraphicsUnit]::Pixel)

$g.Dispose()
$outPath = if ([System.IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path (Split-Path -Parent $PSScriptRoot) $Out }
$dst.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
$dst.Dispose()
$src.Dispose()

$fi = Get-Item $outPath
Write-Host ("  已生成    {0}  {1}x{2}  {3:N1} KB" -f $outPath, $TargetW, $TargetH, ($fi.Length / 1KB))
