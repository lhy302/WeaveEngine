@echo off
chcp 65001 >nul
if not defined VSCMD_VER (
  call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
)
pushd "%~dp0"
if not exist "lua54.lib" (
  call build_lua.bat
)
popd
pushd "%~dp0..\.."
cl /nologo /utf-8 /O2 /Brepro /LD /MD .\core_components\script\loom_script.c .\core_components\script\lua54.lib /Fe:.\core_components\script\script.dll /Fo:.\core_components\script\loom_script.obj /I.\core_components /I.\core_components\script\lua_src
if errorlevel 1 (
  echo BUILD_FAILED
  popd
  exit /b 1
)
del .\core_components\script\loom_script.obj >nul 2>&1
popd
echo BUILD_OK
exit /b 0
