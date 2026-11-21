"""assets/ — 资产域（目录重构 B6 批，2026-11-21）。

模块（原 Loom 根 loom_assets/loom_texture/loom_cubemap/loom_material.py）：
  assets.py    资产身份层（项目级 Assets/ + assets.json + guid 引用）
  texture.py   纹理资产 (M36)
  cubemap.py   立方体贴图资产 (M36)
  material.py  材质资产 (M23)

注意: 本目录同时是**数据目录**（meshes/ materials/ 图像素材/ …），
测试/工具的生产源码扫描原本就排除 assets/ 目录（数据混放是历史布局）。
loom_appearance 外观代计数器不在此包 —— 已于 B3 归 render/contract/appearance.py
（以实际 import 关系为准：只被渲染链使用）。
刻意不 re-export。
"""
