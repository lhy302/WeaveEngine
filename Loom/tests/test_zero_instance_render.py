# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 失败退出码闸门（与既有 test_*.py 同款）：出现 FAIL 开头的行就把退出码改成 1。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith('FAIL') or '\nFAIL' in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)

"""test_zero_instance_render.py — 零可见实例 / 空场景渲染不崩（B13 回归, 2026-11-16）

为什么有这条测试：
  2026-11-13 加 `ab_ui_only` 场景时暴露「VK 在 0 个可见实例时崩」，当时用远在
  `(1000,1000,1000)` 的哨兵物体**绕过**，根因没查。2026-11-16 缺陷账本把根因定位到
  三处（两处 VK 崩溃 + 一处 GL 硬抛），并已修：
    · `vk_renderer._dir_light_vp`：对 `(0,4)` 空数组求 min/max → `ValueError`
    · `vk_renderer.draw_frame`：`n_vis==0` 时 `write_buffer` 空数据 → `Invalid data_offset`
    · `pipeline_glue.light_vps`：空 AABB 行表 / 空可见集 → C 入口返 `-2` → 上层
      `raise`「官方件契约违约」，违反 `loom_lighting` 的「失败→返 False 回退」契约
      （用户侧：编辑器里删光所有物体后 GL 渲染帧直接崩）

测什么（两端 × 三个变体）：
  A. 物体全部 `visible=False`（**合法玩法状态**：玩家把东西全隐藏）
  B. `objects=[]`（空场景，保留灯）
  C. `objects=[] + lights=[]`（完全空场景）

判据：
  1. 三个变体两端都**不抛异常**（这就是本测试的全部意义：以前会崩）；
  2. **有牙自证**：A 变体的画面必须与「物体可见」的画面**明显不同** —— 否则说明测试
     拿到的是一张什么都没变的图，等于没测到东西；
  3. 正常场景仍能渲染（防止修成"一律画空"）。

依赖：真实 GPU（VK 适配器 + GL 4.3 上下文）。无适配器 → FAIL，
除非显式 `LOOM_ALLOW_NO_GPU=1`（与像素门同口径：默认失败，显式才跳过）。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (ROOT, os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'Loom'),
           os.path.join(ROOT, 'Loom', 'tests')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ['LOOM_NO_DIALOG'] = '1'

import test_ab_gl_vk as AB   # noqa: E402  复用离屏渲染夹具（GL 走 EditorApp.render 生产路径）

ok = True


def check(name, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + str(detail)) if detail else ''))
    if not cond:
        ok = False


def _variants():
    base = AB._load_scene(os.path.join(AB.SCENES_DIR, 'ab_scene.json'))
    v = {}
    v['A_全部隐藏'] = dict(base, objects=[dict(o, visible=False) for o in base['objects']])
    v['B_空场景有灯'] = dict(base, objects=[])
    v['C_空场景无灯'] = dict(base, objects=[], lights=[])
    return base, v


def main():
    base, variants = _variants()
    check('夹具自检: ab_scene 有物体且有灯',
          len(base['objects']) > 0 and len(base['lights']) > 0,
          'objects=%d lights=%d' % (len(base['objects']), len(base['lights'])))

    # 先确认正常场景两端都能出图（防止"修成一律画空"）
    img_gl = AB.render_gl(base)
    img_vk = AB.render_vk(base)
    check('正常场景 GL 出图', img_gl.shape == (AB.H, AB.W, 3), img_gl.shape)
    check('正常场景 VK 出图', img_vk.shape == (AB.H, AB.W, 3), img_vk.shape)

    for tag, data in variants.items():
        for backend, fn in (('GL', AB.render_gl), ('VK', AB.render_vk)):
            try:
                img = fn(data)
                check('%s %s 不抛异常' % (backend, tag),
                      img is not None and img.shape == (AB.H, AB.W, 3))
            except Exception as e:
                check('%s %s 不抛异常' % (backend, tag), False,
                      '%s: %s' % (type(e).__name__, ' '.join(str(e).split())[:160]))

    # 有牙自证：把物体全隐藏，画面必须真的变了（否则本测试在测一张没变化的图）
    hid_gl = AB.render_gl(variants['A_全部隐藏'])
    d_gl = float(np.abs(hid_gl - img_gl).mean())
    check('有牙: GL「全部隐藏」画面与可见画面明显不同', d_gl > 1e-4, 'MAE=%.6f' % d_gl)
    hid_vk = AB.render_vk(variants['A_全部隐藏'])
    d_vk = float(np.abs(hid_vk - img_vk).mean())
    check('有牙: VK「全部隐藏」画面与可见画面明显不同', d_vk > 1e-4, 'MAE=%.6f' % d_vk)

    print()
    print('test_zero_instance_render:', 'ALL PASS' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
