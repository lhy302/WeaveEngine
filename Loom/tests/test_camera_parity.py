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


"""test_camera_parity.py — P5 面「相机轨道 / 开发者视角」两端对拍门（无头，2026-11-19）。

上位判据（人类 2026-11-18，docs/guides/开发要求_后端API一致_JVM模型.md §1.3）：
  「两种后端没有用户可感知的差异……如同 JVM 虚拟机在任何 CPU 上都保证字节码解析效果
    一样，不管选择什么后端对用户脚本的表现一致。」

**统一判据（本门的唯一判据）**：不论走哪条路径，两端「相机位姿」必须逐值相等 ——
位姿定义为三元组 (眼睛位置, 前向, 上方向)，且**两端都要等于手算期望表**
（期望值不取自任何一端；算法见「期望值怎么算」段）。

六组（同一份场景 + 同一串脚本级调用/输入 → 两端逐项相等，不是「各自为 True」）：
  ① 轨道相机   orbit_mode=True 下 target/yaw/pitch/distance 各种组合（负角度 / 负 target /
               入口最小距离 0.5 / 超大 distance（入口 1000 与**运行期写入 5000**）/
               pitch 接近 ±90°）→ 两端位姿三元组逐值相等且 = 手算期望表。
  ② ⭐ 脚本写角度字段（**Q-B7-45-1 正式断言**）：**同一份真实注册脚本**在 update() 里写
               engine.camera_yaw / camera_pitch（用户脚本转轨道相机就是这么写的）→
               两端轨道相机位姿都跟着变且相等、且 = 按新角度手算的期望表。
  ③ 玩家相机模式 orbit_mode=False：场景 active_camera 经 apply_camera 写入后两端位姿相等且
               = 由场景相机块手算的期望表；运行期改相机实体再 apply_camera 同；脚本直接写
               engine.camera = Point3D(...) 后两端相等且 = 期望。
  ④ 开发者视角鼠标（apply_dev_camera_mouse）：喂同一串鼠标增量（右键拖动 + 滚轮）→ 两端
               位姿逐值相等且 = 按「0.01 弧度/像素、pitch 钳 ±1.55、distance*=exp(-wheel*0.1)
               再钳 0.5..1000」手算的期望表。VK 的 dev_mouse_enabled 默认 False，按
               **生产方式**（vk_player.py:610 读 LOOM_VK_DEVMOUSE）开启。
  ⑤ 相机挂父（运行时变换传播）：相机挂在父物体下，父物体**运行期**移动/旋转后两端位姿
               相等且 = 由父变换手算的期望表（P1 门验的是加载期的场景→相机，本组验运行时）。
  ⑥ 投影参数   fov / near / far / ortho / ortho_size → 两端「投影参数逐项相等 + 投影矩阵逐
               元素相等」，并且从两端**生产 VP** 反解出的 view 矩阵必须仍是正交基
               （= 证明两端渲染器真的用这个 P，不是只在测试里算了一遍）。

两端生产入口（不拼假对象、不手写公式绕过生产路径；§5 反模式 8）：
  GL : runtime.PlayerApp(None, W, H, ctx=离屏 GL 上下文, scene_data=场景)
       —— **玩家实际发布的打包 GL 入口**（build_entry / game_player / --run 全走它）。
       渲染帧 = loom_render.render:1128（相机段在 _prepare_main_pass:1043：
       orbit_mode → apply_orbit_camera() → V = mat4_view_yaw_pitch(...) → self._vp = V@P）。
       GL 的开发者视角鼠标（组 ④）只存在于编辑器：editor.EditorApp._update_camera:2749
       —— 它是 GL 侧该能力的**唯一生产实现**（scene_driver.apply_dev_camera_mouse 的
       docstring 明写「公式与 GL editor._update_camera 逐位一致」），故组 ④ 的 GL 端用
       editor.EditorApp（生产类 + 生产视图 MinimalEditorView），其余五组用 PlayerApp。
  VK : scene_driver.SceneDriver() + load_from_data(场景)
       —— VK 播放器；渲染帧 = advance_logic:1063（帧首 _sync_orbit_camera_state:1929）
       + render_pose:1290（= vk_player.draw:674/681 的生产调用次序）。

位姿怎么读（只加观测，不绕生产路径）：
  · 眼睛位置：直接取生产字段 —— GL 是 app.camera（apply_orbit_camera / apply_camera 写入），
    VK 是 driver.camera_pos（同语义的 property）。两端渲染器用的就是它。
  · 前向 / 上方向：取**生产 view 矩阵**的第 3 / 第 1 列（mat4_view_yaw_pitch 把 ex/ey/ez
    作列），不另写 trig。
  · 位姿读取保真（每次测量都断言）：用「生产字段 + 生产纯函数 matlib.mat4_view_yaw_pitch /
    mat4_perspective / mat4_ortho」重建的 V@P 必须与**该后端本帧生产 VP 逐元素相等**
    （GL 的 app._vp / VK 的 render_pose 返回值）。这条把「我们读的字段 == 渲染器读的字段」
    变成可判定事实，不是假设（§5 反模式 8 的牙）。

期望值怎么算（不取自任何一端；§5 反模式 3）：
  · 轨道相机：ez = (sin yaw·cos pitch, sin pitch, cos yaw·cos pitch)，
    ey = (-sin yaw·sin pitch, cos pitch, -cos yaw·sin pitch)，eye = target - distance·ez。
    输入全部来自**场景文件 / 本门写死的脚本级赋值**，不读任何一端的中间结果。
  · 玩家相机（根）：eye = 相机实体 position，朝向 = 相机实体 yaw/pitch/roll（度→弧度，
    先按 CameraState 的环绕口径 wrap_deg 归一）。
  · 玩家相机（挂父）：eye = 局部位置 @ 父世界矩阵（S@R@T，用 matlib 三个纯函数独立算），
    世界基 = 局部基 @ 父世界旋转；再按生产同一条换算链（matlib.view_basis_to_angles →
    matlib.mat4_view_yaw_pitch）取 ez/ey —— 手算链与生产链同式同序，故可逐值相等。
  · 开发者视角鼠标：从场景相机的 (yaw0,pitch0,dist0) 出发，按生产文档化的公式逐步手算。
  · 投影：参数逐项相等 + P 由 matlib 纯函数按参数算出后逐元素相等（理由：两端都调**同一个**
    matlib.mat4_perspective / mat4_ortho，P 是参数的纯函数；再加「反解出的 view 仍是正交基」
    这条独立校验，证明后端真的用了这个 P）。

环境前提（只建输入前提，不改任何断言/语义）：
  · LOOM_LOGIC_SYNC=1 —— GL 的异步逻辑线程只在 Qt 宿主（_external_ctx=True）启用
    （engine.py:1443 注释）。本门是离屏 ctx（_external_ctx=True），故按该注释走同步路径。
  · LOOM_NO_PHYSICS=1 —— 本门只验相机面，用生产开关关掉物理（段序里的物理段仍在）。
  · LOOM_VK_DEVMOUSE=1 —— 组 ④ 用生产方式（vk_player.py:610）打开 VK 的开发者视角鼠标。
  · 本门不注入键鼠事件到窗口泵（组 ④ 直接把「本帧鼠标位置/按键/滚轮」写进生产字段，
    与宿主每帧写同一批字段同语义），**不涉及光标落点协议**（P3 的 settle_cursor 不适用）。

已知差异登记表：**必须为空**（KNOWN_DIFFS）。任何「差不多」/阈值/容差都不许。

修前红（2026-11-19，HEAD=f8239f2 实测）：
  · **Q-B7-45-1 证实**（组 ②）：GL 只有一组角度字段（轨道与玩家相机共用
    camera_yaw/camera_pitch，loom_camera.CameraMixin.apply_orbit_camera 读它）；VK 有两组
    （轨道用 self.yaw/self.pitch —— scene_driver.render_pose:1298 / camera_pos:899 /
    _sync_orbit_camera_state:1955 全读它；camera_yaw/camera_pitch 是**玩家相机**角度）。
    后果：同一份脚本写 engine.camera_yaw 想转轨道相机 → GL 生效、**VK 不生效**
    （VK 下一渲染帧帧首 _sync_orbit_camera_state 还会把 camera_yaw 覆盖回 yaw）。
    归属：scene_driver.py:624-633 / :899 / :1298 / :1952-1958（字段两组）；GL 是基准，未改。

修后绿（2026-11-19，Q-B7-45-1 已修，本门 **195 PASS / 0 FAIL**）：
  · 修法（方案 A = 按模式别名，复刻 GL 的单组语义）：SceneDriver.__setattr__ 按
    _ORBIT_ANGLE_ALIAS 表把 camera_yaw/camera_pitch 与 yaw/pitch 在 **orbit_mode=True**
    时变成同一份值（双向）；玩家相机模式（orbit_mode=False）下两组互不相干（修前行为不变）。
    帧首 _sync_orbit_camera_state 正常路径不再写这两个字段（两者已相等），只防御
    「绕过 __setattr__ 直写」的情形 —— 脚本刚写的角度不可能被帧首同步覆盖。
  · 业务代码只改 scene_driver.py（VK 侧）；**GL 一行未动**；本门断言/夹具**一行未改**
    （原本绿的 189 条逐条未动，只把 6 条红点变绿）。
  · 反向兼容：VK 的 yaw/pitch 两个名字保留且仍驱动轨道相机（探针
    tests/_tmp/qb745_script_probe.py 15/15：老写法 engine.yaw=x 的位姿 == 手算期望）。
"""

import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # Loom/
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_DIALOG'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PHYSICS'] = '1'        # 本门只验相机面（生产开关）
os.environ['LOOM_LOGIC_SYNC'] = '1'        # 无头直驱（见文件头「环境前提」）
os.environ['LOOM_VK_DEVMOUSE'] = '1'       # 组 ④：VK 开发者视角鼠标的生产开关
os.environ.setdefault('LOOM_USER_ROOT', tempfile.mkdtemp(prefix='loom_p5_userroot_'))

import numpy as np                                                # noqa: E402

import editor as editor_mod                                       # noqa: E402  GL 编辑器（组 ④ 的唯一生产实现）
import loom_camera                                                # noqa: E402  轨道相机唯一纯函数
import loom_scene_contract                                        # noqa: E402  场景版本号单点（不写死）
import moderngl                                                   # noqa: E402
import runtime                                                    # noqa: E402  GL 打包播放器（生产入口）
import scene_driver as SD                                         # noqa: E402  VK 播放器（生产入口）
from loom_scene_entities import wrap_deg                          # noqa: E402  相机角度环绕（唯一实现）
from core.primitives import Point3D                                    # noqa: E402  脚本写相机的唯一数据形态
from mathlib.matlib import (mat4_ortho, mat4_perspective, mat4_rotation,   # noqa: E402
                    mat4_scale, mat4_translation, mat4_view_yaw_pitch,
                    view_basis_to_angles)
from scripts import Script, register                              # noqa: E402  脚本生产注册路径

ok = True
KNOWN_DIFFS = []        # 已知差异登记表：必须为空；发现差异 = 红并报告，不许登记糊过去
FRAME_DT = 1.0 / 60.0
W, H = 640, 480


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def seq_check(title, rows):
    """rows = [(label, gl值, vk值), ...]：逐行打 GL vs VK 对照表并比对。"""
    bad = [(lb, g, v) for (lb, g, v) in rows if g != v]
    for lb, g, v in rows:
        print('    %-40s GL=%-52s VK=%s' % (lb, g, v))
    check(title, not bad,
          '；'.join('%s: GL=%s VK=%s' % (lb, g, v) for (lb, g, v) in bad[:3])
          if bad else '%d 步逐项相等' % len(rows))


# ============================ 结构段：递归源码扫描 ============================

def _prod_py_files():
    """生产 .py 清单（递归；排除 tests/ __pycache__/_tmp/archive/.git/assets/保存）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in ('tests', '__pycache__', '_tmp', 'archive',
                                          '.git', 'assets', '保存'))
        for fn in sorted(filenames):
            if fn.endswith('.py'):
                out.append(os.path.join(dirpath, fn))
    return out


def _grep_prod(needle):
    """在生产 .py 里找 needle（跳过整行注释），返回 [(相对路径, 行号), ...]。"""
    hits = []
    for p in _prod_py_files():
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f, 1):
                    if line.lstrip().startswith('#'):
                        continue
                    if needle in line:
                        hits.append((os.path.relpath(p, ROOT).replace('\\', '/'), i))
        except Exception:
            continue
    return hits


def _read_prod(fname):
    p = os.path.join(ROOT, fname)
    if not os.path.isfile(p):
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()


def src_has(fname, needle, must=True, why=''):
    src = _read_prod(fname)
    if src is None:
        check('结构：%s 可读' % fname, False, 'ROOT 下没有该生产模块')
        return
    found = needle in src
    check('结构：%s %s %r' % (fname, '含' if must else '不含', needle),
          found if must else (not found), why)


print("=== 〇. 结构：轨道相机公式唯一 / 两端合成点 / 开发者视角鼠标唯一 / 历史名 ===")
_eye_defs = _grep_prod('def orbit_camera_eye')
check('结构：轨道相机眼睛位置公式只有 loom_camera.orbit_camera_eye 一份实现',
      [p for (p, _l) in _eye_defs] == ['loom_camera.py'], _eye_defs)
_eye_calls = _grep_prod('self.camera = orbit_camera_eye(')
check('结构：两端各有 1 处把轨道相机合成进 self.camera（GL loom_camera.apply_orbit_camera / '
      'VK scene_driver._sync_orbit_camera_state），没有第三处',
      sorted(p for (p, _l) in _eye_calls) == ['loom_camera.py', 'scene_driver.py'],
      _eye_calls)
for _hist in ('def _orbit_camera_eye', 'def orbit_eye', 'def _apply_orbit_camera',
              'def sync_orbit_camera_state'):
    _h = _grep_prod(_hist)
    check('结构：历史名/拷贝名 %r 在全部生产文件里不存在' % _hist, not _h, _h[:4])
_aoc_defs = _grep_prod('def apply_orbit_camera')
check('结构：def apply_orbit_camera 只在 loom_camera.py（VK 不得另起一份同名方法 —— '
      '它走自己的 _sync_orbit_camera_state，两套字段语义不混）',
      [p for (p, _l) in _aoc_defs] == ['loom_camera.py'], _aoc_defs)
_sync_defs = _grep_prod('def _sync_orbit_camera_state')
check('结构：def _sync_orbit_camera_state 只在 scene_driver.py',
      [p for (p, _l) in _sync_defs] == ['scene_driver.py'], _sync_defs)
_sync_calls = _grep_prod('self._sync_orbit_camera_state()')
check('结构：VK 的轨道相机每帧/加载各同步一次（恰好 2 个调用点：load_from_data + '
      'advance_logic 帧首）',
      sorted(p for (p, _l) in _sync_calls) == ['scene_driver.py', 'scene_driver.py'],
      _sync_calls)
src_has('loom_render.py', 'self.apply_orbit_camera()', True,
        'GL 播放器每渲染帧把轨道相机合成进 self.camera（_prepare_main_pass）')
src_has('editor.py', 'self.apply_orbit_camera()', True,
        'GL 编辑器每渲染帧同位置同语义合成（editor._prepare_main_pass）')
src_has('runtime.py', 'self.apply_orbit_camera()', True,
        'GL 播放器加载时也合成一次（与 VK load_from_data 的同步点同位置）')
_vp_v = _grep_prod('mat4_view_yaw_pitch(')
check('结构：view 矩阵由同一个 matlib.mat4_view_yaw_pitch 构造（GL 播放器/编辑器 + VK 渲染）',
      {'loom_render.py', 'editor.py', 'scene_driver.py'} <= {p for (p, _l) in _vp_v},
      sorted({p for (p, _l) in _vp_v}))
src_has('scene_driver.py', 'mat4_view_yaw_pitch(np, cam_pos, yaw, pitch, roll)', True,
        'VK 的 render_pose 按模式取 (yaw,pitch,roll) —— 与 GL 同一个构造函数')
src_has('scene_driver.py', 'mat4_view_yaw_pitch(np, cam_pos, self.yaw, self.pitch)', False,
        'VK 不得再硬编码 self.yaw/self.pitch 组 VP（那样玩家相机角度永远进不了 view）')
_bva = _grep_prod('def view_basis_to_angles')
check('结构：基->角度 的逆映射只有 matlib.view_basis_to_angles 一份（两端 apply_camera 共用）',
      [p for (p, _l) in _bva] == ['mathlib/matlib.py'], _bva)
_wrap = _grep_prod('def wrap_deg')
check('结构：相机角度环绕只有 mathlib.mathutil.wrap_deg 一份（B1 批 P1 前置自 loom_scene_entities）',
      [p for (p, _l) in _wrap] == ['mathlib/mathutil.py'], _wrap)
_dev_defs = _grep_prod('def apply_dev_camera_mouse')
check('结构：def apply_dev_camera_mouse 只在 scene_driver.py（VK 侧唯一实现；GL 侧对应'
      '能力是 editor._update_camera）',
      [p for (p, _l) in _dev_defs] == ['scene_driver.py'], _dev_defs)
_dev_calls = _grep_prod('self.apply_dev_camera_mouse()')
check('结构：开发者视角鼠标在 VK 渲染帧里恰好 1 个调用点',
      sorted(p for (p, _l) in _dev_calls) == ['scene_driver.py'], _dev_calls)
src_has('scene_driver.py', "if getattr(self, 'dev_mouse_enabled', False):", True,
        'VK 的开发者视角鼠标被 dev_mouse_enabled 门控（默认关闭 = GL 播放器没有该能力）')
src_has('vk_player.py', 'driver.dev_mouse_enabled = (os.environ.get("LOOM_VK_DEVMOUSE") == "1")',
        True, 'VK 的开发者视角鼠标按生产方式由 LOOM_VK_DEVMOUSE 置位（本门组 ④ 用它开启）')
_uc = _grep_prod('def _update_camera')
check('结构：GL 侧开发者视角鼠标只有 editor._update_camera 一份实现',
      [p for (p, _l) in _uc] == ['editor.py'], _uc)
for _f, _n, _why in (
        ('editor.py', 'max(-1.55, min(1.55', 'GL 右键拖动 pitch 钳 ±1.55'),
        ('scene_driver.py', 'max(-1.55, min(1.55', 'VK 右键拖动 pitch 钳 ±1.55（同常数）'),
        ('editor.py', 'math.exp(-self.mouse_wheel * 0.1)', 'GL 滚轮推拉公式'),
        ('scene_driver.py', 'math.exp(-wheel * 0.1)', 'VK 滚轮推拉公式（同常数）'),
        ('scene_driver.py', 'self.mouse_look_sens = 0.01', 'VK 鼠标灵敏度 0.01 弧度/像素')):
    src_has(_f, _n, True, _why)
check('已知差异登记表为空（不许登记任何容差）', not KNOWN_DIFFS, KNOWN_DIFFS)


# ============================ 夹具（生产入口 + 生产构造式） ============================

_GL = {'ctx': None, 'fbos': {}}


def _gl_ctx():
    if _GL['ctx'] is None:
        _GL['ctx'] = moderngl.create_standalone_context(require=330)
    return _GL['ctx']


def _gl_fbo(w, h):
    key = (w, h)
    fbo = _GL['fbos'].get(key)
    if fbo is None:
        ctx = _gl_ctx()
        fbo = ctx.framebuffer(
            color_attachments=[ctx.renderbuffer((w, h), components=4)],
            depth_attachment=ctx.depth_renderbuffer((w, h)))
        _GL['fbos'][key] = fbo
    return fbo


ORBIT0 = {'target': [1.0, 2.0, 3.0], 'distance': 12.0, 'yaw': 0.9, 'pitch': -0.4}


def scene(camera=None, cameras=None, active=None, objects=None):
    """两端同一份场景（同一份用户内容）。"""
    return {'version': loom_scene_contract.CURRENT_VERSION,
            'camera': dict(camera or ORBIT0),
            'cameras': list(cameras or []),
            'active_camera': active,
            'objects': list(objects or []),
            'lights': [], 'materials': [], 'gravity': -9.8, 'skybox': None}


def cam_dict(cid='c1', pos=(2.0, 3.0, -4.0), yaw=35.0, pitch=-12.0, roll=0.0,
             fov=60.0, parent=None):
    return {'id': cid, 'name': '相机' + cid, 'position': list(pos),
            'yaw': yaw, 'pitch': pitch, 'roll': roll, 'fov': fov,
            'fov_locked': True, 'pitch_lock': False, 'pitch_min': -85.0,
            'pitch_max': 85.0, 'parent_id': parent, 'skybox': None}


def obj_dict(oid='o1', pos=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0),
             scale=(1.0, 1.0, 1.0), scripts=None):
    d = {'id': oid, 'name': '物体' + oid, 'type': 'cube', 'params': {'size': 1.0},
         'position': list(pos), 'rotation': list(rot), 'scale': list(scale),
         'color': '#ffffff', 'visible': True}
    if scripts:
        d['scripts'] = [{'id': s, 'vars': {}} for s in scripts]
    return d


# ---- 期望值（手算；不取自任何一端） ----

def hand_basis(yaw, pitch, roll=0.0):
    """手算 view 正交基 (ex, ey, ez)（弧度；与 mat4_view_yaw_pitch 同一套文档化约定：
    +z_view = ez 为前向；roll 负绕向 —— 本门 roll 恒 0，roll 面由 test_vk_camera_align 覆盖）。"""
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    ex = (cy, 0.0, -sy)
    ey = (-sy * sp, cp, -cy * sp)
    ez = (sy * cp, sp, cy * cp)
    if roll:
        cr, sr = math.cos(roll), math.sin(roll)
        sn = -sr
        exn = (ex[0] * cr + ey[0] * sn, ex[1] * cr + ey[1] * sn, ex[2] * cr + ey[2] * sn)
        eyn = (ey[0] * cr - ex[0] * sn, ey[1] * cr - ex[1] * sn, ey[2] * cr - ex[2] * sn)
        ex, ey = exn, eyn
    return ex, ey, ez


def hand_orbit_pose(target, yaw, pitch, distance):
    """轨道相机手算位姿：(眼睛位置, 前向, 上方向)。"""
    _ex, ey, ez = hand_basis(yaw, pitch, 0.0)
    eye = (target[0] - distance * ez[0],
           target[1] - distance * ez[1],
           target[2] - distance * ez[2])
    return eye, ez, ey


def _world_matrix_of(objd):
    """物体世界矩阵（行向量 S@R@T）—— 用 matlib 三个纯函数独立算（与生产同一套纯函数，
    不是读某一端的中间结果）。"""
    return (mat4_scale(np, objd['scale'][0], objd['scale'][1], objd['scale'][2])
            @ mat4_rotation(np, objd['rotation'][0], objd['rotation'][1], objd['rotation'][2])
            @ mat4_translation(np, objd['position'][0], objd['position'][1],
                               objd['position'][2]))


def hand_player_pose(camd, parentd=None):
    """玩家相机手算位姿（根相机 / 挂父相机）。

    根相机：eye = position，基 = hand_basis(yaw,pitch,roll)（度->弧度，按 CameraState
            的环绕口径 wrap_deg 归一）。
    挂父相机：eye = 局部位置 @ 父世界矩阵；世界基 = 局部基 @ 父世界旋转；
             再把世界基按生产同一条换算链（view_basis_to_angles -> mat4_view_yaw_pitch）
             取 ez/ey —— 与生产同式同序，故可逐值相等。
    """
    yaw = math.radians(wrap_deg(camd['yaw'], 0.0, 360.0))
    pitch = math.radians(wrap_deg(camd['pitch'], -180.0, 180.0))
    roll = math.radians(wrap_deg(camd['roll'], -180.0, 180.0))
    ex, ey, ez = hand_basis(yaw, pitch, roll)
    if parentd is None:
        eye = tuple(float(v) for v in camd['position'])
        return eye, ez, ey
    R3 = np.asarray(mat4_rotation(np, parentd['rotation'][0], parentd['rotation'][1],
                                  parentd['rotation'][2]))[:3, :3]
    ex_w = tuple(float(v) for v in np.array(ex) @ R3)
    ey_w = tuple(float(v) for v in np.array(ey) @ R3)
    ez_w = tuple(float(v) for v in np.array(ez) @ R3)
    p = np.array([camd['position'][0], camd['position'][1], camd['position'][2], 1.0]) \
        @ _world_matrix_of(parentd)
    eye = (float(p[0]), float(p[1]), float(p[2]))
    y2, p2, r2 = view_basis_to_angles(ex_w, ey_w, ez_w)
    V = mat4_view_yaw_pitch(np, eye, y2, p2, r2)
    return eye, tuple(float(v) for v in V[0:3, 2]), tuple(float(v) for v in V[0:3, 1])


# ---- 位姿读取（生产字段 + 生产纯函数；并校验重建的 V@P == 生产 VP） ----

def _proj_gl(app):
    """GL 侧投影矩阵：与 loom_render/editor 的 _prepare_main_pass 逐行同式。"""
    if getattr(app, 'ortho', False):
        h = float(getattr(app, 'ortho_size', 12.0))
        asp = app.width / max(1, app.height)
        return mat4_ortho(np, -h * asp * 0.5, h * asp * 0.5, -h * 0.5, h * 0.5,
                          app.near, app.far)
    return mat4_perspective(np, app._fov, app.width / app.height, app.near, app.far)


def _proj_vk(d, aspect):
    """VK 侧投影矩阵：与 scene_driver.render_pose 逐行同式。"""
    if getattr(d, 'ortho', False):
        h = float(getattr(d, 'ortho_size', 12.0))
        return mat4_ortho(np, -h * aspect * 0.5, h * aspect * 0.5, -h * 0.5, h * 0.5,
                          d.near, d.far)
    return mat4_perspective(np, d.fov, aspect, d.near, d.far)


def _measure_gl(app):
    eye = (float(app.camera.x), float(app.camera.y), float(app.camera.z))
    V = mat4_view_yaw_pitch(np, eye, app.camera_yaw, app.camera_pitch, app.camera_roll)
    P = _proj_gl(app)
    prod = np.asarray(app._vp, dtype=np.float64)
    return {'eye': eye,
            'fwd': tuple(float(v) for v in V[0:3, 2]),
            'up': tuple(float(v) for v in V[0:3, 1]),
            'vp': prod,
            'P': np.asarray(P, dtype=np.float64),
            'vp_ok': bool(np.array_equal(np.asarray(V) @ np.asarray(P), prod)),
            'params': (float(app._fov), float(app.near), float(app.far),
                       bool(getattr(app, 'ortho', False)),
                       float(getattr(app, 'ortho_size', 12.0)))}


def _measure_vk(d, aspect):
    eye = tuple(float(v) for v in d.camera_pos)
    if getattr(d, 'orbit_mode', True):
        yaw, pitch, roll = d.yaw, d.pitch, 0.0
    else:
        yaw, pitch, roll = d.camera_yaw, d.camera_pitch, d.camera_roll
    V = mat4_view_yaw_pitch(np, eye, yaw, pitch, roll)
    P = _proj_vk(d, aspect)
    prod, _pos = d.render_pose(aspect=aspect)
    prod = np.asarray(prod, dtype=np.float64)
    return {'eye': eye,
            'fwd': tuple(float(v) for v in V[0:3, 2]),
            'up': tuple(float(v) for v in V[0:3, 1]),
            'vp': prod,
            'P': np.asarray(P, dtype=np.float64),
            'vp_ok': bool(np.array_equal(np.asarray(V) @ np.asarray(P), prod)),
            'params': (float(d.fov), float(d.near), float(d.far),
                       bool(getattr(d, 'ortho', False)),
                       float(getattr(d, 'ortho_size', 12.0)))}


def triple(m):
    return (m['eye'], m['fwd'], m['up'])


def pose_check(label, g, v, exp, rows=None, expect_equal=True):
    """一段测量：打三列对照（GL / VK / 手算期望）并做 5 条断言。

    expect_equal=False 只用于**报告修前红**的组（组 ②）：仍打表、仍断言「= 手算期望」，
    但把「两端相等」这一条单独留给调用方报红，避免一条缺陷被拆成两条噪音。
    """
    if rows is not None:
        rows.append((label + ' ·眼睛位置', g['eye'], v['eye']))
        rows.append((label + ' ·前向', g['fwd'], v['fwd']))
        rows.append((label + ' ·上方向', g['up'], v['up']))
    print('    %-34s 期望(手算)=%s' % (label, exp))
    check(label + '：两端位姿三元组（眼睛/前向/上方向）逐值相等',
          triple(g) == triple(v),
          'GL=%r VK=%r' % (triple(g), triple(v)))
    check(label + '：GL 位姿 == 手算期望表', triple(g) == exp,
          'GL=%r 期望=%r' % (triple(g), exp))
    check(label + '：VK 位姿 == 手算期望表', triple(v) == exp,
          'VK=%r 期望=%r' % (triple(v), exp))
    check(label + '：两端生产 VP 逐元素相等（位姿 + 投影的合成结果）',
          np.array_equal(g['vp'], v['vp']),
          'max|Δ|=%.3e' % float(np.max(np.abs(g['vp'] - v['vp']))))
    check(label + '：夹具保真 —— 用生产字段重建的 V@P == 该端本帧生产 VP',
          g['vp_ok'] and v['vp_ok'], (g['vp_ok'], v['vp_ok']))


# ---- 组 ② 用：真实注册脚本（同一份脚本两端都跑） ----
ANGLE_WRITE = {'yaw': 1.234, 'pitch': 0.5}


class _CamAngleWriter(Script):
    """用户脚本转轨道相机就是这么写的：直接写 engine.camera_yaw / camera_pitch。"""
    script_id = 'p5_cam_angle_writer'

    def update(self, dt):
        self.engine.camera_yaw = ANGLE_WRITE['yaw']
        self.engine.camera_pitch = ANGLE_WRITE['pitch']


register(_CamAngleWriter)


class Pair:
    """一对生产后端（同一份场景）+ 生产帧驱动 + 位姿读取。"""

    def __init__(self, scene_data, gl='player', w=W, h=H):
        self.w, self.h = w, h
        self.aspect = w / h
        if gl == 'player':
            self.gl = runtime.PlayerApp(None, w, h, ctx=_gl_ctx(), scene_data=scene_data)
            self.gl._external_fb = _gl_fbo(w, h)
            self.gl_kind = 'PlayerApp'
        else:
            # GL 的开发者视角鼠标只存在于编辑器（生产类 + 生产兜底视图 MinimalEditorView）
            self.gl = editor_mod.EditorApp(w, h, ctx=_gl_ctx())
            self.gl._external_fb = _gl_fbo(w, h)
            self.gl.show_grid = False
            self.gl.selected_index = -1
            self.gl.selected_light_index = -1
            self.gl.selected_camera_index = -1
            self.gl.clear_scene()
            self.gl_kind = 'EditorApp'
        self.vk = SD.SceneDriver()
        self.vk._bridge_disabled = True          # 只比相机，不建物理桥
        # 生产方式（vk_player.py:609-612 逐字同一行）：开发者视角鼠标由环境开关置位，
        # 默认关闭（GL 播放器没有该能力）。组 ④ 靠这一行打开。
        self.vk.dev_mouse_enabled = (os.environ.get("LOOM_VK_DEVMOUSE") == "1")
        self.vk.load_from_data(scene_data)
        self._vk_prev_pos = None

    def gl_frame(self, dt=FRAME_DT):
        self.gl.render(dt)
        return _measure_gl(self.gl)

    def vk_frame(self, dt=FRAME_DT):
        self.vk.advance_logic(dt)
        return _measure_vk(self.vk, self.aspect)

    def frames(self, n=1, dt=FRAME_DT):
        g = v = None
        for _ in range(n):
            g = self.gl_frame(dt)
            v = self.vk_frame(dt)
        return g, v

    # ---- 组 ④：开发者视角鼠标（两端各自的生产调用次序） ----
    def dev_step(self, pos, right, wheel=0, dt=FRAME_DT):
        ed = self.gl
        ed.mouse_pos = pos                      # 宿主每帧写本帧鼠标位置（loom_gui:1405）
        ed.buttons = (0, 0, 1 if right else 0)  # 宿主每帧写按住键
        ed.mouse_wheel = wheel                  # 宿主写本帧滚轮（读后清零，loom_gui:1407）
        ed._update_camera(dt)                   # 生产相机交互（dt 显式传入 = 去抖动）
        ed.mouse_wheel = 0
        ed.render(dt)                           # 生产渲染帧（_prepare_main_pass 合成相机）
        g = _measure_gl(ed)

        d = self.vk
        if self._vk_prev_pos is not None:
            d.feed_mouse_rel(pos[0] - self._vk_prev_pos[0],
                             pos[1] - self._vk_prev_pos[1])
        self._vk_prev_pos = pos
        d.mouse_buttons = (False, False, bool(right))
        d.mouse_wheel = wheel
        d.advance_logic(dt)                     # 帧首结算增量 + apply_dev_camera_mouse
        v = _measure_vk(d, self.aspect)
        return g, v


print()
print("=== 〇'. 夹具保真：两端都是生产类 + 生产构造式 + 位姿读取可信 ===")
_p0 = Pair(scene())
check("GL 端是打包播放器 runtime.PlayerApp（生产入口）",
      type(_p0.gl) is runtime.PlayerApp, type(_p0.gl).__name__)
check("VK 端是 scene_driver.SceneDriver（生产入口）",
      type(_p0.vk) is SD.SceneDriver, type(_p0.vk).__name__)
_g0, _v0 = _p0.frames(3)
check("夹具保真：两端相机位姿都来自生产字段 + 生产纯函数，且重建的 V@P == 本帧生产 VP",
      _g0['vp_ok'] and _v0['vp_ok'], (_g0['vp_ok'], _v0['vp_ok']))
check("夹具保真：GL 的 self.camera 与 VK 的 camera_pos 都由 loom_camera.orbit_camera_eye 合成"
      "（同一份实现，逐值相等）",
      _g0['eye'] == _v0['eye']
      and _g0['eye'] == tuple(loom_camera.orbit_camera_eye(
          ORBIT0['target'], ORBIT0['yaw'], ORBIT0['pitch'], ORBIT0['distance'])),
      (_g0['eye'], _v0['eye']))
check("夹具前提：两端场景装配出同名同序物体（同一份场景 = 同一串用户内容）",
      [m.name for m in _p0.gl.models] == [m.name for m in _p0.vk.models],
      ([m.name for m in _p0.gl.models], [m.name for m in _p0.vk.models]))
check("夹具前提：GL 在轨道模式、VK 也在轨道模式（无 active_camera）",
      _p0.gl.orbit_mode is True and _p0.vk.orbit_mode is True,
      (_p0.gl.orbit_mode, _p0.vk.orbit_mode))


# ============================ ① 轨道相机 ============================
print()
print("=== ①. 轨道相机：target/yaw/pitch/distance 各种组合 → 两端位姿相等且 = 手算期望 ===")
rows = []
# 每项：(标签, 场景相机块, 运行期脚本级写入)
ORBIT_CASES = [
    ('①-1 基线 target=(1,2,3) d=12 y=0.9 p=-0.4', dict(ORBIT0), {}),
    ('①-2 负 yaw y=-1.2 p=0.25', {'target': [0.0, 0.0, 0.0], 'distance': 10.0,
                                  'yaw': -1.2, 'pitch': 0.25}, {}),
    ('①-3 负 target + 入口最小距离 0.5', {'target': [-3.0, 1.5, 2.0], 'distance': 0.5,
                                          'yaw': -3.0, 'pitch': -1.2}, {}),
    ('①-4 入口最大距离 1000 + pitch≈+86°', {'target': [2.0, 0.0, -1.0], 'distance': 1000.0,
                                             'yaw': 2.8, 'pitch': 1.5}, {}),
    ('①-5 运行期写 camera_distance=5000（绕过入口钳制）',
     dict(ORBIT0), {'camera_distance': 5000.0}),
    ('①-6 pitch≈+90°（近万向锁）', {'target': [5.0, -2.0, 7.0], 'distance': 3.5,
                                    'yaw': 1.5707963267948966, 'pitch': 1.5707}, {}),
    ('①-7 pitch≈-89°（负向近万向锁）', {'target': [-1.0, 0.5, 2.0], 'distance': 4.25,
                                        'yaw': -0.4, 'pitch': -1.55}, {}),
    ('①-8 运行期改 camera_target + camera_distance（camera_follow 脚本同款写法）',
     dict(ORBIT0), {'camera_target': (4.0, 1.0, -2.0), 'camera_distance': 7.25}),
]
for _label, _cam, _writes in ORBIT_CASES:
    p = Pair(scene(camera=_cam))
    for k, val in _writes.items():
        setattr(p.gl, k, val)         # 同一串脚本级写入（GL: 属性）
        setattr(p.vk, k, val)         # 同一串脚本级写入（VK: property，语义同）
    g, v = p.frames(2)
    _t, _y, _pi, _d = (p.gl.camera_target, p.gl.camera_yaw,
                       p.gl.camera_pitch, p.gl.camera_distance)
    exp = hand_orbit_pose(_t, _y, _pi, _d)
    pose_check(_label, g, v, exp, rows)
    check(_label + '：手算输入（target/yaw/pitch/distance）两端逐项相等',
          (tuple(p.gl.camera_target), p.gl.camera_yaw, p.gl.camera_pitch,
           p.gl.camera_distance)
          == (tuple(p.vk.camera_target), p.vk.yaw, p.vk.pitch, p.vk.distance),
          ((tuple(p.gl.camera_target), p.gl.camera_yaw, p.gl.camera_pitch,
            p.gl.camera_distance),
           (tuple(p.vk.camera_target), p.vk.yaw, p.vk.pitch, p.vk.distance)))
seq_check('① 轨道相机：位姿三元组 / 生产 VP，两端逐项相等', rows)


# ============================ ② 脚本写角度字段（Q-B7-45-1） ============================
print()
print("=== ②. ⭐ 脚本写 engine.camera_yaw / camera_pitch → 两端轨道相机位姿都跟着变且相等 ===")
print("    （Q-B7-45-1 正式断言：同一份真实注册脚本，两端同一份场景）")
rows = []
ANGLE_WRITE['yaw'], ANGLE_WRITE['pitch'] = 1.234, 0.5
_p2scene = scene(objects=[obj_dict('o1', (0.0, 0.0, 0.0), scripts=['p5_cam_angle_writer'])])
p = Pair(_p2scene)
# 6 个渲染帧 = 至少 3 个逻辑帧（logic_fps 默认 30Hz，1/60 的 render_dt 两帧攒一步），
# 保证脚本的 update() 一定跑过 —— 脚本写的是常量，跑几次结果都一样。
g, v = p.frames(6)
exp = hand_orbit_pose(ORBIT0['target'], ANGLE_WRITE['yaw'], ANGLE_WRITE['pitch'],
                      ORBIT0['distance'])
rows.append(('②-1 脚本写角度后 ·眼睛位置', g['eye'], v['eye']))
rows.append(('②-1 脚本写角度后 ·前向', g['fwd'], v['fwd']))
rows.append(('②-1 脚本写角度后 ·上方向', g['up'], v['up']))
print('    期望（按脚本写的 yaw=%.3f pitch=%.3f 手算）=%s' % (ANGLE_WRITE['yaw'],
                                                          ANGLE_WRITE['pitch'], exp))
check('②-1 脚本真的跑了：两端 GL 读到的 camera_yaw/pitch 都是脚本写的值（GL 基准）',
      (p.gl.camera_yaw, p.gl.camera_pitch) == (ANGLE_WRITE['yaw'], ANGLE_WRITE['pitch']),
      (p.gl.camera_yaw, p.gl.camera_pitch))
check('②-1 **Q-B7-45-1**：脚本写 camera_yaw/camera_pitch → 两端轨道相机位姿逐值相等',
      triple(g) == triple(v), 'GL=%r VK=%r' % (triple(g), triple(v)))
check('②-1 脚本写角度后 GL 位姿 == 按新角度手算的期望表（GL 生效）',
      triple(g) == exp, 'GL=%r 期望=%r' % (triple(g), exp))
check('②-1 脚本写角度后 VK 位姿 == 按新角度手算的期望表（VK 生效）',
      triple(v) == exp, 'VK=%r 期望=%r' % (triple(v), exp))
check('②-1 脚本写角度后两端生产 VP 逐元素相等', np.array_equal(g['vp'], v['vp']),
      'max|Δ|=%.3e' % float(np.max(np.abs(g['vp'] - v['vp']))))
# 只写 pitch（同一份脚本级写法）—— 单独一条，覆盖「只动一个字段」的情况
ANGLE_WRITE['yaw'], ANGLE_WRITE['pitch'] = 1.234, -0.9
g, v = p.frames(6)
check('②-2 脚本第二组角度也真的落到了 GL 的字段上（GL 基准）',
      (p.gl.camera_yaw, p.gl.camera_pitch) == (ANGLE_WRITE['yaw'], ANGLE_WRITE['pitch']),
      (p.gl.camera_yaw, p.gl.camera_pitch))
exp2 = hand_orbit_pose(ORBIT0['target'], ANGLE_WRITE['yaw'], ANGLE_WRITE['pitch'],
                       ORBIT0['distance'])
rows.append(('②-2 脚本第二组角度（pitch=-0.9）·眼睛位置', g['eye'], v['eye']))
print('    期望（yaw=%.3f pitch=%.3f）=%s' % (ANGLE_WRITE['yaw'], ANGLE_WRITE['pitch'], exp2))
check('②-2 脚本改 pitch 后两端轨道相机位姿逐值相等（Q-B7-45-1 同一条）',
      triple(g) == triple(v), 'GL=%r VK=%r' % (triple(g), triple(v)))
check('②-2 脚本改 pitch 后 GL 位姿 == 手算期望表（GL 生效）',
      triple(g) == exp2, 'GL=%r 期望=%r' % (triple(g), exp2))
check('②-2 脚本改 pitch 后 VK 位姿 == 手算期望表（VK 生效）',
      triple(v) == exp2, 'VK=%r 期望=%r' % (triple(v), exp2))
seq_check('② 脚本写角度字段：两端位姿逐项相等', rows)


# ============================ ③ 玩家相机模式 ============================
print()
print("=== ③. 玩家相机模式（orbit_mode=False）：active_camera / 运行期 apply_camera / 脚本写 camera ===")
rows = []
_CAM3 = cam_dict('c3', pos=(2.0, 3.0, -4.0), yaw=35.0, pitch=-12.0, roll=0.0, fov=60.0)
p = Pair(scene(cameras=[_CAM3], active='c3'))
g, v = p.frames(2)
check('③-0 两端都进了玩家相机模式（apply_camera 关闭轨道相机）',
      p.gl.orbit_mode is False and p.vk.orbit_mode is False,
      (p.gl.orbit_mode, p.vk.orbit_mode))
pose_check('③-1 场景 active_camera 经 apply_camera 写入后', g, v,
           hand_player_pose(_CAM3), rows)
# 运行期改相机实体再 apply_camera（编辑器「用此相机预览」/播放器切相机同一条路）
_CAM3b = cam_dict('c3', pos=(-6.0, 1.0, 3.0), yaw=95.0, pitch=-20.0, roll=0.0, fov=40.0)
for h in (p.gl, p.vk):
    cam = h.find_camera('c3')
    cam.position = Point3D(*_CAM3b['position'])
    cam.yaw, cam.pitch, cam.roll = _CAM3b['yaw'], _CAM3b['pitch'], _CAM3b['roll']
    cam.fov = _CAM3b['fov']
    h.apply_camera(cam)
g, v = p.frames(2)
pose_check('③-2 运行期改相机实体 + apply_camera 后', g, v, hand_player_pose(_CAM3b), rows)
# 脚本直接写 engine.camera（Point3D 是 namedtuple -> 脚本的写法就是整体赋值）
for h in (p.gl, p.vk):
    h.camera = Point3D(7.0, 3.0, -1.0)
g, v = p.frames(2)
exp3 = ((7.0, 3.0, -1.0),) + hand_player_pose(_CAM3b)[1:]
pose_check('③-3 脚本直接写 engine.camera = Point3D(7,3,-1) 后', g, v, exp3, rows)
seq_check('③ 玩家相机模式：位姿三元组 / 生产 VP，两端逐项相等', rows)


# ============================ ④ 开发者视角鼠标 ============================
print()
print("=== ④. 开发者视角鼠标（apply_dev_camera_mouse）：同一串鼠标增量 → 两端位姿相等且 = 期望 ===")
print("    （GL 端 = editor.EditorApp._update_camera（GL 该能力的唯一生产实现）；"
      "VK 端 = SceneDriver.apply_dev_camera_mouse，按 LOOM_VK_DEVMOUSE 生产方式开启）")
rows = []
_CAM4 = {'target': [1.0, 2.0, 3.0], 'distance': 12.0, 'yaw': 0.6, 'pitch': -0.35}
p = Pair(scene(camera=_CAM4), gl='editor', w=1280, h=800)
check('④-0 GL 端是编辑器（开发者视角鼠标在 GL 侧只有这一条生产实现）',
      type(p.gl) is editor_mod.EditorApp, type(p.gl).__name__)
check('④-0 VK 端按生产方式打开了开发者视角鼠标（vk_player.py:610 读 LOOM_VK_DEVMOUSE）',
      p.vk.dev_mouse_enabled is True, p.vk.dev_mouse_enabled)
# 夹具前提：两端轨道相机初始位姿同源（编辑器的场景相机恢复路径 _apply_camera）
p.gl._apply_camera(_CAM4)
p.gl.orbit_mode = True
p.gl.apply_orbit_camera()
p.vk.set_mouse_lock_allowed(True)     # VK 只在锁定态累积光标增量（GL 编辑器读 mouse_pos 差值）
p.vk.set_mouse_locked(True)
p.gl.mouse_pos = (500, 400)
p.gl._cam_prev_mouse = (500, 400)
p._vk_prev_pos = (500, 400)
check('④-0 夹具前提：两端轨道相机起点逐项相等（target/yaw/pitch/distance）',
      (tuple(p.gl.camera_target), p.gl.camera_yaw, p.gl.camera_pitch, p.gl.camera_distance)
      == (tuple(p.vk.camera_target), p.vk.yaw, p.vk.pitch, p.vk.distance),
      ((tuple(p.gl.camera_target), p.gl.camera_yaw, p.gl.camera_pitch,
        p.gl.camera_distance),
       (tuple(p.vk.camera_target), p.vk.yaw, p.vk.pitch, p.vk.distance)))

_yaw4, _pitch4, _dist4 = _CAM4['yaw'], _CAM4['pitch'], _CAM4['distance']
DEV_STEPS = [
    ('④-1 右键按下并拖动 +100/-50 px', (600, 350), True, 0,
     dict(dyaw=+1.0, dpitch=+0.5)),
    ('④-2 继续拖动 -30/+20 px', (570, 370), True, 0,
     dict(dyaw=-0.3, dpitch=-0.2)),
    ('④-3 松开右键后再拖 +80/0 px（不转视角）', (650, 370), False, 0, dict()),
    ('④-4 滚轮 +1（拉近 d*=exp(-0.1)）', (650, 370), False, 1, dict(dmul=math.exp(-0.1))),
    ('④-5 滚轮 -3（拉远 d*=exp(+0.3)）', (650, 370), False, -3, dict(dmul=math.exp(0.3))),
    # 巨量上拖仍**在视口内**（GL 编辑器的右键拖动只在视口内激活 —— 编辑器有面板，
    # VK 播放器整窗即视口，这个门控本身是两端 UI 形态差异，不属相机面）：
    # 从 y=370 拖到 y=210 = dy=-160 px = pitch +1.6 rad -> 撞上 ±1.55 的钳位。
    ('④-6 右键巨量上拖（pitch 撞钳位 +1.55）', (650, 210), True, 0, dict(pitch_clamp=1.55)),
]
for _label, _pos, _right, _wheel, _delta in DEV_STEPS:
    _yaw4 += _delta.get('dyaw', 0.0)
    _pitch4 += _delta.get('dpitch', 0.0)
    _dist4 *= _delta.get('dmul', 1.0)
    if 'pitch_clamp' in _delta:
        _pitch4 = _delta['pitch_clamp']
    _pitch4 = max(-1.55, min(1.55, _pitch4))
    _dist4 = max(loom_camera.CAM_DIST_MIN, min(loom_camera.CAM_DIST_MAX, _dist4))
    g, v = p.dev_step(_pos, _right, _wheel)
    exp = hand_orbit_pose(_CAM4['target'], _yaw4, _pitch4, _dist4)
    pose_check(_label, g, v, exp, rows)
    check(_label + '：两端轨道相机字段（yaw/pitch/distance）逐项相等且 == 手算期望',
          (p.gl.camera_yaw, p.gl.camera_pitch, p.gl.camera_distance)
          == (p.vk.yaw, p.vk.pitch, p.vk.distance)
          == (_yaw4, _pitch4, _dist4),
          ((p.gl.camera_yaw, p.gl.camera_pitch, p.gl.camera_distance),
           (p.vk.yaw, p.vk.pitch, p.vk.distance),
           (_yaw4, _pitch4, _dist4)))
seq_check('④ 开发者视角鼠标：位姿三元组 / 生产 VP，两端逐项相等', rows)


# ============================ ⑤ 相机挂父（运行时变换传播） ============================
print()
print("=== ⑤. 相机挂父：父物体运行期移动/旋转后 → 两端位姿相等且 = 父变换手算期望 ===")
rows = []
_PARENT5 = obj_dict('o1', pos=(5.0, 0.0, -2.0), rot=(0.0, 0.7853981633974483, 0.0))
_CAM5 = cam_dict('c5', pos=(1.0, 1.6, 0.0), yaw=0.0, pitch=0.0, roll=0.0, fov=70.0,
                 parent='o1')
p = Pair(scene(cameras=[_CAM5], active='c5', objects=[_PARENT5]))
check('⑤-0 两端相机挂父链都恢复（cam.parent 是同一个父物体）',
      p.gl.find_camera('c5').parent is p.gl.models[0]
      and p.vk.find_camera('c5').parent is p.vk.models[0],
      (p.gl.find_camera('c5').parent is not None,
       p.vk.find_camera('c5').parent is not None))
g, v = p.frames(2)
pose_check('⑤-1 挂父相机（加载后）', g, v, hand_player_pose(_CAM5, _PARENT5), rows)

for _label, _mv, _rot in (
        ('⑤-2 父位移 +10x', (10.0, 0.0, 0.0), None),
        ('⑤-3 父再位移 +3y 且自转 90°', (0.0, 3.0, 0.0), math.pi / 2)):
    _p = dict(_PARENT5)
    _p['position'] = [_PARENT5['position'][0] + _mv[0], _PARENT5['position'][1] + _mv[1],
                      _PARENT5['position'][2] + _mv[2]]
    _p['rotation'] = list(_PARENT5['rotation'])
    if _rot is not None:
        _p['rotation'][1] = _PARENT5['rotation'][1] + _rot
    _PARENT5 = _p
    for h in (p.gl, p.vk):
        o = h.models[0]
        o.position = Point3D(*_p['position'])
        o.rotation = Point3D(*_p['rotation'])
    g, v = p.frames(2)
    pose_check(_label, g, v, hand_player_pose(_CAM5, _p), rows)
    check(_label + '：相机真的跟着父动了（眼睛位置与加载时不同）',
          g['eye'] != tuple(hand_player_pose(_CAM5)[0]), g['eye'])
seq_check('⑤ 相机挂父（运行时传播）：位姿三元组 / 生产 VP，两端逐项相等', rows)


# ============================ ⑥ 投影参数 ============================
print()
print("=== ⑥. 投影参数 fov/near/far/ortho/ortho_size → 参数逐项相等 + 投影矩阵逐元素相等 ===")
print("    （理由：两端都调同一个 matlib.mat4_perspective / mat4_ortho，P 是参数的纯函数；"
      "另加「反解出的 view 仍是正交基」这条独立校验，证明后端真的用了这个 P）")
rows = []
PROJ_CASES = [
    ('⑥-1 透视 fov=60 默认 near/far', dict(ORBIT0), {}),
    ('⑥-2 透视 fov=35', {'target': [0.0, 0.0, 0.0], 'distance': 8.0, 'yaw': 0.3,
                        'pitch': -0.2, 'fov': 35.0}, {}),
    ('⑥-3 透视 fov=90 + 运行期改 near/far',
     {'target': [0.0, 0.0, 0.0], 'distance': 8.0, 'yaw': 0.3, 'pitch': -0.2,
      'fov': 90.0}, {'near': 0.05, 'far': 500.0}),
    ('⑥-4 正交 ortho=True ortho_size=12',
     {'target': [0.0, 0.0, 0.0], 'distance': 8.0, 'yaw': 0.3, 'pitch': -0.2,
      'ortho': True, 'ortho_size': 12.0}, {}),
    ('⑥-5 正交 ortho_size=6.5', {'target': [1.0, 0.0, 2.0], 'distance': 5.0,
                                 'yaw': -0.7, 'pitch': 0.15, 'ortho': True,
                                 'ortho_size': 6.5}, {}),
]
for _label, _cam, _writes in PROJ_CASES:
    p = Pair(scene(camera=_cam))
    for k, val in _writes.items():
        setattr(p.gl, k, val)
        setattr(p.vk, k, val)
    g, v = p.frames(2)
    rows.append((_label + ' ·投影参数', g['params'], v['params']))
    check(_label + '：投影参数（fov/near/far/ortho/ortho_size）逐项相等',
          g['params'] == v['params'], (g['params'], v['params']))
    check(_label + '：投影矩阵逐元素相等',
          np.array_equal(g['P'], v['P']),
          'max|Δ|=%.3e' % float(np.max(np.abs(g['P'] - v['P']))))
    check(_label + '：两端生产 VP 逐元素相等（参数相等 + 位姿相等 的合成结果）',
          np.array_equal(g['vp'], v['vp']),
          'max|Δ|=%.3e' % float(np.max(np.abs(g['vp'] - v['vp']))))
    check(_label + '：夹具保真 —— 重建的 V@P == 该端本帧生产 VP（两端真的用这个 P）',
          g['vp_ok'] and v['vp_ok'], (g['vp_ok'], v['vp_ok']))
    check(_label + '：位姿三元组也逐值相等（投影改动不影响位姿）',
          triple(g) == triple(v), 'GL=%r VK=%r' % (triple(g), triple(v)))
seq_check('⑥ 投影参数 / 投影矩阵：两端逐项相等', rows)


# ============================ 收尾 ============================
print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
