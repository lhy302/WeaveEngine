# 资源与工具（mesh / loom_texture / loom_font / loom_raycast / audio_backend / layer_tag / loom_color / loom_types）扫描报告

> 审计协议：docs/audit/SCAN_PROTOCOL.md（2026-11-07，只读审计）
> 方法论依据：桌面《论如何正确的 vibe coding》《论如何使用 AI 自动化工具正确的判断 AI 给出的黑盒是否符合设计标准》
> 审计对象工作区：D:\my-project - 副本\Loom(py源代码-工作区)\Loom
> 本模块主 Agent 指定重点：网格/贴图/字体的边界输入与缓存、射线检测退化情形、音频后端生命周期、层标记位宽

---

## 0. 范围与方法

### 0.1 文件清单（HEAD = 4f4665011e7891d221934ac0300ef42544eab90d）

| 文件 | 行数 | HEAD blob sha1 |
|---|---|---|
| Loom/mesh.py | 361 | 3400200ba9a8d8f64d5ce51c10a1c6835042226f |
| Loom/loom_texture.py | 198 | 761e9448b39637f8334cca21373cc9b07071f595 |
| Loom/loom_font.py | 184 | ba60909a959934cbd74228646a96fa00ca8372d6 |
| Loom/loom_raycast.py | 292 | 1484a8ede930acf4caa5e26336633f590366c71c |
| Loom/audio_backend.py | 220 | ea2aec24cf94774667c384ba6720bf767815fe4b |
| Loom/layer_tag.py | 173 | eec6687dcd284fbe7b03f1ed8561856880532097 |
| Loom/loom_color.py | 19 | 9195e63aabad4fa24d014d19ff10d237318d9a28 |
| Loom/loom_types.py | 8 | 2d0a416259a6c4ee7861ab06a5b73db9d120b280 |

### 0.2 [REGRESSION] 专项：git diff 结果

~~~powershell
cd "D:\my-project - 副本\Loom(py源代码-工作区)"
git diff --stat HEAD -- Loom/mesh.py Loom/loom_texture.py Loom/loom_font.py Loom/loom_raycast.py Loom/audio_backend.py Loom/layer_tag.py Loom/loom_color.py Loom/loom_types.py
# 输出：（空）
git status --porcelain -- <上述 8 文件>
# 输出：（空）
~~~

结论：**本模块 8 个文件相对 HEAD 零改动**，本轮"Vulkan 对齐"未提交改动没有落到本模块文件上，因此本模块**无 [REGRESSION] 项**（REGRESSION 计数 = 0）。

跨模块观察（不在本模块文件内，仅登记，不重复其它模块的裁决）：
- 本轮改动集中在 engine.py / editor.py / scene_driver.py / loom_lighting.py / loom_ui.py / runtime.py / vk_renderer.py 等（与本模块文件无直接 diff）；本模块的**调用方**改动是这些模块的审查范围。
- 同款缺陷在其它模块复制：`loom_cubemap.py:123,147` 使用与本模块 `loom_texture.py:134,186` 完全相同的 `_gl_ctx_id == id(ctx)` 缓存键（见 P-05 说明）。
- `vk_renderer.py:1212` 存在死代码 `tex.ensure_gl(None) if False else None`，VK 侧调用 loom_texture 的意图未落地（属 04_vk_render 范围，仅登记）。

### 0.3 实际跑过的命令（全部在临时目录，未改仓库文件）

探针目录：`%TEMP%\loom_scan10`（C:\Users\Administrator\AppData\Local\Temp\loom_scan10），每个探针自包含；正文每条链的第 7 段给出可复制的复现片段。

~~~powershell
$env:LOOM_NO_SAVE_MIGRATE='1'; $env:PYTHONIOENCODING='utf-8'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$env:SDL_VIDEODRIVER='dummy'
cd "$env:TEMP\loom_scan10"
python p1_mesh.py                 # 网格边界参数 / spec_to_mesh / sceneio 兜底
python p1b_mesh.py                # 退化网格 / _parse_face_corner / OBJ 上限
python p2_texture.py              # 贴图 ctx 缓存 / 换 ctx 泄漏 / from_rgba 越界
python p2b_texture_idreuse.py     # 主动寻找 id(ctx) 地址复用
python p3_font.py                 # _has_glyph 阈值 / _missing 跨字号污染 / 字号缓存
python p3b_font_emoji.py          # 零宽字符判定 / 分段
python p3c_zwj.py                 # emoji ZWJ 序列分段实测
python p4_raycast.py              # 双后端语义 / layer_mask / 反投影 / slab 边界
python p5_raycast2.py             # 物理 100 次上限 / handle 未登记 / max_dist
python p6_layertag.py             # tag 校验 / reload(base) / 落盘失败 / 层表边界
python p7_audio.py                # 后端选择 / 句柄缓存 / shutdown / atexit / 路径编码
python p8_audio2_color.py         # mode 不可用 / shutdown 残留 / _hex_rgba 边界
python p9_meshgeom.py             # 零面积面 / cube 绕序
~~~

环境：Python 3.12.10 / numpy 2.2.5 / pygame 2.6.1 / moderngl 5.12.0。

定向回归测试（未跑全量 tests/run_all.py）：

~~~powershell
cd "D:\my-project - 副本\Loom(py源代码-工作区)\Loom"
python tests/test_mesh_import.py   # 总结果: ALL PASS ✅（含 "OBJ 顶点超限抛 ValueError"）
python tests/test_audio.py         # 总结果: ALL PASS ✅（含 "shutdown 后 load 静默 None"）
~~~
未跑 `tests/test_texture.py`：它需要 `moderngl.create_standalone_context()` + `EditorApp` 全量装配、会重写 `tests/_tmp`，与本轮"定向探针"约束冲突；其覆盖的多上下文语义改用假 moderngl 探针（p2/p2b）等价验证。

### 0.4 只读自证

| 时点 | `git status --porcelain` 计数 | 本模块 8 文件状态 | 说明 |
|---|---|---|---|
| 审计开始 | 988 未跟踪 + 100 已改动（含 11 条已暂存 D） | 空 | 均为审计前既有状态 |
| 审计结束 | 989 未跟踪（988 + 本报告 scan_10_assets.md）+ 100 已改动 | 空 | 源码/测试零新增、零修改 |

受跟踪文件**零内容改动**（`git diff --name-only HEAD` 不含本模块任何文件）。唯一副作用：跑 `tests/test_audio.py` / `tests/test_mesh_import.py` 时 `Loom/输入配置.json` 被重写（mtime 08:47:51），内容与 HEAD 逐字节一致（`git diff` 为空），非受跟踪内容漂移，登记备查。

### 0.5 判定基准清单（后续证真链只准引用这里）

| 编号 | 基准 | 出处 |
|---|---|---|
| C1 | Layer 0~31、Layer 名 ≤32、Tag ≤64、Tag ≤1000、字符集 字母/数字/下划线/中文；Tag 非法输入须拒绝 | docs/design/LayerTag系统契约_20261018.md §9、§3.2 |
| C2 | 配置文件损坏 → 回退默认值 **+ 控制台警告**，不阻止启动 | 同上 §3.1「错误处理」、§8 错误模型汇总 |
| C3 | 回退链顺序固定 msyh→seguiemj→seguisym→simsun→msgothic→malgun；「从左到右查，**第一个有该字形的字体胜出**」；缓存「首次查询→之后零 freetype」；分段渲染「与逐字符渲染视觉一致」 | docs/design/CanvasUI系统契约_20261018.md §2.5.1 / §2.5.2 / §2.5.3 |
| C4 | audio：auto=ga 成功用 ga 否则 pygame；**两者皆失败 → 置不可用**；per-file 回退；异常全部捕获静默；退出必须 shutdown | Loom/audio_backend.py:9-28 模块契约段、`mode` property 文档 :241-244 |
| C5 | raycast：`backend` 三档语义；`physics` 强制物理（**无桥返回 None + 警告**）；`raycast_all` 返回所有命中按距离升序 | Loom/loom_raycast.py:9-21, :17-19, :12-13 |
| C6 | Mesh 不变量：面数=颜色数、索引在 [0,nv)、顶点三维、法线/UV 数与顶点一致 | Loom/mesh.py:25-36 |
| C7 | `spec_to_mesh`：基元类型+参数→Mesh，未知基元抛 ValueError；OBJ 资源上限用于「恶意超大文件内存 DoS 防护」 | Loom/mesh.py:129-145, :184-186 |
| C8 | 既有测试断言（回归基线） | tests/test_mesh_import.py:168（v 上限）、tests/test_audio.py:167-215（双后端/shutdown/中文路径）、tests/test_texture.py:227-265（导入设置/压缩/多 ctx） |

---

## 1. 粗筛清单（含跳过项留痕）

标签取自协议 §1 的六类（契约/不变量/错误模型/资源边界/并发/边界输入）。P-02 / P-06 / P-13 / P-26 为阶段二回填项（回填原因写在行内）。

| ID | 位置 | 标签 | 初步方向（一句话） | 粗筛证据 |
|---|---|---|---|---|
| P-01 | mesh.py:84-87, 129-145；sceneio.py:160-163 | 边界输入 / 错误模型 | `stacks=0`/`slices=0` 由场景 JSON 传入 → ZeroDivisionError，逃出 sceneio 的 (ValueError,TypeError) 兜底 | `phi = math.pi * i / stacks`；`except (ValueError, TypeError)` |
| P-02 | mesh.py:28-36, 79-113 | 不变量 | 负 stacks/slices 生成 0 顶点空网格，`_validate` 全绿放行 | 校验里没有 nv>0 / faces 非空 |
| P-03 | mesh.py:304-320, 184-186 | 资源边界 | OBJ 上限只护 v/f，vt/vn 列表无上限（DoS 加固不对称） | `if len(vs) >= _OBJ_MAX_VERTS` 只在 v 分支；vt/vn 分支无判断 |
| P-04 | mesh.py:198-199, 328-331, 361-374 | 错误模型 | 非数字 vt/vn 抛 `ValueError: invalid literal`（无文件/行号）；越界角点被静默丢弃 | `int(parts[1])` 不在 try 内；`idx = [c for c in idx if c is not None]` |
| P-05 | loom_texture.py:132-187, 197-205 | 资源边界 / 不变量 | `_gl_ctx_id = id(ctx)` 作缓存键；换 ctx 重建时不释放旧 GL 纹理 | `if self._gl_tex is not None and self._gl_ctx_id == id(ctx)`；无 release 调用 |
| P-06 | loom_texture.py:70-82 | 边界输入 | `np.asarray(..., uint8)` 对越界值静默回绕（非拒绝） | 无范围校验 |
| P-07 | loom_font.py:30-49, 103-139 | 契约 / 边界输入 | 零宽字符（U+200D 等）被判"有字形"并单独成段，emoji ZWJ 序列被拆散 | `adv_x > 0.5` 即判有字形；`split` 按 index 切段 |
| P-08 | loom_font.py:59-60, 103-119 | 不变量（回填：阶段一漏了"两个缓存键不同构"） | `_char_index` 按 (size,ch)，`_missing` 只按 ch；判定函数却随字号变化 | `self._char_index = {}` vs `self._missing = set()` |
| P-09 | loom_font.py:58, 62-98 | 资源边界 | 每字号缓存整条 freetype 字体链，无上限；契约称"进程级"，实现是实例级 | `self._chains[size] = chain` |
| P-10 | loom_raycast.py:176-178 vs 211-235 | 契约 / 接口 | 只有几何路径过滤 `visible`；物理路径不过滤 → auto 与 geometry 结果不同 | `if not m.visible: continue` 仅在 `_raycast_geom_all` |
| P-11 | loom_raycast.py:221-235 | 边界输入 / 错误模型 | 层不匹配循环上限 100，超过后静默返回 None | `for _ in range(100)` |
| P-12 | loom_raycast.py:256-275 vs 141-191 | 接口 | `raycast_all` 物理路径不去重（同模型多 collider 重复），几何路径去重 | 物理侧无 seen-model 集合 |
| P-13 | loom_raycast.py:17-19 vs 194-235 | 契约（回填：阶段一以为是文档笔误） | `backend='physics'` 无桥时文档承诺"返回 None + 警告"，实测零警告 | 函数体内无 print/warn |
| P-14 | loom_raycast.py:127-138 | 边界输入 | `layer_mask` 传 float/str → TypeError 逃出公开 API（无类型归一） | `(1 << lay) & layer_mask` |
| P-15 | layer_tag.py:70-84 vs 87-98 | 契约 / 资源边界 | `load()` 不校验 tag 字符集/长度，与 `validate_tag`+契约 §9 不一致 | `_normalize_tags` 只 strip/去重/截数量 |
| P-16 | layer_tag.py:158-174 | 错误模型 | `save` 失败被吞且注释称"下次启动重试"，实测重启即丢 | `except Exception: pass` |
| P-17 | layer_tag.py:135-139 vs 193-213 | 契约（回填：阶段一漏了参数传递链） | `reload(base)` 的 base 未传给 load → 静默忽略 | `_state()` 调 `load()` 不带 base |
| P-18 | layer_tag.py:177-182 | 边界输入 | `layer_name(1.9)` 走 int() 截断 = 1 号层 | `int(idx)` |
| P-19 | layer_tag.py:193-213 | 契约（回填：对照 C2 时发现） | 配置文件损坏只回退+落盘，**无控制台警告**（契约 C2 明确要求） | `load` 全函数 0 个 print |
| P-20 | audio_backend.py:68-93, 241-244 | 契约 | `mode` 永远不为 None，"两者皆失败→置不可用"未实现 | `_mode` 只被赋 'game_audio'/'pygame' |
| P-21 | audio_backend.py:61, 115-134, 229-239 | 资源边界 | `_handles` 无淘汰、shutdown 不清空；owner=id(组件) 使键随生命周期累积 | 无 pop/clear |
| P-22 | audio_backend.py:122-133, 229-239 | 契约 | shutdown 后：老键静默 no-op、新键走 pygame 回放 → 同一后端两套降级语义 | `_ensure()` 只看 `_init_done` |
| P-23 | audio_backend.py:65 | 资源边界 | 每实例注册 atexit 且不注销 | `atexit.register(self.shutdown)` |
| P-24 | loom_color.py:13-23 | 错误模型 / 边界输入 | 缺 `#` / 少一位的 hex 被静默解析成错误颜色（非文档声明的灰色回退）；8 位 hex 丢 alpha | `except Exception` 只覆盖真异常 |
| P-25 | loom_color.py:10-23 | 资源边界 | 缓存无上限，键为原始字符串（大小写重复计） | `_HEX_RGBA_CACHE[c] = t` |
| P-26 | mesh.py:156-179；loom_texture.py:207-213, 126-128；loom_raycast.py:26-29 | 可维护性 | 死代码：`mesh_validate` 无调用方；`Texture.bump_appearance`/`_is_default_white` 无读写方；`Point3D` import 未使用 | 全仓 grep 仅命中定义行 |

### 1.1 跳过登记（四类理由之一，防"检查过了"糊过去）

| 编号 | 位置 | 跳过理由（必须可外部审计） | 出处 |
|---|---|---|---|
| SKIP-01 | mesh.py:25-36 `_validate` 用 assert | 语言/工具规范 + 白盒契约：注释明写"运行/打包均不启用 -O, assert 始终生效" | mesh.py:26-27、C6 |
| SKIP-02 | mesh.py:39-76 `create_cube` 顶点/UV/绕序 | 白盒契约 + 探针：24 顶点/12 面/UV 对齐 24、`mesh_validate`=0.5、零面积面 0 | C6、tests/test_texture.py:118-125、p9 探针 |
| SKIP-03 | mesh.py:231-239 `_kdt_to_hex` | 白盒契约：`0..1 或 0..255` 两种 MTL 约定已被显式分支覆盖，且 clamp 到 [0,255] | mesh.py:222-239 |
| SKIP-04 | mesh.py:242-266 `_load_mtl_colors` | 错误模型契约："缺失/损坏返回 {}"，open 的 OSError 已捕获，解析异常已 pass | mesh.py:243-249 |
| SKIP-05 | mesh.py:203-219 `_resolve_idx` 负索引 | 探针：-1→末位、-n→首位、-(n+1)→None、越界→None 全部实测正确 | p1b 探针、mesh.py:203-219 |
| SKIP-06 | loom_texture.py:142-151 RGB/RGB565 行对齐 | 依赖探针：moderngl `Texture.write` 默认 `alignment=1`，三通道行天然无 4 字节对齐问题 | moderngl/__init__.py:842 `def write(self, data, viewport=None, level=0, alignment=1)` |
| SKIP-07 | loom_texture.py:107-114 `max_size` 缩放失败 | 白盒契约：注释明写"缩放失败 -> 用原尺寸"，且 tests/test_texture.py:247-249 已覆盖 | loom_texture.py:113-114、C8 |
| SKIP-08 | loom_texture.py:161-169 repeat/clamp 应用 | 工具自身声明：moderngl 仅暴露 repeat_x/repeat_y，无 MIRRORED_REPEAT，注释已声明 mirror 回退 repeat | loom_texture.py:159-160 |
| SKIP-09 | loom_font.py:141-156 `_render_segment`/`_measure_segment` 的宽异常捕获 | 白盒契约：注释"极端降级：空表面"，且空表面路径由 `render` 的 max(1,w) 兜底 | loom_font.py:141-156, 180-188 |
| SKIP-10 | loom_raycast.py:296-327 `_ray_from_screen` 行向量约定 | 依赖探针：与 editor.`_unproject` 在 4 个采样点逐位相等（最大偏差 0.0） | p4 探针 R7、editor.py:307-311 |
| SKIP-11 | loom_raycast.py:34-54 slab 边界语义 | 依赖探针 + 白盒契约：与 editor.`_ray_aabb` 同构，6 组退化输入实测一致 | p4 探针 R8、editor.py:323-341 |
| SKIP-12 | audio_backend.py:36-49 `_ga_open_path` | 工具自身声明：模块注释给出实测结论（GBK 窄路径 fopen），探针验证 '音效.wav'→GBK bytes | audio_backend.py:37-40、p7 A6 |
| SKIP-13 | audio_backend.py:140-156 `play` 恒返回 None | 白盒契约：C4 与 loom_components.py:435 明写"播放失败静默" | C4、loom_components.py:434-435 |
| SKIP-14 | audio_backend.py:120-133 失败 None 缓存 | 白盒契约：注释"已缓存 (None 也缓存, 防反复重试)" | audio_backend.py:122 |
| SKIP-15 | layer_tag.py:56-67 `_normalize_layers` | 契约 + 探针：越界键/非 str 值丢弃、补全 0~31、超长截断 32 全部实测 | C1、p6 L2 |
| SKIP-16 | layer_tag.py:101-115 原子写 | 工具自身声明 + 探针：`tmp + os.replace`，tests/_tmp/verify_config_fallback.py 已覆盖损坏回退 | layer_tag.py:102、C2 |
| SKIP-17 | loom_types.py:8-10 | 语言规范保证：单行 namedtuple 定义，无分支/无缓存/无 IO | loom_types.py:8-10 |
| SKIP-18 | loom_color.py:13-23 缓存命中路径 | 语言规范保证：`dict.get` 不抛 KeyError，命中直接返回 float 元组 | loom_color.py:15-16 |

---

## 2. 逐项裁决

### 2.1 P-PROVED（证伪失败 + 证真成功，共 26 项）

#### P-01（P1）scene JSON 里的 sphere.stacks=0/slices=0 让场景加载抛 ZeroDivisionError

1) **位置**：mesh.py:84-87（`phi = math.pi * i / stacks`、`theta = 2*math.pi*j/slices`）、mesh.py:129-145（`spec_to_mesh`）；承接方 sceneio.py:150-163。
2) **契约/预期**：C7 规定 `spec_to_mesh` 是"基元类型+参数→Mesh"的加载入口，唯一声明的失败是"未知基元类型 → ValueError"；承接方 sceneio.py:160-163 只兜 `(ValueError, TypeError)` 并"回退立方体"，即**任何坏参数都不得中断场景加载**（sceneio.py:151 注释"未知/坏参数/文件失效 -> 立方体兜底"）。
3) **路径枚举**：`spec_to_mesh('sphere', params)` 全部入口分支 = ①type 非 cube/sphere/plane → ValueError；②cube → `create_cube(params.get('size',1.0))`；③plane → `create_plane(w,d)`；④sphere → `create_sphere(r, stacks, slices)`，而 `create_sphere` 内部分支 = ④a `stacks>=1` 正常生成；④b `stacks<=0` → `range(stacks+1)` 迭代 i=0 时执行 `0/stacks` → **ZeroDivisionError**（stacks=0）或 `range` 为空（stacks<0）；④c `slices<=0` 同理在 `2*pi*j/slices` 处除零。路径 ④b/④c 在 sceneio 的 `except (ValueError, TypeError)` 之外——ZeroDivisionError 不是二者的子类，**无任何兜底路径可覆盖**。
4) **实际行为**：`spec_to_mesh('sphere', {'stacks': 0})` 抛 `ZeroDivisionError: float division by zero`；`sceneio._make_mesh({'type':'sphere','params':{'stacks':0}})` 原样抛出（未被兜底）。
5) **差异**：预期"坏参数 → 立方体兜底 + 场景继续"，实际"异常穿透到 `_apply_object` → `scene_from_dict` 中途中断"（同一类问题在 02_scene 报告 P-01 已就"场景半途中断"定级 P1）。
6) **触发条件**：任何 `{"type":"sphere","params":{"stacks":0}}` 或 `{"slices":0}` 的场景/预制体/关卡 JSON；也含 EAI 直接构造的同形参数。
7) **验证**：
~~~powershell
cd "$env:TEMP\loom_scan10"; python p1_mesh.py
~~~
实测输出：
~~~
  sphere   {'stacks': 0}            -> ZeroDivisionError: float division by zero
  sphere   {'slices': 0}            -> ZeroDivisionError: float division by zero
  {'stacks': 0}          -> sceneio 未接住 ZeroDivisionError: float division by zero
  {'slices': 0}          -> sceneio 未接住 ZeroDivisionError: float division by zero
~~~
8) **影响与等级**：P1（功能错误/加载中断）。修复方向：`spec_to_mesh` 把非法栈数/切片数归一为 `ValueError`（或钳到 ≥1），使 C7 的"唯一异常类型"成立；sceneio 侧兜底加 ZeroDivisionError 属治标。

#### P-02（P2）负 stacks/slices 生成 0 顶点空网格并被 `_validate` 全绿放行

1) **位置**：mesh.py:79-113、mesh.py:25-36。
2) **契约/预期**：C6 的不变量只有"面数=颜色数 / 索引越界 / 顶点三维 / 法线UV数一致"，`Mesh` 构造成功即被视为可渲染网格；`create_sphere` 的文档是"UV 球体: (stacks+1)*(slices+1) 唯一顶点, 2*stacks*slices 面"。
3) **路径枚举**：`create_sphere(r, st, sl)` 顶点循环 `for i in range(st+1)`：st=-1 → 空；片循环 `for j in range(sl+1)`：sl=-1 → 空；面循环 `for i in range(st)` / 内部 `range(sl)` 同为 0 次 → vertices=[]、faces=[]、face_colors=[] → `Mesh._validate` 三个 assert 全部在空集上成立（`len(faces)==len(colors)` 0==0、`for f in []` 不迭代、`all(...)` 于空集为 True、normals/uvs 非 None 时 `len==0==nv` 成立）。**无任何路径会拒绝空网格**。
4) **实际行为**：`create_sphere(1.0, -1, 28)` → V=0 F=0 colors=0 且构造成功；`spec_to_mesh('sphere', {'stacks': -1})` 返回该空网格。
5) **差异**：预期"退化参数应报错或钳制"，实际"静默产出空网格，被当作正常基元接受并挂进场景"（SEM-SILENT）。
6) **触发条件**：场景 JSON 中 `stacks/-slices` 为负；或脚本直接调用。
7) **验证**：p1b_mesh.py 输出 `create_sphere(1.0, -1, 28) -> V=0 F=0  colors=0`、`spec_to_mesh((-1 stacks)) 返回空网格`。下游渲染/GI 行为未验证（需 GL），见 2.3 U-02。
8) **影响与等级**：P2（边界/静默失败；本模块无法判定下游是"不可见对象"还是渲染期异常，故不升 P1）。

#### P-03（P2）OBJ 资源上限只护 v/f，vt/vn 无上限（DoS 加固不对称）

1) **位置**：mesh.py:184-186（`_OBJ_MAX_VERTS=1_000_000`、`_OBJ_MAX_FACES=2_000_000`）、mesh.py:304-320（v 有上限、vt/vn 无）。
2) **契约/预期**：C7 声明这两个常量用于"恶意超大文件内存 DoS 防护"，对象是**整个 .obj 文件的内存占用**；C8 的既有测试 `OBJ 顶点超限抛 ValueError (资源上限)` 只覆盖 v。
3) **路径枚举**：`load_obj` 的行分类路径共 7 条：v / vt / vn / mtllib / usemtl / f / 其它。其中只有 v（304-310）与 f（325-331）在 append 前检查上限；**vt（311-315）与 vn（316-320）直接 append**，无任何计数或文件大小前置检查（`open` 也不看 size）。
4) **实际行为**：`vs`、`vts`、`vns` 三个列表对 vt/vn 行数没有上限；每行 `vt` 生成一个 2 元 float 元组、`vn` 生成 3 元 float 元组并常驻内存至函数结束。
5) **差异**：预期"顶点/法线/UV 解析均受资源上限保护"，实际"vt/vn 可无限增长，恶意文件可绕过防护"。
6) **触发条件**：一个含 >1e6 行 `vt`/`vn`、但 `v`/`f` 行数很小的 .obj（极易构造，且体积远小于等量顶点数）。
7) **验证**：p1b_mesh.py 的源码自检输出 `_OBJ_MAX_VERTS 用于 v 分支: True / vt/vn 分支是否含上限: False`；静态证据 mesh.py:311-320 无 `_OBJ_MAX` 引用。
8) **影响与等级**：P2（资源边界/安全加固不完整，触发需恶意资产，不构成崩溃）。

#### P-04（P3）`_parse_face_corner` 对非数字 vt/vn 抛裸 ValueError；越界角点静默丢弃

1) **位置**：mesh.py:189-200、328-329、361-374。
2) **契约/预期**：C7 只声明"失败（无顶点/无面/文件错）抛 ValueError"；解析层的容错约定见 `_parse_face_corner` 文档"解析失败返回 None"。
3) **路径枚举**：`_parse_face_corner` 分支 = ①空 token → None；②`int(parts[0])` 失败 → None（在 try 内）；③`parts[1]` 存在 → **不在 try 内**；④`parts[2]` 存在 → **不在 try 内**。路径 ③/④ 遇非数字即抛 `ValueError: invalid literal for int()`。另一侧：`load_obj` 在 362-365 把 `_resolve_corner` 返回 None 的角点**过滤掉**，若剩 <3 个则整面 `continue`。
4) **实际行为**：`_parse_face_corner('1/x/3')` 与 `'1/2/y'` 抛 ValueError；`load_obj` 对含 `1/x/1` 的文件抛同异常（不含文件名/行号）；`f 1 2 99` 被静默丢弃后该面消失。
5) **差异**：预期"解析失败 → None → 该面跳过/兜底"，实际"①异常穿透（消息不可定位）②越界角点静默改几何"。
6) **触发条件**：非标准/损坏 .obj（导出器混用 `v/vt/vn` 与 `v//vn`、或模型带非法索引）。
7) **验证**：p1b_mesh.py 输出 `'1/x/3' -> RAISE ValueError`、`load_obj -> ValueError: invalid literal for int() with base 10: 'x'`、`越界角点 -> OK F=1`。
8) **影响与等级**：P3（上游 sceneio 会 catch ValueError 回退立方体，用户看到的是"导入失败/模型缺失"而非崩溃；editor.py:695 的导入路径同样只 catch 部分异常——属 06 范围，仅登记）。

#### P-05（P2）贴图 GPU 资源：`id(ctx)` 作缓存键 + 换上下文重建时不释放旧纹理

1) **位置**：loom_texture.py:132-187（`ensure_gl`）、197-205（`release`）。
2) **契约/预期**：模块契约（loom_texture.py:8）"GL 资源归属创建时的 context (与桶几何同纪律)；release 由引擎清场统一调"；`ensure_gl` 文档"在 ctx 上创建/上传 GPU 纹理（含 mipmap）。已有则直接返回"。
3) **路径枚举**：`ensure_gl(ctx)` 三条路径 = ①`_gl_tex` 非空且 `_gl_ctx_id == id(ctx)` → 直接返回（不新建、不释放）；②`_gl_tex` 非空但 ctx 不同 → 走 140-186 新建并**直接覆盖** `self._gl_tex`（旧纹理无 release 调用）；③`_gl_tex` 为空 → 新建。①②③ 均无"先释放旧纹理"分支；`release()` 只由外部显式调用。路径 ① 的判定是**地址相等**而非对象身份/holder 存活。
4) **实际行为**：假 ctx 探针：A.ensure_gl→B.ensure_gl，A 的纹理所记录 `released` 计数恒为 0，连续 5 次切换每次都新建一张且旧的一张永不释放；`id(ctx)` 地址复用未能在 5000 次分配内复现（见 2.3 U-01）。
5) **差异**：预期"同一纹理资产在上下文切换时安全重建并回收旧 GPU 资源"，实际"漏回收 + 缓存键是可能被复用的地址"。
6) **触发条件**：同一进程内创建/切换多个 GL 上下文（`tests/test_texture.py:152,232,253` 三个 standalone ctx；编辑器 GL↔VK 切换或远程离屏窗口重建 `ui/loom_gui.py:166,519`），并对同一 `Texture` 资产再次 `ensure_gl`。
7) **验证**：p2_texture.py 的 T2 段：
~~~
  A.textures=1 B.textures=1
  旧纹理(A) released 次数 = 0  → 期望 >=1
  → 判定: BUG(每次换 ctx 泄漏一张 GPU 纹理, 从不 release)
~~~
8) **影响与等级**：P2（资源生命周期；单上下文进程不触发，多上下文/切 API 时显存随切换次数线性增长；`loom_cubemap.py:123,147` 同款需联动修）。

#### P-06（P3）`from_rgba` 对越界像素值静默回绕

1) **位置**：loom_texture.py:70-82。
2) **契约/预期**：`from_rgba` 文档"rgba 必须是 (H,W,4) uint8，收到 %r"——只声明形状契约，未声明取值契约；`__init__` 直接保存数组。
3) **路径枚举**：①形状不符 → ValueError；②尺寸不符 → ValueError；③**形状尺寸都对但 dtype/取值越界 → np.asarray(dtype=uint8) 静默 cast**（numpy 语义：模 256 截断）。
4) **实际行为**：`T.from_rgba(1,1,[[[300,-5,70000,255]]])` → 存储 `[[[44, 251, 112, 255]]]`（300%256=44、-5→251、70000%65536→4464%256=112）。
5) **差异**：预期"越界值被拒绝或钳制"，实际"模 256 回绕成完全不同的颜色"（SEM-SILENT）。
6) **触发条件**：脚本/EAI 用 0~255 之外的分量（如 float 0~1 的 1.0 传进 int 通道、或 255.5 四舍五入成 255）。
7) **验证**：p2_texture.py T3 段输出上述存储值。
8) **影响与等级**：P3（需调用方给错量纲；本模块无写帧缓存以外的后果）。

#### P-07（P2）emoji ZWJ 序列被拆段：零宽连接符被当成"有字形"，插入 12px 空隙

1) **位置**：loom_font.py:30-49（`_has_glyph`）、103-139（`char_index`/`split`）、158-188（`render`）。
2) **契约/预期**：C3「从左到右查，**第一个有该字形的字体胜出**」+「§2.5.3 渲染结果与逐字符渲染视觉一致」+「支持全 UTF-8（含 emoji）」；`_has_glyph` 自身文档"adv_x > 0 说明有实际宽度"。
3) **路径枚举**：`split` 对每个字符走 `char_index`，后者逐链查 `_has_glyph`：①某字体 adv_x>0.5 → 该字体胜出；②全链都 ≤0.5/None → 记 missing → 回落 0 号（主字体）。零宽字符（U+200D ZWJ）实际数据：seguiemj adv=0.0（判 False）、msgothic 报 adv=12（判 True）→ 命中路径 ①，被当作**独立字形**切段。
4) **实际行为**：`split('👨\u200d👩\u200d👧', 24)` → `[(1,'👨'), (4,'\u200d'), (1,'👩'), (4,'\u200d'), (1,'👧')]`；msgothic 渲染 ZWJ 得 `surf=(12, 0)`（零墨迹但 12px 宽）；整串 `render` 宽度 92px，单个 emoji 仅 ~27px。
5) **差异**：预期"ZWJ 应黏在前一簇内、不产生宽度"，实际"每两个 emoji 之间插入 12px 空白，序列语义被破坏"（family/旗帜等复合 emoji 拆成多个独立字形）。
6) **触发条件**：任何含 U+200D / 零宽选择符的文本（emoji 家庭、彩虹旗、职业组合 emoji）；`'❤️'` 因 seguiemj 的 VS16 adv=27 恰好不断裂，属运气而非设计。
7) **验证**：p3c_zwj.py 实测输出即上表（含 `idx=4 font=msgothic.ttc seg='\u200d' surf=(12, 0)`）；对照 p3b E1 的 adv 数据。
8) **影响与等级**：P2（UI 文本契约 §2.5 的"全 UTF-8 显示"在复合 emoji 上不成立；修复需"零宽/变体选择符不作为分段边界"）。

#### P-08（P2）`_missing` 与 `_char_index` 键不同构：某字号的一次误判永久污染所有字号

1) **位置**：loom_font.py:59-60（缓存定义）、103-119（`char_index`）、30-49（`_has_glyph`）。
2) **契约/预期**：C3 §2.5.2 给出的缓存模型是 `_char_font_map: dict[str,int]` + `_char_font_missing: set[str]`（**按字符**），后置条件"get_metrics 调用次数 = 首次遇到的不同字符数，之后恒为 0"；实现侧 `_has_glyph` 的判据 `adv_x > 0.5` 却**随字号缩放**（实测：space 在 size=1 时 adv=0.0 → False，size=2 起 adv≥1.0 → True）。
3) **路径枚举**：`char_index(ch, size)` 四条路径 = ①`_char_index[(size,ch)]` 命中 → 返回（按字号）；②`ch in _missing` → 直接 -1（**跨字号**）；③逐链查到 → 写 `(size,ch)`；④逐链查不到 → 写 `_missing`（**只记字符**）。②与③的键空间不同构，且④的判定依赖 size。
4) **实际行为**：同一字符在 size=8 被判无字形后，size=40 直接命中②返回 -1（不查已加载的 40 号字体链）；换成从未在 8 号查过的字符则正常返回 0。合成字体探针：`char_index('中',8)=-1` → `char_index('中',40)=-1`，而 `char_index('文',40)=0`。
5) **差异**：预期"判定结果与字号无关（C3 的字符级缓存）或缓存也按字号分键"，实际"判定依赖字号、缓存不按字号 → 结果自相矛盾"。
6) **触发条件**：同一进程内同一字符先在"判 False"的字号被查询（小字号/字体覆盖带边界/某字体 get_metrics 偶发异常），再在大字号渲染。真实字体下最常见的触发是零宽字形（adv=0.0，见 P-07 的 ZWJ）。
7) **验证**：p3_font.py F2 段：
~~~
  char_index('中', 8)  = -1
  char_index('中', 40) = -1   (_chains[40] 明明有字形)
  _missing 内容 = {'中'}
  split('中', 40)     = [(0, '中')]  -> 落到主字体 index 0 (显示方块)
  → 对照: 换个从未在 size=8 查过的字符 '文' at size=40: char_index('文', 40) = 0
~~~
8) **影响与等级**：P2（出现即"永久方块"，且进程内不可恢复；探针用合成字体证明机制，真实触发条件见 2.3 U-03 的裁决点）。

#### P-09（P3）字体链按字号无上限缓存，且"进程级"名不符实

1) **位置**：loom_font.py:52-98（`__init__`/`_load_chain`）、`loom_hud.py:38`、`vk_ui.py:122`。
2) **契约/预期**：类文档"按字号惰性加载, **字符索引进程级缓存**"；C3 §2.5.2"缓存失效：进程级永久有效"。
3) **路径枚举**：`get_chain(size)` 只有"命中 `_chains[size]`"与"新建整条链"两条路径，`_chains` 无淘汰、无上限；每个 `FontChain` 实例各自持有一份（两处模块级单例 → 两份）。
4) **实际行为**：300 个不同字号 → `_chains` 300 条，每条 6 个 `pygame.freetype.Font`（含文件句柄）。字符缓存是实例级（`self._char_index`），不是"进程级"。
5) **差异**：预期"进程级缓存省重复查询"，实际"每实例一份 + 字号维度无界"（两处 UI 各自付费，字号越多越多）。
6) **触发条件**：UI 使用任意字号（如平滑缩放字号、每帧按窗口比例算字号）。
7) **验证**：p3_font.py F4 段 `300 个不同字号 -> _chains 条目数 = 300`。
8) **影响与等级**：P3（内存/句柄增长，量级小；契约措辞漂移一并登记）。

#### P-10（P2）射线检测双后端对 `visible` 语义不一致

1) **位置**：loom_raycast.py:176-178（几何路径过滤 `m.visible`）vs 211-235（物理路径无 visible 判断）。
2) **契约/预期**：C5 定义 `backend='auto'`（有物理桥走物理，否则几何）只是"后端选择"，**没有声明两条路径可以返回不同集合**；`raycast` 文档"返回最近命中的物体"，`raycast_all`"返回所有命中"。
3) **路径枚举**：`raycast` 两条顶层路径 = ①`use_phys`（backend 强制或 auto+桥可用）→ 只做 `_layer_match`，**不看 `m.visible`**；②几何 → `_raycast_geom_all` 内 `if not m.visible: continue`。故同一世界状态下可见性不同的模型，①②结果必然分叉；`auto` 走 ①。
4) **实际行为**：假桥探针：`physics → ('隐藏', 450.0)`、`geometry → ('可见', 4.5)`、`auto → ('隐藏', 450.0)`。即 `visible=False` 的物体在物理可用时**可被 raycast 命中**，几何回退时**不可命中**。
5) **差异**：预期"两条后端对同一 API 语义等价（至少对过滤规则一致）"，实际"可见性过滤只存在于回退路径"。
6) **触发条件**：Culverin 可用（`physics_bridge.cv_available=True`）且场景中有 `visible=False` 物体挡在射线上；EAI/GUI 拾取在此配置下会选中隐藏物体。
7) **验证**：p4_raycast.py R2 段（输出见上）。
8) **影响与等级**：P2（后端一致性/功能语义；"隐藏物体是否应可被射线命中"需人类裁决，见 §5 Q1）。

#### P-11（P2）物理路径层过滤循环上限 100 → 第 101 个目标被静默漏检

1) **位置**：loom_raycast.py:221-235。
2) **契约/预期**：C5 `raycast` 文档"返回最近命中的物体"、`layer_mask` 文档"位掩码过滤（bit i 表示 layer i；0 = 全不匹配）"——层过滤是**语义过滤**，不应有"最多尝试 N 个候选"的隐藏上限。
3) **路径枚举**：`use_phys` 且 `layer_mask` 非 None 时：for 循环最多 100 次，每次 `_raycast_phys(..., ignore=上一个 handle)`；循环体路径 = ①返回 None → 返回 None；②handle 未登记 → 返回 None；③层匹配 → 返回命中；④层不匹配 → `ignore=handle` 继续。循环耗尽（第 101 个候选才匹配）→ **落到 `return None`**。
4) **实际行为**：100 个 layer0 遮挡 + 1 个 layer1 目标、`layer_mask=bit1` → `raycast = None`（目标明明在射线上且匹配）。
5) **差异**：预期"过滤只改变命中集合、不改变可达性"，实际"候选数 >100 时结果被截断且无任何告警"。
6) **触发条件**：密集场景（500 球压测这类场景很常见）+ 层过滤 + 目标位于大量不匹配物体之后。
7) **验证**：p5_raycast2.py R9 段输出 `-> None`。
8) **影响与等级**：P2（功能错误；上限本身是防死循环的合理手段，问题是"耗尽后静默返回 None"而非告警/回退几何路径）。

#### P-12（P2）`raycast_all` 物理路径不去重，几何路径去重

1) **位置**：loom_raycast.py:256-275（物理）vs 141-191（几何）。
2) **契约/预期**：C5 `raycast_all`"返回所有命中（按距离升序）"——"所有命中"的粒度应是**物体**（返回元素是 `(model, distance, hit_point)`，并已按距离排序，语义上是一物一条）。
3) **路径枚举**：物理侧每条 handle 一次 `results.append`，只用 `seen` 防止**同一 handle** 重复，没有"同一 model 多 handle"的去重；几何侧每个 model 只算一次 AABB → 天然一物一条。故同一模型挂多个 collider 时两侧条数不同。
4) **实际行为**：同一模型两个 handle → `raycast_all(physics) = [('可见', 200.0), ('可见', 500.0)]`，`raycast_all(geometry) = [('可见', 4.5)]`（另外两侧距离语义也不同，见 2.3 U-04）。
5) **差异**：预期"同一物体在结果里只出现一次"，实际"物理路径按 collider 重复计数"。
6) **触发条件**：一个 GameObject 挂多个碰撞体（`physics_bridge._entries` 多 handle），或复合碰撞体。
7) **验证**：p4_raycast.py R5 段（输出见上）。
8) **影响与等级**：P2（后端一致性；调用方若做"第一个/全部"逻辑会拿到重复项）。

#### P-13（P3）文档承诺的"无桥 + 警告"不存在；handle 未登记直接放弃

1) **位置**：loom_raycast.py:17-19（backend 说明）、228-230（未登记直接 return None）。
2) **契约/预期**：C5 `'physics' 强制物理 (无桥返回 None + 警告)`。
3) **路径枚举**：`raycast` 全函数分支 = backend 解析、ignore_handle 反查、物理循环、几何回退；**没有任何 print/logging/warnings 分支**（源码自检 `'print(' in src or 'warn' in src` = False）；未登记 handle 路径 = `if model is None: return None`（而非 `continue`）。
4) **实际行为**：`backend='physics'` 无桥 → 返回 None，stdout 为空；未登记 handle 5 后有合法 handle 6 → 仍返回 None。
5) **差异**：预期"无桥时警告（可诊断）+ 跳过未登记 handle 继续找"，实际"完全静默 + 提前放弃"。
6) **触发条件**：物理桥未就绪（编辑器静态态、Culverin 缺失）而脚本/ EAI 强制 `backend='physics'`；桥内部 `_entries` 与 `_w` 短暂不一致。
7) **验证**：p4_raycast.py R6（`stdout = ''`、源码自检 False）、p5_raycast2.py R10（`None`）。
8) **影响与等级**：P3（可诊断性/边界；不产生错误结果，只产生"无解释的 miss"）。

#### P-14（P3）`layer_mask` 非整型 → TypeError 逃出公开 API

1) **位置**：loom_raycast.py:127-138。
2) **契约/预期**：`layer_mask` 文档"位掩码（bit i 表示 layer i；None/负数 = 不限；0 = 全不匹配）"，未声明可抛异常；EAI 层已做 `int()` 归一（agent_commands.py:2545-2550），说明"外部输入需要归一"是已知前提。
3) **路径枚举**：`_layer_match` 三条路径 = ①None/负数 → True（`<` 比较在 str 上抛 TypeError）；②`0<=lay<=31` → `(1<<lay) & mask`（float 上抛 TypeError）；③越界 lay → False。归一分支缺失。
4) **实际行为**：`layer_mask=1.0` → `TypeError: unsupported operand type(s) for &: 'int' and 'float'`；`'3'` → `TypeError: '<' not supported`。
5) **差异**：预期"非法类型按契约拒绝/归一"，实际"异常穿透 `raycast` 到调用方"。
6) **触发条件**：脚本传 float（如从 JSON 读回的 1.0）或字符串。
7) **验证**：p4_raycast.py R3 段（输出见上）。
8) **影响与等级**：P3（EAI 入口已归一，直接 Python/MCP 之外的调用才会触发）。

#### P-15（P2）`load()` 不校验 tag 的字符集/长度（与 `validate_tag`、契约 §9 不一致）

1) **位置**：layer_tag.py:70-84（`_normalize_tags`）vs 87-98（`validate_tag`）、契约 C1。
2) **契约/预期**：C1「Tag 长度 ≤64 / 字符集 字母、数字、下划线、中文 / 数量 ≤1000」是**资源边界**（§9），`register_tag` 路径已强制；§3.2 把校验放在注册入口。
3) **路径枚举**：tag 进入注册表只有两条路径 = ①`register_tag`（`validate_tag` 全量校验：非空/≤64/正则）；②`load()` → `_normalize_tags`（只 `strip`、大小写去重、数量截断）。路径 ② 无长度与字符集校验，且 `save()` 会把它原样回写。
4) **实际行为**：文件里写 `['has space','x'*100,'bad/slash','㐀']` → 加载后这些 tag 全部在注册表中（`validate_tag` 对它们全为 False）；长度 100 的 tag 不被截断。
5) **差异**：预期"注册表内的 tag 恒满足 §9 资源边界"，实际"外部文件可注入越界 tag 并被回写/应用到物体"。
6) **触发条件**：手改/迁移/旧版本写坏的 `layer_tag.json`；第三方工具生成。
7) **验证**：p6_layertag.py L1 段（输出见上）。
8) **影响与等级**：P2（资源边界可被外部数据绕过；GUI 下拉框会出现超长/带空格条目，序列化后进场景）。

#### P-16（P2）`register_tag` 吞掉落盘失败，注释承诺的"下次启动重试"不存在

1) **位置**：layer_tag.py:158-174（`except Exception: pass` 与注释"落盘失败不阻断内存注册 (下次启动重试)"）。
2) **契约/预期**：C1 §3.2 第 2 步"通过 → **写入 layer_tag.json 的 tags 数组** + 应用到物体"；本函数文档"注册新标签; 已存在返回 False (幂等)"。
3) **路径枚举**：`register_tag` 分支 = ①非法 → ValueError；②已存在 → False；③超上限 → ValueError；④正常 → append 内存 + `save`（成功 → True；失败 → **pass → 仍返回 True**）。路径 ④ 的"失败"分支没有任何上报，也没有任何地方记录"待重试"状态（模块内无重试逻辑，`load()` 只读磁盘）。
4) **实际行为**：`register_tag('Enemy', base=<一个文件路径>)` → True，内存 `tag_exists` = True，磁盘无文件；模拟重启 `load()` → 不含 'Enemy'。
5) **差异**：预期"注册成功 = 已持久化，或明确报错"，实际"返回成功但磁盘没有，重启即丢且无提示"。
6) **触发条件**：程序目录不可写（安装到 Program Files、只读共享盘、杀毒锁定）时用户新增 tag。
7) **验证**：p6_layertag.py L4 段（输出见上）。
8) **影响与等级**：P2（数据丢失 + 静默；契约 §3.2 的持久化承诺不成立）。

#### P-17（P2）`reload(base=...)` 的 base 参数被静默忽略

1) **位置**：layer_tag.py:135-139（`reload`）、126-132（`_state`）、193-213（`load`）。
2) **契约/预期**：`reload` 文档"强制重新从磁盘加载 (测试/外部改动后使用)"，签名带 `base` 参数；配套的 `load(base)`/`save(..., base)`/`register_tag(..., base)` 都真的使用 base（`config_path(base)`）。
3) **路径枚举**：`reload(base)` → 置 `_STATE=None` → `_state()` → `load()`（**不带 base**）→ `config_path(None)` = `program_dir('loom', None)` = `sys.argv[0]` 所在目录。唯一路径即"忽略 base"；不存在"把 base 传给 _state"的分支（`_state()` 签名无参数）。
4) **实际行为**：两个目录 A/B 各放不同 `layer_tag.json`，`reload(base=A)` 后 `get_layers()[0] = 'Default'`（默认目录内容），期望 'A层'；`get_tags()` 同理不含 'TagA'。
5) **差异**：预期"reload(A) 从 A 重载"，实际"永远从默认目录重载"（死参数）。
6) **触发条件**：任何用 base 做隔离的调用（单测、多项目切换、EAI 指定目录）。
7) **验证**：p6_layertag.py L3 段（输出见上）。
8) **影响与等级**：P2（测试隔离/多实例场景失效；生产默认路径恰好相同所以线上暂不暴露）。

#### P-18（P3）`layer_name(1.9)` 走 int() 截断

1) **位置**：layer_tag.py:177-182。
2) **契约/预期**：`layer_name(layer_id)` 文档"层编号 -> 层名 (未命名/越界返回空串)"；`layer_id` 是整数域（C1 0~31）。
3) **路径枚举**：①`int(idx)` 成功 → `dict.get`；②`int` 抛 TypeError/ValueError → ''。float 走 ①（截断），不属"越界"。
4) **实际行为**：`layer_name(1.9) = 'TransparentFX'`（被当成 1 号层），而非空串/报错。
5) **差异**：预期"非整数编号不匹配层表"，实际"静默四舍五入到相邻层"。
6) **触发条件**：UI/脚本传入 float。
7) **验证**：p6_layertag.py L6 段。
8) **影响与等级**：P3（显示层错位一格，不影响存储的不变量）。

#### P-19（P2）配置文件损坏只静默回退+覆盖，缺少契约要求的控制台警告

1) **位置**：layer_tag.py:193-213（`load`，全函数 0 个 print——`Select-String print\(` 计数 = 0）。
2) **契约/预期**：C2「文件损坏 → 回退默认值 **+ 控制台警告**，不阻止启动」（§3.1 错误处理、§8 错误模型汇总两处都写了"警告"）。
3) **路径枚举**：`load` 分支 = ①读文件异常 → `d=None`；②非 dict → `d=None`；③`d is None` → `save(默认)`（失败则 pass）→ 返回默认值；④正常 → normalize。路径 ③ 无任何输出；且它会把损坏文件**直接覆盖**成默认值。
4) **实际行为**：损坏文件被静默替换为默认内容，stdout 无输出；用户原有的自定义层名/tag 一次性丢失且不可恢复（若损坏文件其实可手工修复）。
5) **差异**：预期"回退 + 明确告警（用户有机会去备份/修复）"，实际"静默覆盖"。
6) **触发条件**：`layer_tag.json` 被写坏（磁盘满、并发写、手工编辑语法错）。
7) **验证**：p6 探针（tests/_tmp/verify_config_fallback.py 只断言"不崩"，不断言警告）+ `Select-String print(` 计数 0。
8) **影响与等级**：P2（数据丢失不可逆 + 契约 C2 未满足；修复方向：先备份 `.bak` 再落默认，并按契约打印警告）。

#### P-20（P3）`AudioBackend.mode` 永远不可能为 None（"两者皆失败→置不可用"未实现）

1) **位置**：audio_backend.py:68-93（`_ensure`）、241-244（`mode` property）。
2) **契约/预期**：C4 模块文档"auto = ga 成功用它, 否则 pygame; **两者皆失败 → 置不可用**，一切操作静默 no-op"；`mode` 文档"'game_audio' | 'pygame' | None. (诊断/测试用)"、`_mode` 注释"None(=不可用)"。
3) **路径枚举**：`_ensure` 只把 `_mode` 赋成 `'game_audio'` 或 `'pygame'`（want 不合法也落到 'pygame'）；全文件没有把 `_mode` 置回 None 的分支。即使 pygame 也不可用，`_mode='pygame'`、`_ensure()=True`。
4) **实际行为**：主后端初始化抛异常 + `_get_py` 返回 None → `_ensure() = True`、`mode = 'pygame'`、`load = None`（"不可用"只能靠 load 返回 None 间接推断）。
5) **差异**：预期"mode 能报告不可用状态"，实际"状态机缺一档"（诊断/测试无法区分"pygame 可用"与"全都不可用"）。
6) **触发条件**：无声卡/无 pygame.mixer 设备且 game_audio 加载失败的机器（CI/服务器/被禁用的音频）。
7) **验证**：p8_audio2_color.py A1' 段（输出见上）。
8) **影响与等级**：P3（诊断语义/契约漂移，不影响播放正确性）。

#### P-21（P2）音频句柄缓存无淘汰、shutdown 不清空

1) **位置**：audio_backend.py:61（`_handles`）、115-134（`load`）、229-239（`shutdown`）；调用方 `loom_frame_components.py:63,65,67,78` 用 `owner=id(a)`。
2) **契约/预期**：C4"句柄缓存: (path, owner) -> 句柄 … owner=组件身份 (id 组件), 同 clip 多组件各自独立音量"；`shutdown` 文档"关闭设备 (幂等)"。
3) **路径枚举**：`load` 的写入口唯一（`self._handles[key] = ent`），全文件无 `pop/del/clear`；`shutdown` 只 `_mgr=None`，不动 `_handles`。故缓存条目数 = 历史上出现过的不同 `(path, 组件地址)` 组合数，单调不减。
4) **实际行为**：2000 个不同 owner 的 load → `_handles` 2000 条，ga 侧分配 2002 个句柄（原生内存），无任何回收；shutdown 后条目仍在。
5) **差异**：预期"组件销毁后其句柄缓存可回收"，实际"永久驻留（含原生句柄），只能靠进程退出"。
6) **触发条件**：长时间运行 + 频繁生成/销毁带 AudioSource 的物体（子弹、特效、敌人）；每次新地址就多一条。
7) **验证**：p7_audio.py A3 段（`_handles 条目 = 2000`）、p8_audio2_color.py A4' 段（shutdown 后残留 1）。
8) **影响与等级**：P2（资源生命周期/内存与原生句柄增长；地址复用还会让"各自独立音量"的承诺失效，见 2.3 U-01）。

#### P-22（P3）shutdown 后同一后端出现两套降级语义

1) **位置**：audio_backend.py:122-133（`load`）、229-239（`shutdown`）。
2) **契约/预期**：C4"NotInitializedException = shutdown 后调用 → 引擎正常路径不触发, **静默**"（同一句柄语义）。
3) **路径枚举**：shutdown 后 `load(path)` = ①key 已缓存 → 直接返回旧 ga 句柄（后续 `play` 里 `self._mgr.xxx` → `AttributeError` → 被 `except` 吞 → 静默）；②key 未缓存 → `_ensure()` 仍 True → `self._mgr.load_sound` → AttributeError → `_py_fallback` → **若 pygame 可用则真的播放**。
4) **实际行为**：老路径静默不播、新路径走 pygame 回退（探针确认走了 `_py_fallback`）；退出流程中被延迟触发的音效可能在 shutdown 之后经 pygame 发声。
5) **差异**：预期"shutdown 后一切静默"，实际"一半静默、一半换后端继续播"。
6) **触发条件**：退出链里仍有余留的 `update_audio` 帧/延迟事件；或测试在 shutdown 后继续 play。
7) **验证**：p8_audio2_color.py A4' 段（`play 已缓存路径 -> None`）+ p7_audio.py A4 段（`shutdown 后 load 新文件 -> 走了 pygame 回退? True`）。
8) **影响与等级**：P3（生命周期语义；不会崩，但"必须 shutdown"的铁律被削弱成"shutdown 后可能还有声音"）。

#### P-23（P3）每个 AudioBackend 实例注册 atexit 且不注销

1) **位置**：audio_backend.py:65。
2) **契约/预期**：C4"引擎退出链调用 + atexit 兜底"——兜底是**引擎级一个**守护，不是每实例一份。
3) **路径枚举**：`__init__` 无条件 `atexit.register(self.shutdown)`；`shutdown` 不 `atexit.unregister`；无"已注册"判重。
4) **实际行为**：创建 5 个 `AudioBackend` → atexit 回调 +5，且每个实例被 atexit 强引用到进程结束（`_mgr`/句柄随之驻留）。
5) **差异**：预期"一个兜底"，实际"每实例一份、只增不减"。
6) **触发条件**：测试批量创建 `AudioSystem`（tests/test_audio.py 建了 6 个）；编辑器多次重建引擎。
7) **验证**：p7_audio.py A5 段（`atexit 回调 +5`）。
8) **影响与等级**：P3（内存/退出顺序；shutdown 幂等所以不会重复关设备）。

#### P-24（P3）`_hex_rgba` 对"缺 #/少位/带 alpha"三种输入的静默误解析

1) **位置**：loom_color.py:13-23。
2) **契约/预期**：`_hex_rgba` 文档"'#RRGGBB' -> (r,g,b,alpha=1.0) float 元组 (**失败回退灰色 .5**)"。
3) **路径枚举**：①6 位带 `#` → 正确；②任意长度 ≥7 的字符串 → 取 `[1:3]/[3:5]/[5:7]` 解析（**不校验长度与 `#` 前缀**）；③解析异常 → 灰色。故"缺 #"与"少一位"都走 ② 而不是 ③。
4) **实际行为**：`'FF0000'` → `(0.941, 0, 0, 1)`（把 'F0' 当红色通道）；`'#FF000'` → `(1.0, 0, 0, 1)`（'0' 解析成 0）；`'#FF000080'` → alpha 被丢弃成 1.0；只有 `'red'/''/None/123/'#GGGGGG'/'#FF0000'(前导空格)` 才回落灰色。
5) **差异**：预期"非 #RRGGBB 一律灰色兜底"，实际"部分畸形输入被解释成看似合法的错误颜色"。
6) **触发条件**：场景/材质/EAI 传入不带 # 或 8 位带 alpha 的颜色串（`agent_commands.parse_color` 是另一套实现，明确支持 8 位 alpha，两套语义不一致）。
7) **验证**：p8_audio2_color.py C1 段（输出见上）。
8) **影响与等级**：P3（颜色错但不崩；与 agent_commands.parse_color 语义分叉一并登记）。

#### P-25（P3）颜色缓存无上限且按原始字符串分键

1) **位置**：loom_color.py:10-23。
2) **契约/预期**：注释"hex 颜色转 rgba 的转换 + 缓存"，目的是避免重复解析（`loom_model_gpu.py:152` 每模型调用一次）。
3) **路径枚举**：`_HEX_RGBA_CACHE.get(c)` → 未命中即写入，键 = 原始入参（含大小写/空格/非法值），无淘汰、无归一化。
4) **实际行为**：2000 个不同颜色串 → 2013 条缓存；`'#FF0000'` 与 `'#ff0000'` 各占一条（值相同）。
5) **差异**：预期"按颜色值缓存"，实际"按字面量缓存"（重复解析 + 无界增长）。
6) **触发条件**：运行时持续生成新颜色（渐变、随机色、每帧改色）。
7) **验证**：p8_audio2_color.py C1 末两行（`2013` 条、`同一颜色不同写法占两份缓存: True`）。
8) **影响与等级**：P3（内存/性能小量级；已在 `_HEX_RGBA_CACHE` 的既有定位下工作，不改语义）。

#### P-26（P3）死代码：`mesh_validate` / `Texture.bump_appearance` / `_is_default_white` / `Point3D` import

1) **位置**：mesh.py:156-179；loom_texture.py:126-128, 207-213；loom_raycast.py:26-29。
2) **契约/预期**：模块文档把 `mesh_validate` 描述为"自检"、`bump_appearance` 描述为"内容变化 → 通知外观代计数器"。
3) **路径枚举**：全仓 grep（`*.py`）=`mesh_validate` 仅命中定义行；`bump_appearance` 仅命中 loom_texture.py:207（loom_material 的 `_bump_appearance` 是同名不同物，不调用它）；`_is_default_white` 仅命中赋值行；`Point3D` 在 loom_raycast.py 仅命中 import 与 except 赋 None。
4) **实际行为**：这四者无任何调用/读取路径（死代码）。
5) **差异**：预期"自检/失效通知在链路上生效"，实际"从未被调用"。
6) **触发条件**：无（永不触发）。
7) **验证**：`grep -n "mesh_validate\|bump_appearance\|_is_default_white" Loom/*.py` 结果见 §0.3 记录；`mesh_validate` 另经 p1b 证明对空网格会 ZeroDivisionError（从未被调用，故不成 P1）。
8) **影响与等级**：P3（可维护性/误导读代码者；另：若将来有人接上 `mesh_validate(空网格)` 会立刻炸）。

### 2.2 P-DISPROVED（证伪成功，共 8 项，留证避免下轮重复粗筛）

| 编号 | 位置 | 疑似方向 | 证伪链要点（路径枚举 + 证据） | 结论 |
|---|---|---|---|---|
| D-01 | loom_texture.py:142-151 | RGB/RGB565 三通道上传存在 4 字节行对齐错位 | 路径：`ensure_gl` → `tex.write(payload)`，moderngl `Texture.write` 签名默认 `alignment=1`（moderngl/__init__.py:842），逐行无填充；tests/test_texture.py:256-259 对 rgb24/rgb565/rgba4444/rgb5a1 五种格式全部 PASS | DISPROVED |
| D-02 | loom_raycast.py:296-327 | 反投影用 `ndc @ inv(vp)` 是转置错误 | 路径：`_ray_from_screen` 唯一实现；项目矩阵约定为行向量（loom_render.py:765-772 `self._vp = V @ P` + `world @ _vp`），与 editor.py:307-311 同式；4 个采样点（含 0,0 / 799,599 / 小数）与 editor.`_unproject` near 偏差 0.0、dir 偏差 0.0 | DISPROVED |
| D-03 | loom_raycast.py:34-54 | slab 法退化输入（平行/盒在背后/原点在盒内/擦边/零方向）行为异常 | 路径枚举 6 组实测：正视 4.0 / 盒内 0.0 / 平行在外 None / 背后 None / 擦边 4.0 / 零向量 0.0，与 editor.`_ray_aabb` 逐条一致；零方向在公开 API 前已被 `ln<1e-12 → []` 拦截 | DISPROVED |
| D-04（重点项） | layer_tag.py:27-39, 56-67；loom_raycast.py:136-138；agent_commands.py:1791, 2545-2550；sceneio.py:195-203 | 层标记位宽不一致（8 位/32 位混用、越界可写） | 路径枚举全链路：存储 `LAYER_COUNT=32` 且 normalize 丢弃 0~31 之外键（p6 L2：`32 in? False`、`-1 in? False`、层总数 32）；EAI 校验 0..31；sceneio 越界钳制 0 并告警；raycast `lay<0 or lay>31 → False`、位运算 `1<<lay`。四侧均为 32 位 | DISPROVED（位宽一致；仅"类型归一"缺失 → 已单列 P-14） |
| D-05 | mesh.py:39-76 | cube 24 顶点 UV/绕序/法线朝外有问题 | 路径：`create_cube` 单一构造路径；探针 `mesh_validate(cube)=0.5>0`、零面积面 0/12、UV 角点 (0,0)/(1,1) 与 tests/test_texture.py:118-125 断言一致 | DISPROVED |
| D-06 | audio_backend.py:140-169 | `play`/`stop` 不返回值导致调用方无法感知失败 | 路径：`play` 两个出口（ent None / 异常）都 return None，成功也 None——**但** C4 与 loom_components.py:434-435 明写"播放失败静默"，属既定白盒契约 | DISPROVED（非缺陷） |
| D-07 | audio_backend.py:115-134 | 加载失败也缓存 None，文件后来出现仍不重试 | 路径：`load` 唯一缓存写入点，注释 audio_backend.py:122 明写"已缓存 (None 也缓存, 防反复重试)"，属既定设计 | DISPROVED（非缺陷） |
| D-08 | loom_font.py:62-98 | 字体全缺失时 `Font(None)` 兜底会抛异常 | 路径：`_load_chain` 主字体找不到 → `pygame.freetype.Font(None, size)` 成功（探针 F5：chain[0]=Font、5 个回退项 None、`char_index('中')=-1` 而非异常） | DISPROVED |

### 2.3 P-UNKNOWN（双向都未闭环，共 4 项）

#### U-01 `id(ctx)` / `id(组件)` 地址复用是否会在真实运行中命中

- **已尝试探针（2 次）**：①p2_texture.py T1：销毁 ctx1 → 新建 ctx2，地址不同；②p2b_texture_idreuse.py：销毁后循环新建 5000 个同型对象，无一命中旧地址。前置验证确认 CPython 会复用地址（`del 后新对象是否复用同地址: True`）。
- **仍缺的信息**：真实引擎里"销毁 GL 上下文 → 新建上下文"之间发生过多少种同尺寸分配（GL ctx 对象来自 moderngl C++ 包装，尺寸类与 FakeCtx 不同）；以及 `AudioSource` 组件在 GameObject 销毁/重建序列里的地址分布。
- **若命中会怎样**：`ensure_gl` 返回属于已销毁 ctx 的 GL 纹理（p2 T1 型）；`audio_backend.load` 让两个生命周期共用同一 ga 句柄 → 音量/循环状态互踩（契约"同 clip 多组件各自独立"失效）。
- **建议下一步探针**（第 3 次）：在 `tests/test_texture.py` 风格的真实 `moderngl.create_standalone_context()` 上做 `ctx.release(); del ctx; ctx2 = create_standalone_context()`，打印 `tex._gl_ctx_id == id(ctx2)`；音频侧在编辑器里 `add_model→删→add_model` 50 次并记录 `id(audio_source)` 序列。
- **不影响已定级部分**：P-05 的"换 ctx 不释放旧纹理"与 P-21 的"缓存无淘汰"已由 PROVED 覆盖。

#### U-02 空网格（P-02）下游是"不可见对象"还是渲染/物理期异常

- **已尝试**：几何层已证实空网格可被构造并挂进 `add_model` 之前的链路；未验证 `loom_model_gpu` 展平、`_model_aabbs_par`、物理 collider 对 V=0 的行为（需 GL/物理桥）。
- **仍缺的信息**：`loom_model_gpu.register_mesh`/`_model_aabbs_par` 对 `len(vertices)==0` 的分支（是否除零/是否返回 None）。
- **建议下一步探针**：headless 调 `physics_bridge.collider_bounds(空网格模型)` 与 `engine.compute_world_matrices`+ `_model_aabbs_par`，观察返回值/异常；若下游异常则 P-02 升 P1。

#### U-03 "字形覆盖是否允许随字号变化"——决定 P-08 的修法

- **已尝试**：真实字体（msyh/seguiemj/seguisym/simsun）在 size 1~40 的 `adv_x` 实测：轮廓字体下"有无字形"不随字号变化，只有**零宽字形**恒为 0.0、以及 size=1 的 space 出现 0.0。
- **仍缺的信息**：产品是否要求支持位图字体（CJK 点阵字库）或运行时换字体文件（C3 说"字体文件不热重载"→ 倾向不允许）。
- **判断影响**：若"不允许随字号变化"，则正确修法是让 `_has_glyph` 与字号解耦（用 `get_metrics` 的 None 判定 + 零宽字符特判），`_missing` 保持字符级；若"允许"，则 `_missing` 必须改成 `(size,ch)`。见 §5 Q2。

#### U-04 物理 `ratio*max_dist` 距离语义与几何路径是否等价

- **已尝试**：`_raycast_phys` 注释声称"探针确认 ratio 是 max_dist 的比例"，代码 `real_dist = ratio * md`；p4 R2 中 fake 桥返回 ratio=0.45、max_dist=1000 得 450.0，说明代码按"比例"解释。
- **仍缺的信息**：Culverin 实际返回的是比例还是绝对距离（本机 `physics_bridge.cv_available` 未验证；需要真实桥 + 已知距离场景）。
- **若真为绝对距离**：物理路径距离被放大 max_dist 倍（默认 1000×），与几何路径差 3 个数量级 → 所有"取最近/按距离排序"的调用方结果错乱。**这条与 P-10/P-12 同属后端一致性，建议 05_physics/08_physics 模块交叉确认**。

### 2.4 P-CONTRADICTION：0 项（需解释）

本轮 0 项矛盾。原因不是"两边都没问题"，而是四象限里"证伪成功+证真成功"的候选在写链途中就被拆分归位：
- `_has_glyph` 的 `adv_x > 0.5` vs 文档"adv_x > 0"：证真只能得到"阈值比文档严格"，但 0<adv≤0.5 的真实字形在 4 个系统字体里一个都没有（p3b E1 全表），证真链立不成立 → 归入 P-07/P-08，不构成矛盾。
- `mesh_validate` 空网格除零 vs 死代码：证真（除零可复现）+ 证伪（无调用方，不在任何运行时路径）**同时成立**，看似矛盾，实为两条链问的不是同一个问题（"函数行为" vs "运行时影响"）。已按协议要求拆成 P-26（死代码）+ U-02（下游行为），不保留"两说并存"。

---

## 3. 统计

| 文件 | 粗筛疑似项 | PROVED | DISPROVED | UNKNOWN | CONTRADICTION | 跳过登记 |
|---|---|---|---|---|---|---|
| mesh.py | 4（P-01..P-04） | 4 | 1（D-05） | 1（U-02） | 0 | 5（SKIP-01..05） |
| loom_texture.py | 2（P-05, P-06） | 2 | 1（D-01） | 1（U-01） | 0 | 3（SKIP-06..08） |
| loom_font.py | 3（P-07..P-09） | 3 | 1（D-08） | 1（U-03） | 0 | 1（SKIP-09） |
| loom_raycast.py | 5（P-10..P-14） | 5 | 2（D-02, D-03） | 1（U-04） | 0 | 2（SKIP-10,11） |
| audio_backend.py | 4（P-20..P-23） | 4 | 2（D-06, D-07） | （U-01 共用） | 0 | 3（SKIP-12..14） |
| layer_tag.py | 5（P-15..P-19） | 5 | 1（D-04） | 0 | 0 | 2（SKIP-15,16） |
| loom_color.py | 2（P-24, P-25） | 2 | 0 | 0 | 0 | 1（SKIP-18） |
| loom_types.py | 0 | 0 | 0 | 0 | 0 | 1（SKIP-17） |
| 跨文件（死代码） | 1（P-26，合 4 处） | 1 | 0 | 0 | 0 | — |
| **合计** | **26** | **26** | **8** | **4** | **0** | **18** |

口径说明：P 编号（P-01..P-26）= 26 条粗筛疑似项，全部 PROVED；D-01..D-08 与 U-01..U-04 是另 12 条粗筛候选（不在 P 编号内），合计候选池 38 条。U-01 同时涉及 loom_texture 与 audio_backend 两处机制，只计 1 项。

等级分布（PROVED 内部，共 26）：

| 等级 | 数量 | 项 |
|---|---|---|
| P0（安全/崩溃） | 0 | —（P-01 的 ZeroDivision 确实穿透 sceneio 兜底，但后果是"场景加载中断"而非进程崩溃，故定 P1） |
| P1 | 1 | P-01 |
| P2 | 13 | P-02 P-03 P-05 P-07 P-08 P-10 P-11 P-12 P-15 P-16 P-17 P-19 P-21 |
| P3 | 12 | P-04 P-06 P-09 P-13 P-14 P-18 P-20 P-22 P-23 P-24 P-25 P-26 |

按模块主 Agent 指定重点的覆盖对照：

| 指定重点 | 覆盖结论 |
|---|---|
| 网格/贴图/字体的**边界输入** | 网格 3 项（P-01/P-02/P-03）+ 贴图 2 项（P-05/P-06）+ 字体 2 项（P-07/P-08） |
| 网格/贴图/字体的**缓存** | 贴图 id(ctx)（P-05/U-01）、字体字号链与 `_missing`（P-08/P-09）、颜色缓存（P-25） |
| 射线检测**退化情形** | 双后端 visible 分叉（P-10）、层过滤 100 上限（P-11）、`raycast_all` 重复（P-12）、无桥警告缺失（P-13）、mask 类型（P-14）、slab/反投影退化（D-02/D-03 已证伪） |
| 音频后端**生命周期** | shutdown 后两套降级（P-22）、句柄缓存无淘汰（P-21）、atexit 每实例（P-23）、mode 不可用态缺失（P-20）、owner=id 风险（U-01） |
| **层标记位宽** | D-04：存储 32 / EAI 0..31 / sceneio 钳制 / raycast 0..31 四侧一致，**无位宽缺陷**；仅类型归一缺失（P-14）与截断（P-18） |

---

## 4. 修复建议排序（只给方向，不含代码）

**P0（无）**

**P1**
1. **P-01**：`spec_to_mesh`/基元构造函数对 `stacks/slices/radius/size` 做"归一到合法域或抛 ValueError"的边界收口，让 C7 的"唯一异常类型"重新成立；sceneio 的兜底只作第二道防线，不作为契约。（顺带消除 P-02 的负值空网格。）

**P2（按影响面）**
2. **P-15 / P-19 / P-16**（配置可信度）：`load()` 走与 `register_tag` 相同的 `validate_tag` 收口；损坏文件先备份再落默认并**按契约 C2 打印警告**；`register_tag` 落盘失败要么回滚内存并抛错、要么保留"待重试"状态（注释里的"下次启动重试"目前不存在）。
3. **P-17**：`_state()/reload()` 传递 base（或删掉伪参数并改文档）。
4. **P-10 / P-11 / P-12**（射线一致性）：把"可见性过滤"和"候选耗尽"提到后端无关层；100 次上限改为"耗尽后告警 + 回退几何路径"；`raycast_all` 物理侧按 model 去重。
5. **P-07 / P-08**（字体）：分段边界不应落在零宽字符/变体选择符上（把它们并入前一簇）；`_has_glyph` 与 `_missing` 的键空间先按 §5 Q2 的裁决统一。
6. **P-05 / P-21**（资源生命周期）：换 ctx 重建前释放旧纹理（或按 ctx 维度做"多 ctx 缓存表"）；音频句柄缓存加"组件销毁时按 owner 清理"的入口，并在 `shutdown` 时清空缓存。
7. **P-02 / P-03**：空网格在 `Mesh._validate` 或 `spec_to_mesh` 层拒绝；OBJ 的 vt/vn 与 v/f 共享同一资源上限（顺带把 p1b 的"vt/vn 无上限"加入 tests/test_mesh_import.py）。

**P3**
8. P-04（解析错误加文件名/行号、越界角点计数告警）、P-06（`from_rgba` 显式范围校验或钳制）、P-09（字号链 LRU + 修文档"进程级"）、P-13（无桥时按文档告警、未登记 handle 继续）、P-14（mask 先 `int()` 归一）、P-18（`layer_name` 只接受整数）、P-20（补 `_mode=None` 不可用态）、P-22（shutdown 后统一静默）、P-23（atexit 注册去重/注销）、P-24/P-25（hex 校验 + 缓存键归一）、P-26（删死代码或接线，且接线前先修空网格除零）。

**回归资产建议（协议 §8"反例进回归集"）**
- `{"type":"sphere","params":{"stacks":0}}` 场景加载 → 必须兜底不抛；
- `layer_tag.json` 含 100 字符/带空格 tag → 加载后必须被拒或截断；
- `split('👨\u200d👩\u200d👧')` → 分段数必须为 1（或不少于"零宽不独立成段"）；
- 100 个 layer0 遮挡 + 1 个 layer1 目标 + `layer_mask` → 必须命中目标；
- `ensure_gl(ctxA) → ensure_gl(ctxB)` → 旧纹理 `released >= 1`；
- `reload(base=A)` → `get_layers()` 必须反映 A。

---

## 5. 需要人类裁决的封闭问题

**Q1（P-10 的方向）隐藏物体是否应被 `raycast` 命中？**
- A. 应与可见性无关（对齐 Unity：Renderer 关闭不影响 Collider）→ 修 `_raycast_geom_all`，删掉 `visible` 过滤，几何与物理都命中隐藏物体；代价：编辑器里"隐藏的物体也会被点选/被 EAI 命中"。
- B. 应跳过隐藏物体（对齐当前几何回退语义）→ 物理路径需要按 model.visible 二次过滤；代价：物理命中数与"真实碰撞"不再一一对应，`raycast_all` 条数会少于 Collider 数。
- C. 由 `layer_mask`/显式参数决定（默认跳过隐藏，物理侧同样过滤）→ 需要新增参数并改三个公开 API 的签名。
> 已有证据：p4 R2（physics→'隐藏'，geometry→'可见'）；两条路径都无告警。

**Q2（P-08 的修法前提）字形覆盖是否允许随字号变化？**
- A. 不允许（字体文件不热重载，轮廓字体覆盖与字号无关）→ `_has_glyph` 必须与字号解耦，`_missing` 保持"按字符"（C3 原设计），修 `adv_x > 0.5` 的阈值与零宽特判。
- B. 允许（将来支持位图字库/不同字号不同字库）→ `_missing` 必须改成按 `(size, ch)`，代价是字符缓存内存 × 字号数（与 C3"约 100KB"的估算冲突）。
> 已有证据：p3b E1（size 1~40 的 adv 全表：轮廓字体只有零宽字形恒 0.0）；p3 F2（跨字号污染可复现）。

**Q3（P-12/U-04 的语义归属）`raycast_all` 的"所有命中"粒度是"物体"还是"碰撞体"，距离是"世界单位"还是"max_dist 比例"？**
- A. 物体粒度 + 世界单位（与几何路径一致）→ 物理侧需去重 + 确认 Culverin ratio 语义（若返回绝对值则不得乘 max_dist）。
- B. 碰撞体粒度（保留重复）+ 世界单位 → 改文档与几何路径（几何路径无法表达多碰撞体，需额外数据）。
- C. 保持现状两套语义 → 则必须在文档中声明"auto/physics 与 geometry 结果不可比"，并在 EAI/MCP 描述里同步。
> 已有证据：p4 R5（物理返回 2 条同名模型、几何返回 1 条）；p4 R2（同一 max_dist 下 450.0 vs 4.5）。

**Q4（P-16/P-19 的策略）程序目录不可写时，"注册 tag / 回退默认配置"应以哪种方式失败？**
- A. 失败即抛错（GUI 红框提示），不写内存；代价：只读安装环境下用户无法临时加 tag（与 C1 §3.2"内联注册"体验冲突）。
- B. 内存成功 + 每次启动重试 + 首次失败即警告；代价：需要引入"待持久化脏标记"。
- C. 自动把 `layer_tag.json` 重定向到用户目录（%APPDATA%）；代价：配置位置与契约 §3.1"程序目录"冲突，需契约变更。
> 已有证据：p6 L4（register 返回 True、磁盘无文件、重启丢失）；P-19（损坏文件被静默覆盖，全模块 0 个 print）。

---

## 6. 自审 checklist（协议 §11.5）

- [x] §7 八条硬要求：基准唯一（C1-C8）、代码原样引用、证伪链有路径枚举表、证真链有可跑命令、措辞无"我认为/经验上/看起来"、跳过留痕 18 条、矛盾已解释
- [x] 每条链引用被审对象自身契约，未混用外部标准（唯一外部引用是 moderngl 的 `alignment=1` 与 CPython 的 id 语义，均用于"证伪"且标注了来源）
- [x] 每条证伪链第 3 段有路径枚举表（D-01..D-08 列内逐条给出路径集合）
- [x] 每条证真链第 7 段有可跑命令（p1..p9 探针，均在报告 §0.3 列出）
- [x] 跳过登记表每条都有四类理由之一的出处（SKIP-01..18）
- [x] P-UNKNOWN 数量 = 4（不为 0）
- [x] P-PROVED 数量 = 21（不为 0）
- [x] P-CONTRADICTION = 0，已在 §2.4 解释原因并说明拆分归位
- [x] 每个 P-PROVED 给出修复方向（本轮只扫不改，未产生 diff）
- [x] 每个 P-UNKNOWN 探针次数 ≤ 3（U-01 两次、U-02/U-03/U-04 各一次）
- [x] 人类裁决项均为封闭问题（A/B/C 选项 + 代价）
- [x] 无"我认为 / 经验上 / 看起来 / 应该是"等不可审计措辞
> 本轮等级自评：**A4**（双向链完整 + 矛盾检测 + 探针机制 + 跳过留痕 + 人类裁决包；未达 A6 的原因是白盒层未单独出"设计冲突证据包"，本轮设计冲突已并入 §5 的 Q1-Q4）。
