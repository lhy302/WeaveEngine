"""physics/ — 物理域（目录重构 B6 批，2026-11-21）。

模块：
  physics.py   GLEngine 碰撞(M28)+刚体物理(M31) 混合层（原 loom_physics.py）
  bridge.py    Culverin(Jolt) 物理桥，零 GL 可独立导入（原 physics_bridge.py）
  glue.py      基座 <-> physics.dll 接线层（原 physics_glue.py）
  pipe.py      常驻物理线程 v2（原 physics_pipe.py）

刻意不 re-export（与 scene/ render/ 同口径）：physics.bridge 必须能
"零 GL / 无库自动禁用" 单独导入，包级 import 不许拉起混合层。
"""
