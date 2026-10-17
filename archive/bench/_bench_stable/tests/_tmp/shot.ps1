param([string]$Out = "C:\Users\Administrator\Desktop\loom_shot.png")
# 全屏截图 (GUI 自动化辅助, 2026-08-20): 用法  powershell -File shot.ps1 -Out <png路径>
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved: $Out ($($b.Width)x$($b.Height))"
