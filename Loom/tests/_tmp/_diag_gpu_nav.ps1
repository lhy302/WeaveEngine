# _diag_gpu_nav.ps1 - 诊断: 任务管理器性能页侧栏元素 + GPU 项可用 UIA 模式
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$sig = @'
using System;
using System.Runtime.InteropServices;
public class D {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
}
'@
Add-Type -TypeDefinition $sig
[void][D]::SetProcessDPIAware()

$tm = @(Get-Process -Name Taskmgr -ErrorAction SilentlyContinue) |
      Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $tm) { Write-Host 'NOWINDOW'; exit 1 }
$h = [IntPtr]$tm.MainWindowHandle
if ([D]::IsIconic($h)) { [void][D]::ShowWindow($h, 9); Start-Sleep -Milliseconds 800 }
[void][D]::SetWindowPos($h, [IntPtr](-1), 0, 0, 0, 0, 0x0043)
Start-Sleep -Milliseconds 400
$r = New-Object 'D+RECT'; [void][D]::GetWindowRect($h, [ref]$r)
Write-Host ("[WIN] hwnd={0} rect={1},{2} {3}x{4} iconic={5} fg_is_tm={6}" -f `
  $h, $r.Left, $r.Top, ($r.Right - $r.Left), ($r.Bottom - $r.Top), [D]::IsIconic($h), ([D]::GetForegroundWindow() -eq $h))

$root = [System.Windows.Automation.AutomationElement]::FromHandle($h)
$title = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'resourceTitle')))
Write-Host ("[STATE] resourceTitle=[{0}]" -f $(if ($title) { $title.Current.Name } else { '(none)' }))

# 枚举所有 Button/ListItem, 打印 id/name/rect/patterns
$cond = New-Object System.Windows.Automation.OrCondition(
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)),
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::ListItem)))
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
Write-Host ("[TREE] button/listitem count = {0}" -f $all.Count)
foreach ($e in $all) {
  $aid = ''; $nm = ''; $br = $null
  try { $aid = $e.Current.AutomationId } catch {}
  try { $nm = $e.Current.Name } catch {}
  try { $br = $e.Current.BoundingRectangle } catch {}
  if ($aid -notmatch 'gpu|dashSidebar|Sidebar|resource' -and $nm -notmatch 'GPU|CPU|内存|磁盘|以太网') { continue }
  $pats = @()
  foreach ($p in @(
      [System.Windows.Automation.SelectionItemPattern]::Pattern,
      [System.Windows.Automation.InvokePattern]::Pattern,
      [System.Windows.Automation.ScrollItemPattern]::Pattern)) {
    $o = $null
    try { if ($e.TryGetCurrentPattern($p, [ref]$o)) { $pats += $p.ProgrammaticName -replace 'PatternIdentifiers.Pattern','' } } catch {}
  }
  Write-Host ("  id='{0}' name='{1}' rect={2},{3} {4}x{5} pats=[{6}]" -f `
    $aid, $nm, [int]$br.X, [int]$br.Y, [int]$br.Width, [int]$br.Height, ($pats -join ','))
}

# ---- 尝试 UIA 模式激活 GPU 项 (不用鼠标) ----
$gpu = $null
foreach ($e in $all) {
  $aid = ''; try { $aid = $e.Current.AutomationId } catch {}
  if ($aid -like 'gpu_entry_*') { $gpu = $e; break }
}
if (-not $gpu) { Write-Host '[GPU] gpu_entry_* NOT FOUND'; [void][D]::SetWindowPos($h, [IntPtr](-2), 0, 0, 0, 0, 0x0043); exit 0 }
Write-Host ("[GPU] found id={0} name={1}" -f $gpu.Current.AutomationId, $gpu.Current.Name)

$sp = $null
if ($gpu.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern, [ref]$sp)) {
  ([System.Windows.Automation.ScrollItemPattern]$sp).ScrollIntoView(); Start-Sleep -Milliseconds 600
  Write-Host '[GPU] ScrollIntoView ok'
}
$br = $gpu.Current.BoundingRectangle
Write-Host ("[GPU] rect after scroll = {0},{1} {2}x{3}" -f [int]$br.X, [int]$br.Y, [int]$br.Width, [int]$br.Height)

$done = ''
$sel = $null
if ($gpu.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$sel)) {
  try { ([System.Windows.Automation.SelectionItemPattern]$sel).Select(); $done = 'SelectionItem.Select'; Start-Sleep -Milliseconds 1200 } catch { Write-Host ('[GPU] Select threw: ' + $_.Exception.Message) }
}
if (-not $done) {
  $inv = $null
  if ($gpu.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$inv)) {
    try { ([System.Windows.Automation.InvokePattern]$inv).Invoke(); $done = 'Invoke.Invoke'; Start-Sleep -Milliseconds 1200 } catch { Write-Host ('[GPU] Invoke threw: ' + $_.Exception.Message) }
  }
}
Write-Host ("[GPU] activated via = '{0}'" -f $done)

$t2 = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'resourceTitle')))
Write-Host ("[STATE] after: resourceTitle=[{0}] iconic={1} fg_is_tm={2}" -f `
  $(if ($t2) { $t2.Current.Name } else { '(none)' }), [D]::IsIconic($h), ([D]::GetForegroundWindow() -eq $h))

[void][D]::SetWindowPos($h, [IntPtr](-2), 0, 0, 0, 0, 0x0043)
