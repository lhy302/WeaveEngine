@echo off
REM build_ckernels.bat - MSVC 编译 loom_kernels.dll (O2 + OpenMP, 禁 fp:fast 保求和序)
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
cd /d "%~dp0"
REM /Brepro: 链接器可复现构建 (PE 时间戳/校验和/调试路径确定化) — 同一源码重编产物逐字节相同
cl /nologo /utf-8 /O2 /Brepro /LD /MD loom_kernels.c /Fe:loom_kernels.dll /Fo:loom_kernels.obj
if errorlevel 1 (
  echo BUILD_FAILED
  exit /b 1
)
echo BUILD_OK
del loom_kernels.obj >nul 2>&1
exit /b 0
