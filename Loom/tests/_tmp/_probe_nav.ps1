# _probe_nav.ps1 - 一次性探针: 逐个测试任务管理器性能页左侧导航项的 UIA 激活效果
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public class NvWin32 {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
'@
[NvWin32]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 300

$p = Get-Process Taskmgr | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
[NvWin32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 700
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)

function Show-State([string]$tag) {
  $t = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'resourceTitle')))
  $log = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'CpuChartTitleLogical')))
  $tt = ''
  if ($t) { try { $tt = $t.Current.Name } catch { $tt = '?' } }
  Write-Output ("STATE[$tag] resourceTitle=[$tt] logicalTitle=" + ($log -ne $null))
}

function Try-Act([object]$el, [string]$what) {
  if (-not $el) { Write-Output "  $what : element NOT FOUND"; return }
  $aid = ''; $nm = ''; $ct = ''
  try { $aid = $el.Current.AutomationId; $nm = $el.Current.Name; $ct = $el.Current.ControlType.ProgrammaticName } catch {}
  Write-Output ("  $what : found id=[$aid] name=[$nm] type=[$ct]")
  foreach ($pt in @(@('SelectionItemPattern', [System.Windows.Automation.SelectionItemPattern]::Pattern),
                    @('InvokePattern', [System.Windows.Automation.InvokePattern]::Pattern))) {
    $pat = $null
    try {
      if ($el.TryGetCurrentPattern($pt[1], [ref]$pat)) {
        Write-Output ("    has " + $pt[0])
        if ($pt[0] -eq 'SelectionItemPattern') { ([System.Windows.Automation.SelectionItemPattern]$pat).Select() }
        else { ([System.Windows.Automation.InvokePattern]$pat).Invoke() }
        Write-Output ("    -> invoked " + $pt[0])
        return
      } else { Write-Output ("    no " + $pt[0]) }
    } catch { Write-Output ("    ERROR " + $pt[0] + ": " + $_.Exception.Message) }
  }
}

Show-State 'before'
$c = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'dashSidebarCpuButton')
$btn = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)
Try-Act $btn 'CPU sidebar button'
Start-Sleep -Milliseconds 1200
Show-State 'after CPU'

# GPU 按钮
$btns = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
  (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)))
$gpu = $null
foreach ($b in $btns) { try { if ($b.Current.AutomationId -like 'gpu_entry_*') { $gpu = $b; break } } catch {} }
Try-Act $gpu 'GPU sidebar button'
Start-Sleep -Milliseconds 1200
Show-State 'after GPU'

# 回到 CPU
Try-Act $btn 'CPU sidebar button (2nd)'
Start-Sleep -Milliseconds 1200
Show-State 'after CPU again'
Write-Output 'PROBE-NAV done'
