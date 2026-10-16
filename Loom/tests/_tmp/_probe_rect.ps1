# _probe_rect.ps1 - 一次性探针: 定位性能页左侧导航列表项的真实屏幕矩形 (判断比例坐标是否命中)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public class RcWin32 {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; } }
'@
[RcWin32]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 300

$p = Get-Process Taskmgr | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
[RcWin32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 700
$r = New-Object 'RcWin32+R'; [RcWin32]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$W = $r.Rr - $r.L; $H = $r.B - $r.T
Write-Output ("WIN $($r.L),$($r.T) ${W}x${H}")
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)

$rt = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
  (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'resourceTitle')))
Write-Output ("resourceTitle=[" + $(if ($rt) { $rt.Current.Name } else { 'NONE' }) + "]")

# 所有带 AutomationId 的元素 + 屏幕矩形 (转成窗口相对比例)
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
Write-Output "--- 带 id 的元素 (窗口相对比例) ---"
foreach ($e in $all) {
  $aid = ''; $nm = ''
  try { $aid = $e.Current.AutomationId; $nm = $e.Current.Name } catch {}
  if ($aid -eq '') { continue }
  $br = $e.Current.BoundingRectangle
  $x = [double]$br.X; $y = [double]$br.Y; $w = [double]$br.Width; $h = [double]$br.Height
  if ([double]::IsInfinity($x) -or [double]::IsNaN($x)) { continue }
  $fx = if ($W -gt 0) { [Math]::Round(($x + $w / 2 - $r.L) / $W, 3) } else { 0 }
  $fy = if ($H -gt 0) { [Math]::Round(($y + $h / 2 - $r.T) / $H, 3) } else { 0 }
  Write-Output ("  id=[$aid] name=[$nm] rect=$([int]$x),$([int]$y),$([int]$w)x$([int]$h) rel=($fx,$fy)")
}
Write-Output '--- 左侧列表区域内的 Pane (可能是列表项) ---'
foreach ($e in $all) {
  $br = $e.Current.BoundingRectangle
  $x = [double]$br.X
  if ([double]::IsInfinity($x) -or [double]::IsNaN($x)) { continue }
  $relx = ($x - $r.L) / $W
  if ($relx -ge 0 -and $relx -le 0.25 -and $br.Width -gt 60) {
    $aid=''; $nm=''; $ct=''
    try { $aid = $e.Current.AutomationId; $nm = $e.Current.Name; $ct = $e.Current.ControlType.ProgrammaticName } catch {}
    $fy = [Math]::Round(($br.Y + $br.Height / 2 - $r.T) / $H, 3)
    Write-Output ("  $ct id=[$aid] name=[$nm] rect=$([int]$br.X),$([int]$br.Y),$([int]$br.Width)x$([int]$br.Height) relY=$fy")
  }
}
Write-Output 'PROBE-RECT done'
