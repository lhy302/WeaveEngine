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


"""test_scene_load_parity.py — **P1 面门：场景加载/切换的用户可见结果 两端对拍**。

上位判据（人类 2026-11-18，docs/guides/开发要求_后端API一致_JVM模型.md §1.3）：
  「两种后端没有用户可感知的差异……如同 JVM 虚拟机在任何 CPU 上都保证字节码解析效果
    一样，不管选择什么后端对用户脚本的表现一致。」

本门覆盖的 6 组（同一份场景文件 / 同一串调用 → 两端逐项相等，不是"各自为 True"）：
  ① 加载成功/失败：load_scene 返回 True/False；缺文件、坏 JSON、版本过高 三种失败路径的
     返回值 + 是否抛异常 + 异常类型/文案要点 两端一致（含"失败后当前场景不被破坏"）。
  ② 加载后的场景内容：物体数 / 名字集合 / guid 集合 / 光源数 / 相机数 + active_camera /
     材质数 / 天空盒（含 solid_color 兜底）。
  ③ 场景版本迁移：v8 老场景（相机 yaw=π/2 弧度 = 90°）加载后两端 camera yaw 都必须 == 90.0
     （不是 1.5707963）—— 这是 B7-17 的缺陷面；v1 老场景（物体无 id）两端都必须补出身份；
     版本高于引擎的场景两端都必须**可见失败**。
  ④ clear_scene：models/materials/lights 全空、current_model_index==0、脚本 on_destroy 两端都派发。
  ⑤ 切换两次（A→B→A）：第二次加载 A 后内容与第一次逐项相等（材质库/桶缓存/LOD/物理桥不残留）。
  ⑥ 相对资源路径：场景引用 sky/xxx.png 时两端都按**场景文件目录**解析（不是 CWD）。

夹具纪律（§5 反模式 8：与生产同构）：
  · GL 端 = runtime.PlayerApp(..., scene_data=...)（播放器生产入口），换场景走用户 API
    load_scene(path)（内核公共实现 → _load_scene_data → sceneio.scene_from_dict）；
  · VK 端 = scene_driver.SceneDriver()（播放器生产入口），换场景走同一个 load_scene(path)
    （→ SceneDriver.load_from_data）；
  · 场景脚本用 scripts.register() 注册（= scripts/ 目录加载脚本的同一条生产注册路径），
    经场景文件 scripts:[{"id":...}] → GameObject.add_script 挂载，不手搓假对象。

留痕（**修前红**：本次只交门 + 红证据；业务代码由 B7-16 / B7-17 修复方改，本门不做修复）：
  · R1 ③-v8 VK 相机 yaw/pitch 绝对值：VK 装配路径不调 sceneio.migrate()（scene_driver.py
    只调 check_engine_version）→ v8 相机 yaw 停在 1.5707963（弧度当度用）。修点 = B7-17
    （"VK 播放器/打包游戏不做场景迁移"）。
  · R2 ③-migrate VK 装配路径经过 sceneio.migrate：migrate() 全仓只有 1 处调用点
    （sceneio.py 的 scene_from_dict 内），VK 装配路径没经过它 → 迁移不是单一入口。修点 = B7-16。
  · R3 ③-gate 闸门单一入口：check_engine_version( 有 3 处重复调用
    （agent_commands.py / editor.py / scene_driver.py），没有单一入口。修点 = B7-16
    （契约模块 loom_scene_contract.py）。**修复方若另起了模块名，改本断言的白名单。**
  · R4 ③-v1 VK 物体 guid：v1 老场景物体无 id → GL 迁移后补出 guid，VK 仍为 None。修点 = B7-16/17。
  · R5 ③-newer 失败后当前场景未被破坏：GL 侧**先 clear_scene 再校验**（migrate 在
    scene_from_dict 内），于是"加载失败"在 GL 上把当前场景清空、VK 上保留 → 失败语义不一致。
    修点 = B7-16（闸门必须在任何状态变更之前、单一入口）。
  · R6 ②-A 材质数：无 material_id 的物体，GL 把它自建的默认材质登记进材质库
    （tests/test_sceneio.py:218「v4 旧对象加载 -> 自建材质进库」锁的就是这条 GL 语义），
    VK 的 build_models 不登记 → 同一场景两端 engine.materials 条数不同（用户脚本可枚举）。
    修点：VK 装配侧复用内核 _register_model_material（**不在本门范围内修**）。
  · R8 ④-3 clear_scene 后光源：**两端都保留**（clear_scene 只清 models/materials，
    光源/相机由调用方另行清 —— editor.py:1305 _new_scene / loom_model_gpu._load_scene_data）。
    人类判据「清空后 lights 全空」因此不是 clear_scene 单独满足的，本门用 ④-6（切到无光源
    场景后 models/materials/lights 三者全空）覆盖**用户可见路径**。这条**不是两端差异**，
    如需改 clear_scene 契约请人类裁决，不属 B7-16/B7-17 范围。
  · R7 ⑥-2 GL 相对路径：GL 的 _load_scene_data 故意忽略 base_dir（loom_model_gpu.py 注释），
    从别处 CWD 启动时 GL 按 CWD 找图失败、VK 按场景目录成功。修点：GL 装配侧传 base_dir。

已知差异登记表：**必须为空**才算通过（不许用阈值/容差把差异糊过去）。
"""

import glob
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # Loom/
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_DIALOG', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')
# 配置隔离到临时用户根（run_all 也这么做；单独跑时同样不许写真实 %LOCALAPPDATA%\Loom）
os.environ.setdefault('LOOM_USER_ROOT', tempfile.mkdtemp(prefix='loom_p1_userroot_'))

import sceneio as S                                          # noqa: E402
import scripts as SCRIPTS_MOD                                # noqa: E402
import moderngl                                              # noqa: E402
import runtime                                               # noqa: E402
import scene_driver                                          # noqa: E402

_fails = []
KNOWN_DIFFS = []          # 已知差异登记表：必须为空
_DETAIL = {}


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    _DETAIL[name] = detail
    if not cond:
        _fails.append(name)


def both(label, gl_value, vk_value, note=''):
    """两端逐项相等（判据 = GL结果 == VK结果，不是各自为 True）。"""
    check('%s 两端相等' % label, gl_value == vk_value,
          'GL=%r VK=%r%s' % (gl_value, vk_value, (' ' + note) if note else ''))


# ==================== 夹具（场景文件） ====================
WORK = tempfile.mkdtemp(prefix='loom_p1_scene_')
SCRIPT_ID = 'p1_load_parity_probe'


def scene_main():
    """A：3 物体（其中 1 个不写 material_id -> 各端自建默认材质）/ 1 平行光 /
    1 相机(active) / 1 显式材质 / 场景级 solid_color 天空盒 / 1 个挂脚本的物体。"""
    return {
        'version': S.SCENE_VERSION,
        'camera': {'target': [0, 1, 0], 'distance': 8.0, 'yaw': 0.5, 'pitch': -0.3},
        'gravity': -9.8,
        'skybox': {'solid_color': [10, 20, 30, 255], 'name': 'p1_sky'},
        'materials': [{'id': 'matP1', 'name': 'matP1', 'color': '#ff3333'}],
        'objects': [
            {'id': 'gp1', 'name': 'p1_one', 'type': 'cube', 'position': [0, 0, 0],
             'material_id': 'matP1',
             'scripts': [{'id': SCRIPT_ID, 'vars': {}}]},
            {'id': 'gp2', 'name': 'p1_two', 'type': 'sphere', 'position': [2, 0, 0]},
            {'id': 'gp3', 'name': 'p1_three', 'type': 'cube', 'position': [4, 0, 0],
             'material_id': 'matP1'},
        ],
        'lights': [{'kind': 'directional', 'name': 'sunP1', 'azimuth': 30.0,
                    'elevation': 45.0, 'intensity': 1.0}],
        'cameras': [{'id': 'camP1', 'name': 'camP1', 'position': [0, 1.6, -3],
                     'yaw': 90.0, 'pitch': 0.0, 'roll': 0.0, 'fov': 60.0}],
        'active_camera': 'camP1',
    }


def scene_other():
    """B：2 物体 / 2 光源 / 无相机 / **无 skybox 键**（走默认蓝兜底）。"""
    return {
        'version': S.SCENE_VERSION,
        'gravity': -12.0,
        'materials': [{'id': 'matB1', 'name': 'matB1', 'color': '#33ff33'},
                      {'id': 'matB2', 'name': 'matB2', 'color': '#3333ff'}],
        'objects': [
            {'id': 'gb1', 'name': 'b_one', 'type': 'cube', 'position': [1, 1, 1],
             'material_id': 'matB1'},
            {'id': 'gb2', 'name': 'b_two', 'type': 'cube', 'position': [2, 2, 2],
             'material_id': 'matB2'},
        ],
        'lights': [{'kind': 'point', 'name': 'p1', 'position': [0, 3, 0], 'intensity': 2.0},
                   {'kind': 'directional', 'name': 'd1', 'azimuth': 10.0,
                    'elevation': 20.0, 'intensity': 0.5}],
        'cameras': [],
        'active_camera': None,
    }


def scene_v8():
    """v8 老场景（M41 之前）：相机 yaw/pitch 存的是**弧度**。
    yaw = π/2 弧度 = 90°；迁移后两端读到的都必须是 90.0（度），不是 1.5707963。"""
    return {
        'version': 8,
        'objects': [{'id': 'gv1', 'name': 'v8_one', 'type': 'cube'}],
        'lights': [{'kind': 'directional', 'name': 'l8', 'direction': [0, -1, 0]}],
        'cameras': [{'id': 'camV8', 'name': 'camV8', 'position': [0, 1.6, 0],
                     'yaw': math.pi / 2.0, 'pitch': math.pi / 2.0}],
        'active_camera': 'camV8',
    }


def scene_v1():
    """v1 老场景：物体**没有 id**（migrate 的 v1 分支负责生成稳定身份）。"""
    return {
        'version': 1,
        'objects': [{'name': 'v1_one', 'type': 'cube', 'position': [0, 0, 0]}],
        'lights': [],
    }


def scene_newer():
    """版本高于引擎：min_engine_version 高于当前引擎（Q-VER-1=A 的生产闸门字段）。"""
    d = scene_main()
    d['min_engine_version'] = '99.0.0'
    return d


def _write(name, data):
    p = os.path.join(WORK, name)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    return p


def _empty_scene():
    return {'version': S.SCENE_VERSION, 'objects': [], 'lights': [], 'materials': [],
            'cameras': [], 'active_camera': None}


# ==================== 两端实例（生产入口） ====================
_GL_CTX = [None]


def _gl_ctx():
    if _GL_CTX[0] is None:
        _GL_CTX[0] = moderngl.create_standalone_context(require=330)
    return _GL_CTX[0]


def new_gl():
    """GL 播放器（生产入口：runtime.PlayerApp + 场景 dict，game_pack 同一条路）。"""
    ctx = _gl_ctx()
    fbo = ctx.framebuffer(
        color_attachments=[ctx.renderbuffer((64, 64), components=4)],
        depth_attachment=ctx.depth_renderbuffer((64, 64)))
    eng = runtime.PlayerApp(None, 64, 64, ctx=ctx, scene_data=_empty_scene())
    eng._external_fb = fbo
    return eng


def new_vk():
    """VK 播放器（生产入口：scene_driver.SceneDriver）。"""
    return scene_driver.SceneDriver()


# ==================== 用户可见内容快照（两端同一份取值口径） ====================
def snapshot(eng):
    mats = list(getattr(eng, 'materials', []) or [])
    cams = list(getattr(eng, 'cameras', []) or [])
    try:
        cube = eng.effective_skybox()
    except Exception:
        cube = None
    sky_paths = None
    sky_solid = None
    if cube is not None:
        try:
            sky_solid = None if cube._solid_color is None else tuple(cube._solid_color)
        except Exception:
            sky_solid = None
        p = getattr(cube, 'paths', None)
        sky_paths = None if p is None else tuple(os.path.basename(x) for x in p)
    return {
        'n_models': len(eng.models),
        'names': sorted(str(getattr(m, 'name', '')) for m in eng.models),
        'guids': sorted(str(getattr(m, 'guid', '')) for m in eng.models),
        'n_lights': len(eng.lights),
        'light_names': sorted(str(getattr(x, 'name', '')) for x in eng.lights),
        'n_cameras': len(cams),
        'cam_names': sorted(str(getattr(c, 'name', '')) for c in cams),
        'active_camera': getattr(eng, 'active_camera', None),
        'n_materials': len(mats),
        'mat_names': sorted(str(getattr(m, 'name', '')) for m in mats),
        'sky_solid': sky_solid,
        'sky_paths': sky_paths,
        'sky_valid': bool(getattr(eng, '_skybox_valid', True)),
        'cam_yaw': [float(getattr(c, 'yaw', float('nan'))) for c in cams],
        'cam_pitch': [float(getattr(c, 'pitch', float('nan'))) for c in cams],
    }


def diff_fields(a, b):
    return [k for k in a if a[k] != b[k]]


def compare_snap(label, gl_snap, vk_snap):
    d = diff_fields(gl_snap, vk_snap)
    check('%s 两端内容逐项相等' % label, not d,
          '' if not d else '不一致项: %s' % '; '.join(
              '%s GL=%r VK=%r' % (k, gl_snap[k], vk_snap[k]) for k in d))


# ==================== ① 加载成功/失败 ====================
def group1_load_result(gl, vk, p_main, p_missing, p_bad, p_newer):
    print()
    print('=== ① 加载成功/失败（返回值 / 是否抛异常 / 异常类型与文案） ===')
    r_gl = gl.load_scene(p_main)
    r_vk = vk.load_scene(p_main)
    both('①-1 load_scene(正常场景) 返回值', r_gl, r_vk)
    check('①-1 load_scene(正常场景) 两端都为 True', r_gl is True and r_vk is True,
          'GL=%r VK=%r' % (r_gl, r_vk))

    r_gl = gl.load_scene(p_missing)
    r_vk = vk.load_scene(p_missing)
    both('①-2 缺文件 返回值', r_gl, r_vk)
    check('①-2 缺文件 两端都返回 False（不抛异常）', r_gl is False and r_vk is False,
          'GL=%r VK=%r' % (r_gl, r_vk))

    r_gl = gl.load_scene(p_bad)
    r_vk = vk.load_scene(p_bad)
    both('①-3 坏 JSON 返回值', r_gl, r_vk)
    check('①-3 坏 JSON 两端都返回 False（不抛异常）', r_gl is False and r_vk is False,
          'GL=%r VK=%r' % (r_gl, r_vk))

    exc = {}
    for tag, eng in (('GL', gl), ('VK', vk)):
        try:
            eng.load_scene(p_newer)
            exc[tag] = ('<no exception>', '')
        except BaseException as e:                       # noqa: BLE001
            exc[tag] = (type(e).__name__, str(e))
    both('①-4 版本过高 异常类型', exc['GL'][0], exc['VK'][0])
    check('①-4 版本过高 两端都抛 sceneio.SceneVersionError',
          exc['GL'][0] == exc['VK'][0] == 'SceneVersionError',
          'GL=%r VK=%r' % (exc['GL'][0], exc['VK'][0]))
    both('①-4 版本过高 异常文案', exc['GL'][1], exc['VK'][1])
    msg = exc['VK'][1]
    check('①-4 版本过高 文案含「要求版本 + 当前版本」要点',
          ('99.0.0' in msg) and (S.ENGINE_VERSION in msg)
          and ('要求' in msg) and ('当前引擎' in msg),
          msg[:120])


# ==================== ② 加载后的场景内容 ====================
def group2_content(gl, vk, p_main, p_other):
    print()
    print('=== ② 加载后的场景内容（逐项相等） ===')
    gl.load_scene(p_main)
    vk.load_scene(p_main)
    g = snapshot(gl)
    v = snapshot(vk)
    compare_snap('②-A 场景 A 加载后', g, v)
    check('②-A 物体数 = 3', g['n_models'] == v['n_models'] == 3,
          'GL=%r VK=%r' % (g['n_models'], v['n_models']))
    check('②-A 名字集合', g['names'] == v['names'] == ['p1_one', 'p1_three', 'p1_two'],
          'GL=%r VK=%r' % (g['names'], v['names']))
    check('②-A guid 集合', g['guids'] == v['guids'] == ['gp1', 'gp2', 'gp3'],
          'GL=%r VK=%r' % (g['guids'], v['guids']))
    check('②-A 光源数 = 1', g['n_lights'] == v['n_lights'] == 1,
          'GL=%r VK=%r' % (g['n_lights'], v['n_lights']))
    check('②-A 相机数 = 1 且 active_camera 同为 camP1',
          g['n_cameras'] == v['n_cameras'] == 1
          and g['active_camera'] == v['active_camera'] == 'camP1',
          'GL=(%r,%r) VK=(%r,%r)' % (g['n_cameras'], g['active_camera'],
                                     v['n_cameras'], v['active_camera']))
    check('②-A 材质数', g['n_materials'] == v['n_materials'],
          'GL=%d VK=%d GL名字=%r VK名字=%r' % (g['n_materials'], v['n_materials'],
                                              g['mat_names'], v['mat_names']))
    check('②-A 天空盒 solid_color 取值', g['sky_solid'] == v['sky_solid'] == (10, 20, 30, 255),
          'GL=%r VK=%r' % (g['sky_solid'], v['sky_solid']))

    gl.load_scene(p_other)
    vk.load_scene(p_other)
    g = snapshot(gl)
    v = snapshot(vk)
    compare_snap('②-B 场景 B（无 skybox 键）加载后', g, v)
    want = tuple(S.DEFAULT_SKYBOX_COLOR)
    check('②-B 无 skybox 键 -> 两端都是默认蓝（solid_color 兜底）',
          g['sky_solid'] == v['sky_solid'] == want,
          'GL=%r VK=%r 期望=%r' % (g['sky_solid'], v['sky_solid'], want))
    check('②-B 无相机 -> 两端 n_cameras=0 且 active_camera=None',
          g['n_cameras'] == v['n_cameras'] == 0
          and g['active_camera'] is None and v['active_camera'] is None,
          'GL=(%r,%r) VK=(%r,%r)' % (g['n_cameras'], g['active_camera'],
                                     v['n_cameras'], v['active_camera']))


# ==================== ③ 场景版本迁移 ====================
def _call_sites(needle, exclude_basenames):
    """扫源码找某个调用的落点（定义处/契约模块除外）。结构面断言用。"""
    hits = []
    for p in sorted(glob.glob(os.path.join(ROOT, '*.py'))):
        base = os.path.basename(p)
        if base in exclude_basenames:
            continue
        try:
            with open(p, encoding='utf-8') as f:
                src = f.read()
        except OSError:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if s.startswith('#'):
                continue
            if needle in s:
                hits.append('%s:%d' % (base, i))
    return hits


def group3_migration(gl, vk, p_v8, p_v1, p_main, p_newer):
    print()
    print('=== ③ 场景版本迁移（v8 弧度->度 / v1 身份 / 版本过高可见失败） ===')
    gl.load_scene(p_main)
    vk.load_scene(p_main)
    r_gl = gl.load_scene(p_v8)
    r_vk = vk.load_scene(p_v8)
    both('③-v8 加载返回值', r_gl, r_vk)
    gy = [c.yaw for c in gl.cameras]
    vy = [c.yaw for c in vk.cameras]
    gp = [c.pitch for c in gl.cameras]
    vp = [c.pitch for c in vk.cameras]
    check('③-v8 GL 相机 yaw == 90.0 度（绝对值）', gy == [90.0], 'GL yaw=%r' % (gy,))
    check('③-v8 VK 相机 yaw == 90.0 度（绝对值，不是 1.5707963）',
          vy == [90.0], 'VK yaw=%r' % (vy,))
    both('③-v8 相机 yaw', gy, vy)
    check('③-v8 GL 相机 pitch == 90.0 度（绝对值）', gp == [90.0], 'GL pitch=%r' % (gp,))
    check('③-v8 VK 相机 pitch == 90.0 度（绝对值）', vp == [90.0], 'VK pitch=%r' % (vp,))
    both('③-v8 相机 pitch', gp, vp)
    compare_snap('③-v8 v8 老场景加载后', snapshot(gl), snapshot(vk))

    # v1：物体无 id -> 迁移必须补出稳定身份（生成值，只断言"两端都有"，不断言逐字相等）
    gl.load_scene(p_v1)
    vk.load_scene(p_v1)
    gg = [getattr(m, 'guid', None) for m in gl.models]
    vg = [getattr(m, 'guid', None) for m in vk.models]
    check('③-v1 GL 物体 guid 已补出（非空字符串）',
          len(gg) == 1 and isinstance(gg[0], str) and len(gg[0]) > 0, 'GL guid=%r' % (gg,))
    check('③-v1 VK 物体 guid 已补出（非空字符串）',
          len(vg) == 1 and isinstance(vg[0], str) and len(vg[0]) > 0, 'VK guid=%r' % (vg,))
    both('③-v1 物体数', len(gl.models), len(vk.models))

    print()
    print('--- ③ 结构面：场景契约单一入口（B7-16） ---')
    contract = 'loom_scene_contract.py'      # 人类裁决 B7-16 的模块名
    sites = _call_sites('check_engine_version(', {'sceneio.py', contract})
    check('③-gate 版本闸门只由场景契约单一入口调用（其它文件 0 处）',
          sites == [], '未收敛的调用点: %s' % (sites,))
    msites = _call_sites('migrate(', {'sceneio.py', contract})
    msites = [x for x in msites if 'def migrate' not in x]
    check('③-migrate 迁移只由场景契约单一入口调用（其它文件 0 处）',
          msites == [], '未收敛的调用点: %s' % (msites,))

    print()
    print('--- ③ 行为面：VK 装配路径是否经过迁移实现 ---')
    _orig = S.migrate
    calls = []

    def _spy(d, *a, **kw):
        calls.append(1)
        return _orig(d, *a, **kw)

    S.migrate = _spy
    try:
        vk.load_scene(p_v8)
    finally:
        S.migrate = _orig
    check('③-migrate VK 装配路径经过 sceneio.migrate（迁移是唯一入口，不是各端各写）',
          len(calls) >= 1, 'sceneio.migrate 被调次数=%d' % len(calls))

    # 版本过高：可见失败 + 失败后当前场景不被破坏
    gl.load_scene(p_main)
    vk.load_scene(p_main)
    before_gl = snapshot(gl)
    before_vk = snapshot(vk)
    for _tag, eng in (('GL', gl), ('VK', vk)):
        try:
            eng.load_scene(p_newer)
        except BaseException:                            # noqa: BLE001
            pass
    after_gl = snapshot(gl)
    after_vk = snapshot(vk)
    both('③-newer 失败对当前场景的影响（GL 与 VK 各自 失败前/失败后 的差）',
         diff_fields(before_gl, after_gl), diff_fields(before_vk, after_vk))
    check('③-newer 失败后 GL 当前场景未被破坏',
          before_gl == after_gl, '被改动项: %s' % (diff_fields(before_gl, after_gl),))
    check('③-newer 失败后 VK 当前场景未被破坏',
          before_vk == after_vk, '被改动项: %s' % (diff_fields(before_vk, after_vk),))


# ==================== ④ clear_scene ====================
def group4_clear(gl, vk, p_main, p_nolight):
    print()
    print('=== ④ clear_scene（数据清空 / current_model_index / on_destroy 派发） ===')
    probe = SCRIPTS_MOD.get_script(SCRIPT_ID)
    check('④-0 夹具保真：探针脚本已按生产注册入口登记',
          probe is not None and probe is _ProbeScript, 'get_script(%r)=%r' % (SCRIPT_ID, probe))

    res = {}
    for tag, eng in (('GL', gl), ('VK', vk)):
        eng.load_scene(p_main)
        eng.update_scripts(0.016)                      # 生产路径：逻辑帧实例化脚本
        scs = [(sc.script_id, getattr(sc, '_script', None))
               for m in eng.models for sc in m.scripts]
        inst = [x for x in scs if x[0] == SCRIPT_ID]
        check('④-0 %s 场景脚本经生产挂载路径实例化' % tag,
              len(inst) == 1 and inst[0][1] is not None, '%r' % (scs,))
        _ProbeScript.DESTROYED = []
        eng.clear_scene()
        res[tag] = (snapshot(eng), len(_ProbeScript.DESTROYED),
                    getattr(eng, 'current_model_index', None))

    g_snap, g_destroyed, g_cmi = res['GL']
    v_snap, v_destroyed, v_cmi = res['VK']
    both('④-1 清空后 物体数', g_snap['n_models'], v_snap['n_models'])
    both('④-2 清空后 材质库条数', g_snap['n_materials'], v_snap['n_materials'])
    both('④-3 清空后 光源数', g_snap['n_lights'], v_snap['n_lights'])
    check('④-1..2 清空后 models/materials 全空（两端）',
          g_snap['n_models'] == v_snap['n_models'] == 0
          and g_snap['n_materials'] == v_snap['n_materials'] == 0,
          'GL=(%d,%d) VK=(%d,%d)' % (g_snap['n_models'], g_snap['n_materials'],
                                     v_snap['n_models'], v_snap['n_materials']))
    # 人类判据「清空后 lights 全空」：**clear_scene 本身两端都不碰光源/相机**
    # （既有契约：编辑器 _new_scene 在 remove_model 之后另行 lights.clear()/cameras.clear()，
    #  见 editor.py:1305；_load_scene_data 也另行清光源/相机）。这条不是两端差异，
    #  是 clear_scene 语义本身的边界 —— 见文件头留痕 R8。用户可见的「切场景后光源清空」
    #  由 ④-6（切到无光源场景后 lights 全空）覆盖。
    check('④-3 clear_scene 后光源：两端都保留（既有契约，非两端差异，见 R8）',
          g_snap['n_lights'] == v_snap['n_lights'] == 1,
          'GL=%r VK=%r' % (g_snap['n_lights'], v_snap['n_lights']))
    both('④-4 current_model_index', g_cmi, v_cmi)
    check('④-4 current_model_index == 0（两端）', g_cmi == v_cmi == 0,
          'GL=%r VK=%r' % (g_cmi, v_cmi))
    both('④-5 on_destroy 派发次数', g_destroyed, v_destroyed)
    check('④-5 脚本 on_destroy 两端都派发 1 次（GL 与 VK 都要派发，S4 已修点不许回归）',
          g_destroyed == v_destroyed == 1, 'GL=%r VK=%r' % (g_destroyed, v_destroyed))

    # ④-6 人类判据「清空后 lights 全空」的用户可见路径：切到一个**没有光源**的场景后
    # models/materials/lights 三者两端都必须为空（这条同时锁 clear_scene + 装配的清空语义）。
    gl.load_scene(p_nolight)
    vk.load_scene(p_nolight)
    g = snapshot(gl)
    v = snapshot(vk)
    both('④-6 切到无光源场景后 物体数', g['n_models'], v['n_models'])
    both('④-6 切到无光源场景后 材质库条数', g['n_materials'], v['n_materials'])
    both('④-6 切到无光源场景后 光源数', g['n_lights'], v['n_lights'])
    check('④-6 切到无光源场景后 models/materials/lights 全空（两端）',
          g['n_models'] == v['n_models'] == 0
          and g['n_materials'] == v['n_materials'] == 0
          and g['n_lights'] == v['n_lights'] == 0,
          'GL=(%d,%d,%d) VK=(%d,%d,%d)' % (g['n_models'], g['n_materials'], g['n_lights'],
                                           v['n_models'], v['n_materials'], v['n_lights']))


# ==================== ⑤ A→B→A ====================
def _residue(eng):
    """换场景后可能残留的内部缓存规模（两端同名/异名都看；None=该端没有这个缓存）。"""
    lm = getattr(eng, '_lod_models', None)
    cc = getattr(eng, '_coll_cache', None)
    bg = getattr(eng, '_bucket_geo', None)
    bi = getattr(eng, '_bucket_inst', None)
    br = getattr(eng, '_bridge', None)
    if br is None:
        br = getattr(eng, '_phys_bridge', None)
    return {
        'lod_models': None if lm is None else len(lm),
        'coll_cache': None if cc is None else len(cc),
        'bucket_geo': None if bg is None else len(bg),
        'bucket_inst': None if bi is None else len(bi),
        'phys_bridge': br is not None,
    }


def group5_switch(gl, vk, p_main, p_other):
    print()
    print('=== ⑤ 切换两次（A→B→A）：第二次 A 与第一次 A 逐项相等 ===')
    gl.load_scene(p_main)
    vk.load_scene(p_main)
    gl_a1, vk_a1 = snapshot(gl), snapshot(vk)
    gl_r1, vk_r1 = _residue(gl), _residue(vk)
    gl.load_scene(p_other)
    vk.load_scene(p_other)
    compare_snap('⑤-B 场景 B 加载后', snapshot(gl), snapshot(vk))
    gl.load_scene(p_main)
    vk.load_scene(p_main)
    gl_a2, vk_a2 = snapshot(gl), snapshot(vk)
    gl_r2, vk_r2 = _residue(gl), _residue(vk)

    check('⑤-1 GL 第二次加载 A == 第一次加载 A（无状态残留）', gl_a1 == gl_a2,
          '差异项: %s' % (diff_fields(gl_a1, gl_a2),))
    check('⑤-2 VK 第二次加载 A == 第一次加载 A（无状态残留）', vk_a1 == vk_a2,
          '差异项: %s' % (diff_fields(vk_a1, vk_a2),))
    compare_snap('⑤-3 第二次加载 A 后', gl_a2, vk_a2)
    check('⑤-4 材质库不随切换膨胀（两端 A 两次同数）',
          gl_a1['n_materials'] == gl_a2['n_materials']
          == vk_a1['n_materials'] == vk_a2['n_materials'],
          'GL=%r/%r VK=%r/%r' % (gl_a1['n_materials'], gl_a2['n_materials'],
                                 vk_a1['n_materials'], vk_a2['n_materials']))
    for tag, r1, r2 in (('GL', gl_r1, gl_r2), ('VK', vk_r1, vk_r2)):
        check('⑤-5 %s 内部缓存规模两次 A 后一致（不随历史累积）' % tag, r1 == r2,
              '第一次=%r 第二次=%r' % (r1, r2))
    both('⑤-6 物理桥存在性（纯加载/切换不建桥，惰性）',
         gl_r2['phys_bridge'], vk_r2['phys_bridge'])


# ==================== ⑥ 相对资源路径 ====================
def group6_relative(gl, vk):
    print()
    print('=== ⑥ 相对资源路径：按场景文件目录解析（不是 CWD） ===')
    proj = os.path.join(WORK, 'projA')
    sky = os.path.join(proj, 'sky')
    os.makedirs(sky, exist_ok=True)
    elsewhere = os.path.join(WORK, 'cwd_elsewhere')
    os.makedirs(elsewhere, exist_ok=True)
    import pygame
    pygame.init()
    names = ['px.png', 'nx.png', 'py.png', 'ny.png', 'pz.png', 'nz.png']
    for i, n in enumerate(names):
        s = pygame.Surface((8, 8))
        s.fill((40 + i * 10, 80, 120))
        pygame.image.save(s, os.path.join(sky, n))
    scene = {
        'version': S.SCENE_VERSION,
        'skybox': {'paths': ['sky/' + n for n in names], 'name': 'p1_six'},
        'objects': [{'id': 'gr1', 'name': 'rel_one', 'type': 'cube'}],
        'lights': [], 'materials': [], 'cameras': [], 'active_camera': None,
    }
    p = os.path.join(proj, 'scene.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(scene, f)
    old = os.getcwd()
    try:
        os.chdir(elsewhere)                    # CWD 里没有 sky/ 目录
        r_gl = gl.load_scene(p)
        r_vk = vk.load_scene(p)
        both('⑥-1 从别处 CWD 加载 返回值', r_gl, r_vk)
        g = snapshot(gl)
        v = snapshot(vk)
        check('⑥-2 GL 六面图按场景目录解析成功（_skybox_valid=True）',
              g['sky_valid'] is True, 'valid=%r err=%r' % (
                  g['sky_valid'], getattr(gl, '_skybox_error', None)))
        check('⑥-3 VK 六面图按场景目录解析成功（_skybox_valid=True）',
              v['sky_valid'] is True, 'valid=%r err=%r' % (
                  v['sky_valid'], getattr(vk, '_skybox_error', None)))
        both('⑥-4 天空盒六面文件名', g['sky_paths'], v['sky_paths'])
        both('⑥-5 天空盒有效标记', g['sky_valid'], v['sky_valid'])
        both('⑥-6 物体数（相对路径场景）', g['n_models'], v['n_models'])
    finally:
        os.chdir(old)


# ==================== 主流程 ====================
class _ProbeScript(SCRIPTS_MOD.Script):
    """夹具脚本：只记录 on_destroy 派发次数（走生产注册/挂载/实例化路径）。"""
    script_id = SCRIPT_ID
    name = 'P1LoadParityProbe'
    params = ()
    DESTROYED = []

    def on_start(self):
        pass

    def update(self, dt):
        pass

    def on_destroy(self):
        _ProbeScript.DESTROYED.append(1)


def main():
    SCRIPTS_MOD.register(_ProbeScript)
    p_main = _write('scene_main.json', scene_main())
    p_other = _write('scene_other.json', scene_other())
    p_v8 = _write('scene_v8.json', scene_v8())
    p_v1 = _write('scene_v1.json', scene_v1())
    p_newer = _write('scene_newer.json', scene_newer())
    p_nolight = _write('scene_nolight.json', {
        'version': S.SCENE_VERSION, 'objects': [], 'lights': [], 'materials': [],
        'cameras': [], 'active_camera': None})
    p_missing = os.path.join(WORK, 'does_not_exist.json')
    p_bad = os.path.join(WORK, 'broken.json')
    with open(p_bad, 'w', encoding='utf-8') as f:
        f.write('{ this is not json')

    gl = new_gl()
    vk = new_vk()

    group1_load_result(gl, vk, p_main, p_missing, p_bad, p_newer)
    group2_content(gl, vk, p_main, p_other)
    group3_migration(gl, vk, p_v8, p_v1, p_main, p_newer)
    group4_clear(gl, vk, p_main, p_nolight)
    group5_switch(gl, vk, p_main, p_other)
    group6_relative(gl, vk)

    print()
    print('=== 已知差异登记表（必须为空） ===')
    check('已知差异登记表为空（不许用阈值/容差糊差异）', not KNOWN_DIFFS,
          '登记项: %r' % (KNOWN_DIFFS,))

    print()
    print('=== 汇总 ===')
    print('  断言总数: %d' % (len(_DETAIL),))
    print('  FAIL 数: %d' % (len(_fails),))
    if _fails:
        print('  失败断言:')
        for n in _fails:
            print('    - %s' % n)
    print('总结果: ' + ('ALL PASS（两端在 P1 面上无用户可感知差异）' if not _fails
                        else '有 FAIL（两端在 P1 面上存在用户可感知差异，见上）'))
    return 0 if not _fails else 1


if __name__ == '__main__':
    sys.exit(main())
