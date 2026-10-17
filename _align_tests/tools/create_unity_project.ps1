# create_unity_project.ps1 — 创建 Unity 对照项目 (一次性)
# 用法: 右键"使用 PowerShell 运行" 或 pwsh -File create_unity_project.ps1
$UnityExe = "E:\Program Files\Unity\2022.3.62f3c1\Editor\Unity.exe"
$ProjPath = "E:\UnityAlign\AlignProject"

if (Test-Path $ProjPath) {
    Write-Host "项目已存在: $ProjPath" -ForegroundColor Yellow
    exit 0
}

Write-Host "创建 Unity 项目: $ProjPath ..." -ForegroundColor Cyan
& $UnityExe -batchmode -quit -createProject $ProjPath -logFile "E:\UnityAlign\create.log"

if (Test-Path (Join-Path $ProjPath "Assets")) {
    Write-Host "创建成功。下一步: 把 _align_tests/tools/AlignRunner.cs 复制到 $ProjPath\Assets\Editor\" -ForegroundColor Green
} else {
    Write-Host "创建失败，见 E:\UnityAlign\create.log" -ForegroundColor Red
}
