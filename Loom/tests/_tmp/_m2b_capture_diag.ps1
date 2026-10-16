# _m2b_capture_diag.ps1 — 诊断: 全屏截图 + 前台窗口 + Z 序 (只读, 不改任何脚本/窗口设置)
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class DiagW {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern int GetWindowTextW(IntPtr h, System.Text.StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassNameW(IntPtr h, System.Text.StringBuilder s, int n);
}
'@
[void][DiagW]::SetProcessDPIAware()

$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen(0, 0, 0, 0, (New-Object System.Drawing.Size($b.Width, $b.Height)))
$out = Join-Path (Split-Path -Parent $PSCommandPath) '_m2b_fullscreen.png'
$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ("FULLSCREEN {0}x{1} -> {2}" -f $b.Width, $b.Height, $out)

$h = [DiagW]::GetForegroundWindow()
$sb = New-Object System.Text.StringBuilder 256; [void][DiagW]::GetWindowTextW($h, $sb, 256)
$sc = New-Object System.Text.StringBuilder 256; [void][DiagW]::GetClassNameW($h, $sc, 256)
Write-Output ("FG hwnd={0} class={1} title={2}" -f $h, $sc.ToString(), $sb.ToString())

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$tops = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
  [System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
$i = 0
foreach ($w in $tops) {
  $i++; if ($i -gt 12) { break }
  try {
    $r = $w.Current.BoundingRectangle
    Write-Output ("Z{0,2} cls={1,-26} off={2,-5} rect={3},{4},{5}x{6} name=[{7}]" -f `
      $i, $w.Current.ClassName, $w.Current.IsOffscreen, [int]$r.X, [int]$r.Y,
      [int]$r.Width, [int]$r.Height, ($w.Current.Name -replace '\s+', ' '))
  } catch { Write-Output ("Z{0} <err>" -f $i) }
}
