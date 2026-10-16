# m2b_raise_tm.ps1 — 把任务管理器窗口【提到前台】(不改 tm_shot.ps1, 只在调用它之前调用本脚本)
#  背景: 本机有一个最大化的浏览器窗口 (360se6_Frame / DeepSeek Harness) 覆盖了任务管理器,
#        tm_shot.ps1 内部 SetForegroundWindow 会被前台锁挡住 → 截图抓到的是浏览器而非任务管理器。
#  做法: ① 最小化态先 SW_RESTORE; ② 注入一次 Alt 键解锁前台; ③ AttachThreadInput 到当前前台
#        线程后 BringWindowToTop + SetWindowPos(HWND_TOP) + SetForegroundWindow。
#  用法: powershell -ExecutionPolicy Bypass -File tests\_tmp\m2b_raise_tm.ps1
#  输出: RAISE hwnd=... fg_after=... ok=True|False
#        不做任何持久改动: 不 kill 进程、不改任务管理器设置、不最小化任何窗口。
param([switch]$Quiet)
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class RaiseWin {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
}
'@

$tm = @(Get-Process -Name Taskmgr -ErrorAction SilentlyContinue) |
      Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $tm) { Write-Output 'RAISE hwnd=0 fg_after=0 ok=False (taskmgr window not found)'; exit 1 }
$h = $tm.MainWindowHandle

if ([RaiseWin]::IsIconic($h)) { [void][RaiseWin]::ShowWindow($h, 9); Start-Sleep -Milliseconds 300 }

# Alt 键注入: 解除"前台锁" (当前进程不是前台进程时 SetForegroundWindow 会被忽略)
[RaiseWin]::keybd_event(0x12, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 80
[RaiseWin]::keybd_event(0x12, 0, 2, [IntPtr]::Zero)
Start-Sleep -Milliseconds 80

$fg = [RaiseWin]::GetForegroundWindow()
$dummy = 0
$tfg = [RaiseWin]::GetWindowThreadProcessId($fg, [ref]$dummy)
$tme = [RaiseWin]::GetCurrentThreadId()
$attached = $false
try {
  $attached = [RaiseWin]::AttachThreadInput($tme, $tfg, $true)
  [void][RaiseWin]::BringWindowToTop($h)
  [void][RaiseWin]::SetWindowPos($h, [IntPtr]::Zero, 0, 0, 0, 0, 0x0043)  # HWND_TOP|NOMOVE|NOSIZE|SHOWWINDOW
  [void][RaiseWin]::SetForegroundWindow($h)
  [void][RaiseWin]::ShowWindow($h, 9)
} finally {
  if ($attached) { [void][RaiseWin]::AttachThreadInput($tme, $tfg, $false) }
}
Start-Sleep -Milliseconds 600

$now = [RaiseWin]::GetForegroundWindow()
$r = New-Object 'RaiseWin+RECT'
[void][RaiseWin]::GetWindowRect($h, [ref]$r)
Write-Output ("RAISE hwnd={0} fg_after={1} ok={2} rect={3},{4},{5}x{6}" -f `
  $h, $now, ($now -eq $h), $r.Left, $r.Top, ($r.Right - $r.Left), ($r.Bottom - $r.Top))
if ($now -ne $h) { exit 2 }
exit 0
