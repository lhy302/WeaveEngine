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


"""test_editor_play_parity.py — S1 面「编辑器播放态对齐」对拍门（无头，2026-11-19）。

上位判据（人类 2026-11-19，Q-B7-47-1 / beta7）：
  「编辑器试播放的表现也要和播放器同步，不能出现编辑器上开发后测试和打包成游戏后
    播放有区别，否则开发器就失去了开发的作用，因为开发出来的东西是失真的。」
  「播放组件完全可以两边用一样的代码，编译的时候分别将代码编进去，这样就无需费力
    给两边同步，只要两边一直同源就不会出现差别。」← 判据 = **同源，不同步**。

对拍面：
  ✅ 实对拍：GL编辑器播放 (真 editor.EditorApp + toggle_play + render) vs
             GL播放器 (真 runtime.PlayerApp + render) —— 本门主体。
  ✅ S5（2026-11-20）：**四面全对拍** —— GL编辑器播放 / GL播放器 / VK编辑器播放 /
     VK播放器（S4 落地 VkEditorApp 后，S1 的两条 SKIP 换成真断言；VK 面断言用的
     采集器与 GL 面**同一个**（measure_gl / ui_tree_of / REC / _model_world），
     同源纪律：不是各写一份）。

四组断言（同一份场景 + 同一串渲染帧 → 逐项相等，且 = 手算期望；期望值不取自任何一端）：
  ① 相机 8 元组 (eye, fwd, up, yaw, pitch, roll) + fov + orbit_mode + 生产 VP ——
     期望手算：根相机 eye=相机实体 position、基=hand_basis(yaw,pitch,roll)（度→弧度、
     wrap_deg 环绕）；挂父相机 eye=局部@父世界矩阵、世界基→view_basis_to_angles→
     mat4_view_yaw_pitch（与生产同式同序）；轨道相机 eye=target-distance·ez、roll=0。
  ② 世界矩阵 _frame_world / _render_world 的 sha256（float64 tobytes）—— 两端逐帧相等，
     且静止单体矩阵 = matlib 三个纯函数手算（S@R@T，平移分量逐帧手算累加）。
  ③ 脚本钩子调用序：真实注册脚本 on_start/on_update/on_late_update 计数与顺序 ——
     期望手算：logic_fps=60、渲染帧 dt=1/60 → 每渲染帧恰 1 逻辑帧 → 帧1=[start,update,
     late]、帧2+=[update,late]；编辑器另断言退出播放追加 on_disable（播放器无此边界）。
  ④ 时钟 steps / alpha / _logic_steps_total 逐帧相等且 = 手算（每帧 1 步、alpha=0、累计=k）。
  ⑤ UI Canvas 树（canvas 元组 + 元素嵌套 (name, rect, visible, children)）逐项相等且 =
     场景 UI 段手写期望；**UI 绘制路径**：编辑器播放态每帧事件序 == ['draw_all','view_draw']
     （Canvas UI 在 FramePlan screen_ui pass = 播放器同一条路径画，view.draw 只画编辑器
     叠加层）；播放器每帧 == ['draw_all']。
  ⑥ 生效天空盒 id（Cubemap guid/name/_solid_color）逐项相等且 = 场景 skybox 段手写期望。

夹具与生产同构（§5 反模式 8）：
  · GL 播放器 = runtime.PlayerApp(None, W, H, ctx=离屏, scene_data=场景) —— 打包 GL 入口。
  · GL 编辑器 = editor.EditorApp(W, H, ctx=离屏) + 生产打开路径 _load_scene(json) +
    生产播放切换 toggle_play() + 生产渲染帧 render(dt)（默认视图 MinimalEditorView）。
  · 两端时钟都按生产入口 set_fps(logic_fps=60)；每帧喂 dt 前清 _logic_wall_last
    （engine._clock_advance docstring 的测试语义：合成 dt 且墙钟≈0 → 1 帧 = 1 逻辑帧）。

结构段（「同源，不同步」的牙）：
  · 相机策略只有 loom_render._apply_main_pass_camera 一份，播放器与编辑器各恰好 1 个调用点；
  · 挂父相机重应用只有 loom_camera._reapply_parent_camera 一份，两端各恰好 1 个调用点；
  · 编辑器调用共享 mixin 方法 _dispatch_late_update（GL 侧 def 只在 render/gl/engine.py）；
  · Canvas UI 只走 FramePlan include_ui 路径（view 层 0 处 ui.draw_all）；
  · 历史缺陷串 'self.is_playing or' 与历史名在生产代码 0 处。

修前红（2026-11-19，HEAD=530eb0b 实测，4 处缺陷未修，**207 PASS / 84 FAIL**）：
  · 结构 9 条（同源形状不存在 / 历史缺陷串在 / 视图层自画 Canvas UI 在）；
  · ① 失真1：用例 A/C 各 5 帧「编辑器相机 8 元组 ≠ 手算期望」「两端不等」「两端生产 VP
    max|Δ|=9.657e+00」（编辑器播放态每帧被陈旧轨道参数覆盖 + roll 抹 0，实测
    eye=(-4.967,-5.0,-7.094) vs 播放器 (2,3,-4)、roll 0 vs 0.262，与调研 3/3 例逐位一致）；
  · ① 失真3：用例 C 帧 2-5「两端相机 8 元组逐项相等」红 + VP |Δ| 随父移动递增
    （9.657e+00 → 9.723e+00，编辑器播放态相机不跟随挂父移动）；
  · ③ 失真2：编辑器钩子序缺 late（帧1 got [start,update]，帧2+ got [update]，
    3 用例 × 5 帧；播放器侧与手算期望逐帧相等）；
  · ⑤ 失真4：编辑器 UI 绘制路径 got [view_draw, draw_all]（Canvas UI 经 view.draw
    自画，3 用例 × 5 帧；播放器 [draw_all] 修前即绿 —— 它是基准）。
  修后绿：**291 PASS / 0 FAIL**（84 条红全部转绿 + 结构段锁定同源形状）。
  稳定性：连跑 20 次，**20/20 全绿一致**（单次约 3.2s），无偶发红。

⑦ 增补（2026-11-20，Q-B7-48-2 修后收口；本段只新增断言，既有断言一字未动）：
  修前红（tests/_tmp/qb7482_disable_probe.py 实测，HEAD=7d3dc83）：编辑器播放 5 帧 → 退出，
    5 轮退出期 on_disable 全 0（期望各 +1）；Lua VM 关闭 100% 走 script_glue.__del__ 兜底
    （on_disable 契约路径 0 次）；播放器对照：load_scene 切场景 on_destroy 照常派发。
  修后绿：5 轮退出各恰 +1 disable；VM 关闭 100% 走 on_disable 契约路径；本门新增 ⑧ 条
    （2 结构 + 3 用例 × 2 行为）后全绿（299 PASS / 0 FAIL；修前红实测 = ⑦ 组 4 条红：3 条行为 + 1 条结构，见上）。

已知差异登记表：**必须为空**（KNOWN_DIFFS）。任何「差不多」/阈值/容差都不许。

已知残差（只报告不锁，**S1 范围外、单独立项**，2026-11-19 实测留痕）：
  · **Q-B7-48-2（新发现，非 S1 四失真）→ 已修（2026-11-20，Q-B7-48-2 单独收口）**：
    编辑器「退出播放」的 on_disable 曾从未触发 —— toggle_play 退出分支第 2 步
    apply_snapshot（undo.py:164-167）先 clear_scripts()+add_script() **重建**全部脚本
    组件，原第 6 步的派发循环（editor.py:2251-2256）遍历到的已是 _script=None 的新
    组件 → scripts.py 的契约（"停止播放: 释放/复位脚本持有的外部资源"）是死代码
    （Lua VM 的停止释放路径同断链，见其 on_disable）。
    修法（同源不同步）：把**全仓唯一**一份 on_disable 派发循环前移到退出分支第 1.5 步
    （apply_snapshot 重建组件**之前**），只挪位置不改派发语义；同源复核修正：生产代码
    inst.on_disable( 派发点全仓恰 1 处，播放器入口 0 处 —— 建门时的「播放器会触发
    on_disable」经复核**不成立**：播放器（GL PlayerApp / VK SceneDriver）无退出播放
    边界，其释放契约经换场景 load_scene→clear_scene→remove_model→on_destroy 派发
    （实测照常，VM 走契约路径关闭）。修前红（tests/_tmp/qb7482_disable_probe.py）：
    编辑器播放 5 帧 → 退出，5 轮 on_disable 全 0、Lua VM 关闭 100% 走 __del__ 兜底
    （契约路径 0 次）；修后绿：5 轮退出各恰 +1 disable、VM 关闭 100% 走 on_disable
    契约路径（存活恒 0 —— 修前「疑似泄漏」实测为兜底即时回收，非线性泄漏）。
    本门 ⑦ 组锁定：退出追加恰一次 on_disable + 全仓唯一派发点在组件重建之前的结构锁。

⑧ S5（2026-11-20，Q-B7-47-1 五阶段·阶段 5）：VK 面补齐 = 四面全对拍 + 修前必红（5 处 VK
  播放/编辑态真缺陷，全部按「同源不同步」修完，本提交）：
  修前红（S5 门 VK 断言先行落笔、生产修复前实测；基线 afe58f2）：
  · ③ VK编辑器钩子序双发：['start','update','late','late'] —— SceneDriver.advance_logic
    渲染帧尾派发 LateUpdate（VK 播放器形状没有渲染帧派发点，本就需要）+ 共享 editor.render
    再派发一次 → VK 编辑器播放态每帧 on_late_update ×2（GL 三面恒单发）；
  · ⑥ VK编辑器生效天空盒恒 None —— SceneDriver.effective_skybox 场景级回落只读播放器字段
    self.skybox，编辑器共享加载写的是 GL 同名字段 _skybox → 场景天空盒整体消失
    （include_sky=False；GL/VK播放器 两面正确）；
  · ② VK编辑器 _frame_world 冻结在进播放位姿 —— VK _logic_prep 只算碰撞对、不刷新逻辑
    位姿矩阵（GL 侧 P-01 内联块 VK 侧没有）→ 抽 EngineCore._refresh_play_frame_world
    两端 _logic_prep 同调（同源唯一实现）；
  · ②/④ VK编辑器 _interp 恒 None —— 渲染矩阵落编辑态管线（= 逻辑位姿、无插值），与
    GL 编辑器播放态差 1 个逻辑帧的观感 → _EditorCore._init_editor_state 补建（GL 已有
    不触发，一行不变）；
  · 编辑态 VK 编辑器照跑逻辑帧 —— SceneDriver.advance_logic 无 is_playing 门（VK 播放器
    形状恒播放用不到），未播放脚本被实例化并 update、物体在编辑态自己动（GL 编辑态零
    逻辑）→ advance_logic 补与 GL 同一条编辑态零逻辑门（播放器形状 is_playing 恒 True
    → 行为零变化）。
  修后绿：四面逐项相等（相机/世界矩阵/钩子/时钟/UI/天空盒），断言计数见提交信息。
  修前必红复跑法：git stash Loom/editor.py Loom/render/gl/engine.py Loom/engine_core.py
  Loom/render/vk/driver.py（4 个生产文件回到修前）→ 门红；还原 → 绿。
"""

import hashlib
import json
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
os.environ['LOOM_NO_PHYSICS'] = '1'        # 本门只验播放态对齐面（生产开关）
os.environ['LOOM_LOGIC_SYNC'] = '1'        # 无头直驱（与 P5 门同前提）
os.environ.setdefault('LOOM_USER_ROOT', tempfile.mkdtemp(prefix='loom_s1_userroot_'))

import numpy as np                                                # noqa: E402

import editor as editor_mod                                       # noqa: E402  GL 编辑器（生产类）
import scene.contract as _scene_contract                                        # noqa: E402  场景版本号单点
import loom_ui                                                    # noqa: E402  Canvas UI（事件插桩）
import moderngl                                                   # noqa: E402
import runtime                                                    # noqa: E402  GL 打包播放器（生产入口）
import render.vk.driver as _sd                                       # noqa: E402  VK 播放器（生产类，S5 四面对拍）
from scene.entities import wrap_deg                          # noqa: E402  相机角度环绕（唯一实现）
from mathlib.matlib import (mat4_ortho, mat4_perspective, mat4_rotation,   # noqa: E402
                    mat4_scale, mat4_translation, mat4_view_yaw_pitch,
                    view_basis_to_angles)
from script.scripts import Script, register                              # noqa: E402  脚本生产注册路径

ok = True
KNOWN_DIFFS = []        # 已知差异登记表：必须为空
FRAME_DT = 1.0 / 60.0
LOGIC_FPS = 60.0
W, H = 640, 480
N = 5                   # 每用例渲染帧数
SPEED = 2.0             # 探针脚本移速 (世界单位/秒)


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


# ============================ 结构段：递归源码扫描 ============================

def _prod_py_files():
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


print("=== 〇. 结构：播放组件同源（同一条实现，两端 import/继承同一份；历史缺陷串 0 处） ===")
_defs = _grep_prod('def _apply_main_pass_camera')
check('结构：主 pass 相机策略只有 loom_render._apply_main_pass_camera 一份实现'
      '（播放器与编辑器继承同一份 = 同源）',
      [p for (p, _l) in _defs] == ['render/gl/render.py'], _defs)
_calls = _grep_prod('self._apply_main_pass_camera()')
check('结构：主 pass 相机策略恰好两个调用点（loom_render._prepare_main_pass + '
      'editor._prepare_main_pass）—— 编辑器不再有第二份条件',
      sorted(p for (p, _l) in _calls) == ['editor/core.py', 'render/gl/render.py'], _calls)
src_has('editor/core.py', 'self.is_playing or', False,
        '历史缺陷串（S1 修前 editor.py:2410 的第二份相机条件）已从编辑器 0 处'
        '（反模式 10：注释/代码不得与同源裁决不符）')
_rpdefs = _grep_prod('def _reapply_parent_camera')
check('结构：挂父激活相机重应用只有 loom_camera._reapply_parent_camera 一份实现',
      [p for (p, _l) in _rpdefs] == ['loom_camera.py'], _rpdefs)
_rpcalls = _grep_prod('self._reapply_parent_camera()')
check('结构：挂父相机重应用恰好两个调用点（loom_render.render + editor.render）'
      '—— 编辑器不再有复制的三行',
      sorted(p for (p, _l) in _rpcalls) == ['editor/core.py', 'render/gl/render.py'], _rpcalls)
_ludefs = _grep_prod('def _dispatch_late_update')
check('结构：def _dispatch_late_update 恰好两份（GL render/gl/engine.py + VK render/vk/driver.py，'
      '既有后端分界；编辑器调用的就是 GL 那一份共享 mixin 方法）',
      sorted(p for (p, _l) in _ludefs) == ['render/gl/engine.py', 'render/vk/driver.py'], _ludefs)
src_has('editor/core.py', 'self._dispatch_late_update(delta_time)', True,
        '编辑器渲染帧派发 LateUpdate（与 loom_render.render 同序）—— 修前 0 处，'
        '脚本 on_late_update 在编辑器播放态死掉')
src_has('editor/core.py', 'include_ui=', True,
        '编辑器 frame_plan 传 include_ui（Canvas UI 走播放器同一条 FramePlan screen_ui 路径）')
src_has('gui/main_window.py', 'ui.draw_all', False,
        'GUI 视图层不再自画 Canvas UI（view.draw 只画编辑器叠加层）')
src_has('ui/minimal_editor_view.py', 'ui.draw_all', False,
        '最小视图同上（同一条 include_ui 路径）')
for _hist in ('def _apply_render_camera', 'def apply_play_camera',
              'def _reapply_active_camera', 'def reapply_parent_camera',
              'def apply_main_pass_camera'):
    _h = _grep_prod(_hist)
    check('结构：历史名/公开别名 %r 在全部生产文件里不存在' % _hist, not _h, _h[:4])

print()
print("=== 〇''. S5 结构：四面同源（GL/VK 编辑器共用同一份 _EditorCore 方法对象） ===")
from render.gl.render import RenderMixin as _RenderMixin     # noqa: E402
from engine import GLEngine as _GLE                     # noqa: E402
_vk_mro = [cls.__name__ for cls in editor_mod.VkEditorApp.__mro__]
check('S5 结构：VkEditorApp -> _EditorCore -> SceneDriver 装配形状（S4 落地未变）',
      _vk_mro[:3] == ['VkEditorApp', '_EditorCore', 'SceneDriver'], _vk_mro[:4])
check('S5 结构：编辑器 render 是同一份函数对象（GL/VK 两入口同一条 editor.render）',
      editor_mod.EditorApp.render is editor_mod.VkEditorApp.render, '')
check('S5 结构：toggle_play 是同一份函数对象（进/出播放边界四面同源）',
      editor_mod.EditorApp.toggle_play is editor_mod.VkEditorApp.toggle_play, '')
check('S5 结构：主 pass 相机策略 = 同一函数对象再绑定（VkEditorApp._apply_main_pass_camera '
      'is loom_render.RenderMixin._apply_main_pass_camera；非复制）',
      editor_mod.VkEditorApp._apply_main_pass_camera is _RenderMixin._apply_main_pass_camera, '')
check('S5 结构：_refresh_play_frame_world 唯一实现（GL/VK 的 _logic_prep 解析到同一函数对象；'
      'getattr 口径 —— 生产修复被回退时两侧皆缺 = False，不是 AttributeError）',
      getattr(_GLE, '_refresh_play_frame_world', None)
      is getattr(_sd.SceneDriver, '_refresh_play_frame_world', None), '')
check('S5 结构：compute_world_matrices 是同一份 TransformMixin 函数对象（四面共享）',
      _GLE.compute_world_matrices is _sd.SceneDriver.compute_world_matrices, '')
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


# ---- VK 夹具（S5：与 GL 同一构造式；离屏纹理 = test_ab_gl_vk 既有口径） ----
_VK_FMT = 'rgba8unorm'
_VK = {'device': None, 'tex': None}


def _vk_device():
    if _VK['device'] is None:
        import wgpu
        adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
        if adapter is None:
            raise RuntimeError('无可用 Vulkan 适配器（与 test_ab_gl_vk 同口径：FAIL 不 SKIP）')
        _VK['device'] = adapter.request_device_sync()
    return _VK['device']


class _VkOffscreenCtx:
    """VK 离屏目标（test_ab_gl_vk.render_vk 的 Ctx 同款）：physical_size +
    get_current_texture —— VkFrameExecutor / 叠加层 flush 的宿主协议。"""

    physical_size = (W, H)

    def get_current_texture(self):
        if _VK['tex'] is None:
            import wgpu
            _VK['tex'] = _vk_device().create_texture(
                size=(W, H, 1), format=_VK_FMT,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
        return _VK['tex']


class _NullView:
    """VK 编辑器宿主视图桩（VkEditorApp 要求显式注入 IEditorView；不画叠加层 ——
    状态面对拍不涉及视图叠加层，像素面归 S5 像素门）。"""

    def attach(self, ctl):
        self.ctl = ctl

    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': True,
                'focus_id': None}

    def handle_key_event(self, ev):
        return True

    def reset_interaction(self):
        pass

    def draw(self, controller, delta_time):
        pass



# ---- 钩子记录（真实注册脚本；REC 按引擎实例分桶） ----
REC = {}


def _rec(engine, name):
    REC.setdefault(id(engine), []).append(name)


@register
class S1PlayProbe(Script):
    """S1 门探针脚本：记录钩子序 + 每逻辑帧匀速移动宿主物体（世界矩阵/挂父相机用手算）。"""
    script_id = 's1_play_probe'
    name = 'S1播放对齐探针'

    def on_start(self):
        _rec(self.engine, 'start')

    def update(self, dt):
        _rec(self.engine, 'update')
        p = self.obj.position           # Point3D 是 namedtuple（不可变）—— 整点赋值
        self.obj.position = type(p)(p.x + SPEED * dt, p.y, p.z)   # 与手算累加同式

    def on_late_update(self, render_dt):
        _rec(self.engine, 'late')

    def on_disable(self):
        _rec(self.engine, 'disable')


# ---- Canvas UI 绘制路径插桩（只加观测，不改行为） ----
UI_EVENTS = []          # ('draw_all', id(engine)) / ('view_draw', id(editor))
_orig_draw_all = loom_ui.UIManager.draw_all


def _rec_draw_all(self, engine, script_host=None):
    UI_EVENTS.append(('draw_all', id(engine)))
    return _orig_draw_all(self, engine, script_host=script_host)


loom_ui.UIManager.draw_all = _rec_draw_all


# ---- 场景构造（两端同一份用户内容） ----
def obj_dict(oid, pos=(0.0, 0.0, 0.0), scripts=None, parent=None):
    d = {'id': oid, 'name': '物体' + oid, 'type': 'cube', 'params': {'size': 1.0},
         'position': list(pos), 'rotation': [0.0, 0.0, 0.0], 'scale': [1.0, 1.0, 1.0],
         'color': '#ffffff', 'visible': True}
    if parent:
        d['parent_id'] = parent
    if scripts:
        d['scripts'] = [{'id': s, 'vars': {}} for s in scripts]
    return d


def cam_dict(cid, pos, yaw, pitch, roll, fov=60.0, parent=None):
    return {'id': cid, 'name': '相机' + cid, 'position': list(pos),
            'yaw': yaw, 'pitch': pitch, 'roll': roll, 'fov': fov,
            'fov_locked': True, 'pitch_lock': False, 'pitch_min': -85.0,
            'pitch_max': 85.0, 'parent_id': parent, 'skybox': None}


def ui_section():
    """场景 UI 段（手写期望的唯一来源：门断言 = 这棵树，不从任何一端读）。"""
    return {'canvases': [{'canvas_type': 'screen', 'z_order': 5, 'width': W, 'height': H,
                          'elements': [
                              {'type': 'panel', 'name': 'HUD底板', 'rect': [10, 20, 300, 120],
                               'anchor': [0, 0], 'pivot': [0, 0], 'visible': True,
                               'bg_color': [0, 0, 0, 128], 'children': [
                                   {'type': 'text', 'name': '分数', 'rect': [12, 22, 100, 30],
                                    'visible': True, 'text': 'SCORE 0', 'font_size': 16,
                                    'color': [255, 255, 255], 'align': 'left', 'wrap_width': 0,
                                    'children': []},
                                   {'type': 'panel', 'name': '血条', 'rect': [12, 60, 200, 14],
                                    'visible': True, 'bg_color': [200, 30, 30, 255],
                                    'children': []},
                               ]},
                          ]}]}


def scene_a():
    """用例 A：active 相机（roll=15 pitch=30，无父）+ 脚本 + UI + 场景级天空盒。"""
    return {'version': _scene_contract.CURRENT_VERSION,
            'camera': {'target': [0.0, 0.0, 0.0], 'distance': 10.0,
                       'yaw': 0.0, 'pitch': -0.35, 'fov': 60.0},
            'cameras': [cam_dict('c1', (2.0, 3.0, -4.0), 35.0, 30.0, 15.0)],
            'active_camera': 'c1',
            'objects': [obj_dict('box', scripts=['s1_play_probe'])],
            'lights': [], 'materials': [], 'gravity': -9.8,
            'skybox': {'solid_color': [255, 0, 0, 255]},
            'ui': ui_section()}


def scene_b():
    """用例 B：纯轨道相机（无 active_camera）+ fov=70 + 无天空盒。"""
    return {'version': _scene_contract.CURRENT_VERSION,
            'camera': {'target': [1.0, 2.0, 3.0], 'distance': 12.0,
                       'yaw': 0.9, 'pitch': -0.4, 'fov': 70.0},
            'cameras': [], 'active_camera': None,
            'objects': [obj_dict('box', scripts=['s1_play_probe'])],
            'lights': [], 'materials': [], 'gravity': -9.8,
            'skybox': None, 'ui': ui_section()}


def scene_c():
    """用例 C：active 相机挂在父物体下 + 父每逻辑帧匀速移动（运行期挂父传播）。"""
    return {'version': _scene_contract.CURRENT_VERSION,
            'camera': {'target': [0.0, 0.0, 0.0], 'distance': 10.0,
                       'yaw': 0.0, 'pitch': -0.35, 'fov': 60.0},
            'cameras': [cam_dict('c1', (2.0, 3.0, -4.0), 35.0, 30.0, 15.0, parent='par')],
            'active_camera': 'c1',
            'objects': [obj_dict('par', scripts=['s1_play_probe']),
                        obj_dict('box')],
            'lights': [], 'materials': [], 'gravity': -9.8,
            'skybox': None, 'ui': ui_section()}


# ---- 期望值（手算；不取自任何一端） ----

def hand_basis(yaw, pitch, roll=0.0):
    """与 mat4_view_yaw_pitch 同一套文档化约定（弧度；roll 负绕向）。"""
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


def hand_orbit_pose(cam_block):
    target = cam_block['target']
    yaw = float(cam_block['yaw'])
    pitch = float(cam_block['pitch'])
    distance = float(cam_block['distance'])
    _ex, ey, ez = hand_basis(yaw, pitch, 0.0)
    eye = (target[0] - distance * ez[0], target[1] - distance * ez[1],
           target[2] - distance * ez[2])
    return (eye, ez, ey, yaw, pitch, 0.0,
            math.radians(float(cam_block.get('fov', 60.0))), True)


def hand_active_pose(camd, parent_x=0.0):
    """active 相机手算位姿 + (yaw,pitch,roll,fov,orbit)。parent_x = 父物体当前 x（无父=0）。
    与生产同一条换算链（度→wrap_deg→弧度→基；挂父再 view_basis_to_angles→
    mat4_view_yaw_pitch），同式同序，故可逐值相等。"""
    yaw = math.radians(wrap_deg(camd['yaw'], 0.0, 360.0))
    pitch = math.radians(wrap_deg(camd['pitch'], -180.0, 180.0))
    roll = math.radians(wrap_deg(camd['roll'], -180.0, 180.0))
    ex, ey, ez = hand_basis(yaw, pitch, roll)
    if camd.get('parent_id') is None:
        eye = (float(camd['position'][0]), float(camd['position'][1]),
               float(camd['position'][2]))
        return eye, ez, ey, yaw, pitch, roll, math.radians(float(camd['fov'])), False
    R3 = np.asarray(mat4_rotation(np, 0.0, 0.0, 0.0))[:3, :3]   # 父旋转 = 0（场景 C 固定）
    ex_w = tuple(float(v) for v in np.array(ex) @ R3)
    ey_w = tuple(float(v) for v in np.array(ey) @ R3)
    ez_w = tuple(float(v) for v in np.array(ez) @ R3)
    Wp = (mat4_scale(np, 1.0, 1.0, 1.0) @ mat4_rotation(np, 0.0, 0.0, 0.0)
          @ mat4_translation(np, parent_x, 0.0, 0.0))
    p = np.array([camd['position'][0], camd['position'][1], camd['position'][2], 1.0]) @ Wp
    eye = (float(p[0]), float(p[1]), float(p[2]))
    y2, p2, r2 = view_basis_to_angles(ex_w, ey_w, ez_w)
    V = mat4_view_yaw_pitch(np, eye, y2, p2, r2)
    return (eye, tuple(float(v) for v in V[0:3, 2]), tuple(float(v) for v in V[0:3, 1]),
            float(y2), float(p2), float(r2), math.radians(float(camd['fov'])), False)


def hand_box_x(k):
    """脚本宿主物体在第 k 个渲染帧后的 x（手算累加：k 次逻辑帧，每次 += SPEED*fixed_dt）。"""
    x = 0.0
    for _ in range(k):
        x = x + SPEED * FRAME_DT
    return x


def hand_box_world(k):
    """静止单体（无父、单位缩放/零旋转）世界矩阵 = matlib 纯函数手算 S@R@T。"""
    return (mat4_scale(np, 1.0, 1.0, 1.0) @ mat4_rotation(np, 0.0, 0.0, 0.0)
            @ mat4_translation(np, hand_box_x(k), 0.0, 0.0))


# ---- 测量（生产字段 + 生产纯函数；校验重建 V@P == 生产 VP） ----

def _proj_gl(app):
    if getattr(app, 'ortho', False):
        h = float(getattr(app, 'ortho_size', 12.0))
        asp = app.width / max(1, app.height)
        return mat4_ortho(np, -h * asp * 0.5, h * asp * 0.5, -h * 0.5, h * 0.5,
                          app.near, app.far)
    return mat4_perspective(np, app._fov, app.width / app.height, app.near, app.far)


def measure_gl(app):
    eye = (float(app.camera.x), float(app.camera.y), float(app.camera.z))
    V = mat4_view_yaw_pitch(np, eye, app.camera_yaw, app.camera_pitch, app.camera_roll)
    P = _proj_gl(app)
    prod = np.asarray(app._vp, dtype=np.float64)
    sky = app.effective_skybox()
    return {'eye': eye,
            'fwd': tuple(float(v) for v in V[0:3, 2]),
            'up': tuple(float(v) for v in V[0:3, 1]),
            'yaw': float(app.camera_yaw), 'pitch': float(app.camera_pitch),
            'roll': float(app.camera_roll),
            'fov': float(app._fov), 'orbit': bool(app.orbit_mode),
            'vp': prod,
            'vp_ok': bool(np.array_equal(np.asarray(V) @ np.asarray(P), prod)),
            'fw_sha': hashlib.sha256(np.asarray(app._frame_world, dtype=np.float64).tobytes()).hexdigest(),
            'rw_sha': hashlib.sha256(np.asarray(app._render_world, dtype=np.float64).tobytes()).hexdigest(),
            # S5: 渲染矩阵的渲染管线原生精度形态（f32 = GPU 上传精度，非容差口径）
            'rw32': np.asarray(app._render_world, dtype=np.float32).tobytes(),
            'steps': int(app._clock.steps), 'alpha': float(app._clock.alpha),
            # S5: GL 端 _logic_steps_total（engine 记账）；VK 编辑器面无该字段，
            # 回落到同一份 CoreClock 的 steps_total（probe3 实测 GL 两面二值恒等）。
            'steps_total': int(getattr(app, '_logic_steps_total',
                                       getattr(getattr(app, '_clock', None),
                                               'steps_total', -1))),
            'sky': None if sky is None else (getattr(sky, 'name', None),
                                             list(getattr(sky, '_solid_color', ()) or ())),
            }


def _vk_fw_sha(drv):
    """VK 播放器面 _frame_world 的 sha（getattr 口径）：生产修复被回退（修前）时
    VK 播放器形状连该字段都没有 —— 测量降级为 None（断言按「不等」红），不让测量
    本身把门炸成 AttributeError（修前红必须以 FAIL 行留痕，见门头 ⑧ 段）。"""
    _fw = getattr(drv, '_frame_world', None)
    if _fw is None:
        return None
    return hashlib.sha256(np.asarray(_fw, dtype=np.float64).tobytes()).hexdigest()

def measure_vk_player(drv, prod_vp):
    """VK 播放器面测量 —— 字段名与 measure_gl 同名同义（采集器同源，不是各写一份）。

    · fw = drv._frame_world（S5 D4 后由共享 EngineCore._refresh_play_frame_world
      每逻辑帧维护，float64 —— 与 GL 面同一份生产者）；
    · rw32 = vk_renderer.world_matrices(models, interp)（VK 渲染管线每帧自算的 f32
      渲染矩阵 —— vk_renderer.draw_frame 消费的正是这一份）；
    · VP = render_pose 生产返回值；「生产字段重建 V@P == 本帧生产 VP」保真断言与
      GL measure_gl 同口径。
    """
    eye = (float(drv.camera.x), float(drv.camera.y), float(drv.camera.z))
    V = mat4_view_yaw_pitch(np, eye, drv.camera_yaw, drv.camera_pitch, drv.camera_roll)
    if getattr(drv, 'ortho', False):
        h = float(getattr(drv, 'ortho_size', 12.0))
        asp = W / max(1, H)
        P = mat4_ortho(np, -h * asp * 0.5, h * asp * 0.5, -h * 0.5, h * 0.5,
                       drv.near, drv.far)
    else:
        P = mat4_perspective(np, drv.fov, W / H, drv.near, drv.far)
    prod = np.asarray(prod_vp, dtype=np.float64)
    sky = drv.effective_skybox()
    import render.vk.renderer as _vr          # 惰性：GL 读者不拉 wgpu 之外的 VK 渲染器
    rw32 = _vr.world_matrices(drv.models, getattr(drv, '_interp', None)).tobytes()
    return {'eye': eye,
            'fwd': tuple(float(v) for v in V[0:3, 2]),
            'up': tuple(float(v) for v in V[0:3, 1]),
            'yaw': float(drv.camera_yaw), 'pitch': float(drv.camera_pitch),
            'roll': float(drv.camera_roll),
            'fov': float(drv.fov), 'orbit': bool(getattr(drv, 'orbit_mode', None)),
            'vp': prod,
            'vp_ok': bool(np.array_equal(np.asarray(V) @ np.asarray(P), prod)),
            'fw_sha': _vk_fw_sha(drv),
            'rw32': rw32,
            'steps': int(drv._clock.steps), 'alpha': float(drv._clock.alpha),
            'steps_total': int(drv._clock.steps_total),
            'sky': None if sky is None else (getattr(sky, 'name', None),
                                             list(getattr(sky, '_solid_color', ()) or ())),
            }


def ui_tree_of(app):
    def el(e):
        return (e.name, tuple(float(v) for v in e.rect), bool(e.visible),
                tuple(el(ch) for ch in e.children))
    out = []
    for c in app.ui.canvases:
        out.append((c.canvas_type, int(c.z_order), int(c.width), int(c.height), el(c.root)))
    return out


def hand_ui_tree():
    def el(d):
        return (d['name'], tuple(float(v) for v in d['rect']), bool(d['visible']),
                tuple(el(ch) for ch in d.get('children') or ()))
    return [(c['canvas_type'], int(c['z_order']), int(c['width']), int(c['height']),
             el(c['elements'][0])) for c in ui_section()['canvases']]


# ---- 一对生产端（同一份场景）+ 生产帧驱动 + 逐帧快照 ----

class Pair:
    def __init__(self, scene_data, host_name='物体box'):
        self.host_name = host_name
        self.events = []
        REC.clear()
        UI_EVENTS.clear()
        self.gl = runtime.PlayerApp(None, W, H, ctx=_gl_ctx(),
                                    scene_data=json.loads(json.dumps(scene_data)))
        self.gl._external_fb = _gl_fbo(W, H)
        self.ed = editor_mod.EditorApp(W, H, ctx=_gl_ctx())
        self.ed._external_fb = _gl_fbo(W, H)
        self.ed.show_grid = False
        self.ed.selected_index = -1
        self.ed.selected_light_index = -1
        self.ed.selected_camera_index = -1
        # 编辑器走生产打开路径（写临时场景文件 -> _load_scene）
        sfile = os.path.join(tempfile.mkdtemp(prefix='loom_s1_scene_'), 's.json')
        with open(sfile, 'w', encoding='utf-8') as f:
            json.dump(scene_data, f)
        self.ed._load_scene(sfile)
        # 生产视图插桩：只记录「view.draw 被调」事件（与 draw_all 同一张事件表，
        # 事件序 = Canvas UI 是否经 view.draw 画的可判定判据）
        self._orig_vd = self.ed.view.draw

        def _vd(ctl, dt, _orig=self._orig_vd, _ed=self.ed):
            UI_EVENTS.append(('view_draw', id(_ed)))
            return _orig(ctl, dt)
        self.ed.view.draw = _vd
        # ---- S5: VK 两面（同一份场景用户内容；生产构造式） ----
        # VK 播放器面 = scene_driver.SceneDriver（生产 VK 播放器同一类），
        # 装配按 vk_player.run_vk 生产同款：is_playing=True（render/vk/player.py:346，
        # 「播放器一进来就是正在播放语义」）→ load_from_data → set_fps。
        self.v = _sd.SceneDriver()
        self.v.is_playing = True
        self.v.load_from_data(json.loads(json.dumps(scene_data)))
        # VK 编辑器面 = editor.VkEditorApp（S4 生产类）：wgpu device + 离屏纹理宿主
        # （VkFrameExecutor/叠加层 flush 协议）→ 生产打开路径 _load_scene →
        # toggle_play（与 GL 编辑器共享的同一份 _EditorCore.toggle_play）。
        self.k = editor_mod.VkEditorApp(W, H, view=_NullView(), device=_vk_device(),
                                        present_format=_VK_FMT)
        self.k._vk_ctx = _VkOffscreenCtx()
        self.k.show_grid = False
        self.k.selected_index = -1
        self.k.selected_light_index = -1
        self.k.selected_camera_index = -1
        self.k._load_scene(sfile)
        # 四面同一份生产时钟设置
        self.gl._clock.set_fps(logic_fps=LOGIC_FPS)
        self.ed.toggle_play()
        self.ed._clock.set_fps(logic_fps=LOGIC_FPS)
        self.v._clock.set_fps(logic_fps=LOGIC_FPS)
        self.k.toggle_play()
        self.k._clock.set_fps(logic_fps=LOGIC_FPS)
        self.gl_hooks_at_enter = list(REC.get(id(self.gl), []))
        self.ed_hooks_at_enter = list(REC.get(id(self.ed), []))
        self.v_hooks_at_enter = list(REC.get(id(self.v), []))
        self.k_hooks_at_enter = list(REC.get(id(self.k), []))
        REC.setdefault(id(self.gl), []).clear()
        REC.setdefault(id(self.ed), []).clear()
        REC.setdefault(id(self.v), []).clear()
        REC.setdefault(id(self.k), []).clear()

    @staticmethod
    def _model_world(app, name):
        idx = [i for i, m in enumerate(app.models) if m.name == name]
        # getattr 口径（修前 VK 播放器形状连 _frame_world 都没有 -> None，断言按不等红）：
        fw = getattr(app, '_frame_world', None)
        return None if fw is None else np.asarray(fw, dtype=np.float64)[idx[0]].copy()

    def frame(self, k):
        """第 k 个渲染帧（1 基）：喂 dt 前清墙钟锚（测试语义，见 _clock_advance docstring）。

        S5: 四面同一帧驱动 —— GL 两面走 render()；VK 播放器面走生产 vk_player.draw
        帧序（advance_logic → interp.alpha 透传 → render_pose；状态面不含 draw_frame，
        像素面归 S5 像素门）；VK 编辑器面与 GL 编辑器**同一条** editor.render 生产帧
        （VkFrameExecutor 消费同一份 FramePlan）。"""
        self.gl._logic_wall_last = None
        self.ed._logic_wall_last = None
        ui0 = len(UI_EVENTS)
        h0 = (len(REC.get(id(self.gl), [])), len(REC.get(id(self.ed), [])))
        self.gl.render(FRAME_DT)
        self.ed.render(FRAME_DT)
        ev_ui = UI_EVENTS[ui0:]
        gh = REC[id(self.gl)][h0[0]:]
        eh = REC[id(self.ed)][h0[1]:]
        # ---- S5: VK 两面 ----
        self.v._logic_wall_last = None
        h0v = len(REC.get(id(self.v), []))
        self.v.advance_logic(FRAME_DT)
        if getattr(self.v, '_interp', None) is not None and self.v._clock is not None:
            self.v._interp.alpha = self.v._clock.alpha
        v_vp, _v_cam_pos = self.v.render_pose(W / H)
        vh = REC[id(self.v)][h0v:]
        self.k._logic_wall_last = None
        h0k = len(REC.get(id(self.k), []))
        self.k.render(FRAME_DT)
        kh = REC[id(self.k)][h0k:]
        return {'g': measure_gl(self.gl), 'e': measure_gl(self.ed),
                'v': measure_vk_player(self.v, v_vp), 'k': measure_gl(self.k),
                'g_hooks': list(gh), 'e_hooks': list(eh),
                'v_hooks': list(vh), 'k_hooks': list(kh),
                'g_ui': [x[0] for x in ev_ui if x[1] == id(self.gl)],
                'e_ui': [x[0] for x in ev_ui if x[1] == id(self.ed)],
                'g_tree': ui_tree_of(self.gl), 'e_tree': ui_tree_of(self.ed),
                'v_tree': ui_tree_of(self.v), 'k_tree': ui_tree_of(self.k),
                'g_host': self._model_world(self.gl, self.host_name),
                'e_host': self._model_world(self.ed, self.host_name),
                'v_host': self._model_world(self.v, self.host_name),
                'k_host': self._model_world(self.k, self.host_name),
                'g_box': self._model_world(self.gl, '物体box'),
                'e_box': self._model_world(self.ed, '物体box'),
                'v_box': self._model_world(self.v, '物体box'),
                'k_box': self._model_world(self.k, '物体box')}


print()
print("=== 〇'. 夹具保真：两端都是生产类 + 生产构造式 ===")
# S5: 先建 wgpu 设备再建任何 GL 上下文 —— 本机驱动实测（GTX 1050 Ti）：
# wgpu Vulkan 设备创建**之后**，既有 moderngl standalone 上下文「下一次新建
# program」会 cannot create program（tests/_tmp/s5_probe9_glctx.py / _probe10 /
# _probe11 / _probe12：设备先行 = 3/3 稳定；旧上下文续用 = 偶发失败）。
# 设备先行是夹具顺序口径，不是被测行为。
_vk_device()
check('S5 夹具：Vulkan 设备先于 GL 上下文建立（驱动干扰规避，见上注）',
      _VK['device'] is not None, type(_VK['device']).__name__)
_p0 = Pair(scene_a())
check('GL 播放器端是 runtime.PlayerApp（打包 GL 生产入口）',
      type(_p0.gl) is runtime.PlayerApp, type(_p0.gl).__name__)
check('GL 编辑器端是 editor.EditorApp（生产类 + 默认生产视图）',
      type(_p0.ed) is editor_mod.EditorApp, type(_p0.ed).__name__)
check('夹具保真：两端时钟 fixed_dt == 1/60（生产入口 set_fps）',
      (_p0.gl._clock.fixed_dt, _p0.ed._clock.fixed_dt) == (FRAME_DT, FRAME_DT),
      (_p0.gl._clock.fixed_dt, _p0.ed._clock.fixed_dt))
check('夹具前提：两端场景装配出同名同序物体（同一份用户内容）',
      [m.name for m in _p0.gl.models] == [m.name for m in _p0.ed.models],
      ([m.name for m in _p0.gl.models], [m.name for m in _p0.ed.models]))
check('夹具前提：进播放即无钩子泄漏（toggle_play 只建快照不实例化脚本）',
      _p0.gl_hooks_at_enter == [] and _p0.ed_hooks_at_enter == [],
      (_p0.gl_hooks_at_enter, _p0.ed_hooks_at_enter))

check('S5 夹具保真：VK 播放器端是 scene_driver.SceneDriver（生产 VK 播放器同一类）',
      type(_p0.v) is _sd.SceneDriver, type(_p0.v).__name__)
check('S5 夹具保真：VK 编辑器端是 editor.VkEditorApp（S4 生产类）',
      type(_p0.k) is editor_mod.VkEditorApp, type(_p0.k).__name__)
check('S5 夹具保真：VK 播放器按生产装配 is_playing=True（vk_player.run_vk 同款）',
      _p0.v.is_playing is True, _p0.v.is_playing)
check('S5 夹具保真：VK 两面时钟 fixed_dt == 1/60（生产入口 set_fps）',
      (_p0.v._clock.fixed_dt, _p0.k._clock.fixed_dt) == (FRAME_DT, FRAME_DT),
      (_p0.v._clock.fixed_dt, _p0.k._clock.fixed_dt))
check('S5 夹具前提：四面场景装配出同名同序物体（同一份用户内容）',
      [m.name for m in _p0.gl.models] == [m.name for m in _p0.ed.models]
      == [m.name for m in _p0.v.models] == [m.name for m in _p0.k.models],
      ([m.name for m in _p0.gl.models], [m.name for m in _p0.v.models],
       [m.name for m in _p0.k.models]))
check('S5 夹具前提：进播放即无钩子泄漏（VK 两面）',
      _p0.v_hooks_at_enter == [] and _p0.k_hooks_at_enter == [],
      (_p0.v_hooks_at_enter, _p0.k_hooks_at_enter))


def pose_assert(tag, m, exp):
    """一条测量 vs 手算期望（8 元组逐项）。"""
    got = (m['eye'], m['fwd'], m['up'], m['yaw'], m['pitch'], m['roll'], m['fov'], m['orbit'])
    check(tag, got == exp,
          '\n      got=%r\n      exp=%r' % (got, exp))


def run_case(tag, scene_data, cam_case, host_name='物体box'):
    """cam_case: 'A' 根相机 / 'B' 轨道 / 'C' 挂父相机。返回逐帧快照。"""
    print()
    print('=== %s ===' % tag)
    pair = Pair(scene_data, host_name=host_name)
    camd = (scene_data['cameras'][0] if scene_data['cameras'] else None)
    snaps = []
    for k in range(1, N + 1):
        snaps.append(pair.frame(k))
    # ---- ① 相机 8 元组 + 生产 VP ----
    for k, s in enumerate(snaps, 1):
        if cam_case == 'B':
            exp = hand_orbit_pose(scene_data['camera'])
        else:
            px = 0.0 if cam_case == 'A' else hand_box_x(k - 1)
            exp = hand_active_pose(camd, parent_x=px)
        pose_assert('%s 帧%d ① 播放器相机 8 元组 == 手算期望' % (tag, k), s['g'], exp)
        pose_assert('%s 帧%d ① 编辑器相机 8 元组 == 手算期望' % (tag, k), s['e'], exp)
        check('%s 帧%d ① 两端相机 8 元组逐项相等' % (tag, k),
              (s['g']['eye'], s['g']['fwd'], s['g']['up'], s['g']['yaw'], s['g']['pitch'],
               s['g']['roll'], s['g']['fov'], s['g']['orbit'])
              == (s['e']['eye'], s['e']['fwd'], s['e']['up'], s['e']['yaw'], s['e']['pitch'],
                  s['e']['roll'], s['e']['fov'], s['e']['orbit']),
              (s['g'], s['e']) if k == 1 else '')
        check('%s 帧%d ① 两端生产 VP 逐元素相等' % (tag, k),
              np.array_equal(s['g']['vp'], s['e']['vp']),
              'max|Δ|=%.3e' % float(np.max(np.abs(s['g']['vp'] - s['e']['vp']))))
        check('%s 帧%d ① 夹具保真（生产字段重建 V@P == 本帧生产 VP）' % (tag, k),
              s['g']['vp_ok'] and s['e']['vp_ok'], (s['g']['vp_ok'], s['e']['vp_ok']))
    # ---- ② 世界矩阵 sha + 脚本宿主/静态单体手算 ----
    for k, s in enumerate(snaps, 1):
        check('%s 帧%d ② 两端 _frame_world sha256 相等' % (tag, k),
              s['g']['fw_sha'] == s['e']['fw_sha'],
              (s['g']['fw_sha'][:12], s['e']['fw_sha'][:12]))
        check('%s 帧%d ② 两端 _render_world sha256 相等' % (tag, k),
              s['g']['rw_sha'] == s['e']['rw_sha'],
              (s['g']['rw_sha'][:12], s['e']['rw_sha'][:12]))
        check('%s 帧%d ② 脚本宿主世界矩阵 == matlib 纯函数手算（播放器）' % (tag, k),
              np.array_equal(s['g_host'], hand_box_world(k)),
              'tx=%r 期望=%r' % (float(s['g_host'][3, 0]), hand_box_x(k)))
        check('%s 帧%d ② 脚本宿主世界矩阵 == matlib 纯函数手算（编辑器）' % (tag, k),
              np.array_equal(s['e_host'], hand_box_world(k)),
              'tx=%r 期望=%r' % (float(s['e_host'][3, 0]), hand_box_x(k)))
        if cam_case == 'C':
            check('%s 帧%d ② 静态 box（无脚本）tx==0（两端）' % (tag, k),
                  float(s['g_box'][3, 0]) == 0.0 and float(s['e_box'][3, 0]) == 0.0,
                  (float(s['g_box'][3, 0]), float(s['e_box'][3, 0])))
    # ---- ③ 钩子调用序 ----
    for k, s in enumerate(snaps, 1):
        exp_hooks = ['start', 'update', 'late'] if k == 1 else ['update', 'late']
        check('%s 帧%d ③ 播放器钩子序 == 手算期望 %r' % (tag, k, exp_hooks),
              s['g_hooks'] == exp_hooks, s['g_hooks'])
        check('%s 帧%d ③ 编辑器钩子序 == 手算期望 %r' % (tag, k, exp_hooks),
              s['e_hooks'] == exp_hooks, s['e_hooks'])
        check('%s 帧%d ③ 两端钩子序逐项相等' % (tag, k), s['g_hooks'] == s['e_hooks'],
              (s['g_hooks'], s['e_hooks']))
    # 退出播放的 on_disable 断言在下方 ⑦ 组（Q-B7-48-2, 2026-11-20 修后收口；建门时
    # 该路径是已知缺陷 —— 反模式：不许把缺陷写成断言，故 S1 建门时未锁）
    # ---- ④ 时钟 ----
    for k, s in enumerate(snaps, 1):
        check('%s 帧%d ④ 时钟 steps/alpha/累计 两端逐项相等' % (tag, k),
              (s['g']['steps'], s['g']['alpha'], s['g']['steps_total'])
              == (s['e']['steps'], s['e']['alpha'], s['e']['steps_total']),
              (s['g']['steps'], s['g']['alpha'], s['g']['steps_total'],
               s['e']['steps'], s['e']['alpha'], s['e']['steps_total']))
        check('%s 帧%d ④ 时钟 == 手算期望（每帧恰 1 逻辑帧, alpha=0, 累计=%d）' % (tag, k, k),
              (s['g']['steps'], s['g']['alpha'], s['g']['steps_total']) == (1, 0.0, k),
              (s['g']['steps'], s['g']['alpha'], s['g']['steps_total']))
    # ---- ⑤ UI 树 + 绘制路径 ----
    exp_tree = hand_ui_tree()
    check('%s ⑤ 播放器 UI Canvas 树 == 场景 UI 段手写期望' % tag,
          snaps[0]['g_tree'] == exp_tree, snaps[0]['g_tree'])
    check('%s ⑤ 编辑器 UI Canvas 树 == 场景 UI 段手写期望' % tag,
          snaps[0]['e_tree'] == exp_tree, snaps[0]['e_tree'])
    for k, s in enumerate(snaps, 1):
        check('%s 帧%d ⑤ 两端 UI Canvas 树逐项相等' % (tag, k),
              s['g_tree'] == s['e_tree'], '')
        check('%s 帧%d ⑤ 播放器 UI 绘制路径 == [\'draw_all\']（FramePlan screen_ui pass）' % (tag, k),
              s['g_ui'] == ['draw_all'], s['g_ui'])
        check('%s 帧%d ⑤ 编辑器 UI 绘制路径 == [\'draw_all\',\'view_draw\']'
              '（同一条 screen_ui pass 在前, view.draw 叠加层在后, 不再自画 Canvas UI）' % (tag, k),
              s['e_ui'] == ['draw_all', 'view_draw'], s['e_ui'])
    # ---- S5（Q-B7-47-1 阶段 5）：VK 面断言（采集器与 GL 面同一个：measure_gl /
    #      measure_vk_player / ui_tree_of / REC / _model_world —— 不是各写一份） ----
    for k, s in enumerate(snaps, 1):
        if cam_case == 'B':
            exp = hand_orbit_pose(scene_data['camera'])
        else:
            px = 0.0 if cam_case == 'A' else hand_box_x(k - 1)
            exp = hand_active_pose(camd, parent_x=px)
        # ---- ① 相机 8 元组 + 生产 VP（VK 面） ----
        pose_assert('%s 帧%d ① VK播放器相机 8 元组 == 手算期望' % (tag, k), s['v'], exp)
        pose_assert('%s 帧%d ① VK编辑器相机 8 元组 == 手算期望' % (tag, k), s['k'], exp)
        check('%s 帧%d ① 四面相机 8 元组逐项相等（GL播放器/GL编辑器/VK播放器/VK编辑器）' % (tag, k),
              (s['g']['eye'], s['g']['fwd'], s['g']['up'], s['g']['yaw'], s['g']['pitch'],
               s['g']['roll'], s['g']['fov'], s['g']['orbit'])
              == (s['e']['eye'], s['e']['fwd'], s['e']['up'], s['e']['yaw'], s['e']['pitch'],
                  s['e']['roll'], s['e']['fov'], s['e']['orbit'])
              == (s['v']['eye'], s['v']['fwd'], s['v']['up'], s['v']['yaw'], s['v']['pitch'],
                  s['v']['roll'], s['v']['fov'], s['v']['orbit'])
              == (s['k']['eye'], s['k']['fwd'], s['k']['up'], s['k']['yaw'], s['k']['pitch'],
                  s['k']['roll'], s['k']['fov'], s['k']['orbit']), '')
        check('%s 帧%d ① 四面生产 VP 逐元素相等' % (tag, k),
              np.array_equal(s['g']['vp'], s['e']['vp'])
              and np.array_equal(s['g']['vp'], s['v']['vp'])
              and np.array_equal(s['g']['vp'], s['k']['vp']),
              'max|Δ|(g,v)=%.3e' % float(np.max(np.abs(s['g']['vp'] - s['v']['vp']))))
        check('%s 帧%d ① 夹具保真（VK 面：生产字段重建 V@P == 本帧生产 VP）' % (tag, k),
              s['v']['vp_ok'] and s['k']['vp_ok'], (s['v']['vp_ok'], s['k']['vp_ok']))
        # ---- ② 世界矩阵（VK 面） ----
        check('%s 帧%d ② 四面 _frame_world sha256 相等（VK 面与 GL 同一份共享 compute 维护）'
              % (tag, k),
              s['g']['fw_sha'] is not None and s['k']['fw_sha'] is not None
              and s['g']['fw_sha'] == s['e']['fw_sha'] == s['v']['fw_sha'] == s['k']['fw_sha'],
              (('none' if s['v']['fw_sha'] is None else s['v']['fw_sha'][:12]),
               ('none' if s['k']['fw_sha'] is None else s['k']['fw_sha'][:12])))
        check('%s 帧%d ② 渲染矩阵逐位相等（GL _render_world f32 == VK 渲染管线原生 f32；'
              'f32 = 渲染管线上传精度, 非容差口径）' % (tag, k),
              s['g']['rw32'] == s['v']['rw32'] and s['e']['rw32'] == s['k']['rw32']
              and s['g']['rw32'] == s['k']['rw32'], '')
        check('%s 帧%d ② 脚本宿主世界矩阵 == matlib 纯函数手算（VK播放器）' % (tag, k),
              s['v_host'] is not None and np.array_equal(s['v_host'], hand_box_world(k)),
              None if s['v_host'] is None else
              'tx=%r 期望=%r' % (float(s['v_host'][3, 0]), hand_box_x(k)))
        check('%s 帧%d ② 脚本宿主世界矩阵 == matlib 纯函数手算（VK编辑器）' % (tag, k),
              s['k_host'] is not None and np.array_equal(s['k_host'], hand_box_world(k)),
              None if s['k_host'] is None else
              'tx=%r 期望=%r' % (float(s['k_host'][3, 0]), hand_box_x(k)))
        if cam_case == 'C':
            check('%s 帧%d ② 静态 box（无脚本）tx==0（四面）' % (tag, k),
                  s['g_box'] is not None and s['e_box'] is not None
                  and s['v_box'] is not None and s['k_box'] is not None
                  and float(s['g_box'][3, 0]) == 0.0 and float(s['e_box'][3, 0]) == 0.0
                  and float(s['v_box'][3, 0]) == 0.0 and float(s['k_box'][3, 0]) == 0.0,
                  (None if s['v_box'] is None else float(s['v_box'][3, 0]),
                   None if s['k_box'] is None else float(s['k_box'][3, 0])))
        # ---- ③ 钩子调用序（VK 面） ----
        exp_hooks = ['start', 'update', 'late'] if k == 1 else ['update', 'late']
        check('%s 帧%d ③ VK播放器钩子序 == 手算期望 %r' % (tag, k, exp_hooks),
              s['v_hooks'] == exp_hooks, s['v_hooks'])
        check('%s 帧%d ③ VK编辑器钩子序 == 手算期望 %r' % (tag, k, exp_hooks),
              s['k_hooks'] == exp_hooks, s['k_hooks'])
        check('%s 帧%d ③ 四面钩子序逐项相等（修前 VK 编辑器每帧双发 late）' % (tag, k),
              s['g_hooks'] == s['e_hooks'] == s['v_hooks'] == s['k_hooks'],
              (s['g_hooks'], s['v_hooks'], s['k_hooks']))
        # ---- ④ 时钟（VK 面） ----
        check('%s 帧%d ④ VK 时钟 == 手算期望（每帧恰 1 逻辑帧, alpha=0, 累计=%d）' % (tag, k, k),
              (s['v']['steps'], s['v']['alpha'], s['v']['steps_total']) == (1, 0.0, k)
              and (s['k']['steps'], s['k']['alpha'], s['k']['steps_total']) == (1, 0.0, k),
              (s['v']['steps'], s['v']['alpha'], s['v']['steps_total'],
               s['k']['steps'], s['k']['alpha'], s['k']['steps_total']))
        check('%s 帧%d ④ 四面时钟 steps/alpha/累计 逐项相等' % (tag, k),
              (s['g']['steps'], s['g']['alpha'], s['g']['steps_total'])
              == (s['e']['steps'], s['e']['alpha'], s['e']['steps_total'])
              == (s['v']['steps'], s['v']['alpha'], s['v']['steps_total'])
              == (s['k']['steps'], s['k']['alpha'], s['k']['steps_total']),
              (s['g']['steps_total'], s['v']['steps_total'], s['k']['steps_total']))
        # ---- ⑤ UI Canvas 树（VK 面） ----
        check('%s 帧%d ⑤ VK两面 UI Canvas 树 == 场景 UI 段手写期望' % (tag, k),
              s['v_tree'] == exp_tree and s['k_tree'] == exp_tree, '')
        check('%s 帧%d ⑤ 四面 UI Canvas 树逐项相等' % (tag, k),
              s['g_tree'] == s['e_tree'] == s['v_tree'] == s['k_tree'], '')
    return pair, snaps


pairA, snapsA = run_case('用例 A：active 相机 (roll15/pitch30) + 脚本 + UI + 天空盒',
                         scene_a(), 'A', host_name='物体box')
pairB, snapsB = run_case('用例 B：纯轨道相机 (fov70) + 无天空盒',
                         scene_b(), 'B', host_name='物体box')
pairC, snapsC = run_case('用例 C：挂父相机 + 父每帧移动',
                         scene_c(), 'C', host_name='物体par')

# ---- ⑥ 生效天空盒 ----
check('⑥ 用例 A 生效天空盒 = 场景级 solid_color [255,0,0,255]（两端逐项相等 + 手写期望）',
      snapsA[0]['g']['sky'] == snapsA[0]['e']['sky']
      and snapsA[0]['g']['sky'] is not None
      and snapsA[0]['g']['sky'][1] == [255, 0, 0, 255],
      (snapsA[0]['g']['sky'], snapsA[0]['e']['sky']))
check('⑥ 用例 B 生效天空盒 = 引擎默认蓝天 [58,155,213,255]（场景无 skybox 的生产回退；两端逐项相等）',
      snapsB[0]['g']['sky'] == snapsB[0]['e']['sky']
      and snapsB[0]['g']['sky'] is not None
      and snapsB[0]['g']['sky'][1] == [58, 155, 213, 255],
      (snapsB[0]['g']['sky'], snapsB[0]['e']['sky']))
check('⑥ 用例 C 生效天空盒 = 引擎默认蓝天（相机级未覆盖；两端逐项相等）',
      snapsC[0]['g']['sky'] == snapsC[0]['e']['sky']
      and snapsC[0]['g']['sky'][1] == [58, 155, 213, 255],
      (snapsC[0]['g']['sky'], snapsC[0]['e']['sky']))

check('⑥ S5: 用例 A 生效天空盒 VK 两面 == GL 两面（修前 VK 编辑器恒 None）',
      snapsA[0]['g']['sky'] == snapsA[0]['v']['sky'] == snapsA[0]['k']['sky']
      and snapsA[0]['v']['sky'] is not None
      and snapsA[0]['v']['sky'][1] == [255, 0, 0, 255],
      (snapsA[0]['g']['sky'], snapsA[0]['v']['sky'], snapsA[0]['k']['sky']))
check('⑥ S5: 用例 B 生效天空盒 VK 两面 == GL 两面（引擎默认蓝天）',
      snapsB[0]['g']['sky'] == snapsB[0]['v']['sky'] == snapsB[0]['k']['sky']
      and snapsB[0]['v']['sky'] is not None
      and snapsB[0]['v']['sky'][1] == [58, 155, 213, 255],
      (snapsB[0]['g']['sky'], snapsB[0]['v']['sky'], snapsB[0]['k']['sky']))
check('⑥ S5: 用例 C 生效天空盒 VK 两面 == GL 两面（引擎默认蓝天）',
      snapsC[0]['g']['sky'] == snapsC[0]['v']['sky'] == snapsC[0]['k']['sky']
      and snapsC[0]['v']['sky'][1] == [58, 155, 213, 255],
      (snapsC[0]['g']['sky'], snapsC[0]['v']['sky'], snapsC[0]['k']['sky']))


# ---- ⑦ 退出播放 on_disable（Q-B7-48-2, 2026-11-20 修后收口） ----
# 口径：退出播放 = 脚本实例禁用，编辑器每个脚本组件恰追加 1 次 on_disable；
# 播放器（GL PlayerApp）无「退出播放」边界（会话内恒播放，释放契约在换场景
# load_scene→clear_scene→remove_model→on_destroy），故 ⑦ 只锁编辑器侧 + 结构锁。
print()
print("=== ⑦. 退出播放 on_disable（Q-B7-48-2）：退出追加恰一次/脚本组件 + 全仓唯一派发点结构锁 ===")

with open(os.path.join(ROOT, 'editor', 'core.py'), 'r', encoding='utf-8') as _f7:
    _ed_src7 = _f7.read()
_no_dis7 = {fn: open(os.path.join(ROOT, fn), 'r', encoding='utf-8').read().count('inst.on_disable(')
            for fn in ('runtime.py', 'render/gl/engine.py', 'core/engine_core.py', 'render/vk/driver.py',
                       'render/gl/model_gpu.py', 'render/vk/player.py', 'game_player.py',
                       'loom_player_window.py')}
check('⑦ 结构：inst.on_disable( 生产派发点全仓恰 1 处（editor.py 第 1.5 步）+ 播放器入口 0 处',
      _ed_src7.count('inst.on_disable(') == 1 and set(_no_dis7.values()) == {0},
      (_ed_src7.count('inst.on_disable('), _no_dis7))
_i_dis7 = _ed_src7.index('inst.on_disable(')
_i_snap7 = _ed_src7.index('apply_snapshot(m, self._play_snap[id(m)])')
check('⑦ 结构：唯一派发点在源码序上位于 apply_snapshot 重建组件之前（toggle_play 退出分支内）',
      0 < _i_dis7 < _i_snap7, (_i_dis7, _i_snap7))

for _t7, _pair7 in (('用例 A', pairA), ('用例 B', pairB), ('用例 C', pairC)):
    _rec7 = REC.setdefault(id(_pair7.ed), [])
    _n7 = len(_rec7)
    _pair7.ed.toggle_play()          # 生产退出入口 toggle_play
    _tail7 = _rec7[_n7:]
    check('%s ⑦ 退出播放追加恰 1 次 on_disable（每脚本组件一次; 本场景恒 1 组件）+ 回到编辑态' % _t7,
          _tail7 == ['disable'] and _pair7.ed.is_playing is False, (_tail7, _pair7.ed.is_playing))
    check('%s ⑦ 退出后编辑态脚本组件 _script 全为 None（重建组件不带旧实例）' % _t7,
          all(sc._script is None for m in _pair7.ed.models for sc in m.scripts),
          [(m.name, [sc.script_id for sc in m.scripts]) for m in _pair7.ed.models])

for _t7, _pair7 in (('用例 A', pairA), ('用例 B', pairB), ('用例 C', pairC)):
    _rec7 = REC.setdefault(id(_pair7.k), [])
    _n7 = len(_rec7)
    _pair7.k.toggle_play()           # 同一份 _EditorCore.toggle_play 退出分支（VK 面）
    _tail7 = _rec7[_n7:]
    check('%s ⑦ VK编辑器退出播放追加恰 1 次 on_disable + 回到编辑态' % _t7,
          _tail7 == ['disable'] and _pair7.k.is_playing is False,
          (_tail7, _pair7.k.is_playing))
    check('%s ⑦ VK编辑器退出后编辑态脚本组件 _script 全为 None' % _t7,
          all(sc._script is None for m in _pair7.k.models for sc in m.scripts),
          [(m.name, [sc.script_id for sc in m.scripts]) for m in _pair7.k.models])

print()
print('=== S5：VK 对拍面已补齐（S4 落地 VkEditorApp 后，S1 的两条 SKIP 换成真断言） ===')
print('S5   四面对拍 = GL编辑器播放 / GL播放器 / VK编辑器播放 / VK播放器（采集器同一个）')

check('已知差异登记表为空（不许登记任何容差）', not KNOWN_DIFFS, KNOWN_DIFFS)

print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
