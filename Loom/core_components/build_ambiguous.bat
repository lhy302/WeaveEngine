@echo off
REM build_ambiguous.bat - 编译 M1-2 校6 歧义注入靶 ambiguous.dll (绝不发行)
REM 与 build_ref.bat 同款工具链/参数 (/O2 /LD /MD; 不用 /fp:fast)
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
pushd "%~dp0"
REM /Brepro: 链接器可复现构建 (PE 时间戳/校验和/调试路径确定化) — 同一源码重编产物逐字节相同
cl /nologo /utf-8 /O2 /Brepro /LD /MD .\ambiguous.c /Fe:.\ambiguous.dll /Fo:.\ambiguous.obj /I.
if errorlevel 1 (
  echo BUILD_FAILED
  popd
  exit /b 1
)
del .\ambiguous.obj >nul 2>&1
popd
echo BUILD_OK
exit /b 0
