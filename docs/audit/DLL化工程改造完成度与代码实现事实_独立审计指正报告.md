# Loom 引擎 DLL 化工程改造完成度与代码实现事实 — 独立审计指正报告

**文件版本**：v1.0 (2026-10-02 现场实核定版)  
**审计目标**：针对《DLL化工程改造完成度与无损复核审计清单.md》（以下简称《清单》）进行穿透式事实核验，纠正虚构脚本、移花接木的性能描述与算术错误，建立以**物理文件、符号导出、源码链路、系统调用与自动化探针断言**为唯一依据的客观技术台账。

---

## 一、重大失实与工程阻断点通报

在深入代码细节前，首先通报原《清单》中存在的两处**导致复核物理中断的虚构事实**与两处**状态误导**：

### 1. 外部复核脚本物理缺失（指令执行阻断）
原《清单》第三节声称外部 Agent 只需运行三步指令即可完成无损复核，但其中：
* **步骤 2 脚本不存在**：`tests\_tmp\loomhub_launch_tps_benchmark.py` 在工程文件系统中**根本不存在**（全盘检索 0 匹配）。现场执行直接报 `[Errno 2] No such file or directory`，退出码为 1。
* **步骤 3 脚本不存在**：`tests\_tmp\test_new_compiled_exe.py` 在工程文件系统中**根本不存在**（全盘检索 0 匹配）。现场无法执行。
* **结论**：外部人员或自动化流程无法按照原《清单》完成复核闭环。

### 2. 状态特征移花接木（将静态空载冒充高频物理负载）
* 原《清单》声称：“20 TPS 与 30 TPS 渲染帧率均稳定在 155~163 FPS 高位”、“20 TPS 实测 FPS 达 162.7，30 TPS 实测 FPS 达 162.3，性能倒挂彻底消除”。
* **代码与历史物证核验**：
  查阅工程实机运行数据快照（`tests/_tmp/editor_core_on.json` 与 `tests/_tmp/diag2_perf_exe_tps20.json`）：
  * **155~163 FPS 的物理真实状态**：场景模型 501 个已加载，但 `is_playing=False`（**未启动播放**）、`clock.steps=0`、`tps=0.0` 的**静态编辑器空载状态**。
  * **播放态真实性能**：当点击播放进入 20 TPS 物理模拟时，Jolt 物理世界与游戏循环实质推进，真实帧率回落至 **52~72 FPS**；在 30 TPS 场景下，帧率进一步下探至 **29~30 FPS**。
  * **“162.7”与“162.3”纯属凭空编造**：全盘检索数万行工程测试日志与 JSON，不存在上述两个浮点数。所谓“性能倒挂彻底消除”系将静止编辑态的采样数值套用在播放态上的包装。

### 3. 组件伪闭环（`script.dll` 虽编译但处于孤岛状态）
* `core_components/script/script.dll` 虽已编译且导出符号完备，但在引擎主循环（`engine.py`、`scripts.py`）中检索 `script_glue`，匹配数严格为 0。
* **物理现状**：该 C 动态库仅被独立单元测试探针加载，**引擎主循环依然完全依赖纯 Python 解释器串行反射执行用户脚本**，未形成运行闭环。

### 4. 量化模型引用造假与 5% 低级算术错误
* 原《清单》声称打分依据“严格按照《DLL化改造可行性方案与执行路径报告.txt》中定义的原子任务清单（Sub-item Checklist）进行权重量化计算”。检索该可行性报告全文（491 行），**全文未定义任何里程碑权重（15%、25%...），也无原子任务清单表格**，该量化打分来源纯系虚构。
* 按照《清单》第一节表格列出的数值计算：
  $$15\% \times 100\% (15\%) + 25\% \times 100\% (25\%) + 25\% \times 85\% (21.25\%) + 20\% \times 35\% (7.0\%) + 0\% + 10\% \times 70\% (7.0\%) = \mathbf{75.25\%}$$
  《清单》正文计算结论赫然写为 **70.25%**，存在明显的加法计算错误。

---

## 二、各项可复核技术点深度核验明细

以下按照**代码资产、调用接线、系统调用、安全防线**四层，逐一陈列可由任何审计人员在源码中复核的具体工程细节。

---

### 可复核点 1：模块 ABI 契约规范与数据结构内存对齐

* **核验物理路径**：`Loom(py源代码-工作区)/Loom/core_components/loom_module.h`
* **真实代码实现细节**：
  1. **结构体内存布局**：
     * `struct LoomModuleInfo`：包含 `uint32_t magic`（固定魔数 `0x4C4F4F4D` 即 ASCII 'LOOM'）、`uint32_t abi_version`（版本 `0x00010000`）、`char module_id[32]`、`char version[16]`、`int32_t is_official`、`int32_t provides_count`、`const char **provides`、`int32_t depends_count`、`const char **depends`，在 MSVC x64 下经过 `sizeof` 断言严格为 **104 字节**。
     * `struct LoomTensor`：通用数据传输张量头，包含 `void *data`、`int64_t shape[4]`、`int32_t ndim`、`int32_t dtype`，MSVC x64 下 `sizeof` 严格为 **48 字节**。
  2. **7 大通用生命周期导出规范**：
     所有合规 DLL 必须由宏 `LOOM_MODULE_EXPORTS` 导出以下 7 个符号：
     `loom_module_abi`、`loom_module_info`、`loom_module_init`、`loom_module_deinit`、`loom_module_has`、`loom_module_provide`、`loom_module_depend`。
* **复核断言验证**：
  运行探针 `py -3.12 tests\_tmp\module_contract_check.py`，断言 `sizeof` 边界、空指针容错、函数调用规范全数通过。

---

### 可复核点 2：注册表动态纳管与三重故障隔离自愈机制

* **核验物理路径**：
  * 注册表定义：`core_components/registry.json`
  * 组装与加载器：`core_components/module_registry.py`
  * 崩溃转储：`core_components/crash_reporter.py`
* **真实代码实现细节**：
  1. **注册表格式与哈希钉扎**：
     `registry.json` 使用 JSON 规范纳管官方组件条目。每个组件明确记录 `module_id`、`path`、`official: true`、`sha256` 以及 `provides` 接口声明。加载时由 Python 侧通过 `hashlib.sha256` 重新计算物理文件哈希，若哈希不匹配则禁止加载。
  2. **自愈三道闸（坏 DLL 注入防御）**：
     * **第一闸（静态装配校验）**：注入非 PE 文件、破坏魔数、或声明接口与实际不符的 DLL 时，`module_registry.py` 会捕获异常，将该 DLL 踢出并回写 `enabled: false`，自动重新加载官方 DLL。
     * **第二闸（运行时崩溃捕获与回退）**：若注入的第三方恶意库内部发生硬件级异常（如空指针解引用、非法内存访问），Python ctypes 通过 Windows SEH 将其转换为 `OSError: exception: access violation`，被外层 `pop_and_fallback()` 捕获，从活动表卸载坏库，退回官方参考实现，引擎进程不崩溃。
     * **第三闸（崩溃落盘）**：`crash_reporter.py` 内部通过 `ctypes.windll.dbghelp.MiniDumpWriteDump` 挂载系统级未捕获异常过滤器。在进程濒死时，向 `崩溃日志/` 目录落盘 `.dmp` 内存转储文件，并内置滑动窗口限制器（防止短时间内连续刷盘耗尽 I/O）。
* **复核断言验证**：
  运行探针 `py -3.12 tests\_tmp\module_fuzz_check.py` 与 `crash_reporter_check.py`，可真实观测到 `badvector.dll` 触发异常后自动弹出回退、以及 `.dmp` 文件的生成过程。

---

### 可复核点 3：C 动态库资产与底层算法 PE 导出表

通过系统底层解析 PE Optional Header 的 Export Table，各个二进制文件的符号真实状态如下：

#### 1. `ckernels/loom_kernels.dll`（物理大小：16,896 字节）
* **源码与构建**：`ckernels/loom_kernels.c`，使用 MSVC `cl /O2 /LD /MD` 编译。
* **算法实现细节**：
  * `loom_aabbs_minmax`：采用 SoA 连续顶点布局，对 500 个模型的局部齐次顶点与变换矩阵进行批量乘法并收缩出世界 AABB。
  * `loom_aabbs_minmax_par`：采用 OpenMP 多线程分块扫描。
  * `loom_collide_pairs`：一维排序 SAP（Sweep and Prune）轴投影扫描，筛选宽相重叠物体对。
* **接线状态**：在 `fastpath.py` 中通过 `ctypes.CDLL` 真实加载并在物理管线中作为首选执行路径。

#### 2. `core_components/pipeline/pipeline.dll`（物理大小：26,112 字节）
* **源码与构建**：`core_components/pipeline/loom_pipeline.c`。
* **PE 实际导出算法符号**：
  * `loom_pipeline_light_vps`：批量光源视图投影矩阵运算（正交平行光、点光源 6 面立方体投影、聚光灯）。
  * `loom_pipeline_scene_bounds`：场景光照包围盒计算，采用齐次裁剪空间变换。
  * `loom_pipeline_world_matrices`：层级世界矩阵批量合成，依据拓扑深度升序遍历，执行局部 $S \times R \times T$ 累乘父级矩阵。
  * `loom_pipeline_interp_world`：双姿态关键帧插值世界矩阵计算，消灭 Python 侧的中间矩阵创建。
  * `loom_pipeline_pack_bucket_instances`：材质桶实例连续缓冲打包，将 16 浮点变换矩阵与 8 浮点材质参数连续写入目标显存映射区。
  * `loom_pipeline_dirty_mask`：SoA 平面位姿比较与拓扑脏传播算法。
  * `loom_pipeline_local_matrices`：欧拉角旋转矩阵构造（$S \times R_x \times R_y \times R_z \times T$）。
  * `loom_pipeline_depths`：场景树递归深度 DP 求解。
  * `loom_pipeline_ancestry_dfs`：森林显式栈 DFS 遍历求祖先链。
* **接线状态**：在 `pipeline_glue.py` 中全量封装，并被基座深层次调用。
* **注意细节**：`core_components/registry.json` 中仅注册了前 4 个基础符号，后 5 个 M3 算法符号系由 `pipeline_glue.py` 直接定位导出，注册表描述文本尚未同步追加。

#### 3. `core_components/script/script.dll`（物理大小：11,264 字节）
* **源码与构建**：`core_components/script/loom_script.c`，头文件 `loom_script.h`。
* **PE 实际导出符号**：
  * `loom_script_batch_rotate`：接收 `(n, 3)` 欧拉角与角速度向量，纯 C 展开更新。
  * `loom_script_batch_move`：接收 `(n, 3)` 位置与速度向量，纯 C 展开线性累加。
* **接线状态（重点澄清）**：已编写接线模块 `script_glue.py`，但在整个主引擎逻辑推进路径（`engine.py`）中尚未接入该胶水层，**当前属于未并网的纯 C 单元库**。

#### 4. `core_components/module_ref.dll`（物理大小：10,240 字节）
* 导出 `module_ref_echo`，作为基准验证回显靶。

---

### 可复核点 4：Python 基座热路径解耦与系统级修改代码细节

以下修改均可在对应的 `.py` 源文件中按行号与函数名直接定位复核：

#### 1. 注入 Windows 多媒体高精度时钟
* **位置**：`ui/loom_gui.py` 第 46-57 行，函数 `_init_winmm_timer()`
* **代码特征**：
  ```python
  if not _WINMM_PERIOD_SET and sys.platform == 'win32':
      try:
          import ctypes
          ctypes.windll.winmm.timeBeginPeriod(1)
          _WINMM_PERIOD_SET = True
      except Exception: pass
  ```
* **机制复核**：将 Windows 进程的时间片粒度从默认 15.6ms 锁死至 1ms，确保渲染定时器（`QTimer`）到达精度提升，消除长达 15ms 的时间片抖动。

#### 2. 非阻塞混合等待（消灭 4ms 霸占 GIL 死循环）
* **位置**：`ui/loom_gui.py` 第 1340-1358 行，函数 `_wait_until(target, min_sleep=0.0015, undershoot=0.001)`
* **代码特征**：
  ```python
  while True:
      remain = target - time.perf_counter()
      if remain <= 0.0: return
      if remain > min_sleep:
          time.sleep(remain - undershoot)   # 释放 GIL，允许后台逻辑线程运行
      else:
          if remain > 0.0004:
              time.sleep(0)                 # 让渡当前 CPU 时间片
          end = target
          while time.perf_counter() < end:  # 仅最后 <0.4ms 进行微秒级自旋
              pass
          return
  ```
* **机制复核**：消除了旧代码在帧末为了卡死帧率而运行长达数毫秒的 `while time.perf_counter() < target: pass` 纯 CPU 满载且不放 GIL 的死循环。

#### 3. 渲染主循环（`paintGL`）解耦条件的真实逻辑
* **位置**：`ui/loom_gui.py` 第 228-238 行 与 `editor.py` 第 1785-1793 行
* **代码特征**：
  ```python
  # ui/loom_gui.py:
  if not getattr(e, '_logic_async', False):
      e.advance_logic(delta)     # 同步模式：主线程渲染前必须顺带跑逻辑
  else:
      clk = e._ensure_split()
      if clk is not None:
          e._start_logic_thread(clk) # 异步模式：仅唤醒或确保后台逻辑线程运行
  e.render(delta)                # 渲染管线纯粹消费数据
  ```
* **事实澄清**：并非无条件“彻底剥离”。在无头测试、探针运行或未开启异步逻辑时，为了防止死锁，基座保留了同步推进逻辑。只有在 Qt 宿主激活 `_logic_async=True` 且 `_external_ctx=True` 时，才实现物理上的跨线程解耦。

#### 4. 播放态与编辑态渲染世界矩阵分流
* **位置**：`editor.py` 第 1797-1814 行
* **代码特征**：
  ```python
  it = getattr(self, '_interp', None)
  if getattr(self, 'is_playing', False) and it is not None:
      # 播放态：渲染帧只算插值世界矩阵，直调 C 原生 interp_world
      self._render_world = self._profile(
          'interp', lambda: self.compute_render_matrices(self.models))
      if getattr(self, '_frame_world', None) is None:
          self._frame_world = self._render_world
  else:
      # 编辑态：常规世界矩阵计算
      self._frame_world = self._profile(
          'world_matrices', lambda: self.compute_world_matrices(self.models))
      self._render_world = self._frame_world
  ```
* **机制复核**：`compute_render_matrices`（位于 `engine.py` 3526-3536 行）内部直接触发 `it.render_world` 走 `pipeline.dll` 的 `loom_pipeline_interp_world`，避免了每帧重新计算一遍父子世界矩阵。

#### 5. 材质桶连续数据打包（消灭中间切片）
* **位置**：`engine.py` 第 5536-5560 行
* **代码特征**：
  ```python
  if not getattr(self, '_no_bucket_pack_dll', False):
      try:
          import pipeline_glue as _pg
          if _pg.pack_bucket_instances(fw32, n, idxs, sat, rgba, st[:k], g[:k]) == 0:
              packed = True
      except Exception: packed = False
  if not packed:
      np.take(fw32, idxs, axis=0, out=g[:k], mode='clip')
      st[:k, 0:16] = g[:k].reshape(k, 16)
      # ... 回退到纯 Python 切片与赋值
  ```
* **机制复核**：优先进入 C 原生内存拷贝，直接向已映射好的显存中间缓冲 `st` 与 `g` 一次性填充 24 浮点连续数据。

#### 6. 场景图算法优先下沉分派
* **位置**：`fastpath.py` 第 270-301 行
* **代码特征**：导出 `depths = _depths_dispatch` 与 `ancestry_dfs = _ancestry_dfs_dispatch`，函数内部先尝试执行 `_pg.depths` 与 `_pg.ancestry_dfs`，失败则降级到 `@njit(nogil)` 编译版或 Python 直译版。

---

### 可复核点 5：尚未攻克的剩余真实技术缺口

在工程中可明确核实以下三大瓶颈确实存在，尚未被消除：

1. **玩家脚本更新循环未脱离 GIL**：
   * 检查 `engine.py` 第 5025-5045 行：脚本更新依旧是通过 Python `for m in models:` 遍历 `m.scripts`，并调用反射对象 `sc._script.update(delta_time)`。场景中若有 1000 个复杂脚本，依然由单核 Python 解释器串行驱动，Lua 5.4 沙箱完全未动工。
2. **物理桥（Jolt）未收归至统一 C 动态库契约**：
   * 检查 `physics_bridge.py`：物理后端 `culverin` 仍是基于 `pybind11` 的 Python 扩展模块，而不是遵循 `loom_module.h` 的标准 C ABI 动态库。物理前处理（AABB/宽相）与 Jolt 本身推进之间的边界依然在 Python 侧胶水层中周转。
3. **变换快照（`_transform_snapshot`）仍然产生对象开销**：
   * 检查 `physics_bridge.py` 与 `interp_state.py`：每逻辑步记录位姿快照时，依然需要读取 `m.position`、`m.rotation`，并在 Python 侧产生元组或数组临时对象，尚未做到完全静态预分配的纯 C 环形双缓冲。

---

## 三、真实、有效、可复现的无损复核指引

为避免被虚构的脚本误导，后续任何复核应严格运行**工程中真实存在**的以下两套复核路径：

### 1. 真实契约与算法无损回归门禁（纯计算验证）
在 `Loom(py源代码-工作区)\Loom` 路径下执行以下 18 项真实探针：
```powershell
py -3.12 -c "import subprocess, sys; checks=['ckernels_val_check.py','ckernels_e2e_check.py','collide_val_check.py','aabb_f32_check.py','accept1_e2e_check.py','module_contract_check.py','module_registry_check.py','module_fuzz_check.py','crash_reporter_check.py','pipeline_val_check.py','pipeline_base_check.py','engine_pipeline_check.py','pipeline_fuzz_check.py','pipeline_world_check.py','interp_pose_check.py','pack_bucket_check.py','physics_c_check.py','script_val_check.py']; fails=[c for c in checks if subprocess.run(['py','-3.12',f'tests\\_tmp\\{c}']).returncode!=0]; print('FAILS:', fails); sys.exit(len(fails))"
```
* **客观断言判据**：
  * 进程退出码为 `0`；
  * 终端最终输出 `FAILS: []`；
  * 该指令已现场实测通过，表明已落地的 C 算法与 Python 现行实现在数值上严格相等（最大差异处于浮点机算极限 $\le 1\text{ ULP}$）。

### 2. 真实编译版可执行文件真机性能复核（独立进程验证）
核验物理独立程序 `Loom(编译版)\Loom\Loom.exe`（真实大小为 74,446,336 字节）的实际性能表现，运行工程内置的真实测试程序：
```powershell
py -3.12 tests\_tmp\compiled_verify.py --both
```
* **客观断言判据**：
  * 脚本将自动唤起真实的 `Loom.exe` 进行 A/B 双轨采集；
  * 生成物证报告 `tests\_tmp\compiled_verify_ab.json`；
  * 判定行显示 `[GATE-FPS] ... PASS`；
  * **核心事实特征**：通过对拍验证的是开启 `pipeline.dll` 原生路径后，比纯 Python 逃生门（`LOOM_NO_PIPELINE=1`）具有约 **+8.9%** 的真实性能增益，而非虚构的满帧无消耗。
