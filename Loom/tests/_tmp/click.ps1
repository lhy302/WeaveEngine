param([int]$X, [int]$Y, [int]$Count = 1)
# 屏幕坐标点击 (GUI 自动化辅助, 2026-08-20): 用法  powershell -File click.ps1 -X 100 -Y 200
Add-Type @"
using System.Runtime.InteropServices;
public class M {
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, System.UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
}
"@
[M]::SetCursorPos($X, $Y) | Out-Null
Start-Sleep -Milliseconds 120
for ($i = 0; $i -lt $Count; $i++) {
  [M]::mouse_event(0x0002, 0, 0, 0, [System.UIntPtr]::Zero)   # LEFTDOWN
  [M]::mouse_event(0x0004, 0, 0, 0, [System.UIntPtr]::Zero)   # LEFTUP
  Start-Sleep -Milliseconds 150
}
Write-Output "clicked $X,$Y x$Count"
