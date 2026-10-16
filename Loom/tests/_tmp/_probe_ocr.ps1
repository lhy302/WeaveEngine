# _probe_ocr.ps1 - 一次性探针: 右键任务管理器图表, 截图弹出菜单区域, 用 Windows.Media.Ocr 读取菜单文本
# 目的: 在无法目视的情况下确定"更改图表/逻辑处理器"菜单项的真实文本与行位置
param([double]$Fy = 0.45, [string]$OutPng = '')
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public class OcWin32 {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,IntPtr e);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; } }
'@
[OcWin32]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 300

$p = Get-Process Taskmgr -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'OCR-PROBE: no taskmgr'; exit 1 }
$r = New-Object 'OcWin32+R'; [OcWin32]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
[OcWin32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 800
$cx = [int](($r.L + $r.Rr) / 2); $cy = [int]($r.T + ($r.B - $r.T) * $Fy)
Write-Output ("OCR-PROBE right-click at ({0},{1})" -f $cx, $cy)
[OcWin32]::SetCursorPos($cx, $cy) | Out-Null
Start-Sleep -Milliseconds 300
[OcWin32]::mouse_event(0x0008, 0, 0, 0, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 120
[OcWin32]::mouse_event(0x0010, 0, 0, 0, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 1200

$tops = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
  [System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
$pop = $null
foreach ($w in $tops) { if ($w.Current.ClassName -eq '#32768') { $pop = $w; break } }
if (-not $pop) { Write-Output 'OCR-PROBE: no popup'; exit 1 }
$pr = $pop.Current.BoundingRectangle
$px = [int]$pr.X; $py = [int]$pr.Y; $pw = [int]$pr.Width; $ph = [int]$pr.Height
Write-Output ("OCR-PROBE popup={0},{1},{2}x{3}" -f $px, $py, $pw, $ph)

# 截取菜单区域(略微外扩, 取整数)
$m = 6
$x0 = [Math]::Max(0, $px - $m); $y0 = [Math]::Max(0, $py - $m)
$w0 = [Math]::Min(600, $pw + 2 * $m); $h0 = [Math]::Min(600, $ph + 2 * $m)
$bmp = New-Object System.Drawing.Bitmap($w0, $h0)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($x0, $y0, 0, 0, (New-Object System.Drawing.Size($w0, $h0)))
$g.Dispose()
if ($OutPng) { $bmp.Save($OutPng, [System.Drawing.Imaging.ImageFormat]::Png); Write-Output ("OCR-PROBE saved $OutPng") }

# ---- Windows.Media.Ocr ----
try {
  [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
  [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
  [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
  [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
  [Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
} catch { Write-Output ('OCR-PROBE: WinRT type load failed: ' + $_.Exception.Message) }

$AddTypeSrc = @'
using System;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Threading.Tasks;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage.Streams;
public static class OcrHelp {
  public static async Task<string> Run(byte[] bgra, int w, int h) {
    var stream = new InMemoryRandomAccessStream();
    var writer = new DataWriter(stream);
    writer.WriteBytes(bgra);
    await writer.StoreAsync();
    await writer.FlushAsync();
    writer.DetachStream();
    stream.Seek(0);
    var decoder = await BitmapDecoder.CreateAsync(stream);
    var bitmap = await decoder.GetSoftwareBitmapAsync(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied);
    var engine = OcrEngine.TryCreateFromUserProfileLanguages();
    if (engine == null) return "NO_ENGINE";
    var result = await engine.RecognizeAsync(bitmap);
    var sb = new System.Text.StringBuilder();
    foreach (var line in result.Lines) {
      var wr = line.Words[0].BoundingRect;
      sb.AppendLine(string.Format("LINE y={0:F0} x={1:F0} text=[{2}]", wr.Y, wr.X, line.Text));
    }
    return sb.ToString();
  }
}
'@
$refs = @(
  'C:\Windows\System32\WinMetadata\Windows.Foundation.winmd',
  'C:\Windows\System32\WinMetadata\Windows.Graphics.winmd',
  'C:\Windows\System32\WinMetadata\Windows.Media.winmd',
  'C:\Windows\System32\WinMetadata\Windows.Storage.winmd',
  'System.Runtime.WindowsRuntime.dll'
)
try {
  Add-Type -TypeDefinition $AddTypeSrc -ReferencedAssemblies $refs -Language CSharp -ErrorAction Stop
  $bmpData = $bmp.LockBits((New-Object System.Drawing.Rectangle(0,0,$w0,$h0)), [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $bytes = New-Object byte[] ($bmpData.Stride * $h0)
  [System.Runtime.InteropServices.Marshal]::Copy($bmpData.Scan0, $bytes, 0, $bytes.Length)
  $bmp.UnlockBits($bmpData)
  $task = [OcrHelp]::Run($bytes, $w0, $h0)
  $task.Wait(20000) | Out-Null
  Write-Output '--- OCR RESULT ---'
  Write-Output $task.Result
} catch {
  Write-Output ('OCR-PROBE: Add-Type/Run failed: ' + $_.Exception.Message)
}
$bmp.Dispose()
[OcWin32]::SetCursorPos(100, 600) | Out-Null
Start-Sleep -Milliseconds 200
[OcWin32]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero) | Out-Null
[OcWin32]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 300
Write-Output 'OCR-PROBE done'
