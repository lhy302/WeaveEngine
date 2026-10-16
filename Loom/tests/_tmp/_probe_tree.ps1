# _probe_tree.ps1 - 一次性探针: 按页 dump 任务管理器 UIA 树, 找出跨页稳定的定位锚点
param([switch]$SwitchCpu)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public class TrWin32 {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; } }
'@
[TrWin32]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 300

$p = Get-Process Taskmgr | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
[TrWin32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 700
$r = New-Object 'TrWin32+R'; [TrWin32]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)

function Dump-Tree([string]$tag) {
  $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  Write-Output ("=== TREE[$tag] count=" + $all.Count + " ===")
  foreach ($e in $all) {
    $aid = ''; $nm = ''; $ct = ''
    try { $aid = $e.Current.AutomationId; $nm = $e.Current.Name; $ct = $e.Current.ControlType.ProgrammaticName } catch {}
    if ($aid -ne '' -or $nm -match 'CPU|GPU|内存|磁盘|以太网|性能') {
      Write-Output ("  type=$ct id=[$aid] name=[$nm]")
    }
  }
}

Dump-Tree 'as-is'

# 点左侧 CPU 列表项(按比例: 窗口左边缘 x+8% 处, 纵向 21.5%)
$cx = [int]($r.L + ($r.Rr - $r.L) * 0.07)
$cy = [int]($r.T + ($r.B - $r.T) * 0.215)
Write-Output ("click left-nav CPU at ($cx,$cy)")
[TrWin32]::SetCursorPos($cx, $cy) | Out-Null
Start-Sleep -Milliseconds 250
[TrWin32]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 70
[TrWin32]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 1500
Dump-Tree 'after-mouse-cpu'
Write-Output 'PROBE-TREE done'
