@echo off
REM build_badvector.bat - 编译 M1-5 模糊测试坏靶 badvector.dll (绝不发行)
REM 与 build_ref.bat 同款工具链/参数 (/O2 /LD /MD; 不用 /fp:fast)
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
pushd "%~dp0"
REM /Brepro: 链接器可复现构建 (PE 时间戳/校验和/调试路径确定化) — 同一源码重编产物逐字节相同
cl /nologo /utf-8 /O2 /Brepro /LD /MD .\badvector.c /Fe:.\badvector.dll /Fo:.\badvector.obj /I.
if errorlevel 1 (
  echo BUILD_FAILED
  popd
  exit /b 1
)
del .\badvector.obj >nul 2>&1
popd
echo BUILD_OK
exit /b 0
