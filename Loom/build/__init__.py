"""build/ — 构建/发布域（目录重构 B6 批，2026-11-21）。

模块（原 Loom 根 build_game.py / game_pack.py）：
  build_game.py  游戏构建器（Unity BuildPipeline 对齐；Nuitka 运行时打包）
  game_pack.py   游戏资源包 .lsc（加密打包/解包/插件包）

BIN_DIR 定位走 sys.argv[0]/__file__ 逐级上溯（源码版深一层仍解析到 Loom/）。
刻意不 re-export。
"""
