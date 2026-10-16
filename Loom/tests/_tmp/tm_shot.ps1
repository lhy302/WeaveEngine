# tm_shot.ps1 - 对 Windows 任务管理器做【定向截图】(只截任务管理器窗口, 非全屏)
#  用途: Loom 播放模式下目视确认 (a) CPU 负载是否分摊到多逻辑处理器 (b) GPU 利用率是否吃满
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File tm_shot.ps1 -View cpu  -Tag play_src
#    powershell -ExecutionPolicy Bypass -File tm_shot.ps1 -View gpu  -Tag play_src
#    powershell -ExecutionPolicy Bypass -File tm_shot.ps1 -View both -Tag play_src
#    powershell -ExecutionPolicy Bypass -File tm_shot.ps1 -View cpu  -FullScreen
#  退出码: 0 = 至少产出一张 PNG ; 1 = 失败(找不到窗口 / 保存失败)
#
#  本机实测口径 (2026-09-08, 中文 Win10 + Xeon E5-2696v3 18C/18T, GTX 1050 Ti, 125% DPI):
#    · 任务管理器窗口标题 = "任务管理器" (即使系统 UI 语言是 en-US), 进程名 Taskmgr
#    · UIA 可用的关键 AutomationId:
#        tabctrl / dashSidebarCpuButton / gpu_entry_0_0_<id> / chartInfo / resourceTitle
#        CpuChartTitleLogical  -> 存在即代表【逻辑处理器】小图视图
#        CPU00..CPU170         -> 每个逻辑处理器的独立小图 (18 个)
#        logicalproc           -> 性能页专有元素 (用于判断"性能"页是否已打开)
#    · 标签栏(进程/性能/...)与图表右键菜单【都不暴露】UIA 子元素 (自定义绘制),
#      因此"性能"标签与"更改图表->逻辑处理器"只能靠鼠标注入, 见下面导航策略。
#
#  ---------------------------------------------------------------------------
#  DPI 处理方案 (选了哪种 / 为什么)
#  选定方案 = 进程 DPI 感知 (SetProcessDPIAware) 为主 + 物理/逻辑缩放比换算为兜底
#  理由:
#    1) GetWindowRect 与 GetSystemMetrics(SM_CXSCREEN) 返回【物理像素】;
#       Graphics.CopyFromScreen 在【DPI 未感知】进程里按【逻辑像素】解释入参。
#       本机实测: 未感知进程 GetWindowRect=774x696, 感知后=967x870, 125% 缩放,
#       若不处理则截图区域完全错位 → 必须让两者同口径。
#    2) SetProcessDPIAware() 在本脚本 main 里【最先】调用, 早于任何截图;
#       实测调用后 GetWindowRect(15,98,982,968) 与 UIA 窗口矩形(15,98,967x870)
#       完全一致, 且截图尺寸 = 967x870 = 物理窗口尺寸 → 坐标口径已统一。
#    3) 再叠一层兜底: ratio = SM_CXSCREEN / PrimaryScreen.Bounds.Width,
#       感知生效时 ratio≈1.0; 若 ratio 明显偏离 1.0 (感知未生效), 则把窗口矩形
#       除以 ratio 换算成逻辑坐标再裁剪。双保险, 且日志会打印实际 ratio 便于审计。
#    4) 不用 SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2): 只截主屏上的
#       任务管理器, 单屏场景 System DPI Aware 已足够, 少一个兼容分支。
#  ---------------------------------------------------------------------------
param(
    [string]$OutDir = '',
    [ValidateSet('cpu', 'gpu', 'both')][string]$View = 'both',
    [string]$Tag = '',
    [switch]$FullScreen,

    # ---------- 导航参数 (UIA 走不通时的鼠标注入坐标, 全部为窗口矩形【相对比例】) ----------
    # "性能"标签: 标签栏在窗口顶部, 实测 UIA 的 tabctrl 矩形 = 窗口 y+33..y+61;
    # 中文 Win10 标签顺序 = 进程 | 性能 | 应用历史记录 | 启动 | 用户 | 详细信息 | 服务
    # 故"性能"约在 x≈170px 处 → 比例约 0.176 (窗口宽 967)
    [double]$PerfTabX = 0.176,
    [double]$PerfTabY = 0.054,

    # 左侧导航列表项纵向比例 (性能页: 左侧是 CPU/内存/磁盘/网络/GPU 列表)
    # 本机实测(窗口 15,98 967x870): CPU 项中心 y=208(rel 0.239), GPU 项中心 y=788(rel 0.906),
    # 中间依次是 内存/磁盘0..3/以太网。注意: 列表会随"当前页"重排, 故比例只作兜底,
    # 首选路线是直接读 UIA 元素矩形 (dashSidebarCpuButton / gpu_entry_*) 再点其中心。
    [double]$PnlX    = 0.070,   # 列表横向中心 (实测列表项 x≈29..282, 中心 155 → rel 0.16)
    [double]$PnlCpuX = 0.160,
    [double]$PnlCpuY = 0.239,   # "CPU" 列表项 (兜底)
    [double]$PnlGpuX = 0.160,
    [double]$PnlGpuY = 0.906,   # "GPU" 列表项 (兜底; 无独显/未加载 GPU 引擎时可能不存在)

    # 图表右键菜单: 菜单是自定义绘制窗口(class #32768), 无 Win32 菜单、无 UIA 子元素,
    # 只能按比例点。菜单从右键点向右下展开, 故比例基于【窗口矩形】推算, 本机实测可调。
    [double]$MenuClickX = 0.50,  # 右键点: 图区中心
    [double]$MenuClickY = 0.45,
    [double]$MenuLvl1X  = 0.78,  # 一级项 "更改图表" (右键点右侧 + 菜单第 6 行)
    [double]$MenuLvl1Y  = 0.52,
    [double]$MenuLvl2X  = 0.95,  # 二级项 "逻辑处理器" (子菜单在更右侧)
    [double]$MenuLvl2Y  = 0.56,
    [int]$MenuRetry = 3,         # 右键菜单有时不弹出 → 重试次数

    [switch]$NoStart,            # 调试: 任务管理器未运行时不自动启动
    [switch]$Diag,               # 调试: 额外落盘菜单区域裁图, 便于人工核对菜单坐标
    [switch]$NoTopMost,          # 调试: 不做 HWND_TOPMOST 置顶 (默认置顶, 抗前台锁)
    [switch]$NoPrintWindow       # 调试: 不用 PrintWindow 备用通道
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# ==================== 0. DPI 感知 (必须在任何截图之前) ====================
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$sig = @'
using System;
using System.Runtime.InteropServices;
public class TmWin32 {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

  [DllImport("user32.dll", SetLastError=true)] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter,
      int x, int y, int cx, int cy, uint uFlags);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, IntPtr extra);
}
'@
Add-Type -TypeDefinition $sig -ReferencedAssemblies System.Drawing

$dpiAware = $false
try { $dpiAware = [TmWin32]::SetProcessDPIAware() } catch { $dpiAware = $false }

# ==================== 1. 工具函数 ====================
# v2: 必须用 Write-Host —— 原 Write-Output 会混进函数返回值, 被 [void]() / 赋值调用吞掉,
#     导致 [MOUSE]/[NAV]/[CAP] 等日志静默丢失 (2026-09-09 定位)。
function Log([string]$s) { Write-Host $s }

function Get-ScreenMetrics {
  $sw = [TmWin32]::GetSystemMetrics(0)   # SM_CXSCREEN (物理像素)
  $sh = [TmWin32]::GetSystemMetrics(1)   # SM_CYSCREEN (物理像素)
  $b  = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $ratio = 1.0
  if ($b.Width -gt 0) { $ratio = [double]$sw / [double]$b.Width }
  [pscustomobject]@{
    PhysW = $sw; PhysH = $sh
    BoundsW = $b.Width; BoundsH = $b.Height; BoundsX = $b.X; BoundsY = $b.Y
    Ratio = $ratio; Aware = $dpiAware
  }
}

# 把矩形夹紧到屏幕内 (负数/越界一律裁剪, 否则 CopyFromScreen 抛异常)
function Clamp-Rect([int]$l, [int]$t, [int]$r, [int]$b, [int]$sw, [int]$sh) {
  $l2 = [Math]::Max(0, [Math]::Min($l, $sw - 1))
  $t2 = [Math]::Max(0, [Math]::Min($t, $sh - 1))
  $r2 = [Math]::Max($l2 + 1, [Math]::Min($r, $sw))
  $b2 = [Math]::Max($t2 + 1, [Math]::Min($b, $sh))
  [pscustomobject]@{ X = $l2; Y = $t2; W = ($r2 - $l2); H = ($b2 - $t2) }
}

# ==================== 2. 定位任务管理器窗口 ====================
$TitleRe = '(任务管理器|Task\s*Manager)'   # 中文/英文系统标题都要兼容

function Find-Taskmgr {
  $procs = @(Get-Process -Name Taskmgr -ErrorAction SilentlyContinue)
  if ($procs.Count -eq 0) { return $null }
  $withWin = @($procs | Where-Object { $_.MainWindowHandle -ne 0 })
  if ($withWin.Count -eq 0) { return $null }
  $byTitle = @($withWin | Where-Object { $_.MainWindowTitle -match $TitleRe })
  if ($byTitle.Count -gt 0) { return $byTitle[0] }
  return $withWin[0]   # 标题取不到时退化: 任何有主窗口的 Taskmgr
}

function Wait-Taskmgr([int]$timeoutSec) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    $p = Find-Taskmgr
    if ($p) { return $p }
    Start-Sleep -Milliseconds 400
  }
  return $null
}

# ==================== 3. UI Automation ====================
$UiaReady = $false
try {
  Add-Type -AssemblyName UIAutomationClient -ErrorAction Stop
  Add-Type -AssemblyName UIAutomationTypes -ErrorAction Stop
  $UiaReady = $true
} catch { Log ('[UIA] load failed: ' + $_.Exception.Message) }

function Uia-FindById([object]$root, [string]$id) {
  if (-not $root) { return $null }
  try {
    $cond = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $id)
    return $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
  } catch { return $null }
}

function Uia-FindByName([object]$root, [string]$name) {
  if (-not $root) { return $null }
  try {
    $cond = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::NameProperty, $name)
    return $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
  } catch { return $null }
}

# 依次尝试 SelectionItemPattern.Select() / InvokePattern.Invoke() / SetFocus()
function Uia-Activate([object]$el) {
  if (-not $el) { return '' }
  try {
    $pat = $null
    if ($el.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pat)) {
      ([System.Windows.Automation.SelectionItemPattern]$pat).Select(); return 'select'
    }
  } catch {}
  try {
    $pat2 = $null
    if ($el.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pat2)) {
      ([System.Windows.Automation.InvokePattern]$pat2).Invoke(); return 'invoke'
    }
  } catch {}
  try { $el.SetFocus(); return 'focus' } catch {}
  return ''
}

# ---- 当前视图检测 (用 UIA 客观判定, 不靠猜) ----
# 本机实测锚点:
#   resourceTitle       -> 当前页标题 (CPU / 磁盘 2 (D:) / GPU 0 ...), 跨页稳定
#   chartInfo/logicalproc -> 性能页专有
#   CpuChartTitleLogical  -> 逻辑处理器小图视图 (存在即为 logical)
#   CPU00..CPU170         -> 每核小图, 用于数核数
function Uia-ResourceTitle([object]$root) {
  $t = Uia-FindById $root 'resourceTitle'
  if ($t) { try { return $t.Current.Name } catch {} }
  return ''
}

function Get-ViewState([object]$root) {
  $st = [pscustomobject]@{
    Page = 'unknown'; ResourceTitle = ''; Logical = $false; LogicalPanes = 0; Gpu = $false
  }
  if (-not $root) { return $st }
  $st.ResourceTitle = Uia-ResourceTitle $root
  if ($st.ResourceTitle -ne '' -or (Uia-FindById $root 'chartInfo')) {
    $st.Page = 'performance'
  } else { $st.Page = 'other' }

  if (Uia-FindById $root 'CpuChartTitleLogical') {
    $st.Logical = $true
    foreach ($i in 0..63) {                     # 数每核小图 CPU00..CPU630
      if (Uia-FindById $root ('CPU' + ($i * 10))) { $st.LogicalPanes++ }
    }
  }
  if ($st.ResourceTitle -match 'GPU') { $st.Gpu = $true }
  elseif (Uia-FindById $root 'gpuUsage') { $st.Gpu = $true }
  return $st
}

# ==================== 4. 鼠标注入 ====================
function Click-At([int]$x, [int]$y, [string]$why) {
  try {
    [TmWin32]::SetCursorPos($x, $y) | Out-Null
    Start-Sleep -Milliseconds 120
    [TmWin32]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)   # LEFTDOWN
    Start-Sleep -Milliseconds 60
    [TmWin32]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)   # LEFTUP
    Log ("[MOUSE] click ($x,$y)  $why")
    return $true
  } catch {
    Log ('[MOUSE] click failed: ' + $_.Exception.Message)
    return $false
  }
}

function Click-Rel([object]$rect, [double]$fx, [double]$fy, [string]$why) {
  return Click-At ([int]($rect.X + $rect.W * $fx)) ([int]($rect.Y + $rect.H * $fy)) $why
}

function Right-Click-At([int]$x, [int]$y) {
  try {
    [TmWin32]::SetCursorPos($x, $y) | Out-Null
    Start-Sleep -Milliseconds 150
    [TmWin32]::mouse_event(0x0008, 0, 0, 0, [IntPtr]::Zero)   # RIGHTDOWN
    Start-Sleep -Milliseconds 70
    [TmWin32]::mouse_event(0x0010, 0, 0, 0, [IntPtr]::Zero)   # RIGHTUP
    return $true
  } catch { return $false }
}

# 右键菜单是否弹出 (class #32768 的顶层窗口); 返回菜单矩形或 $null
function Get-MenuPopup {
  if (-not $UiaReady) { return $null }
  try {
    $tops = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
      [System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($w in $tops) {
      if ($w.Current.ClassName -eq '#32768') { return $w.Current.BoundingRectangle }
    }
  } catch {}
  return $null
}

# ==================== 5. 截图 ====================
#  v2 修复 (2026-09-09): 原实现只用 Graphics.CopyFromScreen 抓屏幕像素,
#  当 SetForegroundWindow 被前台锁拒绝时 (实测日志 [WARN] SetForegroundWindow did
#  not take effect), 截到的是压在任务管理器上方的浏览器窗口 → 证据无效。
#  现在: (1) 采集前强制 HWND_TOPMOST 置顶; (2) 双通道截图 CopyFromScreen + PrintWindow;
#        (3) 对两张图做像素体检 (非黑占比 / 唯一色数), 自动判定可用性并写日志。
function Save-Shot([object]$rect, [string]$path) {
  $bmp = $null; $g = $null
  try {
    $bmp = New-Object System.Drawing.Bitmap($rect.W, $rect.H)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($rect.X, $rect.Y, 0, 0, (New-Object System.Drawing.Size($rect.W, $rect.H)))
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    return $true
  } catch {
    Log ('[ERROR] capture/save failed: ' + $_.Exception.Message)
    return $false
  } finally {
    if ($g) { $g.Dispose() }
    if ($bmp) { $bmp.Dispose() }
  }
}

# PrintWindow(PW_RENDERFULLCONTENT=2): 直接取窗口自身内容, 不受遮挡影响
function Save-Shot-PW([object]$hwnd, [object]$rect, [string]$path) {
  $bmp = $null; $g = $null
  try {
    $bmp = New-Object System.Drawing.Bitmap($rect.W, $rect.H)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    $ok = [TmWin32]::PrintWindow([IntPtr]$hwnd, $hdc, 2)
    $g.ReleaseHdc($hdc)
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    return $ok
  } catch {
    Log ('[ERROR] PrintWindow failed: ' + $_.Exception.Message)
    return $false
  } finally {
    if ($g) { $g.Dispose() }
    if ($bmp) { $bmp.Dispose() }
  }
}

# 像素体检: 返回 非黑占比% / 唯一色数 / 是否为纯色(疑似黑屏或遮挡)
function Get-ImageStats([string]$path) {
  $bmp = $null
  try {
    $bmp = [System.Drawing.Bitmap]::FromFile($path)
    $w = $bmp.Width; $h = $bmp.Height
    $step = [Math]::Max(1, [int]([Math]::Sqrt(($w * $h) / 40000.0)))
    $nonBlack = 0; $total = 0
    $colors = New-Object 'System.Collections.Generic.HashSet[string]'
    for ($y = 0; $y -lt $h; $y += $step) {
      for ($x = 0; $x -lt $w; $x += $step) {
        $c = $bmp.GetPixel($x, $y); $total++
        if ($c.R -gt 8 -or $c.G -gt 8 -or $c.B -gt 8) { $nonBlack++ }
        [void]$colors.Add(('{0},{1},{2}' -f $c.R, $c.G, $c.B))
      }
    }
    [pscustomobject]@{
      Path = $path; W = $w; H = $h; Sampled = $total
      NonBlackPct = [Math]::Round(100.0 * $nonBlack / [Math]::Max(1, $total), 1)
      UniqColors = $colors.Count
      Sane = ($nonBlack -gt 0.02 * $total) -and ($colors.Count -gt 12)
    }
  } catch {
    Log ('[ERROR] stats failed: ' + $_.Exception.Message)
    [pscustomobject]@{ Path = $path; Sane = $false; NonBlackPct = -1; UniqColors = -1 }
  } finally {
    if ($bmp) { $bmp.Dispose() }
  }
}

# 双通道采集: 采集前【重读窗口矩形】(窗口可能在导航期间被移动), 再 CopyFromScreen +
# PrintWindow, 体检后选主图。主图优先 PrintWindow (窗口自身内容, 不受遮挡/位置漂移影响)。
function Capture-Window([object]$hwnd, [string]$basePath) {
  $fg = [TmWin32]::GetForegroundWindow()
  # v2 修复: 原实现在脚本开头只读一次 rect, 导航期间窗口若移动 → 采集区域错位,
  #   实测边缘混入浏览器像素。现在每次采集前重读。
  $rr = New-Object 'TmWin32+RECT'
  [void][TmWin32]::GetWindowRect([IntPtr]$hwnd, [ref]$rr)
  $clip = Clamp-Rect $rr.Left $rr.Top $rr.Right $rr.Bottom $sm.PhysW $sm.PhysH
  Log ('[CAP] foreground={0} tm={1} is_foreground={2} iconic={3} visible={4}' -f `
       $fg, $hwnd, ($fg -eq $hwnd), [TmWin32]::IsIconic([IntPtr]$hwnd), [TmWin32]::IsWindowVisible([IntPtr]$hwnd))
  Log ('[CAP] rect(now)={0},{1} {2}x{3} -> clip={4},{5} {6}x{7}' -f `
       $rr.Left, $rr.Top, ($rr.Right - $rr.Left), ($rr.Bottom - $rr.Top), $clip.X, $clip.Y, $clip.W, $clip.H)
  if ($clip.W -lt 200 -or $clip.H -lt 200) {
    Log '[WARN] 窗口矩形异常 (过小/屏外); 截图可能无效'
  }

  $res = [pscustomobject]@{ Primary = ''; Screen = ''; Pw = ''; Stats = $null }
  $dir = Split-Path -Parent $basePath
  $stem = [System.IO.Path]::GetFileNameWithoutExtension($basePath)

  $res.Screen = Join-Path $dir ($stem + '.png')
  $okScreen = Save-Shot $clip $res.Screen
  $stScreen = Get-ImageStats $res.Screen
  Log ('[CAP] screen : ok={0} nonblack={1}% uniq={2} sane={3}' -f $okScreen, $stScreen.NonBlackPct, $stScreen.UniqColors, $stScreen.Sane)

  $stPw = $null
  if (-not $NoPrintWindow) {
    $res.Pw = Join-Path $dir ($stem + '_pw.png')
    $okPw = Save-Shot-PW $hwnd $clip $res.Pw
    $stPw = Get-ImageStats $res.Pw
    Log ('[CAP] printwin: ok={0} nonblack={1}% uniq={2} sane={3}' -f $okPw, $stPw.NonBlackPct, $stPw.UniqColors, $stPw.Sane)
  }

  if ($stPw -and $stPw.Sane) { $res.Primary = $res.Pw; $res.Stats = $stPw }
  elseif ($stScreen.Sane) { $res.Primary = $res.Screen; $res.Stats = $stScreen }
  else { $res.Primary = $res.Screen; $res.Stats = $stScreen; Log '[WARN] 两条通道的像素体检均不理想, 仍以 screen 通道为准' }
  Log ('[CAP] primary = ' + $res.Primary)
  return $res
}

# ==================== 6. 导航 ====================
function Goto-PerfTab([object]$root, [object]$rect) {
  if (Uia-ResourceTitle $root) { Log '[NAV] already on Performance page'; return $true }
  # UIA 路线: 按 AutomationId / 名称找标签 (本机实测标签栏不暴露子元素, 多半走不通)
  $el = Uia-FindById $root 'PerformanceTab'
  if (-not $el) { $el = Uia-FindByName $root '性能' }
  if (-not $el) { $el = Uia-FindByName $root 'Performance' }
  if ($el) {
    $how = Uia-Activate $el
    if ($how) {
      Log ("[UIA] perf tab activated via $how")
      Start-Sleep -Milliseconds 900
      if (Uia-ResourceTitle $root) { return $true }
    }
  } else {
    Log '[UIA] perf tab not reachable by UIA (tab bar is custom-drawn)'
  }
  # 鼠标路线 (相对比例)
  $null = Click-Rel $rect $PerfTabX $PerfTabY 'Performance tab (mouse)'
  Start-Sleep -Milliseconds 1000
  if (Uia-ResourceTitle $root) { Log '[NAV] Performance page opened (mouse)'; return $true }
  Log '[NAV] Performance page NOT confirmed after mouse click'
  return $false
}

# 左侧列表项: 先用 UIA 元素矩形点中心, 失败再按比例兜底; 每次都读 resourceTitle 校验
function Goto-SidebarItem([object]$root, [object]$rect, [string]$which, [object]$el) {
  if ($el) {
    # v2: 性能页左侧资源列表很长 (18 逻辑核 + 磁盘 + 网络 + GPU), GPU 项常在可视区之外
    #     → 先用 ScrollItemPattern.ScrollIntoView() 把它滚进可视区
    try {
      $sp = $null
      if ($el.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern, [ref]$sp)) {
        ([System.Windows.Automation.ScrollItemPattern]$sp).ScrollIntoView()
        Log ("[NAV] $which item ScrollIntoView() ok")
        Start-Sleep -Milliseconds 500
      }
    } catch { Log ('[NAV] ScrollIntoView failed: ' + $_.Exception.Message) }

    # v2 关键修复: 【UIA 模式优先】。实测本机任务管理器侧栏项只支持 InvokePattern;
    #   Invoke 切页不依赖窗口 z-order/焦点 (2026-09-09 诊断: gpu_entry_0_0_92061
    #   Invoke 后 resourceTitle 由 [CPU] 变 [GPU], 窗口未最小化)。
    #   原先优先"鼠标点矩形中心", 窗口被前台锁挡住时会点到别的窗口, 实测还导致
    #   任务管理器被最小化 (iconic=True) → 截图与导航双失败。
    $how = Uia-Activate $el
    if ($how) {
      Log ("[UIA] sidebar $which activated via $how")
      Start-Sleep -Milliseconds 1200
      return
    }
    Log ("[NAV] $which item has no UIA pattern; fallback to mouse click")
    $br = $null
    try { $br = $el.Current.BoundingRectangle } catch {}
    if ($br -and $br.Width -gt 1) {
      $cx = [int]($br.X + $br.Width / 2); $cy = [int]($br.Y + $br.Height / 2)
      Log ("[NAV] $which item rect=({0},{1} {2}x{3}) -> click center ({4},{5})" -f `
           [int]$br.X, [int]$br.Y, [int]$br.Width, [int]$br.Height, $cx, $cy)
      $null = Click-At $cx $cy ("left-nav $which item (UIA rect)")
      Start-Sleep -Milliseconds 1100
      return
    }
  } else {
    Log ("[UIA] $which sidebar item not found in tree")
  }
  $fx = if ($which -eq 'cpu') { $PnlCpuX } else { $PnlGpuX }
  $fy = if ($which -eq 'cpu') { $PnlCpuY } else { $PnlGpuY }
  $null = Click-Rel $rect $fx $fy ("left-nav $which item (proportion)")
  Start-Sleep -Milliseconds 1100
}

function Goto-CpuItem([object]$root, [object]$rect) {
  # 本机实测: 性能页 CPU 列表项 = dashSidebarCpuButton (概览页同名元素也在同一棵树里)
  $el = Uia-FindById $root 'dashSidebarCpuButton'
  Goto-SidebarItem $root $rect 'cpu' $el
  if ((Uia-ResourceTitle $root) -match '^CPU') { Log '[NAV] CPU page confirmed'; return $true }
  # 再试一次 (列表可能刚重排)
  Log '[NAV] CPU page not confirmed; retry once'
  Goto-SidebarItem $root $rect 'cpu' $el
  if ((Uia-ResourceTitle $root) -match '^CPU') { Log '[NAV] CPU page confirmed (retry)'; return $true }
  return $false
}

function Goto-GpuItem([object]$root, [object]$rect) {
  # GPU 项 AutomationId 带硬件后缀 (gpu_entry_0_0_<id>), 用前缀匹配
  $el = $null
  try {
    $cond = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Button)
    $btns = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
    foreach ($b in $btns) {
      $aid = ''
      try { $aid = $b.Current.AutomationId } catch {}
      if ($aid -like 'gpu_entry_*') { $el = $b; break }
    }
  } catch {}
  Goto-SidebarItem $root $rect 'gpu' $el
  if ((Uia-ResourceTitle $root) -match 'GPU') { Log '[NAV] GPU page confirmed'; return $true }
  Log '[NAV] GPU page not confirmed; retry once'
  Goto-SidebarItem $root $rect 'gpu' $el
  if ((Uia-ResourceTitle $root) -match 'GPU') { Log '[NAV] GPU page confirmed (retry)'; return $true }
  return $false
}

# 切到"逻辑处理器"小图: 右键图区 -> 更改图表 -> 逻辑处理器
# 已知: 菜单无 UIA 子元素、无 Win32 菜单 → 只能鼠标注入, 且菜单有时不弹出(重试)
function Goto-LogicalGraph([object]$root, [object]$rect) {
  for ($try = 1; $try -le $MenuRetry; $try++) {
    $cx = [int]($rect.X + $rect.W * $MenuClickX)
    $cy = [int]($rect.Y + $rect.H * $MenuClickY)
    Log ("[NAV] right-click chart ($cx,$cy) attempt $try/$MenuRetry")
    [void](Right-Click-At $cx $cy)
    Start-Sleep -Milliseconds 1100

    $menu = Get-MenuPopup
    if (-not $menu) {
      Log '[NAV] context menu did not appear (custom-drawn menu; retry)'
      continue
    }
    Log ("[NAV] menu popup at {0},{1} {2}x{3}" -f [int]$menu.X, [int]$menu.Y, [int]$menu.Width, [int]$menu.Height)
    if ($Diag) {
      $dg = Join-Path $OutDir ('_diag_menu_' + (Get-Date -Format 'HHmmss') + '.png')
      $dm = Clamp-Rect ([int]$menu.X - 8) ([int]$menu.Y - 8) ([int]($menu.X + $menu.Width) + 300) ([int]($menu.Y + $menu.Height) + 8) $sm.PhysW $sm.PhysH
      if (Save-Shot $dm $dg) { Log ("[DIAG] menu crop -> $dg") }
    }
    # 一级: 更改图表 / Change graph to
    $null = Click-Rel $rect $MenuLvl1X $MenuLvl1Y 'menu level-1 (Change graph to)'
    Start-Sleep -Milliseconds 900
    # 二级: 逻辑处理器 / Logical processors
    $null = Click-Rel $rect $MenuLvl2X $MenuLvl2Y 'menu level-2 (Logical processors)'
    Start-Sleep -Milliseconds 1400
    return $true
  }
  Log '[NAV] could not open context menu (all attempts failed)'
  return $false
}

# ==================== 7. main ====================
$ROOT = Split-Path -Parent $PSCommandPath
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = $ROOT }
if (-not [System.IO.Path]::IsPathRooted($OutDir)) { $OutDir = Join-Path (Get-Location).Path $OutDir }
if (-not (Test-Path $OutDir)) {
  try { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
  catch { Log ('[ERROR] cannot create OutDir: ' + $OutDir + ' : ' + $_.Exception.Message); exit 1 }
}

$sm = Get-ScreenMetrics
Log ("[DPI] aware={0} physical={1}x{2} bounds={3}x{4} ratio={5:N3}" -f $sm.Aware, $sm.PhysW, $sm.PhysH,
     $sm.BoundsW, $sm.BoundsH, $sm.Ratio)
if ([Math]::Abs($sm.Ratio - 1.0) -gt 0.02) {
  Log ('[DPI] scaling detected (ratio={0:N3}) -> window rect will be divided by ratio' -f $sm.Ratio)
}

# ---- 找窗口; 没有就启动 (最多等 15s) ----
$tm = Find-Taskmgr
if (-not $tm) {
  $running = @(Get-Process -Name Taskmgr -ErrorAction SilentlyContinue).Count -gt 0
  if (-not $running -and -not $NoStart) {
    Log '[INFO] Taskmgr not running -> Start-Process taskmgr.exe'
    try { Start-Process -FilePath 'taskmgr.exe' | Out-Null }
    catch { Log ('NOWINDOW: taskmgr (start failed: ' + $_.Exception.Message + ')'); exit 1 }
  }
  $tm = Wait-Taskmgr 15
}
if (-not $tm) { Log 'NOWINDOW: taskmgr'; exit 1 }

$hwnd = $tm.MainWindowHandle
Log ("[WINDOW] title={0} hwnd={1} pid={2}" -f $tm.MainWindowTitle, $hwnd, $tm.Id)

# ---- 唤醒 + 置顶 (v2): 任务管理器可能被最小化(rect=-32000)且前台锁会拒绝 SetForegroundWindow ----
function Wake-Window([object]$h) {
  if ([TmWin32]::IsIconic([IntPtr]$h)) {
    Log '[WIN] minimized -> ShowWindow(SW_RESTORE)'
    [void][TmWin32]::ShowWindow([IntPtr]$h, 9)
    Start-Sleep -Milliseconds 700
  }
  if (-not [TmWin32]::IsWindowVisible([IntPtr]$h)) {
    Log '[WIN] not visible -> ShowWindow(SW_SHOW)'
    [void][TmWin32]::ShowWindow([IntPtr]$h, 5)
    Start-Sleep -Milliseconds 500
  }
  # 前台锁破解: 先 SendInput 一次 ALT 松开 (系统认为发生了用户输入), 再 SetForegroundWindow
  try {
    [TmWin32]::keybd_event(0x12, 0, 0, [IntPtr]::Zero)      # VK_MENU down
    [TmWin32]::keybd_event(0x12, 0, 2, [IntPtr]::Zero)      # VK_MENU up
    Start-Sleep -Milliseconds 80
  } catch {}
  [void][TmWin32]::BringWindowToTop([IntPtr]$h)
  [void][TmWin32]::SetForegroundWindow([IntPtr]$h)
  Start-Sleep -Milliseconds 400
  if (-not $NoTopMost) {
    # HWND_TOPMOST=-1, SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW = 0x0002|0x0001|0x0040
    $okTop = [TmWin32]::SetWindowPos([IntPtr]$h, [IntPtr](-1), 0, 0, 0, 0, 0x0043)
    Log ('[WIN] SetWindowPos(HWND_TOPMOST)={0}' -f $okTop)
    Start-Sleep -Milliseconds 300
  }
  $fg = [TmWin32]::GetForegroundWindow()
  Log ('[WIN] foreground={0} is_tm={1}' -f $fg, ($fg -eq [IntPtr]$h))
  if ($fg -ne [IntPtr]$h) {
    Log '[WARN] SetForegroundWindow 未生效 (前台锁); 已用 HWND_TOPMOST 保证窗口绘制在最上层'
  }
}
Wake-Window $hwnd

$r = New-Object 'TmWin32+RECT'
[void][TmWin32]::GetWindowRect([IntPtr]$hwnd, [ref]$r)
if ($r.Left -lt -10000) {
  Log '[WIN] rect 仍在屏外(疑似最小化未恢复); 再试 SW_RESTORE + SW_SHOW'
  [void][TmWin32]::ShowWindow([IntPtr]$hwnd, 9)
  [void][TmWin32]::ShowWindow([IntPtr]$hwnd, 5)
  Start-Sleep -Milliseconds 800
  [void][TmWin32]::GetWindowRect([IntPtr]$hwnd, [ref]$r)
}
$rawL = $r.Left; $rawT = $r.Top; $rawR = $r.Right; $rawB = $r.Bottom
Log ("[RECT] raw left={0} top={1} right={2} bottom={3} w={4} h={5}" -f $rawL, $rawT, $rawR, $rawB,
     ($rawR - $rawL), ($rawB - $rawT))

if ([Math]::Abs($sm.Ratio - 1.0) -gt 0.02) {
  $inv = 1.0 / $sm.Ratio
  $rawL = [int][Math]::Round($rawL * $inv); $rawT = [int][Math]::Round($rawT * $inv)
  $rawR = [int][Math]::Round($rawR * $inv); $rawB = [int][Math]::Round($rawB * $inv)
  Log ("[RECT] logical left={0} top={1} right={2} bottom={3}" -f $rawL, $rawT, $rawR, $rawB)
}

if ($FullScreen) {
  $clip = Clamp-Rect $sm.BoundsX $sm.BoundsY ($sm.BoundsX + $sm.BoundsW) ($sm.BoundsY + $sm.BoundsH) $sm.PhysW $sm.PhysH
  Log ("[RECT] FULLSCREEN x={0} y={1} w={2} h={3}" -f $clip.X, $clip.Y, $clip.W, $clip.H)
} else {
  $clip = Clamp-Rect $rawL $rawT $rawR $rawB $sm.PhysW $sm.PhysH
  Log ("[RECT] CLIPPED x={0} y={1} w={2} h={3}" -f $clip.X, $clip.Y, $clip.W, $clip.H)
}

$root = $null
if ($UiaReady) {
  try { $root = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd) }
  catch { Log ('[UIA] FromHandle failed: ' + $_.Exception.Message) }
}
$before = Get-ViewState $root
Log ("[STATE] before: page={0} logical={1} panes={2} gpu={3} title=[{4}]" -f `
     $before.Page, $before.Logical, $before.LogicalPanes, $before.Gpu, $before.ResourceTitle)
$perfOk = Goto-PerfTab $root $clip
if (-not $perfOk) { Log '[WARN] Performance page not confirmed; continuing anyway' }

$views = if ($View -eq 'both') { @('cpu', 'gpu') } else { @($View) }
$shots = @{}
foreach ($v in $views) {
  Log ("=== view: {0} ===" -f $v)
  if ($v -eq 'cpu') {
    [void](Goto-CpuItem $root $clip)
    Start-Sleep -Milliseconds 1000
    $st = Get-ViewState $root
    if (-not $st.Logical) {
      # 还不是逻辑处理器视图 → 走右键菜单 (更改图表 -> 逻辑处理器)
      [void](Goto-LogicalGraph $root $clip)
      $st = Get-ViewState $root
    } else {
      Log '[NAV] already in logical-processor view; skip graph-type menu'
    }
    Start-Sleep -Milliseconds 1500     # 图表 1s 刷新一次, 等波形有内容
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $path = Join-Path $OutDir ("tm_cpu_" + $Tag + "_" + $stamp + ".png")
    $cap = Capture-Window $hwnd $path
    $shots['cpu'] = ($cap.Primary -ne '')
    if ($shots['cpu']) {
      Log ("[SHOT] $($cap.Primary)")
      Log ("[SIZE] {0}x{1}" -f $clip.W, $clip.H)
    }
    $st = Get-ViewState $root
    if ($st.Logical -and $st.Page -eq 'performance') {
      Log ("VIEW=cpu(logical) panes={0} title=[{1}]" -f $st.LogicalPanes, $st.ResourceTitle)
    } else {
      Log 'NAV_FAIL: cpu logical-processor view not reached'
      Log ("VIEW=unknown(page={0} title=[{1}])" -f $st.Page, $st.ResourceTitle)
    }
  } else {
    [void](Goto-GpuItem $root $clip)
    Start-Sleep -Milliseconds 1500
    $st = Get-ViewState $root
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $path = Join-Path $OutDir ("tm_gpu_" + $Tag + "_" + $stamp + ".png")
    $cap = Capture-Window $hwnd $path
    $shots['gpu'] = ($cap.Primary -ne '')
    if ($shots['gpu']) {
      Log ("[SHOT] $($cap.Primary)")
      Log ("[SIZE] {0}x{1}" -f $clip.W, $clip.H)
    }
    if ($st.Gpu) {
      Log ("VIEW=gpu title=[{0}]" -f $st.ResourceTitle)
    } else {
      Log 'NAV_FAIL: gpu view not reached'
      Log ("VIEW=unknown(page={0} title=[{1}])" -f $st.Page, $st.ResourceTitle)
    }
  }
}

# ---- 收尾: 取消置顶 (HWND_NOTOPMOST=-2), 避免任务管理器一直压在用户其他窗口之上 ----
if (-not $NoTopMost) {
  try {
    [void][TmWin32]::SetWindowPos([IntPtr]$hwnd, [IntPtr](-2), 0, 0, 0, 0, 0x0043)
    Log '[WIN] HWND_NOTOPMOST restored'
  } catch {}
}

# ---- 退出码: 0 = 至少产出一张 PNG ----
$anyShot = $false
foreach ($v in $views) { if ($shots[$v]) { $anyShot = $true } }
if ($anyShot) { exit 0 } else { Log '[ERROR] no PNG produced'; exit 1 }
