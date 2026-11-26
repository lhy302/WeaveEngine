# -*- coding: utf-8 -*-
"""editor/core_playback.py — 播放态辅助：播放期渲染/逻辑矩阵刷新、退出播放原子化（失败回滚 + 一次告警）。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：播放态辅助：播放期渲染/逻辑矩阵刷新、退出播放原子化（失败回滚 + 一次告警）。
我不负责：toggle_play（core.py：editor.core.apply_snapshot patch 面 + 源码 index 门）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""

class EditorPlaybackMixin(object):
    """播放态辅助：播放期渲染/逻辑矩阵刷新、退出播放原子化（失败回滚 + 一次告警）（纯搬迁）。"""

    def _refresh_play_matrices(self, it):
        """播放态渲染帧矩阵刷新 (P-01, 2026-11-07).

        渲染矩阵 (_render_world) 走插值；逻辑矩阵 (_frame_world) **只**由逻辑帧
        _logic_prep 维护。旧实现在这里写 `if _frame_world is None:
        _frame_world = _render_world`，一旦进播放 _frame_world 非空就再没人刷新
        → 逻辑矩阵/SoA 快照/阴影 VP/碰撞 AABB 全部冻结在进播放位姿。
        首帧 (逻辑帧尚未跑) 才用当前位形补一次，且必须走 compute_world_matrices
        (它同时刷新 _soa_snap)，绝不拿插值矩阵冒充逻辑位姿。"""
        if (getattr(self, '_render_world', None) is not None
                and it.static_frame()):
            pass
        else:
            self._render_world = self._profile(
                'interp', lambda: self.compute_render_matrices(self.models))
        if getattr(self, '_frame_world', None) is None:
            self._frame_world = self._profile(
                'world_matrices',
                lambda: self.compute_world_matrices(self.models))

    # ================ 退出播放的原子化 (2026-11-08 批4 · 审计 U-01 / 裁决 A) ========
    def _exit_play_atomic(self):
        """退出播放: 要么完整成功, 要么**回滚到"仍在播放"**并明确告警 (不留中间态).

        背景: 旧实现 `render` 帧末用裸 `except Exception: pass` 包住 `toggle_play()`,
        而退出播放是"整场景还原"的复合操作 (移除播放期新物体 / apply_snapshot /
        父链 / 光源 / 相机 / 物理桥销毁 / GC 解冻) —— 半途失败会留下半还原场景,
        调用方却什么都看不到, 下一次进播放就以这个坏状态为新基线。

        做法: 先快照播放记录的**引用**(模型/光源/相机/快照表/编辑态相机与投影),
        失败时整体还原并把 `is_playing` 置回 True。还原路径对已还原项是幂等的
        (apply_snapshot 写绝对值; remove_model/attach_model 都有存在性判断),
        所以用户再点一次"停止播放"会从同一基线重跑整条路径。

        告警策略 (共性问题): 不捕 BaseException (SystemExit/KeyboardInterrupt 上抛);
        失败**首次**打日志+traceback+用户可见提示, 之后的失败只累加计数不再刷屏。

        返回 True=已退出播放; False=失败并已回滚到播放态。
        """
        if not getattr(self, 'is_playing', False):
            return True
        keep = {}
        for name in ('_play_models', '_play_lights', '_play_snap',
                     '_play_light_snap', '_play_parents', '_play_cameras',
                     '_play_camera_snap', '_play_active_camera',
                     '_play_edit_cam', '_play_edit_proj'):
            keep[name] = getattr(self, name, None)
        try:
            self.toggle_play()
        except Exception as e:
            for name, val in keep.items():
                setattr(self, name, val)
            self.is_playing = True
            self._play_exit_fail_count = int(
                getattr(self, '_play_exit_fail_count', 0)) + 1
            self._play_exit_error = '%s: %s' % (type(e).__name__, e)
            if not getattr(self, '_play_exit_warned', False):
                self._play_exit_warned = True        # 只告警一次, 之后只计数
                print('[播放] 退出播放失败, 已回滚到播放态 (可再次停止播放重试): %s'
                      % self._play_exit_error)
                try:
                    import traceback
                    traceback.print_exc()
                except Exception as _e:
                    print('[播放] 打印退出播放异常栈失败: %r' % (_e,))
                try:
                    self._notify('退出播放失败, 已留在播放态 (可重试): %s'
                                 % self._play_exit_error, (235, 90, 90))
                except Exception as _e:
                    print('[播放] 退出播放失败提示未能上屏: %r' % (_e,))
            return False
        self._play_exit_error = None
        self._play_exit_warned = False               # 成功退出 -> 下次失败重新告警
        return True
