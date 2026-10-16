# _probe_menu.ps1 - 一次性探针: 右键任务管理器图表, 枚举弹出菜单(#32768)的 Win32 菜单文本
# 目的: 弄清"更改图表/逻辑处理器"菜单项在中文 Win10 上的真实文本与索引
param([double]$Fy = 0.45)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System; using System.Text; using System.Runtime.InteropServices;
public class PmWin32 {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,IntPtr e);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr h);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr GetMenuStringW(IntPtr hMenu, uint uIDItem, StringBuilder lpString, int nMaxCount, uint uFlag);
 [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr hMenu);
 [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);
 [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; } }
'@
[PmWin32]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 300

$p = Get-Process Taskmgr -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'PROBE: no taskmgr'; exit 1 }
$r = New-Object 'PmWin32+R'; [PmWin32]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
Write-Output ("PROBE win={0},{1},{2},{3}" -f $r.L, $r.T, $r.Rr, $r.B)
[PmWin32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 800

$cx = [int](($r.L + $r.Rr) / 2)
$cy = [int]($r.T + ($r.B - $r.T) * $Fy)
Write-Output ("PROBE right-click at ({0},{1}) fy={2}" -f $cx, $cy, $Fy)
[PmWin32]::SetCursorPos($cx, $cy) | Out-Null
Start-Sleep -Milliseconds 300
[PmWin32]::mouse_event(0x0008, 0, 0, 0, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 120
[PmWin32]::mouse_event(0x0010, 0, 0, 0, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 1000

$tops = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
  [System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
Write-Output ("PROBE tops={0}" -f $tops.Count)
$pop = $null
foreach ($w in $tops) {
  if ($w.Current.ClassName -eq '#32768') { $pop = $w; break }
}
if (-not $pop) { Write-Output 'PROBE: no #32768 popup'; exit 1 }
$pr = $pop.Current.BoundingRectangle
$hwnd = [IntPtr]$pop.Current.NativeWindowHandle
Write-Output ("PROBE popup rect={0},{1},{2}x{3} hwnd={4}" -f [int]$pr.X, [int]$pr.Y, [int]$pr.Width, [int]$pr.Height, $hwnd)

$menu = [PmWin32]::GetMenu($hwnd)
$n = [PmWin32]::GetMenuItemCount($menu)
Write-Output ("PROBE GetMenu={0} count={1}" -f $menu, $n)
for ($i = 0; $i -lt $n; $i++) {
  $sb = New-Object System.Text.StringBuilder 512
  [void][PmWin32]::GetMenuStringW($menu, [uint32]$i, $sb, 512, 0x400)
  $sub = [PmWin32]::GetSubMenu($menu, $i)
  Write-Output ("PROBE item[{0}] text=[{1}] submenu={2}" -f $i, $sb.ToString(), $sub)
  if ($sub -ne [IntPtr]::Zero) {
    $sn = [PmWin32]::GetMenuItemCount($sub)
    for ($j = 0; $j -lt $sn; $j++) {
      $sb2 = New-Object System.Text.StringBuilder 512
      [void][PmWin32]::GetMenuStringW($sub, [uint32]$j, $sb2, 512, 0x400)
      Write-Output ("PROBE     sub[{0}] text=[{1}]" -f $j, $sb2.ToString())
    }
  }
}
# 关闭菜单
[PmWin32]::SetCursorPos(100, 600) | Out-Null
Start-Sleep -Milliseconds 200
[PmWin32]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero) | Out-Null
[PmWin32]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 300
Write-Output 'PROBE done (menu dismissed)'
