# -*- coding: utf-8 -*-
"""
gui/panels/asset_mixin.py — 资源浏览器面板（资产列表/预览/应用/放入场景）（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：资源列表重建与选中、双击预览、[应用到选中]/[放入场景]（翻译成
asset_apply/asset_place 命令）、资源摘要。
我不负责：左侧层级树（hierarchy_mixin）、资产文件本体管理。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

import os

from PySide6.QtCore import Qt

from PySide6.QtGui import QColor

from PySide6.QtWidgets import (
    QListWidgetItem,
)


class AssetMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    # ---------------- 资源面板 ----------------
    def _rebuild_resources(self):
        e = self.editor
        rl = self.resources
        rl.blockSignals(True)
        rl.clear()
        self._assets = []       # [(type, key), ...] 与行顺序对应
        groups = {'mesh': ('网格', '□'), 'material': ('材质', '■'), 'prefab': ('Prefab', '◆')}
        by = {'mesh': [], 'material': [], 'prefab': []}
        for it in e._scan_assets():
            by.setdefault(it.get('type'), []).append(it)
        for gtype in ('mesh', 'material', 'prefab'):
            name, mark = groups[gtype]
            items = by[gtype]
            head = QListWidgetItem("— %s (%d) —" % (name, len(items)))
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            head.setForeground(QColor('#888888'))
            rl.addItem(head)
            for it in items:
                disp = it.get('name') or os.path.basename(it.get('key', '?'))
                row = QListWidgetItem("%s %s" % (mark, disp))
                row.setData(Qt.ItemDataRole.UserRole, (it.get('type'), it.get('key')))
                rl.addItem(row)
                self._assets.append((it.get('type'), it.get('key')))
        rl.blockSignals(False)

    def _res_item_data(self, item):
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _res_double(self, item):
        """双击: 放入场景 (视口中心)."""
        e = self.editor
        d = self._res_item_data(item)
        if e is None or d is None:
            return
        # Q-B7-56-2 裁定①: 双击翻译成 asset_place 命令 (命令体 =
        # e._asset_drop_to_scene(it, 视口中心), 同一入口; 拖拽落场景仍走鼠标豁免面)
        self._invoke_cmd('asset_place', {'type': d[0], 'key': d[1]})
        self._refresh_all()

    def _cmd_apply_asset(self):
        e = self.editor
        if e is None or self._res_selected is None:
            return
        # Q-B7-56-2 裁定①: 应用材质资产翻译成 asset_apply 命令 (命令体 =
        # e._apply_material_asset(it, m), 同一入口)
        self._invoke_cmd('asset_apply', {'type': self._res_selected[0],
                                         'key': self._res_selected[1]})
        self._refresh_all()

    def _cmd_place_asset(self):
        e = self.editor
        if e is None or self._res_selected is None:
            return
        # Q-B7-56-2 裁定①: 放入场景按钮翻译成 asset_place 命令 (同双击)
        self._invoke_cmd('asset_place', {'type': self._res_selected[0],
                                         'key': self._res_selected[1]})
        self._refresh_all()

    def _res_digest(self, e):
        """资源列表内容摘要 (资产 (type,key) 序列), 变化才重建列表."""
        try:
            return [(it.get('type'), it.get('key')) for it in e._scan_assets()]
        except Exception:
            return []
