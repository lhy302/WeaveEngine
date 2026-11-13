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

"""test_vk_p1_stage.py — VK P1 逃生舱（--stage p1）管线可创建 (2026-11-13)

为什么有这条测试：
  `VkRenderer(stage='p1')` 是一条**诊断逃生舱**（`py vk_player.py --stage p1`），
  只画清屏、用于定位显卡/驱动问题。它在 23 个 A/B 场景里零覆盖，也**没有 GL 对应
  阶段**可以单源化，因此 T3 明确豁免它（计划 §9.34 / 未完项清单 A1-8）。
  豁免的前提是：**至少证明它还能把管线建起来**——否则某次重构把它改坏了，
  等到真需要逃生时才发现，那就等于没有逃生舱。

本测试锁（纯 CPU，不需要 GPU/窗口）：
  A. stage='p1' 能构造成功，且只建 1 条管线、1 个 bind group layout（单 uniform）；
  B. p1 的两段 WGSL 仍存在且自洽（顶点/片段都不引用主 pass 的 Scene/Bucket 块）；
  C. 对照：默认 stage='p4' 走的是另一条路径（12 条 binding），证明本测试确实在区分 stage。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import vk_renderer as VR                            # noqa: E402

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


class _FakeDevice:
    '只记录 bind group layout / pipeline layout 的假 device（无 GPU）。'

    def __init__(self):
        self.bgls = []
        self.pipeline_layouts = []
        self.pipelines = []

    def create_shader_module(self, code=None):
        return {'code': code}

    def create_bind_group_layout(self, entries=None):
        self.bgls.append(entries)
        return ('bgl', len(self.bgls) - 1)

    def create_pipeline_layout(self, bind_group_layouts=None):
        self.pipeline_layouts.append(list(bind_group_layouts or []))
        return ('pl', len(self.pipeline_layouts) - 1)

    def create_render_pipeline(self, **kw):
        self.pipelines.append(kw)
        return ('pipe', len(self.pipelines))

    def create_buffer(self, **kw):
        return ('buf',)

    def create_bind_group(self, **kw):
        return ('group',)


print('=' * 60)
print('A. stage=p1 逃生舱管线可创建')
print('=' * 60)

p1_dev = _FakeDevice()
p1 = VR.VkRenderer(p1_dev, 'rgba8unorm', stage='p1')

check('A1 stage=p1 构造成功', p1 is not None and p1.stage == 'p1', getattr(p1, 'stage', None))
check('A2 p1 只建 1 条管线', len(p1_dev.pipelines) == 1, len(p1_dev.pipelines))
check('A3 p1 bind group layout 只有 1 组', len(p1_dev.bgls) == 1, len(p1_dev.bgls))
check('A4 p1 的 BGL 只有 1 条 binding(0 uniform)',
      len(p1_dev.bgls[0]) == 1 and int(p1_dev.bgls[0][0]['binding']) == 0
      and 'buffer' in p1_dev.bgls[0][0], p1_dev.bgls[0])
check('A5 p1 pipeline layout 只引用这 1 组',
      len(p1_dev.pipeline_layouts) == 1 and len(p1_dev.pipeline_layouts[0]) == 1,
      p1_dev.pipeline_layouts)

print('=' * 60)
print('B. p1 的两段 WGSL 自洽')
print('=' * 60)

_vs = getattr(VR, '_MAIN_P1_VERT', '')
_fs = getattr(VR, '_MAIN_P1_FRAG', '')
check('B1 p1 顶点/片段源码都存在且非空', bool(_vs.strip()) and bool(_fs.strip()),
      (len(_vs), len(_fs)))
check('B2 p1 不引用主 pass 的 Scene/Bucket 块（逃生舱只画清屏）',
      'sc.' not in _vs and 'bkt.' not in _fs and 'lights[' not in _fs, '')
check('B3 p1 片段有 @fragment 入口、顶点有 @vertex 入口',
      '@fragment' in _fs and '@vertex' in _vs, '')

print('=' * 60)
print('C. 对照: 默认 stage=p4 走另一条路径（证明本测试在区分 stage）')
print('=' * 60)

p4_dev = _FakeDevice()
VR.VkRenderer(p4_dev, 'rgba8unorm')
check('C1 默认 p4 的 BGL 不是 1 条 binding（与 p1 明显不同）',
      len(p4_dev.bgls[0]) > 1, len(p4_dev.bgls[0]))
check('C2 默认 p4 建的管线数 > p1',
      len(p4_dev.pipelines) > len(p1_dev.pipelines),
      (len(p4_dev.pipelines), len(p1_dev.pipelines)))

print('=' * 60)
if _fails:
    print('FAIL 汇总: %d 项 —— %s' % (len(_fails), ', '.join(_fails)))
else:
    print('VK P1 逃生舱管线 全部 PASS')