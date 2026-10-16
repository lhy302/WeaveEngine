# _m2b_uia_tree.ps1 — 打印任务管理器窗口的 UIA 树 (AutomationId/ControlType/Name/矩形), 只读诊断
param([int]$Max = 90, [string]$Filter = '')
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class TW {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
'@
[void][TW]::SetProcessDPIAware()

$p = @(Get-Process -Name Taskmgr -ErrorAction SilentlyContinue) |
     Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'NO_TASKMGR'; exit 1 }
Write-Output ("TM pid={0} hwnd={1} title={2}" -f $p.Id, $p.MainWindowHandle, $p.MainWindowTitle)
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
if (-not $root) { Write-Output 'NO_ROOT'; exit 1 }

$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                     [System.Windows.Automation.Condition]::TrueCondition)
Write-Output ("descendants={0}" -f $all.Count)
$i = 0
foreach ($e in $all) {
  $i++; if ($i -gt $Max) { break }
  try {
    $c = $e.Current
    $r = $c.BoundingRectangle
    $line = ("#{0,3} type={1,-22} aid={2,-28} name=[{3}] rect={4},{5},{6}x{7}" -f `
      $i, $c.ControlType.ProgrammaticName.Replace('ControlType.', ''), $c.AutomationId,
      ($c.Name -replace '\s+', ' '), [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height)
    if ($Filter -and $line -notmatch $Filter) { continue }
    Write-Output $line
  } catch { Write-Output ("#{0} <err>" -f $i) }
}
