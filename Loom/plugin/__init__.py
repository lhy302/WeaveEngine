"""plugin/ — 插件系统域（目录重构 B6 批，2026-11-21）。

模块（原 Loom 根 plugin_loader.py / plugin_sandbox.py）：
  loader.py   L1 分级插件加载器（信任/回滚/受限沙箱接线）
  sandbox.py  受限沙箱内核（V06/P-01/P-02 收口；**零模块级 import** 纪律不变）

安全面零变化：白名单仍是纯标准库八件（math/re/...），引擎模块一律
不在白名单 —— 搬家不改 restricted_import 判据。刻意不 re-export。
"""
