# -*- coding: utf-8 -*-
"""
gui/panels/inspector_mixin.py — 检查器面板（对象/光源/相机属性面板 + 数值行拖拽会话）（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：检查器目标解析、面板重建、数值行（valueChanged 实时应用命令化 +
DragBlock 拖拽块）、焦点联动与值同步、组件摘要。
我不负责：UI 树元素/Canvas 检查器（uitree_mixin）、gizmo 视口叠加（gizmo_mixin）。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

import math

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from gui.widgets import DraggableSpin


class InspectorMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    # ---------------- 检查器 ----------------
    def _insp_target(self):
        """当前检查器目标 (含类型). ('obj'|'light'|'camera'|'ui', 对象)."""
        e = self.editor
        if e is None or e.is_playing:
            return None
        # 2026-10-18 阶段5: UI 树选中的元素优先（C3 联动）
        if self._ui_selected_name is not None and self._ui_selected_canvas is not None:
            ui = getattr(e, 'ui', None)
            if ui is not None and self._ui_selected_canvas < len(ui.canvases):
                c = ui.canvases[self._ui_selected_canvas]
                elem = c.root.find(self._ui_selected_name)
                if elem is not None:
                    return ('ui', elem)
        # 2026-10-19 第1档序3阶段4: 选中 Canvas 节点本身 -> Canvas 属性面板
        if self._ui_selected_name is None and self._ui_selected_canvas is not None:
            ui = getattr(e, 'ui', None)
            if ui is not None and self._ui_selected_canvas < len(ui.canvases):
                return ('canvas', ui.canvases[self._ui_selected_canvas])
        m = e._selected()
        if m is not None:
            return ('obj', m)
        l = e._selected_light()
        if l is not None:
            return ('light', l)
        c = e._selected_camera()
        if c is not None:
            return ('camera', c)
        return None

    def _insp_key_of(self):
        e = self.editor
        if e is None:
            return None
        if e.is_playing:
            return ('play',)
        t = self._insp_target()
        if t is None:
            return None
        kind, obj = t
        # 2026-10-18 阶段5: UI 元素用 (canvas_idx, name) 标识（元素会重建, id 不稳）
        if kind == 'ui':
            return ('ui', self._ui_selected_canvas, self._ui_selected_name)
        if kind == 'canvas':
            return ('canvas', self._ui_selected_canvas)
        return (kind, id(obj))

    def _rebuild_inspector(self):
        """清空并重建检查器表单 (选中目标变化时).
        2026-08-22 修复: 清空必须先 setParent(None) 立即脱离 —— 原 deleteLater
        是异步延迟删除, 旧按钮仍占据面板, 重建后新旧按钮重叠错位 (用户实测
        "截面按钮绑定到阴影/光柱未切换"根因: 点到的其实是旧面板残留按钮)."""
        e = self.editor
        lay = self.inspector_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)   # 立即从父容器/布局移除 (视觉即刻消失)
                w.deleteLater()     # 事件循环空闲时回收 C++ 对象
        self._spins = {}
        self._spin_meta = {}
        self._dragblock.hide_target()       # 旧行全部失效, 拖拽块收起
        self._INSP_LE_CACHE = None          # 表单重建, QLineEdit 集合缓存失效
        self._building = True
        try:
            t = self._insp_target()
            if t is None:
                if e.is_playing:
                    lay.addRow(QLabel("→ 播放中 —— 停止后回到编辑"))
                else:
                    lay.addRow(QLabel("(未选中对象)"))
                return
            kind, obj = t
            if kind == 'obj':
                self._build_obj_inspector(lay, obj)
            elif kind == 'light':
                self._build_light_inspector(lay, obj)
            elif kind == 'ui':
                # 2026-10-18 阶段5: UI 元素检查器
                self._build_ui_inspector(lay, obj)
            elif kind == 'canvas':
                # 2026-10-19 第1档序3阶段4: Canvas 属性面板
                self._build_canvas_inspector(lay, obj)
            else:
                self._build_camera_inspector(lay, obj)
        finally:
            self._building = False

    # ---- 数值行通用 (撤销接线: 命令化数值行编辑会话批, 合一步撤销) ----
    def _spin(self, lay, label, value, lo, hi, key, apply, step=0.1, dec=3):
        """数值行通用入口 (2026-08-22 加拖拽调节): QDoubleSpinBox + 聚焦后检查器
        底部弹出 DragBlock 拖区 (按住左右拖动调值, 每像素=step). 后续新增可拖条
        数值行只需继续调用本函数, 自动获得拖拽调节 + 撤销. apply(v) 已翻译成
        EAI 命令 (每条自带一步撤销; Q-B7-56-1 裁定① + Q-B7-56-2 扫尾后全部
        数值行命令化): 撤销/教学日志/刷新由**数值行编辑会话批**协议接管
        (_spin_session_begin/end —— 会话内连续命令合成一步撤销, 对齐旧快照协议
        "一次编辑=一步撤销"的用户可见语义). 终审 F-69 (agent-68): 旧
        via_cmd=False 分支 (edit_model/edit_light/edit_camera 快照直调) 已删
        —— 本批后所有调用点均走命令会话批, 死分支无引用."""
        sb = DraggableSpin(key, self._spin_focused)
        sb.setRange(lo, hi)
        sb.setDecimals(dec)
        sb.setSingleStep(step)
        sb.setValue(float(value))
        self._spins[key] = sb
        e = self.editor

        def edit(active):
            if self._building or e is None:
                return
            # Q-B7-56-1 裁定① + Q-B7-56-2 扫尾: 全部数值行走命令化会话批协议
            # (begin/end 合一步撤销); 旧 edit_model/edit_light/edit_camera
            # 快照直调死分支已删 (终审 F-69, agent-68: 本批后无 via_cmd=False
            # 调用点, 无引用).
            if active:
                self._spin_session_begin(label)
            else:
                self._spin_session_end(label)

        def on_drag(v):
            if self._building or e is None:
                return
            edit(True)          # 先开会话批: 首条命令也进批 (合一步撤销)
            apply(v)

        def on_finish():
            if self._building or e is None:
                return
            edit(False)         # 收口会话批 + _spin_session_end 统一补日志/刷新

        sb.valueChanged.connect(on_drag)
        sb.editingFinished.connect(on_finish)
        self._spin_meta[key] = (apply, label, lo, hi, step, sb, edit)
        lay.addRow(label, sb)
        return sb

    # ---- 底部数值拖拽块 (2026-08-22 用户需求, 通用) ----
    def _spin_focused(self, key):
        """数值行聚焦 -> 底部拖拽块切换到该行 (显示后左键按住左右拖动调值)."""
        meta = self._spin_meta.get(key)
        if meta is None:
            return
        apply_, label, lo, hi, step, sb, edit = meta
        self._dragblock.set_target(label, apply_, lo, hi, step, sb, edit, self)

    def _btn_row(self, lay, pairs):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        for text, fn in pairs:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            h.addWidget(b)
        lay.addRow(row)

    def _insp_input_focused(self):
        """焦点是否在检查器表单输入控件 (正在输入值, rebuild 应打断避免丢输入).
        2026-08-22 修: 原实现任何 QLineEdit 都挡 —— 场景名/预制名框(工具栏)
        是窗口默认驻扎焦点, 用户从没碰过输入框就点检查器按钮时, 焦点恒在场景名
        框 → 点击后 rebuild 永远被挡 → 按钮文字/状态永不刷新 (用户实测
        "设为激活相机"按钮不变的真凶之一; 程序化 click 也不抢焦点同路径).
        现在只挡检查器表单内的 QLineEdit (名称/音频路径框) + spinbox + combo."""
        fw = QApplication.focusWidget()
        if isinstance(fw, (QDoubleSpinBox, QComboBox)):
            return True
        if isinstance(fw, QLineEdit):
            return self.inspector is not None and fw in self._insp_line_edits()
        return False

    def _insp_line_edits(self):
        if self._INSP_LE_CACHE is None:
            self._INSP_LE_CACHE = set(self.inspector.findChildren(QLineEdit))
        return self._INSP_LE_CACHE

    def _insp_component_digest(self, key):
        """检查器组件状态摘要, 变化时重建检查器.
        2026-08-22 修复: 原实现光源/相机一律返回 None → 检查器永不重建,
        阴影/模式/截面按钮点击后文字不刷新 (用户实测); 现按目标类型分派.
        obj: 音频/动画播放中/循环/当前剪辑; light: 阴影/模式/截面/尺寸;
        camera: FOV/预览/激活 状态."""
        if key != self._insp_key:
            return None
        e = self.editor
        if e is None:
            return None
        t = self._insp_target()
        if t is None:
            return None
        kind, obj = t
        parts = []
        if kind == 'light':
            parts.append(('shadow', getattr(obj, 'shadow', False)))
            parts.append(('mode', getattr(obj, 'mode', 'full')))
            parts.append(('shape', getattr(obj, 'shape', 'circle')))
            parts.append(('size', round(float(getattr(obj, 'size', 0.0)), 4)))
            return repr(parts)
        if kind == 'camera':
            parts.append(('fov', round(float(getattr(obj, 'fov', 0.0)), 4)))
            parts.append(('preview', getattr(e, 'preview_camera', None) is obj))
            # active: editor 存 guid 非对象 (is obj 永远 False, 同按钮文字 bug);
            # fov_lock/pitch_lock: "玩家可调""俯仰限制"按钮文字 + min/max 行显隐
            parts.append(('active', getattr(e, 'active_camera', None)
                          == getattr(obj, 'guid', None)))
            parts.append(('fov_lock', bool(getattr(obj, 'fov_locked', False))))
            parts.append(('pitch_lock', bool(getattr(obj, 'pitch_lock', False))))
            return repr(parts)
        # obj 类型: 音频/动画动态状态
        au = getattr(obj, 'audio_source', None)
        if au is not None:
            parts.append(('au', getattr(au, 'playing', False),
                          getattr(au, 'loop', False), getattr(au, 'volume', 0)))
        an = getattr(obj, 'animator', None)
        if an is not None:
            parts.append(('an', getattr(an, 'playing', False),
                          getattr(an, 'loop', False), getattr(an, 'current', None)))
        # 2026-08-22 系统性排查: 补点击后状态变化的字段 —— 碰撞器启用/刚体
        # (＋加刚体后应自动换成"移除刚体"行)/脚本行/×/Prefab 断开按钮消失/
        # 材质库 (＋新建材质后下拉刷新), 否则这些控件点击后检查器永不重建
        col = getattr(obj, 'collider', None)
        if col is not None:
            parts.append(('col', bool(getattr(col, 'enabled', False))))
        rb = getattr(obj, 'rigidbody', None)
        if rb is not None:
            parts.append(('rb', bool(getattr(rb, 'use_gravity', False))))
        if getattr(obj, 'scripts', None):
            parts.append(('scr', [sc.script_id for sc in obj.scripts]))
        if getattr(obj, 'prefab_ref', None):
            parts.append(('pref', getattr(obj, 'prefab_ref', None)))
        mats = getattr(e, 'materials', None)
        if mats is not None:
            parts.append(('mats', [getattr(m, 'name', '') for m in mats]))
        return repr(parts)

    def _sync_inspector_values(self, force=False):
        """同目标时同步 spinbox 当前值 (gizmo 拖拽等外部改动).
        spinbox 正在输入 (有焦点) 时跳过, 防值被写回干扰输入;
        force=True 时忽略焦点 (拖拽块按下前同步, 保证拖动基准 = 模型值)."""
        e = self.editor
        if e is None:
            return
        if not force and isinstance(QApplication.focusWidget(), QDoubleSpinBox):
            return
        t = self._insp_target()
        if t is None:
            return
        kind, obj = t
        for key, sb in self._spins.items():
            try:
                if kind == 'obj':
                    if key.startswith('pos.'):
                        v = getattr(obj.position, key[4].lower())
                    elif key.startswith('rot.'):
                        v = math.degrees(getattr(obj.rotation, key[4].lower()))
                    elif key.startswith('scale.'):
                        v = obj.scale[{'X': 0, 'Y': 1, 'Z': 2}[key[4]]]
                    elif key == 'sat':
                        v = obj.saturation
                    elif key.startswith('au.vol') and obj.audio_source is not None:
                        v = obj.audio_source.volume
                    elif key.startswith('svar.'):
                        _, i, pname = key.split('.', 2)
                        sc = obj.scripts[int(i)]
                        v = sc.script_vars.get(pname, 0.0)
                    elif key == 'col.fric':
                        v = obj.collider.friction
                    elif key == 'col.rest':
                        v = obj.collider.restitution
                    elif key == 'col.roll':
                        v = obj.collider.rolling_friction
                    elif key == 'rb.fric' and obj.rigidbody is not None:
                        v = obj.rigidbody.friction
                    elif key == 'rb.rest' and obj.rigidbody is not None:
                        v = obj.rigidbody.restitution
                    elif key == 'rb.roll' and obj.rigidbody is not None:
                        v = obj.rigidbody.rolling_friction
                    else:
                        continue
                elif kind == 'light':
                    if key.startswith('li.c'):
                        v = {'R': 0, 'G': 1, 'B': 2}[key[3]]
                        v = obj.color[v]
                    elif key == 'li.intensity':
                        v = obj.intensity
                    elif key == 'li.size':
                        v = obj.size
                    elif key == 'li.az':
                        v = obj.azimuth
                    elif key == 'li.el':
                        v = obj.elevation
                    elif key == 'li.roll':
                        v = obj.roll
                    elif key.startswith('li.p'):
                        v = getattr(obj.position, key[4].lower())
                    else:
                        continue
                else:
                    if key.startswith('cam.p'):
                        v = getattr(obj.position, key[5].lower())
                    elif key == 'cam.yaw':
                        v = obj.yaw
                    elif key == 'cam.pitch':
                        v = obj.pitch
                    elif key == 'cam.roll':
                        v = obj.roll
                    elif key == 'cam.fov':
                        v = obj.fov
                    elif key == 'cam.pmin':
                        v = obj.pitch_min
                    elif key == 'cam.pmax':
                        v = obj.pitch_max
                    else:
                        continue
                if abs(sb.value() - float(v)) > 1e-4:
                    sb.blockSignals(True)
                    sb.setValue(float(v))
                    sb.blockSignals(False)
            except Exception:
                pass

    def _build_obj_inspector(self, lay, m):
        e = self.editor
        name_edit = QLineEdit(m.name)
        name_edit.editingFinished.connect(
            lambda: self._invoke_cmd('object_rename', {'name': m.name, 'new': name_edit.text()})
            if name_edit.text() != m.name else None)   # Q-B7-56-1 裁定①
        lay.addRow("名称", name_edit)
        # ---- Layer / Tag (2026-10-18, 契约 §7) ----
        import kernels.layer_tag as layer_tag
        lay_combo = QComboBox()
        for i in range(32):
            nm = e.layer_name(i)
            lay_combo.addItem("%d: %s" % (i, nm if nm else "(未命名)"), i)
        lay_combo.setCurrentIndex(m.layer)
        # Q-B7-56-2 裁定①: Layer 翻译成 set_layer 命令 (命令体 = commit_model+
        # set_object_layer 同一撤销路径)
        lay_combo.currentIndexChanged.connect(
            lambda i: self._invoke_cmd('set_layer', {'name': m.name, 'layer': i})
            if i != m.layer else None)
        lay.addRow("Layer", lay_combo)

        tag_combo = QComboBox()
        tag_combo.setEditable(True)
        for t in layer_tag.get_tags():
            tag_combo.addItem(t)
        cur_tag = m.tag
        idx = tag_combo.findText(cur_tag)
        if idx >= 0:
            tag_combo.setCurrentIndex(idx)
        else:
            tag_combo.setEditText(cur_tag)

        def _apply_tag():
            val = tag_combo.currentText().strip()
            if val == m.tag:
                return
            ok, reason = layer_tag.validate_tag(val)
            if not ok:
                e._notify("Tag 非法: %s" % reason, (220, 80, 80))
                tag_combo.setEditText(m.tag)
                return
            # Q-B7-56-2 裁定① (P2-2): 注册与设置都翻译成命令 —— register_tag
            # (幂等注册) + set_tag (含同款校验/自动注册); GUI 预校验只保留
            # toast/回退 UX。tag_exists 是读侧, 豁免。
            if not e.tag_exists(val):
                r = self._invoke_cmd('register_tag', {'tag': val},
                                     notify_error=False)
                if isinstance(r, dict) and r.get('error'):
                    e._notify("Tag 注册失败: %s" % r['error'], (220, 80, 80))
                    tag_combo.setEditText(m.tag)
                    return
                # 注册成功后刷新下拉项 (新 tag 出现在列表里)
                if tag_combo.findText(val) < 0:
                    tag_combo.addItem(val)
                    tag_combo.setCurrentIndex(tag_combo.count() - 1)
            self._invoke_cmd('set_tag', {'name': m.name, 'tag': val})

        tag_combo.activated.connect(lambda _i: _apply_tag())
        if tag_combo.lineEdit() is not None:
            tag_combo.lineEdit().editingFinished.connect(_apply_tag)
        lay.addRow("Tag", tag_combo)
        parent_name = m.parent.name if m.parent is not None else "(根)"
        info = "父级: %s" % parent_name
        if m.prefab_ref:
            info += "  [Prefab %s]" % m.prefab_ref[:8]
        lay.addRow(QLabel(info))
        if m.prefab_ref:
            lay.addRow(QLabel("类型: %s" % (m.primitive or '导入网格')))
        # Q-B7-56-2 裁定①: 存网格为资产翻译成 asset_save 命令
        self._btn_row(lay, [("存网格为资产",
                             lambda: self._invoke_cmd('asset_save',
                                                      {'what': 'mesh'}))])

        p = m.position
        lay.addRow(QLabel("位置"))
        for axis, cur in (('X', p.x), ('Y', p.y), ('Z', p.z)):
            # Q-B7-56-1 裁定①: 数值行写位置翻译成 set_transform 命令 (单轴语义
            # 与旧 vec_set 直写逐字一致 —— 命令体就是 vec_set; 数值行会话批把
            # 拖拽/连输合一步撤销)
            self._spin(lay, axis, cur, -1000, 1000, 'pos.' + axis,
                       lambda v, a=axis: self._cmd_vec_set(m, 'model',
                                                           'position', a, v))
        r = m.rotation
        lay.addRow(QLabel("旋转 (°)"))
        for axis, cur in (('X', r.x), ('Y', r.y), ('Z', r.z)):
            # 2026-08-27 修复: 原写 setattr(m.rotation, 'X', ...) —— rotation 是
            # Point3D **namedtuple**, setattr 直接抛 AttributeError (且键名大小写
            # 也不对), 异常在 Qt 信号回调里被吞 -> 旋转三行从来改不动值.
            # Q-B7-56-1 裁定①: 旋转行翻译成 set_transform 命令 (rx/ry/rz **度制**,
            # 命令层内部转弧度 + vec_set 整体重建, 与命令行输 set_transform 同义;
            # 这里不再预转 radians —— 命令层换算)
            self._spin(lay, axis, math.degrees(cur), -360, 360, 'rot.' + axis,
                       lambda v, a=axis: self._cmd_vec_set(m, 'model',
                                                           'rotation', a, v),
                       step=1.0)
        s = m.scale
        lay.addRow(QLabel("缩放"))
        for i, axis in enumerate(('X', 'Y', 'Z')):
            # Q-B7-56-2 裁定①: 缩放行翻译成 set_transform sx/sy/sz 命令
            self._spin(lay, axis, s[i], 0.01, 100, 'scale.' + axis,
                       lambda v, a=axis: self._invoke_cmd(
                           'set_transform', {'name': m.name,
                                             's' + a.lower(): v},
                           quiet=True),
                       step=0.1)
        # 材质 (M23: 材质在 renderer.material, 共享引用语义)
        if e.materials:
            combo = QComboBox()
            cur_mat = m.renderer.material
            for i, mat in enumerate(e.materials):
                combo.addItem("%s%s" % (mat.name, '  √' if mat is cur_mat else ''), i)
            combo.setCurrentIndex(max(0, next((i for i, x in enumerate(e.materials)
                                              if x is cur_mat), 0)))
            # Q-B7-56-2 裁定①: 换材质翻译成 set_material 命令 (共享引用语义)
            combo.currentIndexChanged.connect(
                lambda i: self._invoke_cmd('set_material',
                                           {'name': m.name, 'index': i})
                if i >= 0 else None)
            lay.addRow("材质", combo)
        self._btn_row(lay, [
            ("＋新建材质", lambda: self._invoke_cmd('material_new',
                                               {'name': m.name})),
            ("存材质为资产", lambda: self._invoke_cmd('asset_save',
                                                  {'what': 'material'}))])
        # Q-B7-56-2 裁定①: 饱和度行翻译成 set_saturation 命令 (会话批协议)
        self._spin(lay, "饱和度", m.saturation, 0, 2, 'sat',
                   lambda v: self._invoke_cmd('set_saturation',
                                              {'name': m.name, 'value': v},
                                              quiet=True),
                   step=0.05)
        # 碰撞 (B1-修复_b 2026-08-30 用户二轮: 按钮措辞陷阱 —— 旧文"碰撞器: 禁用"
        # 出现在**已启用**状态, 状态式误读会把"点此禁用"读成"当前禁用" -> 用户点
        # 一次以为启用, 实际关掉碰撞器; 桥路径下不建体=>浮空 (配合自由积分修复).
        # 改为 状态+动作显式: "启用中(点按禁用)" / "已禁用(点按启用)"。
        if m.collider is not None:
            # Q-B7-56-2 裁定①: 碰撞器开关翻译成 collider 命令 (缺 on = 切换)
            self._btn_row(lay, [("碰撞器: 启用中(点按禁用)" if m.collider.enabled
                                 else "碰撞器: 已禁用(点按启用)",
                                 lambda: self._invoke_cmd('collider',
                                                          {'name': m.name}))])
            # B1 (2026-08-30) 用户新需求: 接触材质 —— 阿蒙东-库仑摩擦 f=μN,
            # 弹性=回弹系数, 滚动摩擦=滚动阻力. B1-P1(2026-08-30) 用户实测
            # "摩擦选项有两个" -> 单组显示: 有刚体只显示刚体组 (动态体用 rb 值),
            # 无刚体只显示碰撞组 (静态/运动学用 col 值) —— 数据仍双通道.
            if m.rigidbody is None:
                # Q-B7-56-2 裁定①: 接触材质行翻译成 collider 命令 (会话批协议)
                self._spin(lay, "摩擦系数", m.collider.friction, 0, 3, 'col.fric',
                           lambda v: self._invoke_cmd(
                               'collider', {'name': m.name, 'friction': v},
                               quiet=True), step=0.05)
                self._spin(lay, "弹性", m.collider.restitution, 0, 1, 'col.rest',
                           lambda v: self._invoke_cmd(
                               'collider', {'name': m.name, 'restitution': v},
                               quiet=True), step=0.05)
                self._spin(lay, "滚动摩擦", m.collider.rolling_friction, 0, 3, 'col.roll',
                           lambda v: self._invoke_cmd(
                               'collider', {'name': m.name, 'rolling_friction': v},
                               quiet=True), step=0.05)
            # 2026-10-18 阶段1档序17 Trigger: is_trigger 开关（路线见路线图 §2.7）
            # 语义: is_trigger=True 时物理层建 sensor 体（可重叠穿过, 不产生接触力）,
            # 事件走 on_trigger_enter/exit/stay（双方任一方 trigger 即走 trigger 路径）.
            # 按钮措辞: 状态+动作显式（"触发器: 开/关"），避免同 toggle_collider 旧措辞陷阱.
            # Q-B7-56-2 裁定①: 触发器翻译成 collider is_trigger 命令
            self._btn_row(lay, [
                ("触发器: 开 (点按关闭)" if getattr(m.collider, 'is_trigger', False)
                 else "触发器: 关 (点按开启)",
                 lambda: self._invoke_cmd(
                     'collider', {'name': m.name,
                                  'is_trigger': not getattr(m.collider,
                                                            'is_trigger',
                                                            False)}))])
        # 刚体
        if m.rigidbody is not None:
            # Q-B7-56-2 裁定①: 刚体重力/移除翻译成 rigidbody 命令
            txt = "刚体: 受重力" if m.rigidbody.use_gravity else "刚体: 不受重力"
            self._btn_row(lay, [
                (txt, lambda: self._invoke_cmd('rigidbody',
                                               {'name': m.name,
                                                'action': 'gravity'})),
                ("移除刚体", lambda: self._invoke_cmd('rigidbody',
                                                  {'name': m.name,
                                                   'action': 'remove'}))])
            # B1: 动态体接触材质 (桥透传; pair 值 = 两体几何平均); 滚动摩擦
            # 0=关闭; 桥内衰减系数 f = max(0, 1-μ·rolling·K·dt)
            # Q-B7-56-2 裁定①: 刚体接触材质行翻译成 rigidbody action=set 命令
            self._spin(lay, "摩擦系数", m.rigidbody.friction, 0, 3, 'rb.fric',
                       lambda v: self._invoke_cmd(
                           'rigidbody', {'name': m.name, 'action': 'set',
                                         'friction': v}, quiet=True),
                       step=0.05)
            self._spin(lay, "弹性", m.rigidbody.restitution, 0, 1, 'rb.rest',
                       lambda v: self._invoke_cmd(
                           'rigidbody', {'name': m.name, 'action': 'set',
                                         'restitution': v}, quiet=True),
                       step=0.05)
            self._spin(lay, "滚动摩擦", m.rigidbody.rolling_friction, 0, 3, 'rb.roll',
                       lambda v: self._invoke_cmd(
                           'rigidbody', {'name': m.name, 'action': 'set',
                                         'rolling_friction': v}, quiet=True),
                       step=0.05)
        else:
            self._btn_row(lay, [("＋加刚体 (受重力)",
                                 lambda: self._invoke_cmd(
                                     'rigidbody', {'name': m.name,
                                                   'action': 'add'}))])
        # 音频 (组件属性名 = audio_source, 与旧版GUI 一致)
        if m.audio_source is not None:
            au = m.audio_source
            clip_edit = QLineEdit(au.clip or "")
            clip_edit.setPlaceholderText("音频文件路径 (wav/ogg)")
            # Q-B7-56-2 裁定①: 音频组件操作翻译成 audio / set_audio_3d 命令
            clip_edit.editingFinished.connect(
                lambda: self._invoke_cmd('audio', {'name': m.name,
                                                   'action': 'clip',
                                                   'clip': clip_edit.text()}))
            lay.addRow("音频", clip_edit)
            self._btn_row(lay, [("循环: 开" if au.loop else "循环: 关",
                                 lambda: self._invoke_cmd('audio',
                                                          {'name': m.name,
                                                           'action': 'loop'})),
                                ("→播放" if not au.playing else "■停止",
                                 lambda: self._invoke_cmd('audio',
                                                          {'name': m.name,
                                                           'action': 'play'})),
                                ("移除", lambda: self._invoke_cmd(
                                    'audio', {'name': m.name,
                                              'action': 'remove'}))])
            self._spin(lay, "音量", au.volume, 0, 1, 'au.vol',
                       lambda v: self._invoke_cmd('audio', {'name': m.name,
                                                            'action': 'volume',
                                                            'value': v},
                                                  quiet=True),
                       step=0.05)
            # 2026-10-18 3D 音频 (契约 §9): 类别决定空间化, music 强制 2D
            cat_combo = QComboBox()
            for _label, _val in (("音效", "sfx"), ("背景音乐", "music"), ("人声", "voice")):
                cat_combo.addItem(_label, _val)
            _ci = cat_combo.findData(au.category)
            cat_combo.setCurrentIndex(max(0, _ci))

            def _on_cat(_i, _c=cat_combo, _a=au, _m=m):
                _v = _c.itemData(_i)
                if not _v or _v == _a.category:
                    return
                # Q-B7-56-2 裁定①: 类别翻译成 set_audio_3d 命令 (同款校验+
                # 一步撤销; 撤销标签为命令层 "设置音频 3D")
                self._invoke_cmd('set_audio_3d', {'name': _m.name,
                                                  'category': _v})
                self._refresh_all()

            cat_combo.currentIndexChanged.connect(_on_cat)
            lay.addRow("类别", cat_combo)
            if au.is_spatial():
                # Q-B7-56-2 裁定①: 3D 距离行翻译成 set_audio_3d 命令。
                # GUI 预判 min<max 保留旧 toast UX (不合法不发命令); 合法值由
                # 命令层再校验一次 (组件 setter 静默回退 → 命令层显式报错)。
                def _min_set(v):
                    if v >= au.max_distance:
                        e._notify("最小距离必须小于最大距离", (220, 80, 80))
                        self._refresh_all()
                        return
                    self._invoke_cmd('set_audio_3d',
                                     {'name': m.name, 'min_distance': v},
                                     quiet=True)

                def _max_set(v):
                    if v <= au.min_distance:
                        e._notify("最大距离必须大于最小距离", (220, 80, 80))
                        self._refresh_all()
                        return
                    self._invoke_cmd('set_audio_3d',
                                     {'name': m.name, 'max_distance': v},
                                     quiet=True)

                self._spin(lay, "最小距离", au.min_distance, 0.01, 10000, 'au.min',
                           _min_set, step=0.1)
                self._spin(lay, "最大距离", au.max_distance, 0.01, 10000, 'au.max',
                           _max_set, step=1.0)
                self._spin(lay, "衰减强度", au.rolloff, 0.01, 10, 'au.roll',
                           lambda v: self._invoke_cmd(
                               'set_audio_3d', {'name': m.name, 'rolloff': v},
                               quiet=True),
                           step=0.1)
        else:
            self._btn_row(lay, [("＋加音频源",
                                 lambda: self._invoke_cmd(
                                     'audio', {'name': m.name,
                                               'action': 'add'}))])
        # 动画
        if m.animator is not None:
            # Q-B7-56-2 裁定①: 动画组件操作翻译成 animator 命令
            an = m.animator
            self._btn_row(lay, [("循环: 开" if an.loop else "循环: 关",
                                 lambda: self._invoke_cmd('animator',
                                                          {'name': m.name,
                                                           'action': 'loop'})),
                                ("→播放" if not an.playing else "■停止",
                                 lambda: self._invoke_cmd('animator',
                                                          {'name': m.name,
                                                           'action': 'play'})),
                                ("移除", lambda: self._invoke_cmd(
                                    'animator', {'name': m.name,
                                                 'action': 'remove'}))])
            for clip in (an.clips or []):
                self._btn_row(lay, [("→ " + clip if an.current == clip else clip,
                                     lambda c=clip: self._invoke_cmd(
                                         'animator', {'name': m.name,
                                                      'action': 'clip',
                                                      'clip': c}))])
        else:
            self._btn_row(lay, [("＋加动画组件",
                                 lambda: self._invoke_cmd(
                                     'animator', {'name': m.name,
                                                  'action': 'add'}))])
        # 脚本
        if m.scripts:
            for i, sc in enumerate(m.scripts):
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                h.addWidget(QLabel(sc.script_id))
                b = QPushButton("×")
                b.setFixedWidth(28)
                # Q-B7-56-2 裁定①: 移除脚本翻译成 script_remove 命令
                b.clicked.connect(lambda _=False, i=i: self._invoke_cmd(
                    'script_remove', {'name': m.name, 'index': i}))
                h.addWidget(b)
                lay.addRow("脚本", row)
                try:
                    from script.scripts import get_script
                    params = get_script(sc.script_id).params
                    # Q-B7-56-2 附带修正: params 既可能是 dict {key: 默认值规格}
                    # (旧约定) 也可能是 ((key,label,default,...),...) 元组表
                    # (scripts.py 现行约定) —— 旧代码一律 .items() 对元组表抛
                    # AttributeError 被 except 吞掉, 脚本参数行从未渲染过。
                    if isinstance(params, dict):
                        pitems = [(k, d.get('default', 0.0))
                                  for k, d in params.items()]
                    else:
                        pitems = [(p[0], p[2] if len(p) > 2 else 0.0)
                                  for p in params]
                    for pname, dflt in pitems:
                        val = sc.script_vars.get(pname, dflt)
                        # Q-B7-56-2 裁定①: 脚本参数行翻译成 script_var 命令
                        self._spin(lay, pname, val, -1e6, 1e6,
                                   'svar.%d.%s' % (i, pname),
                                   lambda v, i=i, p=pname: self._invoke_cmd(
                                       'script_var', {'name': m.name,
                                                      'index': i, 'key': p,
                                                      'value': v},
                                       quiet=True),
                                   step=0.1)
                except Exception:
                    pass
        # 可挂脚本下拉 (2026-08-22 修复: script_options() 返回 (id,name) 元组,
        # 旧代码当字符串 addItem 会 TypeError 被吞 -> 下拉从未显示; 已挂脚本
        # 也未过滤, 一并修: 过滤+addItem(name, id))
        try:
            from script.scripts import script_options
            have = {sc.script_id for sc in m.scripts}
            opts = [(sid, nm) for sid, nm in script_options()
                    if sid is not None and sid not in have]
            if opts:
                combo = QComboBox()
                combo.addItem("＋ 添加脚本…", None)
                for sid, nm in opts:
                    combo.addItem(nm, sid)
                # Q-B7-56-2 裁定①: 添加脚本翻译成 script_add 命令
                combo.currentIndexChanged.connect(
                    lambda i: self._invoke_cmd('script_add',
                                               {'sid': combo.itemData(i),
                                                'target': m.name})
                    if combo.itemData(i) else None)
                lay.addRow(QLabel("脚本"), combo)
        except Exception:
            pass
        if m.prefab_ref:
            # 2026-08-27 修复: _btn_row 的回调是无参调用 f(), 直接挂
            # e.unlink_prefab (签名 unlink_prefab(self, m)) 点一下就 TypeError
            # 被 Qt 吞掉 —— 按钮从来没断开过 Prefab 连接.
            # Q-B7-56-2 裁定①: 断开 Prefab 翻译成 prefab_unlink 命令
            self._btn_row(lay, [("与 Prefab 断开连接",
                                 lambda: self._invoke_cmd('prefab_unlink',
                                                          {'name': m.name}))])

    def _build_light_inspector(self, lay, l):
        e = self.editor
        name_edit = QLineEdit(l.name)
        name_edit.editingFinished.connect(
            lambda: self._invoke_cmd('object_rename', {'name': l.name, 'new': name_edit.text()})
            if name_edit.text() != l.name else None)   # Q-B7-56-1 裁定①
        lay.addRow("名称", name_edit)
        # Q-B7-56-2 裁定①: 光源按钮翻译成 light_set 命令 (同款一步撤销)
        self._btn_row(lay, [("阴影: 开" if l.shadow else "阴影: 关",
                             lambda: self._invoke_cmd('light_set',
                                                      {'name': l.name,
                                                       'shadow': not l.shadow}))])
        if l.kind == 'directional':
            # 模式: M29 全场景平行光 'full' | 光束 'beam' (截面平行光)
            self._btn_row(lay, [("模式: 全场景" if l.mode != 'beam' else "模式: 光束",
                                 lambda: self._invoke_cmd(
                                     'light_set', {'name': l.name,
                                                   'mode': 'beam' if l.mode != 'beam'
                                                   else 'full'}))])
            if l.mode == 'beam':
                self._btn_row(lay, [("截面: 圆" if l.shape == 'circle' else "截面: 矩形",
                                     lambda: self._invoke_cmd(
                                         'light_set', {'name': l.name,
                                                       'shape': 'circle' if l.shape != 'circle'
                                                       else 'rect'}))])
                # Q-B7-56-2 裁定①: 光源数值行翻译成 light_set 命令 (会话批协议)
                self._spin(lay, "尺寸", l.size, 0.05, 50, 'li.size',
                           lambda v: self._invoke_cmd('light_set',
                                                      {'name': l.name,
                                                       'size': v},
                                                      quiet=True),
                           step=0.05)
        self._spin(lay, "强度", l.intensity, 0, 10, 'li.intensity',
                   lambda v: self._invoke_cmd('light_set', {'name': l.name,
                                                            'intensity': v},
                                              quiet=True),
                   step=0.05)
        self._spin(lay, "颜色 R", l.color[0], 0, 1, 'li.cR',
                   lambda v: self._invoke_cmd('light_set', {'name': l.name,
                                                            'r': v},
                                              quiet=True),
                   step=0.01)
        self._spin(lay, "颜色 G", l.color[1], 0, 1, 'li.cG',
                   lambda v: self._invoke_cmd('light_set', {'name': l.name,
                                                            'g': v},
                                              quiet=True),
                   step=0.01)
        self._spin(lay, "颜色 B", l.color[2], 0, 1, 'li.cB',
                   lambda v: self._invoke_cmd('light_set', {'name': l.name,
                                                            'b': v},
                                              quiet=True),
                   step=0.01)
        if l.kind == 'directional':
            # M30: 平行光三角度存度制 (azimuth/elevation/roll), 直接读写不转换
            # Q-B7-56-2 裁定①: 三角度行度制直传 (命令层 light_set 同为度制直写)
            self._spin(lay, "朝向", l.azimuth, -360, 360, 'li.az',
                       lambda v: self._invoke_cmd('light_set',
                                                  {'name': l.name,
                                                   'azimuth': v},
                                                  quiet=True),
                       step=1.0)
            self._spin(lay, "俯仰", l.elevation, -360, 360, 'li.el',
                       lambda v: self._invoke_cmd('light_set',
                                                  {'name': l.name,
                                                   'elevation': v},
                                                  quiet=True),
                       step=1.0)
            self._spin(lay, "倾斜", l.roll, -180, 180, 'li.roll',
                       lambda v: self._invoke_cmd('light_set',
                                                  {'name': l.name, 'roll': v},
                                                  quiet=True),
                       step=1.0)
        p = l.position
        for axis, cur in (('X', p.x), ('Y', p.y), ('Z', p.z)):
            # Q-B7-56-1 裁定①: 光源位置行翻译成 light_set 命令
            self._spin(lay, "位置 " + axis, cur, -1000, 1000, 'li.p' + axis,
                       lambda v, a=axis: self._cmd_vec_set(l, 'light',
                                                           'position', a, v))

    def _build_camera_inspector(self, lay, c):
        e = self.editor
        name_edit = QLineEdit(c.name)
        name_edit.editingFinished.connect(
            lambda: self._invoke_cmd('object_rename', {'name': c.name, 'new': name_edit.text()})
            if name_edit.text() != c.name else None)   # Q-B7-56-1 裁定①
        lay.addRow("名称", name_edit)
        p = c.position
        for axis, cur in (('X', p.x), ('Y', p.y), ('Z', p.z)):
            # Q-B7-56-1 裁定①: 摄像机位置行翻译成 camera_set 命令
            self._spin(lay, "位置 " + axis, cur, -1000, 1000, 'cam.p' + axis,
                       lambda v, a=axis: self._cmd_vec_set(c, 'camera',
                                                           'position', a, v))
        # M41: 摄像机朝向存度制 (yaw/pitch/roll 环绕), 直接读写不转换
        # Q-B7-56-2 裁定①: 相机角度/FOV 行翻译成 camera_set 命令 (度制直传)
        self._spin(lay, "朝向", c.yaw, -360, 360, 'cam.yaw',
                   lambda v: self._invoke_cmd('camera_set', {'name': c.name,
                                                             'yaw': v},
                                              quiet=True),
                   step=1.0)
        self._spin(lay, "俯仰", c.pitch, -360, 360, 'cam.pitch',
                   lambda v: self._invoke_cmd('camera_set', {'name': c.name,
                                                             'pitch': v},
                                              quiet=True),
                   step=1.0)
        self._spin(lay, "倾斜", c.roll, -180, 180, 'cam.roll',
                   lambda v: self._invoke_cmd('camera_set', {'name': c.name,
                                                             'roll': v},
                                              quiet=True),
                   step=1.0)
        self._spin(lay, "FOV", c.fov, 20, 120, 'cam.fov',
                   lambda v: self._invoke_cmd('camera_set', {'name': c.name,
                                                             'fov': v},
                                              quiet=True),
                   step=1.0)
        # fov_locked 语义 (engine.py): True=锁定玩家调整. 旧代码 "玩家可调" if
        # c.fov_locked 布尔颠倒 (默认 True 却显示"玩家可调"); LoomGUI 是 not
        # Q-B7-56-2 裁定①: fov 锁定/俯仰限制按钮翻译成 camera_set 命令
        self._btn_row(lay, [("玩家可调" if not c.fov_locked else "玩家锁定",
                             lambda: self._invoke_cmd('camera_set',
                                                      {'name': c.name,
                                                       'fov_lock': not c.fov_locked}))])
        self._btn_row(lay, [("俯仰限制: 已启用" if c.pitch_lock else "俯仰限制: 未启用",
                             lambda: self._invoke_cmd('camera_set',
                                                      {'name': c.name,
                                                       'pitch_lock': not c.pitch_lock}))])
        if c.pitch_lock:
            self._spin(lay, "最低俯角", c.pitch_min, -180, 180, 'cam.pmin',
                       lambda v: self._invoke_cmd('camera_set',
                                                  {'name': c.name,
                                                   'pitch_min': v},
                                                  quiet=True),
                       step=1.0)
            self._spin(lay, "最高仰角", c.pitch_max, -180, 180, 'cam.pmax',
                       lambda v: self._invoke_cmd('camera_set',
                                                  {'name': c.name,
                                                   'pitch_max': v},
                                                  quiet=True),
                       step=1.0)
        # Q-B7-56-2 裁定①: 预览/激活翻译成 camera_preview / camera_active 命令
        # (exit_preview 走 camera_preview off=true, 不新增命令)
        if e.preview_camera is c:
            self._btn_row(lay, [("退出预览",
                                 lambda: self._invoke_cmd('camera_preview',
                                                          {'off': True}))])
        else:
            self._btn_row(lay, [("用此相机预览",
                                 lambda: self._invoke_cmd('camera_preview',
                                                          {'name': c.name}))])
        # active_camera 在 editor 里存 guid (set_active_camera 写 cam.guid) 非相机
        # 对象 —— 旧代码 e.active_camera is c 永远 False, 点击后按钮文字永不刷新
        # (用户实测 2026-08-22). 与旧版GUI 同款 guid 比较.
        is_active = (e.active_camera == c.guid)
        self._btn_row(lay, [("取消激活" if is_active else "设为激活相机",
                             lambda: self._invoke_cmd(
                                 'camera_active', {} if is_active
                                 else {'name': c.name}))])

    def _on_app_focus_changed(self, old, new):
        """焦点离开检查器数值行 -> 隐藏拖拽块 (拖拽进行中不隐藏, 防松手前消失)."""
        if self._dragblock.is_dragging():
            return
        if new is None or not new in self._spins.values():
            self._dragblock.hide_target()
