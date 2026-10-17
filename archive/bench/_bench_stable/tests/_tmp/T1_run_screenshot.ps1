# T1_run_screenshot.ps1 — 验收链 T1: 启动 Loom Qt 编辑器, 找窗, 截图, 测 --auto-close, 清进程
# 用法: T1_run_screenshot.ps1 -Scene <json或无> -OutPng <png或none> -AutoClose <0|8> -LogDir <dir>
param(
  [string]$Scene, [string]$OutPng, [int]$AutoClose = 0, [string]$LogDir
)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$sig = @'
using System;
using System.Runtime.InteropServices;
public class Win32S2 {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
}
'@
Add-Type -TypeDefinition $sig

Set-Location "D:\my-project\Loom(py源代码-工作区)\Loom"
$env:PYTHONUNBUFFERED = "1"
$argsL = @("-3.12", "Loom.py")
if ($Scene -and $Scene -ne "NONE") { $argsL += @("--open", $Scene) }
if ($AutoClose -gt 0) { $argsL += @("--auto-close", "$AutoClose") }
$outLog = Join-Path $LogDir "run_s_out.txt"; $errLog = Join-Path $LogDir "run_s_err.txt"
$p = Start-Process -FilePath "py" -ArgumentList $argsL -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
$t0 = Get-Date
Write-Output "LAUNCH pid=$($p.Id) autoClose=$AutoClose t0=$($t0.ToString('HH:mm:ss.fff'))"

# 轮询窗口 (最长 25s)
$win = $null
$tAppear = $null
for ($i = 0; $i -lt 50; $i++) {
  Start-Sleep -Milliseconds 500
  if ($p.HasExited) { break }
  $cand = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*编辑器*' } | Select-Object -First 1
  if ($cand) { $win = $cand; $tAppear = $i * 0.5; break }
}
if ($win) {
  Write-Output ("WIN tAppear=+{0:N1}s title={1} hwnd={2}" -f $tAppear, $win.MainWindowTitle, $win.MainWindowHandle)
  [Win32S2]::SetForegroundWindow($win.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 600
  $r = New-Object 'Win32S2+RECT'
  [Win32S2]::GetWindowRect($win.MainWindowHandle, [ref]$r) | Out-Null
  Write-Output ("RECT left={0} top={1} right={2} bottom={3} w={4} h={5}" -f $r.Left,$r.Top,$r.Right,$r.Bottom,($r.Right-$r.Left),($r.Bottom-$r.Top))
  if ($OutPng -and $OutPng -ne "NONE") {
    $sw = [Win32S2]::GetSystemMetrics(0)   # SM_CXSCREEN 物理宽
    $sh = [Win32S2]::GetSystemMetrics(1)   # SM_CYSCREEN 物理高
    Write-Output ("SCREEN physical={0}x{1}" -f $sw, $sh)
    $bmp = New-Object System.Drawing.Bitmap($sw, $sh)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen(0, 0, 0, 0, (New-Object System.Drawing.Size($sw, $sh)))
    $g.Dispose()
    $bmp.Save($OutPng, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Output ("SAVED $OutPng")
  }
} else {
  Write-Output "WIN_NOT_FOUND"
}

# 收尾: 等退出 (auto-close) 或强杀
$waitS = 18
if (-not $p.HasExited) {
  if (-not $p.WaitForExit($waitS * 1000)) {
    Write-Output "TIMEOUT_${waitS}s -> KILL"
    taskkill /PID $($p.Id) /T /F 2>$null | Out-Null
  }
}
Start-Sleep -Milliseconds 800
$alive = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
$exitCode = if ($alive) { "STILL_ALIVE" } else { $p.ExitCode }
$elapsed = ((Get-Date) - $t0).TotalSeconds
Write-Output ("END exit={0} wall={1:N1}s" -f $exitCode, $elapsed)
