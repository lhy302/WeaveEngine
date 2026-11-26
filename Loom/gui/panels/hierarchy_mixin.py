# -*- coding: utf-8 -*-
"""
gui/panels/hierarchy_mixin.py — 层级树面板（树构建/右键菜单/拖拽挂父/重命名）（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：层级树区操作按钮行、树重建、行数据、单击选中/拖行挂父/拖空白
脱父（翻译成 reparent 命令）、右键菜单、重命名三态、内容摘要。
我不负责：窗口级键盘事件过滤（eventFilter，主窗口职责）、检查器。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

from PySide6.QtCore import Qt

from PySide6.QtGui import QBrush, QColor

from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QPushButton,
    QTreeWidgetItem,
    QWidget,
)


class HierarchyMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    def _build_hier_tools(self):
        """层级树区顶部操作按钮行 (对齐旧版GUI 层级面板 "-- 操作 --" 按钮区):
        + 平行光 / + 点光源 / + 摄像机 / 显隐. 写操作全走 EditorApp 命令,
        视图不直接改模型状态、不自己压撤销栈 (与旧版GUI 相同)."""
        self._hier_tools = QWidget()
        h = QHBoxLayout(self._hier_tools)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(4)
        pairs = (
            ("+ 平行光", lambda: self._cmd_add_light('directional')),
            ("+ 点光源", lambda: self._cmd_add_light('point')),
            # 2026-10-19 第1档序9 聚光灯
            ("+ 聚光灯", lambda: self._cmd_add_light('spot')),
            ("+ 摄像机", self._cmd_add_camera),
            ("显隐", self._cmd_toggle_visible),
        )
        for text, fn in pairs:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            h.addWidget(b)

    # ---------------- 层级树 ----------------
    def _hier_data(self, item):
        """item -> ('model'|'light'|'camera', index) 或 None."""
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _rebuild_hierarchy(self):
        e = self.editor
        tree = self.hierarchy
        tree.blockSignals(True)
        tree.clear()
        try:
            # 对象 (DFS 前序, 子级挂父 item)
            head = QTreeWidgetItem(["对象 (%d)" % len(e.models)])
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            head.setForeground(0, QBrush(QColor('#888888')))
            tree.addTopLevelItem(head)
            head.setExpanded(True)   # 分组头默认折叠 -> 对象行不可见 (2026-08-18 bug)
            self._hier_obj_item = {}
            rows = e._hierarchy_rows()
            for i, (depth, m) in enumerate(rows):
                item = QTreeWidgetItem(["%s %s" % ('√' if m.visible else '×', m.name)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('model', i))
                item.setExpanded(True)
                if m.parent is not None:
                    pitem = self._hier_obj_item.get(id(m.parent))
                    if pitem is not None:
                        pitem.addChild(item)
                    else:
                        head.addChild(item)
                else:
                    head.addChild(item)
                self._hier_obj_item[id(m)] = item
                if i == e.selected_index and e.selected_light_index < 0 \
                        and e.selected_camera_index < 0:
                    item.setBackground(0, QBrush(QColor('#2d5a88')))
            # 光源
            head = QTreeWidgetItem(["— 光源 (%d) —" % len(e.lights)])
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            head.setForeground(0, QBrush(QColor('#888888')))
            tree.addTopLevelItem(head)
            head.setExpanded(True)
            for i, l in enumerate(e.lights):
                mark = '◎' if l.kind == 'directional' else '●'
                item = QTreeWidgetItem(["%s %s" % (mark, l.name)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('light', i))
                head.addChild(item)
                if i == e.selected_light_index:
                    item.setBackground(0, QBrush(QColor('#2d5a88')))
            # 摄像机
            head = QTreeWidgetItem(["— 摄像机 (%d) —" % len(e.cameras)])
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            head.setForeground(0, QBrush(QColor('#888888')))
            tree.addTopLevelItem(head)
            head.setExpanded(True)
            for i, c in enumerate(e.cameras):
                lock = '锁' if c.fov_locked else '开'
                item = QTreeWidgetItem(["◇ %s [%s]" % (c.name, lock)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('camera', i))
                head.addChild(item)
                if i == e.selected_camera_index:
                    item.setBackground(0, QBrush(QColor('#2d5a88')))
        finally:
            tree.blockSignals(False)
        # 2026-08-22: setExpanded(True) 必须在 item 已入树 (已 addChild/addTopLevelItem)
        # 之后调用才生效 —— Qt 对"未入树"的 item 设置 expanded 会被忽略 (探针实测:
        # 入树前 False / 入树后 True). 上面循环里 946 行 setExpanded 发生在 addChild
        # 之前 → 每次 rebuild 后所有带子行全折叠, 用户实测: 挂父后点箭头"闪一下
        # 收回 / 二级挂父列表打不开". 重建完成后统一全展开 (head 行一直这么做, OK).
        def _expand_all(it):
            it.setExpanded(True)
            for i in range(it.childCount()):
                _expand_all(it.child(i))
        for i in range(tree.topLevelItemCount()):
            _expand_all(tree.topLevelItem(i))

    def _hier_arrow_zone(self, item, pos):
        """点击位置是否命中该行的展开/折叠箭头 (item 视觉矩形左侧的分支指示器区).
        2026-08-22: 箭头区点击必须走 Qt 原生 toggle, 不能劫持成"选中+刷新" ——
        _hier_digest 含 selected_index, 点击箭头落入 release 单击分支会选中该行 →
        digest 变化 → _refresh_all → 整树 rebuild → 用户刚点击的展开/折叠被整体
        抹掉 (旧 item 引用也被删), 现象=用户实测"闪一下收回/二级挂父打不开"."""
        if item.childCount() <= 0:
            return False   # 无子项的行没有箭头, 不拦截
        rect = self.hierarchy.visualItemRect(item)
        return rect.left() - self.hierarchy.indentation() <= pos.x() < rect.left()

    def _hier_item_at(self, pos):
        return self.hierarchy.itemAt(pos.toPoint())

    def _select_by_kind(self, kind, idx):
        e = self.editor
        if e is None:
            return
        if kind == 'model':
            e._select_model(idx)
        elif kind == 'light':
            e.selected_light_index = idx
            e.selected_index = -1
            e.selected_camera_index = -1
        elif kind == 'camera':
            if 0 <= idx < len(e.cameras):
                e._select_camera(e.cameras[idx])

    def _hier_drop(self, d0, d1):
        """拖拽落点解析: 拖到行=挂父, 拖空白=脱父 (仅对象/相机参与).

        Q-B7-56-1 裁定① (2026-11-22): 挂父/脱父本体翻译成 reparent 命令 (物体与
        相机共用同一条命令, 命令层内含脱父/自挂/成环判据, 与本函数的拖拽预判
        一致; 无效拖拽只选中不翻译, 保持旧 UX)。拖拽手势本身属鼠标豁免面,
        命令化的只是落点解析后的那次写操作。
        """
        e = self.editor
        if e is None or d0 is None:
            return
        kind0, idx0 = d0
        src = None
        if kind0 == 'model' and 0 <= idx0 < len(e.models):
            src = e.models[idx0]
        elif kind0 == 'camera' and 0 <= idx0 < len(e.cameras):
            src = e.cameras[idx0]
        if src is None:
            return
        if d1 is None:
            # 拖空白: 有父则脱父 (reparent 命令缺 parent = 脱父)
            if getattr(src, 'parent', None) is not None:
                self._invoke_cmd('reparent', {'child': src.name})
            return
        kind1, idx1 = d1
        dst = None
        if kind1 == 'model' and 0 <= idx1 < len(e.models):
            dst = e.models[idx1]
        elif kind1 == 'camera' and 0 <= idx1 < len(e.cameras):
            dst = e.cameras[idx1]
        if dst is None or dst is src:
            return
        if kind0 == kind1 == 'model':
            # 不拖到自身/父/后代 (命令层同判据)
            if not self._is_ancestor(dst, src) and src.parent is not dst:
                self._invoke_cmd('reparent', {'child': src.name,
                                              'parent': dst.name})
            else:
                e._select_model(idx0)
        elif kind0 == kind1 == 'camera':
            if src.parent is not dst:
                self._invoke_cmd('reparent', {'child': src.name,
                                              'parent': dst.name})

    @staticmethod
    def _is_ancestor(anc, m):
        p = m.parent
        while p is not None:
            if p is anc:
                return True
            p = p.parent
        return False

    # ---------------- 层级右键菜单 ----------------
    def _hier_menu(self, pos):
        e = self.editor
        if e is None:
            return
        item = self.hierarchy.itemAt(pos)
        d = self._hier_data(item)
        if d is None:
            return
        kind, idx = d
        self._select_by_kind(kind, idx)
        menu = QMenu(self)
        if kind == 'model' and 0 <= idx < len(e.models):
            m = e.models[idx]
            menu.addAction("重命名", lambda: self._rename_obj(m))
            menu.addAction("复制", self._cmd_dup)
            menu.addAction("删除", self._cmd_del)
            if m.parent is not None:
                # Q-B7-56-1 裁定①: 脱父翻译成 reparent 命令 (缺 parent = 脱父)
                menu.addAction("脱父", lambda: self._invoke_cmd(
                    'reparent', {'child': m.name}))
        elif kind == 'light' and 0 <= idx < len(e.lights):
            l = e.lights[idx]
            menu.addAction("重命名", lambda: self._rename_light(l))
            menu.addAction("删除", self._cmd_del)
        elif kind == 'camera' and 0 <= idx < len(e.cameras):
            c = e.cameras[idx]
            menu.addAction("重命名", lambda: self._rename_camera(c))
            # Q-B7-56-2 裁定①: 预览/激活翻译成 camera_preview / camera_active 命令
            menu.addAction("用此相机预览", lambda: self._invoke_cmd(
                'camera_preview', {'name': c.name}))
            menu.addAction("取消激活" if e.active_camera == c.guid else "设为激活相机",
                           lambda: self._invoke_cmd(
                               'camera_active', {}
                               if e.active_camera == c.guid else {'name': c.name}))
            if c.parent is not None:
                # Q-B7-56-1 裁定①: 相机脱父同样走 reparent 命令
                menu.addAction("脱父", lambda: self._invoke_cmd(
                    'reparent', {'child': c.name}))
            menu.addAction("删除", self._cmd_del)
        menu.exec(self.hierarchy.viewport().mapToGlobal(pos))
        self._refresh_all()

    def _ask_text(self, title, prompt, initial):
        text, ok = QInputDialog.getText(self, title, prompt, text=initial)
        return text if ok else None

    def _rename_obj(self, m):
        v = self._ask_text("重命名", "新名称:", m.name)
        if v is not None and self.editor is not None:
            # Q-B7-56-1 裁定①: 改名翻译成 object_rename 命令 (命令层按名字解析
            # 三类目标, 命令体 = ed.rename/rename_light/rename_camera 同一入口;
            # 重名/非法名由命令层查实际结果报 error -> _notify, 与旧 toast 等价)
            self._invoke_cmd('object_rename', {'name': m.name, 'new': v})
            self._refresh_all()

    def _rename_light(self, l):
        v = self._ask_text("重命名", "新名称:", l.name)
        if v is not None and self.editor is not None:
            self._invoke_cmd('object_rename', {'name': l.name, 'new': v})
            self._refresh_all()

    def _rename_camera(self, c):
        v = self._ask_text("重命名", "新名称:", c.name)
        if v is not None and self.editor is not None:
            self._invoke_cmd('object_rename', {'name': c.name, 'new': v})
            self._refresh_all()

    def _hier_digest(self, e):
        """层级树内容摘要 (模型/光源/摄像机 + 选中态), 变化才重建树."""
        return ([(id(m), m.name, m.visible, id(m.parent) if m.parent else None)
                 for m in e.models]
                + [(id(l), l.name) for l in e.lights]
                # 2026-08-22: 补 fov_locked —— 层级相机行 [锁/开] 标识, 检查器
                # "玩家可调"点击后层级树也要刷新 (旧 digest 只有 (id,name) 永不重建)
                + [(id(c), c.name, c.fov_locked) for c in e.cameras]
                + [e.selected_index, e.selected_light_index, e.selected_camera_index])
