# -*- coding: utf-8 -*-
"""LoomHub.py — LoomHub 项目管理器入口 (薄).

GUI 界面组件在 LoomHubGUI.py (类 LoomHubGUI, IHubView 默认实现, 可替换).
启动: py -3.12 LoomHub.py  (等效 py -3.12 LoomHubGUI.py)
换界面 = 新写一个 IHubView 实现替换 LoomHubGUI."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 2026-10-19 单实例锁：防止 PyInstaller --onefile 启动慢时用户连点导致多开窗口。
# 放在所有 import 之前——第一个实例才继续往下执行，否则本进程直接退出。
from hub_single_instance import ensure_single_instance
ensure_single_instance('LoomHub — 项目管理器', 'Global\\LoomHub_SingleInstance')

from LoomHubGUI import LoomHubGUI, main   # noqa: F401  (LoomHubGUI 供测试/外部 import)

if __name__ == "__main__":
    if '--agent' in sys.argv:
        # 2026-08-27 HUB-EAI: 启动命令桥 (.hub_agent_port.json) →
        # Agent 全链路: 引擎/项目列表 → 导入/安装/默认 → 项目创建/导入 →
        # launch_engine 启动 Loom (GUI 同款环境) → Loom 侧 --agent 继续
        sys.argv.remove('--agent')
        import hub_commands
        _svc = hub_commands.HubService()
        try:
            _svc.start()
        except Exception as e:
            print('[hub-agent] HUB-EAI 启动失败: %r' % e)
        try:
            main()
        finally:
            _svc.stop()
    else:
        main()
