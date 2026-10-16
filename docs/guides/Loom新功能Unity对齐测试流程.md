# Loom 新功能 Unity 对齐测试流程

> 版本：2026-10-13
> 适用：给 Loom **新增/修改任一功能**后，验证其行为是否与 Unity 等价。
> 环境：Loom 源码版 + Unity 2022.3.62f3c1（`E:\Program Files\Unity\2022.3.62f3c1\Editor\Unity.exe`）
> 原则：**截图 + MCP 实操 + Unity 对照 + 多数据注入**。不靠"看代码觉得对"，靠"跑出来的画面和数值对"。

---

## 〇、这份流程解决什么问题

新增一个功能后，最常见的自欺是："代码逻辑看起来对"。本流程强制四件事：

1. **单次 MCP 操作前后两段截图** —— 证明这一次操作真的生效、且效果符合预期
2. **Unity 等价操作前后两段截图** —— 拿到"标准答案"（Ground Truth）
3. **同一操作多组不同数据** —— 证明不是只对某一个值对，而是各情况下都对
4. **边界/异常数据** —— 证明不会在极端输入下崩/歪

只有四条全过，才判定"该功能与 Unity 对齐"。

---

## 一、环境准备（一次性，做完就不用再管）

### 1.1 Loom 侧
- 源码版本：`D:\my-project\Loom(py源代码-工作区)\Loom\`
- MCP 服务：`loom_mcp.py`（stdio），接入方式见项目级 `.mcp.json`
- 引擎启动：必须带 `--agent` 参数才会开 EAI 命令桥（HTTP 127.0.0.1 + `.agent_port.json`）
- 截图输出：默认 `保存/shot_<uuid>.png`，也可指定 `file=` 参数

### 1.2 Unity 侧（需要先准备一个对照项目）
当前这台机器上的 Unity **还没有可用的对照项目**。需先做一次：

1. 用 Unity Hub 或命令行建一个空项目，例如：
   ```
   E:\UnityAlign\AlignProject\   (3D Core 模板, 2022.3.62f3c1)
   ```
2. 在项目 `Assets/Editor/` 下放一个自动化脚本 `AlignRunner.cs`（骨架见第五节），
   支持通过命令行 `-executeMethod AlignRunner.Run` 接收 JSON 操作清单 → 执行 → 截图 → 输出结果 JSON。
3. 命令行调用（无头）：
   ```powershell
   & "E:\Program Files\Unity\2022.3.62f3c1\Editor\Unity.exe" ^
     -batchmode -nographics -quit ^
     -projectPath "E:\UnityAlign\AlignProject" ^
     -executeMethod AlignRunner.Run ^
     -logFile "E:\UnityAlign\logs\run.log" ^
     -alignOps "E:\UnityAlign\ops\current.json"
   ```
   > ⚠️ `-nographics` 下无法读回渲染画面像素。需要截图时必须去掉 `-nographics`（依赖 GPU/OpenGL）。
   > 若目标是纯逻辑对齐（变换数值、碰撞结果等），`-nographics` 更快；若是视觉对齐，去掉它。

3. 每次对照跑完，从 Unity 项目里取两张截图 + 一份结果 JSON。

### 1.3 截图与结果存放约定
```
D:\my-project\_align_tests\
  └─ <功能名>_<日期>_<序号>\
       ├─ loom_before.png
       ├─ loom_after.png
       ├─ unity_before.png
       ├─ unity_after.png
       ├─ loom_result.json
       ├─ unity_result.json
       └─ verdict.md        (人工/自动对比结论)
```

---

## 二、标准测试流程（每新增一个功能，重复走一遍）

### Step 0：启动修改后的 Loom + 连接 MCP
1. 关闭任何旧的 Loom 进程（避免旧端口文件残留）
2. 启动：`py -3.12 Loom.py --open 保存/场景.json --agent`（或空场景）
3. 等 `.agent_port.json` 出现且 `pid` 对应本次进程
4. 通过 MCP 客户端确认连通：`tools/list` 返回 24 个工具

### Step 1：Loom 侧单次操作 + 前后截图
对目标功能，用 MCP 一次调用完成一个原子操作：
1. `unity_capture_viewport` → 存 `loom_before.png`
2. 执行目标操作（例如 `unity_gameobject_create` / `unity_transform_set` / 新功能对应工具）
3. `unity_capture_viewport` → 存 `loom_after.png`
4. 拉取状态（`diag_inspect_gameobject` / `diag_get_engine_metrics`）存 `loom_result.json`

**判定点**：before/after 两图差异 = 该操作应有的视觉变化（不多不少）；数值（result.json）符合预期。

### Step 2：Unity 侧等价操作 + 前后截图
1. 在 Unity 对照项目里，用 C# 脚本执行**语义等价**的操作
2. 操作前 `AlignRunner` 截图 → `unity_before.png`
3. 执行操作
4. 操作后截图 → `unity_after.png`
5. 导出关键数值（position/rotation/scale/碰撞结果/…）→ `unity_result.json`

### Step 3：对照判定
按第三节判定标准逐条比对：
- 视觉：两张 before 应"同源场景"，两张 after 应呈现**等价变化**
- 数值：loom_result 与 unity_result 的对应字段应一致（在容差内）
- 副作用：不该出现的对象/状态变化，两边都不能有

### Step 4：多数据注入（核心步骤）
**同一操作至少用 5 组不同数据跑一遍**，覆盖：
- 正数 / 负数 / 零
- 小值 / 大值 / 极大值
- 边界值（如旋转 ±180°、缩放 0、位置极远）

对每组数据重复 Step 1~3，把结论累加到 `verdict.md`。

### Step 5：边界/异常数据
额外注入：
- 非法类型（字符串/None/空）
- 越界值（FOV > 180、质量为负、缩放为 0）
- 并发/连续操作（连点、快速切换）

判定：**不崩**（引擎不 crash、不卡死）+ **行为可解释**（与 Unity 一致或明确不同且已知原因）。

### Step 6：结论 + 记录
在 `verdict.md` 写：
```
功能：<名称>
测试时间：<日期>
通过：✅ / ❌
对齐度：N/5 组数据完全对齐
不对齐项：（列出 + 截图编号 + 数值差异 + 推测原因）
Unity 版本：2022.3.62f3c1
Loom commit：<git hash>
```

---

## 三、判定标准（什么算"对齐"）

| 维度 | 对齐定义 | 容差 |
|------|---------|------|
| 变换数值 | position/rotation/scale 字段一致 | 浮点 `1e-4` |
| 视觉呈现 | after 截图的物体外观/位置/颜色一致 | 肉眼可辨即算差异 |
| 层级关系 | parent/children 结构一致 | 精确 |
| 物理结果 | 碰撞/重力/摩擦后的位姿一致 | `1e-2`（物理引擎不同，允许小差） |
| UI 布局 | 控件位置/尺寸/文字一致 | 像素级肉眼比对 |
| 边界行为 | 越界输入的处理方式一致（都夹紧/都报错/都忽略） | 语义一致 |
| 崩溃行为 | 都不崩 | 精确 |

**判定分级**：
- 🟢 **完全对齐**：所有维度在容差内
- 🟡 **部分对齐**：数值对但视觉有差（或反之），需记录差异点
- 🔴 **不对齐**：核心行为方向不同（如 Loom 移动而 Unity 旋转）

---

## 四、结果记录表模板

每次功能测试填一行（追加到项目根的 `_align_tests/RESULTS.md`）：

```markdown
| 功能 | 日期 | Loom commit | 数据组数 | 对齐度 | 结论 | 截图目录 |
|------|------|------------|---------|--------|------|---------|
| 变换-位置 | 2026-10-13 | a1b2c3d | 5/5 | 🟢 | 通过 | _align_tests/transform_pos_20261013_01/ |
| 光照-点光 | 2026-10-13 | a1b2c3d | 3/5 | 🟡 | 大距离衰减不齐 | _align_tests/pointlight_20261013_02/ |
```

---

## 五、自动化骨架

### 5.1 Loom 侧驱动（Python，走 MCP stdio）
```python
# align_loom.py — 单功能 Loom 侧执行 + 双截图
import json, subprocess, sys, os, time

LOOM = r"D:\my-project\Loom(py源代码-工作区)\Loom"
p = subprocess.Popen(['py', '-3.12', os.path.join(LOOM, 'loom_mcp.py')],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    cwd=LOOM, text=True, encoding='utf-8', bufsize=1)

_id = [0]
def call(tool, args=None):
    _id[0] += 1
    p.stdin.write(json.dumps({'jsonrpc':'2.0','id':_id[0],'method':'tools/call',
        'params':{'name':tool,'arguments':args or {}}}) + '\n')
    p.stdin.flush()
    return json.loads(p.stdout.readline())

def shot(path):
    call('unity_capture_viewport', {'path': path})
    time.sleep(0.3)

# 握手
p.stdin.write(json.dumps({'jsonrpc':'2.0','id':99,'method':'initialize',
    'params':{'protocolVersion':'2024-11-05','capabilities':{}}}) + '\n')
p.stdin.flush(); p.stdout.readline()
p.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'}) + '\n')
p.stdin.flush()

# 用例：创建物体 → 前后截图 → 改位置 → 前后截图
def case(name, op, args, out_dir):
    shot(os.path.join(out_dir, f'{name}_before.png'))
    r = call(op, args)
    time.sleep(0.5)
    shot(os.path.join(out_dir, f'{name}_after.png'))
    return r

if __name__ == '__main__':
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    r = case('create', 'unity_gameobject_create',
             {'primitive':'cube','name':'A','position':[2,1,0]}, out)
    print(json.dumps(r, ensure_ascii=False)[:300])
    p.stdin.close(); p.terminate()
```

### 5.2 Unity 侧驱动（C# Editor 脚本骨架，放 Unity 项目 `Assets/Editor/AlignRunner.cs`）
```csharp
// AlignRunner.cs — 命令行批处理: 执行 JSON 操作清单 + 截图 + 输出结果
using UnityEditor;
using UnityEngine;
using System.IO;

public static class AlignRunner {
    public static void Run() {
        string opsPath = GetArg("-alignOps");
        var ops = JsonUtility.FromJson<OpList>(File.ReadAllText(opsPath));
        string outDir = Path.GetDirectoryName(opsPath);
        foreach (var op in ops.ops) {
            ExecuteOp(op);
            if (op.captureAfter) CaptureView(outDir, op.name + "_after.png");
        }
        // 写出结果 JSON
        File.WriteAllText(Path.Combine(outDir, "unity_result.json"),
            JsonUtility.ToJson(new Result{ ok = true }));
        EditorApplication.Exit(0);
    }
    static void ExecuteOp(Op op) {
        // 按 op.type 分派: create / set_transform / material / light ...
        // 与 Loom MCP 工具语义一一对应
    }
    static void CaptureView(string dir, string name) {
        var cam = Camera.main;
        var rt = new RenderTexture(1280, 800, 24);
        cam.targetTexture = rt;
        cam.Render();
        RenderTexture.active = rt;
        var tex = new Texture2D(1280, 800, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0,0,1280,800), 0, 0);
        tex.Apply();
        File.WriteAllBytes(Path.Combine(dir, name), tex.EncodeToPNG());
        cam.targetTexture = null;
    }
    static string GetArg(string key) {
        var a = System.Environment.GetCommandLineArgs();
        for (int i = 0; i < a.Length-1; i++) if (a[i] == key) return a[i+1];
        return null;
    }
    [System.Serializable] public class OpList { public Op[] ops; }
    [System.Serializable] public class Op { public string type; public string name; public bool captureAfter; /*...*/ }
    [System.Serializable] public class Result { public bool ok; }
}
```

### 5.3 一键对照（Python 编排）
```powershell
# 1) Loom 侧跑 + 截图
py align_loom.py D:\my-project\_align_tests\transform_pos_20261013_01
# 2) Unity 侧跑 + 截图
& "E:\Program Files\Unity\2022.3.62f3c1\Editor\Unity.exe" -batchmode -quit ^
  -projectPath "E:\UnityAlign\AlignProject" ^
  -executeMethod AlignRunner.Run ^
  -alignOps "D:\my-project\_align_tests\transform_pos_20261013_01\ops.json"
# 3) 对比 + 生成 verdict.md（可用图像 diff + 数值 diff 脚本）
```

---

## 六、常见陷阱与注意事项

1. **`-nographics` 无法截图** —— 要视觉对齐必须去掉；纯数值对齐可保留（更快）。
2. **Unity 首次跑对照项目会编译脚本**，第一次慢（30s~2min），之后快。
3. **Loom 端口文件残留** —— 上次引擎没退干净时 `.agent_port.json` 会指向死进程，启动前先删。
4. **场景不一致** —— Loom 和 Unity 起始场景必须是"同源"（同数量/同位置物体），否则截图无法对照。建议两边用同一份 `场景.json` 语义转换。
5. **物理引擎差异** —— Loom 用 Jolt，Unity 用 PhysX，复杂碰撞下位姿不可能逐位一致，判据放宽到"行为方向一致 + 收敛结果接近"。
6. **坐标系** —— 两者都是 Y-up 左手/Z 前，但旋转表示（欧拉顺序）可能不同，对照旋转要小心。
7. **截图分辨率/相机** —— 两边相机位置/FOV 必须对齐，否则同一场景视觉不同是"相机差异"不是"功能差异"。
8. **多数据注入至少 5 组** —— 少于 5 组不算过关；能覆盖 3 个量级的极值更佳。

---

## 七、当前已知不对齐项（持续更新）

| 功能 | Loom 现状 | Unity 行为 | 差异 | 优先级 |
|------|----------|-----------|------|--------|
| 骨骼动画 | 无 | SkinnedMeshRenderer + Avatar | 完全缺失 | P0 |
| 纹理贴图 | 仅单色 | Texture + Shader | 完全缺失 | P0 |
| 模型导入 | 仅 .obj | .fbx/.gltf/.obj/... | 格式少 | P1 |
| 聚光灯 | 无（仅平行/点光） | Spot Light | 缺失 | P1 |
| 关节 | 无 | Joint 系列 | 缺失 | P2 |
| 粒子 | 无 | ParticleSystem | 缺失 | P2 |
| 导航寻路 | 无 | NavMesh | 缺失 | P2 |

---

## 八、给用户的操作清单（每次新功能后照做）

1. [ ] 关闭旧 Loom 进程
2. [ ] 启动修改后的 Loom（`--agent`）
3. [ ] 连接 MCP 工具（确认 24 tools）
4. [ ] 新建对照目录 `_align_tests/<功能>_<日期>_<序号>/`
5. [ ] 写本次功能的 `ops.json`（Loom 与 Unity 各一份等价操作清单，含 5+ 组数据）
6. [ ] 跑 Loom 侧 → 收 before/after 截图 + result
7. [ ] 跑 Unity 侧 → 收 before/after 截图 + result
8. [ ] 逐维度比对 → 填 `verdict.md`
9. [ ] 追加一行到 `_align_tests/RESULTS.md`
10. [ ] 若不对齐，回到代码修 → 重跑本流程

---

*本流程文件为"新功能对齐 Unity"的协议约定（2026-10-13 起生效）。首次使用需先完成 1.2 的 Unity 对照项目准备。*
