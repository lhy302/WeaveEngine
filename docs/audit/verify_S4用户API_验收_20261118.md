# verify_S4用户API_验收_20261118 —— lead 独立验收（9 条用户 API + on_destroy 收口）

> 日期 2026-11-18 · 类型 **独立验收**（lead 复跑 + 自写探针，不采信子代理自报值）
> 被验对象：`4960dd8`（子代理 `agent-3` 实施）+ lead 的 on_destroy 收口补丁
> 判据来源（人类原话）：「两个后端暴露给用户的 API 都是一样的，选择哪个后端在用户端就是换个配置，
> 类似于 JVM 虚拟机：不管底层用的什么后端，往上暴露的接口都一样。」

---

## 1 验收结论

**通过**。用户 API 已两端一致，且是**同一份实现**（同一函数对象）。

| 指标 | 验收值 |
|---|---|
| 两端共同公开成员 | **97**（此前 88） |
| GL 独有 | **15**（全部登记为后端渲染原语，各有理由） |
| VK 独有 | **10**（全部登记为宿主/相机内部，各有理由） |
| 9 条用户 API 是否同一函数对象 | **是**（逐条实测 `g is v` 全 True） |
| 7 条门 | 全绿（8/6/14/96/12/8/13 条断言） |
| `run_all` | **180.6s EXIT=0**，146 文件，仅 1 条 FAIL 行（= 已知假绿 `test_hub_update`） |

## 2 lead 独立复跑

```
[EXIT0] test_user_api_parity.py              PASS=8  FAIL=0
[EXIT0] test_engine_api_matrix.py            PASS=6  FAIL=0
[EXIT0] test_host_event_parity.py            PASS=14 FAIL=0
[EXIT0] test_input_chain_parity.py           PASS=96 FAIL=0
[EXIT0] test_vk_logic_frame_parity.py        PASS=12 FAIL=0
[EXIT0] test_beam_light_backend_parity.py    PASS=8  FAIL=0
[EXIT0] test_clock_settings_propagation.py   PASS=13 FAIL=0
[run_all] EXIT0 180.6s  →  全部测试完成 ✅（146 文件，1 条 FAIL 行 = 已知假绿）
```

## 3 「同一份实现」逐条核实（不看它的门，自己查对象身份）

```
SAME add_light / remove_light / clear_scene / remove_subtree / load_scene
SAME get_tps / get_logic_time_ratio / step_logic_once / update_scripts
全部同一对象: True []
```

## 4 lead 功能探针（`tests/_tmp/lead_accept_user_api.py`，不复用它的探针）

| # | 验证点 | GL | VK |
|---|---|---|---|
| 1 | `add_light` 入列且返回同一对象 / `remove_light` 真摘掉 | ✅ | ✅ |
| 2 | `remove_subtree` 删父连子留独立 / `clear_scene` 清空 models+materials | ✅ | ✅ |
| 3 | `load_scene(路径)` 真换场景（含 1 光源）/ 缺文件返回 False 不抛 | ✅ | ✅ |
| 4 | `get_tps` 驱动后 >0 / `get_logic_time_ratio` 非 None | 34.60 / 1.0002 | 107.75 / 3.585 |
| 5 | `step_logic_once` 暂停态返回 True 且只前进 1 帧 | ✅ | ✅ |
| 6 | `update_scripts` 可调且脚本钩子命中 | start | start |

> `get_tps` 两端数值不同（34.6 vs 107.75）是**驱动方式不同**造成的：GL 走 `render(dt)` 内部时钟、
> VK 由探针直接 `advance_logic(1/60)`。采样口径一致（每逻辑帧一次）。**留痕**：同一宿主循环下应再对拍一次（未核）。

## 5 lead 补的一个真缺陷：`on_destroy` 两端不一致

子代理自报「VK 的 `clear_scene`/`load_scene` 不派发 `on_destroy`，超出本次范围，请裁决」。
lead 实测确认这是**用户可观察的语义差异**（脚本生命周期钩子），按人类要求必须抹平：

```
修前：GL after=[start, destroy]  |  VK after=[start]            → 不一致
修后：GL after=[start, destroy]  |  VK after=[start, destroy]   → 一致
```

**根因**：`remove_model` 只在 GL 有实现（子树递归 + 派发 `on_destroy`），VK 有一份**浅版**
（只从 `models` 摘除 + 剪 LOD，不派发、不递归）—— 于是「删父留悬空子」「脚本收不到 on_destroy」两个差异。

**修法**：把 `remove_model` 收进 `EngineCore`（GL 语义：有子 → `remove_subtree`，否则 `_remove_one_model`），
删掉 GL 与 VK 各自的副本；后端差异只留在 `_remove_one_model`（GL 解 GPU 引用 / VK 剪 LOD 候选）。
验收：`run_all` 180.6s 全绿（146 文件）、7 条门全绿、9 条功能探针 ALL PASS。

## 6 对子代理自报值的核对

| 自报 | lead 核对 |
|---|---|
| 「共同 97 / GL 独有 15 / VK 独有 10」 | ✅ 一致（112−15 = 107−10 = 97） |
| 「9 条同一函数对象」 | ✅ 自查对象身份全 True |
| 「run_all 180.9s」 | 复跑 **180.6s** ✅ |
| 「get_tps 30.05 / ratio 1.0157（GL）；29.13 / 0.9717（VK）」 | 我的探针得 34.60/1.0002 与 107.75/3.585 —— **量级与符号一致，具体值取决于驱动方式**；采样口径已核实为「每逻辑帧一次」 |
| 「动了 `test_engine_api_matrix` 基线（98→107、删 9 条）」 | ✅ 核实：这正是该门 docstring 规定的维护动作；4 条实质断言未放宽 |
| 「VK clear_scene 不派发 on_destroy（未做）」 | ✅ 已由 lead 补掉（见 §5） |
| 「GL `_load_scene_data` 不吃 base_dir（有意）」 | 接受：GL 相对资源走资产上下文，补传会改 GL 可观察行为 |

## 7 未做 / 未核（诚实清单）

| 项 | 状态 | 说明 |
|---|---|---|
| 同一宿主循环下 `get_tps` 两端数值对拍 | **未核** | 本次两端由不同入口驱动（`render` vs `advance_logic`），数值不可直接比 |
| 后端内部 25 条（GL 15 渲染原语 + VK 10 宿主/相机） | **有意保留** | 各有白名单理由；用户脚本不该调；渲染等价由 `test_ab_gl_vk` 26 场景 MAE≈0 钉住 |
| 真窗口实机点验（VK 播放器 F9/F10/F11 + 鼠标锁定） | **未核** | 无头环境跑不了 GLFW 回调；`test_integration` 只覆盖到拉起窗口 |
| `test_hub_update` 假绿 / `is_program_files` | **未修** | 归 Hub 0.1.5（Q-B7-29-1） |
| AOCI 认知维护 | **未执行** | 本会话无 `aoci_*` 工具 |

## 8 留痕

- 本次为「子代理实施 + lead 验收 + lead 补缺陷」。子代理主动报告了 on_destroy 差异（值得肯定），
  但它选择「留待裁决」——按人类要求，这属于**用户可观察的 API 语义差异**，不该留；lead 已补。
- 教训：**「API 一样」不只看方法是否存在**，还要看「同名方法在相同输入下是否产生相同副作用」
  （on_destroy 派发就是副作用面）。
