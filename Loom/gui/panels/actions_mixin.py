# -*- coding: utf-8 -*-
"""
gui/panels/actions_mixin.py — 工具栏/菜单/快捷键动作命令壳（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：播放/TPS/场景存读新建/撤销重做/gizmo 模式/加删物体/导入/显隐/
Prefab 存放等动作 → EAI 命令的薄壳（每个 _cmd_* 只做取值 + 转调 _invoke_cmd）。
我不负责：工具栏构建（toolbar_mixin）、设置面板（settings_mixin）、命令桥本体。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""


class ActionsMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    def _cmd_play(self):
        if self.editor is not None:
            # Q-B7-56-1 裁定①: 播放/暂停点击翻译成 play 命令 (缺省 toggle, 与
            # 命令行/远程同一条命令); TPS 按钮复位与刷新保留 (GUI 自身反馈)
            self._invoke_cmd('play')
            # 分离批5: 进出新播放复位 TPS 按钮文字 (暂停态不跨播放会话)
            if hasattr(self, '_act_tps_pause'):
                self._act_tps_pause.setText("⏸暂停TPS")
            self._refresh_all()

    def _cmd_tps_pause(self):
        """暂停/恢复逻辑时钟 (F9 同款, 分离批5 用户需求)."""
        e = self.editor
        if e is None:
            return
        # Q-B7-56-2 裁定①: 翻译成 logic_pause 命令 (命令体 = e.toggle_logic_paused(),
        # EngineCore 公共实现 GL/VK 同源); GUI 保留按钮文字/toast/状态栏反馈。
        r = self._invoke_cmd('logic_pause', {}, notify_error=False)
        new_state = r.get('paused')
        if new_state is not None and e.is_playing:
            paused = new_state
            self._act_tps_pause.setText("▶恢复TPS" if paused else "⏸暂停TPS")
            self._notify("逻辑时钟 %s" % ("已暂停 (⏭步进1帧生效)" if paused
                                       else "已恢复"), (240, 200, 90))
            self._refresh_status()

    def _cmd_tps_step(self):
        """步进 1 逻辑帧 (F10 同款, 仅暂停态生效)."""
        e = self.editor
        if e is None:
            return
        # Q-B7-56-2 裁定①: 翻译成 logic_step 命令 (命令体 = e.step_logic_once());
        # 未暂停时命令层报错, GUI 保留原提示文案/颜色 (notify_error=False 防双 toast)。
        r = self._invoke_cmd('logic_step', {}, notify_error=False)
        if r.get('stepped'):
            self._notify("步进 1 逻辑帧", (240, 200, 90))
        else:
            self._notify("先暂停 TPS (⏸暂停TPS / F9) 再步进", (240, 160, 90))

    def _cmd_scene_name(self):
        e = self.editor
        if e is not None:
            e.scene_name = self._scene_edit.text().strip() or '场景'

    def _cmd_prefab_name(self):
        e = self.editor
        if e is not None:
            e.prefab_name = self._prefab_edit.text().strip() or 'prefab'

    def _cmd_save(self):
        ed = self.editor
        if ed is None:
            return
        # Q-B7-56-1 裁定①: 保存翻译成 scene_save 命令。有对应文件 = 无 path 分支
        # (与命令行同一条); 无对应文件 = 先弹保存对话框选路径 (GUI 输入采集, 与
        # editor.save_scene 旧分支一致), 保存本体再走命令 (人类对话框授权路径由
        # 命令层 user 作用域放行白名单)。
        if getattr(ed, '_scene_path', None):
            self._invoke_cmd('scene_save')
        else:
            path = ed.choose_scene_save_path()
            if path:
                self._invoke_cmd('scene_save', {'path': path})
        self._refresh_all()

    def _cmd_save_as(self):
        ed = self.editor
        if ed is None:
            return
        # Q-B7-56-1 裁定①: 另存为 = 对话框选路径 (GUI 输入采集) + scene_save 命令
        # (旧 save_scene_as() = _save_scene(None) 也是同一个对话框)。
        path = ed.choose_scene_save_path()
        if path:
            self._invoke_cmd('scene_save', {'path': path})
        self._refresh_all()

    def _cmd_load(self):
        ed = self.editor
        if ed is None:
            return
        # Q-B7-56-1 裁定①: 加载翻译成 scene_load 命令。防丢确认框 (三态) 与
        # 文件对话框是 GUI 输入采集, 保留在 GUI 侧; 换场本体走命令 (命令层内含
        # isfile/prepare/对象图校验, 与远程 EAI 完全同一条)。
        if getattr(ed, 'is_playing', False):
            return                       # 与 editor.load_scene_cmd 同前置
        if not ed._confirm_unsaved():
            return                       # 用户取消: 中止 (旧语义)
        path = ed.choose_scene_to_open()
        if path:
            self._invoke_cmd('scene_load', {'path': path})
        self._refresh_all()

    def _cmd_new(self):
        ed = self.editor
        if ed is None:
            return
        # Q-B7-56-1 裁定①: 新建翻译成 scene_new 命令 (命令 = ed._new_scene,
        # 与 editor.new_scene_cmd 尾段同一入口); 防丢确认框保留在 GUI 侧。
        if getattr(ed, 'is_playing', False):
            return                       # 与 editor.new_scene_cmd 同前置
        if not ed._confirm_unsaved():
            return                       # 用户取消: 中止 (旧语义)
        self._invoke_cmd('scene_new')
        self._refresh_all()

    def _cmd_undo(self):
        if self.editor is not None:
            # Q-B7-56-1 裁定①: 撤销翻译成 undo 命令 (D10=B 拒批语义同源)。
            # notify_error=False: 结果交 _report_history_result 统一出声, 防双 toast。
            self._report_history_result(
                self._invoke_cmd('undo', notify_error=False))
            self._refresh_all()

    def _cmd_redo(self):
        if self.editor is not None:
            self._report_history_result(
                self._invoke_cmd('redo', notify_error=False))
            self._refresh_all()

    def _cmd_gizmo(self, mode):
        if self.editor is not None:
            # Q-B7-56-1 裁定①: gizmo 模式切换翻译成 gizmo 命令
            self._invoke_cmd('gizmo', {'mode': mode})

    def _cmd_add(self, typ):
        if self.editor is not None:
            # Q-B7-56-1 裁定①: 加基元翻译成 object_add 命令 (与命令行同一条;
            # 自动聚焦只对 agent 作用域生效, 人类点击相机不被拖走 —— 见命令层)
            self._invoke_cmd('object_add', {'type': typ})
            self._refresh_all()

    def _cmd_import_obj(self):
        ed = self.editor
        if ed is None:
            return
        # Q-B7-56-1 裁定①: 导入 = 文件对话框选路径 (GUI 输入采集, 与
        # editor._import_obj 的对话框逐参一致) + import_obj 命令 (导入本体,
        # 含相机适配/撤销, 与命令行同一条)。取消 = 不发命令 (旧语义)。
        path = ed.choose_obj_to_import()
        if not path:
            return
        self._invoke_cmd('import_obj', {'path': path})
        self._refresh_all()

    def _cmd_dup(self):
        if self.editor is not None:
            # Q-B7-56-1 裁定①: 复制翻译成 object_duplicate 命令
            self._invoke_cmd('object_duplicate')
            self._refresh_all()

    def _cmd_del(self):
        e = self.editor
        if e is not None:
            # Q3=A (2026-11-07): 删除入口再挂一次钩子 —— 幂等, 且不依赖
            # bind_editor 是否跑过 (editor.__init__ 会覆盖 attach 期注入)。
            # 钩子在 N>0 时弹「该物体有 N 个子物体…」, 返回 False 则 editor 不删。
            self._inject_delete_confirm(e)
            # Q-B7-56-1 裁定① (清单外顺带归零): 删除翻译成 object_delete 命令
            # (命令体 = e.delete_object(), 确认钩子语义原样在 editor 侧生效)。
            self._invoke_cmd('object_delete')
            self._refresh_all()

    def _cmd_add_light(self, kind):
        if self.editor is not None:
            # Q-B7-56-1 裁定①: 加光源翻译成 light_add 命令
            self._invoke_cmd('light_add', {'kind': kind})
            self._refresh_all()

    def _cmd_add_camera(self):
        if self.editor is not None:
            # Q-B7-56-1 裁定①: 加摄像机翻译成 camera_add 命令
            self._invoke_cmd('camera_add')
            self._refresh_all()

    def _cmd_toggle_visible(self):
        e = self.editor
        if e is not None:
            m = e._selected()
            if m is not None:
                # Q-B7-56-1 裁定① (清单外顺带归零): 显隐翻译成 set_visible 命令
                # (缺 on = 切换, 命令体 = e.toggle_visible(m), 同一入口)
                self._invoke_cmd('set_visible', {'name': m.name})
                self._refresh_all()

    def _cmd_prefab_save(self):
        if self.editor is not None:
            # Q-B7-56-1 裁定①: 存 Prefab 翻译成 prefab_save 命令 (无 path = 命令
            # 调 editor._save_prefab(None), 对话框/默认名逻辑原样在 editor 侧)。
            self._invoke_cmd('prefab_save')
            self._refresh_all()

    def _cmd_prefab_put(self):
        if self.editor is not None:
            # Q-B7-56-1 裁定①: 放 Prefab 实例翻译成 prefab_place 命令
            self._invoke_cmd('prefab_place')
            self._refresh_all()
