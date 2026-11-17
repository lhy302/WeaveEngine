# 契约 · `IEngineAPI`（引擎公共接口）· 2026-11-17

> **这是什么**：beta7 批 0a 的产物 —— 一份两端（GL `GLEngine` / VK `SceneDriver`）都必须实现的**公共接口白盒契约**。
> 脚本、内容、工具链**只允许依赖本契约**；契约之外的成员（§6 仅 GL、§7 非契约）**不得**出现在脚本里。
>
> **状态**：主审起草（2026-11-17），**等人类复核**。其中 §4.3「B 类形态统一方向」标为 `主审暂定（可推翻）`。
> **依据裁决**：Q-B7-24-1 认可 A 边界 · Q-B7-24-2 属性面进契约（口径升 v2）· Q-B7-24-3 仅 GL 面**显式失败** · Q-B7-24-4 批 0 拆 0a/0b。
> **取证**：[../audit/impl_B7-24_API矩阵_20261117.md](../audit/impl_B7-24_API矩阵_20261117.md) · **门**：`Loom/tests/test_engine_api_matrix.py`
> **口径**：v2（含普通类属性）。v1（不含属性）数字为 GL 105 / VK 38，两套数字**不可混用**。

---

## 0 契约的边界（三句话）

1. **契约面 = A 40 + B 15 = 55 条**。两端都必须有、同名、同签名、同可观察语义。
2. **仅 GL 面 = C 20 条**。VK 侧调用必须**显式抛** `NotSupportedOnBackend`（Q-B7-24-3 裁决 a）——**允许差异，不允许差异是隐形的**。
3. **非契约面 = D 12 条**。public 但语义私有，转 `_xxx`；契约不承诺，脚本不得使用。

现状（口径 v2，2026-11-17 实测）：GL 公开成员 **109**，VK **39**，共同 **29**，GL 独有 **80**，VK 独有 **10**。
80 + 10 = 90 条差异的**全部去向**：A 40 / B 8+7 / C 20+2 / D 12 / 口径假差异 1（`script_keys`，见 §10）。

---

## 1 口径与复算

```powershell
$env:LOOM_NO_DIALOG='1'
py -3.13 Loom/tests/test_engine_api_matrix.py          # 门（差异只许缩小）
py -3.13 Loom/tests/test_engine_api_matrix.py --list   # 打印矩阵（含签名来源的定义点）
```

**v2 口径**：类体内 `def`（含 `@property` / `@staticmethod` / `@classmethod`）+ **公开类属性**；名字不以 `_` 开头；
递归收集基类（GL 侧 8 个 mixin）；同名按 MRO 最近者为准。**只看存在性**，签名与语义由本契约正文规定。

**口径已知盲区（v3 候选，本次不做，留痕）**：`__init__` 里 `self.x = ...` 赋的**实例属性**不在矩阵内。
已确认它会产生一条**假差异**：`script_keys`（见 §10）。

---

## 2 六元组总则

### 2.1 接口面三段

| 段 | 内容 | 条数 | 两端都必须有？ | 违反时 |
|---|---|---|---|---|
| **核心**（§3 + §4） | 脚本/内容/工具链会用的能力 | **55** | **是** | 门红 |
| **仅 GL**（§6） | GL 立即模式绘制 / GLFW 回调 / GL 帧循环 / 诊断 | **20** | 否（VK 侧显式抛） | 必须抛 `NotSupportedOnBackend` |
| **非契约**（§7） | public 但语义私有 | **12** | 否 | 转私有后自然不可达 |

### 2.2 前置条件（调用方保证）

- **P1 线程**：所有 API 只在**主线程**（渲染线程 / 引擎所属线程）调用。逻辑线程、脚本回调之外的其他线程**不得**直接调。
- **P2 生命周期**：`__init__` 完成后、`run()` 之外、`close()`/退出之前。帧内（`advance_logic` / `render` 内部）**不得**重入。
- **P3 对象有效性**：传入的 `model` / `guid` / `CameraState` / `LightState` 必须是**本引擎实例**当前持有的对象；
  已 `remove_*` 的对象视为失效，再传即非法（E2）。
- **P4 参数域**：见各条签名与 §2.7 非法域；`None` 只在签名显式允许处合法。

### 2.3 后置条件（引擎保证）

- **Q1 立即一致**：返回时，该 API 承诺的可观察状态**已生效**（不做延迟到下一帧的隐式批处理），
  例外仅 `add_*` / `remove_*` 的 GPU 上传（可延迟到本帧渲染前，但**数据面立即一致**）。
- **Q2 返回值**：签名声明的返回类型；查找类失败返回 `None` / `[]`（E4），**不抛**。
- **Q3 副作用范围**：只影响被点名对象及其（签名声明的）子树；**不得**改写调用方未提及的对象。
  这条直接对应 beta6 的教训：GL 侧阴影容量改写场景数据（B7-22 待收敛）。
- **Q4 可观察等价**：见不变量 I1。

### 2.4 不变量

| 编号 | 不变量 | 为什么必须有 |
|---|---|---|
| **I1 后端无关** | 同一场景 + 同一输入序列 → 同一可观察状态：对象集合与 guid、变换、层/标签、碰撞事件序列、UI 命中结果、脚本回调序列 | 这是 beta7「双后端无感切换」的唯一要求（路线登记 §6.1） |
| **I2 单位** | 长度 = 米；**角度 = 度（deg）**；时间 = 秒 | **B7-17 就是踩这个**：v8 场景 GL `yaw=90.0` vs VK `1.5707963`。契约层面钉死「对外一律度」 |
| **I3 坐标系** | 右手 Y-up；矩阵为**行向量**；局部 = `S@R@T`，世界 = 局部 @ 父世界 | 两端 packer 语义相反过（B7-22 列此项） |
| **I4 身份稳定** | 同一对象的 `guid` 在两端、在存盘/读盘前后**不变**；`guid` 全局唯一 | 资产/场景/撤销都靠它 |
| **I5 幂等** | `register_tag` 幂等（已存在 → `False`）；`remove_*` 对不存在对象 → `False` 不抛 | 幂等是脚本能安全重试的前提 |
| **I6 不静默** | 任何失败必须**可见**（抛异常 / 返回 `False` / 明确 `None`）；**禁止**「静默降级到另一个后端」或「静默丢弃调用」 | 环境适配型降级可以但要可见；缺陷型失败必须显式（方法论 §6.3） |

### 2.5 错误模型

| 编号 | 类型 | 触发 | 处置 |
|---|---|---|---|
| **E1** | `NotSupportedOnBackend(api, backend)` | 在 VK 下调用 §6「仅 GL」的 API | **抛**。异常文本必须含：API 名 + 当前后端 + 替代路径 |
| **E2** | `ValueError` | 参数非法：层越界、坐标 NaN/Inf、自环/设为子孙、几何非法、失效对象 | **抛** |
| **E3** | `TagNotRegisteredError` | `set_object_tag` 用未注册 tag | **抛**（LayerTag 契约 §9） |
| **E4** | 返回 `None` / `[]` / `-1` / `False` / 空串 | 查找不到、移除不存在、层名未命名 | **不抛**（查找失败是合法域，不是错误） |
| **E5** | `AttributeError` 或 `False` | `send_message_to_name` 目标不存在 / 目标无该方法 | **必须可见**：日志 + 返回 `False`；**不得**静默吞（I6） |
| **E6** | 复用语义 | `add_material` 同名材质 | 见 §3 该条；**必须**在契约里写明是复用还是新建，不许两端各猜 |

### 2.6 资源边界

| 资源 | 谁持有 | 谁释放 | 契约承诺 |
|---|---|---|---|
| 模型几何（VBO/IBO） | 引擎 | `remove_subtree` / `clear_scene` / 退出 | 调用方**不释放**，也不得保留引用跨帧使用 |
| 材质 | 引擎材质库 | 引擎（无显式删除 API） | `add_material` 返回的 `Material` 是**引用**，不是所有权 |
| 纹理 / 资产 | 资产库（guid 引用计数） | 资产库 | API **不转移所有权** |
| 阴影贴图 | 引擎（按灯） | `remove_light` | 释放由引擎负责，调用方无感 |
| 相机 / 光源实体 | 场景 | `remove_camera` / `remove_light` | 句柄失效后不得再用（P3） |

### 2.7 非法域（不得出现在脚本/内容里）

- 以 `_` 开头的任何成员；
- §6「仅 GL」的 20 条（VK 下会抛 E1）；
- §7 非契约的 12 条（转私有后不可达）；
- 编辑器专属语义：选中态（`get_current_model` / `select_next_model`）、gizmo 换算、撤销栈内部（`attach_model`）；
- 任何 `GLEngine` / `SceneDriver` 的**构造参数**与内部字段（`self.m` / `self.models` / `self.buckets` 等）。

---

## 3 A 类：脚本/内容会用的公共 API（40 条，VK 必须补齐）

> 判据：语义上是「脚本 / 内容 / 工具链会调用的能力」。**签名以 GL 侧为契约签名**（§4.3 同一裁决）。
> 「VK 落地动作」列 = 0b 要做的具体事；「错误/边界」列 = 该条在 §2.5 上的具体化。

| 方法 / 属性 | 契约签名（GL 为参考） | 语义（源码 docstring 首行） | VK 落地动作 | 错误 / 边界 | 定义点 |
|---|---|---|---|---|---|
| `add_camera` | `add_camera(self, position=None, yaw=0.0, pitch=0.0, roll=0.0, fov=60.0, fov_locked=True, name=None, guid=None, pitch_lock=False, pitch_min=-85.0, pitch_max=85.0)` | 添加场景摄像机实体 (不可见实体, 不渲染网格/不参与拾取). 返回 CameraState. | VK 补齐同名同签名 | 返回 CameraState；父/场景非法 → E2 | Loom/loom_camera.py:128 |
| `add_light` | `add_light(self, kind='directional', position=None, direction=None, color=(1.0, 1.0, 1.0), intensity=1.0, name=None, guid=None, mode='full', shape='circle', size=5.0, shadow=True, azimuth=None, elevation=None, roll=None, range=10.0, spot_inner_angle=30.0, spot_outer_angle=60.0)` | 添加场景光源 (不可见实体, 不渲染网格/不参与拾取). 返回 LightState. | VK 补齐同名同签名 | 返回 LightState；灯型未知 → E2 | Loom/loom_lighting.py:44 |
| `add_material` | `add_material(self, color=None, saturation=1.0, name=None, guid=None)` | 新建材质并加入材质库 (供物体共享引用). 返回 Material. | VK 补齐同名同签名 | 返回 Material；同名 → E6 | Loom/loom_model_gpu.py:60 |
| `add_model` | `add_model(self, mesh, position, rotation, normal_mode='flat', name=None, scale=None, visible=True, color=None, saturation=1.0)` | 添加模型并一次性上传展平几何到 VBO. | VK 补齐同名同签名 | 返回 guid；几何非法 → E2 | Loom/loom_model_gpu.py:31 |
| `apply_game_bindings` | `apply_game_bindings(self)` | 把**用户层** key_bindings 叠加到 self.actions（最高优先级层）. | VK 补齐同名同签名 | 见 §2.5 | Loom/loom_input.py:520 |
| `clear_scene` | `clear_scene(self)` | 清空全部模型 (M16: 新建/加载场景用) | VK 补齐同名同签名 | 释放全部 GPU 几何 | Loom/loom_model_gpu.py:342 |
| `collider_bounds` | `collider_bounds(self, m, M=None)` | 世界空间碰撞体数据 -> ('box', (mn, mx)) 或 ('sphere', (center, radiu | VK 补齐同名同签名 | 见 §2.5 | Loom/loom_physics.py:118 |
| `find_all_by_name` | `find_all_by_name(self, name)` | 按物体名查找所有匹配（与 find_by_tag 返回列表一致）。 | VK 补齐同名同签名 | 找不到 → []（E4） | Loom/engine.py:675 |
| `find_by_name` | `find_by_name(self, name)` | 按物体名查找首个匹配（Unity GameObject.Find 语义）。 | VK 补齐同名同签名 | 找不到 → None（E4） | Loom/engine.py:662 |
| `find_by_script` | `find_by_script(self, script_id)` | 查找挂有指定脚本的物体（按 script_id 匹配，物体去重）。 | VK 补齐同名同签名 | 找不到 → []（E4） | Loom/engine.py:685 |
| `find_by_tag` | `find_by_tag(self, tag)` | 查找所有指定标签的物体 (不区分大小写). | VK 补齐同名同签名 | 不区分大小写；找不到 → []（E4） | Loom/engine.py:655 |
| `get_bounding_box` | `get_bounding_box(self, model, M=None)` | 获取模型的轴对齐包围盒 (AABB), 用世界矩阵变换 (含父链 S@R@T). | VK 补齐同名同签名 | 无几何 → None（E4） | Loom/loom_transform.py:407 |
| `get_logic_time_ratio` | `get_logic_time_ratio(self)` | 逻辑时钟拿到的时间 / 真实墙钟 (1.0 = 时钟没被 dt 口径亏欠)。 | VK 补齐同名同签名 | 1.0 = 未亏欠 | Loom/engine.py:1610 |
| `get_tps` | `get_tps(self)` | 实测 TPS (逻辑帧/秒, 2 秒滑动窗口; 状态栏直读). 暂停时 → 0. | VK 补齐同名同签名 | 暂停时 → 0 | Loom/engine.py:1624 |
| `layer_id` | `layer_id(self, name)` | 层名 -> 层编号 (找不到返回 -1). | VK 补齐同名同签名 | 找不到 → -1（E4） | Loom/engine.py:645 |
| `layer_name` | `layer_name(self, layer_id)` | 层编号 -> 层名 (未命名/越界返回空串). | VK 补齐同名同签名 | 越界/未命名 → 空串（E4） | Loom/engine.py:640 |
| `model_world_matrix` | `model_world_matrix(self, m)` | 物体世界模型矩阵 (行向量): local(S@R@T) @ 父世界矩阵 沿父链合成 | VK 补齐同名同签名 | 见 §2.5 | Loom/loom_transform.py:57 |
| `mouse_lock_allowed` | `mouse_lock_allowed = False` | — | **VK 加只读 property**（现只有 setter） | 只读；写请用 set_mouse_lock_allowed | Loom/loom_input.py:225 |
| `mouse_locked` | `mouse_locked = False` | — | **VK 加只读 property**（现只有 set_mouse_locked/toggle） | 只读；写请用 set_mouse_locked | Loom/loom_input.py:226 |
| `mouse_unlock_requested` | `mouse_unlock_requested = False` | — | **VK 加只读 property**（现只有 poll_unlock） | 只读；引擎置位 | Loom/loom_input.py:227 |
| `raycast` | `raycast(self, origin, direction, max_dist=1000.0, ignore_model=None, backend='auto', layer_mask=None)` | 射线检测: 返回最近命中的物体. | VK 补齐同名同签名 | 无命中 → None（E4） | Loom/loom_raycast.py:194 |
| `raycast_all` | `raycast_all(self, origin, direction, max_dist=1000.0, backend='auto', layer_mask=None)` | 射线检测: 返回所有命中（按距离升序）. | VK 补齐同名同签名 | 无命中 → []（E4） | Loom/loom_raycast.py:246 |
| `raycast_screen` | `raycast_screen(self, px, py, max_dist=1000.0, ignore_model=None, backend='auto', layer_mask=None)` | 从屏幕像素 (px, py) 反投影发射线，返回最近命中. | VK 补齐同名同签名 | 无命中 → None（E4） | Loom/loom_raycast.py:280 |
| `register_tag` | `register_tag(self, tag)` | 注册新标签 (幂等); 已存在返回 False, 非法抛 ValueError. | VK 补齐同名同签名 | 幂等；已存在 → False；非法名 → E2 | Loom/engine.py:650 |
| `remove_camera` | `remove_camera(self, cam)` | 从场景移除摄像机 (先脱父, 同时清 active 指向). 相机物体化 2026-08-16. | VK 补齐同名同签名 | 不存在 → False（E4） | Loom/loom_camera.py:140 |
| `remove_light` | `remove_light(self, light)` | 从场景移除光源 (释放其阴影贴图) | VK 补齐同名同签名 | 不存在 → False；释放阴影贴图 | Loom/loom_lighting.py:64 |
| `remove_subtree` | `remove_subtree(self, root)` | 删除 root 及其全部子孙 (M14: 删除物体/撤销 redo 用). | VK 补齐同名同签名 | 不存在 → False（E4） | Loom/loom_model_gpu.py:328 |
| `resolve_collisions` | `resolve_collisions(self, m, max_iter=4, bounds=None)` | 把 m 推干净: 迭代推离所有相交物体. 返回是否发生过碰撞 (被挡). | VK 补齐同名同签名 | 返回是否发生过碰撞 | Loom/loom_physics.py:412 |
| `save_action_bindings` | `save_action_bindings(self, path=None)` | 导出/落盘当前动作绑定. | VK 补齐同名同签名 | 见 §2.5 | Loom/loom_input.py:561 |
| `script_occupied_keys` | `script_occupied_keys(self, exclude_action=None)` | 脚本声明占用的具体键名 -> {键名: [脚本显示名, ...]}。 | VK 补齐同名同签名 | 见 §2.5 | Loom/loom_input.py:284 |
| `send_message_to_name` | `send_message_to_name(self, model_name, method_name, *args, **kwargs)` | 2026-10-18 阶段1档序6 SendMessage: 按物体名字调用脚本方法。 | VK 补齐同名同签名 | 目标/方法不存在 → E5（不静默吞） | Loom/engine.py:701 |
| `set_camera_parent` | `set_camera_parent(self, cam, new_parent, preserve_world=True)` | 把摄像机挂到 new_parent (GameObject) 下 (None=根). 只可挂 GameObject, | VK 补齐同名同签名 | 见 §2.5 | Loom/loom_camera.py:218 |
| `set_object_layer` | `set_object_layer(self, obj, layer_id)` | 设置物体层; 越界抛 ValueError (校验在 GameObject.layer setter). | VK 补齐同名同签名 | 层越界 → E2 | Loom/engine.py:717 |
| `set_object_tag` | `set_object_tag(self, obj, tag)` | 设置物体标签; 未注册抛 TagNotRegisteredError (校验在 GameObject.tag set | VK 补齐同名同签名 | 未注册 → E3 | Loom/engine.py:721 |
| `set_parent` | `set_parent(self, child, new_parent, preserve_world=True)` | 把 child 挂到 new_parent 下 (None=根). 拒绝设置自身或设为子孙 (防环). | VK 补齐同名同签名 | 自环/设为子孙 → E2 | Loom/loom_transform.py:358 |
| `tag_exists` | `tag_exists(self, tag)` | 标签是否已注册 (不区分大小写). | VK 补齐同名同签名 | 不抛 | Loom/engine.py:635 |
| `toggle_logic_paused` | `toggle_logic_paused(self)` | 暂停/恢复逻辑时钟 (F9, MC 同款暂停世界 TPS): 渲染帧照跑 | VK 补齐同名同签名 | 返回暂停后状态 | Loom/engine.py:1581 |
| `validate_action_binding` | `validate_action_binding(self, name, keys)` | 键位冲突校验 -> (ok, reason). 冲突时 reason 可直接展示给玩家。 | VK 补齐同名同签名 | 返回 (ok, reason)，不抛 | Loom/loom_input.py:315 |
| `world_scale` | `world_scale(self, m)` | 物体世界缩放 (沿父链各局部缩放分量相乘, 忽略父旋转; 与引擎缩放处理一致) | VK 补齐同名同签名 | 见 §2.5 | Loom/loom_transform.py:334 |
| `world_to_local` | `world_to_local(self, m, p)` | 世界点 -> 该物体父空间的局部坐标 (行向量: local = world @ inv(parentWorldM) | VK 补齐同名同签名 | 父链断 → E2 | Loom/loom_transform.py:343 |

---

## 4 B 类：两端都有、只是形态不同（15 条）

### 4.1 GL 独有 8 条（VK 侧以别的形态存在）

| 方法 | 契约签名 | 语义 | 定义点 |
|---|---|---|---|
| `apply_orbit_camera` | `apply_orbit_camera(self)` | 轨道相机: 由 target/yaw/pitch/distance 反推眼睛位置, 复用 mat4_view_yaw | Loom/loom_camera.py:52 |
| `load_scene` | `load_scene(self, path)` | M37/M38: 运行时切换到另一个场景文件 (Unity SceneManager.LoadScene 式). | Loom/loom_model_gpu.py:355 |
| `move_camera` | `move_camera(self, delta_time)` | 根据按键状态移动相机 | Loom/loom_camera.py:67 |
| `rotate_camera` | `rotate_camera(self, delta_time)` | 根据按键状态旋转相机视角 | Loom/loom_camera.py:108 |
| `update_animations` | `update_animations(self, dt)` | 推进动画并应用变换 (位置/旋转/缩放). | Loom/loom_frame_components.py:81 |
| `update_audio` | `update_audio(self, dt)` | M34: 每帧按 AudioSource 组件 playing 状态 play/stop (播放状态变化才操作). | Loom/loom_frame_components.py:42 |
| `update_physics` | `update_physics(self, delta_time, events=True)` | M31: 每帧刚体步进 + 碰撞事件回调 (Unity Rigidbody 理念). | Loom/loom_physics.py:460 |
| `update_scripts` | `update_scripts(self, delta_time)` | — | Loom/engine.py:1079 |

### 4.2 VK 独有 7 条（GL 侧以别的形态存在）

| VK 方法 | VK 现状签名 | 语义 | 定义点 |
|---|---|---|---|
| `apply_dev_camera_mouse` | `apply_dev_camera_mouse(self)` | 开发者 (轨道) 相机鼠标: 滚轮推拉 + 右键拖动转视角. | Loom/scene_driver.py:1495 |
| `camera_pos` | `camera_pos` | 相机世界位置. | Loom/scene_driver.py:777 |
| `camera_target` | `camera_target(self, v)` | — | Loom/scene_driver.py:1615 |
| `camera_distance` | `camera_distance(self, v)` | — | Loom/scene_driver.py:1623 |
| `load_from_data` | `load_from_data(self, data, base_dir=None, ctx=None)` | — | Loom/scene_driver.py:613 |
| `render_pose` | `render_pose(self, aspect=None)` | 渲染帧: 插值平面状态 + VP 计算 (渲染层每帧调). | Loom/scene_driver.py:1037 |
| `step` | `step(self, dt, aspect=None)` | 兼容入口 (旧探针/测试直调): advance_logic(dt) + 返回 VP. | Loom/scene_driver.py:1061 |

### 4.3 形态统一方向 —— `主审暂定（可推翻）`

**裁决：以 GL 形态为契约形态。** 理由（按重要性）：

1. **编辑器只有 GL 一条腿**（`EditorApp(GLEngine)`）—— 脚本在编辑器里写、在编辑器里调，编辑器能跑的那套就是事实标准；
2. **beta7 零新功能** —— 把 GL 改成 VK 形态 = 改 GL 语义，属于「功能/语义变更」，越界；
3. **存量内容按 GL 写**（`examples/PacMan2D.json` 的玩法脚本、`Projects/`），改 GL 形态会一次性打碎所有存量；
4. **VK 侧改名成本低于 GL 侧**：VK 只有 39 个公开成员、消费者是播放器/打包器，共 7 条要改。

**逐条落法**：

| VK 现状 | 契约形态 | 0b 动作 |
|---|---|---|
| `step(dt)` | `advance_logic(dt)` + `render()` 两个入口 | 保留 `step` 作**兼容别名**（标 deprecated），新增两个契约入口 |
| `render_pose()` | `render()` | 同上（`render` 为契约名，`render_pose` 转内部） |
| `load_from_data(data)` | `load_scene(path)` | 新增 `load_scene`；`load_from_data` 降为内部/兼容 |
| `camera_pos` / `camera_target` / `camera_distance` | `camera_world_position()` + `active_camera` 的 `CameraState` 字段 | VK 补 `camera_world_position()`；三个轨道参数降为**非契约**（开发相机内部） |
| `apply_dev_camera_mouse()` | `apply_orbit_camera()` | 契约名用 GL 的；`apply_dev_camera_mouse` 转内部 |
| GL `move_camera` / `rotate_camera` | 同名 | VK 补两个「按按键状态驱动相机」的入口（语义照 GL：读 `actions`/键位状态） |
| GL `apply_orbit_camera` | 同名 | VK 已有等价物 → 改名即可 |
| GL `update_animations` / `update_audio` / `update_physics` / `update_scripts` | 同名 | **归 B7-26 一起做**（VK `_logic_frame` 段序补齐时把 4 段显式化，见路线登记 B7-26） |

> **注意**：`update_*` 这 4 条不单独在 0b 里做 —— 它们是 **B7-26（逻辑帧段序一致）的交付物**。
> 0b 只负责「把契约名写进接口」，实现由 B7-26 落地。这是有意的依赖，不是遗漏。

---

## 5 属性面（Q-B7-24-2 裁决：进契约）

| 属性 | 归属 | GL 现状 | VK 现状 | 契约要求 |
|---|---|---|---|---|
| `mouse_locked` | A（只读状态） | `False`（类属性，`loom_input.py:226`） | **无** | VK 加只读 `@property`，返回与 `set_mouse_locked` 写入值一致 |
| `mouse_lock_allowed` | A（只读状态） | `False`（`loom_input.py:227`） | **无** | 同上 |
| `mouse_unlock_requested` | A（只读状态） | `False` | **无** | 同上（VK 现只有 `poll_unlock()` 消费式接口，需另存一份只读视图） |
| `render_api_current` | 共享（只读） | `'opengl'`（`engine.py:919`） | `'vulkan'`（`scene_driver.py:831`） | 两端**值不同是正确行为**（如实反映本实例后端）；契约只要求「同名 + 返回字符串 + 与 `get_render_api()` 一致」 |
| `camera_pos` | B（VK 独有，降为非契约） | 无（GL 用 `camera_world_position()`） | `@property`（`scene_driver.py:777`） | 不进契约；契约名是 `camera_world_position()` |
| `script_keys` | **口径假差异**（两端语义相同） | `__init__` 实例属性（`engine.py:418`） | `@property` 别名 `key_state`（`scene_driver.py:1132`） | 不进契约差异清单；但**两端都必须有**（引擎前置检查依赖它），见 §10 |

> **为什么属性必须进契约**：脚本读状态只能靠属性（`if engine.mouse_locked:`）。
> 只对齐方法不对齐属性，结果是「API 都对齐了，读状态还是 `AttributeError`」—— 正是 Q-B7-24-2 裁决要堵的洞。

---

## 6 C 类：仅 GL 可用（20 条）· Q-B7-24-3 裁决 (a) 显式失败

**契约要求（硬）**：在 VK 实例上访问以下任一成员，必须抛

```python
class NotSupportedOnBackend(RuntimeError):
    """该 API 只在某个后端可用。刻意不提供静默替代 —— 静默替代会让脚本在切换后端时行为漂移。"""
```

异常文本模板：`'<api> 只在 opengl 后端可用；当前后端 vulkan。替代路径：<...>'`。

**为什么不用「返回 None」或「no-op」**：no-op 会让脚本以为调用成功（I6 违约），
而这正是 beta6 里「天空盒失败一端静默」（B7-22 差距 9）那一类缺陷的成因。

| 方法 | 签名 | 语义 | VK 侧应给的替代路径 | 定义点 |
|---|---|---|---|---|
| `blit_texture` | `blit_texture(self, tex)` | GL 立即模式 GUI 合成 | 走 FramePlan 的 `world_canvas` / `ui` pass | Loom/loom_hud.py:233 |
| `draw_lines` | 见签名 | 世界空间折线 | FramePlan `buckets` 的 line 绘制源 | Loom/engine.py:738 |
| `draw_screen_lines` | 见签名 | 屏幕折线描边 | `ui` pass | Loom/engine.py:809 |
| `draw_screen_polygon` | 见签名 | 屏幕三角扇填充 | `ui` pass | Loom/engine.py:850 |
| `draw_screen_rect` | 见签名 | 屏幕像素矩形 | `ui` pass | Loom/loom_hud.py:214 |
| `draw_text_quad` | 见签名 | 屏幕像素文字 | `ui` pass（文字图集） | Loom/loom_hud.py:108 |
| `draw_texture_quad` | 见签名 | 屏幕像素纹理 | `ui` pass | Loom/loom_hud.py:156 |
| `push_scissor` / `pop_scissor` | 见签名 | 立即模式裁剪栈 | `ui` pass 的 scissor 状态 | Loom/loom_hud.py:178/197 |
| `render` | 见签名 | GL 渲染一帧（含时钟 advance 与逻辑步） | `render_pose()` + `step()`（§4.3） | Loom/loom_render.py:1128 |
| `run` | 见签名 | GL 主运行循环 | 播放器/打包器的自有循环 | Loom/loom_render.py:1301 |
| `present_health` | 见签名 | 上屏健康快照 | VK 有自己的上屏状态，走诊断接口 | Loom/loom_render.py:1287 |
| `should_fallback_remote` | 见签名 | 连续上屏失败 → 建议离屏回读 | VK 侧另有回退链 | Loom/loom_render.py:1291 |
| `profile_snapshot` | 见签名 | 插桩快照 | 诊断走 `engine_metrics` EAI 命令 | Loom/loom_profiler.py:69 |
| `get_frame_jitter` | 见签名 | 帧长统计 | 同上 | Loom/loom_hud.py:329 |
| `on_key_event` / `on_text_input` / `on_quit_request` | 见签名 | GLFW 窗口回调入口 | VK 由播放器喂（`feed_mouse_rel` 等） | Loom/loom_glfw_window.py:427/430/433 |
| `step_logic_once` | 见签名 | 编辑器 F10 单步 | 编辑器专属（编辑器只有 GL） | Loom/engine.py:1602 |
| `sync_script_keys` | 见签名 | 嵌入式（Qt 宿主）刷脚本键 | 编辑器专属 | Loom/loom_input.py:262 |

### 6.1 反向的「仅 VK」（2 条，**不需要** GL 抛）

| VK 方法 | 语义 | 说明 | 定义点 |
|---|---|---|---|
| `consume_mouse_input` | `consume_mouse_input(self)` | 帧首结算鼠标增量: 累积值 -> mouse_rel (int 截断, 同 GL 的 int(dx)). | Loom/scene_driver.py:1487 |
| `feed_mouse_rel` | `feed_mouse_rel(self, dx, dy)` | 后端喂光标增量 (像素). 仅锁定状态累积 —— 与 loom_glfw_window._update_mouse_ | Loom/scene_driver.py:1478 |

> 这 2 条是**宿主喂输入**的管线：GL 侧对应的是 GLFW 回调（私有 `_update_mouse_rel`），**GL 没有公开对等 API**，
> 所以 GL 侧不存在「脚本误调」的可能 —— 不需要抛 E1。契约里只作「宿主接口」声明。

---

## 7 D 类：非契约（12 条，建议转私有）

**处置**：改名为 `_xxx`（一次性重命名 + 全仓调用点同步）。转私有后，脚本自然调不到，契约也不必承诺。
**为什么不当成「仅 GL」**：C 类是「这一端才有意义的能力」，D 类是「public 但本来就不该被外部看见的内部助手」——
两者混在一起会让「仅 GL」表变成垃圾场，脚本作者无法判断哪些是真能力。

| 现名 | 建议私有名 | 定义点 |
|---|---|---|
| `attach_model` | `_attach_model` | Loom/loom_model_gpu.py:80 |
| `collect_subtree` | `_collect_subtree` | Loom/loom_transform.py:400 |
| `compute_render_matrices` | `_compute_render_matrices` | Loom/loom_transform.py:224 |
| `compute_world_matrices` | `_compute_world_matrices` | Loom/loom_transform.py:124 |
| `find_model_by_guid` | `_find_model_by_guid` | Loom/loom_lighting.py:73 |
| `get_current_model` | `_get_current_model` | Loom/loom_transform.py:48 |
| `is_ancestor` | `_is_ancestor` | Loom/loom_transform.py:349 |
| `parent_world_matrix` | `_parent_world_matrix` | Loom/loom_transform.py:314 |
| `reset_sky_state` | `_reset_sky_state` | Loom/engine.py:1402 |
| `resolve_unlock_key_conflict` | `_resolve_unlock_key_conflict` | Loom/loom_input.py:539 |
| `select_next_model` | `_select_next_model` | Loom/loom_transform.py:42 |
| `world_rotation_matrix` | `_world_rotation_matrix` | Loom/loom_transform.py:327 |

---

## 8 门与落地纪律

**门**：`Loom/tests/test_engine_api_matrix.py`（v2 口径，已进 `run_all`）。差异基线冻结、**只许缩小**，四个方向都有牙。

**每落地一条契约条目的提交必须同时包含三件事**（缺一即视为未完成）：

1. 门里的基线**删掉这一行**（`EXPECTED_GL_ONLY` / `EXPECTED_VK_ONLY`）；
2. 本契约文档里该条的状态从 `待落地` 改成 `已落地（file:line + 测试名）`；
3. **一条对拍断言**（同一输入 → 两端同一可观察结果）。

**为什么必须同一次提交**：分开做就会出现「基线删了但实现没写」（门假绿）或「实现了但基线没删」（门红但没人知道为什么）。

---

## 9 0a / 0b 拆分与成本（Q-B7-24-4 裁决：拆）

| 段 | 内容 | 估 | 状态 |
|---|---|---|---|
| **0a** | 本契约正文 + 门升级 v2 + C/D 排除声明 + 属性面 | **3-4 人天** | 本次交付（文档 + 门已完成；剩「人类复核 + 修订」） |
| **0b** | A 40 + B 15 = **55 条**落地（VK 侧）+ 55 条对拍断言 | **估 8-12 人天** | 并入批 1 |
| 合计 | | **11-16 人天** | 原估 4-6 → **需按此重估**（路线登记 §7.2 总账同步调整） |

**0b 内部顺序（依赖决定，不是偏好）**：

1. **先属性面 3 条**（`mouse_locked` 等）—— 最小、无依赖、能立刻让「读状态」不再 AttributeError，是**可感知成果**；
2. **再 B 类 15 条形态统一** —— 多数是改名/薄适配，做完 A 类才有落脚点（例：A 类要在 VK 侧写 `render` 语义，得先有 `render` 入口）；
3. **最后 A 类 40 条** —— 按 §3 表顺序，其中 LayerTag 组（7 条）与查找组（5 条）可以并行给两个子代理（**一个组件一个子代理**）；
4. `update_animations` / `update_audio` / `update_physics` / `update_scripts` **不在这里做**，交给 B7-26。

---

## 10 留痕（跳过 / 未核 / 口径变化）

| 项 | 处置 | 理由 |
|---|---|---|
| **口径 v1 → v2** | 已写明：105/38 → 109/39；GL 独有 77 → 80（+3 鼠标属性） | Q-B7-24-2 裁决「属性面要进契约」。**两套数字不可混用**，历史文档按 v1 写的已在本文件与 audit 文件里标注 |
| **口径盲区：`__init__` 实例属性** | **未纳入**，留 v3 候选 | 已确认产生 1 条假差异：`script_keys`（GL `engine.py:418` 实例属性 / VK `scene_driver.py:1132` property 别名 `key_state`，**两端语义相同**）。纳入 v3 需扫 `__init__` 的 `self.x = ...`，会引入大量编辑器内部字段，需单独裁决「哪些算 API」 |
| **`script_keys` 判为假差异** | 不进契约差异清单，但**两端都必须有**（`update_scripts` 前置检查依赖它是 dict，缺了会静默退回，见 `scene_driver.py:1136`） | 这条是本次取证的意外收获：它差点被当成「VK 独有 API」而白写一遍 |
| **跳过：签名逐条比对** | 本契约以 GL 签名为契约签名（§4.3 裁决），**没有**逐条核对 VK 现有签名 | 0b 落地时逐条核；现在核等于提前做 0b |
| **跳过：语义一致性验证** | 留给 P1~P5 门与 B7-22 | 需真渲染对拍，不是静态能判 |
| **未核：A 40 条在 VK 侧「内部是否已有等价数据结构」** | **未逐项核** | §3「VK 落地动作」列按命名 + docstring + 调用分布推断，**不是逐条读实现**。0b 开工前必须逐项核一遍，否则会把「已有等价物」当「要新写」而虚高成本 |
| **未核：`camera_target` / `camera_distance` 的 property setter** | 只记了 getter | AST 里同名 def 会被 setter 覆盖，kind 判定不稳；不影响「存在性」结论，但**签名不完整** |

---

> **下一步**：人类复核本契约（尤其 §4.3 形态方向、§3 的 40 条边界）。复核通过后开 0b，
> 或先做批 1 的四个 P0 真缺陷（B7-18 / B7-21 / B7-17 / B7-26）—— 批 1 不依赖 0b，只依赖本契约的「契约名」。
