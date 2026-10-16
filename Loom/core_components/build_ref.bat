@echo off
REM build_ref.bat - 编译契约参考实现 module_ref.dll (契约头编译闸门)
REM 与 ckernels\build_ckernels.bat 同款工具链/参数 (/O2 /LD /MD)
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
cd /d "%~dp0"
REM /Brepro: 链接器可复现构建 (PE 时间戳/校验和/调试路径确定化) — 同一源码重编产物逐字节相同
cl /nologo /utf-8 /O2 /Brepro /LD /MD loom_module_ref.c /Fe:module_ref.dll /Fo:loom_module_ref.obj /I.
if errorlevel 1 (
  echo BUILD_FAILED
  exit /b 1
)
echo BUILD_OK
del loom_module_ref.obj >nul 2>&1
exit /b 0
