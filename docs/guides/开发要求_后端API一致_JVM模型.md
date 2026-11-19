# 开发要求：后端 API 的 JVM 式一致（新增后端 / 新增 API 必读）

> **人类原话（2026-11-17 / 11-18，多次重申，是本文件唯一的上位判据）**：
> 「两个后端暴露给用户的 API 都是一样的，选择哪个后端在用户端就是换个配置，**类似于 JVM 虚拟机：**
> **不管底层用的什么后端，往上暴露的接口都一样**。」
> 「最后的目标一定是**两种后端没有用户可感知的差异**，还是那个目标：如同 JVM 虚拟机在任何 CPU 上
> 都保证字节码解析效果一样，那样**不管选择什么后端对用户脚本的表现一致**。」

**这份文件是强制要求，不是建议。** 任何新增后端、新增后端 API、或修改现有后端行为的改动，
都必须按本文的流程走完，否则视为未完成。

---

## 1 目标：什么叫「一致」

### 1.1 保证什么（必须做到）

**同一份脚本 + 同一份场景 + 同一串输入 → 两个后端产生同一串可观察结果。**

「可观察结果」= 用户（脚本 / 内容 / 宿主 / 玩家）能看见或读到的任何东西：

| 面 | 例子 |
|---|---|
| API 存在性 | `engine.find_by_name()` 在两端都能调，不会 AttributeError |
| API 返回值 | 同一查询返回同一结果（含 `None` / `[]` / `-1` 这些「失败值」） |
| 事件序列 | `on_collision_start/end`、`on_trigger_*`、`on_start/on_destroy` 的**顺序与次数** |
| 状态位 | `is_key` / `get_action` / `mouse_locked` / `logic_paused` / `fullscreen` |
| 副作用 | 派发次数（UI 每次按下只派发 1 次）、资源释放、脚本钩子是否被调 |
| 画面 | 同一场景两端像素级接近（现有 `test_ab_gl_vk` 26 场景 MAE≈0） |
| 窗口几何 | 全屏进出后的尺寸 / 位置 / 边框 / 置顶 |

### 1.2 不保证什么（明确不做）

| 不做 | 理由 |
|---|---|
| **性能对齐** | 后端算法本就不同（GL SAP+C 内核 vs VK 朴素 O(n²)），只要语义一致即可；性能下沉是独立优化项 |
| **内部结构相同** | GL 每物体持久 VBO，VK 每帧按 mesh 现建缓冲 —— 只要「物体出现在画面上」一致就行 |
| **实现细节相同** | 但**不允许**把差异变成「用户能看见的」 |

### 1.3 一句话判据

> **能不能写一份脚本，在两端跑出完全一样的结果？** 不能 → 不一致。

---

## 2 三层分类（每个公开成员必须落在其中一层）

| 层 | 判据 | 要求 | 登记位置 |
|---|---|---|---|
| **① 用户 API** | 脚本 / 内容 / 工具链会调用的能力 | **两端必须有、且是同一个函数对象**（不是各写一遍） | `docs/design/契约_IEngineAPI_20261117.md` |
| **② 后端内部** | 只有某一端才有意义（立即模式绘制原语、上屏诊断、GLFW 回调、宿主喂输入） | 允许只在一端，**但必须登记白名单 + 写明「用户为什么不该感知到它」** | `Loom/tests/test_user_api_parity.py` 的 `BACKEND_ONLY_*` |
| **③ 禁止** | 同一件事两端行为不同，且用户能感知 | **不许存在** | — |

**判据不可含糊**：拿不准是 ① 还是 ② 时，**按 ① 处理**（宁可多补一份实现，也不许留一个隐形差异）。

---

## 3 新增一个后端 API 的强制流程（7 步，缺一即未完成）

### 第 1 步 · 先分类，别先写代码

- 这个能力是**用户 API** 还是**后端内部**？
- 如果是用户 API：**GL 侧现在有没有？VK 侧呢？** 两端现状各是什么（用 `git grep` 找，不要凭印象）。
- 如果是后端内部：为什么用户不该感知到它？写出**一句话理由**。

### 第 2 步 · 公共实现放内核，后端差异收在钩子里

`@
EngineCore（后端无关）               ← 公共 API 写在这里（薄封装 + 数据面）
   └─ self._backend_xxx(...)          ← 后端钩子（getattr 取，缺失即跳过）
GLEngine  /  VkEngine               ← 各自实现 _backend_xxx（GPU 上传 / 窗口操作 / …）
`@

**硬要求**：
- 公共 API 必须在 `EngineCore`（或共享 mixin）里，**两端继承同一份** → `getattr(GLEngine,n) is getattr(SceneDriver,n)` 为 True。
- 后端差异**只允许**出现在 `_backend_*` 钩子 / `_xxx_impl` 里，不许渗回公共层。
- 钩子用 `getattr(self, '_backend_xxx', None)` 取，**不要**在 `EngineCore` 里写空实现（会被 MRO 遮住，见 §5 反模式 2）。

### 第 3 步 · 写「两端对拍门」（不是单端测试）

**每一个用户 API 面，都必须有一条对拍门**：同一输入喂两端，逐项比对可观察结果。

门的最低要求：

| 要求 | 说明 |
|---|---|
| **两端同一输入** | 用同一个构造序列喂 GL 与 VK，不是「各自测各自的」 |
| **逐项相等** | 断言 `GL结果 == VK结果`，不是「各自为 True」 |
| **失败值也测** | `None` / `[]` / `-1` / `False` 这些「找不到」的返回值两端必须一致 |
| **副作用也测** | 派发次数、钩子触发次数、资源是否释放 |
| **修前必红** | 门写完先在**未修状态**跑一次，确认它真的会红（见第 4 步） |
| **已知差异登记表** | 门里留一个显式的「已知差异」列表；**为空**才算通过，不许用阈值糊过去 |

### 第 4 步 · 修前必红（这一步最容易被跳过，也最容易造假）

**必须真跑出红，不许读码推断。** 两种做法都行：
- 把业务代码临时回退到未修版（`git show HEAD~1:path` 覆盖），跑门 → 必须红；
- 或造一个**运行时变异**（monkeypatch），跑门 → 必须红。

**贴出红的断言原文**，不要只说「验过了」。

### 第 5 步 · 修后必绿 + 全套回归

- 新门全绿；
- **相关既有门**全绿（改输入 → 跑事件面/输入链门；改渲染 → 跑 A/B 像素门）；
- `py -3.13 tests/run_all.py` **单实例**全绿。

### 第 6 步 · 留痕

任何「这次不做 / 未核 / 已知差异」都必须写进：
- 代码注释（就地）；
- `docs/design/待裁决清单_beta6.md`（需人类拍板的）；
- 交付报告的「未做/未核清单」。

**不许写「查不到」** —— 写「未核」。

### 第 7 步 · 派独立审核（一个组件一个代理）

新增/改动后端 API 后，**必须派一个未参与实现的子代理**审：
- 它要能**独立复跑**门，并挑几个自报数字自己重测；
- 按方法论先**反手**（这是不是测试迎合代码 / 环境问题 / 超范围 / 把真缺陷改成假绿）再正手；
- 判定用四象限：PROVED / DISPROVED / UNKNOWN / CONTRADICTION。

---

## 4 门的分类：每一面都要有门

### 4.1 已有对拍门的面（不要重复造）

| 面 | 门 | 断言数 |
|---|---|---|
| 用户 API 集合 + 同一份实现 | `test_user_api_parity.py` | 8 |
| 引擎公开成员矩阵（差异只许缩小） | `test_engine_api_matrix.py` | 6 |
| 事件面（键/文本/退出钩子） | `test_host_event_parity.py` | 14 |
| 输入链（key_state→script_keys→is_key→解锁键） | `test_input_chain_parity.py` | 106 |
| 全屏（F11）窗口几何 | `test_fullscreen_parity.py` | 47 |
| 逻辑帧段序 + 碰撞事件序列 | `test_vk_logic_frame_parity.py` | 12 |
| 时钟设置传播 | `test_clock_settings_propagation.py` | 13 |
| beam 灯像素对拍 | `test_beam_light_backend_parity.py` | 8 |
| A/B 像素（26 场景） | `test_ab_gl_vk.py` | 26 场景 |
| 鼠标锁定与光标捕获 | `test_mouse_lock_parity.py` | 62（**全绿**；R1/F-3 + F-1/F-2/F-6/F-7 + Q-B7-40-1 打包播放器路径 已修） |
| **P1 场景加载/切换的用户可见结果**（load_scene / clear_scene / 版本迁移 / 相对资源路径） | `test_scene_load_parity.py` | 76（2026-11-19 实测 76 PASS / 0 FAIL；本行旧记 69 已过期） |
| **P3 UI 命中与焦点**（点击命中 / hover 集合 / 焦点与键盘 / 滚动消费 / UI 消费对引擎的屏蔽 / 坐标系 / **窗口 resize 的画布跟随** / **跨帧持按的相机门控**） | `test_ui_hit_parity.py` | 144（**全绿**；P3-1 滚轮门控 2026-11-18 已修，Q-B7-41-1/41-2 2026-11-18 已修 → 81→144） |
| **P4 音频播放状态**（播放状态机 / 3D 听者同步 / 每帧更新时序 / 暂停期行为 / 无音频设备降级 / 脚本 API 面） | `test_audio_parity.py` | 105（**105 PASS / 0 FAIL（2026-11-19 修后实测）**；修前红 = 90 PASS / 15 FAIL —— 四条缺陷 P4-1~P4-4 已全部修完，见下） |
| **P5 相机轨道 / 开发者视角**（轨道相机位姿 / 脚本写角度字段 / 玩家相机模式 / 开发者视角鼠标 / 相机挂父的运行时传播 / 投影参数） | `test_camera_parity.py` | 195（**195 PASS / 0 FAIL（2026-11-19 修后实测）**；修前红 = 189 PASS / 6 FAIL，红点 Q-B7-45-1 **已修**，见下） |
| **P6 暂停 / 单步的窗口级观感**（暂停期画面冻结但渲染继续 / F10 恰好 1 逻辑帧 / 恢复无欠账 / 暂停画面逐像素稳定 / 单步画面 == 逻辑推进 / 两端截图逐像素对拍） | `test_pause_parity.py` | 71（**71 PASS / 0 FAIL（2026-11-19 修后实测）**；修前红 = 69 PASS / 2 FAIL —— 红点 P6-1「暂停边界插值对齐两端不同 → 冻结画面差 1 个逻辑帧」**已按人类裁决「暂停不得跳变」修完**，见下） |

> **P1 门当前状态（2026-11-18，B7-16/B7-17 修后）**：`test_scene_load_parity.py` **69 条全绿**
> （修前 = 52 PASS / 17 FAIL，红证据见该门文件头 R1~R8 留痕）。修法：场景契约独立成模块
> `Loom/loom_scene_contract.py`（`CURRENT_VERSION` / `SceneVersionError` / `gate` / `migrate` /
> `prepare`），**所有打开场景的路径都走 `prepare()`**（编辑器 / GL 播放器 / VK 播放器 / 打包
> 游戏 / 游戏包 / EAI 命令），散落的 5 处闸门调用收敛到契约模块（其它文件 0 处）；VK 装配
> 路径因此自动迁移（v8 相机 yaw 90.0）；闸门前移到任何状态变更之前（失败不再清空当前场景）；
> VK 装配侧复用内核 `_register_model_material` 登记自建默认材质；GL 装配侧补传 `base_dir`
> （相对资源按场景目录解析）。契约模块自身的门 = `test_scene_contract.py`（36 条，含「单独
> import 不拉 engine/GPU」的子进程断言）。

> **P3 门当前状态（2026-11-18，Q-B7-41-1/41-2 修后实测）**：`test_ui_hit_parity.py` = **144 PASS / 0 FAIL（144 条全绿）**。
> 八组：① 点击命中、② 焦点与键盘、③ hover 集合、④ 滚动消费、⑤ UI 消费对引擎的屏蔽、
> ⑥ 坐标系一致性、⑦ 窗口 resize 的 UI 画布跟随、⑧ 跨帧持按的相机门控 —— **全绿**。
> ④ 组曾红 1 条 = **P3-1（已修，2026-11-18）**：滚轮停在**可滚 ScrollView** 上时 GL
> `engine.mouse_wheel=-3` / VK `driver.mouse_wheel=0`（同一串输入 + 同一棵树）—— 脚本读
> `mouse_wheel` 做镜头缩放时，GL 在滚动列表的同时还会缩放，VK 不会。
> **修法（只改 GL 侧滚轮门控；VK 行为零变化）**：判据抽成共享前置 `Loom/loom_ui_input.py`
> （`wheel_taken_by_scrollview` = 滚轮专属判据；`wheel_consumed_by_ui` = P-09 组合规则），
> 三处 import **同一份**（解耦规则 3）：`runtime.PlayerApp._dispatch_ui_mouse`（GL —— 判据在
> dispatch **之前**取，只有滚轮本身被 ScrollView 吃掉才把 `self.mouse_wheel` 清 0；同帧
> 「点按钮 + 滚轮」仍把滚轮留给脚本）、`vk_ui.UIInputBridge.begin_frame` 与 `vk_player.draw`
> （VK —— 行为不变，只把两处同体拷贝换成共享实现，保留 `_wheel_taken_by_scrollview` 历史名字的
> 别名，调用点与既有门不动）。
> 修前红原文：`FAIL ④ 滚动消费：消费位 + 脚本可见滚轮 + scroll_pos，两端逐项相等
> 可滚 ScrollView 上滚轮(-3) ·脚本可见滚轮: GL=-3 VK=0`（80 PASS / 1 FAIL）→ 修后 81 PASS / 0 FAIL。
> 两项相邻留痕已修（2026-11-18，本门 81 → 144，修前红证据见提交信息）：
> ① **Q-B7-41-1（裁决「判为缺陷，VK 补 ui.resize」）已修** —— 唯一实现抽到共享前置
> `Loom/loom_ui_resize.py`（口径与 GL `_on_resize` 逐条一致：int 截断 + 下限 320x240），
> `vk_player.draw` 帧首在 `begin_frame` **之前**调用（与 GL「先 `_on_resize` 再
> `_dispatch_ui_mouse`」同序）；**GL 一行未动**（基准）。门 = ⑦ 组（640x400 → 800x500 →
> 200x100 钳到 320x240：画布尺寸 / anchor 矩形 / 命中结果逐项相等）。
> ② **Q-B7-41-2（裁决「以 GL 为准」）已修** —— `vk_ui.UIInputBridge.ui_active` 改成只看
> **本帧** `dispatch_mouse` 的返回值（= GL 的 `ui_consumed`），跨帧「按下未松开/拖动中/
> pointer-down 未 up」三个判据已删；`vk_ui.py` 里那段「与 GL 的 `ui_consumed` 不同」的注释
> 已同步删改（反模式 10）。门 = ⑧ 组（按住控件 / 空白区按下未松开 / 拖动滑条：`(ui_consumed,
> wants_camera, 相机实际拿到的增量)` 三元组逐项相等）。
> 已知残差（只报告不锁）：GL 的 `engine.mouse_rel` 在「本帧被 UI 消费」时仍非 0（脚本可读），
> VK 因 feed 被 `wants_camera` 门控所以是 0 —— 差的只是「脚本在 UI 消费帧读 mouse_rel」这一面。

> **P4 门当前状态（2026-11-19，HEAD=7567f34 实测）**：`test_audio_parity.py` = **90 PASS / 15 FAIL**
> （**修前红**，照 P1/P2/P3 先例提交：本任务只交门 + 红证据，业务代码一行未改）。六组：
> ① 播放状态机（播/停/暂停/恢复/换 clip/改音量：两端实例状态 + 后端调用序列 + **独立判据**
> pygame 通道占用）、② 3D 听者同步（set_listener 的 position/forward/up 逐项相等且 = 由场景
> 文件手算的期望表；玩家相机路径 + 轨道相机路径；每逻辑帧同步一次）、③ 每帧更新时序（实例级
> 插桩记录**实际**段序与音频段位置/次数；N 帧 → N 次；**绑死模式 logic_fps<=0** 下每渲染帧次数）、
> ④ 暂停期（logic_paused 时两端同决策冻结 / 暂停期置 playing 不抢跑不积压 / 恢复首帧恰好 1 帧
> 1 次 1 播 / F10 单步 1 帧）、⑤ 无音频设备（SDL 驱动不可用 = 生产 AudioBackend 真实降级路径：
> 两端都不崩、句柄缓存 None、脚本 API 返回值相同、状态机照走）、⑥ 脚本 API 面（engine.audio.*
> 与 add_audio_source/remove_audio_source 的存在性/返回值/副作用/「资源不存在」失败路径 +
> **真实注册脚本在 on_start 里调音频 API**）。
> **门红点 = 四条缺陷（只报告不修，均归 P4 新项）**：
> · **P4-1（两端同坏，用户可感知 = 3D 音效根本不播）**：`loom_components.AudioSystem`（:1015）
>   只有 load/play/stop/play_sound/shutdown，**没有** `play_spatial` / `set_listener` /
>   `update_sound_position`，而 `loom_frame_components.update_audio`:71 与
>   `sync_audio_listener`:44 正是调这三个 —— category 为 sfx/voice（**默认 sfx**）且
>   playing=True 时音频段抛 AttributeError（GL engine.py:1218 / VK scene_driver.py:902 一路抛到
>   宿主）；set_listener 的异常被 `sync_audio_listener` 的 except 吞掉 → 监听器**永不生效**。
>   2D（music）路径正常。归属：`loom_components.py:1015`（缺 3 个委托方法）。
> · **P4-2（VK 听者不跟随相机）**：GL 的 `self.camera` 每渲染帧由 `loom_render.py:1053`
>   `apply_orbit_camera()` 更新（`runtime.py:174` 加载时也调）；VK **全仓 0 处**
>   `apply_orbit_camera` 调用点，`self.camera` 恒为 `scene_driver.py:616` 的初始 (0,0,-5)，
>   朝向取 `camera_yaw/camera_pitch`（:617 恒 0）而轨道相机实际用 `yaw/pitch`
>   （`render_pose:1257`）。实测：GL 听者 =(-7.658,6.673,-3.870)/fwd=(-0.721,0.389,-0.573)，
>   VK =(0,0,-5)/fwd=(0,0,-1)。归属：`scene_driver.py:616-619` + 缺 apply_orbit_camera 调用点。
> · **P4-3（VK 首帧前 engine.audio 是 None）**：GL 在 `__init__` 就建 AudioSystem
>   （engine.py:405），VK 是 `self.audio = None`（scene_driver.py:659）+ 首帧惰性建。脚本在
>   on_start 里调 `engine.audio.play_sound(...)` → GL 返回 None，VK 抛 AttributeError →
>   引擎判成坏脚本（`_script_broken=True`）→ **该脚本在 VK 上整局不再运行**（实测：GL 8 个
>   脚本 0 个坏、VK 4 个 `p4_audio_api_raw` 全坏且 update 再未执行）。
> · **P4-4（绑死模式 VK 没有音频段）**：用户设置 `logic_fps<=0`（`core_clock.split_enabled`）
>   时两端都进旧绑死模式。GL 两条绑死路径都调 update_audio（engine.py:1504 /
>   loom_render.py:1126 `_escape_door_step`），VK 的 `advance_logic:1109-1115` 与
>   `_step_one_logic_frame:1133-1137` 都没有 → 实测 3 个渲染帧：GL 3 次 / VK 0 次（F10 单步
>   同理）。归属：`scene_driver.py:1109-1115 / :1133-1137`。
> **未核（留痕）**：设备级 3D 声像（需 game_audio + 真声卡；本门固定
> `LOOM_AUDIO_BACKEND=pygame` + `SDL_AUDIODRIVER=dummy` 以保证无设备可跑，只验 3D **参数面**）；
> 播放进度（秒）—— 两端生产代码都没有该 API，故以「3D 空间位置」作位置面；
> game_audio 的 per-file 回退路径（ogg/opus → pygame）。
>
> **P4 修后状态（2026-11-19，HEAD=788a998 之上实测）**：`test_audio_parity.py` = **105 PASS / 0 FAIL**
> （P4 面门全绿）。四条缺陷的修法与证据：
> · **P4-1**（3D 音效两端都不播）：`loom_components.AudioSystem` 补 `play_spatial` /
>   `set_listener` / `update_sound_position` 三个纯转发（唯一实现仍在 `audio_backend.py`）。
> · **P4-3**（VK 首帧前 engine.audio 是 None）：VK 在 `__init__` 就建 `AudioSystem()`
>   （与 GL engine.py:405 同位置；构造失败仍留 None 作可见降级）。
> · **P4-2**（VK 听者不跟随相机）：轨道相机眼睛位置的公式抽成**唯一实现**
>   `loom_camera.orbit_camera_eye`（GL 的 `CameraMixin.apply_orbit_camera` 也调它，数值不变）；
>   VK 新增 `SceneDriver._sync_orbit_camera_state()`（与 GL 的 apply_orbit_camera 同语义同值），
>   在**加载时**（= GL runtime.PlayerApp 加载路径）与**每渲染帧帧首**（= GL
>   loom_render._prepare_main_pass 同位置，任何消费相机的地方之前）调用；VK 的轨道角度在
>   `yaw/pitch`、玩家相机角度在 `camera_yaw/camera_pitch`（GL 两者共用一组），故同步时把
>   轨道角度**镜像**到 `camera_yaw/camera_pitch` —— 共享的 `sync_audio_listener` 读的正是后者；
>   `sync_audio_listener` 取源顺序**一行未动**，`camera_pos` 里的同公式拷贝改为调共享纯函数。
>   探针 `tests/_tmp/p42_listener_follow_probe.py`（9/9）：三个位姿下 VK 的 set_listener
>   位置/前向/上方向都跟着相机变，且与 GL 逐值相等、且 = 手算期望。
> · **P4-4**（绑死模式 VK 没有音频段）：`advance_logic` 的绑死分支与
>   `_step_one_logic_frame` 的无时钟分支各补 `self.update_audio(...)`（物理之后、
>   LateUpdate/return 之前，与 GL 同序）。**以 GL 为准核实过**：GL 没有独立的无时钟单步路径
>   （step_logic_once 只置 _step_requested，绑死分支不看它），「绑死 + F10 单步」在 GL 上 =
>   1 个绑死渲染帧 = 1 次音频段（实测 GL=1，VK 修前 0）。探针
>   `tests/_tmp/p44_bound_audio_play_probe.py`（8/8）：绑死模式下 VK 的 AudioSource 真的
>   play/stop（pygame 通道占用 1 → 0 → 1 的独立判据）。
> · **已知残差（只报告不锁，归 P5 相机面）**：① 两端「轨道角度」的公开字段名不同（GL
>   `camera_yaw/camera_pitch`；VK `yaw/pitch`，VK 的 `camera_yaw/camera_pitch` 是玩家相机
>   角度）—— 同一份脚本写 `camera_yaw` 移动轨道相机在 VK 上不生效；② 同一渲染帧内「脚本改
>   轨道角度 → 该帧逻辑帧的听者朝向」：GL 立刻生效（读活的 camera_yaw），VK 滞后到下一个
>   渲染帧（帧首镜像）。

> **P5 门当前状态（2026-11-19，Q-B7-45-1 修后实测）**：`test_camera_parity.py` = **195 PASS / 0 FAIL**
> （修前红 = 189 PASS / 6 FAIL，红证据见下段「门红点」；业务代码改动只在 VK 侧
> `scene_driver.py`，GL 一行未动）。
> **统一判据**：不论哪条路径，两端「相机位姿」必须逐值相等 —— 位姿 = 三元组 (眼睛位置, 前向,
> 上方向)，且**两端都要等于手算期望表**（期望值不取自任何一端，否则两端一致地错也测不出）。
> 六组：① 轨道相机（target/yaw/pitch/distance 八种组合：负 yaw / 负 target / 入口最小距离 0.5 /
> 入口最大 1000 / **运行期写入 5000**（绕过入口钳制）/ pitch 近 ±90° / 运行期改
> target+distance）、② **脚本写角度字段（Q-B7-45-1 正式断言：同一份真实注册脚本写
> `engine.camera_yaw` / `camera_pitch`）**、③ 玩家相机模式（场景 active_camera 经
> `apply_camera` / 运行期改相机实体再 apply_camera / 脚本直接写 `engine.camera`）、
> ④ 开发者视角鼠标（同一串右键拖动 + 滚轮 → yaw/pitch/distance 逐步手算）、⑤ 相机挂父
> （父物体**运行期**移动/旋转后的变换传播；P1 门验的是加载期，本组验运行时）、⑥ 投影参数
> （fov/near/far/ortho/ortho_size：参数逐项相等 + 投影矩阵逐元素相等，理由见门文件头）。
> **夹具与生产同构**：GL 走 `runtime.PlayerApp.render(dt)` 的生产渲染帧（相机段在
> `_prepare_main_pass`，VP 落在 `self._vp`）；组 ④ 的 GL 端走 `editor.EditorApp`
> —— GL 侧开发者视角鼠标的**唯一生产实现**是 `editor._update_camera`（VK 的
> `apply_dev_camera_mouse` docstring 自述「公式与 GL editor._update_camera 逐位一致」）；
> VK 走 `advance_logic(dt)` + `render_pose(aspect)`（= `vk_player.draw` 的生产调用次序）。
> **位姿读取保真**：每次测量都断言「用生产字段 + 生产纯函数重建的 V@P == 该端本帧生产 VP」，
> 把「我们读的字段 == 渲染器读的字段」变成可判定事实（§5 反模式 8 的牙）。
> **有牙证明**：把唯一实现 `loom_camera.orbit_camera_eye` 的 y 分量符号临时改掉 → **36 条
> 当场红**；还原后回到 189/6。注意此时「两端相等」仍成立（两端调同一份函数）—— 正是
> 「只比两端会漏掉两端同坏、必须同时比手算期望」的同一教训（§4.1 P1 那段的判据）。
> **门红点 = Q-B7-45-1（已修，2026-11-19）**：GL 只有一组角度字段（轨道与玩家相机共用
> `camera_yaw/camera_pitch`，`loom_camera.CameraMixin.apply_orbit_camera` 读它）；VK 有两组
> （轨道用 `self.yaw/self.pitch` —— `scene_driver.render_pose:1298` / `camera_pos:899` /
> `_sync_orbit_camera_state:1955` 全读它；`camera_yaw/camera_pitch` 是**玩家相机**角度）。
> 后果：同一份脚本写 `engine.camera_yaw` 想转轨道相机 → GL 生效、**VK 不生效**（且 VK 下一
> 渲染帧帧首 `_sync_orbit_camera_state` 还会把 `camera_yaw` 覆盖回 `yaw`）。实测：GL 眼睛
> =(-8.939,-3.753,-0.480) / fwd=(0.828,0.479,0.290)（= 按新角度手算的期望表），VK 仍是场景
> 初值 =(-7.658,6.673,-3.870) / fwd=(0.721,-0.389,0.573)；两端 VP max|Δ|=3.544。
> 归属：`scene_driver.py:624-633 / :899 / :1298 / :1952-1958`（字段分两组）；GL 是基准，未改。
> **修法（Q-B7-45-1 已修，2026-11-19，方案 A = 按模式别名，复刻 GL 的单组语义）**：
> `scene_driver.SceneDriver.__setattr__` 加一张模块级别名表 `_ORBIT_ANGLE_ALIAS` ——
> **orbit_mode=True** 时 `camera_yaw/camera_pitch` 与 `yaw/pitch` 是**同一份值**（双向：
> 写哪个都等于写轨道角度，读哪个都读到轨道角度）；**orbit_mode=False** 时两组互不相干
> （`camera_yaw` 仍是玩家相机角度，修前行为逐位不变）。VK 内部 13 处 `self.yaw/self.pitch`
> **一行未改**，`yaw/pitch` 两个名字**保留**（现有 VK 脚本反向兼容）。
> 帧首 `_sync_orbit_camera_state` 不再可能覆盖脚本写的角度：正常路径两者已相等（别名保证）
> 故**不写**，只在「确实不等」（有人绕过 `__setattr__` 直写）时才补镜像。
> 为什么用 `__setattr__` 而不是 `@property`：属性名一旦在类体里 def，会被
> `test_engine_api_matrix`（AST 扫类体）与 `test_user_api_parity`（`dir(SceneDriver)`）
> 记成「VK 独有的公开成员」→ 两张差异名单都会变大（本任务明令不许）；`__setattr__` 是
> dunder，不进这两张表，且是唯一能拦住用户脚本直接赋值 `engine.camera_yaw = x` 的钩子。
> **修后证据**：门 195 PASS / 0 FAIL（组 ② 6 条红全绿）；探针
> `Loom/tests/_tmp/qb745_script_probe.py`（15/15）—— 同一份脚本写 `camera_yaw=1.234` /
> `camera_pitch=0.5`，两端位姿 = ((-8.939340825701304, -3.753106463250436,
> -0.48012499388361096), (0.8282784021417753, 0.479425538604203, 0.2900104161569676),
> (-0.4524905533738882, 0.8775825618903728, -0.15843341242718523)) 逐值相等且 = 手算期望，
> 两端生产 VP max|Δ|=0；反向兼容：`engine.yaw/engine.pitch` 老写法仍驱动轨道相机
> （位姿 = 手算期望），且与 `camera_yaw` 双向同步；回归：玩家相机模式下写 `camera_yaw`
> 不污染 `yaw/pitch`、帧首同步不覆盖脚本写的相机角度。
> 相关门全绿（修后实测）：`test_input_chain_parity` 106 / `test_mouse_lock_parity` 62 /
> `test_ui_hit_parity` 144 / `test_scene_load_parity` 76 / `test_audio_parity` 105 /
> `test_vk_camera_align` 85 / `test_user_api_parity` 8 / `test_engine_api_matrix` 6；
> `run_all` 全绿 228.4s；`tools/smoke.py` EXIT 0。
> **残留（只报告不锁，本单范围外）**：① `vk_renderer.orbit_camera` 的第三份公式拷贝仍是
> 死代码待清理（解耦规则 3）；② 边界情形「玩家相机模式下写 `camera_yaw` 后脚本再把
> `orbit_mode` 置 True」两端仍可能不同（GL 用刚写的值，VK 帧首以 `yaw` 为准）—— 修前同样
> 存在，不是本次引入，**未核**（无门覆盖，需人类决定是否补）。
> **稳定性**：本门连跑 20 次，**20/20 完全一致**（每次 189 PASS / 6 FAIL，FAIL 标签签名同一），
> 无偶发红（单次约 3.8s）。
> **已知残差（只报告不锁）**：`vk_renderer.orbit_camera:284-291` 是轨道相机眼睛位置公式的
> **第三份拷贝**（全仓 0 调用点 = 死代码，公式与 `loom_camera.orbit_camera_eye` 逐字相同 →
> 无行为差异），属解耦规则 3 的待清理项，不是 P5 的行为差异。
> **未核（本门不覆盖，留痕）**：① 相机 roll（侧头倾斜）本门只取 roll=0 —— 由既有门
> `test_vk_camera_align.py`（85 条，仍全绿）覆盖；② GL 编辑器的场景相机恢复把 pitch 钳到
> [-1.55, 0]（编辑器特有策略，`editor.py:1161`），本门组 ④ 用负 pitch 避开该钳制，正 pitch
> 的编辑器恢复口径**未核**（属编辑器 UI 策略，不是两端差异）；③ 「右键拖动只在视口内激活」
> （GL 编辑器有面板、VK 播放器整窗即视口）是 UI 形态差异 —— 本门把鼠标事件保持在视口内，
> 视口外拖动的门控**未核**；④ 相机焦点插值动画（editor `_advance_focus_anim`，180ms 线性）
> **未核**（属编辑器交互时序，归 P6 面）；⑤ 打包版（`build_entry`/`game_player`）的相机面
> 未单独跑 —— 本门 GL 端用的就是打包播放器同一个类 `runtime.PlayerApp`，但「真打包产物」
> 未跑（归打包链路，非后端差异）。

> **P6 门当前状态（2026-11-19，HEAD=489e84b 实测）**：`test_pause_parity.py` = **69 PASS / 2 FAIL**
> （**修前红**，照 P1/P2/P3/P4 先例提交：本任务只交门 + 红证据，业务代码一行未改）。
> **P6 与 P1~P5 的区别**：前五面比的是「数值 / 状态」，本面比的是**玩家在窗口里看到的** ——
> 判据是「同一串暂停/单步操作后，两端画出来的那一帧逐像素相等」，外加「画面推进量 ==
> 逻辑推进量」这条把画面与逻辑钉在一起的桥。**P2 已覆盖的「暂停期 mouse_rel 不结算不累积」
> 「暂停期按解锁键」本门不重复**（见本表 P2 行）。
> 六组：① 暂停期逻辑冻结 + 渲染继续 + 画面逐像素稳定（10 个渲染帧：两端逻辑帧计数 Δ=0、
> 位姿/动画时间/刚体速度逐值不变、GL `_stage_frames` +10 且 VK `draw_frame` +10、实测
> FPS≈89、暂停第 1 帧 == 第 10 帧 MAE=0/MAX=0）；② F10 单步**恰好** 1 个逻辑帧（喂真 F10 键
> 事件走内核唯一入口 → 逻辑帧计数 +1，不是 0 也不是 2；位移 == 手算 `SPEED*fixed_dt`
> 逐值相等；连按 3 次 == +3）；③ 恢复无欠账（暂停 30 个渲染帧后恢复 → 首帧增量 == 正常一帧
> 的量 = 手算 `render_dt/fixed_dt` = 1，位移 == 1 步，`pending_steps()` 都为 0）；④ 暂停期
> 画面 == 暂停时刻画面（10 帧后仍 MAE=0）+ 暂停不跳变 + 恢复后真的动 + 恢复首帧 == 参照对
> 「正常 1 帧」的画面；⑤ 单步的画面推进 == 逻辑推进（单步 1/3 次的画面 == 参照对「正常
> 1/3 帧」的画面，**逐像素**）；⑥ 两端截图对拍 4 个时刻（暂停瞬间 / 单步 1 / 单步 3 /
> 恢复后）MAE<=2e-4 且 NCC>=0.999。
> **夹具与生产同构**：GL 走 `runtime.PlayerApp.render(dt)`（暂停分支
> loom_render:1153-1193、F10 消费 :1174-1183），VK 走 `advance_logic(dt)` +
> `render_pose(aspect)` + `VkRenderer.draw_frame`（= `vk_player.draw:643-725` 的生产调用
> 次序）；键事件两端同一串喂 `handle_key_event`（内核 S1 唯一入口）；画面取自**生产渲染
> 目标**（GL 的 `_external_fb` / VK 的离屏纹理，test_ab_gl_vk 既有口径，FBO 回读 flipud）。
> **判据独立性**：逻辑帧计数用**独立计数器**（构造引擎前对 `_logic_frame` 做类级包装，不看
> 任何一端自报的 `steps`）；位移/动画时间**手算**（`x += SPEED*fixed_dt` 逐步累加，与脚本 /
> evaluate_animations 同一个表达式）；画面推进量用**另一条生产路径**当参照（同一构造 + 同一
> 预热序列的第二个 Pair 正常推进 1/3 帧）—— 这条同时证明「单步的画面 == 1 个 fixed_dt 的量」
> 而不是 0 或多帧。
> **门红点 = P6-1（只报告不修，需人类/lead 裁决归属）**：两端**暂停边界**的插值对齐不同 ——
> 内核 `EngineCore.set_logic_paused`（engine_core.py:273-292）在暂停时做
> `_interp.align()`（prev←curr）+ `_render_world=None`；VK 的覆盖版
> `SceneDriver.set_logic_paused`（scene_driver.py:1027-1047）**两者都不做**。
> 后果（用户可感知）：按 F9 的**瞬间**，GL 的画面**向前跳 1 个逻辑帧**（冻结的是 curr），VK 停在
> 原画面（冻结的是 prev）→ 同一场景同一时刻按 F9，两端冻结画面差 1 帧的位移；且 GL 上「暂停
> 后第一次 F10 画面几乎不动」（那一帧已在暂停瞬间预支）。
> 实测（3 物体场景）：暂停瞬间 GL vs VK **MAE=2.97e-4 / MAX=0.518 / NCC=0.973**（门限 2e-4）；
> 其余 3 个时刻 MAE<=3.1e-7 / NCC>=0.99999（说明差异只在暂停边界）。
> 诊断表：暂停瞬间画面 vs 参照「正常 0 帧 / 正常 1 帧」—— GL: 2.96e-4 / 2.3e-7（= **1 帧**），
> VK: 0 / 2.97e-4（= **0 帧**）。
> **有牙证明（运行时变异，不改业务文件）**：把 GL 的 `it.align()` 在运行时关掉 → 暂停瞬间两端
> MAE=**0.0**；给 VK 运行时补上 `it.align()` → 同样 MAE=**0.0**（基线 8.38e-5，单物体场景）。
> 探针 `Loom/tests/_tmp/p6_probe30_rootcause.py`。
> 归属两读（**待裁决**）：① 按「GL 是基准」的既有口径 → VK 的 `set_logic_paused` 缺
> `_interp.align()` + `_render_world` 失效（scene_driver.py:1027-1047）；② 按「暂停不得跳变」的
> 用户语义 → GL 侧的 align 是跳变源（engine_core.py:285-291）。
> **稳定性**：本门连跑 **20 次，20/20 完全一致**（每次 69 PASS / 2 FAIL，FAIL 标签签名同一），无偶发红
> （单次约 8.2s）。
> **相关门全绿（2026-11-19 修前红状态下实测）**：`test_input_chain_parity` 106 /
> `test_mouse_lock_parity` 62 / `test_ui_hit_parity` 144 / `test_scene_load_parity` 76 /
> `test_audio_parity` 105 / `test_camera_parity` 195；`run_all` 234.5s —— **唯一失败 =
> `test_pause_parity.py`**（其余 154 个文件全绿）；`tools/smoke.py` EXIT 0（7.3s，4 PASS / 3 SKIP
> 源码模式）。
> **未核（本门不覆盖，留痕）**：① GL 的「墙钟下限」路径（floor=True 真正生效、帧长 > dt 时多追
> 逻辑步）—— 本门把该输入项归零以获得可手算的确定性；② 真窗口 swapchain 回读（画面取自生产
> 渲染目标，swap 后回读未定义且本夹具 VK 侧无窗口）；③ 绑死模式（设置 `logic_fps<=0`）下的
> 暂停/单步；④ UI/HUD 叠加层（GL 播放器 `_draw_hud` 是 pass、VK 默认 `hud_lines=None`，有 UI
> 的场景归 P3 面）。

> **P6 修后状态（2026-11-19，HEAD=0f0dc54 之上实测）**：`test_pause_parity.py` = **71 PASS / 0 FAIL**
> （P6 面门全绿，六面闭环）。**P6-1 的裁决 = ② 按「暂停不得跳变」**（人类原话）。
> **分析（`align()` 在暂停分支原本防什么）**：暂停分支那四件事（`clk.reset()` /
> `_logic_wall_last=None` / `it.align()` / `_render_world=None`）都是「边界收尾」套路：
> `clk.reset()` 把 accumulator 与 alpha 归零（不补暂停期欠账），于是渲染帧的插值相位被钉在
> `alpha=0`；此时若 prev≠curr，画面显示的是 **prev**（落后 curr 一个逻辑帧）。`align()` 就是把
> prev 拉到 curr，让**冻结的画面 = 最新逻辑状态 curr**，顺带让 `InterpState.static_frame()` 恒真
> （暂停期每帧跳过插值世界矩阵重算）。也就是说它防的是「暂停后画面停在一个**过时的**逻辑帧
> 位姿上」。**为什么现在判定它错**：① 插值层的契约是「画面落后 curr 一个 (1-alpha) 帧」，而暂停
> **不改任何位姿、只停时间** —— prev/curr 正是玩家最后看到那一帧的依据，把 prev 拉成 curr 等于
> **在暂停瞬间篡改画面**（实测位移恰好 = 1 个逻辑帧：暂停瞬间画面 == 参照「正常推进 1 帧」、
> 暂停前最后一帧 == 「正常 0 帧」，MAE 2.96e-4）；② 人类裁定的用户语义是「按 F9 就地冻结」，
> VK 的覆盖版（只 `clk.reset()`）已经是对的；③ 它还有副作用缺陷：暂停后**第一次 F10 画面几乎
> 不动**（那一帧在暂停瞬间已被预支）。**与其它 5 处 `align()` 的判据**：那 5 处的**位姿本身刚刚
> 被换掉**（换场景 / 进出播放 / 编辑器首帧 / VK 加载 / 直接改位姿），必须把 prev 钉到新位姿，
> 否则首帧会从旧位姿插值过来（`loom_model_gpu.py:298`「第一帧从原点飞过来」）；暂停是唯一
> 「位姿不变、只有时间停」的边界 → **prev 必须保留**。所以只删暂停分支那一次，`align()` 语义与
> 其它 5 个调用点**一行未动**。
> **修法（选 a：直接去掉暂停分支的 `it.align()`）**：最简，且**恰好让 GL 与 VK 同构**（VK 只做
> `clk.reset()`）。选 b（align 到当前插值位置）被否：它要把 prev 与 curr **同时**写成插值结果，
> 等于丢掉 curr 这个真实逻辑帧 → 恢复后第一次 advance 的插值区间跨 2 个逻辑帧（画面跳 2 帧 =
> 新的欠账），且仍要改共享模块。保留 `_render_world=None`：`clk.reset()` 把 alpha 归 0，缓存的
> 渲染矩阵是旧 alpha 的产物。**代价（可接受，且与 VK 同口径）**：暂停期 `static_frame()` 不再恒真
> → GL 每暂停帧重算插值世界矩阵（VK 本来就每帧 `render_pose`）；实例桶脏闸 `_bucket_frame_sig`
> 含 alpha / 逻辑帧计数 / 静止判定，暂停期三项都不变 → **实例上传仍然只做一次**。
> **修前红原文（69 PASS / 2 FAIL）**：
> `FAIL ④ 暂停瞬间画面 == 暂停前最后一帧画面（按 F9 不得跳变；两端都要成立）  GL mae=0.00029640 max=0.517647 / VK mae=0.00000000 max=0.000000`
> `FAIL ⑥ 4 个时刻两端截图逐像素相等或 MAE<=0.0002 且 NCC>=0.999  暂停瞬间 MAE=0.00029670 NCC=0.973150`
> **修后绿（71 PASS / 0 FAIL）**：④ 暂停瞬间 `GL mae=0.00000000 max=0.000000 / VK mae=0.00000000`；
> ⑥ 暂停瞬间 `MAE=3.1e-7 MAX=0.035294 NCC=0.999990`（其余 3 个时刻 1.4e-7 ~ 3.1e-7）；诊断表
> （暂停瞬间 vs 参照）：GL vs 0 帧 **0.0** / vs 1 帧 2.96e-4（修前是 2.96e-4 / 2.3e-7 —— 方向反了）。
> **门内已绿的断言一条未动**：本任务**没有改测试文件**（`git diff` 只含 2 个生产文件 + 本文档）。
> **加载/进出播放未回归证据**：5 个 `align()` 调用点源码未动（`loom_model_gpu.py:298` /
> `runtime.py:189` / `editor.py:2184`、`:2306` / `scene_driver.py:901` / `loom_transform.py:197`），
> 且相关门全绿：`test_ab_gl_vk`（26 场景，逐场景 MAE 与基线一致）/ `test_editor_playback_matrix` 9 /
> `test_xform_sync` 8（含 `test_write_triggers_align_and_invalidate`）/ `test_interp_state` 10 /
> `test_clock_pause_restart` 19 / `test_beta3_batch2_camera_proj` 74 / `test_scene_load_parity` 76 /
> `test_mouse_lock_parity` 62 / `test_ui_hit_parity` 144 / `test_audio_parity` 105 / `test_camera_parity` 195。
> **恢复不跳变探针**（`Loom/tests/_tmp/p6_probe31_resume_step.py`，修后实测）：暂停 N ∈ {1, 30, 100}
> 个渲染帧后恢复 → **首帧** Δ逻辑帧 = 1 / 1，Δ位移 = 0.033333333333333326（= 手算 `SPEED*fixed_dt`，
> 与 N 无关；不是 N 帧的量也不是 0），两端逐值相同；暂停瞬间画面 vs 暂停前最后一帧 MAE = **0.0**
> （两端各自 + 两端互拍）。
> **全套**：`run_all` 155 个文件 **EXIT 0 / 232.3s**；`tools/smoke.py` **EXIT 0**（6.3s，4 PASS / 3 SKIP）。
> **未核（留痕）**：① 真实帧率下 alpha>0 的暂停边界（本门夹具 alpha 恒 0）—— 此时两端都会把画面
> 从「prev/curr 之间的插值位置」拉回 prev（最多 1 个逻辑帧的后退量），两端**同量**、仍逐像素一致，
> 但后退量本身未做像素级量化；② 真窗口 swapchain 回读；③ 绑死模式（`logic_fps<=0`）下的暂停/单步；
> ④ UI/HUD 叠加层（归 P3 面）。

### 4.1b 六面补完（2026-11-19 全部闭环，**653 条断言全绿**）

| 面 | 门 | 断言 | 状态 | 本轮修出的真缺陷 |
|---|---|---|---|---|
| P1 场景加载/切换 | `test_scene_load_parity.py` | 76 | ✅ 全绿 | R1~R7（VK 不迁移 / 闸门 5 处散落 / GL 先清后校验 / VK 材质 / GL base_dir 等） |
| P2 鼠标锁定与光标 | `test_mouse_lock_parity.py` | 62 | ✅ 全绿 | R1（GL 暂停期 mouse_rel 不冻结）/ F-1（VK 返回值 None）/ F-2（幂等断流）/ F-3（GL 暂停期解不了锁）/ F-6（VK 无 mouse_pos）/ F-7（allowed 语义）/ Q-40-1（GL 打包播放器被拒后不释放光标） |
| P3 UI 命中与焦点 | `test_ui_hit_parity.py` | 144 | ✅ 全绿 | P3-1（GL 滚轮无消费门控）/ Q-41-1（VK 无 ui.resize）/ Q-41-2（跨帧持按 wants_camera 语义） |
| P4 音频播放状态 | `test_audio_parity.py` | 105 | ✅ 全绿 | P4-1（`AudioSystem` 缺 3D 三方法 → **两端同坏**，3D 音效从未响过）/ P4-2（VK 听者不跟随相机）/ P4-3（VK 首帧前 audio=None → 脚本被判坏）/ P4-4（绑死模式 VK 无音频段） |
| P5 相机轨道/开发者视角 | `test_camera_parity.py` | 195 | ✅ 全绿 | Q-45-1（脚本写 `camera_yaw` 在 VK 上转不动轨道相机） |
| P6 暂停/单步窗口观感 | `test_pause_parity.py` | 71 | ✅ 全绿 | P6-1（GL 暂停瞬间画面跳 1 个逻辑帧） |
| **合计** | **6 条门** | **653** | **全绿** | **17 个真缺陷**（口径注：按「B7-16 模块化」计 1 条；逐项拆开列是 23 条 —— 分子分母不同口径，两数都对但**不可混用**） |

**方法论收获（写进 §5 反模式的反面）**：
1. **只做两端对比会漏「两端一致地坏」** —— P4-1 是两端都缺 3D 方法，若门只比 GL vs VK 会全绿；靠「**期望值不取自任何一端**」（手算期望表）才抓出来。
2. **门的夹具会自己骗人** —— Q-43-1（`glfw.set_cursor_pos` 异步落点）导致两条门 10% 偶发假红；不修它，后面每建一面门都在「这是真红还是竞态」里挣扎。
3. **结构断言不许锁「缺陷态」** —— 标题写「VK 没有任何 X 调用点」的断言，修好后必然翻红；要么不写，要么直接锁「修复后的正确形态」。

---

### 4.2 尚无对拍门的面（**按此优先级补**，见 Q-B7-37-1）

> **2026-11-19 独立审核纠错**：本表曾被整表划掉（overclaim）—— 实际**仍有未落地面**：
> **物理面、动画面**（P6 只把它们当夹具探针，无两端对拍）、**打包端到端**（B7-29）、**绑死模式暂停/单步**。
> 这些已登记为缺口（`ARCHITECTURE.md` 图 19.3），不许宣称「无缺口」。

| 优先级 | 面 | 为什么用户能感知 |
|---|---|---|
| ~~**P1**~~（已落地 → §4.1） | ~~场景加载/切换的用户可见结果~~ | 门 = `test_scene_load_parity.py`；B7-17（v8 场景 GL 90° vs VK 1.5708°）由本门锁住 |
| ~~P2~~（已落地 → §4.1） | ~~鼠标锁定与光标捕获~~ **门 = `test_mouse_lock_parity.py`（62 条全绿）**：R1 + F-3（暂停期门控）+ F-1/F-2/F-6/F-7 + Q-B7-40-1（打包播放器路径）全部已修 | — |
| ~~**P3**~~（已落地 → §4.1） | ~~UI 命中与焦点~~ **门 = `test_ui_hit_parity.py`（144 条）**：点击命中 / hover 集合 / 焦点与键盘 / 滚动消费 / UI 消费对引擎的屏蔽 / 坐标系 / 窗口 resize 的画布跟随 / 跨帧持按的相机门控，八组 | P3-1（滚轮脚本可见值）**已修**（2026-11-18，判据抽共享前置 `loom_ui_input.py`）；Q-B7-41-1（VK 补 `ui.resize`，共享前置 `loom_ui_resize.py`）与 Q-B7-41-2（VK 的相机门控对齐 GL 的 `ui_consumed`）**已修**（2026-11-18）→ 144 全绿 |
| ~~**P4**~~（已落地 → §4.1） | ~~音频播放状态（play/stop/3D 位置/音量）~~ **门 = `test_audio_parity.py`（105 条，修前红 90 PASS / 15 FAIL）**：播放状态机 / 3D 听者同步 / 每帧更新时序 / 暂停期行为 / 无音频设备降级 / 脚本 API 面，六组 | 有声卡就能听出来 → 已量化为「两端音频实例状态 + 后端调用序列 + 设备通道占用」逐项相等；四条缺陷 **P4-1~P4-4 已全部修完**（105 PASS / 0 FAIL，2026-11-19） |
| ~~**P5**~~（已落地 → §4.1） | ~~相机轨道 / 开发者视角~~ **门 = `test_camera_parity.py`（195 条，195 PASS / 0 FAIL）**：轨道相机 / 脚本写角度字段 / 玩家相机模式 / 开发者视角鼠标 / 相机挂父运行时传播 / 投影参数，六组 | 编辑器用户直接感知 → 已量化为「两端相机位姿三元组（眼睛位置 / 前向 / 上方向）逐值相等且 = 手算期望表」；**Q-B7-45-1 已修**（2026-11-19：VK 的 `camera_yaw/camera_pitch` 按 `orbit_mode` 与 `yaw/pitch` 互为别名，脚本写 `camera_yaw` 两端都转轨道相机；修前红 189/6 → 修后 195/0） |
| ~~**P6**~~（已落地 → §4.1） | ~~暂停 / 单步的窗口级观感~~ **门 = `test_pause_parity.py`（71 条，修前红 69 PASS / 2 FAIL）**：暂停期逻辑冻结 + 渲染继续 + 画面逐像素稳定 / F10 恰好 1 逻辑帧（独立计数器 + 手算位移）/ 恢复无欠账（暂停 30 帧后首帧仍 1 步）/ 单步画面 == 参照对「正常 1 帧」的画面（逐像素）/ 4 个时刻两端截图 MAE<=2e-4，六组 | 冻结画面差 1 个逻辑帧 = 玩家肉眼可见 → 红点 **P6-1 已修**（2026-11-19，人类裁决「② 按暂停不得跳变」→ 去掉 GL 暂停分支的 `it.align()`，两端都就地冻结；修前红 69 PASS / 2 FAIL → 修后 71 PASS / 0 FAIL，见 §4.1 P6 段） |

---

## 5 反模式清单（都是本工程**真犯过**的，新增 API 时逐条自查）

| # | 反模式 | 真实案例 | 正确做法 |
|---|---|---|---|
| 1 | **只对齐方法名，不对齐语义** | B7-24 最初只做「方法名集合差异」，结论是「差 79 条」；但真正的问题在语义 | 门必须断言**行为**（同一输入 → 同一输出），不是断言「方法存在」 |
| 2 | **在 EngineCore 写空实现当钩子** | `_backend_light_removed` 在 EngineCore 里写空实现 → MRO 中 EngineCore 在前，GL 的覆盖被遮住 → 删光源不再释放阴影贴图 | 钩子用 `getattr(self, '_backend_xxx', None)` 取；**不要**在公共层写同名空实现 |
| 3 | **门用被测对象自己当判据** | 性能门用 `fastpath.aabbs_simd_impl()`（被测对象自报）决定要不要测 → 探测坏了就整段跳过、测试全绿 | 判据必须**独立**（如 `kernel32!IsProcessorFeaturePresent`），「独立判据说支持而自报不支持」→ **FAIL 而不是 SKIP** |
| 4 | **改测试去迎合代码** | 把门里 3 条断言改掉，理由是「旧断言锁的正是缺陷」—— 而那条「缺陷」根本没被证明过 | 改断言前先证明旧断言**本身错了**；否则先修代码 |
| 5 | **静默差异** | VK 按 F11 完全没反应、GL 置顶静默失败（`except: pass`） | **允许差异，不允许差异是隐形的**。不支持就显式报（`NotSupportedOnBackend` / 打印一次） |
| 6 | **修 A 引入 B，被全绿掩盖** | 加 `screen_format` 时把 `_fmt_key` 写进 if 分支内 → `clear_color` 非默认时 UnboundLocalError；tests 里 `clear_color` 零命中 → run_all 全绿 | **新参数/新分支必须有门**；改完跑「非默认参数」用例 |
| 7 | **拿自报数字当证据** | 声称「单独连跑 3 次稳定 0.80」，审核实测 0.96/0.72/0.84 | 数字必须**自己真跑**，并写清**口径**（如「余量 = 阈值÷实测最坏−1」） |
| 8 | **门用假夹具，与生产不同构** | 门里 `_FakeBridge` 与 `_FakeUI` 是两个对象，生产里 `UIInputBridge.ui is driver.ui` 是同一个 → 「双重派发」这个真风险测不到 | 夹具用**生产那个类 + 生产构造式**；并加一条「夹具保真」断言 |
| 9 | **超范围顺手改** | 修全屏时顺手改 GL 的置顶/还原，导致两端不一致 | 一次只改一个面；跨面改动必须单独立项 + 单独审核 |
| 10 | **文档/注释与事实不符** | 注释写「F11 已统一」，实际 VK 侧 `allow_fullscreen` 根本不存在 | 注释必须与代码同步；「链路已统一」≠「每个键都生效」 |

---

## 6 一页速查（新增后端 API 时贴在眼前）

`@
□ 分类：用户 API / 后端内部？（拿不准按用户 API）
□ 公共实现进 EngineCore，后端差异进 _backend_* 钩子
□ 两端是同一个函数对象吗？（getattr(GLEngine,n) is getattr(SceneDriver,n)）
□ 写了「两端对拍门」吗？（同一输入 → 逐项相等，失败值也测）
□ 修前必红真跑了吗？（贴红的断言原文）
□ 修后绿 + 相关既有门 + run_all 全绿？
□ 未做/未核/已知差异都留痕了吗？
□ 派了独立审核子代理吗？（一个组件一个代理）
`@

---

## 7 适用范围

| 场景 | 是否适用 |
|---|---|
| 新增后端 API | **必须** |
| 修改现有后端行为 | **必须** |
| 新增后端（D3D / Metal / 软件光栅） | **必须**（新后端必须实现 §2 的 ① 层全部条目） |
| 纯内部重构（不改可观察行为） | 适用 §3 第 5-6 步（回归 + 留痕），可不写新门，但**必须证明行为零变化** |
| 文档 / 注释修改 | 不适用，但**不许写与事实不符的内容** |

---

> **本文件的维护**：每次新增一面「对拍门」，更新 §4.1；每次发现新的反模式，追加到 §5。
> 相关：`docs/design/契约_IEngineAPI_20261117.md`（接口正文）、`docs/design/设计_单一引擎门面_后端下沉_20261117.md`（架构形状）、
> `docs/guides/AI协作工程方法论_合并版_20261117.md`（审核方法）。
