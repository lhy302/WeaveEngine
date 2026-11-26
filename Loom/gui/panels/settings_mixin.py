# -*- coding: utf-8 -*-
"""
gui/panels/settings_mixin.py — 设置对话框（含渲染后端下拉 + settings_set 命令壳）（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：设置对话框构建（GUI 界面/保存目录/渲染后端下拉 →
write_render_api_choice 唯一写盘路径；网格/并行/帧率等 editor 依赖段）、
_cmd_set_parallel（settings_set 命令壳）。
我不负责：命令桥本体（cmd_bridge_mixin）、状态栏（status_mixin）。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

import math
import os

from PySide6.QtCore import Qt

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class SettingsMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    # ---------------- 设置对话框 ----------------
    def _cmd_settings(self):
        """设置对话框。

        2026-11-25 终审 P0-1（另一半）: **面板必须始终可达**。修前首行是
        `e = self.editor; if e is None: return` —— 视口装配失败（VK 不可用机器）
        时 self.editor 恒 None，对话框创建 0 次，用户连「把后端改成 OpenGL」这条
        唯一逃生门都没有（只能 --backend opengl 或手改 json）。
        现在按依赖切两段:
          · 不依赖 editor 的段落（GUI 界面 / 保存目录 / 渲染后端下拉 —— 只用
            guiloader + settings_set 命令壳）**无条件渲染**；
          · 依赖 editor 的段落（网格/并行/帧率/移速/重力/逻辑帧/插值/帧缓冲/核心数/
            插件）在 editor 为 None 时整段跳过，并显示一行「编辑器未就绪」说明。
        """
        e = self.editor          # 可能为 None（视口装配失败）—— 下面按依赖分段
        import guiloader
        s = guiloader.load_settings('loom')
        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        lay = QVBoxLayout(dlg)
        # GUI 界面
        lay.addWidget(QLabel("GUI 界面（重启后生效）"))
        gui_list = QListWidget()
        cur_gui = s.get('gui', 'LoomGUI')
        for g in guiloader.scan_guis('loom'):
            row = QListWidgetItem(("● " if g['id'] == cur_gui else "○ ") + g['name'])
            row.setData(Qt.ItemDataRole.UserRole, g['id'])
            gui_list.addItem(row)
        lay.addWidget(gui_list)

        def _on_gui(row):
            """切 GUI（不依赖 editor: 只写设置.json）。P0-1: editor 为 None 也可用。"""
            gid = row.data(Qt.ItemDataRole.UserRole)
            if gid:
                s['gui'] = gid
                guiloader.save_settings('loom', s)
                self._notify_or_print("已切换到「%s」，重启后生效" % gid, (240, 200, 90))
        gui_list.itemClicked.connect(_on_gui)
        # 保存目录
        lay.addWidget(QLabel("保存目录"))
        dir_row = QWidget()
        h = QHBoxLayout(dir_row)
        h.setContentsMargins(0, 0, 0, 0)
        dir_label = QLabel(s.get('save_dir') or '(默认)')
        h.addWidget(dir_label, 1)

        def _choose_dir():
            import filedialog
            d = filedialog.choose_directory("选择保存目录")
            if d:
                s['save_dir'] = d
                guiloader.save_settings('loom', s)
                dir_label.setText(d)
                self._notify_or_print("保存目录已更改，重启后生效", (240, 200, 90))
        b = QPushButton("更改…")
        b.clicked.connect(_choose_dir)
        h.addWidget(b)
        lay.addWidget(dir_row)
        # ---- 渲染后端（不依赖 editor: 只用 guiloader + settings_set 命令壳）----
        # Q-B7-60-1（人类 2026-11-23 裁决「一个键全局消费」）: 同一个 render_api 键既
        # 决定**编辑器视口**后端，也决定播放/打包游戏的后端（编辑器读它走
        # run_player.resolve_backend 同一条解析链）；玩家侧仍可 --backend /
        # 游戏设置.json 自行覆盖，底层设置 API 留给开发者 UI。
        # 裁决①: 重启编辑器生效，**不做视口热切换**。
        # 2026-11-25 终审 P1-1（写盘单层化）: 选中项 = **生效值**
        # （effective_render_api = 解析链最终结果），不再是引擎层单层值 —— 否则就是
        # 「面板显示 X、生效 Y」（游戏层覆盖键压过引擎层）。生效值来自游戏层时在右侧
        # 标注来源层，用户能看出「这个值是谁写的」。
        api_row = QWidget()
        ha = QHBoxLayout(api_row)
        ha.setContentsMargins(0, 0, 0, 0)
        ha.addWidget(QLabel("渲染后端（编辑器与播放共用，重启生效）"))
        api_combo = QComboBox()
        # 2026-11-06 R-05 (复核 B 指出): 下拉此前只有 vulkan/opengl, 设计文档 P5
        # 明写的 auto(vk 失败自动回退 gl) 因此无法从 UI 选到; 设置里存成 auto 时
        # 下拉还会错误地显示成 Vulkan。三项与 run_player.resolve_backend 的合法值
        # 集合严格一致。
        # P1-2（2026-11-25）: auto 两端同义 —— 先试 VK、失败回退 GL（编辑器侧由启动期
        # 探测 + 回退实现），故「自动（Vulkan 失败回退 OpenGL）」这个文案对两端都成立。
        try:
            from hostenv.editor_launch import effective_render_api
            _eff_api, _eff_src = effective_render_api()
        except Exception as _ee:
            print('[设置] 读生效渲染后端失败 (%r) -> 退回引擎层配置值' % (_ee,))
            _eff_api, _eff_src = s.get('render_api', 'vulkan'), 'engine'
        for i, (txt, aid) in enumerate((
                ("自动（Vulkan 失败回退 OpenGL）", "auto"),
                ("Vulkan（新，推荐）", "vulkan"),
                ("OpenGL（保底）", "opengl"))):
            api_combo.addItem(txt, aid)
            if aid == _eff_api:
                api_combo.setCurrentIndex(i)
        api_combo.setToolTip(
            "设置当前项目的渲染后端（以配置文件为准）。编辑器视口与播放/打包游戏共用此键；"
            "修改后重启编辑器/播放器生效。--backend 命令行参数可临时覆盖本次启动。")
        self._render_api_combo = api_combo
        # Q-B7-56-2 裁定①: 面板写盘翻译成命令（唯一写盘路径内部走 settings_set 命令壳），
        # 不再直写 guiloader。重启生效提示保留。
        api_combo.currentIndexChanged.connect(self._cmd_set_render_api)
        ha.addWidget(api_combo)
        if _eff_src == 'game':
            ha.addWidget(QLabel("（生效值来自 游戏设置.json 覆盖层）"))
        lay.addWidget(api_row)
        # ---- editor 为 None（视口装配失败）时: 以上三段照常可用，以下整段跳过 ----
        if e is None:
            lay.addWidget(QLabel(
                "编辑器未就绪（视口装配失败）：以上 GUI 界面 / 保存目录 / 渲染后端"
                "仍可修改；改成 OpenGL 后重启编辑器即可继续使用。"))
            _btns0 = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            _btns0.rejected.connect(dlg.reject)
            _btns0.accepted.connect(dlg.accept)
            lay.addWidget(_btns0)
            dlg.exec()
            return
        # ---- 以下依赖 editor（网格/并行/帧率/移速/重力/逻辑帧/插值/帧缓冲/核心数/插件）----
        # 网格 / 并行 / 脚本核心数
        grid_chk = QCheckBox("无限网格（即时生效）")
        grid_chk.setChecked(bool(getattr(e, 'show_grid', True)))
        grid_chk.toggled.connect(lambda v: (setattr(e, 'show_grid', bool(v)),
                                            s.__setitem__('show_grid', bool(v)),
                                            guiloader.save_settings('loom', s)))
        lay.addWidget(grid_chk)
        par_chk = QCheckBox("多核并行（重启生效）")
        par_chk.setChecked(bool(getattr(e, 'parallel_enable', True)))
        # Q-B7-56-2 裁定①: 设置写盘翻译成 settings_set 命令 (提示保留)
        par_chk.toggled.connect(self._cmd_set_parallel)
        lay.addWidget(par_chk)
        # 帧率上限 (2026-08-19): 档位即时生效 (渲染定时器周期直接改)
        fps_row = QWidget()
        hf = QHBoxLayout(fps_row)
        hf.setContentsMargins(0, 0, 0, 0)
        hf.addWidget(QLabel("帧率上限（即时生效）"))
        fps_combo = QComboBox()
        cur_fps = s.get('fps_limit', '120')
        for i, (txt, fid) in enumerate(guiloader.FPS_OPTIONS):
            fps_combo.addItem(txt, fid)
            if fid == cur_fps:
                fps_combo.setCurrentIndex(i)
        fps_combo.currentIndexChanged.connect(
            lambda i: (s.__setitem__('fps_limit', fps_combo.itemData(i)),
                       guiloader.save_settings('loom', s),
                       self._apply_fps_limit(fps_combo.itemData(i)),
                       getattr(self, '_fb_lazy_refresh', lambda: None)(),
                       e._notify("帧率上限已生效", (240, 200, 90))))
        hf.addWidget(fps_combo)
        lay.addWidget(fps_row)
        # 摄像机移速倍率 (2026-08-19): 对数坐标拖条 —— 倍率 2^(p/100),
        # p∈[-100,100] 对应 0.5x~2x; 0.5→1 与 1→2 距离相等 (对数等距).
        speed_row = QWidget()
        hs = QHBoxLayout(speed_row)
        hs.setContentsMargins(0, 0, 0, 0)
        cur_sp = float(s.get('cam_speed', 1.0))
        speed_slider = QSlider(Qt.Orientation.Horizontal)
        speed_slider.setRange(-100, 100)
        speed_slider.setValue(int(round(100.0 * math.log2(cur_sp))))
        speed_label = QLabel("摄像机移速 %.2fx" % cur_sp)

        def _apply_speed(v):
            m = 2.0 ** (v / 100.0)
            s['cam_speed'] = round(m, 3)
            guiloader.save_settings('loom', s)
            speed_label.setText("摄像机移速 %.2fx" % m)
            if e is not None:
                e._cam_speed = s['cam_speed']   # 缓存同步 (editor._update_camera)
            e._notify("摄像机移速 %.2fx 已生效" % m, (240, 200, 90))
        speed_slider.valueChanged.connect(_apply_speed)
        hs.addWidget(QLabel("0.5x"))
        hs.addWidget(speed_slider, 1)
        hs.addWidget(QLabel("2x"))
        hs.addWidget(speed_label)
        lay.addWidget(speed_row)
        # 重力加速度 (2026-08-30 用户实测): 场景内整体重力可调 (m/s², 负=向下),
        # 即时生效 (engine.gravity; 场景文件可覆盖, 面板值=全局默认)
        grav_row = QWidget()
        hg = QHBoxLayout(grav_row)
        hg.setContentsMargins(0, 0, 0, 0)
        hg.addWidget(QLabel("重力加速度"))
        grav_spin = QDoubleSpinBox()
        grav_spin.setRange(-100.0, 100.0)
        grav_spin.setDecimals(2)
        grav_spin.setSingleStep(1.0)
        grav_spin.setValue(float(s.get('gravity', -9.8)))
        grav_spin.valueChanged.connect(
            lambda v: (s.__setitem__('gravity', round(float(v), 2)),
                       guiloader.save_settings('loom', s),
                       setattr(e, 'gravity', float(v)),
                       e._notify("重力加速度 %.2f m/s² 已生效 (播放器/场景)" % v,
                                 (240, 200, 90))))
        hg.addWidget(grav_spin)
        hg.addWidget(QLabel("m/s²（负=向下，即时生效）"))
        lay.addWidget(grav_row)
        # 逻辑帧频率 (2026-09-05 分离批3): 20/30/45/60/120/跟随渲染帧(=旧绑死)
        lf_row = QWidget()
        hl = QHBoxLayout(lf_row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(QLabel("逻辑帧率（播放态）"))
        lf_combo = QComboBox()
        for txt, fid in (("1 Hz（步进播放）", 1), ("20 Hz", 20), ("30 Hz（默认）", 30),
                         ("45 Hz", 45), ("60 Hz", 60), ("120 Hz", 120),
                         ("跟随渲染帧（旧模式）", 0)):
            lf_combo.addItem(txt, fid)
            if int(fid) == int(s.get('logic_fps', 30)):
                lf_combo.setCurrentIndex(lf_combo.count() - 1)

        def _apply_lf(i):
            v = int(lf_combo.itemData(i))
            s['logic_fps'] = v
            guiloader.save_settings('loom', s)
            # 批5: 即时生效 — 播放态直接改运行中时钟 (accumulator 按新步长
            # 继续; <=0 时即时停步进=跟随渲染, >0 恢复分离)
            clk = getattr(e, '_clock', None)
            if clk is not None:
                if v > 0:
                    clk.set_fps(logic_fps=v)   # 即时改频 (accumulator 连续)
                # v<=0: 保持时钟但 preview 提示走重启 (绑死模式仅在启动时由
                # logic_fps<=0 判定, 不热切; ★B7b 2026-10-16 删 LOOM_NO_SPLIT env)
            e._notify("逻辑帧率 %s %s" % (
                "跟随渲染帧" if v <= 0 else ("%dHz%s" % (v, "（步进播放）" if v == 1 else "")),
                "已即时生效" if (v > 0 and clk is not None) else "（重启播放生效）"),
                (240, 200, 90))
        lf_combo.currentIndexChanged.connect(
            lambda i: (_apply_lf(i),
                       getattr(self, '_fb_lazy_refresh', lambda: None)()))
        hl.addWidget(lf_combo)
        lay.addWidget(lf_row)
        # 方案二 (2026-09-05): 插值模式 — 插值(默认, 落后半帧)/外推(领先半帧,
        # 急变速物体可能过冲; Unity Rigidbody.interpolation 枚举同款 trade-off)
        im_row = QWidget()
        hi = QHBoxLayout(im_row)
        hi.setContentsMargins(0, 0, 0, 0)
        hi.addWidget(QLabel("渲染位姿模式"))
        im_combo = QComboBox()
        for txt, mid in (("插值（默认，画面落后半帧内）", 'interpolate'),
                         ("外推（画面领先半帧内，可回退）", 'extrapolate')):
            im_combo.addItem(txt, mid)
            if mid == s.get('interp_mode', 'interpolate'):
                im_combo.setCurrentIndex(im_combo.count() - 1)
        im_combo.currentIndexChanged.connect(
            lambda i: (s.__setitem__('interp_mode', im_combo.itemData(i)),
                       guiloader.save_settings('loom', s),
                       setattr(e, '_interp_mode', im_combo.itemData(i)),
                       e._notify("渲染位姿模式: %s 已生效" % im_combo.itemData(i),
                                 (240, 200, 90))))
        hi.addWidget(im_combo)
        lay.addWidget(im_row)
        # 实验开关 (2026-09-06): TPS/FPS 帧缓冲 — 两道独立闸门灰置:
        #   TPS 缓冲: 逻辑帧率 >= 30 (低 TPS 单帧时间长, 缓冲引入延迟得不偿失)
        #   FPS 缓冲: 帧率档位 >= 60 且非无上限/auto (无上限=画一帧显一帧无节拍)
        # 两个开关互不牵连 (射击类=低TPS高FPS 只开 FPS 侧; 3A=高TPS低FPS 只开 TPS 侧)
        def _fb_gates():
            lf = int(s.get('logic_fps', 30))
            fl = s.get('fps_limit', '120')
            if fl == 'auto':
                fl = guiloader.device_fps_limit()
            try:
                fln = int(fl)
            except (TypeError, ValueError):
                fln = 0
            return lf, fln
        fb_row = QWidget()
        hfb = QHBoxLayout(fb_row)
        hfb.setContentsMargins(0, 0, 0, 0)
        tps_chk = QCheckBox("TPS缓冲（实验）")
        fps_chk = QCheckBox("FPS缓冲（实验）")
        tps_chk.setToolTip("空闲时提前算好下一逻辑帧 (最多2帧), 尖峰帧到点取成品保 TPS 节律。\n"
                           "要求: 逻辑帧率 ≥ 30 (低帧率缓冲延迟过大, 得不偿失)")
        fps_chk.setToolTip("空闲时把下一渲染帧预画进离屏缓冲, 到点直接上屏。\n"
                           "要求: 帧率上限 ≥ 60 且非无上限/自动 (无上限画一帧显一帧, 无节拍可缓冲)")
        hfb.addWidget(tps_chk)
        hfb.addWidget(fps_chk)
        hfb.addStretch(1)
        lay.addWidget(fb_row)

        def _fb_refresh():
            lf, fln = _fb_gates()
            tps_ok = lf >= 30
            fps_ok = fln >= 60
            tps_chk.setEnabled(tps_ok)
            fps_chk.setEnabled(fps_ok)
            if not tps_ok and tps_chk.isChecked():
                tps_chk.setChecked(False)
            if not fps_ok and fps_chk.isChecked():
                fps_chk.setChecked(False)
            tps_chk.setText("TPS缓冲（实验）" if tps_ok
                            else "TPS缓冲（需逻辑帧率≥30）")
            fps_chk.setText("FPS缓冲（实验）" if fps_ok
                            else "FPS缓冲（需帧率≥60且非无上限）")
        _fb_refresh()
        # 逻辑帧率/帧率档位变化时刷新灰置 (下拉回调里已存 s, 这里轮询即可 —
        # 两个 combo 的 currentIndexChanged 无法在此处直接拿到, 用懒刷新:
        # 面板每次打开重建, 运行中改档位后重开设置即刷新)
        tps_chk.setChecked(bool(s.get('frame_buffer_tps', False)))
        fps_chk.setChecked(bool(s.get('frame_buffer_fps', False)))
        _fb_refresh()   # setChecked 后再校一次闸门 (越界存档值自动弹回)

        def _apply_fb():
            s['frame_buffer_tps'] = bool(tps_chk.isChecked())
            s['frame_buffer_fps'] = bool(fps_chk.isChecked())
            guiloader.save_settings('loom', s)
            fb = getattr(e, '_frame_buf', None)
            if fb is not None:
                lf, _fln = _fb_gates()
                fb.enabled = bool(s['frame_buffer_tps'] and lf >= 30)
            e._notify("帧缓冲开关: TPS=%s FPS=%s %s" % (
                "开" if s['frame_buffer_tps'] else "关",
                "开" if s['frame_buffer_fps'] else "关",
                "(TPS 侧即时生效; FPS 侧重启播放生效)"),
                (240, 200, 90))
        tps_chk.toggled.connect(_apply_fb)
        fps_chk.toggled.connect(_apply_fb)
        self._fb_lazy_refresh = _fb_refresh   # 两个下拉回调联动刷新灰置
        # 批5: "物理步频"下拉已撤 — 物理在逻辑帧内自动子步 (Unity fixed_dt 语义),
        # 步长=内部参数 (设置.json "phys_substep_dt" 键, 高级开发者可调)
        cores_row = QWidget()
        hc = QHBoxLayout(cores_row)
        hc.setContentsMargins(0, 0, 0, 0)
        hc.addWidget(QLabel("脚本预留核心数"))
        cores = QComboBox()
        for n in (1, 2, 4):
            cores.addItem(str(n), n)
        cores.setCurrentIndex(max(0, cores.findData(int(s.get('script_cores', 2)))))
        cores.currentIndexChanged.connect(
            lambda i: (s.__setitem__('script_cores', cores.itemData(i)),
                       guiloader.save_settings('loom', s),
                       e._notify("预留核数重启后生效", (240, 200, 90))))
        hc.addWidget(cores)
        lay.addWidget(cores_row)
        # 插件挂载区 (2026-08-27 L1 分级): 三类三态展示 + 单独 加载/卸载/确认信任.
        #  plugins/editor|player = 普通插件 (受限环境, 目录即声明注入层);
        #  core_plugins/<类别>   = 核心插件 (全权, 信任闸: 未信任/被改 -> 确认后重启生效)
        lay.addWidget(QLabel(
            "插件（plugins/editor|player 普通插件·受限；core_plugins 核心插件·信任闸+重启生效）"))
        import plugin.loader as plugin_loader
        plug_list = QListWidget()
        plug_summary = QLabel("")

        def _add_head(text):
            item = QListWidgetItem(text)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            plug_list.addItem(item)

        def _add_plug_row(text, pid, state, path=None):
            """state: loaded|unloaded|broken|untrusted|modified"""
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(6, 2, 6, 2)
            h.addWidget(QLabel(text), 1)
            b_load = QPushButton("加载")
            b_unload = QPushButton("卸载")
            b_load.setEnabled(state == 'unloaded')
            b_unload.setEnabled(state == 'loaded')
            b_load.clicked.connect(lambda: (_do_load(pid), _refresh_plugins()))
            b_unload.clicked.connect(lambda: (_do_unload(pid), _refresh_plugins()))
            h.addWidget(b_load)
            h.addWidget(b_unload)
            if state in ('untrusted', 'modified'):
                b_trust = QPushButton("确认信任")
                b_trust.clicked.connect(
                    lambda: (_do_trust(pid, path), _refresh_plugins()))
                h.addWidget(b_trust)
            item = QListWidgetItem()
            plug_list.addItem(item)
            item.setSizeHint(row.sizeHint())
            plug_list.setItemWidget(item, row)

        def _do_load(pid):
            plugin_loader.load_plugin(pid)   # 取消会话禁用 + 重新加载
            e._notify("已加载「%s」" % pid, (240, 200, 90))

        def _do_unload(pid):
            ok, err = plugin_loader.unload_plugin(pid)   # 会话禁用 (重启恢复)
            e._notify("已卸载「%s」%s" % (
                pid, err if not ok else "（重启前保持卸载，删目录可永久移除）"),
                (240, 200, 90))

        def _do_trust(pid, path):
            ok = plugin_loader.confirm_core_trust(pid, path)
            e._notify("「%s」已写入信任记录，重启后生效" % pid if ok
                      else "「%s」信任记录写入失败" % pid, (240, 200, 90) if ok
                      else (240, 120, 120))

        def _scan_unloaded(skip_ids=frozenset()):
            """未加载目录行: ['standard'|'core', pid|fname, info, path, err].
            skip_ids: 已单列 (待信任/已加载) 的插件 id, 不再重复列出."""
            out = []
            for layer in ('editor', 'player'):
                d = plugin_loader.plugin_dir(layer)
                if not os.path.isdir(d):
                    continue
                for fname in sorted(os.listdir(d)):
                    p = os.path.join(d, fname)
                    if not os.path.isdir(p):
                        continue
                    if any(plugin_loader.get_plugin(i)['path'] == p
                           for i in plugin_loader.get_loaded()):
                        continue
                    info, err = plugin_loader._parse_manifest(p)
                    if info is not None and info['id'] in skip_ids:
                        continue
                    out.append(('standard', fname, info, p, err))
            core = plugin_loader.core_plugin_root()
            if os.path.isdir(core):
                for cat in sorted(os.listdir(core)):
                    cd = os.path.join(core, cat)
                    if not os.path.isdir(cd):
                        continue
                    for fname in sorted(os.listdir(cd)):
                        p = os.path.join(cd, fname)
                        if not os.path.isdir(p):
                            continue
                        if any(plugin_loader.get_plugin(i)['path'] == p
                               for i in plugin_loader.get_loaded()):
                            continue
                        info, err = plugin_loader._parse_manifest(p, core=True)
                        if info is not None and info['id'] in skip_ids:
                            continue
                        out.append(('core', fname, info, p, err))
            return out

        def _refresh_plugins():
            plugin_loader.rescan_plugins()
            plug_list.clear()
            trust_items = plugin_loader.list_untrusted()
            trust_by_id = {t['id']: t for t in trust_items}
            core_rows, std_rows = [], []
            for pid, ent in plugin_loader.get_loaded().items():
                kind = ent['kind']
                txt = "● 已加载  %s  %s v%s" % (
                    "核心" if kind == 'core' else "标准", pid,
                    ent['info'].get('name', ''), ent['info']['version'])
                (core_rows if kind == 'core' else std_rows).append(
                    ('loaded', txt, pid, ent['path']))
            for tid, t in trust_by_id.items():
                prefix = "⚠ 被修改" if t['state'] == 'modified' else "⚠ 待信任"
                (core_rows if t.get('kind') == 'core' else std_rows).append(
                    (t['state'], "%s  %s（确认后重启生效）" % (prefix, tid),
                     tid, t['path']))
            for kind, fname, info, p, err in _scan_unloaded(set(trust_by_id)):
                if info is None:
                    txt = "× 有问题  %s  (%s)" % (fname, err)
                    (core_rows if kind == 'core' else std_rows).append(
                        ('broken', txt, fname, p))
                else:
                    txt = "○ 未加载  %s  %s v%s" % (
                        info['id'], info.get('name', ''), info['version'])
                    (core_rows if kind == 'core' else std_rows).append(
                        ('unloaded', txt, info['id'], p))
            if core_rows:
                _add_head("── 核心插件（全权 · 信任闸） ──")
                for state, txt, pid, path in core_rows:
                    _add_plug_row(txt, pid, state, path)
            if std_rows:
                _add_head("── 普通插件（受限环境） ──")
                for state, txt, pid, path in std_rows:
                    _add_plug_row(txt, pid, state, path)
            if plug_list.count() == 0:
                plug_list.addItem("(插件目录为空或不存在)")
            plug_summary.setText(
                "plugins: %s   |  核心: %s   |  已加载 %d 个" % (
                    plugin_loader.plugin_dir('loom'),
                    plugin_loader.core_plugin_root(), len(plugin_loader.get_loaded())))
        _refresh_plugins()
        lay.addWidget(plug_list)
        plug_row = QWidget()
        hp = QHBoxLayout(plug_row)
        hp.setContentsMargins(0, 0, 0, 0)
        hp.addWidget(plug_summary, 1)
        pb = QPushButton("重新扫描")
        pb.clicked.connect(lambda: (_refresh_plugins(),
                                    e._notify("插件已重新扫描", (240, 200, 90))))
        hp.addWidget(pb)
        lay.addWidget(plug_row)
        lay.addWidget(QLabel("更改 GUI / 保存目录 / 并行需重启 Loom 生效"))
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)

        dlg.exec()

    def _cmd_set_render_api(self, index):
        """渲染后端下拉框（Q-B7-60-1 裁定①② + 2026-11-25 终审 P1-1 单层化）。

        人类 2026-11-23 裁决「一个键全局消费」: 这里写的 render_api 既是播放/打包
        游戏的后端，也是**编辑器视口**的后端（编辑器侧读它走
        hostenv.editor_launch.editor_backend_choice -> run_player.resolve_backend）。
        裁决①「重启编辑器生效」: 不做视口热切换，故只落盘 + 提示重启，不重建视口。

        P1-1（修前缺陷）: 面板原来只写**引擎层**，而解析链优先级是 游戏层 > 引擎层 ——
        播放器 VK 失败回退把游戏层写成 opengl 后，面板显示 vulkan、生效却是 opengl，
        且「改回」无效。现在写盘走**唯一写盘路径** write_render_api_choice（同一份函数
        也被 VK 装配失败自动回退使用）: 引擎层写入 + 清游戏层覆盖键 + 复核生效值。
        """
        combo = getattr(self, '_render_api_combo', None)
        api = combo.itemData(index) if combo is not None else None
        if not api:
            return
        from hostenv.editor_launch import write_render_api_choice
        # invoke=self._invoke_cmd = 与设置面板同一条命令壳入口（settings_set）
        res = write_render_api_choice(api, invoke=self._invoke_cmd)
        if not res.get('ok'):
            self._notify_or_print("渲染后端保存失败：%s" % (res.get('error'),),
                                  (235, 90, 90))
            return
        self._notify_or_print(
            "渲染后端已保存（生效值 %s）：编辑器视口与播放/打包游戏共用此键，"
            "重启编辑器/播放器后生效" % (res.get('effective'),), (240, 200, 90))

    def _cmd_set_parallel(self, on):
        """多核并行复选框 (Q-B7-56-2 裁定①): 设置写盘翻译成 settings_set 命令
        (命令体 = guiloader load/save 同一入口); 重启生效提示保留。
        网格显隐复选框不在此列 —— 编辑器视图状态, 终审判定豁免。"""
        self._invoke_cmd('settings_set', {'key': 'parallel_enable',
                                          'value': bool(on)})
        e = self.editor
        if e is not None:
            e._notify("并行开关重启后生效", (240, 200, 90))
