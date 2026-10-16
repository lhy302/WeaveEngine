# T5 重验: PrintWindow 直抓发布包游戏窗口 (避开桌面遮挡), 双时刻采样
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W32 {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
}
"@
function Grab-Dwm($h, $path) {
    $r = New-Object System.Drawing.Rectangle
    [System.Windows.Forms.SystemInformation]::VirtualScreen | Out-Null
    # 用 GetWindowRect 抓客户区大小
    Add-Type @"
using System; using System.Runtime.InteropServices;
public class W32b {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
}
"@
    $rc = New-Object W32b+RECT
    [void][W32b]::GetWindowRect($h, [ref]$rc)
    $w = $rc.R - $rc.L; $ht = $rc.B - $rc.T
    $bmp = New-Object System.Drawing.Bitmap($w, $ht)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    [void][W32]::PrintWindow($h, $hdc, 3)   # PW_RENDERFULLCONTENT
    $g.ReleaseHdc($hdc); $g.Dispose()
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    return "$w x $ht"
}

$exe = "D:\my-project\游戏发布\跳台试炼\MyGame.exe"
$p = Start-Process $exe -PassThru -WorkingDirectory (Split-Path $exe)
$h = [IntPtr]::Zero
for ($i = 0; $i -lt 60 -and $h -eq [IntPtr]::Zero; $i++) {
    Start-Sleep -Milliseconds 500
    $p.Refresh()
    $h = $p.MainWindowHandle
    if ($p.HasExited) { "进程已退出! code=$($p.ExitCode)"; exit 1 }
}
if ($h -eq [IntPtr]::Zero) { "未拿到窗口句柄"; Stop-Process -Id $p.Id -Force; exit 1 }
[void][W32]::SetForegroundWindow($h)
Start-Sleep 6
$sz1 = Grab-Dwm $h "D:\my-project\Loom(py源代码-工作区)\Loom\tests\_tmp\验收截图\T5v_首帧6s.png"
Start-Sleep 6
$sz2 = Grab-Dwm $h "D:\my-project\Loom(py源代码-工作区)\Loom\tests\_tmp\验收截图\T5v_首帧12s.png"
Stop-Process -Id $p.Id -Force
"标题=[$($p.MainWindowTitle)]  尺寸=$sz1/$sz2  PrintWindow 抓图 OK"
