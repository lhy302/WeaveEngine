# -*- coding: utf-8 -*-
"""scene/ — 场景数据层（按域拆分，目录重构 B2 批 Q-B7-38-1，2026-11-21）。

成员（旧 sceneio.py 2220 行按域拆 + 契约/实体/查询三模块归位）:
  contract   场景契约：版本号 / 闸门 gate / 迁移 migrate / 唯一入口 prepare
  entities   场景实体状态类（LightState / CameraState / direction_to_angles；
             wrap_deg 实现仍在 mathlib.mathutil，此处 re-export）
  query      SceneQueryMixin —— Layer·Tag / 查找 / SendMessage（后端无关）
  identity   ★ guid 唯一真源：new_guid()（uuid4，新对象身份）+
             derived_guid()（迁移期确定性派生，同输入同输出）
  asset      资产身份层（资产上下文 / 资产问题登记 / 失效引用保留）
  object     对象 <-> dict（含父链校验/建链 + Canvas UI 段序列化）
  camera     相机投影归一（ortho/fov/布尔）+ 摄像机实体序列化
  light      光源序列化
  sky        天空盒解析/发射（Q1/Q4/Q5/Q6/A3=B 白盒契约）
  material   材质资产解析/发射（Q-B1-3=A 资产库唯一真相源）
  resource   独立资产文件（材质/网格；M24 资源浏览器）
  prefab     Prefab 序列化/实例化（M16）
  io         场景装配（scene_to_dict / scene_from_dict，吃 prepare 的结果）+
             存盘/读盘 + LOOMSC1 混淆编码

纪律：本 __init__ **刻意不** re-export 任何成员 —— scene.io/object 等会拉起
loom_components（numpy）引擎图，而契约 scene.contract 必须能「零 numpy/零 GPU」
单独 import（test_scene_contract A3 钉住）。取用一律显式：
    from scene.contract import prepare
旧引用面：sceneio.py 保留为**薄门面**，re-export 全部旧名（外部引用 0 行改动）。
"""
