@echo off
REM build_pipeline.bat - 编译 pipeline.dll (M2a 逻辑帧 prep 链, 2026-09-08)
REM 与 build_ref.bat 同款工具链/参数 (/O2 /LD /MD; 不用 /fp:fast 保求和序)
REM 注: loom_pipeline.c 内 #include "../core_components/loom_module.h" 是相对
REM     引擎根解析的, 故本脚本先 cd 到引擎根再编译 (含括号路径用引号)。
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
pushd "%~dp0..\.."
REM /Brepro: 链接器可复现构建 (PE 时间戳/校验和/调试路径确定化) — 同一源码重编产物逐字节相同
cl /nologo /utf-8 /O2 /Brepro /LD /MD .\core_components\pipeline\loom_pipeline.c /Fe:.\core_components\pipeline\pipeline.dll /Fo:.\core_components\pipeline\loom_pipeline.obj /I.\core_components
if errorlevel 1 (
  echo BUILD_FAILED
  popd
  exit /b 1
)
del .\core_components\pipeline\loom_pipeline.obj >nul 2>&1
popd
echo BUILD_OK
exit /b 0
