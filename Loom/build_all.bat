@echo off
REM ====================================================================
REM build_all.bat - Loom DLL 化战役 M1 统一构建入口 (2026-09-08)
REM
REM 职责 (报告 M1 扩容版):
REM   1. 锁定 MSVC 工具链 (VS2022 Community vcvars64, 与 ckernels 同源)
REM   2. 一键重编全部 DLL (当前: ckernels + core_components/module_ref + pipeline 及测试靶)
REM   3. 一键跑全量对拍网 (tests\_tmp 下纳管探针; 当前活跃 21 个 + 0 注释)
REM   4. 任何一步失败立即报错退出 (exit code != 0)
REM
REM ★编码 (2026-09-08 实测): 本文件与 5 个 build_*.bat 均为 UTF-8 无 BOM
REM   (cp936 解码直接报 illegal multibyte sequence, 即非 GBK), 故一律保持
REM   UTF-8 写入; 不要用 GBK 另存, 否则中文注释与既有文本全部乱码。
REM   注: 默认 936 代码页控制台里中文注释显示为乱码, 但不影响 bat 执行
REM   (UTF-8 续字节 0x80-0xBF 与 ASCII 特殊字符不冲突, 已实测 EXIT=0)。
REM
REM ★bat 解析坑 (2026-09-08 实测): 本项目路径含括号 "Loom(py源代码-工作区)",
REM   含括号变量在 if (...) 括号块内展开会提前闭合块结构 — 实锤报错
REM   "\Loom\ckernels\build_ckernels.bat was unexpected at this time."
REM   对策: 全脚本不用含括号的变量做二次展开; 开头 cd /d "%~dp0" 定位后,
REM   其余一律相对路径; 错误分支改用单行 if ... goto (无括号块)。
REM
REM 约定: 新增 DLL 时在 [DLL 清单] 段加一行 call :build_dll <子目录> <bat名>;
REM       新增对拍探针在 [对拍清单] 段加一行。CMake 迁移待 DLL>=4 (报告 v1.1)。
REM 用法: 双击 或 cmd /c "build_all.bat [skip_checks]"   (skip_checks=只编译)
REM ====================================================================
setlocal
cd /d "%~dp0"
echo [build_all] engine root = %CD%

REM ---- 锁 MSVC 工具链 ----
set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" goto :novcvars
call "%VCVARS%" >nul 2>&1
if errorlevel 1 goto :vcfail
echo [build_all] MSVC toolchain OK

REM ====================================================================
REM [DLL 清单] 每行: call :build_dll <相对子目录> <构建bat文件名>
REM 构建 bat 自身负责 cl 参数 (ckernels 惯例: /O2 /LD /MD, 禁 fp:fast)
REM ====================================================================
set DLL_FAIL=0
call :build_dll ckernels build_ckernels.bat
if not "%DLL_FAIL%"=="0" goto :fail
call :build_dll core_components build_ref.bat
if not "%DLL_FAIL%"=="0" goto :fail
call :build_dll core_components build_badvector.bat
if not "%DLL_FAIL%"=="0" goto :fail
call :build_dll core_components build_ambiguous.bat
if not "%DLL_FAIL%"=="0" goto :fail
call :build_dll core_components\pipeline build_pipeline.bat
if not "%DLL_FAIL%"=="0" goto :fail
call :build_dll core_components\script build_script.bat
if not "%DLL_FAIL%"=="0" goto :fail

REM ---- (M2+ 在此追加: call :build_dll core_components\pipeline build_pipeline.bat) ----

echo [build_all] all DLL builds OK

REM ---- registry.json sha256 回填: DLL 已用 /Brepro 可复现重编, 此处把
REM      三个官方组件的真实 SHA256 钉进 registry.json (审计 P13: 空 sha = 放行,
REM      非空 = 加载器强制比对)。必须放在 skip_checks 判断之前, 保证只编译也回填。
echo [build_all] ---- refresh registry.json sha256 ----
py -3.12 "tests\_tmp\refresh_registry_sha.py"
if errorlevel 1 goto :fail

REM ---- A1 生成 official_manifest.py (官方件出厂基准, 编译进 exe; 必须在 refresh 之后) ----
echo [build_all] ---- generate official_manifest.py ----
py -3.12 "tests\_tmp\gen_official_manifest.py"
if errorlevel 1 goto :fail

if "%~1"=="skip_checks" (
  echo [build_all] skip_checks=1, 对拍网跳过
  exit /b 0
)

REM ====================================================================
REM [对拍清单] 一行一个探针 (tests\_tmp 下, 须 exit 0 = 全 PASS)
REM ====================================================================
set CHECK_FAIL=0
call :run_check ckernels_val_check.py
call :run_check collide_val_check.py
call :run_check aabb_f32_check.py
REM ---- M1 新增 (DLL 契约层) ----
call :run_check accept1_e2e_check.py
call :run_check module_contract_check.py
call :run_check module_registry_check.py
call :run_check module_fuzz_check.py
call :run_check pipeline_prep_check.py
call :run_check crash_reporter_check.py
REM ---- M2 新增 (pipeline.dll) ----
call :run_check pipeline_val_check.py
call :run_check pipeline_base_check.py
call :run_check engine_pipeline_check.py
call :run_check pipeline_fuzz_check.py
call :run_check pipeline_world_check.py
call :run_check pipeline_e2e_check.py
call :run_check percore_check.py
REM ---- M2 验收②: 编辑器基线口径 A/B (较重: 启动编辑器两次, 约 2 分钟; 判据 [GATE-ACCEPT2]/[GATE-REGRESSION]) ----
call :run_check editor_core_check.py --both
REM ---- M2 验收③: 编译版 pipeline ON/OFF FPS A/B (较重: 启动编译版两次, 约 2.5 分钟; 无编译版自动 SKIP) ----
call :run_check compiled_verify.py --both
REM ---- M3 主线程分段归因 (较重: 启动编辑器一次, 约 40 秒; 判据=分段闭合 ok + 帧计数增长) ----
call :run_check mt_profile_check.py --mode on --secs 8
REM ---- M3-N4: interp_pose C 实现逐位对拍 (纯计算, 秒级) ----
call :run_check interp_pose_check.py
REM ---- M3: pack_bucket C 实现逐位对拍 (纯计算, 秒级) ----
call :run_check pack_bucket_check.py
REM ---- M3: physics dirty_mask/local_matrices C 实现逐位对拍 (纯计算, 秒级) ----
call :run_check physics_c_check.py
REM ---- M4: script batch_rotate/batch_move C 实现逐位对拍 (纯计算, 秒级) ----
call :run_check script_val_check.py
REM ---- M4: physics.dll pre_step/post_step/substep_loop C 实现逐位对拍 (纯计算, 秒级) ----
call :run_check physics_dll_val_check.py
if not "%CHECK_FAIL%"=="0" goto :fail

echo.
echo [build_all] ======== ALL PASS ========
exit /b 0

:novcvars
echo [build_all] FATAL: vcvars64.bat not found
echo [build_all] 要求 VS2022 Community, 路径见 VCVARS 变量
exit /b 2

:vcfail
echo [build_all] FATAL: vcvars64 call failed
exit /b 2

:fail
echo.
echo [build_all] ======== BUILD/CHECK FAILED ========
exit /b 1

REM ---- 子例程: 编译一个 DLL 子目录 (相对路径, 无括号块) ----
:build_dll
set "SUBDIR=%~1"
set "BATNAME=%~2"
echo.
echo [build_all] ---- building %SUBDIR% ----
if not exist "%SUBDIR%\%BATNAME%" goto :dll_missing
pushd "%SUBDIR%"
call .\%BATNAME%
if errorlevel 1 goto :dll_build_fail
popd
exit /b 0
:dll_missing
echo [build_all] WARN: build bat missing: %SUBDIR%\%BATNAME% - 跳过该 DLL
exit /b 0
:dll_build_fail
echo [build_all] FAILED: %SUBDIR%
popd
set DLL_FAIL=1
exit /b 1

REM ---- 子例程: 跑一个对拍探针 (须 exit 0 = 全 PASS) ----
REM ★M2b 改: 转发额外参数 %2 %3 (单行无括号块, 不触发含括号路径解析坑),
REM   否则 `call :run_check editor_core_check.py --both` 的 --both 会被吞掉,
REM   变成只跑单档 → 拿不到 [GATE-ACCEPT2]/[GATE-REGRESSION] 判定行。
:run_check
echo.
echo [build_all] ---- check %~1 %2 %3 ----
py -3.12 "tests\_tmp\%~1" %2 %3
if errorlevel 1 echo [build_all] CHECK FAILED: %~1 %2 %3
if errorlevel 1 set CHECK_FAIL=1
exit /b 0