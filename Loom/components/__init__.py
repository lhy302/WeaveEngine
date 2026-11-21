"""components/ — 组件/实体域（目录重构 B6 批，2026-11-21）。

模块（原 Loom 根 loom_components/loom_game_object/loom_frame_components/
loom_transform/loom_collision/loom_raycast/loom_model_data.py）：
  components.py        Component 家族 + AnimationClip/Animator + 动画快路径
  game_object.py       GameObject 容器 (M25)
  frame_components.py  每帧组件推进子系统（音频/动画/碰撞回调）
  transform.py         变换层次子系统
  collision.py         碰撞配对/事件派发共享实现（两端同一份）
  raycast.py           射线检测子系统
  model_data.py        模型/材质/光源数据面（后端无关）

AudioSystem 不在本包 —— 已按域拆 audio/system.py（见该模块 docstring）。
刻意不 re-export（numpy 链，包级 import 保持零重依赖）。
"""
