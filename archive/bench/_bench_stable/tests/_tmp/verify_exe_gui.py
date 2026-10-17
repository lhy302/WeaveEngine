# -*- coding: utf-8 -*-
"""编译版 GUI 系统验证 (2026-08-14): 坏 GUI 回退 + 外部自定义 GUI 加载(标记文件)."""
import os
import json
import subprocess
import time

REL = r"D:\my-project\Loom(编译版本)"
ok = True


def check(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        ok = False


def launch(path, seconds=6):
    p = subprocess.Popen([path])
    time.sleep(seconds)
    alive = p.poll() is None
    if alive:
        p.kill()
    return alive


# ---- 1) 坏 GUI 回退 (Loom.exe) ----
loom = os.path.join(REL, "Loom")
gui_dir = os.path.join(loom, "GUI")
os.makedirs(gui_dir, exist_ok=True)
broken = os.path.join(gui_dir, "BrokenGUI.py")
with open(broken, "w", encoding="utf-8") as f:
    f.write("# gui: loom\nraise RuntimeError(\"boom 坏文件\")\n")
with open(os.path.join(loom, "设置.json"), "w", encoding="utf-8") as f:
    json.dump({"gui": "BrokenGUI", "save_dir": ""}, f, ensure_ascii=False)
alive = launch(os.path.join(loom, "Loom.exe"))
s = json.load(open(os.path.join(loom, "设置.json"), encoding="utf-8"))
check("Loom.exe 坏GUI 启动不崩(回退官方)", alive)
check("回退后 设置.json.gui = LoomGUI", s.get("gui") == "LoomGUI", s.get("gui"))
os.remove(broken)
with open(os.path.join(loom, "设置.json"), "w", encoding="utf-8") as f:
    json.dump({"gui": "LoomGUI", "save_dir": ""}, f, ensure_ascii=False)

# ---- 2) 外部自定义 GUI 真正被加载 (LoomHub.exe 写标记文件) ----
hub = os.path.join(REL, "LoomHub")
gui_dir2 = os.path.join(hub, "GUI")
marker = os.path.join(gui_dir2, "marker_loaded.txt")
if os.path.exists(marker):
    os.remove(marker)
with open(os.path.join(gui_dir2, "标记HubGUI.py"), "w", encoding="utf-8") as f:
    f.write(
        "# -*- coding: utf-8 -*-\n"
        "# gui: loomhub\n"
        "# gui-name: 标记验证\n"
        "import os, sys\n"
        "import pygame\n"
        "HERE = os.path.dirname(os.path.abspath(__file__))\n"
        "sys.path.insert(0, os.path.join(HERE, '..'))\n"
        "from hub_controller import IHubView\n"
        "class MarkerGUI(IHubView):\n"
        "    def __init__(self, controller=None):\n"
        "        self.ctrl = controller; self._done = False\n"
        "        pygame.init()\n"
        "        self.screen = pygame.display.set_mode((400, 300))\n"
        "        # 写标记文件证明自定义 GUI 被加载\n"
        "        with open(os.path.join(HERE, 'marker_loaded.txt'), 'w') as mf:\n"
        "            mf.write('custom gui loaded')\n"
        "    def attach(self, c):\n"
        "        self.ctrl = c\n"
        "    def run(self):\n"
        "        import time as _t\n"
        "        t0 = _t.time()\n"
        "        while not self._done and _t.time() - t0 < 30:\n"
        "            for ev in pygame.event.get():\n"
        "                if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):\n"
        "                    self._done = True\n"
        "            pygame.display.flip()\n"
        "            pygame.time.delay(30)\n"
        "        pygame.quit()\n"
        "def build_gui(controller=None):\n"
        "    return MarkerGUI(controller)\n"
    )
with open(os.path.join(hub, "设置.json"), "w", encoding="utf-8") as f:
    json.dump({"gui": "标记HubGUI", "open_py": True}, f, ensure_ascii=False)
alive2 = launch(os.path.join(hub, "LoomHub.exe"))
check("LoomHub.exe 外部自定义 GUI 启动不崩", alive2)
check("外部自定义 GUI 被加载(标记文件出现)", os.path.isfile(marker))
if os.path.exists(marker):
    os.remove(marker)
os.remove(os.path.join(gui_dir2, "标记HubGUI.py"))
with open(os.path.join(hub, "设置.json"), "w", encoding="utf-8") as f:
    json.dump({"gui": "LoomHubGUI", "open_py": True}, f, ensure_ascii=False)

print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
