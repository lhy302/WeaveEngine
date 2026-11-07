# 场景序列化与实体（sceneio / loom_scene_entities / loom_cubemap / matlib）扫描报告

> 审计协议：docs/audit/SCAN_PROTOCOL.md（2026-11-07，只读审计）
> 方法论依据：桌面《论如何正确的 vibe coding》《论如何使用 AI 自动化工具正确的判断 AI 给出的黑盒是否符合设计标准》
> 审计对象工作区：D:\my-project - 副本\Loom(py源代码-工作区)\Loom

## 0. 范围与方法（文件清单 + 行数 + 跑过什么命令）

### 0.1 文件清单（HEAD = 4f4665011e7891d221934ac0300ef42544eab90d）

| 文件 | 行数 | HEAD blob sha1 |
|---|---|---|
| Loom/sceneio.py | 1171 | cca98dbd628b1da40ae0ab166ccbf86b0f65619f |
| Loom/loom_scene_entities.py | 207 | ae4b61d9ed353c187d62af322dc89ceee9c9586e |
| Loom/loom_cubemap.py | 169 | f01d383373ef0844543623d397cb2d5a2d45ce6c |
| Loom/matlib.py | 292 | 4b9a464ffb2d87b601d9bebff2ede4aaee4eab23 |

### 0.2 [REGRESSION] 专项：git diff 结果

```
cd "D:\my-project - 副本\Loom(py源代码-工作区)"
git diff HEAD --stat -- Loom/sceneio.py Loom/loom_scene_entities.py Loom/loom_cubemap.py Loom/matlib.py
# 输出：（空）
git status --porcelain -- Loom/sceneio.py Loom/loom_scene_entities.py Loom/loom_cubemap.py Loom/matlib.py
# 输出：（空）
```

结论：**本模块 4 个文件相对 HEAD 零改动**，不存在"Vulkan 对齐"未提交 diff 引入的回归。当前 100 个文件的未提交改动全部落在其它模块（见 0.4 的跨模块观察）。

### 0.3 实际跑过的命令（全部在临时目录，未改仓库文件）

探针目录：%TEMP%\loom_audit_02（即 C:\Users\Administrator\AppData\Local\Temp\loom_audit_02），每个探针自包含，正文第 2 节给出可复制复现片段。

```powershell
$env:LOOM_NO_SAVE_MIGRATE='1'; $env:LOOM_QUIET='1'; $env:PYTHONIOENCODING='utf-8'
python "$env:TEMP\loom_audit_02\p1_matlib.py"      # matlib 数值/往返/退化
python "$env:TEMP\loom_audit_02\p2_gimbal.py"      # decompose_euler 万向锁 + set_parent
python "$env:TEMP\loom_audit_02\p3_sceneio.py"     # 加载容错/材质增长/env/环引用
python "$env:TEMP\loom_audit_02\p4_ent_cube.py"    # 实体角度 + cubemap（含 standalone GL）
python "$env:TEMP\loom_audit_02\p5_ui_prefab.py"   # UI/prefab
python "$env:TEMP\loom_audit_02\p6_misc.py"        # 迁移/blob/原子写/组件往返
python "$env:TEMP\loom_audit_02\p7_bool.py"        # bool 字段字符串语义
python "$env:TEMP\loom_audit_02\p8_allui.py"       # 全 UI 类型往返
python "$env:TEMP\loom_audit_02\evidence.py"       # 汇总证据（报告正文引用其输出）
```

环境：Python 3.12.10 / numpy 2.2.5 / pygame 2.6.1 / moderngl 5.12.0。

定向回归测试（未跑全量 tests/run_all.py）：

```powershell
cd "D:\my-project - 副本\Loom(py源代码-工作区)\Loom"
python tests/test_sceneio.py       # 总结果: ALL PASS
python tests/test_camera_parent.py # 总结果: ALL PASS
python tests/test_decompose.py     # 2000 随机角 往返最大误差: 6.86313324422573e-13；超差次数: 0 => PASS
python tests/test_cubemap.py       # ALL PASS
```

只读自证：审计前 git status --porcelain 计数 1085；审计后 1086，唯一差异是新增本报告文件 `docs/audit/scan_02_scene.md`（未跟踪）；四个受审计文件 `git status --porcelain -- <files>` 恒为空——未改动任何受跟踪源码/测试/文档。

### 0.4 跨模块观察（不在本模块文件内，仅登记）

未提交改动中 scene_driver.py / vk_renderer.py 为 Vulkan 侧复制了本模块的加载语义（_apply_skybox、_apply_ui、build_materials/build_models/build_lights/build_cameras）。这不属于本报告文件清单，见 P-23（P-UNKNOWN）。

---

## 1. 粗筛清单（含跳过项留痕）

六类标签：契约/不变量/错误模型/资源边界/并发/边界输入（协议 §1）。P-02 / P-09 / P-24 为阶段二回填项（回填原因：阶段一未把"类型混淆"与"字段映射"拆到足够细）。

| ID | 位置 | 标签 | 初步方向（一句话） | 粗筛证据 |
|---|---|---|---|---|
| P-01 | sceneio.py:228-235, 287-296, 278-284, 349-364, 436-446, 903, 914-918, 679-687 | BND-EMPTY / SEM-MISMATCH | 加载容错只覆盖 _f3/_f1 白名单字段，其余字段裸 float()/int()，坏值直接抛异常 | _f3 有 try（L70-75），但 m.collider.friction = float(col.get('friction', 0.5))（L292）裸转 |
| P-02 | sceneio.py:171-179, 291, 296, 442 | SEM-SILENT | visible/enabled/is_trigger/fov_locked 走 bool()/原样透传，"false" 字符串变真值 | visible=obj.get('visible', True)（L177）无类型校验；bool(col.get('enabled', True))（L291） |
| P-03 | sceneio.py:879-889 + loom_model_gpu.py:54, 74-78 | BND-RESOURCE / SEM-MISMATCH | 每次加载 add_model 自建默认材质先入材质库、随后被 material_id 覆盖但从不移除 → 库与存档逐轮膨胀 | L881-885 收录全部 engine.materials；L180-187 只换引用不清理旧材质 |
| P-04 | sceneio.py:486-489 vs 529-537 | SEM-SILENT / AUDIT-ASYMMETRY | 纯色 env_map 只 emit paths: null，apply 只认 paths，保存即丢 | _emit_skybox 有 solid_color 分支（L386-389），_emit_material 没有 |
| P-05 | sceneio.py:300-307, 873-875；loom_transform.py:328-335, 343-349 | INVARIANT / BND | 父链成环：序列化静默丢对象，world_scale/is_ancestor 死循环 | 格式注释写"DFS 前序: 父一定在子之前"（L22），_link_by_map 不校验顺序/环 |
| P-06 | sceneio.py:1130-1137, 180-187 | SEM-MISMATCH | prefab 不携带材质库，跨场景实例化只恢复 color/saturation，PBR/贴图丢失 | prefab_to_dict 只写 version/prefab/objects（L1135-1137） |
| P-07 | sceneio.py:840-845 | SEM-SILENT | _apply_ui 对多 root 元素最后一个覆盖前面，静默丢弃 | for ed in ...: canvas.root = root_el |
| P-08 | sceneio.py:914-918 | IFACE-PRECOND | 怀疑 scene_from_dict 不清空 models → 重复对象 | 同函数内 _apply_lights/_apply_cameras/_apply_materials 都 clear（L910-913） |
| P-09 | sceneio.py:673-809 | SEM-MISMATCH | 怀疑 UI 字段映射（15 类）有错名/漏字段 | 分支多、字段多，属人工易错区 |
| P-10 | sceneio.py:393-407 | SEM-SILENT | skybox 路径失效静默 None，无任何告警 | except Exception: pass（L405-406） |
| P-11 | sceneio.py:372-390 | SEM-SILENT | 内存态 cubemap 无法序列化 → skybox 静默消失 | return None（L390） |
| P-12 | sceneio.py:512-537 | SEM-SILENT | 材质贴图/环境贴图文件缺失静默跳过 | except Exception: pass（L526-527, 536-537） |
| P-13 | sceneio.py:975-989 | IFACE-UNIT | 怀疑 v8→v9 弧度→度迁移误伤顶层轨道 camera dict | L977-978 注释声称不碰，需实测 |
| P-14 | matlib.py:88-95 | BND-OFFBYONE | decompose_euler 万向锁分支 atan2 符号随 β 正负而变，怀疑 -90° 分支错 | alpha = atan2(r[1,0], r[1,1]) 不区分 β=±90 |
| P-15 | matlib.py:113-134, 212-237 | BND-EMPTY | mat4_look_at / mat4_view_forward 归一化无零向量保护 | fx / fl（L117）、fx / fl（L218） |
| P-16 | matlib.py:99-110, 199-209 | SEM-MISMATCH | 怀疑 depth 映射 [near->0, far->1] 与注释不符 | 注释 L102-103、L201 |
| P-17 | matlib.py:175-196 | SEM-MISMATCH | 怀疑 view_basis_to_angles 与 mat4_view_yaw_pitch 的 roll 负绕向不互逆 | 两处 sn = -sin（L134 vs L157） |
| P-18 | loom_cubemap.py:86-113 | BND-OVERFLOW | _to_255 不钳制，越界通道塞进 uint8 数组 | return int(round(v))（L90）；arr[:,:,0] = int(rgba[0])（L112） |
| P-19 | loom_cubemap.py:121-131 | BND-EMPTY | ensure_gl 只写 faces[:6]，不足 6 面时未写面上传未定义内容 | L130-131 |
| P-20 | loom_scene_entities.py:23-29, 51-52, 146-148 | AUDIT-DOCIMPL | wrap_deg(180,-180,180) -> -180，与注释"(-180,180]"写法相反 | if lo <= v < hi: return v |
| P-21 | loom_scene_entities.py:94-116 | INVARIANT | 怀疑方向缓存键漏 roll / 直接写 angle 不失效 | 缓存键 (azimuth, elevation, roll) |
| P-22 | loom_scene_entities.py:32-41, 69-73 | SEM-DEFAULT | 零方向向量被当成 (az,el)=(0,0)，变 +z，而非回退默认 (0,-1,0) | if (z or x) else 0.0（L40） |
| P-23 | scene_driver.py:342-390, vk_renderer.py:957-980 | IFACE-ERROR | VK 侧平行实现与 sceneio 语义漂移（跨模块，非本文件） | 见 0.4 |
| P-24 | loom_cubemap.py:121-148 | BND-RESOURCE | 怀疑 ctx 切换时旧 GL 纹理未显式 release | _gl_ctx_id 判据存在（L123）但无 release 分支 |

### 跳过项留痕（严格遵守四类可审计理由）

| 编号 | 跳过对象 | 理由类别 | 具体事实 |
|---|---|---|---|
| SKIP-01 | sceneio.encode_blob/decode_blob（L1018-1036） | 白盒契约明确声明 | docstring 声明"非绝对保密"、decode_blob 非法返回 None（L1028）；实测 encode→decode 往返相等、非法输入返回 None（p6 输出 PASS×3） |
| SKIP-02 | save_json_atomic（L1001-1011） | 已有回归测试覆盖 | tests/test_sceneio.py:110-115 断言原子写成功且无 .tmp 残留；本次 p6 对 save_scene_data 明文/混淆各测一次均 PASS |
| SKIP-03 | prefab_to_dict/load_prefab/save_prefab（L1130-1149） | 已有回归测试覆盖 | tests/test_sceneio.py:283-307 覆盖 3+3 实例、GUID 唯一、父链完整、根 offset |
| SKIP-04 | _emit_object 组件 emit 分支（audio/animator/rigidbody/collider/scripts，L106-140） | 已有测试证据（本次定向探针） | p6[4] 组件 round-trip 字段一致（collider/rigidbody/audio/animator/scripts 全等），PASS |
| SKIP-05 | _emit_ui_element/_apply_ui_element 全 15 类字段映射（L542-809） | 已有测试证据（本次定向探针） | p8 全类型往返 ui round-trip equal: True；唯一差异是 grid 子元素 reflow 后补齐 rect（预期行为） |
| SKIP-06 | loom_cubemap.from_files（L41-74） | 已有回归测试覆盖 | tests/test_cubemap.py 输出 PASS from_files 加载 4、PASS from_files 面数不足报错 |
| SKIP-07 | mat_validate（L240-292）本体的正确性 | 语言规范保证 + 已实测 | 只做 numpy 矩阵乘法与 max(abs)，无分支；实测 max_err=1.78e-15 |

---

## 2. 逐项裁决

> 编号说明：P-01~P-07 为 sceneio 证真，P-08~P-13 为 sceneio 证伪；P-14~P-17 为 matlib；P-18~P-19 为 cubemap 证真、P-24 为 cubemap 证伪；P-20~P-22 为实体；P-23 为跨模块 UNKNOWN。

### 2.1 P-PROVED（11 项）

---

#### P-01 · P-PROVED · P1 · 加载容错的数值字段覆盖面不足：坏值直接抛异常，整个场景加载中断

1) **位置**：sceneio.py:228-235（rigidbody）、287-296（collider）、278-284（animator）、349-364（光源角度）、436-446（相机 pitch_min/max）、903（gravity）、914-918（objects 容器/元素类型）、679-687 与 693-773（UI 的 int()/float()）。

2) **契约/预期**：模块文档 L38-42 声明"加载容错: 未知基元类型 -> 立方体兜底; 缺字段 -> 默认值"；_f3 注释 L68-69 与 _f1 注释 L79 明写"坏场景文件不崩"。因此任一字段类型错误都应回退默认值并继续加载。

3) **路径枚举**（_apply_object 的字段处理分三类）：
   - 路径 A：走 _f3（position/rotation/scale，L172-179）→ 有 try，返回默认。
   - 路径 B：走 _f1（光源数值、相机 yaw/pitch/fov、轨道相机字段）→ 有 try，返回默认。
   - 路径 C：裸 float()/int() 或直接透传 → 无 try：collider 三件套（L292-294）、rigidbody 六字段（L230-235，转换发生在 GameObject.add_rigidbody）、animator frames（L281 dict(f)）、gravity（L903）、光源 azimuth/elevation/roll（L361-364，转换发生在 LightState.__init__ L65-68）、相机 pitch_min/pitch_max（L445-446，转换发生在 CameraState.__init__ L166-167）、objects 为 null / 元素非 dict（L914-918）、UI z_order/font_size 等（L686, L695, L712-714）。
   - 路径 C 的 9 个子情形全部实测抛异常（见 7）。

4) **实际行为**：路径 C 的任一坏字段使 scene_from_dict 抛出 ValueError/TypeError/AttributeError。此时函数已执行到中途（engine.gravity 已改、engine._skybox 已改、ui/lights/cameras/materials 已 clear 并部分重建、objects 已建了若干），调用方拿到异常时引擎处于**半加载状态**。

5) **差异**：预期"回退默认值并继续"，实际"抛异常并留下半加载状态"。

6) **触发条件**：场景/Prefab JSON 中对应字段类型与预期不符（手工编辑、外部工具生成、版本错配）。正常自产文件不会触发。

7) **验证**：
```powershell
$env:LOOM_NO_SAVE_MIGRATE='1'; $env:PYTHONIOENCODING='utf-8'
python -c @"
import sys
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
import engine as E; import sceneio as S
E.GLEngine._build_gpu = lambda self, m: None
cases = {
 'objects: null': {'version':10,'objects':None},
 'objects: [str]': {'version':10,'objects':['x']},
 'collider.friction': {'version':10,'objects':[{'id':'o','type':'cube','collider':{'friction':'oops'}}]},
 'rigidbody.mass': {'version':10,'objects':[{'id':'o','type':'cube','rigidbody':{'mass':'abc'}}]},
 'animator.clips': {'version':10,'objects':[{'id':'o','type':'cube','animator':{'clips':{'walk':'abc'}}}]},
 'gravity': {'version':10,'objects':[],'gravity':'abc'},
 'light.azimuth': {'version':10,'objects':[],'lights':[{'azimuth':'abc'}]},
 'camera.pitch_min': {'version':10,'objects':[],'cameras':[{'pitch_min':'abc'}]},
 'ui.font_size': {'version':10,'objects':[],'ui':{'canvases':[{'elements':[{'type':'text','font_size':'big'}]}]}},
}
for tag, d in cases.items():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models=[];e.materials=[];e.lights=[];e.cameras=[];e.active_camera=None;e.current_model_index=0;e.gravity=-9.8
    try:
        S.scene_from_dict(e, d); print('OK    ', tag)
    except Exception as ex:
        print('RAISE ', tag, type(ex).__name__+':', str(ex)[:60])
"@
```
   实测输出（evidence.py [EVID-2]）：
```
  RAISE objects: null                TypeError: 'NoneType' object is not iterable
  RAISE objects: [str]               AttributeError: 'str' object has no attribute 'get'
  RAISE collider.friction='oops'     ValueError: could not convert string to float: 'oops'
  RAISE rigidbody.mass='abc'         ValueError: could not convert string to float: 'abc'
  RAISE animator.clips walk='abc'    ValueError: dictionary update sequence element #0 has length 1; 2 is required
  RAISE gravity='abc'                ValueError: could not convert string to float: 'abc'
  RAISE light.azimuth='abc'          ValueError: could not convert string to float: 'abc'
  RAISE camera.pitch_min='abc'       ValueError: could not convert string to float: 'abc'
  RAISE ui text.font_size='big'      ValueError: invalid literal for int() with base 10: 'big'
```
   编辑器真实路径：editor.py:986-991 的 try 只包住 open + json.load，sceneio.scene_from_dict(...)（L997）在 try 外，异常会直接冒到加载回调。

8) **影响与等级**：**P1**。坏文件（甚至只是 "objects": null）会让场景加载半途而废并留下部分被清空/重建的引擎状态；与模块自述的"坏场景文件不崩"契约直接冲突。

---

#### P-02 · P-PROVED · P2 · bool 字段把字符串当真值："false" 变 True，且 visible 以字符串原样进存档

1) **位置**：sceneio.py:177（visible=obj.get('visible', True)）、291（bool(col.get('enabled', True))）、296（bool(col.get('is_trigger', False))）、442（fov_locked=d.get('fov_locked', True)）。

2) **契约/预期**：格式注释 L30 "visible": bool；fov_locked 文档 L19 "视角广度玩家是否可调"（布尔语义）。加载应把 JSON 布尔解释为布尔。

3) **路径枚举**：JSON 合法布尔 → 正常；JSON 字符串 → 路径 C 无校验：
   - visible：直接被 GameObject 保存，_emit_object 原样写回（L105），渲染层用真值判断 → "false" 视为可见。
   - enabled/is_trigger：bool("false") == True（Python 语言规范）→ 反向语义。
   - fov_locked：CameraState.__init__ 再 bool(...)（loom_scene_entities.py:161）→ 同样 True。
   - 全路径无异常、无告警。

4) **实际行为**：字符串字段被当作真值接受或原样保留。

5) **差异**：预期"布尔或回退默认"，实际"字符串 → True / 字符串原样进存档"。

6) **触发条件**：场景文件中布尔字段写成字符串（手写 JSON、JS 生成的 JSON、旧工具导出）。

7) **验证**：
```powershell
python -c @"
import sys
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
import engine as E, sceneio as S
E.GLEngine._build_gpu = lambda self, m: None
e = E.GLEngine.__new__(E.GLEngine)
e.models=[];e.materials=[];e.lights=[];e.cameras=[];e.active_camera=None;e.current_model_index=0
S.scene_from_dict(e, {'version':10,'objects':[{'id':'o','type':'cube','visible':'false','collider':{'enabled':'false'}}]})
m = e.models[0]
print('visible =', repr(m.visible), ' collider.enabled =', repr(m.collider.enabled))
print('re-emit visible =', repr(S.scene_to_dict(e)['objects'][0]['visible']))
"@
```
   实测输出：
```
visible = 'false'  collider.enabled = True
re-emit visible = 'false'
```

8) **影响与等级**：**P2**。不崩溃但语义反转：本应隐藏的物体可见、本应关闭的碰撞体开启；字符串还会原样回写，污染后续存档。

---

#### P-03 · P-PROVED · P1 · 材质库在 load→save 循环中每轮 +1 个孤儿默认材质，存档无限膨胀

1) **位置**：sceneio.py:171（add_model）、180-187（material_id 替换）、879-889（scene_to_dict 收录全部 engine.materials）；关联 loom_model_gpu.py:54（_register_model_material(model)）、74-78（默认材质入材质库）、292-296（仅删除"当前被删物体引用"的材质）。

2) **契约/预期**：场景序列化应幂等：load(save(x)) 再 save 得到等价数据；材质库只含真实资产与引用。

3) **路径枚举**：
   - 路径 1：对象无 material_id（v4 旧文件）→ 只保留自建材质，无孤儿 → 不增长。
   - 路径 2：对象有 material_id 且库中已存在 → add_model 先创建并登记默认材质 M0（L54 调 _register_model_material），随后 L187 m.renderer.material = mat 换引用，**M0 留在 engine.materials**；remove_model 只处理"模型当前引用的材质"（loom_model_gpu.py:293-296），M0 永远轮不到 → 每加载一个此类对象 +1。
   - 路径 3（本路径叠加）：scene_to_dict L879 用 list(engine.materials) 全量收录，孤儿被写进存档 → 下次加载把孤儿当真实资产再建一遍，再叠加新的孤儿。
   - 无任何清理分支（全库只有 editor.py:1030、loom_model_gpu.py:296/321、sceneio.py:497、undo.py:438 五处 materials.clear/remove，均不覆盖"加载后被替换的默认材质"）。

4) **实际行为**：每轮 save/load，材质数 +1（每个带 material_id 的对象各 +1）。

5) **差异**：预期固定点，实际线性增长。

6) **触发条件**：任何"打开含 material_id 的场景 → 保存"的常规操作（编辑器保存、EAI 保存命令、运行时 load_scene 后再存）。

7) **验证**：
```powershell
python -c @"
import sys, json
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
import engine as E; from mesh import create_cube; import sceneio as S
E.GLEngine._build_gpu = lambda self, m: None
def new():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models=[];e.materials=[];e.lights=[];e.cameras=[];e.active_camera=None;e.current_model_index=0;e.gravity=-9.8
    return e
e = new(); m = e.add_model(create_cube(1.0), E.Point3D(0,0,0), E.Point3D(0,0,0), name='A')
m.renderer.material = e.add_material(color='#FF8800', name='shared')
cur = S.scene_to_dict(e)
print('cycle0', len(cur['materials']), [x['name'] for x in cur['materials']])
for i in range(1, 4):
    ne = new(); S.scene_from_dict(ne, json.loads(json.dumps(cur))); cur = S.scene_to_dict(ne)
    print('cycle%d' % i, len(cur['materials']), [x['name'] for x in cur['materials']])
"@
```
   实测输出（evidence.py [EVID-3]）：
```
  cycle0 file_materials=2 names=['材质', 'shared']
  cycle1 file_materials=3 names=['材质', 'shared', '材质']
  cycle2 file_materials=4 names=['材质', 'shared', '材质', '材质']
  cycle3 file_materials=5 names=['材质', 'shared', '材质', '材质', '材质']
```

8) **影响与等级**：**P1**（数据正确性/资源）。存档随打开-保存次数线性膨胀，材质库被同名默认材质污染，资产浏览器出现大量不可引用垃圾条目；长期使用后加载变慢。若团队认为"库只增不减"是可接受的产品语义，可降 P2，但"每次加载都新增"不可能是设计意图（已有 remove_model 的孤儿清理逻辑说明作者本意是"不留孤儿"）。

---

#### P-04 · P-PROVED · P1 · 纯色环境贴图（Cubemap.from_solid）序列化后丢失

1) **位置**：sceneio.py:486-489（_emit_material 的 env_map 段）、493-537（_apply_materials，只在 eref.get('paths') 时重建）。

2) **契约/预期**：材质资产应可往返；模块对 skybox 已有"纯色来源"专门处理（_emit_skybox L386-389 solid_color），说明"纯色 cubemap 必须能被序列化"是模块内已承认的契约。

3) **路径枚举**：
   - 路径 1：env_map 由 Cubemap.from_files 创建 → paths 非空 → emit 写 paths → apply 重建 → OK。
   - 路径 2：env_map 由 Cubemap.from_solid 创建（_solid_color 非空、paths=None）→ emit 写 "paths": null → apply 条件 if eref and eref.get('paths') 为假 → **整个 env_map 丢弃**，无告警。
   - 路径 3：内存态 cubemap（faces 直给）→ 同样丢弃（与 skybox 的 return None 同构，但材质侧连"可识别来源"都没有）。
   - 生产者可达性：agent_commands.py:1244 cube = Cubemap.from_solid(color, size=16, name='环境贴图') → L1247 mat.env_map = cube（EAI/MCP 的 set_env 纯色命令）；tests/test_cubemap.py:114 同样用法。

4) **实际行为**：保存写出 {"guid":..., "name":..., "paths": null}；重新加载后 mat.env_map is None。

5) **差异**：预期 env_map 保留（或至少 emit 侧像 skybox 一样写 solid_color），实际丢失。

6) **触发条件**：用 EAI/MCP set_env 设纯色环境贴图 → 保存场景 → 重新打开。

7) **验证**：
```powershell
python -c @"
import sys, json
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
import engine as E; from mesh import create_cube; import sceneio as S
from loom_cubemap import Cubemap
E.GLEngine._build_gpu = lambda self, m: None
def new():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models=[];e.materials=[];e.lights=[];e.cameras=[];e.active_camera=None;e.current_model_index=0
    return e
e = new(); m = e.add_model(create_cube(1.0), E.Point3D(0,0,0), E.Point3D(0,0,0))
m.renderer.material.env_map = Cubemap.from_solid((200,100,50), size=4, name='solid_env')
d = S.scene_to_dict(e)
print('emitted:', json.dumps([x.get('env_map') for x in d['materials']], ensure_ascii=False))
ne = new(); S.scene_from_dict(ne, json.loads(json.dumps(d)))
print('reload env_map:', [getattr(x, 'env_map', None) for x in ne.materials])
"@
```
   实测输出：
```
emitted: [{"guid": "aedfd132ddb24e8685c52914ad6ea706", "name": "solid_env", "paths": null}]
reload env_map: [None, None]
```

8) **影响与等级**：**P1**（保存即丢用户数据，影响面限于纯色 env 路径）。修复只需让 _emit_material 走与 _emit_skybox 相同的 solid_color 分支、_apply_materials 支持 solid_color。

---

#### P-05 · P-PROVED · P1 · 父链成环：重新序列化静默丢对象，world_scale 死循环

1) **位置**：sceneio.py:300-307（_link_by_map 建链）、873-875（scene_to_dict 只从根 DFS）；消费侧 loom_transform.py:328-335（world_scale while 循环）、343-349（is_ancestor while 循环）。

2) **契约/预期**：格式注释 L22 "objects: DFS 前序: 父一定在子之前"；_link_by_map 应据此拒绝"父出现在子之后"的引用，从而在结构上排除环；scene_to_dict 注释 L873 "只从根开始, DFS 前序" 要求每个对象都可达。

3) **路径枚举**：
   - 路径 1：合法前序树 → 正常。
   - 路径 2：parent_id 指向更靠后的对象（违反 L22 注释）→ _link_by_map L304 只看 pid in id_map，不检查顺序 → 照连。
   - 路径 3：两个对象互指（a→b、b→a）→ 两条边都被连上，形成环，无检测。
   - 路径 4（后果 A）：scene_to_dict 遍历 for m in engine.models: if m.parent is None → 环上对象没有根 → 不 emit → 保存后这两个对象从存档消失。
   - 路径 5（后果 B）：world_scale 的 while cur is not None 在环上永不终止；is_ancestor 同构。world_rotation_matrix/model_world_matrix 是递归实现（L321-326、L53-60），环上表现为 RecursionError 而非死循环。
   - 无任何环检测/告警分支。

4) **实际行为**：加载成功（指针互指）、保存丢对象、几何查询挂死。

5) **差异**：预期"按格式注释建链并保证可序列化"，实际"建出环 → 丢数据 + 挂死"。

6) **触发条件**：场景/Prefab JSON 中手工构造或第三方生成的环状 parent_id。正常编辑器路径有 set_parent 防环（loom_transform.py:362-367），自产文件不会触发。

7) **验证**：
```powershell
python -c @"
import sys
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
import engine as E, sceneio as S
E.GLEngine._build_gpu = lambda self, m: None
e = E.GLEngine.__new__(E.GLEngine)
e.models=[];e.materials=[];e.lights=[];e.cameras=[];e.active_camera=None;e.current_model_index=0;e.gravity=-9.8
S.scene_from_dict(e, {'version':10,'objects':[
  {'id':'a','type':'cube','parent_id':'b'},{'id':'b','type':'cube','parent_id':'a'},{'id':'c','type':'cube'}]})
print('parents:', [(x.guid, x.parent.guid if x.parent else None) for x in e.models])
print('re-serialized:', [o['id'] for o in S.scene_to_dict(e)['objects']])
print('world_scale:', e.world_scale(e.models[0]))   # 该行不返回
"@
```
   实测输出（evidence.py [EVID-5]，含子进程 6s 超时）：
```
  parents: [('a', 'b'), ('b', 'a'), ('c', None)]
  re-serialized objects: ['c']
  world_scale child TIMEOUT 6s stdout='...loaded\n'
```
   （world_scale 子进程 6 秒未退出，判定为死循环）

8) **影响与等级**：**P1**。打开一个环状文件后：保存会静默删除对象（不可逆数据丢失）；任何触发 world_scale（挂父/缩放/物理/编辑器 gizmo）的操作会让编辑器永久卡死。若场景文件允许来自玩家分享/游戏包（本仓库有 game_pack 分发），应升 **P0**。
---

#### P-06 · P-PROVED · P2 · Prefab 跨场景实例化丢失材质的 PBR/贴图属性

1) **位置**：sceneio.py:1130-1137（prefab_to_dict 只写 version/prefab/objects）、180-187（_apply_object：material_id 不在库时 add_material(color,saturation,guid=mat_id)）。

2) **契约/预期**：注释 L44-45 "Prefab (M16): 资产文件只存一棵子树 (局部引用), 实例化时整体重生成 GUID"。材质引用按 guid 保留（L187 语义），说明设计上依赖"材质库"跨文件共享。

3) **路径枚举**：
   - 路径 1：目标引擎材质库已有该 guid（在同一场景内实例化）→ 共享原材质 → 正常。
   - 路径 2：目标引擎材质库没有该 guid（把 prefab 文件拖进另一个场景 / 新进程）→ add_material(color=obj['color'], saturation=...) 只还原颜色与饱和度 → metallic/roughness/pbr/albedo/normal_map/env_map 全部回默认。
   - 路径 3：prefab 文件本身没有 materials 段（L1135-1137）→ 无任何回退来源。
   - 可达性：editor.py:1109 _instantiate_prefab、agent_commands.py:1635、ui/loom_gui.py:2018。

4) **实际行为**：实例材质 guid 保留，但 pbr=False/metallic=0.0/roughness=0.5。

5) **差异**：预期"Prefab 实例还原原始外观"，实际"外观退化为纯色材质"。

6) **触发条件**：跨场景/跨进程实例化带 PBR 材质的 prefab。

7) **验证**：
```powershell
python -c @"
import sys
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
import engine as E; from mesh import create_cube; import sceneio as S
E.GLEngine._build_gpu = lambda self, m: None
def new():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models=[];e.materials=[];e.lights=[];e.cameras=[];e.active_camera=None;e.current_model_index=0
    return e
e = new(); m = e.add_model(create_cube(1.0), E.Point3D(0,0,0), E.Point3D(0,0,0))
mat = m.renderer.material; mat.metallic=0.9; mat.roughness=0.2; mat.pbr=True
pf = S.prefab_to_dict(m)
i = S.instantiate_prefab(new(), pf)[0].renderer.material
print('pbr=%s metallic=%s roughness=%s guid_kept=%s' % (i.pbr, i.metallic, i.roughness, i.guid == mat.guid))
"@
```
   实测输出：
```
pbr=False metallic=0.0 roughness=0.5 guid_kept=True
```

8) **影响与等级**：**P2**。功能缺失（外观不一致），不崩溃；是否"应当"由人类裁决（见 §5 Q3）。

---

#### P-07 · P-PROVED · P3 · _apply_ui 对同一 canvas 的多个 elements 只保留最后一个

1) **位置**：sceneio.py:840-845。

2) **契约/预期**：_emit_ui 永远只写一个 elements 项（L661），即"单 root"是当前写出契约；读取侧应与之对称（要么接受列表并明确取第一个，要么告警）。

3) **路径枚举**：
   - 路径 1：文件含 1 个 element（自产文件）→ 正常。
   - 路径 2：文件含 N>1 个 element → 循环内 canvas.root = root_el 逐个覆盖 → 只有最后一个生效，前面静默丢弃，无告警。
   - 路径 3：元素为未知 type → _apply_ui_element 打印警告并返回 None，if root_el is not None 跳过 → 不覆盖（这条有告警）。

4) **实际行为**：多 root 时后者覆盖前者。

5) **差异**：预期"明确约定单 root 并拒绝/告警多余项"，实际静默丢弃。

6) **触发条件**：手写/旧版本/第三方生成的场景，或未来 emit 改为多 root。

7) **验证**：
```powershell
python -c @"
import sys
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
import engine as E, sceneio as S, loom_ui
E.GLEngine._build_gpu = lambda self, m: None
e = E.GLEngine.__new__(E.GLEngine)
e.models=[];e.materials=[];e.lights=[];e.cameras=[];e.active_camera=None;e.current_model_index=0
e.width=1280;e.height=800;e.ui=loom_ui.UIManager()
S.scene_from_dict(e, {'version':10,'objects':[],'ui':{'canvases':[{'elements':[
  {'type':'panel','name':'first'},{'type':'panel','name':'second'}]}]}})
print('root.name =', e.ui.canvases[0].root.name)
"@
```
   实测输出：
```
root.name = second
```

8) **影响与等级**：**P3**（当前写出侧恒为单 root，触发依赖外部文件）。

---

#### P-14 · P-PROVED · P2 · decompose_euler 万向锁分支只对 β=+90° 正确，β=-90° 时重建出错误旋转

1) **位置**：matlib.py:88-95，关键分支 L90-92：
```python
if abs(cb) < 1e-9:      # 万向锁: 令 γ=0, α 从剩余分量取
    alpha = math.atan2(float(r[1, 0]), float(r[1, 1]))
    gamma = 0.0
```

2) **契约/预期**：docstring L76-83 "把旋转矩阵 R 分解回欧拉角 (α,β,γ), 与 mat4_rotation 的约定一致 … R = Rx@Ry@Rz"；分解结果必须满足 mat4_rotation(α,β,γ) == R（tests/test_decompose.py:3 的原话："mat4_rotation(euler) -> decompose -> 重构成同一矩阵"）。

3) **路径枚举**（从 mat4_rotation 的矩阵展开推）：
   - 路径 1：|cos β| ≥ 1e-9 → 通用分支 L93-95，实测往返 <1.4e-15（PASS）。
   - 路径 2：β=+90°（cb=0）→ R[1,0]=sin(α-γ)、R[1,1]=cos(α-γ)；取 γ=0 时 α=atan2(R[1,0],R[1,1])=α-γ，重建正确。
   - 路径 3：β=-90°（cb=0）→ 由 rx@ry@rz 展开得 R[1,0]=-sin(α+γ)、R[1,1]=cos(α+γ)；代码取 α=atan2(R[1,0],R[1,1])=-(α+γ)，但重建需要 α=+(α+γ) → 符号相反。
   - 路径 4：通用分支在 |cb| 刚大于 1e-9 时使用，不进入该分支。

4) **实际行为**：β=-90° 时分解出的 (α,β,γ) 重建出的是错符号旋转，矩阵最大偏差可达约 2（旋转矩阵元素量纲）。

5) **差异**：预期重建误差 <1e-9，实际 0.78~1.93（依赖 α+γ）。

6) **触发条件**：传入矩阵的 β 落在 asin 的 -π/2 端（-r[0,2] 被 clamp 到 -1，等价 |β+90°| ≲ 1e-9 rad），且 α+γ ≠ 0。真实可达路径：loom_transform.set_parent(child,parent,preserve_world=True) 对"局部欧拉 Y=-90°（sin 恰为 -1.0）且 X/Z 非零"的物体调用 decompose_euler（loom_transform.py:388）；editor.py:527 gizmo 旋转收尾同一函数。

7) **验证**：
```powershell
python -c @"
import sys, math
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
import numpy as np, matlib as M, engine as E
from mesh import create_cube
E.GLEngine._build_gpu = lambda self, m: None
pa = E.GameObject(create_cube(1.5), E.Point3D(0,0,0), E.Point3D(0,0,0), name='p')
ch = E.GameObject(create_cube(1.5), E.Point3D(1,0,0),
                  E.Point3D(math.radians(30), math.radians(-90), math.radians(45)), name='c')
e = E.GLEngine.__new__(E.GLEngine)
e.models=[];e.materials=[];e.lights=[];e.cameras=[];e.active_camera=None;e.current_model_index=0
e.models=[pa, ch]
Rb = e.world_rotation_matrix(ch).copy()
e.set_parent(ch, pa, preserve_world=True)
print('max|R_after-R_before| =', float(np.max(np.abs(e.world_rotation_matrix(ch) - Rb))))
print('local euler =', [round(math.degrees(v),3) for v in (ch.rotation.x, ch.rotation.y, ch.rotation.z)])
print('decompose 单测:')
for bdeg in (90.0, -90.0):
    R = M.mat4_rotation(np, 0.7, math.radians(bdeg), -1.1)
    a2,b2,g2 = M.decompose_euler(R)
    print('  beta=%+g rebuild_err=%.3e' % (bdeg, float(np.max(np.abs(M.mat4_rotation(np,a2,b2,g2)-R)))))
"@
```
   实测输出（evidence.py [EVID-1] + p2_gimbal）：
```
world-rotation max|after-before| = 1.9318516525781364
local euler after (deg) = [-75.0, -90.0, 0.0]
beta=+90 rebuild_err=1.110e-16
beta=-90 rebuild_err=7.788e-01
```
   现有测试为何没抓到：tests/test_decompose.py 随机 2000 组角度的 β 落在 (-π/2,π/2) 开区间内（输出"往返最大误差 6.86e-13、超差 0"），tests/test_reparent_preserve.py 只测父旋转 +90° 且子为纯位移（无 X/Z 分量）。

8) **影响与等级**：**P2**（边界）。触发窗口窄（需要 Y 恰好 -90°），但命中时物体世界朝向跳变（矩阵差 1.93），且发生在"保世界"的挂父/gizmo 收尾——用户会看到"挂父后物体突然翻转"。

---

#### P-18 · P-PROVED · P2 · Cubemap.from_solid 对越界通道直接抛 OverflowError（无校验/钳制）

1) **位置**：loom_cubemap.py:86-90（_to_255）、111-113（写入 uint8 数组）。

2) **契约/预期**：docstring L78-84 声明可接受 "(r,g,b,a) 0-255 或 '#RRGGBB'" 与 "0-1 浮点"；非法输入的错误模型未定义，但既然函数自称"占位/纯色环境"的稳健工厂，越界值应被钳制或明确拒绝。

3) **路径枚举**：
   - 路径 1：字符串 → _hex_rgba 保证 0-1 → 正常。
   - 路径 2：tuple/list 且每个通道 ∈[0,1] → 乘 255 → 正常。
   - 路径 3：tuple/list 且存在通道 ∈(1,255] → 原样取整 → 正常。
   - 路径 4：存在通道 >255 或 <0 → np.zeros(...,uint8) 赋值 → numpy 2.x 抛 OverflowError（numpy<2 会静默回绕，行为随依赖版本变化，更不可控）。
   - 路径 5：_apply_skybox 调 from_solid 时被 L397-407 的 try/except: pass 吞掉 → 场景静默无天空盒（不崩但丢数据）。

4) **实际行为**：OverflowError: Python integer 300 out of bounds for uint8。

5) **差异**：预期"钳制/明确 ValueError"，实际 OverflowError（且错误类型依赖 numpy 版本）。

6) **触发条件**：任何把 0-255 之外数值传入 from_solid 的调用（EAI set_env 颜色、手写场景的 solid_color、脚本调用）。

7) **验证**：
```powershell
python -c @"
import sys
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
from loom_cubemap import Cubemap
for c in [(300,0,0), (-5,0,0), (255,255,255,255)]:
    try:
        cube = Cubemap.from_solid(c, size=2)
        print('from_solid(%r) -> %s' % (c, cube._faces[0][0,0].tolist()))
    except Exception as ex:
        print('from_solid(%r) -> %s: %s' % (c, type(ex).__name__, ex))
"@
```
   实测输出（evidence.py [EVID-6]）：
```
  from_solid((300, 0, 0)) -> OverflowError: Python integer 300 out of bounds for uint8
  from_solid((-5, 0, 0)) -> OverflowError: Python integer -5 out of bounds for uint8
  from_solid((255, 255, 255, 255)) -> pixel [255, 255, 255, 255]
```

8) **影响与等级**：**P2**（边界输入）。skybox 加载路径被吞成静默 None；直接调用方（EAI 命令）会拿到异常。

---

#### P-19 · P-PROVED · P3 · ensure_gl 在面数不足 6 时静默上传未初始化面

1) **位置**：loom_cubemap.py:121-131。

2) **契约/预期**：类 docstring L23 "6 面 RGBA"；from_files 显式检查 len(paths) != 6（L46-47）并在 tests/test_cubemap.py 有 PASS from_files 面数不足报错。构造器 faces= 参数与 ensure_gl 应维持同一不变量。

3) **路径枚举**：
   - 路径 1：faces 为 None/空 → L126-128 用 1x1 全白兜底并把 size 置 1 → 正常。
   - 路径 2：faces 恰好 6 → 正常。
   - 路径 3：0 < len(faces) < 6 → for i, f in enumerate(faces[:6]) 只写已有面；ctx.texture_cube 已按 size 创建，其余面内容为 GL 未定义值 → 采样出垃圾，无异常、无告警。
   - 路径 4：len(faces) > 6 → 多余面被 [:6] 静默截断。

4) **实际行为**：上传成功，未写面内容未定义。

5) **差异**：预期与 from_files 同等校验，实际无校验。

6) **触发条件**：直接 Cubemap(size, faces=[...]) 且列表长度 ≠6（脚本/工具构造）。

7) **验证**：
```powershell
python -c @"
import sys, numpy as np
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
import moderngl
from loom_cubemap import Cubemap
ctx = moderngl.create_standalone_context()
c = Cubemap(2, faces=[np.full((2,2,4), 7, np.uint8)])
print('faces_len =', len(c._faces))
t = c.ensure_gl(ctx)
print('ensure_gl ->', t is not None, 'filters =', t.filter)
ctx.release()
"@
```
   实测输出：
```
faces_len = 1
ensure_gl -> True filters = (9987, 9729)
```

8) **影响与等级**：**P3**（内部构造错误才会触发；渲染垃圾但无崩溃）。

---

#### P-22 · P-PROVED · P3 · 零方向向量被静默解释为 +z，而非回退默认方向

1) **位置**：loom_scene_entities.py:32-41（direction_to_angles）、69-73（LightState.__init__ 的 direction 分支）；调用方 sceneio.py:349-364（_f3(d.get('direction'), (0,-1,0))）。

2) **契约/预期**：_apply_lights 的缺省 direction 是 (0,-1,0)（L350，即"从上往下照"）；direction_to_angles docstring L33-35 只定义单位向量语义。

3) **路径枚举**：
   - 路径 1：方向向量长度为 0 → n = math.sqrt(0) or 1.0 → 1.0 → x=y=z=0 → el=asin(0)=0，az = 0 if not (z or x) → (0°,0°) → 派生方向 (0,0,1)。
   - 路径 2：NaN 分量 → or 1.0 不生效（NaN 真值）→ az=NaN、el=90°、方向含 NaN（备注，未单独立项）。
   - 路径 3：合法单位向量 → 正常。

4) **实际行为**：(0,0,0) 不是"回退默认 (0,-1,0)"，而是变成"朝 +z 的平行光"。

5) **差异**：预期"坏方向 → 默认/告警"，实际"水平 +z 静默"。

6) **触发条件**：场景 "direction": [0,0,0]（或全零 float 组），且 azimuth 缺失（有 azimuth 时走角度分支）。

7) **验证**：
```powershell
python -c @"
import sys
sys.path.insert(0, r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom')
from loom_scene_entities import LightState
L = LightState(kind='directional', direction=(0,0,0))
print('az/el =', L.azimuth, L.elevation, ' direction =', tuple(round(v,6) for v in L.direction))
"@
```
   实测输出：
```
az/el = 0.0 0.0  direction = (0.0, 0.0, 1.0)
```

8) **影响与等级**：**P3**（坏输入下光照方向错误，不崩溃）。
### 2.2 P-DISPROVED（12 项）

---

#### P-08 · P-DISPROVED · scene_from_dict 不清空 engine.models（怀疑重复对象）

1) **位置**：sceneio.py:914-918（objects 循环）与同函数 L909-913（ui/lights/cameras/materials 都 clear）。
2) **契约**：docstring L898-900 "dict -> 引擎场景 (容错加载)"；未声明"必须清空 models"。三处生产调用方均在调用前显式清空：editor.py:992-997（remove_model 全删 + undo.clear）、runtime.py:28-50（remove_model 默认场景）、loom_model_gpu.py:337-341（clear_scene()）。
3) **路径枚举**（调用方全集，grep scene_from_dict 结果）：
   - 路径 1 editor.py:997 → 先删除全部 models（L993-994）。
   - 路径 2 runtime.py:50 → L29-30 先 remove_model 清默认场景。
   - 路径 3 loom_model_gpu.py:341 → L337 clear_scene()（L315-321 清 models + materials）。
   - 路径 4 测试/探针直接调用：属调用方责任。
   无第四条生产路径；不存在"调用后出现旧对象残留"的可达场景。
4) **实际行为**：追加式加载（探针实测 models 2 个：旧 + 新）。
5) **差异**：无（契约未要求自清空，三个生产调用方均满足前置条件）。
6) **触发条件**：仅当新调用方忘记清空时才会重复；当前无此调用方。
7) **验证**：p3_sceneio.py [C5] 输出 "加载后 models 数=2 名称=['旧','新']"，同时 grep 显示 3 个调用方均先清空。
8) **判定**：**P-DISPROVED**（不构成当前 bug）；建议作为 P3 文档化（"调用方必须先清空 models"），或让函数自清空以消除 API 陷阱。

---

#### P-09 · P-DISPROVED · UI 元素字段映射（15 类）往返不一致？

1) **位置**：sceneio.py:542-647（emit）、673-809（apply）。
2) **契约**：每个 type 的 emit/apply 必须字段同名同义；未知 type 跳过并告警（L788-790）。
3) **路径枚举**：按 15 个 emit 分支逐一对应 apply 分支（panel/text/image/button/slider/toggle/progress_bar/scroll_view/dropdown/grid_layout/input_field/shape/element + 未知类型 + children 递归 + event_bindings）。本次用"全类型实例 → emit → apply → 再 emit"做端点对照，覆盖全部 15 条路径。
4) **实际行为**：两次 emit 完全相等；与输入逐字段对照仅 grid 子元素多出 reflow 后的 rect（预期：_reflow 覆盖）。
5) **差异**：无。
6) **触发条件**：无。
7) **验证**：p8_allui.py 输出 ui round-trip equal: True，12 个元素 FIELD-OK（grid 的差异是 reflow 补齐 rect，不是丢失）。
8) **判定**：**P-DISPROVED**（字段映射无错名/漏字段）。备注：多 root 覆盖问题见 P-07，坏数值字段见 P-01。

---

#### P-10 · P-DISPROVED · skybox 路径失效静默 None 违反契约？

1) **位置**：sceneio.py:393-407。
2) **契约**：docstring L394 明写 "dict -> Cubemap 实例（失败返回 None，容错）"。
3) **路径枚举**：路径 1 无 skybox 段 → None；路径 2 paths 全存在 → Cubemap；路径 3 任一文件缺失/解码失败 → Cubemap.from_files 抛 ValueError → 被 L405-406 捕获 → None；路径 4 solid_color → from_solid。全部路径与契约一致。
4) **实际行为**：场景加载成功，engine._skybox = None。
5) **差异**：无（对契约而言）。
6) **触发条件**：天空盒文件被移动/删除。
7) **验证**：p3_sceneio.py [C6] 输出 "加载成功 _skybox=None"，无异常。
8) **判定**：**P-DISPROVED**；建议 P3：加一条可见日志（与音频 category 的显式告警对齐），否则用户无法定位"天空盒为什么没了"。

---

#### P-11 · P-DISPROVED · 内存态 cubemap 无法序列化

1) **位置**：sceneio.py:378-390。
2) **契约**：docstring L390 明写 "无可用来源（内存态 cubemap 无法序列化）"。
3) **路径枚举**：paths 非空 → 写 paths；_solid_color 非空 → 写 solid_color；都无 → None。三条路径与注释逐条对应，无遗漏。
4) **实际行为**：返回 None。
5) **差异**：无。
6) **触发条件**：直接构造 Cubemap(size, faces=[...]) 后赋给 skybox。
7) **验证**：p5_ui_prefab.py 输出 "_emit_skybox(内存态) = None"。
8) **判定**：**P-DISPROVED**（契约已声明）。

---

#### P-12 · P-DISPROVED · 材质贴图/环境贴图文件缺失静默跳过

1) **位置**：sceneio.py:512-537。
2) **契约**：L496 注释 "文件缺失/解码失败 -> 跳过贴图, 容错"；L537 "文件缺失 -> 保持无 env (容错)"。
3) **路径枚举**：albedo/normal_map（L515 有 path → try 重建；无 path → 跳过；异常 → pass）、env_map（L530 paths 存在 → try；否则跳过；异常 → pass）。与注释一致。
4) **实际行为**：材质保留其余字段，贴图槽为空。
5) **差异**：无。
6) **触发条件**：贴图文件被删除。
7) **验证**：代码路径直读 + tests/test_cubemap.py 的 "PASS 材质设 env" / "PASS ensure_gl 可用" 覆盖正向；缺失路径未产生异常。
8) **判定**：**P-DISPROVED**；建议 P3 同 P-10 加日志。

---

#### P-13 · P-DISPROVED · v8→v9 相机弧度→度迁移误伤顶层轨道 camera

1) **位置**：sceneio.py:975-989。
2) **契约**：L977-978 注释 "只改 cameras 数组; 顶层编辑器轨道 camera dict 仍是弧度 … 不碰"。
3) **路径枚举**：路径 1 v≥9 → 整段跳过；路径 2 v<9 且无 cameras → 空循环；路径 3 v<9 且有 cameras → 只改 data['cameras']，从未读 data['camera']。
4) **实际行为**：cameras[0].yaw 90.0（由 π/2 转度）；顶层 camera.yaw 仍 1.5707963。
5) **差异**：无。
6) **触发条件**：加载 v8 场景。
7) **验证**：p6_misc.py [3] 输出：
```
   camera(顶层) = {'yaw': 1.5707963, 'pitch': 0.5}
   cameras[0]  = {'yaw': 90.0, 'pitch': 28.6479, 'roll': 0.0, ...}
   PASS 相机 yaw 弧度->度 (90.0)
   PASS 顶层 camera 未被改成度
```
8) **判定**：**P-DISPROVED**（迁移正确）。

---

#### P-15 · P-DISPROVED · mat4_look_at / mat4_view_forward 零向量除零可达？

1) **位置**：matlib.py:113-134（look_at）、212-237（view_forward）。
2) **契约**：输入要求 eye≠target、forward 非零（数学定义上的前置条件）。
3) **路径枚举**（调用方全集，grep 结果）：
   - mat4_look_at：全仓库仅 matlib.py:18（文档）与 L113（定义）出现，**零调用方** → 路径不存在。
   - mat4_view_forward：loom_lighting.py:696 附近用于光源视图，forward 取自 LightState.direction（由单位球面三角函数构造，恒为单位向量；P-22 的 NaN 情形另计）；up 取自 up_vector()（单位且与 d 正交，本次 P-17 实测）。
   - mat4_perspective 的 aspect：唯一调用 loom_render.py:771 self.width / self.height，窗口尺寸在 loom_glfw_window.py:172-173 等处被 max(320,…)/max(240,…) 钳制 → 不为 0。
4) **实际行为**：显式传退化值会抛 ZeroDivisionError（实测），但无生产路径传入退化值。
5) **差异**：无（不可达）。
6) **触发条件**：仅外部/新增调用方传退化值。
7) **验证**：p1_matlib.py [E] 输出 "mat4_look_at eye==target -> ZeroDivisionError" 等 5 条；grep 确认 look_at 无调用方。
8) **判定**：**P-DISPROVED**（不可达）；建议 P3：给 look_at 加零向量保护或删除死代码（它现在只被 docstring 提到）。

---

#### P-16 · P-DISPROVED · perspective/ortho 深度映射与注释不符？

1) **位置**：matlib.py:99-110、199-209。
2) **契约**：L102-103 "clip.z 映射到 [0,1] 单调递增 (near->0, far->1)"；L201 同义。
3) **路径枚举**：z=near、z∈(near,far)、z=far、z<0（相机后）全部代入行向量 [0,0,z,1] @ P。
4) **实际行为**：perspective：w=z，ndc.z(near)=0、ndc.z(far)=1、单调整；ortho：w=1，z=0.1→0、10→1。
5) **差异**：无。
6) **触发条件**：无。
7) **验证**：p1_matlib.py [F][G]：
```
PASS F) perspective z=0.3 -> ndc.z  w=0.300000 ndc_z=0.000000
PASS F) perspective z=100 -> ndc.z  w=100.000000 ndc_z=1.000000
PASS G) ortho z=0.1 -> ndc.z  ndc_z=0.000000
PASS G) ortho z=10 -> ndc.z  ndc_z=1.000000
```
8) **判定**：**P-DISPROVED**。

---

#### P-17 · P-DISPROVED · view_basis_to_angles 与 mat4_view_yaw_pitch 的 roll 不互逆？

1) **位置**：matlib.py:137-172（正向，sn=-sin）、175-196（反解）。
2) **契约**：docstring L176-187 "给定世界/父空间正交基 … 还原 (yaw,pitch,roll) 弧度, 使 mat4_view_yaw_pitch 的旋转部分重建同一基 … 与负绕向约定一致"；LightState.up_vector/CameraState.up_vector 须保持单位正交。
3) **路径枚举**：roll=0（跳过旋转分支 L154）、roll≠0（L154-162）、pitch=±90（退化）、任意 yaw。本次 2000 组随机 (yaw,pitch∈(-1.5,1.5),roll) 端点往返 + 5 组 up_vector 正交/归一 + 2 组 pitch 近 90°。
4) **实际行为**：往返最大误差 8.88e-16；up_vector |u|=1、u·d≤5.6e-17；pitch=90° 往返误差 0，pitch=89.999999° 误差 2.35e-09（条件数导致，量级正确）。
5) **差异**：无（2.35e-09 来自接近万向锁的病态条件，不属于实现错误）。
6) **触发条件**：无。
7) **验证**：p2_gimbal.py [1] 输出 "PASS 1) view_basis_to_angles 往返 <1e-9 maxerr=8.882e-16"；p4_ent_cube.py [E4] 5 条 PASS。
8) **判定**：**P-DISPROVED**。

---

#### P-20 · P-DISPROVED · wrap_deg(180,-180,180) 返回 -180 导致角度错误？

1) **位置**：loom_scene_entities.py:23-29。
2) **契约**：docstring L24 "把 v 环绕进 [lo, hi)"（半开区间）；类注释 L51-52 写 "elevation 俯仰 (-180,180]"，两处写法相反。
3) **路径枚举**：路径 1 已在区间 → 原样；路径 2 v=hi → lo + ((hi-lo)%span) = lo；路径 3 v<lo 或 ≥hi+span → 取模。对 ±180 两条路径都落到 -180。
4) **实际行为**：方向向量对 180° 与 -180° 完全相同（(0,0,-1)），up_vector 在极点处参考方向任取。
5) **差异**：行为等价，无功能 bug；只有注释区间写法与实现相反。
6) **触发条件**：输入恰为 180。
7) **验证**：p4_ent_cube.py 输出 "wrap_deg(180,-180,180) = -180.0"；"in(yaw,pitch,roll)=(0,180,0) -> stored=(0.0,-180.0,0.0) dir=(-0.0,-0.0,-1.0)"（与 -180 一致）。
8) **判定**：**P-DISPROVED**（无行为差异）；建议 P3 统一注释为 [-180,180)。

---

#### P-21 · P-DISPROVED · 方向缓存不失效？

1) **位置**：loom_scene_entities.py:100-108（缓存键 (azimuth, elevation, roll)）。
2) **契约**：docstring L97-99 "azimuth/elevation/roll 或 direction 反算路径写入即 bump 版本失效"。
3) **路径枚举**：路径 1 直接改 azimuth → 键变 → 重算；路径 2 direction setter → 写三个角度 → 键变；路径 3 roll 变 → 键变（方向不依赖 roll，只多一次缓存 miss，无正确性问题）；路径 4 角度不变 → 命中缓存返回同一 Point3D。
4) **实际行为**：改 azimuth 后 direction 立即更新（实测 az 0°→90°：(0,0,1)→(1,0,0)）。
5) **差异**：无。第一次探针误用 elevation=-90°（此时 azimuth 对方向无影响）导致假阳性，已用 elevation=0 复测。
6) **触发条件**：无。
7) **验证**：p5_ui_prefab.py [E2b] 输出 "az=0 -> (0.0,0.0,1.0) ; 改 az=90 -> (1.0,0.0,0.0)"。
8) **判定**：**P-DISPROVED**。

---

#### P-24 · P-DISPROVED · cubemap ctx 切换时旧 GL 纹理泄漏？

1) **位置**：loom_cubemap.py:121-148。
2) **契约**：docstring L9 "CPU 侧持 6 面 RGBA，GPU 侧延迟创建（同 Texture 纪律）"；L122 "已有则直接返回"。
3) **路径枚举**：路径 1 同 ctx 且已建 → 直接返回（L123-124）；路径 2 首次/新 ctx → 新建并覆盖 _gl_tex；路径 3 release() → 显式释放（L158-165）。路径 2 的旧对象是否释放取决于 Python 引用计数 + moderngl GC：self._gl_tex = tex 覆盖后旧对象无可达引用，moderngl 在对象析构/上下文 GC 时释放。
4) **实际行为**：未观察到显式 double-release 或崩溃；release() 后 gl_tex is None（tests/test_cubemap.py "PASS release 后 gl_tex 为 None"）。
5) **差异**：无（若旧 ctx 已销毁，纹理随上下文消失，不构成长期泄漏）。
6) **触发条件**：需要"同一 Cubemap 跨 ctx 复用且旧 ctx 仍存活"的调用点；grep 未找到 ctx 重建路径。
7) **验证**：p4_ent_cube.py [K3] "PASS size=4: gl_tex=True mipmaps=True filters=(9987,9729)"；"release -> gl_tex= None"。
8) **判定**：**P-DISPROVED**（当前无泄漏证据）；如需强保证，可在覆盖前显式 try: old.release()（P3）。

---

### 2.3 P-UNKNOWN（1 项）

#### P-23 · P-UNKNOWN · 双后端加载语义漂移（scene_driver/vk_renderer 复制 sceneio 逻辑）

- **已尝试探针**：阅读 scene_driver.py:342-390（_apply_skybox、_apply_ui、自建 build_materials/build_models/build_lights/build_cameras）；vk_renderer.py:957-980（懒补 _link_ui_targets）；scene_driver.py:148-166（env_map 重建副本）。
- **已知事实**：VK 侧 load_from_data 的材质/物体/相机/光源构建是平行实现（scene_driver.py:360-367），并额外把 _apply_ui 的异常捕获打印（L355-359）；scene_driver.py:158-162 的 env_map 重建同样只认 paths（与 P-04 同构）。
- **无法判定的原因**：这些文件不属于本模块清单；要判定"同一场景在 GL/VK 两侧加载结果是否等价"需要运行双后端端到端对比（tests/test_vk_camera_align.py、tests/_tmp/ab_gl_vk.py），属于 04/05 号审计员的范围。
- **还缺的信息**：VK 渲染器实机可用性（当前仅确认 scene_driver 源码事实，未运行 VK 帧循环）。
- **建议下一步探针（≤3）**：① 对同一 scene dict 分别走 sceneio.scene_from_dict 与 SceneDriver.load_from_data，比对 models/cameras/lights/materials 的字段级快照；② 若 P-04 修复，检查 scene_driver 的 env_map 副本是否同步；③ 运行 tests/test_vk_camera_align.py 观察双端相机一致性。
- **等级**：暂记 **P-UNKNOWN**（不等于无风险；P-04 的双后端副本几乎肯定同样丢纯色 env）。

---

## 3. 统计（数量表）

| 结论 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 11 | P-01, P-02, P-03, P-04, P-05, P-06, P-07, P-14, P-18, P-19, P-22 |
| P-DISPROVED | 12 | P-08, P-09, P-10, P-11, P-12, P-13, P-15, P-16, P-17, P-20, P-21, P-24 |
| P-UNKNOWN | 1 | P-23 |
| P-CONTRADICTION | 0 | — |
| [REGRESSION] | 0 | 本模块 4 文件相对 HEAD 零 diff（§0.2） |
| 粗筛/回填合计 | 24 | P-01 ~ P-24 |

### 3.1 按等级（仅 PROVED）

| 等级 | 数量 | 编号 |
|---|---|---|
| P0（崩溃/安全） | 0 | — |
| P1（功能/数据错误） | 4 | P-01, P-03, P-04, P-05 |
| P2（边界/功能缺失） | 4 | P-02, P-06, P-14, P-18 |
| P3（加固/可维护性） | 3 | P-07, P-19, P-22 |

### 3.2 按文件

| 文件 | PROVED | DISPROVED | UNKNOWN |
|---|---|---|---|
| sceneio.py | 7（P-01 ~ P-07） | 6（P-08 ~ P-13） | 1（P-23，跨模块） |
| matlib.py | 1（P-14） | 3（P-15 ~ P-17） | 0 |
| loom_cubemap.py | 2（P-18, P-19） | 1（P-24） | 0 |
| loom_scene_entities.py | 1（P-22） | 2（P-20, P-21） | 0 |

---

## 4. 修复建议排序（按 P0→P3，只给方向，不含代码）

1. **P1 / P-01**：在 sceneio 加载入口建立统一的类型收敛层（等价于把 _f1/_f3 扩展为 _as_float/_as_int/_as_bool），覆盖 gravity、collider 三件套、rigidbody 六字段、animator frames、光源角度、相机 pitch_min/max、UI 的 int/float 字段与 objects 容器；失败要带"物体名+字段名"的可见告警；保证 scene_from_dict 要么全成功、要么在改动引擎前完成 schema 预检（避免半加载）。补一条"坏字段矩阵"回归用例（当前 test_sceneio 只覆盖 position/rotation/scale/light/camera 五项）。
2. **P1 / P-05**：_link_by_map 按格式注释（父必须先于子）只接受已出现的父 id；建链后做一次环检测（visited 集），发现即断开并告警。world_scale/is_ancestor/model_world_matrix/world_rotation_matrix 增加环保护（迭代 + visited 或递归深度上限）。补一个"环文件"回归用例。
3. **P1 / P-03**：在 _apply_object 用库材质替换后，把 add_model 自建的默认材质从 engine.materials 移除（或给 add_model 增加"不注册材质"的内部开关）；新增 save→load→save 幂等断言（材质数不增长）。
4. **P1 / P-04**：_emit_material 对 env_map._solid_color 写 solid_color 段，_apply_materials 增加 from_solid 分支；同步 scene_driver.py 的副本实现（P-23）。
5. **P2 / P-14**：万向锁分支按 β 符号区分 atan2 的符号（β=-90° 取 atan2(-r[1,0], r[1,1])）；在 test_decompose 增加 β=±90° 精确点与"α、γ 非零"的组合；在 test_reparent_preserve 增加"子物体 Y=-90° 且 X/Z 非零"用例。
6. **P2 / P-18**：_to_255 增加 0..255 钳制（或对越界显式抛 ValueError 并在 _apply_skybox 打印告警），避免错误类型随 numpy 版本漂移。
7. **P2 / P-02**：布尔字段统一 _as_bool（只接受真正的 bool，字符串给出告警并回退默认），并让 visible 在加载时收敛为 bool。
8. **P2 / P-06**：Prefab 携带可选 materials 段，或在实例化时按 guid 到工程材质库回查；否则在文档中明确"prefab 不携带材质，跨场景实例化会退化"。
9. **P3 / P-07**：_apply_ui 对 len(elements) > 1 给出告警（保留第一个或最后一个要写死并测试）。
10. **P3 / P-19**：ensure_gl 对 faces 长度 ∉ {0,6} 抛 ValueError（与 from_files 对齐）。
11. **P3 / P-22**：direction_to_angles 对零向量返回默认 (0,-1,0) 的等价角度（el=-90°）或抛 ValueError；_apply_lights 对零向量打印告警。
12. **P3 / P-10、P-11、P-12**：skybox/贴图丢失时打印一次可见日志（与音频字段的显式告警风格一致）。
13. **P3 / P-15**：删除或加保护的 mat4_look_at（当前零调用方）；mat4_view_forward 补零向量保护。
14. **P3 / P-20**：统一注释区间（[-180,180)）或改用闭区间实现，避免下一位读者误判。

---

## 5. 需要人类裁决的封闭问题（3 条）

1. **场景/存档文件是否视为"不可信输入"？**
   - 背景：P-05（环 → 死循环 + 静默丢对象）与 P-01（坏字段 → 崩溃）只在"文件可能被手改/第三方生成"时才有实际威胁；正常编辑器自产文件不会触发。
   - 问题：A) 视为不可信（需按 P0/P1 全量防御 + 加载前 schema 预检）；B) 只保证"自产文件正确"，坏文件允许报错退出（则 P-05 降 P2、P-01 降 P2，只需保证错误信息可读）。
   - 影响：决定 §4 第 1/2 条的投入规模。

2. **材质库保存时是否允许自动裁剪"无任何物体/资产引用"的条目？**
   - 背景：P-03 的根因是加载时产生孤儿；也可以选择"保存时裁剪"来止血，但会删掉用户手工创建、暂未使用的材质资产（当前 _emit_material 全量收录，且 test_sceneio 的断言"换材质不清库"暗示库只增不减是被接受的）。
   - 问题：A) 只在加载时阻止孤儿产生（保留手工材质）；B) 保存时裁剪未引用材质（文件更干净，但可能丢"素材库"语义）；C) 两者都做（需要给材质加"资产"标记）。

3. **Prefab 是否应携带材质资产？**
   - 背景：P-06——prefab 文件只有 objects，跨场景实例化时 PBR/贴图丢失；_emit_object 仍写 material_id 说明设计意图是"引用工程材质库"。
   - 问题：A) prefab 携带 materials 段（自包含，文件更大）；B) 维持现状，实例化时按 guid 到工程材质库/资产目录回查（需要"工程级材质库"概念）；C) 明确不支持，文档声明"prefab 不含材质，跨场景实例化会退化"。

---

## 附：本报告所有实测输出的复现入口

- 探针源码：%TEMP%\loom_audit_02\p1_matlib.py … p8_allui.py、evidence.py（每个文件开头都有 sys.path.insert，可直接 python <file> 复跑；正文各条已内联最小复现片段）。
- 统一环境：$env:LOOM_NO_SAVE_MIGRATE='1'; $env:LOOM_QUIET='1'; $env:PYTHONIOENCODING='utf-8'。
- 全程未修改任何受跟踪文件：审计前 git status --porcelain 1085 条，审计后 1086 条，唯一新增为报告文件本身（未跟踪）；四个受审计文件的状态查询恒为空。


