# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
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


"""test_scene_contract.py — **场景契约模块门**（B7-16，2026-11-18）。

人类裁决（原话）：
  「场景迁移功能我好像也明确要求单独一个模块，因为**只是数据到数据的转换，不需要涉及
    复杂的内部操作**，且如果在特定场景下转换是有问题的话**修起来也容易**。」

所以本门锁的是「这个模块真的是纯数据 -> 数据」+「它是唯一真源 / 唯一入口」，
全部**不需要 GPU / 窗口 / 引擎实例**就能跑：

  A. **能单独 import**：子进程 import loom_scene_contract 后 sys.modules 里不得出现
     engine / sceneio / moderngl / wgpu / glfw / pygame / numpy / vk_renderer /
     scene_driver / runtime —— 否则「能单独 import 测试」就是空话（契约模块一旦拖进
     引擎，就再也不能脱离 GPU 环境单测）。
  B. **CURRENT_VERSION 是唯一真源**：== 12；sceneio.SCENE_VERSION 是它的别名；
     sceneio 源码里**不再**出现 SCENE_VERSION = 12（不许再定义）。
  C. **gate 语义**（= 原 check_engine_version，纯搬家不许改）：无字段放行 / 更高版本抛 /
     非法类型抛 / 当前版本恰好满足时放行 / 更低要求放行。
  D. **migrate 语义**（= 原 sceneio.migrate）：v8 相机弧度->度、v1 物体补 id、
     version 抬到当前版本、非 dict 降级不抛、v3/v4 老格式补齐。
  E. **prepare 只是便捷组合**：闸门**只有一道、在 migrate() 里面**（prepare 不再自己额外
     gate —— B7-16 复查 P0-2 实测那道是冗余的，删掉后本门曾 36 PASS / 0 FAIL = 死断言）。
     真实不变量：更高版本场景**被拒**且抛错后 data 原样（闸门先于任何数据变更，这正是 R5
     「加载失败把当前场景清空」的根因面）、迁移到 CURRENT_VERSION、幂等、迁移恰好跑 1 次。
  F. **sceneio 的同名符号是同一份实现**（re-export 不许各写一份）；且 sceneio.prepare
     的迁移那一步**真的经过 sceneio.migrate 这个符号**（tests/test_scene_load_parity.py
     的 ③-migrate 就是按这个符号观察 VK 装配路径的）。

结构面「其它文件 0 处 gate( / check_engine_version( / sceneio.gate( / migrate(」在
tests/test_scene_load_parity.py 的 ③-gate / ③-migrate（那里要两端真实实例，且递归扫
Loom/**/*.py），本门不重复造。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # Loom/
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_DIALOG', '1')
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

import loom_scene_contract as C              # noqa: E402
import sceneio as S                          # noqa: E402

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


# ==================== A. 契约模块能单独 import（不拉引擎/GPU） ====================
_FORBIDDEN_ROOTS = ('engine', 'engine_core', 'sceneio', 'scene_driver', 'runtime',
                    'vk_renderer', 'vk_player', 'moderngl', 'wgpu', 'glfw',
                    'pygame', 'numpy', 'loom_render', 'loom_model_gpu', 'editor')

_PROBE = ("import sys\n"
          "import loom_scene_contract as C\n"
          "bad = sorted({m.split('.')[0] for m in sys.modules} & set(%r))\n"
          "print('VERSION=%%s' %% (C.CURRENT_VERSION,))\n"
          "print('BAD=%%s' %% (','.join(bad),))\n") % (_FORBIDDEN_ROOTS,)


def t_standalone_import():
    print()
    print('=== A. 契约模块能单独 import（不拉 engine / GPU / 窗口） ===')
    env = dict(os.environ)
    env['PYTHONPATH'] = ROOT
    env['PYTHONIOENCODING'] = 'utf-8'
    p = subprocess.run([sys.executable, '-c', _PROBE], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
    out = (p.stdout or '') + (p.stderr or '')
    got_ver = ''
    bad = '<none>'
    for line in (p.stdout or '').splitlines():
        if line.startswith('VERSION='):
            got_ver = line[len('VERSION='):].strip()
        elif line.startswith('BAD='):
            bad = line[len('BAD='):].strip()
    check('A1 子进程 import loom_scene_contract 成功（无异常）',
          p.returncode == 0 and got_ver != '', out.strip()[-160:])
    check('A2 子进程读到的 CURRENT_VERSION == 12', got_ver == '12', got_ver)
    check('A3 import 契约模块不拉 engine / sceneio / GPU / 窗口模块',
          bad == '', '被拖进来的模块: %s' % (bad,))


# ==================== B. CURRENT_VERSION 唯一真源 ====================
def t_single_source():
    print()
    print('=== B. CURRENT_VERSION 是唯一真源（sceneio 只 re-export） ===')
    check('B1 CURRENT_VERSION == 12', C.CURRENT_VERSION == 12, C.CURRENT_VERSION)
    check('B2 sceneio.SCENE_VERSION 是别名（值相同）',
          S.SCENE_VERSION == C.CURRENT_VERSION, (S.SCENE_VERSION, C.CURRENT_VERSION))
    src = open(os.path.join(ROOT, 'sceneio.py'), encoding='utf-8').read()
    check('B3 sceneio 源码里不再出现 SCENE_VERSION = 12（不许再定义）',
          'SCENE_VERSION = 12' not in src, '')
    check('B4 sceneio 从契约模块 import（唯一真源）',
          'from loom_scene_contract import' in src, '')


# ==================== C. gate 语义 ====================
def t_gate():
    print()
    print('=== C. gate 语义（= 原 check_engine_version，纯搬家不许改） ===')
    check('C1 无 min_engine_version -> 放行（旧场景/Hub 场景兼容）',
          C.gate({'version': 11}) is True)
    check('C2 非 dict -> 放行（容错加载）', C.gate(None) is True)

    def _raises(d, **kw):
        try:
            C.gate(d, **kw)
        except C.SceneVersionError:
            return True
        except BaseException:
            return False
        return False

    check('C3 要求版本高于当前引擎 -> 抛 SceneVersionError',
          _raises({'min_engine_version': '99.0.0'}))
    check('C4 非法类型（int）-> 抛（字段存在就必须合法）',
          _raises({'min_engine_version': 3}))
    check('C5 空串 -> 抛', _raises({'min_engine_version': '   '}))
    check('C6 不可解析（banana）-> 抛（不 fail-open）',
          _raises({'min_engine_version': 'banana'}))
    check('C7 当前引擎版本恰好满足 -> 放行',
          C.gate({'min_engine_version': C.ENGINE_VERSION}) is True)
    check('C8 更低要求 -> 放行',
          C.gate({'min_engine_version': '0.0.1'}) is True)


# ==================== D. migrate 语义 ====================
def t_migrate():
    print()
    print('=== D. migrate 语义（= 原 sceneio.migrate） ===')
    d8 = {'version': 8,
          'objects': [{'id': 'o1', 'name': 'o1', 'type': 'cube'}],
          'cameras': [{'id': 'c1', 'name': 'c1',
                       'yaw': 1.5707963267948966, 'pitch': 1.5707963267948966}]}
    m8 = C.migrate(d8)
    check('D1 v8 相机 yaw 弧度 -> 度（90.0，不是 1.5707963）',
          m8['cameras'][0]['yaw'] == 90.0, m8['cameras'][0]['yaw'])
    check('D2 v8 相机 pitch 弧度 -> 度', m8['cameras'][0]['pitch'] == 90.0,
          m8['cameras'][0]['pitch'])
    check('D3 迁移后 version = CURRENT_VERSION', m8['version'] == C.CURRENT_VERSION,
          m8['version'])
    check('D4 迁移原地改并返回同一对象（既有契约）', m8 is d8)

    v1 = {'version': 1, 'objects': [{'name': 'noid', 'type': 'cube'}]}
    m1 = C.migrate(v1)
    oid = m1['objects'][0].get('id')
    check('D5 v1 物体无 id -> 迁移补出非空字符串 id',
          isinstance(oid, str) and len(oid) > 0, oid)
    check('D6 v1 迁移补 parent_id / prefab_ref',
          m1['objects'][0].get('parent_id') is None
          and m1['objects'][0].get('prefab_ref') is None)

    junk = C.migrate(['not', 'a', 'dict'])
    check('D7 非 dict -> 降级成空场景（不抛）',
          isinstance(junk, dict) and junk.get('objects') == []
          and junk.get('version') == C.CURRENT_VERSION, junk)

    v2 = {'version': 2, 'objects': []}
    m2 = C.migrate(v2)
    check('D8 v2 -> 补 lights/materials/cameras/active_camera',
          m2.get('lights') == [] and m2.get('materials') == []
          and m2.get('cameras') == [] and 'active_camera' in m2, sorted(m2))

    v3 = {'version': 3, 'objects': [{'name': 'a', 'script': {'id': 's1'}}]}
    m3 = C.migrate(v3)
    check('D9 v3 单 script 字段 -> scripts 数组（且删掉旧键）',
          m3['objects'][0].get('scripts') == [{'id': 's1'}]
          and 'script' not in m3['objects'][0], m3['objects'][0])


# ==================== E. prepare = 便捷组合（闸门在 migrate 内，唯一一道） ====================
def t_prepare():
    print()
    print('=== E. prepare = 便捷组合（闸门在 migrate 内唯一一道）+ 迁移 + 幂等 ===')

    # E0：prepare 必须**恰好**跑一次迁移实现 —— 它是便捷组合，不是第二条并行路径。
    calls = []

    def _spy(d, *a, **kw):
        calls.append(1)
        return C.migrate(d, *a, **kw)

    C.prepare({'version': 8, 'objects': []}, migrate_fn=_spy)
    check('E0 prepare 恰好调用迁移实现 1 次（便捷组合，不重复跑迁移）',
          len(calls) == 1, '被调次数=%d' % (len(calls),))

    # E1/E2：真实不变量 —— 过高版本**被拒**，且拒绝时 data 原样未改（闸门先于任何数据变更）。
    # 修前状态（B7-16 复查 P0-2 实测）：prepare 里另有一道冗余 gate，于是"删 prepare 的
    # gate"或"删 migrate 的 gate"本门都 36 PASS / 0 FAIL —— E1/E2 当时是死断言。
    newer = {'version': 8, 'min_engine_version': '99.0.0',
             'cameras': [{'id': 'c1', 'yaw': 1.5707963267948966}],
             'objects': [{'name': 'x'}]}
    snapshot = repr(newer)
    raised = False
    try:
        C.prepare(newer)
    except C.SceneVersionError:
        raised = True
    check('E1 更高版本场景 prepare -> 抛 SceneVersionError（拒绝来自 migrate 内那道唯一闸门）',
          raised)
    check('E2 抛错时 data **原样未改**（闸门先于任何数据变更）',
          repr(newer) == snapshot, repr(newer))

    # E2b：prepare **自己不许再加一道闸门** —— 注入一个空迁移时它只做组合、不拦版本。
    # 这条钉住「闸门只有一道、在 migrate 内」这个裁决：谁把 gate 搬回 prepare，这里立刻红
    # （否则冗余第二道会重新掩盖"真闸门在哪"，正是 P0-2 死断言的根因）。
    raised_again = False
    try:
        C.prepare(dict(newer), migrate_fn=lambda d: d)
    except C.SceneVersionError:
        raised_again = True
    check('E2b prepare 自己不额外设闸门（注入空迁移时不拦；闸门只在 migrate 内那一道）',
          raised_again is False)

    d = {'version': 8, 'objects': [{'id': 'o', 'type': 'cube'}],
         'cameras': [{'id': 'c', 'yaw': 1.5707963267948966, 'pitch': 0.0}]}
    p1 = C.prepare(d)
    after1 = repr(p1)
    p2 = C.prepare(p1)
    check('E3 prepare 迁移到 CURRENT_VERSION', p1['version'] == C.CURRENT_VERSION,
          p1['version'])
    check('E4 prepare 幂等（连跑两次结果一致）', repr(p2) == after1,
          'once=%s twice=%s' % (after1[:60], repr(p2)[:60]))
    check('E5 prepare 返回值 = 迁移后的同一份数据（可直接喂装配）', p1 is d)
    check('E6 prepare 对「无 min_engine_version 的旧场景」照常放行并迁移',
          C.prepare({'version': 1, 'objects': [{'name': 'n'}]})['version']
          == C.CURRENT_VERSION)


# ==================== F. sceneio 的 re-export 是同一份实现 ====================
def t_reexport():
    print()
    print('=== F. sceneio 同名符号 re-export 是同一份实现（不许各写一份） ===')
    check('F1 sceneio.gate is 契约 gate', S.gate is C.gate)
    check('F2 sceneio.migrate is 契约 migrate', S.migrate is C.migrate)
    check('F3 sceneio.SceneVersionError is 契约 SceneVersionError',
          S.SceneVersionError is C.SceneVersionError)
    check('F4 sceneio.check_engine_version is 契约 gate（旧调用点不断）',
          S.check_engine_version is C.gate)
    check('F5 sceneio.ENGINE_VERSION is 契约 ENGINE_VERSION',
          S.ENGINE_VERSION == C.ENGINE_VERSION)
    check('F6 sceneio.prepare 存在（所有打开场景的路径的唯一入口）',
          callable(S.prepare))

    # sceneio.prepare 的「迁移」这一步必须真的经过 sceneio.migrate 这个符号 ——
    # tests/test_scene_load_parity.py ③-migrate 就是按这个符号观察 VK 装配路径的。
    _orig = S.migrate
    calls = []

    def _spy(d, *a, **kw):
        calls.append(1)
        return _orig(d, *a, **kw)

    S.migrate = _spy
    try:
        S.prepare({'version': 8, 'objects': []})
    finally:
        S.migrate = _orig
    check('F7 sceneio.prepare 的迁移那一步经过 sceneio.migrate 符号',
          len(calls) == 1, '被调次数=%d' % (len(calls),))


def main():
    t_standalone_import()
    t_single_source()
    t_gate()
    t_migrate()
    t_prepare()
    t_reexport()

    print()
    print('=== 汇总 ===')
    print('  FAIL 数: %d' % (len(_fails),))
    if _fails:
        print('  失败断言:')
        for n in _fails:
            print('    - %s' % n)
    print('总结果: ' + ('ALL PASS' if not _fails else '有 FAIL'))
    return 0 if not _fails else 1


if __name__ == '__main__':
    sys.exit(main())
