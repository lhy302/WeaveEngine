# hub_fps_shot.ps1 - Launch engine from a version's own LoomHub, screenshot FPS (ASCII only)
# Usage: powershell -ExecutionPolicy Bypass -File hub_fps_shot.ps1 -HubDir <LoomHub dir> -Scene <scene.json> -OutPng <prefix> [-Source]
# Flow: start LoomHub --agent -> HUB-EAI launch_engine (same chain as GUI double click)
#       -> wait editor window -> maximize -> settle 12s -> shot A -> 5s -> shot B -> cleanup
param(
    [Parameter(Mandatory=$true)][string]$HubDir,
    [Parameter(Mandatory=$true)][string]$Scene,
    [Parameter(Mandatory=$true)][string]$OutPng,
    [switch]$Source
)
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms,System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class W32 {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
}
"@
[W32]::SetProcessDPIAware() | Out-Null

function Save-Shot([string]$path) {
    $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.X, $b.Y, 0, 0, $bmp.Size)
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    # crop bottom-left quadrant for FPS legibility
    $cw = [int]($b.Width / 2); $ch = [int]($b.Height / 2)
    $rect = New-Object System.Drawing.Rectangle 0, $ch, $cw, $ch
    $crop = $bmp.Clone($rect, $bmp.PixelFormat)
    $dir = [System.IO.Path]::GetDirectoryName($path)
    $name = [System.IO.Path]::GetFileNameWithoutExtension($path)
    $crop.Save((Join-Path $dir ($name + "_crop.png")), [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $crop.Dispose(); $bmp.Dispose()
    Write-Output "SHOT $path (+crop)"
}

# 0. cleanup leftovers
Get-Process -Name 'Loom','LoomHub' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# 1. start LoomHub with --agent (HUB-EAI bridge)
$portFile = Join-Path $HubDir '.hub_agent_port.json'
if (Test-Path $portFile) { Remove-Item $portFile -Force }
if ($Source) {
    $hub = Start-Process -FilePath 'py' -ArgumentList '-3.12','LoomHub.py','--agent' -WorkingDirectory $HubDir -PassThru -WindowStyle Hidden
} else {
    $hub = Start-Process -FilePath (Join-Path $HubDir 'LoomHub.exe') -ArgumentList '--agent' -WorkingDirectory $HubDir -PassThru
}

# 2. wait port file (10s)
$ok = $false
for ($i = 0; $i -lt 20; $i++) { if (Test-Path $portFile) { $ok = $true; break }; Start-Sleep -Milliseconds 500 }
if (-not $ok) { Write-Output "FAIL: port file not found: $portFile"; Stop-Process -Id $hub.Id -Force -ErrorAction SilentlyContinue; exit 1 }
$info = Get-Content $portFile -Encoding UTF8 -Raw | ConvertFrom-Json
Write-Output ("HUB-EAI port={0} hubpid={1}" -f $info.port, $hub.Id)

# 3. launch_engine (same chain as GUI double click: cwd=interpreter dir, env copy)
$headers = @{ 'X-Agent-Token' = $info.token }
$payload = @{ cmd = 'launch_engine'; args = @{ scene = $Scene; mode = 'open' } } | ConvertTo-Json -Depth 5
$bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
try {
    $resp = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/cmd" -f $info.port) -Method Post -Headers $headers -Body $bytes -ContentType 'application/json; charset=utf-8' -TimeoutSec 30
} catch {
    Write-Output "FAIL: launch_engine request error: $($_.Exception.Message)"
    Stop-Process -Id $hub.Id -Force -ErrorAction SilentlyContinue; exit 1
}
if (-not $resp.pid) { $resp = $resp.result }   # dispatch wraps in {ok, result}
if (-not $resp.pid) { Write-Output ("FAIL: launch_engine no pid: " + ($resp | ConvertTo-Json -Depth 5)); Stop-Process -Id $hub.Id -Force -ErrorAction SilentlyContinue; exit 1 }
$epid = [int]$resp.pid
Write-Output ("ENGINE pid={0} cmd={1}" -f $epid, $resp.command)

# 4. wait editor window (60s max)
$winTitle = ''
$p = $null
for ($i = 0; $i -lt 120; $i++) {
    $p = Get-Process -Id $epid -ErrorAction SilentlyContinue
    if (-not $p) { Write-Output "FAIL: engine process exited early"; Stop-Process -Id $hub.Id -Force -ErrorAction SilentlyContinue; exit 1 }
    if ($p.MainWindowTitle) { $winTitle = $p.MainWindowTitle; break }
    Start-Sleep -Milliseconds 500
}
if (-not $winTitle) { Write-Output "FAIL: no editor window in 60s"; Stop-Process -Id $hub.Id -Force -ErrorAction SilentlyContinue; exit 1 }
Write-Output ("WINDOW title=[{0}]" -f $winTitle)
try {
    [W32]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
    [W32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
} catch {}

# 5. settle 12s -> shot A, then 5s -> shot B
Start-Sleep -Seconds 12
Save-Shot "$OutPng`_a.png"
Start-Sleep -Seconds 5
Save-Shot "$OutPng`_b.png"

# 6. cleanup
Stop-Process -Id $epid -Force -ErrorAction SilentlyContinue
Stop-Process -Id $hub.Id -Force -ErrorAction SilentlyContinue
Get-Process -Name 'Loom','LoomHub' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Output "DONE $OutPng"
