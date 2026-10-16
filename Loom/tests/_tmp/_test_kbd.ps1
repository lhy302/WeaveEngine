# _test_kbd.ps1 - 测试键盘菜单路线: Alt+V 打开"查看"菜单, 用方向键选择"更改图表"→"总体利用率"
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public class KbWin32 {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; } }
'@
[KbWin32]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 400
$p = Get-Process Taskmgr -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
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
  $n = 0
  foreach ($w in [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
      [System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
    if ($w.Current.ClassName -eq '#32768') { $n++ }
  }
  return $n
}
function Send-Key([int]$vk, [string]$name) {
  [KbWin32]::keybd_event([byte]$vk, 0, 0, [IntPtr]::Zero) | Out-Null
  Start-Sleep -Milliseconds 60
  [KbWin32]::keybd_event([byte]$vk, 0, 2, [IntPtr]::Zero) | Out-Null
  Start-Sleep -Milliseconds 500
  Write-Output ("  sent $name (vk=$vk) popups=" + (Get-Popups))
}
function Send-Alt([int]$vk, [string]$name) {
  [KbWin32]::keybd_event(0x12, 0, 0, [IntPtr]::Zero) | Out-Null   # Alt down
  Start-Sleep -Milliseconds 60
  [KbWin32]::keybd_event([byte]$vk, 0, 0, [IntPtr]::Zero) | Out-Null
  Start-Sleep -Milliseconds 60
  [KbWin32]::keybd_event([byte]$vk, 0, 2, [IntPtr]::Zero) | Out-Null
  [KbWin32]::keybd_event(0x12, 0, 2, [IntPtr]::Zero) | Out-Null   # Alt up
  Start-Sleep -Milliseconds 800
  Write-Output ("  sent Alt+$name (vk=$vk) popups=" + (Get-Popups))
}

[KbWin32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 900
$st = Get-State
Write-Output ("start logical=" + $st.logical + " overall=" + $st.overall)

Write-Output 'STEP: Alt+V (查看菜单)'
Send-Alt 0x56 'V'
Start-Sleep -Milliseconds 500
# 菜单里找"更改图表": 先按 Home 到第一项, 再逐项下移, 每步报告
Write-Output 'STEP: navigate menu with Down/Right/Enter'
for ($i = 1; $i -le 8; $i++) {
  Send-Key 0x28 "Down#$i"
  $st = Get-State
  if ($st.overall) { Write-Output "  -> OVERALL reached after $i downs"; break }
}
$st = Get-State
Write-Output ("after downs: logical=" + $st.logical + " overall=" + $st.overall)
# 若还停在 logical, 尝试 Enter 确认当前项
Send-Key 0x0D 'Enter'
Start-Sleep -Milliseconds 1200
$st = Get-State
Write-Output ("after enter: logical=" + $st.logical + " overall=" + $st.overall)
# 收尾: Esc 关掉可能残留的菜单
[KbWin32]::keybd_event(0x1B, 0, 0, [IntPtr]::Zero) | Out-Null
[KbWin32]::keybd_event(0x1B, 0, 2, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 400
$st = Get-State
Write-Output ("FINAL logical=" + $st.logical + " overall=" + $st.overall + " popups=" + (Get-Popups))
