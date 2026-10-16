# _test_nav.ps1 - 端到端验证: 先切成"总体利用率", 再跑 tm_shot.ps1 -View cpu, 检查是否切回逻辑处理器
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public class Tn3Win32 {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; } }
'@
Write-Output ("aware=" + [Tn3Win32]::SetProcessDPIAware())
Start-Sleep -Milliseconds 400

$p = Get-Process Taskmgr -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'TEST: no taskmgr'; exit 1 }
$rect = New-Object 'Tn3Win32+R'
[Tn3Win32]::GetWindowRect($p.MainWindowHandle, [ref]$rect) | Out-Null
$L = [int]$rect.L; $T = [int]$rect.T; $RW = [int]$rect.Rr; $BH = [int]$rect.B
$W = $RW - $L; $H = $BH - $T
Write-Output ("TEST window L=$L T=$T R=$RW B=$BH  W=$W H=$H  hwnd=" + $p.MainWindowHandle)

function Get-Root { return [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle) }
function Find-Id($root, [string]$id) {
  return $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $id)))
}
function Is-Logical { return ((Find-Id (Get-Root) 'CpuChartTitleLogical') -ne $null) }
function Get-Popup {
  foreach ($w in [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
      [System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
    if ($w.Current.ClassName -eq '#32768') {
      $b = $w.Current.BoundingRectangle
      return [pscustomobject]@{ X = [int]$b.X; Y = [int]$b.Y; W = [int]$b.Width; H = [int]$b.Height }
    }
  }
  return $null
}
function Fore {
  [Tn3Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 700
}
function LClick([int]$x, [int]$y) {
  [Tn3Win32]::SetCursorPos($x, $y) | Out-Null; Start-Sleep -Milliseconds 220
  [Tn3Win32]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero) | Out-Null; Start-Sleep -Milliseconds 80
  [Tn3Win32]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero) | Out-Null; Start-Sleep -Milliseconds 1200
}
function Open-Menu {
  $cx = [int]($L + $W * 0.55); $cy = [int]($T + $H * 0.40)
  for ($i = 1; $i -le 10; $i++) {
    Fore
    [Tn3Win32]::SetCursorPos($cx, $cy) | Out-Null; Start-Sleep -Milliseconds 300
    [Tn3Win32]::mouse_event(0x0008, 0, 0, 0, [IntPtr]::Zero) | Out-Null; Start-Sleep -Milliseconds 90
    [Tn3Win32]::mouse_event(0x0010, 0, 0, 0, [IntPtr]::Zero) | Out-Null; Start-Sleep -Milliseconds 1100
    $m = Get-Popup
    if ($m) { Write-Output ("  menu on try ${i}: " + $m.X + ',' + $m.Y + ' ' + $m.W + 'x' + $m.H); return $m }
  }
  Write-Output '  menu never opened (10 tries)'
  return $null
}

Write-Output ("TEST start: logical=" + (Is-Logical))
if (Is-Logical) {
  Write-Output 'STEP1: switch to overall view via menu item #1 -> sub #1'
  $m = Open-Menu
  if ($m) {
    LClick ($m.X + [int]($m.W * 0.4)) ($m.Y + 14)
    $sub = Get-Popup
    if ($sub) {
      Write-Output ("  submenu: " + $sub.X + ',' + $sub.Y + ' ' + $sub.W + 'x' + $sub.H)
      LClick ($sub.X + [int]($sub.W * 0.4)) ($sub.Y + 14)
    } else {
      Write-Output '  no submenu -> dismiss menu'
      LClick ($L + 30) ($BH - 30)
    }
  }
  Start-Sleep -Milliseconds 1500
}
$logicalBefore = Is-Logical
Write-Output ("STEP1 result: logical=" + $logicalBefore)

Write-Output 'STEP2: run tm_shot.ps1 -View cpu'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'tm_shot.ps1') -OutDir (Join-Path $PSScriptRoot '_tm_smoke') -View cpu -Tag navtest 2>&1 | ForEach-Object { '  ' + $_.ToString() }
$final = Is-Logical
Write-Output ("TEST-RESULT: forced_overall_first=" + (-not $logicalBefore) + " logical_after_script=" + $final)
