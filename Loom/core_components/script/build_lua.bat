@echo off
chcp 65001 >nul
if not defined VSCMD_VER (
  call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
)
pushd "%~dp0"
cl /nologo /utf-8 /MD /O2 /Brepro /c /DLUA_COMPAT_5_3 lua_src\lapi.c lua_src\lauxlib.c lua_src\lbaselib.c lua_src\lcode.c lua_src\lcorolib.c lua_src\lctype.c lua_src\ldblib.c lua_src\ldebug.c lua_src\ldo.c lua_src\ldump.c lua_src\lfunc.c lua_src\lgc.c lua_src\linit.c lua_src\liolib.c lua_src\llex.c lua_src\lmathlib.c lua_src\lmem.c lua_src\loadlib.c lua_src\lobject.c lua_src\lopcodes.c lua_src\loslib.c lua_src\lparser.c lua_src\lstate.c lua_src\lstring.c lua_src\lstrlib.c lua_src\ltable.c lua_src\ltablib.c lua_src\ltm.c lua_src\lundump.c lua_src\lutf8lib.c lua_src\lvm.c lua_src\lzio.c /Ilua_src
if errorlevel 1 (
  echo LUA_COMPILE_FAILED
  popd
  exit /b 1
)
lib /nologo /out:lua54.lib *.obj
if errorlevel 1 (
  echo LUA_LIB_FAILED
  popd
  exit /b 1
)
del *.obj >nul 2>&1
echo LUA_BUILD_OK
popd
exit /b 0
