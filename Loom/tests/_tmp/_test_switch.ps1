# _test_switch.ps1 - 用右键菜单把 CPU 图切成"总体利用率", 验证菜单点击坐标并确认视图切换成功
param([int]$MaxRounds = 6)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public class SwWin32 {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; } }
'@
[SwWin32]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 400
$p = Get-Process Taskmgr -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
$rect = New-Object 'SwWin32+R'; [SwWin32]::GetWindowRect($p.MainWindowHandle, [ref]$rect) | Out-Null
$L = [int]$rect.L; $T = [int]$rect.T; $W = [int]($rect.Rr - $L); $H = [int]($rect.B - $T)
Write-Output "SWITCH window=$L,$T ${W}x${H}"

function Get-Root { return [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle) }
function Find-Id($root, [string]$id) {
  return $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $id)))
}
function Get-State {
  $root = Get-Root
  $log = Find-Id $root 'CpuChartTitleLogical'
  $ovr = Find-Id $root 'CpuChartTitle'
  return @{ logical = ($log -ne $null); overall = ($ovr -ne $null) }
}
function Get-Popups {
  $list = @()
  foreach ($w in [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
      [System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
    if ($w.Current.ClassName -eq '#32768') {
      $b = $w.Current.BoundingRectangle
      $list += [pscustomobject]@{ X = [int]$b.X; Y = [int]$b.Y; W = [int]$b.Width; H = [int]$b.Height }
    }
  }
  return $list
}
function Fore { [SwWin32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null; Start-Sleep -Milliseconds 700 }
function LClick([int]$x, [int]$y) {
  [SwWin32]::SetCursorPos($x, $y) | Out-Null; Start-Sleep -Milliseconds 220
  [SwWin32]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero) | Out-Null; Start-Sleep -Milliseconds 80
  [SwWin32]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero) | Out-Null; Start-Sleep -Milliseconds 1300
}
function RClick([int]$x, [int]$y) {
  [SwWin32]::SetCursorPos($x, $y) | Out-Null; Start-Sleep -Milliseconds 300
  [SwWin32]::mouse_event(0x0008, 0, 0, 0, [IntPtr]::Zero) | Out-Null; Start-Sleep -Milliseconds 90
  [SwWin32]::mouse_event(0x0010, 0, 0, 0, [IntPtr]::Zero) | Out-Null; Start-Sleep -Milliseconds 1200
}

$st = Get-State
Write-Output ("start logical=" + $st.logical + " overall=" + $st.overall)
for ($round = 1; $round -le $MaxRounds; $round++) {
  $st = Get-State
  if ($st.overall) { Write-Output "ALREADY OVERALL"; break }
  Write-Output ("ROUND $round : opening menu")
  Fore
  $cx = [int]($L + $W * 0.55); $cy = [int]($T + $H * 0.40)
  RClick $cx $cy
  $pop = Get-Popups
  if ($pop.Count -eq 0) { Write-Output '  no menu'; continue }
  $m = $pop[0]
  Write-Output ("  menu=" + $m.X + ',' + $m.Y + ' ' + $m.W + 'x' + $m.H + '  rows~' + [int]($m.H / 6))
  # 点第 1 项 (菜单顶部往下 ~14px)
  LClick ($m.X + [int]($m.W * 0.4)) ($m.Y + 14)
  $pop2 = Get-Popups
  Write-Output ("  after level-1 click: popups=" + $pop2.Count)
  if ($pop2.Count -gt 0) {
    $sub = $pop2[0]
    Write-Output ("  submenu=" + $sub.X + ',' + $sub.Y + ' ' + $sub.W + 'x' + $sub.H)
    # 点子菜单第 1 项
    LClick ($sub.X + [int]($sub.W * 0.4)) ($sub.Y + 14)
  } else {
    Write-Output '  no submenu (click may have dismissed menu); continue'
  }
  Start-Sleep -Milliseconds 1500
  $st = Get-State
  Write-Output ("  -> logical=" + $st.logical + " overall=" + $st.overall)
  if ($st.overall) { Write-Output "SWITCHED TO OVERALL on round $round"; break }
}
$st = Get-State
Write-Output ("FINAL logical=" + $st.logical + " overall=" + $st.overall)
