# fix_r_scan09 — scan_09 遗留缺陷修复（P-10 / P-03 / P-07 / P-11..P-14）

- **批次**：r_scan09（F4_plugin_sandbox 的遗留项收尾）
- **角色**：修复子代理（非审计员）
- **修改文件**：plugin_loader.py、loom_events.py（父 Agent 追加授权 P-07）、scheduler.py
  - plugin_sandbox.py 在本批允许列表内，但本批无对应遗留缺陷，**未改动**。
- **新增测试**：tests/test_plugin_unload_modules.py、tests/test_plugin_trust_toctou.py、
  tests/test_events_once_reentry.py、tests/test_scheduler_pool.py（均被 run_all 的
  test_*.py glob 自动收集）。
- **未做**：没有 git add/commit；没有顺手重构；P-08 / P-15 / P-16 / P-17 等未在本批清单，未动。

## 0. 验收数字

| 门槛 | 改后实测 | 说明 |
|---|---|---|
| python tests/_tmp/ab_batch.py（22 场景，MAE ≤ 0.0002） | **22/22 PASS，失败 0，最大 MAE 0.000082，exit=0** | 逐场景数值与 F4 基线一致；本批不触渲染 |
| python tests/run_all.py（exit=0） | **exit=0，102 个测试文件全部通过，末行「全部测试完成 ✅」** | 4 个新增测试均被收集（输出第 1732/3707/3710/3761 行） |
| tests/test_plugin_loader.py | ALL PASS | 既有插件加载器回归 |
| tests/test_plugin_register_rollback.py | ALL PASS | F4 事务回滚 / id 所有权不回归 |
| tests/test_plugin_sandbox_escape.py | ALL PASS | F4 两条 P0 逃逸链不回归 |
| tests/test_events_clear_defer.py | ALL PASS | F4 clear 延迟语义不回归（P-07 兼容性证据见 §2） |
| tests/_tmp/smoke_events.py | SMOKE_PASS | 事件总线冒烟 |

> ab_batch 改前基线尝试（10:32）撞上**并行代理正在改 vk_renderer.py 的中间态**
> （ResourceBinding binding 10 is not available in the pipeline layout，22 场景全异常）；
> 该文件 10:37 后稳定，改后重跑 22/22 全绿。此失败与 plugin_loader/scheduler/loom_events
> 无关（本批三文件均不在渲染链路）。

## 1. 逐项修复

### 1.1 [P-10 / P3] 插件卸载不清 sys.modules

- **位置**：plugin_loader.py:769-803（unload_plugin），加载写入点在 _load_entry_restricted /
  _load_entry_unrestricted 的 sys.modules[mod_name] = mod。
- **根因**：卸载只清 SCRIPTS / 工具栏按钮 / _LOADED，从不摘模块。已卸载插件的代码与
  globals 仍被解释器缓存（import loom_plugin_xxx 仍命中旧代码；插件目录改名/升级导致 id
  变化时无界累积），热重载表现为「旧插件常驻」。
- **改法**：卸载清理末尾按 **对象身份** 摘模块 —— 仅当 sys.modules.get(mod_name) is mod
  时 pop；同名条目被别的模块替换/同名系统模块一律不动（只摘自己加的）。
- **改前/改后实测**（%TEMP%\probe_r_scan09.py）：

    改前: loaded=['probe.p10'] | 模块在 sys.modules=True | 卸载后 retained=True
    改后: loaded=['probe.p10'] | 模块在 sys.modules=True | 卸载后 retained=False
    系统模块完好 (os/sys/json/re): 改前 True / 改后 True

- **测试**：test_plugin_unload_modules.py A/B/C/D —— 正常卸载、同名条目被替换时不误删、
  系统模块对象身份不变、rescan 目录消失清理、手动卸载后重载得到新模块对象。

### 1.2 [P-03 / P2] 核心插件信任闸 hash→exec TOCTOU

- **位置**：plugin_loader.py:291-326（新增 _read_entry_bytes / _verify_entry_bytes /
  _load_entry_unrestricted），接入点 _load_one:589-597。
- **根因**：core_trust_state 先对目录算 SHA256，_load_one 随后让 SourceFileLoader.exec_module
  **重新读盘**执行；两步之间文件可被替换 —— 被哈希的是 benign、被执行的是 malicious，信任表
  仍显示 trusted。契约要求「被验证的字节 = 被执行的字节」。
- **改法**：核心插件加载改为 **一次读取 bytes → 对该 bytes 重算 SHA256 并比对信任表 → 编译执行
  同一份 bytes**。替换发生在读取前 → 指纹不符拒载（broken）；替换发生在读取后 → 执行的就是
  已校验的那份字节。仍用 spec/module_from_spec 保留 __spec__/__loader__/__package__ 语义。
- **改前/改后实测**（注入「hash 已完成、执行前替换」：把 core_trust_state 固定为 trusted）：

    改前: after replace load=['probe.core'] broken=[] | P-03 malicious executed=True
    改后: after replace load=[] broken=['probe.core'] | P-03 malicious executed=False
          broken error = "核心插件入口与信任指纹不一致 (TOCTOU 防护): entry.py"

- **测试**：test_plugin_trust_toctou.py A~E —— 已信任正常加载、替换即拒载且不落盘、恢复
  benign 后可重新加载、_load_entry_unrestricted 执行传入 bytes 而非磁盘内容、真实信任闸对
  modified 仍报 modified（二次校验不替代第一道门）。

### 1.3 [P-07 / P2] once + 重入 emit 重复触发

- **位置**：loom_events.py:143-168（EventBus.emit 的 once 消费点）。
- **根因**：once 的移除被推迟到最外层 _apply_pending；once 回调里重入 emit 同名事件时，
  内层快照仍看到 alive=True 的同一个 handler，递归重复触发（审计实测 499 次）。
- **改法**：once handler 在**调用前**置 alive=False 消费（异常也消费，Unity 语义）；内层/重入
  emit 的快照虽仍含该 handler，但 alive 检查直接跳过。**不移除正在遍历的列表**：派发中仍只把
  移除动作追加到 _pending_remove，由 finally -> _apply_pending() 统一摘除。
- **改前/改后实测**（probe 把递归上限设为 10，避免触发解释器上限）：

    改前: once invocations=10 | listeners=0   （无 cap 时审计实测 499 次）
    改后: once invocations=1  | listeners=0

- **测试**：test_events_once_reentry.py A~E（重入同名事件、once+普通订阅者、异常消费、
  F4 clear 延迟兼容、once+clear 同帧）。详见 §2。

### 1.4 [P-11 / P2] NgilPool 的 mask 参数被静默忽略

- **位置**：scheduler.py:66（self._mask = int(mask or 0)）、_loop:94（if self._mask:）。
- **根因**：__init__ 收到 mask 后从未落属性，_loop 用 getattr(self,'_mask',0) 恒取 0 →
  pin_current_thread 分支永不执行，NgilPool(mask=0x3) 与不传等价。
- **改法**：self._mask = int(mask or 0)，_loop 直接读 self._mask。
- **改前/改后实测**：hasattr(_mask)=False | value=None → True | value=5。
- **测试**：test_scheduler_pool.py A —— mask 落属性、2 个 worker 都按 mask 绑核、绑核发生在
  工作线程、默认 mask=0 不绑核。

### 1.5 [P-12 / P3] metrics['packages'] 声明后从未累加

- **位置**：scheduler.py:117-126（worker finally 内累加）。
- **根因**：submit_batch / wait_exchange 全文件无 metrics['packages'] 累加点，
  监控面板恒显示 0 包（agent_commands.py:1030 消费该字段）。
- **改法**：worker 每执行完一个包（finally，与 _pending 递减同锁）metrics['packages'] += 1
  —— 「消化的任务包总数」= worker 真正执行过的包；被 shutdown 丢弃的队列包不计。
- **改前/改后实测**（3 包成功执行）：

    改前: metrics={'batches':1,'packages':0,...}
    改后: metrics={'batches':1,'packages':3,...}

- **测试**：test_scheduler_pool.py B —— 两批累计 3→5、batches 1→2、空批不增加 packages。

### 1.6 [P-13 / P2] 超时降级后 worker 仍写，调用方串行兜底并发写同一输出

- **位置**：scheduler.py:144-190（新增 _wait_drained；wait_exchange 超时分支）。
- **根因**：wait_exchange 超时只置 degraded 并返回 False，submit_batch 不撤销任务，worker
  仍在 fn(*args) 内写共享 numpy 切片；调用方按契约随即跑串行版本 → 两个写者并发，结果可能是
  交错脏数据（无锁、无版本号）。
- **改法**：超时后 **先 drain 在途包**（_wait_drained 等到 _pending<=0，worker 停写），再置
  degraded / 计数 / 返回 False。调用方拿回控制权时 worker 已停写，串行兜底是安全的。
- **改前/改后实测**（worker sleep 0.15s 后写 marker，timeout 0.02s）：

    改前: returned=False | worker_write_already_done_at_return=False | log=[]
    改后: returned=False | worker_write_already_done_at_return=True  | log=['worker_write']

- **测试**：test_scheduler_pool.py C —— 超时返回 False 时 worker 已停写、degraded/timeouts 计数、
  串行兜底可安全接管。

### 1.7 [P-14 / P2] shutdown 丢队列 + _pending 变负 + wait 假完成

- **位置**：scheduler.py:208-233（shutdown），scheduler.py:126（worker 递减防御下界），
  scheduler.py:181-184（wait 的 cancelled 分支）。
- **根因**：shutdown 清空 _jobs 后直接把 _pending 归零；已在 fn 里的 worker 收尾再减 1 →
  -1 → empty 为真 → _done.set() → 随后 wait_exchange 对「只执行了部分包」返回 True。
- **改法**：
  1. shutdown 只把**队列中未开始**的包从 _pending 减去（在途包仍由 worker finally 递减），
     并置 _cancelled；有在途包时不提前 _done.set()，由 worker 收尾置位。
  2. worker 递减加 if self._pending > 0 防御下界（正常账目下不会触发）。
  3. wait_exchange 在 _cancelled 时先 drain 再返回 False（True 的契约是「全部完成」）。
- **改前/改后实测**（提交 4 包，1 worker，第 1 包在途时 shutdown）：

    改前: pending_after_shutdown=-1 | executed=[0] | wait_after_shutdown=True  | pending_final=-1
    改后: pending_after_shutdown=0  | executed=[0] | wait_after_shutdown=False | pending_final=0

- **测试**：test_scheduler_pool.py D —— pending 不为负、队列包不执行、wait 不假完成、幂等
  shutdown；E 组守护正常批/空批/降级前受理等既有语义。

## 2. P-07 修法与 F4 语义兼容性证据

1. **F4 的 clear() 延迟语义未回退**：tests/test_events_clear_defer.py 全 PASS，关键行
   seen=['h1','h2'] emit=2、非派发期 clear 仍立即、clear 后新增订阅延迟到下一轮、off 对照。
2. **once 与 clear 同帧**：新测试 E 组 —— once 回调里先 clear('e') 再重入 emit('e')：

       seen=['once','h2','h2'] | once 只触发 1 次 | 本轮 h2 仍收到事件 | 本轮后 listener_count=0

   说明 once 的「调用前消费」与 F4 的「移除延迟入队」不冲突：本轮快照照常派发，下一轮起不再有
   once/被 clear 的订阅。
3. **不破坏遍历安全**：once 消费只改 h.alive，不改 _handlers 列表；派发中移除动作仍只进
   _pending_remove，由 finally 的 _apply_pending() 统一应用（与 F4 的 clear/off 同队列）。
4. **异常语义**：once 回调抛异常也只触发一次（测试 C），与 Unity「异常也移除」一致。

## 3. 新增回归测试

| 文件 | 覆盖 | 断言要点 |
|---|---|---|
| tests/test_plugin_unload_modules.py | P-10 | 卸载摘模块、只摘自己那份、系统模块身份不变、rescan 目录消失、重载新模块对象 |
| tests/test_plugin_trust_toctou.py | P-03 | 已信任正常加载、hash 后替换拒载且不落盘、恢复后可加载、执行传入 bytes、modified 仍拦 |
| tests/test_events_once_reentry.py | P-07 | 重入同名事件只 1 次、once+普通订阅者、异常消费、F4 clear 兼容、once+clear 同帧 |
| tests/test_scheduler_pool.py | P-11/12/13/14 | mask 绑核、packages 累加、超时 drain 停写、shutdown 账目/wait、既有语义 |

## 4. 设计取舍与遗留（只登记）

1. **P-13 的 drain 是「正确性优先」**：超时后 wait_exchange 的**实际耗时可能超过 timeout**
   （要等在途 fn 结束）。这是「调用方串行兜底不得与 worker 并发写」的必要条件；若未来要严格
   保证主线程时延上界，需要 L2 方案（可取消的任务包/独立输出缓冲），不是本批能安全引入的。
   任务书「主线程 wait 恒带超时」的调用形态未变（仍传 timeout），变的是超时后的交接动作。
2. **metrics 语义**：packages 按 worker 实际执行累加，因此「超时后 drain 的批次」会出现
   packages>0 而 batches=0（该批未以成功完成计入 batches）。这是「消化」而非「成功批」的口径，
   已在代码注释写明。
3. **shutdown 的 join 仍是 timeout=2.0**：极端情况下 shutdown 返回时 fn 可能仍在跑；但此后
   wait_exchange 会先 drain 再返回 False，凡按契约 wait 的调用方是安全的。引擎当前只在退出链
   调 shutdown，不读结果。
4. **P-24（2ms 超时误降级概率）仍 UNKNOWN**：本批未改默认阈值（任务书红线）；drain 不改变
   「命中一次即永久降级」的判定。
5. **tests/_tmp/sched_pool_check.py P3 的 batches>0 断言是陈旧预期**：当前 engine.py 全文件
   没有 run_batch/submit_batch 调用点（scan_09 P-13 所述「潜伏」），池虽建但不提交，故 P3 的
   「池侧账」必为 0。该脚本 P0/P1/P2/P4 全 PASS；其末行 emoji 在本机 GBK 控制台会
   UnicodeEncodeError（脚本自身未 reconfigure stdout），均为既有问题，非本批引入。
6. **未修**：P-08 EventHandler.cancel() 与 off() 计数漂移（不在本批清单）；P-15/P-16/P-17
   等脚本层遗留（不在本批文件范围）。

## 5. 复现命令

    cd "D:\my-project - 副本\Loom(py源代码-工作区)\Loom"
    python tests/test_plugin_unload_modules.py
    python tests/test_plugin_trust_toctou.py
    python tests/test_events_once_reentry.py
    python tests/test_scheduler_pool.py
    python tests/test_plugin_loader.py
    python tests/test_plugin_register_rollback.py
    python tests/test_plugin_sandbox_escape.py
    python tests/test_events_clear_defer.py
    python tests/_tmp/smoke_events.py
    python tests/_tmp/ab_batch.py
    python tests/run_all.py

改前/改后对照探针：%TEMP%\probe_r_scan09.py（输出 %TEMP%\probe_r_before.txt /
%TEMP%\probe_r_after.txt）。
