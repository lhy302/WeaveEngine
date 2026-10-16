# -*- coding: utf-8 -*-
"""真实运行时 GUI 探针 (2026-08-22): 检查器按钮点击后状态刷新系统性回归.
覆盖用户实测 bug: "设为激活相机"点击后文字永不变化 —— 根因 editor.active_camera
存 guid 而按钮用 `is c` 对象比较 (永远 False). 同类扫描修复项一并验证:
相机 fov_locked (按钮+层级 [锁/开]), pitch_lock (按钮+最低俯角行显隐),
物体 碰撞器启用/刚体(＋加刚体后应换成"刚体: 受重力"+"移除刚体")/脚本行/×.
程序化读控件, 不需要截图. 流程完全走 LoomGUI + _refresh_all (300ms 轮询 tick)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))      # ...\Loom\tests\_tmp
LOOM_DIR = os.path.dirname(os.path.dirname(HERE))      # 上两层 = Loom\
sys.path.insert(0, LOOM_DIR)

# 真实插件目录 (探针运行 cwd 在 tests\_tmp, 程序目录解析会错位 → 钉到 Loom\plugins)
import plugin_loader
plugin_loader.plugin_dir = lambda program='loom', base=None: os.path.join(LOOM_DIR, 'plugins')

from PySide6.QtWidgets import QApplication, QPushButton, QLabel, QTreeWidget, QTreeWidgetItem

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        FAILS.append(name)


from ui.loom_gui import LoomGUI

app = QApplication(sys.argv)
win = LoomGUI(scene_path=None, width=1000, height=680)
win.show()
app.processEvents()
e = win.editor
check("editor 实例已创建", e is not None)


def btn(txt):
    for b in win.findChildren(QPushButton):
        if b.text() == txt:
            return b
    return None


def labels(txt):
    return [l for l in win.findChildren(QLabel) if txt in l.text()]


def hier_texts():
    # QTreeWidgetItem 不在 findChildren 结果里 (非 QObject), 须 topLevel 递归
    out = []

    def rec(items):
        for it in items:
            t = it.text(0)
            if t and '◇' in t:
                out.append(t)
            rec([it.child(i) for i in range(it.childCount())])
    rec([win.hierarchy.topLevelItem(i)
         for i in range(win.hierarchy.topLevelItemCount())])
    return out


def _tick():
    win._refresh_all()      # 模拟 300ms 轮询
    app.processEvents()


# ========== 相机: 激活按钮 (主 bug) ==========
win._cmd_add_camera()
_tick()
cam = e.cameras[-1]                        # _cmd_add_camera 新加的是最后一个
check("加相机后自动选中 (检查器=相机)", e._selected_camera() is cam)
b1 = btn("设为激活相机")
check("初始按钮文字=设为激活相机", b1 is not None)
if b1:
    b1.click()
_tick()
check("点击后 active_camera==guid", e.active_camera == cam.guid, repr(e.active_camera))
check("点击后按钮变=取消激活", btn("取消激活") is not None,
      [b.text() for b in win.findChildren(QPushButton) if '激活' in b.text()])
b2 = btn("取消激活")
if b2:
    b2.click()
_tick()
check("再点后 active_camera=None (可取消)", e.active_camera is None)
check("再点后按钮回=设为激活相机", btn("设为激活相机") is not None)

# ========== 相机: 玩家可调/层级 [锁/开] (digest 补 fov_locked) ==========
# 默认 fov_locked=True (锁定) → 按钮"玩家锁定" + 层级 [锁]
b = btn("玩家锁定")
check("fov 默认锁定时按钮=玩家锁定", b is not None)
check("层级相机行初始 [锁]", any('[锁]' in t for t in hier_texts()), hier_texts())
if b:
    b.click()
_tick()
check("点击后按钮=玩家可调 (布尔未颠倒)", btn("玩家可调") is not None)
check("层级相机行 [开] (digest 含 fov_locked)", any('[开]' in t for t in hier_texts()),
      hier_texts())

# ========== 相机: 俯仰限制 (digest 补 pitch_lock) ==========
b = btn("俯仰限制: 未启用")
check("pitch 未锁时按钮=未启用", b is not None)
if b:
    b.click()
_tick()
check("点击后按钮=已启用", btn("俯仰限制: 已启用") is not None)
check("启用后最低俯角行出现", len(labels("最低俯角")) >= 1)

# ========== 物体: 碰撞器/刚体 (digest 补 col/rb) ==========
win._cmd_add('cube')
_tick()
m = e.models[-1]
check("加立方体后自动选中 (检查器=物体)", e._selected() is m)
# 默认 collider.enabled=True → 按钮=状态+动作 "碰撞器: 启用中(点按禁用)"; 点击后=已禁用
b = btn("碰撞器: 启用中(点按禁用)")
check("碰撞器默认启用时按钮=启用中(点按禁用)", b is not None)
if b:
    b.click()
_tick()
check("点击后按钮=已禁用(点按启用)", btn("碰撞器: 已禁用(点按启用)") is not None)
b = btn("＋加刚体 (受重力)")
check("无刚体时按钮=＋加刚体", b is not None)
if b:
    b.click()
_tick()
check("点击后出现 刚体: 受重力", btn("刚体: 受重力") is not None)
check("点击后出现 移除刚体", btn("移除刚体") is not None)

# ========== 物体: 脚本行/× (digest 补 scr) ==========
e.add_script(m, 'rotate')
_tick()
check("挂脚本后检查器出现 rotate 标签", len(labels('rotate')) >= 1)
check("挂脚本后出现 × 按钮 (移除脚本)", btn("×") is not None)

win.close()
print("总结果:", "ALL PASS ✅" if not FAILS else "FAIL ❌ " + str(FAILS))
sys.exit(1 if FAILS else 0)
