# 调研报告 02：资产导入与全局唯一 GUID 引用体系（beta6）

> 编号：02／beta6
> 状态：**调研（只读）**，不含实现代码；接口与数据结构为草案。
> 仓库根：`D:\my-project - 副本\Loom(py源代码-工作区)`，本文所有行号以本次实测提交为准。
> 探针脚本（gitignore 目录内，可重复执行）：
> `Loom/tests/_tmp/research_02_probe_asset_refs.py`（A–G 段）
> `Loom/tests/_tmp/research_02_probe_b.py`（H–J 段）
> 跑法：`cd Loom; $env:PYTHONIOENCODING='utf-8'; python tests/_tmp/research_02_probe_asset_refs.py`

---

## ① 现状（证据）

### 1.1 资源引用方式全清单（含失效场景）

先给结论：**当前没有任何"资产身份"层**。全局唯一的只有"场景内对象/材质 id"，
而"资源正文"一律靠**路径字符串**，且同一件事存在 **3 套不同的路径基址**。

| # | 载体（字段） | 形态 | 写入点 | 读取点 | 解析基址 | 失效场景（实测/代码） |
|---|---|---|---|---|---|---|
| 1 | 场景级天空盒 `skybox.paths`（6 面） | **相对场景目录** + 目录内校验 | `sceneio._emit_skybox_checked` L757-785（L782-784 写 `name/guid/paths(rel)`） | `skybox_from_dict` L631-688（L649-677 拒绝绝对/`..`/缺文件） | 场景文件目录（L656） | 换机/移动场景目录：**相对路径能救回**（只要图跟着走）；但**没有 guid，同一张图被 3 个场景各存一份**，改图要改 3 处 |
| 2 | 相机级天空盒 `cameras[].skybox.paths` | 同上 | `_emit_camera` L788-809（L808） | `_apply_cameras` L812-856（L848） | 场景文件目录 | 同 #1 |
| 3 | 材质颜色贴图 `materials[].albedo.path` | **绝对路径** | `_emit_material` L871-901（L880）← `Texture.from_file` 把 path 转 `abspath`（`loom_texture.py` L122） | `_apply_materials` L904-955（L926-938，`Texture.from_file(ref['path'])` 原样） | **无**（直接用存下的绝对路径） | 换机/改名/移动场景目录 → 贴图**静默消失**（L937 `except: pass`）。探针 B 段实测：改名后 `albedo 恢复? False`，stdout 无任何告警 |
| 4 | 材质法线贴图 `materials[].normal_map.path` | 同 #3 | `_emit_material` L886-889 | `_apply_materials` L924-938 | 无 | 同 #3 |
| 5 | 材质环境贴图 `materials[].env_map.paths`（6 面） | **绝对路径** | `_emit_material` L890-900（L895 `list(paths)`）← `Cubemap.from_files` 存 `abspath`（`loom_cubemap.py` L77） | `_apply_materials` L939-954（L945 原样喂 `from_files`） | **无**（相对路径会按 **CWD** 解析，不是场景目录） | 探针 B 段实测：改名后 `env_map 恢复? False`，**完全静默**。探针 C 段实测：即使手写成相对路径，也按 CWD 解析（`env_map 恢复? False`，stdout 空） |
| 6 | 物体 → 材质 `objects[].material_id` | **guid**，但**只在同一文件的 `materials[]` 里解析** | `_emit_object` L248-304（L265） | `_apply_object` L337-362（L351-358：`engine._find_material(mat_id)`，找不到就 `add_material(guid=mat_id)`） | 引擎内存材质库（`loom_model_gpu.py` L66-72） | `assets/materials/*.json` **完全不参与加载**：探针 I 段实测，`material_id` 指向资产文件里的 guid 时，材质被重建为"裸材质"——`name=材质, pbr=False, metallic=0.0`，资产里的 PBR/贴图/名字全丢 |
| 7 | 场景对象身份 `objects[].id / parent_id / prefab_ref` | **guid**（场景内唯一） | `_emit_object` L252-254 | `_apply_object` L359-362 / `_link_by_map` L471-480 | 文件内自洽 | 无全局注册表：**同一场景内重复 guid 不报错**。探针 D 段实测：两个材质同 id `dup` → 库里出现 `['dup','dup']`，物体拿到第一个（red），**stdout 无重复 guid 告警** |
| 8 | 网格（基元） | 内联 `type + params` | `_emit_object` L259-260 | `_make_mesh` L321-334 | 无 | 基元无损；但"网格"不是资产，**无法被复用/替换**（同一网格 100 个物体各存一份 params） |
| 9 | 网格（.obj 导入） `objects[].params.obj` | **绝对路径** | `mesh.load_obj` L406-407（`params={'obj': abspath(path)}`） | `_make_mesh` L325-330 | 无 | 文件丢失 → **静默退回 1.0 立方体**（L329-330）。探针 H 段实测：载入后 `primitive='cube'`，`params={'size':1.0}`，stdout 空 |
| 10 | 网格资产 `assets/meshes/*.json` 的 `id` | guid | `save_mesh_asset` L1640-1646（L1643 **每次都 `generate_guid()`**） | 无人引用（资源面板只取 `type/params`，`editor.py` L1434-1449） | — | **死身份**：这个 guid 在整个仓库里没有任何引用方；重复保存同一网格得到多个 guid，且场景里永远不写它 |
| 11 | 材质资产 `assets/materials/*.json` 的 `id` | guid | `save_material_asset` L1620-1622（复用 `mat.guid`，同 guid 覆盖：`editor.py` L1502-1517） | 只被"拖拽/命令应用"读（`_apply_material_asset` L1471-1489） | 直接读文件 | 加载场景**不查资产库**（见 #6）；且资产里内嵌的贴图路径同样是绝对路径（同 #3） |
| 12 | Prefab `prefab.guid` + `objects[].prefab_ref` | guid | `prefab_to_dict` L1664-1671 | `instantiate_prefab` L1686-1708 | 直接读文件 | 仅"来源标记"，**不回查资产库**：Prefab 里的材质 guid 落到新场景时同样按 #6 重建（丢贴图/PBR） |
| 13 | UI 图片 `ui.canvases[].children[].texture_path` | **原样字符串**（相对→CWD） | `_emit_ui_element` L1038；读 `L1175` | `loom_ui.Image._load` L991-1007（L1003 `pygame.image.load(self.texture_path)`） | 进程 CWD | 失败→**灰底占位，静默**（L1006-1007）；换 CWD 启动即丢图 |
| 14 | 音频 `objects[].audio_source.clip` | **原样路径字符串** | `_emit_object` L288-297（L289） | `loom_components` L250-254（注释 L238：`clip 音频文件路径`）；命令 L1952-1953 原样写 | 进程 CWD | 同上；无存在性校验、无 guid |

**三套基址并存（实测/代码）**

- 天空盒：**场景目录**（`sceneio.py` L656；命令侧 `agent_commands.py` L1021-1038）；
- 贴图/环境贴图**命令入口**：**引擎目录**（`agent_commands.py` L1702-1704 `_root=dirname(agent_commands.py)`；L1821-1827 同）；
- 材质 env / UI / 音频**加载**：**进程 CWD**（`sceneio.py` L945；`loom_ui.py` L1003）。

### 1.2 `.meta` / uuid / 集中清单：都不存在

- `.meta`：`glob "**/*.meta"` → **0 个**；`.guid` → 0 个。
- 集中清单：`grep "assets\.json"` → **0 命中**（全仓库）。
- guid 生成：`sceneio.generate_guid()` L61-62 = `uuid.uuid4().hex`；`Texture` L48、`Cubemap` L30、`Material` `loom_material.py` L34 各自 `uuid4().hex`。
- guid **是可信输入**：`Texture.from_file(guid=...)` / `Cubemap.from_files(guid=...)` 直接采用调用方给的 guid，**不查重、不校验**（`loom_texture.py` L45-50、`loom_cubemap.py` L28-31）。探针 G 段实测：两个材质的两张贴图可以是**同一个 guid 但不同文件**（`['SAME','SAME']`）。
- **重复 guid 已经会错画**：VK 侧纹理缓存键就是 guid（`vk_renderer.py` L1426-1437，L1432/1435），GL 侧材质桶键也带 `_tex_guid`（`loom_model_gpu.py` L110-117）。撞 guid = 绑错图/合错桶。
- 同一文件导入两次 → **两个 guid**（探针 F 段实测：`相同? False`），即**没有内容去重**。

### 1.3 资产目录与分层现状

| 层 | 实际位置 | 证据 | 问题 |
|---|---|---|---|
| 引擎目录资产 | `Loom/assets/`（`materials/`、`meshes/`、`*.prefab`、`图像素材/`、`假车库.mtl`、`culverin_schema.json`） | `editor.py` L45 `APP_DIR=dirname(__file__)`；L1375 `os.path.join(APP_DIR,'assets')`；本机实测目录清单 | **不在项目里**：与场景所在目录无关；同一台机器上所有项目共用一个资产库 |
| 场景文件 | 任意路径（默认 `Loom/Projects/`，可另存到任何目录） | `editor.py` L48 `DEFAULT_SAVE_DIR`；L1125 `_choose_scene_path` | 场景与资产目录**无绑定关系**，因此"相对场景目录"只在天空盒一处成立 |
| 用户层 | `%LOCALAPPDATA%\Loom\{engine,hub,games,projects,logs}` | `userpaths.py` L30-79 | **只有配置文件**，没有任何资产缓存/覆盖层 |
| 模板层 | 引擎目录同名配置文件（只读） | `docs/design/用户配置目录契约_20261108.md` L22-28 | 资产没有"模板层"概念（内置网格是硬编码 `editor.py` L1366-1370） |

**两个与发布相关的硬事实**（决定了资产不能继续放在引擎目录）：

1. 引擎打包**排除** `assets`：`tools/package_engine.py` L23-24 `EXCLUDE_DIRS` 含 `'assets'`；启动自检也跳过它（`Loom.py` L339-343）。
2. 游戏打包**不拷资产**：`build_game.py` L195-200 只把**场景 dict** 读进内存，L221-240 只拷运行时/`core_components`/`ckernels`，L278-279 交给 `game_pack.pack`（`game_pack.py` L58-70 只存 `scene/scripts/config`）。
   而播放器在"包内场景 dict"模式下 `scene_path=None` → `_base=None`（`runtime.py` L136-138；`vk_player.py` L305-308）→ 天空盒相对路径退化成**按 CWD 解析**。**结论：现在打出来的游戏，任何贴图/六面图都不保证能加载。**

### 1.4 `agent_commands` 里 `asset_place / asset_save` 的真实语义

- `assets`（`agent_commands.py` L2236-2242）：**每次现扫盘** `editor._scan_assets()`，只列 **mesh / material / prefab** 三类（`editor.py` L1372-1400：`meshes|materials` 子目录 + `assets/*.prefab`）。**没有 texture/cubemap/audio 类型。**
- `asset_place`（L2269-2276）：把 `(type,key)` 资产"放到视口中心"——实际是 `_asset_drop_to_scene`（`editor.py` L1429-1469）：mesh→建物体（内联 spec，**不建立对资产 guid 的引用**）、prefab→实例化、material→应用到选中。
- `asset_save`（L2279-2295）：`what=mesh|material` → `editor._save_mesh_asset / _save_material_asset`（L1519-1562）；落盘目标 `APP_DIR/assets/{meshes,materials}`，走写路径白名单 `_safe_write_path`（白名单根：程序目录/场景目录/用户目录/Temp，L84-119）。
- 也就是说：**"资产"目前只是"面板里能点的一个文件"，没有任何引用完整性**——存/放两端都不建立 guid 依赖，场景里也从不记录资产 guid（除材质恰好复用了 guid 这条半吊子路径）。

### 1.5 beta5 已有的 `valid/reason` 模式（本设计要对齐的样板）

- 数据侧：`skybox_from_dict() -> (cube, valid, reason)`（`sceneio.py` L631-688），失败必给 reason、绝不静默；
- 引擎侧：加载后挂 `engine._skybox_valid / _skybox_error`（L1426-1432）；保存越界则 `valid=False` + 不写出（L1383-1394）；
- 命令侧：`skybox_get` 返回 `valid/reason/scene_valid/active_camera_skybox/vk`（`agent_commands.py` L1126-1178）。
- 明确对照：**同样一件"图找不到"，天空盒会出声 + 有 reason，贴图/环境贴图/UI/音频全部静默**（探针 B/C/E 段 stdout 为空）。这是本批最该消灭的不一致。

---

## ② 目标设计（含数据/接口草案）

### 2.1 设计原则（与现有架构对齐）

1. **一个 guid = 一个资产身份 = 一条索引记录**；路径永远**不**进场景文件，只在索引里以**项目相对 POSIX 路径**出现。
2. **项目层优先**：资产属于"项目"，不属于"引擎目录"（`tools/package_engine.py` L23-24 已经证明引擎目录不是资产的家）。
3. **失败必须出声**：全部走 `(obj, valid, reason)`，与 skybox 同款；引擎聚合 `_asset_errors`，命令可查。
4. **不新增兼容负担**：仓库已声明"内测开发、破坏兼容无需迁移"（`docs/design/用户配置目录契约_20261108.md` L3-10）。因此旧路径**只做一次性迁移**，不做长期双读分支。

### 2.2 存储方案取舍（问题 2）

| 方案 | 优点 | 缺点 | 判定 |
|---|---|---|---|
| A 每资产 `.meta` sidecar（Unity 风格） | 与文件同生共死、天然随目录移动、diff 友好 | 与现有"资产=一个 JSON"习惯不符；一个 guid 的导入设置散落 1 万个小文件；重命名资产时要么改名要么保留孤儿 | ✗ 不采用（引入成本高、与本仓库"集中 JSON + 原子写"风格冲突） |
| **B 集中 `Assets/assets.json`（推荐）** | 单点读写；guid 唯一性可在一处校验；指纹（hash/mtime）集中；加载只读一个文件（O(1) dict）；可用现成 `save_json_atomic`（`sceneio.py` L1535-1545）与 `userpaths.backup_path`（L69-79） | 大项目单文件（万级资产约几 MB，可接受）；并发写需一把锁 | ✓ **采用** |
| C 二者并存 | 灵活 | 两处真相，必须处理不一致 | ✗ |

**分层（复用现有用户配置契约的形状，不发明新机制）：**

| 层 | 位置 | 写者 | 语义 |
|---|---|---|---|
| 项目层（唯一真相） | `<项目根>/Assets/assets.json` + `<项目根>/Assets/<Type>/...` | 导入器/编辑器 | 资产正文 + 索引 |
| 用户层（仅 delta） | `%LOCALAPPDATA%\Loom\projects\<pid>\assets.json` | 运行时/编辑器 | 只存"本机覆盖"：源文件路径覆盖、导入设置覆盖（应对"资产在本机别处"） |
| 模板层（只读） | 引擎内置 | 构建产物 | 内置网格/默认材质/默认天空盒，用 **逻辑 guid** `builtin:cube` 等（对齐现有 key `builtin.cube`，`editor.py` L1366-1370） |

> ⚠️ 与现有 `%LOCALAPPDATA%\Loom\projects\<pid>\` 的 `project_id` 已存在（`userpaths.py` L115-140），本设计**复用同一个 pid**，不新建标识体系。

### 2.3 数据草案：`assets.json`

```jsonc
{
  "schema": 1,
  "project_id": "3f2c…",            // = <项目>/.loom/project_id（userpaths.py L115-140）
  "assets": {
    "5f0a9d0c…": {                  // guid = uuid4().hex（沿用 sceneio.generate_guid 语义）
      "type": "texture",            // texture | cubemap | material | mesh | audio | model
      "src": "Textures/wood.png",   // 项目相对 POSIX 路径；模板层资产为 null
      "builtin": false,             // true -> 逻辑 guid（builtin:cube），不落 src
      "name": "wood",
      "import": {                   // 导入设置（对标 Unity Import Settings）
        "wrap": "repeat", "filter_mode": "trilinear", "aniso": 1.0,
        "max_size": 0, "mipmaps": true, "compression": "none", "srgb": true
      },
      "fingerprint": {              // 变更检测（问题 2 的"源文件改动怎么发现"）
        "sha256": "…", "size": 123456, "mtime": 1762000000.0
      },
      "deps": [],                   // material -> [贴图 guid]；model -> [材质 guid]
      "sub": {}                     // model 子资源（本批不用）
    }
  }
}
```

**变更检测策略（明确回答"hash 还是 mtime"）**

- 索引里**同时**记录 `sha256 + size + mtime`；
- **加载热路径只读 `mtime + size`**（两次 `os.stat`，不做 hash），不一致再算 `sha256`，两者都不同才标记 `stale`；
- 判定结果进入 `engine._asset_errors`（`valid=False, reason='源文件已变更（mtime/size），请 asset_reimport'|'内容已变更（sha256）'`），**不阻塞加载**（贴图照旧用已存字节或旧 `Texture`），但**必须出声**；
- 重导入 = 重新解码 + 更新 `import/fingerprint`，**guid 不变**（引用不失效）。

### 2.4 场景文件里的引用形态（目标）

只写 guid，丢掉 path：

```jsonc
// 材质（materials[]）
{"id": "<mat guid>", "name": "wood", "color": null, "pbr": true, "metallic": 0.2,
 "roughness": 0.6,
 "albedo":       {"guid": "<tex guid>", "import": {"wrap": "repeat"}},   // import 可省略=用资产默认
 "normal_map":   {"guid": "<tex guid>"},
 "env_map":      {"guid": "<cubemap guid>"}}

// 场景/相机天空盒（保持既有键名，只换内容）
"skybox": {"guid": "<cubemap guid>"}
"cameras[].skybox": {"guid": "<cubemap guid>"}

// 物体
"material_id": "<mat guid>"
"params": {"obj_asset": "<model guid>"}      // 替代 params.obj 绝对路径（模型批）
"ui…texture_path" -> "ui…texture_guid": "<tex guid>"   // 键名新增，旧键迁移后删除
"audio_source.clip_path" -> "audio_source.clip_guid": "<audio guid>"
```

保留的**不可废弃**语义：`skybox` 的 `solid_color` 分支（纯色 cubemap 无文件，`sceneio.py` L890-900 / `loom_cubemap.py` L79-136）、`guid` 可选（旧文件）→ 但**必须有 reason**。

### 2.5 接口草案（签名级，不含实现）

新增模块 `Loom/assetdb.py`（单点收口，禁止其它模块自己拼资产路径）：

```python
# ---- 索引读写 ----
def project_root(scene_dir) -> str            # 场景目录 -> 项目根（向上找 Assets/ 或 .loom/；缺省=场景目录）
def index_path(project_root) -> str           # <root>/Assets/assets.json
def load_index(project_root) -> (dict|None, valid, reason)
def save_index(project_root, index) -> str    # 复用 sceneio.save_json_atomic
def validate_index(index) -> (ok, reasons)    # schema/重复 guid/类型/相对路径越界/缺 src

# ---- guid 身份 ----
def new_guid() -> str                          # uuid4().hex（= sceneio.generate_guid）
def register(index, kind, src_abs, import_settings) -> (guid, created|deduped, reason)
def lookup(index, guid) -> entry|None
def builtin_guid(name) -> str                  # "builtin:" + name

# ---- 解析（全项目统一入口，带 valid/reason）----
def resolve(index, project_root, guid, kind=None) -> (abs_path|None, entry|None, valid, reason)
def check_stale(entry, project_root) -> (clean, fingerprint_now|None, reason)

# ---- 场景侧适配（与 beta5 同款三元组）----
def texture_from_ref(d, ctx) -> (Texture|None, valid, reason)     # ctx 提供 index/project_root
def cubemap_from_ref(d, ctx) -> (Cubemap|None, valid, reason)     # 兼容 solid_color
def material_from_ref(d, ctx) -> (Material|None, valid, reason)
```

引擎侧聚合（新增，形状对齐 `_skybox_valid/_skybox_error`）：

```python
engine._asset_errors: list[tuple[str, str, str]]   # (where, guid, reason)
engine.assets_ok() -> bool
```

命令层（新增/扩展，全部返回 `ok/valid/reason`）：

```
asset_import  {path, type=texture|cubemap|material, name?, import?} -> {guid, deduped, valid, reason}
asset_get     {guid}                                                -> {entry, valid, reason, stale}
asset_reimport{guid}                                                -> {valid, reason, fingerprint}
assets        {type?}                 # 扩展 assets 命令：新增 texture|cubemap 两类
scene_assets_check {}                 # 全场景引用体检：逐 guid 给 valid/reason/是否 stale
```

> 兼容底线：`assets / asset_place / asset_save` 的**既有返回结构不能变**（`test_eai_real.py` 有 9 处覆盖），只允许**新增键/新增 type**。

### 2.6 导入管线（问题 3）

**beta6 范围：贴图 + 六面图 + 材质。模型（obj/gltf → 网格+材质子资源）下一批。**
理由（有证据，不是感觉）：`mesh.load_obj` 目前把 MTL 颜色**烘进 face_colors**（`mesh.py` L335-339、L360-372），没有任何"材质子资源"概念；要做子资源必须先有材质资产引用体系——即本报告 2.3–2.5 的地基。先做模型会把两件事耦合进一个批次。

| 管线 | 输入 | 落盘 | 运行时产物 | 本批 |
|---|---|---|---|---|
| 贴图 | png/jpg/bmp（`pygame.image`，`loom_texture.py` L98） | `Assets/Textures/<name>.<ext>`（同 sha256 已存在→复用 guid，不复制） | `Texture`（CPU RGBA + import 设置；GPU 延迟 `ensure_gl`，L153-214） | ✅ |
| 六面图 | 6 张方图 或 目录 `px/nx/py/ny/pz/nz` | `Assets/Cubemaps/<name>/`（一个目录 = 一个资产 = 一个 guid） | `Cubemap`（`validate()` L155-179 保留） | ✅ |
| 材质 | 参数 + 贴图 guid | `Assets/assets.json` 条目（+ 可选 `Assets/Materials/<name>.json` 供人读） | `Material` | ✅ |
| 模型 | obj（现有）/gltf（无） | `Assets/Models/<name>/` + `sub: {mesh:guid, mat:guid}` | `Mesh` + 材质子资产 | ⛔ 下一批 |

**"复制进项目"还是"引用原位"**：必须**复制**。证据：绝对路径模式在换机/打包时 100% 失效（探针 B 段、`build_game.py` L221-240），而"引用原位"要求绝对路径。复制后项目自包含，才可能让 `build_game` 有东西可打。
**压缩**：beta6 **只记录** `compression` 导入设置（`loom_texture.py` L33-43 的 5 档是**运行时 GL internal_format**，不是离线 DXT），不引入 off-line 压缩（moderngl 无 BC 压缩 API，见该处注释 L33-34）。

### 2.7 引用解析与失败出声（问题 4）

```
加载场景：read data -> migrate() -> 建 index 视图（项目层 + 用户层 delta 合并）
  -> 每个引用：resolve(guid)
       命中 + stat 一致      -> 构建资产，valid=True
       命中 + 指纹不符      -> 用旧设置构建，valid=False, reason='源文件已变更…'
       未命中但 legacy_path -> 一次性迁移（见 2.8），成功则 valid=True
       未命中且无 legacy    -> valid=False, reason='guid 未在资产索引中（可能是别的项目/被删）'
       路径越界/非法类型    -> valid=False, reason='…'
  -> engine._asset_errors 汇总；命令 scene_assets_check 可查
```

- 对齐 beta5：**不抛异常、不静默**；返回 `(obj, valid, reason)`（同 `skybox_from_dict`）。
- 越界规则：资产正文**必须**落在 `<项目根>/Assets/` 内（用 `sceneio._inside_scene_dir` 同一实现 L609-628，换成项目根）——这是把 A3=B 规则从"场景目录"**上移**成"项目根"，而不是取消。

### 2.8 迁移（问题 5）

现有事实：`SCENE_VERSION = 10`（`sceneio.py` L57），`migrate()` L1471-1532 已有 v1→v10 全套就地升级；`skybox` 已经是"缺键/null → 默认蓝"的容错范式（L699-714）。

**方案：v10 → v11 就地迁移（不写回原值）+ 一次性落盘脚本。**

1. **读侧迁移**（`migrate()` 内新增 v<11 分支，纯内存）：
   - `skybox.paths`（相对场景目录）→ 逐面 join → 计算目录内容 sha256 集合 → `register()` 得 cubemap guid；成功则把 `skybox` 换成 `{"guid":…}`，失败则保留原键 + 标记 `_legacy_reason`；
   - `materials[].albedo/normal_map.path`（绝对）→ 存在则 `register()` 为贴图资产 → 换 guid；不存在 → `valid=False, reason='源图不存在' + 原 path`（**保留 path 作为一个版本内的 fallback**，见 ④ 风险 1）；
   - `materials[].env_map.paths` → 同上；
   - `objects[].params.obj` → beta6 **不迁**（模型批），保持"文件失效→立方体"但**加出声**（当前 L329-330 静默）。
2. **写侧**：一旦加载期间发生过任何自动迁移，`_save_scene` 按 v11 写出（只写 guid），并在通知栏说明"N 个资源已自动登记进项目资产库"。
3. **一次性脚本** `tools/migrate_scene_assets_v11.py`：批量处理 `examples/`、`Projects/`、`docs/audit/*.json` 与测试夹具，输出 `迁移报告.json`（每场景：迁移成功/失败逐条 reason）。**只跑一次，跑完删脚本**（符合"不新增兼容负担"，`用户配置目录契约` L3-10）。
4. **旧路径字段的去留**：v11 场景**规范上不含 path**；读侧 fallback 保留**一个 beta 版本**，随后删除（在报告中登记为后续待办，不写成永久分支）。

---

## ③ 分步落地计划（每步可验收、含测试点）

> 全部步骤都遵循：先有"可复现失败证据"，再有实现；验收以**沙箱里跑得起来的测试**为准，不用 AI 打分为准。

| 步 | 内容 | 验收标准（可执行） | 测试点 | 预估 |
|---|---|---|---|---|
| **S0** 立规 + 只读盘点 | 本报告裁决后定稿为 `docs/design/资产与GUID契约_<日期>.md`；新增只读扫描脚本（`tests/_tmp`），输出"现存场景里全部路径引用清单" | `python tests/_tmp/research_02_probe_asset_refs.py` 与 `_probe_b.py` 可复现 ① 全部结论；新扫描脚本对 `examples/` 产出清单 json | 不进 CI（临时工具）；清单作为 S4 迁移输入 | 0.5 人天 |
| **S1** 索引与解析内核 `assetdb.py` | 读写/校验/注册/解析/指纹；**不改任何现有行为**（无调用方） | 单测全绿；手工破坏 `assets.json` 不抛、给 reason | `test_assetdb_core.py`：① 重复 guid 检出 ② 非 uuid/空 guid 拒绝 ③ `src` 越界（`../`、绝对）拒绝 ④ 缺文件 reason ⑤ 损坏 JSON 不崩 ⑥ 原子写（写半截不破坏旧文件）⑦ 同 sha256 去重返回同 guid | 1.5 人天 |
| **S2** 贴图 guid 化（albedo/normal） | `asset_import`（贴图）+ 场景只写 guid + 读侧走 `resolve` + `_asset_errors` + `scene_assets_check` | **复现并修复探针 B 段**：改名项目目录后重载，`albedo` 仍有效且 `valid=True`；删源图后 `valid=False` 且 reason 明确 | `test_asset_guid_texture.py`：① 导入→存→换目录→重载贴图在 ② 源图删除→valid=False+reason ③ 源图改动（mtime 后 sha256 变）→stale 报告 ④ 同图两次导入→同 guid、只有一个文件 ⑤ 旧绝对路径场景→v11 迁移后可加载 ⑥ UI 未迁移场景加载不崩 | 2 人天 |
| **S3** 六面图 guid 化（场景/相机/材质 env） | cubemap 资产 = 目录资产；`skybox` 只写 guid；A3=B 规则上移为"项目根内" | `skybox_get` 仍返回 `valid/reason`（`agent_commands.py` L1126-1178 结构不变）；越界 guid → `valid=False` | `test_skybox_scene.py` 迁移（现有 172 处 skybox 断言中约 8-12 处涉及 paths）；新增：① 同一 cubemap 被场景+相机+材质三处引用，**改一次三处同变** ② 目录缺 1 面→reason 指出第几面 ③ 纯色 cubemap 仍可序列化/还原 | 1.5 人天 |
| **S4** v11 迁移 + 一次性脚本 | `migrate()` v<11 分支 + `tools/migrate_scene_assets_v11.py` | 脚本对 `examples/`、`docs/audit/*.json`、`tests/_tmp/ab_*.json` 产出逐条迁移报告；抽 3 个真实场景"迁移→载入→渲染前校验（`scene_assets_check`）全 valid" | `test_scene_migrate_v11.py`：① 相对 skybox paths→guid ② 绝对 albedo path→guid ③ 源图缺失→保留 reason 不崩 ④ 已是 v11 的场景幂等（再迁移不改文件）⑤ 未知版本仍降级不抛（L39 既有约束） | 1 人天 |
| **S5** 打包打通（资产随包） | `build_game` 收集被引用资产 → `game_pack` 增加 `assets` 段（按 sha256 去重）→ 播放器用包内 base | **端到端**：打包 → 把发布夹改名/移盘 → 启动 → 贴图与天空盒仍在；删包内一张图 → 出声 + reason | `test_build_assets_pack.py`（无窗口，只测 pack/load 结构）：① 引用 2 贴图 → 包内 2 条 ② 同图被 2 材质引用 → 1 条 ③ 旧包（无 assets 段）载入 → 出声不崩 | 1 人天 |
| **S6** 收尾 | 命令帮助、契约文档、全量回归 | `cd Loom` 跑 121 个 `test_*.py` 全绿；`test_eai_real.py` 的 `assets/asset_place/asset_save` 断言不变 | 回归清单见 ⑥ | 0.5 人天 |

**建议批次切法**：`S0+S1+S2+S3+S4`（贴图+六面图最小闭环，约 6.5 人天）先落地并让 `scene_assets_check` 可用；`S5` 打包单独一批（它改的是发布链，不阻塞编辑器可用性）。

---

## ④ 风险与回滚

| # | 风险 | 触发条件（证据） | 缓解 | 回滚 |
|---|---|---|---|---|
| R1 | 序列化格式变更让**存量场景全部丢贴图/天空盒** | 探针 B 段已证明：改绝对路径即静默丢 | ① `migrate()` 只升级内存，**首次保存才写新格式**；② 一个 β 版本内保留 `legacy_path` 读侧 fallback；③ 自动迁移必然打印"已登记 N 个资产" | `SCENE_VERSION` 改回 10 + 移除 v11 分支；`Assets/` 目录可整体删除（源图是复制的，原件未动） |
| R2 | **guid 碰撞导致错画** | VK 纹理缓存按 guid（`vk_renderer.py` L1432-1437）；GL 桶键含 `_tex_guid`（`loom_model_gpu.py` L110-117）；探针 D/G 段证明现在重复 guid **无告警** | 注册时全局查重（同 guid 不同 sha256 → 拒绝导入并报冲突）；`validate_index` 每次加载校验；场景内重复 guid 出声 | 索引校验失败 → 拒绝加载该批资产（`valid=False`）并允许 `asset_reimport` 重新分配 guid；不破坏场景其余部分 |
| R3 | `assets.json` 损坏 = 全项目资产失效（单点） | 集中方案固有 | 原子写（复用 `save_json_atomic` L1535-1545）+ 写前 `.bak-<时间戳>`（复用 `userpaths.backup_path` L69-79）+ 读失败不崩、只 `valid=False` | 回滚 = 用 `.bak` 覆盖；索引可由"扫 `Assets/` 重建"（指纹重算），不丢源图 |
| R4 | 性能：加载变慢/启动扫描 | 大项目 | 加载只读 `assets.json`（一次 JSON）+ 只对引用到的条目做 `stat`；**不做全量目录扫描**（现 `_scan_assets` 的做法只保留在资产面板） | 面板扫描可回退为"懒加载" |
| R5 | 双后端不一致（GL 直读 CPU 像素 / VK 按 guid 缓存） | `test_vk_material_tex_settings.py` 25 处断言 | 两侧都从**同一个** `resolve()` 出来的 `Texture` 对象取数据；guid 唯一性保证 VK 缓存键有效 | 保留 `LOOM_ASSET_LEGACY_PATH=1` 开关，退回路径模式（临时） |
| R6 | 与"不新增兼容负担"的开发声明冲突 | `用户配置目录契约` L3-10 | 一次性脚本 + 一个 β 周期的 fallback，**登记删除条件**；不写永久双格式 | 直接删除 fallback 分支（场景需再跑一次迁移） |
| R7 | 打包链回归（`build_game` 改动影响发包） | 发布链是 beta5 刚验证过的热点 | `assets` 段**追加**而非替换；无资产时输出空段，旧播放器忽略未知键 | 回滚 `game_pack.pack` 的 `assets` 参数默认 `None` |

---

## ⑤ 工作量估计（人天 / 会话数）

| 步 | 人天 | 会话 | 说明 |
|---|---|---|---|
| S0 | 0.5 | 1 | 报告定稿 + 只读清单工具 |
| S1 | 1.5 | 1 | 纯新增模块，最低风险 |
| S2 | 2.0 | 1.5 | 改 `_emit_material/_apply_materials` + 新命令 + 6 类测试 |
| S3 | 1.5 | 1 | 复用 `_inside_scene_dir`/valid-reason 范式，但触及天空盒测试面 |
| S4 | 1.0 | 1 | migrate 分支 + 一次性脚本 + 真实场景抽验 |
| S5 | 1.0 | 1 | 发布链，需端到端验证 |
| S6 | 0.5 | 0.5 | 回归 121 个测试 |
| **合计** | **8.0 人天** | **6–7 个会话** | 不含模型导入 |

- 模型导入（obj/gltf → 网格+材质子资源，含 `mesh.py` 的 MTL 解析升级、UV/贴图绑定）：**另立 4–6 人天**，建议 beta7。
- 若只做"贴图 + 背景板级六面图（不改打包）"：**S0+S1+S2 ≈ 4 人天 / 3 会话**。

---

## ⑥ 与现有代码的兼容边界

**必须保持的契约（改了就红测试/红功能）**

| 契约 | 位置 | 保持方式 |
|---|---|---|
| `skybox_from_dict -> (cube, valid, reason)` 三元组 | `sceneio.py` L631-688 | 新增 `cubemap_from_ref`，**签名同构**；旧函数保留给迁移期 |
| 引擎 `_skybox_valid/_skybox_error` + `skybox_get` 返回字段 | `sceneio.py` L1426-1432；`agent_commands.py` L1126-1178 | 不动；新增并行字段（`assets_ok`） |
| `_find_material(guid)` = 场景内材质库查找 | `loom_model_gpu.py` L66-72 | 语义不变（先查场景库，再查资产库——**追加**而非替换） |
| 预制体 guid 语义（实例重生成 guid + `prefab_ref`） | `sceneio.py` L1686-1708 | 不动 |
| `assets/asset_place/asset_save` 返回结构 | `agent_commands.py` L2236-2295；`test_eai_real.py` 9 处 | 只允许**新增键/新增 type**，不改既有键名 |
| `save_json_atomic`（tmp+fsync+replace） | `sceneio.py` L1535-1545 | 索引写入复用 |
| 写路径白名单（程序目录/场景目录/用户目录/Temp） | `agent_commands.py` L84-119 | 资产导入的**写入目标**必须落在白名单内 → 进一步支持"资产放项目根（=场景目录）"而非引擎目录 |

**明确要改的边界**

| 对象 | 现状 | 目标 | 影响面 |
|---|---|---|---|
| 场景 `materials[].albedo/normal_map/env_map` | 含绝对 `path` | 仅 `guid`（+可选 import 覆盖） | `_emit_material` L871-901、`_apply_materials` L904-955、`save_material_asset` L1620-1622 |
| `skybox` / `cameras[].skybox` | 相对 `paths` | `{"guid":…}` 或 `solid_color` | L723-809、L1383-1404、`skybox_set` L1001-1061 |
| `_apply_materials` 签名 | `(engine, mat_dicts)` | 追加 `resolver`（关键字参数，默认 `None`=旧行为） | L904、L1437（唯一调用点） |
| `Texture.path` 语义 | "源文件路径（绝对），会落盘" | "解析结果（绝对），**不落盘**" | `loom_texture.py` L48-50/L122 |
| `assets/meshes/*.json` 的 `id` | 死身份 | 要么被场景引用（模型批），要么**不再生成** | `sceneio.py` L1640-1646 |
| `Loom/材质`（散落单文件资产）、`Loom/assets/假车库.mtl` | 引擎目录散落 | 收敛到项目 `Assets/`（或转模板层内置） | 文件迁移，非代码 |
| 引擎目录 `Loom/assets/` | 资产库 | **降级**为"模板层内置资产"（只读） | `editor.py` L1375/L1529/L1550；`tools/package_engine.py` L23-24 |

**受影响测试清单（预计需要改动的断言点）**

| 测试文件 | 命中数 | 预计改点 |
|---|---|---|
| `test_skybox_scene.py` | 172 | 约 10-14 处（paths 断言 → guid 断言） |
| `test_skybox_engine_parity.py` | 39 | 少量（引擎侧只读 `effective_skybox`） |
| `test_vk_material_tex_settings.py` | 25 | 3-5 处（材质`_tex_guid` 不变，构造方式变） |
| `test_texture.py` | 17 | 2-4 处（`Texture.path` 语义） |
| `test_scene_solid_env_roundtrip.py` | 11 | 2 处（env 形态） |
| `test_assetbrowser.py` | 6 | 2 处（`_scan_assets` 新增类型） |
| `test_eai_real.py` | 9 | **0 处**（必须不变，作为回归闸门） |
| `test_undo_full_coverage.py`、`test_scene_material_no_growth.py` | 10+2 | 1-2 处 |

---

## ⑦ 需要人类裁决的封闭问题

每条都给"默认建议"；未裁决前不进入实现（S0 之后停）。

| # | 问题 | 选项 | 建议 |
|---|---|---|---|
| Q1 | 资产索引载体 | A 集中 `Assets/assets.json` / B 每资产 `.meta` / C 两者 | **A**（证据：仓库现有资产=单 JSON、`save_json_atomic` 现成、无 .meta 先例） |
| Q2 | 导入语义 | A 复制进项目 / B 引用原位 / C 复制+大文件链接 | **A**（B 必死：探针 B 段 + `build_game` 不打资产） |
| Q3 | 资产根目录 | A 项目根 `Assets/`（新）/ B 复用 `Loom/assets/`（现）/ C 项目根 `assets/`（小写，沿用旧名） | **A** 或 C（**不能是 B**：`package_engine.py` L23-24 明确排除 `assets`，且 `APP_DIR` 是引擎目录，多项目会互相污染）。倾向 **A**（与 `Projects/` 首字母大写风格一致） |
| Q4 | 项目根的判定 | A 场景目录向上找 `Assets/` 或 `.loom/project_id` / B 场景目录本身 / C 显式设置 | **A**（复用 `userpaths.project_id` L115-140；找不到时**退化=B 并出声**） |
| Q5 | 旧场景迁移 | A `migrate()` 内存升级 + 一次性脚本 + 一个 β 周期的 path fallback / B 只内存升级不落盘 / C 直接拒绝旧文件 | **A**（C 会毁存量 4 个真实场景：`examples/PacMan2D.json`、`docs/audit/pacman{2,3}d_scene.json` 等） |
| Q6 | 六面图"必须在目录内"的边界 | A 项目根内（上移） / B 保持场景目录 / C 放开 | **A**（否则与"项目资产库"矛盾；且 A3=B 的人类裁决意图是"不许越权读盘"） |
| Q7 | 同内容不同文件名 | A 按 sha256 去重（同 guid） / B 各自独立 guid | **A**（省空间、避免"改一张图要改两处"；代价：文件名不是身份） |
| Q8 | 贴图压缩 | A 只记 import 设置（运行时 5 档） / B 离线 DXT/BC | **A**（moderngl 无 BC API，`loom_texture.py` L33-34 注释已说明） |
| Q9 | 引擎目录既有资产（`Loom/材质`、`assets/假车库.mtl`、`assets/图像素材/`） | A 转模板层内置（逻辑 guid） / B 删除 / C 原样保留 | **A**（`图像素材` 被 UI 示例引用；`材质` 是散落单文件，建议 B） |
| Q10 | 打包时资产形态 | A 明文 `assets/` 随包（可按 hash 去重/可 patch） / B 加密进 `.lsc` | **A**（beta6 目标只是"能加载"，加密属保护策略，且 `.lsc` 已含场景明文语义） |
| Q11 | guid 是否跨项目全局唯一 | A 是（uuid4 + 索引内查重） / B 仅项目内 | **A**（uuid4 天然全局；跨项目碰撞只可能来自手改文件，加载时报冲突即可） |
| Q12 | 模型导入排期 | A beta6 只做贴图+六面图+材质（本报告） / B 同批做 obj 子资源 | **A**（`mesh.py` L335-339 目前把 MTL 烘进 face_colors，先有材质引用体系再谈子资源） |

---

### 附：可复现证据索引

| 结论 | 复现命令 | 关键输出 |
|---|---|---|
| 贴图/环境贴图落盘为绝对路径，天空盒为相对 | `python tests/_tmp/research_02_probe_asset_refs.py`（A 段） | `albedo 绝对? True / env 绝对? True / skybox 绝对? False` |
| 换机后贴图与 env 静默丢失 | 同上（B 段） | `albedo 恢复? False / env_map 恢复? False`，stdout 无相关告警 |
| 材质 env 相对路径按 CWD 解析且静默 | 同上（C 段） | `env_map 恢复? False`，stdout `<空>` |
| 场景内重复 guid 无告警、首条胜出 | 同上（D 段） | `['dup','dup']` / 物体拿到 `red` |
| 贴图越界被接受（对比天空盒拒绝） | 同上（E 段） | `albedo 恢复? True`；同路径给天空盒 → `valid=False reason='…必须放在场景目录…'` |
| 同文件两次导入 → 不同 guid（无内容去重） | 同上（F 段） | `相同? False` |
| guid 被原样信任、同 guid 两文件共存 | 同上（G 段） | `['SAME','SAME']` |
| obj 丢失 → 静默变立方体 | `python tests/_tmp/research_02_probe_b.py`（H 段） | `primitive = cube`，stdout `<空>` |
| 材质资产文件不参与加载（PBR/名字丢失） | 同上（I 段） | `('ASSETM','材质','#00FF00',False,0.0,0.5)` |
| 无 `.meta` / 无 `assets.json` | `glob "**/*.meta"`；`grep "assets\.json"` | 0 / 0 |
| 真实场景里确有绝对路径 | `Loom/tests/_tmp/ab_tex.json` L24 | `"path": "D:\\my-project - 副本\\…\\checker.png"` |
| 引擎包/游戏包都不带资产 | `tools/package_engine.py` L23-24；`build_game.py` L195-200/L221-240/L278-279 | `EXCLUDE_DIRS` 含 `assets`；只 pack scene/scripts/config |

> 备注：本报告未修改任何受跟踪文件；探针脚本位于 `Loom/tests/_tmp/`（`Loom/.gitignore` 已忽略 `tests/_tmp/*`），所有运行产物写系统临时目录。
