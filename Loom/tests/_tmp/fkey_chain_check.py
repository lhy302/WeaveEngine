# -*- coding: utf-8 -*-
"""fkey_chain_check.py — F9/F10 编辑器键链全链模拟 (纯断言, 无窗口)."""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pygame
from types import SimpleNamespace

try:
    import editor as ed_mod
    import engine as E

    ed = ed_mod.EditorApp.__new__(ed_mod.EditorApp)
    ed.is_playing = True
    ed._split_enable = True
    ed._clock = None
    ed._interp = None
    ed._render_world = None
    ed._logic_steps = 0
    ed._logic_gen = 0
    ed._prep_aabbs = None
    ed._prep_light_vps = None
    ed._prep_pairs = None
    ed._prep_sig = None
    ed._disp_gen = -1
    ed._pipe_disabled = False
    ed._tps_events = []
    ed.models = []
    ed.lights = []
    ed.cameras = []
    ed.materials = []
    ed.msg = ''
    ed._msg_until = 0

    class _View:                              # GUI 视图桩 (handle_key_event 不吞)
        @staticmethod
        def handle_key_event(ev):
            return False
    ed.view = _View()
    E.GLEngine._ensure_split(ed)
    assert ed._clock is not None, '分离时钟未建'

    ev = SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_F9, mod=0)
    ret = ed.on_key_event(ev)
    assert ret is True, 'on_key_event 未消费 F9'
    assert ed._logic_paused is True, 'F9 未触发暂停'

    ev = SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_F10, mod=0)
    ed.on_key_event(ev)
    assert ed._step_requested is True, 'F10 未置请求'

    ev = SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_F9, mod=0)
    ed.on_key_event(ev)
    assert ed._logic_paused is False, 'F9 未恢复'

    print('editor.on_key_event F9/F10 全链: OK (暂停 -> 步进 -> 恢复)')
except Exception:
    traceback.print_exc()
    sys.exit(1)
