# shot_editor.ps1 — 找 Loom Qt 编辑器窗口(CopyFromScreen 全屏截图) —— 验收链临时工具
param([string]$OutPng)
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$sig = @'
using System;
using System.Runtime.InteropServices;
public class Win32S {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
}
'@
Add-Type -TypeDefinition $sig
$target = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*编辑器*' } | Select-Object -First 1
if (-not $target) { Write-Output 'NOWINDOW'; exit 1 }
Write-Output ("WINDOW: title={0} hwnd={1}" -f $target.MainWindowTitle, $target.MainWindowHandle)
[Win32S]::SetForegroundWindow($target.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 500
$r = New-Object 'Win32S+RECT'
[Win32S]::GetWindowRect($target.MainWindowHandle, [ref]$r) | Out-Null
Write-Output ("RECT: left={0} top={1} right={2} bottom={3} w={4} h={5}" -f $r.Left, $r.Top, $r.Right, $r.Bottom, ($r.Right - $r.Left), ($r.Bottom - $r.Top))
$sw = [Win32S]::GetSystemMetrics(0); $sh = [Win32S]::GetSystemMetrics(1)
Write-Output ("SCREEN physical={0}x{1}" -f $sw, $sh)
$bmp = New-Object System.Drawing.Bitmap($sw, $sh)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen(0, 0, 0, 0, (New-Object System.Drawing.Size($sw, $sh)))
$g.Dispose()
$bmp.Save($OutPng, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output ("SAVED: {0}" -f $OutPng)
