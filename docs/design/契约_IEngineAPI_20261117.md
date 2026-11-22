# 契约 · `IEngineAPI`（引擎公共接口）· 2026-11-17

> **这是什么**：beta7 批 0a 的产物 —— 一份两端（GL `GLEngine` / VK `SceneDriver`）都必须实现的**公共接口白盒契约**。
> 脚本、内容、工具链**只允许依赖本契约**；契约之外的成员（§6 仅 GL、§7 非契约）**不得**出现在脚本里。
>
> **状态**：**已裁决**（2026-11-22）。§4.3「B 类形态统一方向」由人类裁决为「旧形态名不再用，形态名全部统一」，> 执行方向 = 以 GL 形态名为契约名；落地与逐对考古结论见 §4.3。
> **依据裁决**：Q-B7-24-1 认可 A 边界 · Q-B7-24-2 属性面进契约（口径升 v2）· Q-B7-24-3 仅 GL 面**显式失败** · Q-B7-24-4 批 0 拆 0a/0b。
> **取证**：[../audit/impl_B7-24_API矩阵_20261117.md](../audit/impl_B7-24_API矩阵_20261117.md) · **门**：`Loom/tests/test_engine_api_matrix.py`
> **口径**：v2（含普通类属性）。v1（不含属性）数字为 GL 105 / VK 38，两套数字**不可混用**。

---

## 0 契约的边界（三句话）

1. **契约面 = A 40 + B 15 + 宿主事件入口 3 = 58 条**。两端都必须有、同名、同签名、同可观察语义。
   > **2026-11-17 修正（人类裁决：不受后端影响 / JVM 模型）**：`on_key_event` / `on_text_input` / `on_quit_request`
   > 原被我判为「仅 GL」（C 类），**这是误判** —— 它们是**宿主/用户的事件入口**，不该因后端不同而存在性不同。
   > 已移出 C 类、并入核心契约（见 §6.2），实现由 S1「事件面统一」承担。详见
   > [设计_单一引擎门面_后端下沉_20261117.md](设计_单一引擎门面_后端下沉_20261117.md)。
2. **仅 GL 面 = C 17 条**（原 20 条 − 3 条宿主事件入口）。VK 侧调用必须**显式抛** `NotSupportedOnBackend`（Q-B7-24-3 裁决 a）——**允许差异，不允许差异是隐形的**。
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
| **I4 身份稳定** | 同一对象的 `guid` 在两端、在存盘/读盘前后**不变**；`guid` 全局唯一。**guid 语义（Q-B7-49-1 P2，2026-11-21）**：① 新增对象/资产的 guid 由 `scene.identity.new_guid()`（uuid4）生成——**唯一实现，全仓生产代码只许 `scene/identity.py` 一处 uuid4**；② 迁移期 v1 物体缺 id 时**不用 uuid4**，用 `scene.identity.derived_guid()` 确定性派生——同一份 v1 输入无论迁移几次 / 在哪个后端 / 哪台机器，派生值逐值相等；③ 保存场景后 id 固化为永久身份，跨端与跨存盘不变（门：tests/test_scene_contract.py G 组） | 资产/场景/撤销都靠它；迁移期确定性派生修「同输入两次迁移 guid 不同」（修前红实测 uuid4 每次不同） |
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

### 4.2 VK 独有 6 条（GL 侧以别的形态存在，**已按 Q-B7-24-5 改名/删除**）

> Q-B7-24-5（2026-11-22 人类裁决「旧形态名不再用」）：原 7 条中 `step` 已**删除**，其余 4 条旧名已
> 改名（`render_pose` → `compute_frame_view_proj`、`load_from_data` → `build_scene_from_data`、
> `camera_pos` → `current_camera_position`、`apply_dev_camera_mouse` → `apply_editor_camera_mouse`）。
> 逐对同义性判据见 §4.3 的 T1 表。

| VK 方法（现行名） | VK 现状签名 | 语义 | 定义点 |
|---|---|---|---|
| `apply_editor_camera_mouse` | `apply_editor_camera_mouse(self)` | 编辑器(轨道)相机**鼠标输入**: 滚轮推拉 + 右键拖动转视角（GL 对应物 `editor._update_camera`）. | Loom/render/vk/driver.py |
| `current_camera_position` | `current_camera_position`（`@property`） | 无参取「当前相机世界位置」（轨道反推 / 脚本 `camera`）；GL 对应物是 `self.camera` 属性. | Loom/render/vk/driver.py |
| `camera_target` | `camera_target(self, v)` | 轨道相机目标点（GL 侧是属性而非方法）. | Loom/render/vk/driver.py |
| `camera_distance` | `camera_distance(self, v)` | 轨道相机距离（同上）. | Loom/render/vk/driver.py |
| `build_scene_from_data` | `build_scene_from_data(self, data, base_dir=None, ctx=None)` | 从**已解析 dict** 装配场景（GL 对应物 `sceneio.scene_from_dict`；用户 API 是 `load_scene(path)`）. | Loom/render/vk/driver.py |
| `compute_frame_view_proj` | `compute_frame_view_proj(self, aspect=None)` | 渲染帧的位姿/VP 计算（LOD 选模 + V@P，返回 `(vp, cam_pos)`）；**不是** GL 的整帧 `render`. | Loom/render/vk/driver.py |

### 4.3 形态统一 —— **已裁决**（人类 2026-11-22）

> **人类裁决（最高依据，2026-11-22）**：
> 「Q-B7-24-5：**旧形态名不再用，形态名全部统一**。」
>
> **执行方向**：以 **GL 形态名**为契约名。原「主审暂定（可推翻）」一节据此**转正**，
> 裁决依据原文保留在 §4.3.2 存档。
>
> **落地**：commit `a606363`（改名/删除 + 全仓调用点）· `e333133`（门，修前真红）。
> **门**：`Loom/tests/test_api_form_name_unification.py`（A 组同源/归属 · B 组旧名已消失 · C 组行为不变）
> 以及回归门 `test_user_api_parity` / `test_engine_api_matrix` / `test_editor_play_parity` /
> `test_camera_parity` / `test_pause_parity` / `test_eai_real`。

#### 4.3.1 逐对考古表（T1：先出表再动手）

| 旧名（VK） | 契约名（GL） | 是否同义（证据） | 处置 |
|---|---|---|---|
| `step(dt, aspect=None)` | `advance_logic(render_dt)` | **否**。`step` 是**复合体**：`advance_logic(dt)` + 位姿计算，返回 `(vp, cam_pos)`；`advance_logic` 只推进时钟，返回 `(steps, phys_steps)`，不含位姿。GL 侧**根本没有** `step` 同名物（矩阵门 GL-only 里也没有它）。 | **删除**（不留别名）：`advance_logic` 与位姿入口都已存在，生产代码零调用点（只有旧探针/文档提过）。 |
| `render_pose(aspect=None)` | `render(delta_time)` | **否**。GL 的 `render` 是**整帧**（推进时钟 + 阴影 pass + 绘制 + HUD + 交换缓冲，`render/gl/render.py:1262`）；`render_pose` 只算本帧位姿/VP 并做 LOD 选模，**不画不上屏**。VK 的整帧在 `render/vk/player.py` 的 `draw`（`advance_logic → 位姿/VP → VkRenderer.draw_frame → 上屏`）。 | 改名 `compute_frame_view_proj`，登记为**后端内部**；VK **不提供** `render`（A-3 断言：若将来提供，必须与 GL 同一函数对象）。 |
| `load_from_data(data, base_dir=None, ctx=None)` | `load_scene(path)` | **否**。一个吃**已解析 dict**（后端装配器，GL 对应物是 `sceneio.scene_from_dict`），一个吃**文件路径**（用户 API，两端同一函数对象 `core/engine_core.py:592`，内部经 `_load_scene_data` 调装配器）。 | 改名 `build_scene_from_data`，登记为**后端内部**；`load_scene` 早已两端同源，不动。 |
| `camera_pos`（`@property`） | `camera_world_position(cam)` | **否**。`camera_pos` 无参、返回「**当前**相机世界位置」（轨道参数反推 / 脚本写的 `self.camera`）；`camera_world_position(cam)` 吃一个**相机实体**。GL 侧「当前相机位置」是 `self.camera` **属性**，不是方法。 | 改名 `current_camera_position`，登记为**后端内部**；`camera_world_position` 早已两端同源（`loom_camera.py:211`），不动。 |
| `apply_dev_camera_mouse()` | `apply_orbit_camera()` | **否**。前者吃**鼠标增量**改轨道参数（输入 → 状态：滚轮推拉 + 右键转视角，公式同 GL `editor._update_camera`）；后者由轨道参数**合成相机位姿**（状态 → 位姿，`loom_camera.py:71`）。方向相反的两种操作。 | 改名 `apply_editor_camera_mouse`，登记为**后端内部**；`apply_orbit_camera` 早已两端同源，不动。 |

**没有一对是「同义 → 删旧名只留 GL 名」**：5 条旧名里 1 条是复合体（删）、4 条与 GL 名**不同义**
（改名 + 登记为后端内部）。真正的「同义」三条（`load_scene` / `camera_world_position` /
`apply_orbit_camera`）**在本次之前就已经是两端同一函数对象**，本项只做复核与加门。

#### 4.3.2 为什么「以 GL 形态为契约形态」（裁决依据，2026-11-17 原文存档）

1. **编辑器只有 GL 一条腿**（`EditorApp(GLEngine)`）—— 脚本在编辑器里写、在编辑器里调，编辑器能跑的那套就是事实标准；
2. **beta7 零新功能** —— 把 GL 改成 VK 形态 = 改 GL 语义，属于「功能/语义变更」，越界；
3. **存量内容按 GL 写**（`examples/PacMan2D.json` 的玩法脚本、`Projects/`），改 GL 形态会一次性打碎所有存量；
4. **VK 侧改名成本低于 GL 侧**：VK 消费者只有播放器/打包器。

#### 4.3.3 落地后的现状（2026-11-22 探针实测）

| 契约名 | GL | VK | 同一函数对象 | 说明 |
|---|---|---|---|---|
| `advance_logic` | ✅ `render/gl/engine.py:1422` | ✅ `render/vk/driver.py` | ❌ | **同语义·实现分属各后端**（GL 有异步逻辑线程 / Qt 宿主分支，VK 走 `FixedStepClock`）。名字已统一；是否并成一份属 JVM 模型第 2 步（后端差异进钩子）的待办，不在本项。 |
| `render` | ✅ `render/gl/render.py:1262` | ❌ | — | GL 独有后端内部（VK 整帧 = `render/vk/player.py` 的 `draw` 三段）。 |
| `load_scene` | ✅ `core/engine_core.py:592` | ✅ 同左 | ✅ | 用户 API。 |
| `camera_world_position` | ✅ `loom_camera.py:211` | ✅ 同左 | ✅ | 用户 API。 |
| `apply_orbit_camera` | ✅ `loom_camera.py:71` | ✅ 同左 | ✅ | 用户 API。 |
| `move_camera` / `rotate_camera` / `update_animations` / `update_physics` / `update_scripts` | ✅ | ✅ | ✅ | 已在 B7-26 等批次补齐（`update_audio` 两端同名、实现分属各端：GL 走 `FrameComponentMixin`，VK 走 `SceneDriver.update_audio`，同语义）。 |

**VK 侧仍公开、但已登记为后端内部（类型②）的四条**：`compute_frame_view_proj` /
`build_scene_from_data` / `current_camera_position` / `apply_editor_camera_mouse`。
它们**不该是用户 API** 的理由就是上表的「是否同义」列 —— 它们各自对应 GL 的另一件东西
（整帧 `render` / 装配器 `sceneio.scene_from_dict` / 属性 `self.camera` / `editor._update_camera`），
把它们当用户 API 会让脚本在切后端时语义漂移。

---

## 5 属性面（Q-B7-24-2 裁决：进契约）

| 属性 | 归属 | GL 现状 | VK 现状 | 契约要求 |
|---|---|---|---|---|
| `mouse_locked` | A（只读状态） | `False`（类属性，`loom_input.py:226`） | **无** | VK 加只读 `@property`，返回与 `set_mouse_locked` 写入值一致 |
| `mouse_lock_allowed` | A（只读状态） | `False`（`loom_input.py:227`） | **无** | 同上 |
| `mouse_unlock_requested` | A（只读状态） | `False` | **无** | 同上（VK 现只有 `poll_unlock()` 消费式接口，需另存一份只读视图） |
| `render_api_current` | 共享（只读） | `'opengl'`（`engine.py:919`） | `'vulkan'`（`scene_driver.py:831`） | 两端**值不同是正确行为**（如实反映本实例后端）；契约只要求「同名 + 返回字符串 + 与 `get_render_api()` 一致」 |
| `current_camera_position` | B（VK 独有，降为非契约；Q-B7-24-5 由 `camera_pos` 改名） | 无（GL 用 `self.camera` 属性 + `camera_world_position()`） | `@property`（`render/vk/driver.py`） | 不进契约；契约名是 `camera_world_position()`（吃相机实体，两端同一函数对象） |
| `script_keys` | **口径假差异**（两端语义相同） | `__init__` 实例属性（`engine.py:418`） | `@property` 别名 `key_state`（`scene_driver.py:1132`） | 不进契约差异清单；但**两端都必须有**（引擎前置检查依赖它），见 §10 |
| `mouse_rel` | A（只读状态，Q-B7-43-2 裁决 A） | 每帧由生产泵无条件结算（`loom_glfw_window._update_mouse_rel`，暂停期 (0,0)） | `feed_mouse_rel`（仅锁定态累积）→ `consume_mouse_input` 帧首结算（`render/vk/driver.py`）；喂入由 `vk_player.draw` 帧首**无条件**做 | **两端同语义（2026-11-22 人类裁决「选 A」）**：`mouse_rel` = **本帧鼠标物理位移增量**（int 像素元组），**不管**本帧鼠标事件是否被 UI 消费；「UI 消费帧不转视角」由相机消费点的 `ui_consumed` 早退承担，**不许**再靠「不喂 mouse_rel」实现 |
| `ui_consumed` | A（只读状态，Q-B7-43-2 裁决「补 ui_consumed」） | `runtime.PlayerApp._dispatch_ui_mouse` 每帧写 = 本帧 `dispatch_mouse` 返回值（`runtime.py:297`） | `render/vk/driver.py` 实例属性（初值 `False`）；**每帧写入点**在 `vk_player.draw` 帧首 `driver.ui_consumed = not ui_bridge.wants_camera()`（与 GL 同序：帧首、相机/脚本消费之前） | **两端同语义（bool）**：「本帧鼠标事件被 UI 消费」；脚本 `if engine.ui_consumed:` 两端都能跑。写入点每端各一处（GL `runtime.py` / VK `player.py`）。门 = `tests/test_mouse_rel_ui_consumed_parity.py`（A/B/C/D 四组，修前红证据见该文件头与提交信息） |

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
| `render` | 见签名 | GL 整帧入口（含时钟 advance 与逻辑步 + 绘制 + 上屏） | VK **无**同名物：整帧 = `render/vk/player.py` 的 `draw`（`advance_logic` → `compute_frame_view_proj` → `VkRenderer.draw_frame`）（§4.3） | Loom/render/gl/render.py:1262 |
| `run` | 见签名 | GL 主运行循环 | 播放器/打包器的自有循环 | Loom/loom_render.py:1301 |
| `present_health` | 见签名 | 上屏健康快照 | VK 有自己的上屏状态，走诊断接口 | Loom/loom_render.py:1287 |
| `should_fallback_remote` | 见签名 | 连续上屏失败 → 建议离屏回读 | VK 侧另有回退链 | Loom/loom_render.py:1291 |
| `profile_snapshot` | 见签名 | 插桩快照 | 诊断走 `engine_metrics` EAI 命令 | Loom/loom_profiler.py:69 |
| `get_frame_jitter` | 见签名 | 帧长统计 | 同上 | Loom/loom_hud.py:329 |
| ~~`on_key_event` / `on_text_input` / `on_quit_request`~~ | — | — | — | **已移出 C 类 → §6.2（宿主事件入口，属核心契约）** |
| `step_logic_once` | 见签名 | 编辑器 F10 单步 | 编辑器专属（编辑器只有 GL） | Loom/engine.py:1602 |
| `sync_script_keys` | 见签名 | 嵌入式（Qt 宿主）刷脚本键 | 编辑器专属 | Loom/loom_input.py:262 |

### 6.2 宿主事件入口（**不属于 C 类**，核心契约，3 条）

> 人类裁决（2026-11-17）：「用户不管用的是VK后端还是GL后端都用的是完全一样的事件API，底层的区别由引擎进行屏蔽。」
> 因此这三个**必须两端同名同签名同语义**。「谁把事件喂进来」是宿主的事（编辑器 GLFW/Qt、播放器、打包游戏），
> 不是用户 API 的差异。

| 入口 | 契约签名 | 语义 | 现状 | 落地步 |
|---|---|---|---|---|
| `on_key_event` | `on_key_event(self, ev) -> bool` | 键盘事件入口；`ev` = `{type: KEYDOWN/KEYUP, key, mod, unicode}`；返回 True = 已消费（不再进 `key_state`） | GL 有（GLFW 回调调用）；**VK 无** | **S1** |
| `on_text_input` | `on_text_input(self, ev) -> bool` | 文本输入入口（IME/字符提交）；返回 True = 已消费 | GL 有；**VK 无** | **S1** |
| `on_quit_request` | `on_quit_request(self) -> bool` | 关窗请求；返回 True = 允许退出（False = 拒绝/已处理） | GL 有；**VK 无** | **S1** |

> 同一批还要统一（S1）：鼠标增量入口（GL 内部 `_update_mouse_rel` / VK `feed_mouse_rel` + `consume_mouse_input`）、
> 鼠标锁定三件套（`set_mouse_locked` / `toggle_mouse_locked` / `set_ui_capture_mouse` 已在共享 28 条内）。

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

## 11 落地进度（滚动更新）

| 条目 | 状态 | 证据 |
|---|---|---|
| `update_audio`（音频段） | **已落地 2026-11-17** | B7-26：VK 补音频段，两端调同一份 `loom_frame_components.update_audio`；VK 公开方法 39 → **40**，API 矩阵门基线已同步（口径 v2.1）；门 `test_vk_logic_frame_parity.py` |
| 碰撞事件派发（`on_collision_*` / `on_trigger_*`） | **已落地 2026-11-17** | B7-26：新增 `loom_collision.dispatch`，GL/VK 同一函数；事件序列对拍两端逐条相等 |
| `update_animations` / `update_physics` / `update_scripts`（§4.3 B 类） | `update_scripts` **已落地 2026-11-18（S4）**；其余待 0b | S4：`update_scripts` 的公共薄封装进 `engine_core.EngineCore`，两端是同一个函数对象；后端实现走 `_update_scripts_impl`（VK 那份仍叫 `_update_scripts`，有既有调用方/段序追踪在用） |
| **S4（2026-11-18）：9 条用户 API 两端同一份实现** | **已落地** | `add_light` / `remove_light` / `clear_scene` / `remove_subtree` / `load_scene` / `get_tps` / `get_logic_time_ratio` / `step_logic_once` / `update_scripts` 全部搬进 `engine_core.EngineCore`；后端差异走 `_backend_*` 钩子 / `_xxx_impl`。VK 公开方法 98 → **107**，共同 88 → **97**，GL 独有 24 → **15**。门 `test_user_api_parity.py`（ALL PASS）+ API 矩阵门基线 v3.3（详见 §12） |
| A 类其余 36 条 + 属性面 3 条 + B 类其余 | 待 0b | — |

---

> **下一步**：人类复核本契约（尤其 §4.3 形态方向、§3 的 40 条边界）。复核通过后开 0b，
> 或先做批 1 的四个 P0 真缺陷（B7-18 / B7-21 / B7-17 / B7-26）—— 批 1 不依赖 0b，只依赖本契约的「契约名」。

---

## 12 S4 落地细节（2026-11-18）—— 用户 API 的两端同一份实现

判据（人类原话）：「两个后端暴露给用户的 API 都是一样的，选择哪个后端在用户端就是换个配置，
类似于 JVM 虚拟机：不管底层用的什么后端，往上暴露的接口都一样。」
→ 门 `tests/test_user_api_parity.py` 除了查「两端都有」，还查
`getattr(GLEngine, n) is getattr(SceneDriver, n)`（**同一个函数对象**，不是各写一遍）。

| 用户 API | 公共面（唯一实现，engine_core.EngineCore） | 后端层（各自一份） |
|---|---|---|
| `add_light` / `remove_light` | 建 LightState + append / 从 `lights` 摘掉 | 钩子 `_backend_light_added` / `_backend_light_removed`（GL 在 `loom_lighting` 释放阴影贴图；VK 无需定义） |
| `clear_scene` | 逐个 remove_model + 清 materials / 网格顶点缓存 + current_model_index 归零 | 钩子 `_backend_scene_cleared`（GL 释放桶资源；VK 清碰撞包围盒缓存） |
| `remove_subtree` | `collect_subtree` + 脱摄像机 + 逐节点 `_remove_one_model` | `_remove_one_model`（GL 在 `loom_model_gpu`，VK 在 `scene_driver`） |
| `load_scene(path)` | 读文件 → 判类型 → 交装配（返回 bool） | `_load_scene_data(data, base_dir)`（GL: `sceneio.scene_from_dict`；VK: `build_scene_from_data`） |
| `get_tps` | 读 `_tps_events` | `_tps_sample()` 由公共 `update_scripts` 每逻辑帧记一次（**VK 现在真的在记**，之前恒 0 = 假实现） |
| `get_logic_time_ratio` | 读 `_logic_dt_sum` / `_logic_wall_sum` | `_logic_ratio_tick()`：GL 在 `_clock_advance`（floor=True，恒 ≥1），VK 在 `advance_logic`（floor=False，如实记宿主 dt） |
| `step_logic_once` | 仅暂停态置 `_step_requested` | VK `advance_logic` 暂停分支**真的消费**它（`clk.step_once()` = 恰好 1 个逻辑帧） |
| `update_scripts` | 薄封装：记 TPS 样本 → 调 `_update_scripts_impl` | GL 在 `engine.py`；VK 的 impl 委托它已有的 `_update_scripts` |

实测（`tests/_tmp/probe_user_api.py`，60 渲染帧 + 真实墙钟）：
GL `get_tps()≈30.0` / `get_logic_time_ratio()≈1.016`；VK `get_tps()≈29.1` / `ratio≈0.97`；
两端 `step_logic_once()` 在暂停态都**恰好前进 1 个逻辑帧**（未请求的暂停帧前进 0 帧）。

**已知残留差异（登记，不在 S4 范围）**：
1. `clear_scene` / `load_scene` 在 VK 侧**不派发**脚本 `on_destroy`（VK 的 `remove_model` 是浅删），
   GL 会派发。抹平必须改 VK 既有公共成员 `remove_model`（`test_lod_fastpath` 等锁着），需单独裁决。
2. GL 的 `_load_scene_data` **不吃** `base_dir`（原 `load_scene` 就没传，GL 的相对资源走资产上下文），
   VK 吃。补传会改变 GL 的资产解析结果 = 改可观察行为，故保持原样。
