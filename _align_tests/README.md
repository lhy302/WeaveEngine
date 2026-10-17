# Loom ↔ Unity 对齐测试 —— 工具与用法

本目录是一套自动化对齐测试脚手架, 配套文档:
  docs/guides/Loom新功能Unity对齐测试流程.md

## 一次性准备

1. 创建 Unity 对照项目 (只需一次):
   运行 `tools/create_unity_project.ps1`
   → 生成 E:\UnityAlign\AlignProject

2. 把 `tools/AlignRunner.cs` 复制到 Unity 项目的 `Assets/Editor/` 下。

3. (可选) 在 Unity 项目里建一个固定相机 (位置/朝向对齐 Loom 的测试视角),
   若没有, AlignRunner 会自动建一个。

## 每次新功能对齐测试

1. 建 case 目录: `_align_tests/<功能>_<日期>_<序号>/`
2. 写 `ops.json` (格式见下)
3. 启动 Loom (带 --agent)
4. 跑 Loom 侧: `py _align_tests/tools/align_loom.py <case_dir>`
5. 跑 Unity 侧:
   ```
   & "E:\Program Files\Unity\2022.3.62f3c1\Editor\Unity.exe" ^
     -batchmode -quit ^
     -projectPath "E:\UnityAlign\AlignProject" ^
     -executeMethod AlignRunner.Run ^
     -alignOps "<case_dir>\ops.json"
   ```
6. 自动对比:
   `py _align_tests/tools/compare.py <case_dir>`
   → 生成 <case_dir>/verdict.md (操作成功性 + 截图变化机械核对)
7. (人工) 看图 + 比对 result.json 字段, 完善 verdict.md
8. 追加结果到 ../RESULTS.md

## 目录布局 (每个 case 目录)

```
<case_dir>/
  ops.json              操作清单 (两侧共用)
  <name>_before.png     Loom 操作前
  <name>_after.png      Loom 操作后
  loom_result.json      Loom 侧结果 (align_loom.py 产出)
  unity/                ← Unity 侧截图放这 (避免与 Loom 撞名)
    <name>_before.png
    <name>_after.png
  unity_result.json     Unity 侧结果 (AlignRunner.cs 产出)
  verdict.md            对比结论 (compare.py 产出)
```

## ops.json 格式

```json
{
  "cases": [
    {"name": "pos_01", "op": "unity_transform_set",
     "args": {"name_or_id": "A", "position": [2, 1, 0]}},
    {"name": "pos_02", "op": "unity_transform_set",
     "args": {"name_or_id": "A", "position": [-5, 10, 3]}}
  ]
}
```

注意: Loom 侧和 Unity 侧的 ops.json 共用一份; Unity 侧字段名做了映射
(rotation → rotation_deg, 详见 AlignRunner.cs)。
