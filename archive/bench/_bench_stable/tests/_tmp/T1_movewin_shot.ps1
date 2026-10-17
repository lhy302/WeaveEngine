# T1_movewin_shot.ps1 — 启动编辑器 --open 场景, MoveWindow 调整尺寸后截图 (验证检查器面板)
param([string]$OutPng, [int]$W = 1450, [int]$H = 820)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing
$sig = @'
using System;
using System.Runtime.InteropServices;
public class Win32M {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int x, int y, int nWidth, int nHeight, bool bRepaint);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
}
'@
Add-Type -TypeDefinition $sig
Set-Location "D:\my-project\Loom(py源代码-工作区)\Loom"
$env:PYTHONUNBUFFERED = "1"
$p = Start-Process -FilePath "py" -ArgumentList "-3.12","Loom.py","--open","D:\my-project\Loom(py源代码-工作区)\封装测试材料\跳台试炼场景_明文.json" -RedirectStandardOutput "tests\_tmp\T1_movewin_out.txt" -RedirectStandardError "tests\_tmp\T1_movewin_err.txt" -PassThru
Write-Output "LAUNCH pid=$($p.Id)"
$win = $null
for ($i = 0; $i -lt 50; $i++) {
  Start-Sleep -Milliseconds 500
  if ($p.HasExited) { break }
  $cand = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*编辑器*' } | Select-Object -First 1
  if ($cand) { $win = $cand; break }
}
if (-not $win) { Write-Output "WIN_NOT_FOUND"; taskkill /PID $($p.Id) /T /F 2>$null | Out-Null; exit 1 }
Write-Output ("WIN title={0} hwnd={1}" -f $win.MainWindowTitle, $win.MainWindowHandle)
[Win32M]::SetForegroundWindow($win.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 500
$null = [Win32M]::MoveWindow($win.MainWindowHandle, 0, 0, $W, $H, $true)
Start-Sleep -Milliseconds 1500
$r = New-Object 'Win32M+RECT'
[Win32M]::GetWindowRect($win.MainWindowHandle, [ref]$r) | Out-Null
Write-Output ("RECT after move: {0}x{1}" -f ($r.Right - $r.Left), ($r.Bottom - $r.Top))
Start-Sleep -Milliseconds 800
$sw = [Win32M]::GetSystemMetrics(0); $sh = [Win32M]::GetSystemMetrics(1)
$bmp = New-Object System.Drawing.Bitmap($sw, $sh)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen(0, 0, 0, 0, (New-Object System.Drawing.Size($sw, $sh)))
$g.Dispose()
$bmp.Save($OutPng, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output ("SAVED {0}" -f $OutPng)
taskkill /PID $($p.Id) /T /F | Out-Null
Write-Output "KILLED"
