"""script/ — 脚本域（目录重构 B6 批，2026-11-21）。

模块：
  scripts.py    物体脚本系统 (M27)（原 Loom/scripts.py；旧名 scripts 经
                sys.modules 别名兼容仓外用户脚本，见该文件尾部）
  glue.py       基座 <-> script.dll 接线层 (M4)（原 script_glue.py）
  scheduler.py  NgilPool 常驻 nogil 工作池（原 scheduler.py）

注意: 本包与数据目录 Loom/scripts/（用户游戏脚本 .py/.lua）是两回事。
刻意不 re-export。
"""
