# -*- coding: utf-8 -*-
"""qt_arrow_probe.py — 层级树展开箭头 BUG 复现 (2026-08-22 用户实测)
用户现象: ①物体挂父后点挂父对象行旁箭头 → 子项闪出又收回(最终折叠)且选中该行;
②二级挂父后挂父列表打不开 (疑同机制).
排查疑问点:
  A) _rebuild_hierarchy 里 item.setExpanded(True) 在 addChild **之前**调用
     (qt_view.py:946 先 setExpanded 后 addChild) —— Qt 是否忽略"无子项时"的 expanded?
  B) _hier_digest 含 selected_index → 点箭头(release 选中该行) → digest 变 →
     _refresh_all 全树 rebuild → 用户刚点的展开/折叠被抹掉 = "闪一下收回".
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LOOM_DIR)

import plugin_loader
plugin_loader.plugin_dir = lambda program='loom', base=None: os.path.join(LOOM_DIR, 'plugins')

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        FAILS.append(name)


app = QApplication(sys.argv)

# ========== Step 1: 纯 Qt —— setExpanded(True) 时序行为 ==========
t = QTreeWidget()
# 模拟 qt_view 的两种调用时序
a = QTreeWidgetItem(["A"])
a.setExpanded(True)            # 未入树且无子时调用 (qt_view model 行的实际时序)
b = QTreeWidgetItem(["B"])
t.addTopLevelItem(b)
b.setExpanded(True)            # 入树后无子时调用 (head 的时序)
t.addTopLevelItem(a)
a_child = QTreeWidgetItem(["A-child"])
a.addChild(a_child)
b_child = QTreeWidgetItem(["B-child"])
b.addChild(b_child)
t.show()
app.processEvents()
check("Step1 根因确认 A: 未入树时 setExpanded 无效 (有子后 False)",
      a.isExpanded() is False, a.isExpanded())
check("Step1 B(入树后 setExpanded) 有子后 isExpanded", b.isExpanded(), b.isExpanded())

# ========== Step 2: 完整编辑器链路复现 ==========
from ui.loom_gui import LoomGUI

win = LoomGUI(scene_path=None, width=1000, height=680)
win.show()
app.processEvents()
e = win.editor
check("editor 实例已创建", e is not None)


def _tick():
    win._refresh_all()      # 模拟 300ms 轮询
    app.processEvents()


def hier_item(m):
    return win._hier_obj_item.get(id(m))


win._cmd_add('cube'); _tick()          # P = models[0]
win._cmd_add('cube'); _tick()          # C = models[1]
p0 = e.models[0]
c0 = e.models[1]
check("两物体已创建 (n=" + str(len(e.models)) + ")", len(e.models) >= 2)

# --- 一级挂父: C -> P ---
e.reparent(c0, p0); _tick()
pi = hier_item(p0)
ci = hier_item(c0)
check("挂父后 P 行 item 存在", pi is not None)
check("挂父后 P 行子项数=1", pi.childCount() == 1 if pi else None,
      pi.childCount() if pi else None)
check("挂父后 P 行 isExpanded", pi.isExpanded(), pi.isExpanded())   # ← 真因候选 A

# --- 程序化点击 P 行箭头 (真实鼠标事件, 走 eventFilter + Qt 内部 toggle) ---
# 注: 点击箭头 → release 选中 → _refresh_all → digest 变 → rebuild → 旧 item 被
# C++ 删除, 所以每轮循环重新取 item (rebuild 后引用失效本身也是机制 B 的现场证据)
rect = win.hierarchy.visualItemRect(pi)
check("P 行视觉矩形有效", rect.width() > 0, rect)
# rebuild 计数 hook (观察点箭头是否触发 rebuild —— 修复后应=0)
orig_rb = win._rebuild_hierarchy
rb_count = [0]


def rb_wrap():
    rb_count[0] += 1
    return orig_rb()


win._rebuild_hierarchy = rb_wrap
# 真实箭头区 x = rect.left()-11 (前期扫描实测 Qt 箭头判定区 ≈ rect.left()-17..-2)
pos_arrow = QPoint(rect.left() - 11, rect.center().y())
# Step3a: 展开态点箭头 → 折叠且保持 (用户要的"收起"能生效)
QTest.mouseClick(win.hierarchy.viewport(), Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, pos_arrow)
app.processEvents()
check("Step3a 点箭头(原展开) → 折叠且保持", hier_item(p0).isExpanded() is False,
      hier_item(p0).isExpanded() if hier_item(p0) is not None else None)
# Step3b: 再点箭头 → 展开且保持 + _tick 后仍展开 (修复: 不再"闪一下收回")
QTest.mouseClick(win.hierarchy.viewport(), Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, pos_arrow)
app.processEvents()
_tick()
pi2 = hier_item(p0)
check("Step3b 再点箭头 → 展开且保持 (修复: '闪一下收回'已解决)",
      pi2 is not None and pi2.isExpanded() is True,
      pi2.isExpanded() if pi2 is not None else None)
# Step3c: 点箭头不选中该行 (原生行为, 选中仍=挂父时选中的 C)
check("Step3c 点箭头不选中该行 (选中仍=C)",
      e.selected_index == e.models.index(c0), e.selected_index)
# Step3d: 点箭头不触发 rebuild (digest 不含点击 → 不该整树重扫)
check("Step3d 点箭头不触发 rebuild (rb=0)", rb_count[0] == 0, rb_count[0])
win._rebuild_hierarchy = orig_rb
ci2 = hier_item(c0)
if pi2 is not None:
    check("Step3 P 行子项仍挂在 P 下", pi2.childCount() == 1)
    ci2p = ci2.parent() if ci2 is not None else None
    check("Step3 C 行父项=P", ci2p is pi2)

# --- 二级挂父: P -> G ---
win._cmd_add('cube'); _tick()          # G
g0 = e.models[-1]
e.reparent(p0, g0); _tick()
gi = hier_item(g0)
pi2 = hier_item(p0)
check("二级挂父后 G 行子项数=1", gi.childCount() == 1 if gi else None)
check("二级挂父后 P 行 isExpanded (修复: 不再折叠)", pi2.isExpanded(),
      pi2.isExpanded() if pi2 else None)
check("二级挂父后 G 行 isExpanded (修复: 不再折叠)", gi.isExpanded(), gi.isExpanded())
# 点 G 箭头 → 点前收起, 点击后应展开且保持 (用户: 打不开 → 修复后打得开)
rect = win.hierarchy.visualItemRect(gi)
ok = False
for dx in (-17, -14, -11, -8, -6, -4, -2, 2, 5, 8, 11):
    grec = win.hierarchy.visualItemRect(gi) if gi.parent() else None
    gcur = hier_item(g0)
    gcur.setExpanded(False)
    app.processEvents()
    pos = QPoint(grec.left() + dx, grec.center().y())
    QTest.mouseClick(win.hierarchy.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, pos)
    app.processEvents()
    gcur = hier_item(g0)
    if gcur is not None and gcur.isExpanded():
        ok = True
        break
_tick()
gi2 = hier_item(g0)
check("Step4 点 G 箭头+刷新后 G 行展开 (修复: 打不开已解决)",
      ok and gi2 is not None and gi2.isExpanded(), gi2.isExpanded() if gi2 else None)

win.close()
print("总结果:", "ALL PASS ✅(未复现 bug 则探针本身全过)" if not FAILS else "FAIL ❌ " + str(FAILS))
sys.exit(1 if FAILS else 0)
