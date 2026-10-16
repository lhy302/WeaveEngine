@echo off
chcp 65001 >nul
if not defined VSCMD_VER (
  call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
)
pushd "%~dp0..\.."
cl /nologo /utf-8 /O2 /Brepro /LD /MD .\core_components\physics\loom_physics.c /Fe:.\core_components\physics\physics.dll /Fo:.\core_components\physics\loom_physics.obj /I.\core_components
if errorlevel 1 (
  echo BUILD_FAILED
  popd
  exit /b 1
)
del .\core_components\physics\loom_physics.obj >nul 2>&1
popd
echo BUILD_OK
exit /b 0
