# _test_menu.ps1 - 定位右键菜单可靠性: 先置前再右键, 多次尝试, 报告菜单矩形
param([int]$Tries = 6)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public class Tm2Win32 {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; } }
'@
[Tm2Win32]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 300
$p = Get-Process Taskmgr | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
$r = New-Object 'Tm2Win32+R'; [Tm2Win32]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$W = $r.Rr - $r.L; $H = $r.B - $r.T
Write-Output ("WIN $($r.L),$($r.T) ${W}x${H} hwnd=" + $p.MainWindowHandle)
for ($t = 1; $t -le $Tries; $t++) {
  [Tm2Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 700
  $fg = [Tm2Win32]::GetForegroundWindow()
  $cx = [int]($r.L + $W * 0.55); $cy = [int]($r.T + $H * 0.40)
  [Tm2Win32]::SetCursorPos($cx, $cy) | Out-Null
  Start-Sleep -Milliseconds 300
  [Tm2Win32]::mouse_event(0x0008, 0, 0, 0, [IntPtr]::Zero) | Out-Null
  Start-Sleep -Milliseconds 90
  [Tm2Win32]::mouse_event(0x0010, 0, 0, 0, [IntPtr]::Zero) | Out-Null
  Start-Sleep -Milliseconds 1300
  $menu = $null
  foreach ($w in [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
      [System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
    if ($w.Current.ClassName -eq '#32768') { $menu = $w.Current.BoundingRectangle; break }
  }
  $isFg = ($fg -eq $p.MainWindowHandle)
  if ($menu) {
    Write-Output ("try ${t}: fg=$isFg click=($cx,$cy) MENU=" + [int]$menu.X + ',' + [int]$menu.Y + ',' + [int]$menu.Width + 'x' + [int]$menu.Height)
    # 关闭菜单 (点空白处)
    [Tm2Win32]::SetCursorPos(($r.L + 30), ($r.B - 30)) | Out-Null
    Start-Sleep -Milliseconds 200
    [Tm2Win32]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero) | Out-Null
    [Tm2Win32]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds 600
  } else {
    Write-Output "try ${t}: fg=$isFg click=($cx,$cy) no menu"
  }
}
Write-Output 'TEST-MENU done'
