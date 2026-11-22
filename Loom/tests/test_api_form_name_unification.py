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


"""test_api_form_name_unification.py — **形态名统一门**（Q-B7-24-5）。

人类裁决（2026-11-22，最高依据）：
  「Q-B7-24-5：旧形态名不再用，形态名全部统一。」
执行方向 = 契约 docs/design/契约_IEngineAPI_20261117.md §4.3：**以 GL 形态名为契约名**。

本门锁三件事（对应 T3 的 A/B/C 三组）：
  A 组：契约名在两端是**同一份实现**（或已登记为本后端真差异），不许一端偷别名；
  B 组：**旧形态名已不存在** —— hasattr(SceneDriver, 旧名) 全为 False，生产源码里也没有
        同名方法定义（注释里提历史可以，代码里留旧名不行）；
  C 组：**改名不改行为** —— 用改名**之前**以旧名实测出的行为指纹（golden 常量）比对，
        新名调出来的数值必须逐位一致。

逐对考古结论（T1 表，完整证据见 docs/design/契约_IEngineAPI_20261117.md §4.3）：
  旧名(VK)                 | 契约名(GL)                 | 同义?                                                | 处置
  step(dt, aspect)         | advance_logic(dt)          | 否：step = advance_logic + 位姿，返回 (vp, cam_pos)   | 删除（GL 无同名物，生产零调用点）
  render_pose(aspect)      | render(delta_time)         | 否：render 是整帧（画+上屏），render_pose 只算位姿/VP   | 改名 compute_frame_view_proj（后端内部）
  load_from_data(data)     | load_scene(path)           | 否：一个吃已解析 dict（装配器），一个吃路径（用户 API）  | 改名 build_scene_from_data（后端内部）
  camera_pos (property)    | camera_world_position(cam) | 否：无参取「当前相机位置」vs 吃相机实体               | 改名 current_camera_position（后端内部）
  apply_dev_camera_mouse() | apply_orbit_camera()       | 否：吃鼠标增量改轨道参数 vs 由轨道参数合成位姿          | 改名 apply_editor_camera_mouse（后端内部）
"""

import os
import sys
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

import engine as E                                          # noqa: E402
import render.vk.driver as SD                               # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


GL = E.GLEngine
VK = SD.SceneDriver

# ============================================================================
# A 组：契约名 —— 同源 / 归属
# ============================================================================
print("=== A. 契约名（GL 形态名）在两端的状态 ===")

# A-1 三条已判定为**同义**的契约名：两端必须是同一个函数对象（不是各写一遍）。
SAME_IMPL = ['load_scene', 'camera_world_position', 'apply_orbit_camera']
not_same = []
missing = []
for n in SAME_IMPL:
    g = getattr(GL, n, None)
    v = getattr(VK, n, None)
    if g is None or v is None:
        missing.append((n, g is not None, v is not None))
    elif g is not v:
        not_same.append(n)
check('A-1 同义契约名两端都存在（load_scene / camera_world_position / apply_orbit_camera）',
      not missing, '缺失(名字,GL有,VK有): %s' % missing)
check('A-1 同义契约名两端是同一个函数对象（同一份实现，不是两端各写一遍）',
      not not_same, '不是同一份: %s' % not_same)

# A-2 advance_logic：两端同名（GL 形态名就是它），但实现分属各后端的帧循环
#     —— 这是**真后端差异**（GL 有异步逻辑线程 / Qt 宿主分支，VK 走 FixedStepClock），
#     已登记契约 §4.3；这里锁的是「名字两端都有」+「不许第三方偷偷别名」。
_adv_g = getattr(GL, 'advance_logic', None)
_adv_v = getattr(VK, 'advance_logic', None)
check('A-2 advance_logic 两端都有同名入口（契约名，GL 形态）',
      _adv_g is not None and _adv_v is not None, (_adv_g is not None, _adv_v is not None))
check('A-2 advance_logic 不同源时各自定义在本后端生产模块（真后端差异，不是别名转发）',
      _adv_g is not None and _adv_v is not None
      and (_adv_g is _adv_v
           or (_adv_g.__module__.startswith('render.gl')
               and _adv_v.__module__.startswith('render.vk'))),
      (_adv_g.__module__ if _adv_g else None, _adv_v.__module__ if _adv_v else None))

# A-3 render：GL 的整帧入口。VK 的整帧 = render/vk/player.py 的 draw
#     （advance_logic → 位姿/VP → VkRenderer.draw_frame → 上屏），所以 render 是
#     GL 独有后端内部入口；若 VK 将来出现同名入口，必须与 GL 同一份实现。
_ren_g = getattr(GL, 'render', None)
_ren_v = getattr(VK, 'render', None)
check('A-3 render 是 GL 侧的整帧入口（契约里登记为 GL 独有后端内部）',
      _ren_g is not None, _ren_g is not None)
check('A-3 VK 侧若出现 render 同名入口，必须是 GL 的同一份实现（当前由 player.draw 三段承担）',
      _ren_v is None or _ren_v is _ren_g,
      'VK render=%r' % (_ren_v,))

# ============================================================================
# B 组：旧形态名已不存在
# ============================================================================
print()
print("=== B. 旧形态名（VK 历史形态）已不再作为入口存在 ===")

OLD_NAMES = ['step', 'render_pose', 'load_from_data', 'camera_pos',
             'apply_dev_camera_mouse']
still_there = [n for n in OLD_NAMES if hasattr(VK, n)]
check('B-1 旧形态名在 SceneDriver 上都不再是可用入口', not still_there,
      '仍在: %s' % still_there)
for n in OLD_NAMES:
    check('B-1 旧形态名 %r 在 SceneDriver 上不可见（类与实例一致）' % n,
          hasattr(VK, n) is False, hasattr(VK, n))

# B-2 生产源码里不许再有同名方法定义（注释提历史允许）。
# 白名单 = 同名但**不同概念**的方法定义，逐条写理由。
DEF_WHITELIST = {
    ('Loom/core/interp.py', 'render_pose'):
        'InterpState.render_pose(alpha, models) 是**插值平面**计算（pos/rot/scl 的 (N,3) 矩阵），'
        '不是引擎帧入口；SceneDriver.render_pose 是后端位姿/VP 入口。两者同名不同物，'
        '且 InterpState 不在 IEngineAPI 面上（用户脚本拿不到它）。',
    ('Loom/physics/bridge.py', 'step'):
        'PhysicsWorldBridge.step(dt) 是**物理世界步进**（Culverin C 层），与引擎帧入口无关；'
        'GL/VK 两端都通过 PhysicsMixin 调它，不属于形态名范畴。',
}
SKIP_DIRS = {'__pycache__', '.git', '_tmp', 'archive', 'build', 'player_runtime',
             'node_modules', '.pytest_cache'}
def_defs = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for fn in filenames:
        if not fn.endswith('.py'):
            continue
        full = os.path.join(dirpath, fn)
        rel = os.path.relpath(full, REPO).replace(os.sep, '/')
        if rel.startswith('Loom/tests/'):
            continue          # 测试夹具自己的桩类不算生产代码
        try:
            src = open(full, 'r', encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for i, line in enumerate(src.split('\n'), 1):
            for n in OLD_NAMES:
                if re.match(r'^\s*def\s+' + n + r'\s*\(', line):
                    def_defs.append((rel, i, n, line.strip()))
unexpected = [d for d in def_defs if (d[0], d[2]) not in DEF_WHITELIST]
check('B-2 生产源码里不再有旧形态名的方法定义（白名单只有同名不同概念的两处）',
      not unexpected, '未登记的定义: %s' % (unexpected,))
for d in def_defs:
    check('B-2 白名单条目有理由：%s:%d def %s' % (d[0], d[1], d[2]),
          (d[0], d[2]) in DEF_WHITELIST, DEF_WHITELIST.get((d[0], d[2]), '（无理由）'))

# ============================================================================
# C 组：改名不改行为（golden = 改名**之前**用旧名实测的指纹）
# ============================================================================
print()
print("=== C. 行为不变：新名调出来的数值 == 改名前的 golden 指纹 ===")

import numpy as np                                          # noqa: E402
import sceneio as _sio                                      # noqa: E402

SCENE = {'version': _sio.CURRENT_VERSION,
         'camera': {'target': [1.0, 2.0, 3.0], 'distance': 12.0, 'yaw': 0.9, 'pitch': -0.4},
         'cameras': [], 'active_camera': None,
         'objects': [{'id': 'o1', 'name': '物体o1', 'type': 'cube', 'params': {'size': 1.0},
                      'position': [0.0, 0.0, 0.0], 'rotation': [0.0, 0.0, 0.0],
                      'scale': [1.0, 1.0, 1.0], 'color': '#ffffff', 'visible': True}],
         'lights': [{'id': 'l1', 'name': '灯', 'type': 'directional',
                     'direction': [0.0, -1.0, 0.0], 'color': '#ffffff', 'intensity': 1.0}],
         'materials': [], 'gravity': -9.8, 'skybox': None}

# golden 常量来源：改名**之前**在 HEAD（旧名 step/render_pose/load_from_data/
# camera_pos/apply_dev_camera_mouse 仍在）上实测，同一份 SCENE、同一串鼠标输入。
G_BUILD = (1, 1, 0, 1, True, 1.047197551197, 12.0, 0.9, -0.4)
G_CAMERA_POS = (-7.657902344128, 6.673020107704, -3.87048834309)
G_VP_SUM = 21.651874176
G_DEVMOUSE = (0.97, -0.37, 9.824769036936, 0.0)

_d = VK()
_d._bridge_disabled = True
try:
    _d.build_scene_from_data(SCENE, None)
    built = True
    err = ''
except Exception as e:                                     # 名字不存在也算红，不崩门
    built = False
    err = repr(e)
check('C-1 装配入口（新名 build_scene_from_data）可用', built, err)
if built:
    got = (len(_d.models), len(_d.materials), len(_d.cameras), len(_d.lights),
           _d.orbit_mode, round(float(_d.fov), 12), round(float(_d.distance), 12),
           round(float(_d.yaw), 12), round(float(_d.pitch), 12))
    check('C-1 装配结果与改名前的 golden 指纹逐项一致（模型/材质/相机/灯光/轨道参数）',
          got == G_BUILD, 'got=%r golden=%r' % (got, G_BUILD))

    _pos = getattr(_d, 'current_camera_position', None)
    if _pos is None:
        check('C-2 当前相机位置入口（新名 current_camera_position）存在', False)
    else:
        _pos = tuple(round(float(v), 12) for v in _pos)
        check('C-2 当前相机位置 == 改名前的 golden（且与 self.camera 同一份值）',
              _pos == G_CAMERA_POS
              and _pos == tuple(round(float(v), 12)
                                for v in (_d.camera.x, _d.camera.y, _d.camera.z)),
              'got=%r golden=%r self.camera=%r' % (_pos, G_CAMERA_POS, _d.camera))

    _vp_fn = getattr(_d, 'compute_frame_view_proj', None)
    if _vp_fn is None:
        check('C-3 位姿/VP 入口（新名 compute_frame_view_proj）存在', False)
    else:
        _vp, _cp = _vp_fn(aspect=1.6)
        _vp = np.asarray(_vp, dtype=np.float64)
        check('C-3 本帧 VP 与改名前的 golden 逐元素一致（矩阵和）',
              round(float(_vp.sum()), 9) == G_VP_SUM,
              'got=%r golden=%r' % (round(float(_vp.sum()), 9), G_VP_SUM))
        check('C-3 位姿入口返回的相机位置 == 改名前的 golden',
              tuple(round(float(v), 12) for v in _cp) == G_CAMERA_POS,
              tuple(round(float(v), 12) for v in _cp))

    _dev_fn = getattr(_d, 'apply_editor_camera_mouse', None)
    if _dev_fn is None:
        check('C-4 编辑器相机鼠标入口（新名 apply_editor_camera_mouse）存在', False)
    else:
        _d.mouse_buttons = (False, False, True)
        _d.mouse_rel = (7, -3)
        _d.mouse_wheel = 2
        _dev_fn()
        _got = (round(float(_d.yaw), 12), round(float(_d.pitch), 12),
                round(float(_d.distance), 12), float(_d.mouse_wheel))
        check('C-4 右键拖动 + 滚轮 的相机响应 == 改名前的 golden（且滚轮读后清零）',
              _got == G_DEVMOUSE, 'got=%r golden=%r' % (_got, G_DEVMOUSE))

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
