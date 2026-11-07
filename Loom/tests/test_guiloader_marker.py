# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

"""guiloader 头部标识: BOM / tab 不再让合法 GUI 失效 (P3)."""
import tempfile
import guiloader as G

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

d = tempfile.mkdtemp(prefix="loom_gui_marker_")
folder = os.path.join(d, "GUI")
os.makedirs(folder)

bom = os.path.join(folder, "BomGUI.py")
with open(bom, "w", encoding="utf-8-sig") as f:
    f.write("# gui: loom\n# gui-name: BOM界面\n# gui-desc: bom desc\n")

tab = os.path.join(folder, "TabGUI.py")
with open(tab, "w", encoding="utf-8") as f:
    f.write("#\tgui:\tloom\n#\tgui-name:\tTab界面\n")

wrong = os.path.join(folder, "WrongGUI.py")
with open(wrong, "w", encoding="utf-8") as f:
    f.write("# gui: loomhub\n")

marker, name, desc = G._parse_header(bom)
check("BOM 文件标识可解析", marker == "#gui:loom", str(marker))
check("BOM 文件 name/desc", name == "BOM界面" and desc == "bom desc",
      str((name, desc)))
marker2, name2, _ = G._parse_header(tab)
check("tab 标识可解析", marker2 == "#gui:loom", str(marker2))
check("tab name 可解析", name2 == "Tab界面", str(name2))

items = {x["id"]: x for x in G.scan_guis("loom", base=d)}
check("scan 收录 BOM GUI", "BomGUI" in items)
check("scan 收录 tab GUI", "TabGUI" in items)
check("scan 仍拒绝错程序标识", "WrongGUI" not in items)
check("scan 官方项恒在", items.get("LoomGUI", {}).get("is_official") is True)

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
