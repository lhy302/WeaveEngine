# T1_printwin.ps1 — PrintWindow (PW_RENDERFULLCONTENT) 抓 Loom 编辑器窗口内容
param([string]$OutPng)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing
$sig = @'
using System;
using System.Runtime.InteropServices;
public class W32P {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
'@
Add-Type -TypeDefinition $sig
$win = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*编辑器*' } | Select-Object -First 1
if (-not $win) { Write-Output 'NOWINDOW'; exit 1 }
$r = New-Object 'W32P+RECT'
[W32P]::GetWindowRect($win.MainWindowHandle, [ref]$r) | Out-Null
$w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
Write-Output ("RECT {0}x{1}" -f $w, $h)
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
$ok = [W32P]::PrintWindow($win.MainWindowHandle, $dc, 3)  # PW_CLIENTONLY(1)|PW_RENDERFULLCONTENT(2)
$g.ReleaseHdc($dc)
$g.Dispose()
Write-Output ("PRINTWINDOW ok={0}" -f $ok)
$bmp.Save($OutPng, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output ("SAVED {0}" -f $OutPng)
