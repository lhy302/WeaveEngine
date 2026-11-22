# -*- coding: utf-8 -*-
"""test_pause_parity.py — P6 面「暂停 / 单步的窗口级观感」两端对拍门（2026-11-19）。

上位判据（人类原话，docs/guides/开发要求_后端API一致_JVM模型.md §1.3）：
  「两种后端没有用户可感知的差异……如同 JVM 虚拟机在任何 CPU 上都保证字节码解析效果
    一样，不管选择什么后端对用户脚本的表现一致。」

**P6 与 P1~P5 的区别**：前五面比的是「数值 / 状态」，本面比的是**玩家在窗口里看到的**。
所以本门的判据不是「字段相等」，而是「**同一串暂停/单步操作后，两端画出来的那一帧
逐像素相等**」，外加「画面推进量 == 逻辑推进量」这条把画面与逻辑钉在一起的桥。

本门验什么（六组；P2 已覆盖的「暂停期 mouse_rel 不结算不累积」「暂停期按解锁键」
**不重复**，见 docs §4.1 P2 行）：

  ① 暂停时画面冻结但渲染继续
     · 两端 F9 暂停后连跑 N=10 个渲染帧 → 逻辑状态**逐值不变**（物体位姿 / 动画时间 /
       刚体速度 / 时钟 alpha）；
     · 但渲染仍在跑：GL 的 _stage_frames +10、VK 的 draw_frame 调用 +10（生产计数器），
       每帧都真的出了画面，实测帧间隔 > 0（打印 FPS）；
     · 画面逐像素稳定：暂停第 1 帧截图 == 第 10 帧截图（MAE=0 且 MAX=0）。
  ② F10 单步**恰好**推进 1 个逻辑帧
     · 暂停态喂一次真 F10 键事件（内核唯一入口 handle_key_event → step_logic_once）→
       两端逻辑帧计数**恰好 +1**（不是 0，不是 2）；
     · 位移量 == 手算 SPEED*fixed_dt（逐值相等，不是「差不多」）；动画时间 == 手算 +1*fixed_dt；
     · 连按 3 次 → 恰好 +3，位移 == 手算 3 步。
  ③ 恢复无欠账
     · 暂停 30 个渲染帧后恢复 → 恢复首帧逻辑帧增量 == **正常一帧的量**（= 手算
       render_dt/fixed_dt = 1），**不是** 30；位移量 == 1 步（不是 30 步）；
     · 恢复后画面不跳变：恢复首帧 == 同一状态「正常推进 1 帧」的画面（逐像素相等）。
  ④ 暂停期渲染画面 == 暂停时刻画面（窗口级关键）
     · 暂停瞬间截图 A，暂停 10 帧后截图 B → A == B（逐像素，MAE=0/MAX=0）；
     · 恢复并跑 1 帧后截图 C → C != A（证明恢复真的动了），且 C 等于「正常 1 帧」的画面。
  ⑤ 单步的画面推进 == 逻辑推进
     · 单步 1 次后截图 D1：D1 != A（动了），且 D1 == 参照对「同一状态 + **正常 1 帧**」
       的画面（逐像素相等 —— 期望值来自**另一条生产路径**，不取自被测那一帧）；
     · 单步 3 次后截图 D3 == 参照对「正常 3 帧」的画面（逐像素）。
  ⑥ 两端截图对拍（最强判据）
     · 同一场景 + 同一暂停/单步序列后的 4 个时刻（暂停瞬间 / 单步 1 / 单步 3 / 恢复后）
       两端截图逐像素相等或 MAE<=2e-4（口径来源：tests/test_ab_gl_vk.py 的
       DEFAULT_GATE['mae_abs']=0.0002，既有 A/B 门口径，见本文件 MAE_GATE）。

两端生产入口（不拼假对象、不手写状态机绕过生产路径；§5 反模式 8）：
  GL : runtime.PlayerApp(None, W, H, ctx=离屏 GL 上下文, scene_data=场景)
       —— 玩家实际发布的打包 GL 入口（build_entry / game_player / --run 全走它）。
       渲染帧 = loom_render.render(delta_time)（暂停分支 :1153-1193、F10 消费 :1174-1183）。
       画面 = 该帧生产渲染目标 _external_fb 的逐像素回读（test_ab_gl_vk 同口径，
       FBO 回读自下而上 → np.flipud）。
  VK : scene_driver.SceneDriver() + build_scene_from_data(场景)
       渲染帧 = advance_logic(render_dt) + compute_frame_view_proj(aspect) + VkRenderer.draw_frame(...)
       —— 与 vk_player.draw:643-725 的生产调用次序逐项一致（帧首结算 → 时钟 → compute_frame_view_proj
       → draw_frame）。
       画面 = draw_frame 写进的离屏纹理逐像素回读（test_ab_gl_vk 同口径）。
  键事件: 两端同一串 pygame 键常量喂 handle_key_event（内核 S1 唯一入口，两端同一份）——
       F9 暂停 / F10 单步都走它，不在测试里直接调 set_logic_paused（那就是绕生产路径）。

判据独立性（§5 反模式 3：不许用被测对象自证）：
  · **逻辑帧计数**用独立计数器：把 _logic_frame（时钟的 on_logic_step 回调 = 一个逻辑帧的
    唯一组织点）在**构造引擎之前**做类级包装，逐次计数。计数器不看任何一端自报的
    steps/_logic_steps（那些只作为额外佐证打印）。
  · **位移量**手算：mover 脚本按 x += SPEED*fixed_dt 走，期望值由本文件用同一个表达式
    逐步累加得到（fixed_dt 取自时钟的公开属性 fixed_dt，不是读位置反推）。
  · **画面推进量**用「另一条生产路径」当参照：同一构造 + 同一预热序列的第二个 Pair
    （参照对）正常推进 1/3 帧，画面必须与暂停态单步 1/3 次的画面**逐像素相等**。
    这条同时证明「单步的画面 == 1 个 fixed_dt 的量」而不是「0」或「多帧」。

环境前提（只建输入前提，不改任何断言/语义）：
  · LOOM_LOGIC_SYNC=1 —— GL 的异步逻辑线程只在 Qt 宿主（_external_ctx=True）启用
    （render/gl/engine.py:1443 注释）。本门是离屏 ctx（_external_ctx=True），按该注释走同步路径。
  · 两端同一份设置改动：clk.set_fps(logic_fps=60.0)（设置面板改 TPS 的生产入口，
    ui/loom_gui.py:3799 / agent_commands.py:3649 同款，运行中即时生效）→ fixed_dt=1/60，
    于是「1 渲染帧（dt=1/60）= 恰好 1 个逻辑帧」可**手算**，期望值不依赖任何一端。
  · GL 每帧喂 dt 前把 _logic_wall_last 清空 —— 这是 engine._clock_advance docstring
    明写的无头直驱口径（「测试 / 无头直驱: 传合成 dt 且墙钟≈0 -> max = 合成 dt」）：
    真实运行里帧间隔≈dt，测试里渲染一帧可能花 20ms，不归零会让 GL 多追逻辑步而 VK 不追
    （VK 的 _logic_ratio_tick 是 floor=False，只记账不推进）。**真实墙钟下限路径
    （floor=True 生效）未纳入本门**（见文件末「未核」）。
  · 夹具顺序前提（本机实测，纯测试进程伪影）：本进程里先建 GL 上下文、后建 wgpu
    (Vulkan) device，会让**已存在的** GL 上下文后续 ctx.buffer(...) 失败
    （_moderngl.Error: cannot create buffer + GL_INVALID_OPERATION；实测见交付报告）。
    故夹具先建设备再建 GL 上下文。生产里一个进程只用一种后端（用户选 opengl 或 vulkan），
    不存在该组合 —— 这是**测试进程特有的驱动交互**，不是用户可感知的两端差异。
  · 物理：本门**打开**物理（不设 LOOM_NO_PHYSICS），用 Jolt(Culverin) 桥驱动一个自由落体
    刚体，把「暂停期物理位置逐值不变」变成可判定事实（实测两端逐帧逐值相等）。
  · 动画：场景里挂一个 Animator 物体的 clip，并用生产 API animator.play('slide') 起播
    （同一串脚本级调用喂两端；场景字典不落盘 playing 是设计如此，见 animator_to_dict）。

已知差异登记表：**必须为空**（KNOWN_DIFFS）。任何「差不多」/阈值/容差都不许。
（唯一的数值门限是 MAE_GATE，它是**既有 A/B 门口径**，来源写死在常量旁边。）

结构断言防护（B7-16 复查 P0-1 教训）：结构段用**递归**扫描定位生产文件（排除 tests/），
同时覆盖当前名与历史名；且**只断言正面不变量**（唯一实现 / 调用点存在 / 两端同一个函数
对象），**不锁任何缺陷态**（P4 教训：别把「VK 没有 X」写进结构断言）。

未核（本门不覆盖，留痕）：
  ① GL 的「墙钟下限」路径（floor=True 真正生效、帧长 > dt 时多追逻辑步）：本门把该输入项
     归零以获得可手算的确定性，真实帧率抖动下的表现**未核**（VK 侧 floor=False，天然不同口径，
     属既有设计差异，不是本门引入）。
  ② 真窗口 swapchain 回读：两端画面都取自**生产渲染目标**（GL 的 _external_fb / VK 的离屏
     纹理，test_ab_gl_vk 同口径）。真窗口上屏内容（glfw.swap_buffers 之后的前台缓冲）
     **未核** —— swap 后回读未定义，且本夹具的 VK 侧没有窗口。
  ③ 绑死模式（设置 logic_fps<=0）下的暂停/单步**未核**（本门固定分离模式；绑死模式的
     暂停分支见 P4-4 记录）。
  ④ UI/HUD 叠加层未纳入像素对拍（GL 播放器 _draw_hud 是 pass、VK 默认 hud_lines=None，
     两端都没有叠加层 —— 有 UI 的场景属 P3 面）。
"""
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    """打印出 FAIL 即让进程退出码为 1（run_all 只看退出码）。"""

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


import math
import os
import sys
import tempfile
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # Loom/
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_DIALOG'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_LOGIC_SYNC'] = '1'        # 无头直驱（见文件头「环境前提」）
os.environ.setdefault('LOOM_USER_ROOT', tempfile.mkdtemp(prefix='loom_p6_userroot_'))

import numpy as np                                                # noqa: E402
import pygame                                                     # noqa: E402

import engine as E                                                # noqa: E402
import scene.contract as _scene_contract                                        # noqa: E402  场景版本号单点（不写死）
import moderngl                                                   # noqa: E402
import runtime                                                    # noqa: E402  GL 打包播放器（生产入口）
import render.vk.driver as SD                                         # noqa: E402  VK 播放器（生产入口）
import render.vk.renderer as VR                                          # noqa: E402  VK 渲染器（生产绘制）
import wgpu                                                       # noqa: E402
from core.primitives import Point3D                                    # noqa: E402  脚本写位姿的唯一数据形态
from script.scripts import Script, register                              # noqa: E402  脚本生产注册路径

ok = True
KNOWN_DIFFS = []            # 已知差异登记表：必须为空
FRAME_DT = 1.0 / 60.0       # 渲染帧步（与 logic_fps=60 对齐 → 1 帧 = 1 逻辑帧，可手算）
LOGIC_FPS = 60.0
W, H = 480, 320             # 与 test_ab_gl_vk 同分辨率（口径一致）
SPEED = 2.0                 # mover 脚本速度 (单位/秒) —— 期望值手算的唯一输入
# 像素对拍门限：**沿用既有 A/B 门口径**
# 来源：tests/test_ab_gl_vk.py 的 DEFAULT_GATE['mae_abs'] = 0.0002（全局，非本门新造）
MAE_GATE = 0.0002


def check(label, cond, detail=''):
    global ok
    # 2026-11-19（P1-6）：detail 只在**失败**时打印，且冠以「失败详情:」前缀。
    # 修前无论成败都打 detail，于是 PASS 行后面挂着一串 GL/VK 快照，读起来像
    # 「PASS 却说两端不一致」（本门多数 check 的 detail 是 GL/VK 双列快照）。
    # 只改打印逻辑，断言表达式一字未动。
    print(('PASS ' if cond else 'FAIL ') + label
          + (('  失败详情: ' + str(detail)) if (not cond and detail) else ''))
    if not cond:
        ok = False


def seq_check(title, rows):
    """rows = [(label, gl值, vk值), ...]：逐行打 GL vs VK 对照表并比对。"""
    bad = [(lb, g, v) for (lb, g, v) in rows if g != v]
    for lb, g, v in rows:
        print('    %-44s GL=%-34s VK=%s' % (lb, g, v))
    check(title, not bad,
          '；'.join('%s: GL=%s VK=%s' % (lb, g, v) for (lb, g, v) in bad[:3])
          if bad else '%d 步逐项相等' % len(rows))


def tri_check(title, rows):
    """rows = [(label, gl值, vk值, 手算期望), ...]：三列对照 + 逐行断言。

    这是本门的主要"三列"证据形态：GL / VK / 手算期望 同时打出来。
    """
    bad = []
    for lb, g, v, exp in rows:
        print('    %-40s GL=%-26s VK=%-26s 期望=%s' % (lb, g, v, exp))
        if not (g == v == exp):
            bad.append((lb, g, v, exp))
    check(title, not bad,
          '；'.join('%s: GL=%r VK=%r 期望=%r' % b for b in bad[:3])
          if bad else '%d 行三列逐值相等' % len(rows))


# ============================ 〇. 结构：唯一实现 / 生产锚点 / 历史名 ============================

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


print("=== 〇. 结构：暂停/单步的唯一实现 + 三条暂停分支 + 历史名 ===")
# 1) 暂停/步进语义只有一份（内核 EngineCore），两端继承同一份函数对象
_step_defs = _grep_prod('def step_logic_once')
check('结构：def step_logic_once 只有 engine_core.py 一份（两端同一个函数对象）',
      [p for (p, _l) in _step_defs] == ['core/engine_core.py'], _step_defs)
check('结构：GLEngine.step_logic_once is SceneDriver.step_logic_once（同一份实现，不是各写一遍）',
      E.GLEngine.step_logic_once is SD.SceneDriver.step_logic_once,
      (E.GLEngine.step_logic_once, SD.SceneDriver.step_logic_once))
_toggle_defs = _grep_prod('def toggle_logic_paused')
check('结构：def toggle_logic_paused 只有 engine_core.py 一份',
      [p for (p, _l) in _toggle_defs] == ['core/engine_core.py'], _toggle_defs)
_state_defs = _grep_prod('def _logic_paused_state')
check('结构：def _logic_paused_state 只有 engine_core.py 一份（两端同读一处判定）',
      [p for (p, _l) in _state_defs] == ['core/engine_core.py'], _state_defs)
# set_logic_paused：内核版 + VK 的显式覆盖（VK 有 logic_paused 字段，覆盖是登记在案的）
_pause_defs = sorted(p for (p, _l) in _grep_prod('def set_logic_paused'))
check('结构：def set_logic_paused 只在内核 + VK 驱动两处（内核版为 GL 基准，VK 覆盖登记在案）',
      _pause_defs == ['core/engine_core.py', 'render/vk/driver.py'], _pause_defs)
# 2) 一个逻辑帧的唯一组织点：两端各一份（段序一致由 test_vk_logic_frame_parity 覆盖）
_lf_defs = sorted(p for (p, _l) in _grep_prod('def _logic_frame'))
check('结构：def _logic_frame 恰好两端各一份（render/gl/engine.py / render/vk/driver.py，没有第三份拷贝）',
      _lf_defs == ['render/gl/engine.py', 'render/vk/driver.py'], _lf_defs)
# 3) 三条暂停分支都消费 _step_requested 并走 clk.step_once()（GL 宿主/GL 渲染帧/VK）
for _f, _why in (('render/gl/engine.py', 'GL 宿主同步路径的暂停分支（advance_logic）'),
                 ('render/gl/render.py', 'GL 玩家主循环的暂停分支（render 自驱时钟）'),
                 ('render/vk/driver.py', 'VK 渲染帧的暂停分支（advance_logic）')):
    src_has(_f, 'clk.step_once()', True, _why + '：F10 单步走时钟唯一实现')
    src_has(_f, '_step_requested', True, _why + '：F10 请求标志消费点')
    src_has(_f, 'self._logic_wall_last = None', True,
            _why + '：暂停/恢复边界重锚墙钟（不补暂停期欠账）')
src_has('render/gl/render.py', 'self._logic_steps = 0', True,
        'GL 暂停且无步进请求：本渲染帧零逻辑（世界冻结、渲染照跑）')
src_has('core/engine_core.py', 'self._step_requested = True', True,
        'F10 请求标志的唯一置位点（仅暂停态生效）')
src_has('core/engine_core.py', "if not self._logic_paused_state():", True,
        'step_logic_once 仅在暂停态生效（播放态按 F10 不跳帧）')
# 4) 历史名 / 拷贝名不得回来（真·历史名实测不存在；这里把它们钉住）
for _hist in ('def _step_one_frame', 'def step_frame', 'def _advance_one_logic_frame',
              'def _step_logic_once'):
    _h = _grep_prod(_hist)
    check('结构：历史名/拷贝名 %r 在全部生产文件里不存在' % _hist, not _h, _h[:4])
check('已知差异登记表为空（不许登记任何容差）', not KNOWN_DIFFS, KNOWN_DIFFS)


# ============================ 夹具（生产入口 + 生产构造式） ============================

_GL = {'ctx': None, 'fbo': None}
_VK = {'device': None, 'renderer': None, 'tex': None, 'readbuf': None, 'bpr': 0, 'draws': 0}


def _device():
    """wgpu 设备（**必须先于 GL 上下文创建**，见文件头「夹具顺序前提」）。"""
    if _VK['device'] is None:
        adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
        if adapter is None:
            raise RuntimeError('无可用 Vulkan 适配器（本门要求两端都真渲染）')
        _VK['device'] = adapter.request_device_sync()
    return _VK['device']


def _gl_target():
    """GL 离屏渲染目标（test_ab_gl_vk 同口径：引擎把 _external_fb 当渲染目标）。"""
    if _GL['ctx'] is None:
        _device()                       # ★顺序前提：设备先建
        _GL['ctx'] = moderngl.create_standalone_context(require=430)
        ctx = _GL['ctx']
        _GL['fbo'] = ctx.framebuffer(
            color_attachments=[ctx.renderbuffer((W, H), components=4)],
            depth_attachment=ctx.depth_renderbuffer((W, H)))
    return _GL['ctx'], _GL['fbo']


def _vk_renderer():
    if _VK['renderer'] is None:
        device = _device()
        fmt = 'rgba8unorm'
        _VK['tex'] = device.create_texture(
            size=(W, H, 1), format=fmt,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
        _VK['renderer'] = VR.VkRenderer(device, fmt)
        bpr = (W * 4 + 255) // 256 * 256
        _VK['bpr'] = bpr
        _VK['readbuf'] = device.create_buffer(
            size=bpr * H, usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)
        # 生产渲染调用计数器（draw_frame = vk_player.draw:720 的那一次调用）
        _orig = _VK['renderer'].draw_frame

        def _counted(*a, **k):
            _VK['draws'] += 1
            return _orig(*a, **k)
        _VK['renderer'].draw_frame = _counted
    return _VK['renderer']


class _VkCtx:
    """vk_player.draw 的 canvas 契约（get_current_texture + physical_size）。"""
    physical_size = (W, H)

    def get_current_texture(self):
        return _VK['tex']


def read_gl():
    """GL 生产渲染目标的逐像素回读（FBO 自下而上 → flipud，test_ab_gl_vk 同口径）。"""
    raw = _GL['fbo'].read(components=3)
    img = np.frombuffer(raw, dtype='u1').reshape(H, W, 3).astype(np.float32) / 255.0
    return np.flipud(img)


def read_vk():
    device = _VK['device']
    bpr = _VK['bpr']
    buf = _VK['readbuf']
    enc = device.create_command_encoder()
    enc.copy_texture_to_buffer(
        {'texture': _VK['tex']},
        {'buffer': buf, 'offset': 0, 'bytes_per_row': bpr, 'rows_per_image': H},
        (W, H, 1))
    device.queue.submit([enc.finish()])
    buf.map_sync(wgpu.MapMode.READ)
    arr = np.frombuffer(buf.read_mapped(), dtype='u1').reshape(H, bpr // 4, 4)
    img = arr[:, :W, :3].astype(np.float32) / 255.0
    try:
        buf.unmap()
    except Exception:
        pass
    return img


def metrics(a, b):
    """MAE / MAX / NCC —— 与 test_ab_gl_vk.metrics 逐行同口径（float64 累加）。"""
    d = np.abs(a.astype(np.float64) - b.astype(np.float64))
    mae = float(d.mean())
    mx = float(d.max())
    la = a.astype(np.float64).mean(axis=2).ravel()
    lb = b.astype(np.float64).mean(axis=2).ravel()
    la = la - la.mean()
    lb = lb - lb.mean()
    ncc = float((la * lb).sum() / (np.linalg.norm(la) * np.linalg.norm(lb) + 1e-12))
    return mae, mx, ncc


def img_eq(a, b):
    """逐像素完全相等（MAE==0 且 MAX==0）。"""
    return bool(np.array_equal(a, b))


# ---- 场景（两端同一份用户内容） ----

class _Mover(Script):
    """匀速移动脚本：用户脚本驱动物体就是这么写的（每逻辑帧 x += SPEED*fixed_dt）。"""
    script_id = 'p6_mover'
    name = 'P6 匀速移动'

    def on_fixed_update(self, fixed_dt):
        o = self.obj
        o.position = Point3D(o.position.x + SPEED * fixed_dt, o.position.y, o.position.z)


register(_Mover)


def _cube(oid, pos, scale=(1.0, 1.0, 1.0), color='#40c0ff', size=1.0, **kw):
    d = {'id': oid, 'name': oid, 'type': 'cube', 'params': {'size': size},
         'position': list(pos), 'rotation': [0.0, 0.0, 0.0], 'scale': list(scale),
         'color': color, 'visible': True}
    d.update(kw)
    return d


def scene_data():
    """同一份场景：脚本物体（mover）+ 动画物体（anim）+ 自由落体（fall）+ 一盏定向光。"""
    return {
        'version': _scene_contract.CURRENT_VERSION,
        'camera': {'target': [0.0, 0.0, 0.0], 'distance': 9.0, 'yaw': 0.6, 'pitch': -0.3},
        'cameras': [], 'active_camera': None,
        'objects': [
            _cube('mover', (0.0, 0.0, 0.0), size=1.0, color='#40c0ff',
                  scripts=[{'id': 'p6_mover', 'vars': {}}]),
            _cube('anim', (0.0, 1.6, 0.0), size=0.8, color='#ffcc40',
                  animator={'current': 'slide', 'loop': True,
                            'clips': {'slide': [{'time': 0.0, 'position': [-1.5, 1.6, 0.0]},
                                                {'time': 1.0, 'position': [1.5, 1.6, 0.0]}]}}),
            _cube('fall', (1.6, 2.5, 0.0), size=0.8, color='#40ff80',
                  rigidbody={'mass': 1.0, 'use_gravity': True, 'is_kinematic': False,
                             'friction': 0.5, 'restitution': 0.0}),
        ],
        'lights': [{'id': 'sun', 'kind': 'directional', 'direction': [-0.4, -1.0, -0.3],
                    'color': [1.0, 0.96, 0.9], 'intensity': 1.0, 'shadow': True,
                    'mode': 'full', 'shape': 'circle', 'size': 5}],
        'materials': [], 'gravity': -9.8, 'skybox': None,
    }


# ---- 独立逻辑帧计数器（构造前做类级包装 → 时钟里注册的就是 wrapper） ----

_COUNT = {'gl': 0, 'vk': 0}
_ORIG_LF = {}


def _install_logic_counter(cls, key):
    _ORIG_LF[key] = cls._logic_frame

    def wrapped(self, fixed_dt):
        _COUNT[key] += 1
        return _ORIG_LF[key](self, fixed_dt)

    wrapped.__name__ = '_logic_frame'
    wrapped.__doc__ = 'P6 门的独立逻辑帧计数器包装（原实现见 _ORIG_LF）'
    cls._logic_frame = wrapped


_install_logic_counter(E.GLEngine, 'gl')      # PlayerApp 继承 GLEngine
_install_logic_counter(SD.SceneDriver, 'vk')


def count():
    return dict(_COUNT)


def dcount(base):
    return (_COUNT['gl'] - base['gl'], _COUNT['vk'] - base['vk'])


# ---- 位姿 / 逻辑状态读取（只加观测，不绕生产路径） ----

def _pt(p):
    return (float(p.x), float(p.y), float(p.z))


def _sc(s):
    return (float(s[0]), float(s[1]), float(s[2]))


def logic_state(eng):
    """逻辑状态快照：物体位姿 + 动画时间/播放位 + 刚体速度。

    只读生产字段（模型 transform / animator / rigidbody），不读任何渲染中间量。
    """
    out = []
    for m in eng.models:
        an = getattr(m, 'animator', None)
        rb = getattr(m, 'rigidbody', None)
        out.append((
            getattr(m, 'name', '?'),
            _pt(m.position), _pt(m.rotation), _sc(m.scale),
            None if an is None else (float(an.time), bool(an.playing)),
            None if rb is None else _pt(rb.velocity),
        ))
    return tuple(out)


def clock_state(eng):
    clk = getattr(eng, '_clock', None)
    if clk is None:
        return None
    return (float(clk.alpha), int(clk.steps), int(clk.pending_steps()))


def hand_x(x0, n):
    """手算 n 个逻辑帧后的 mover x（与脚本同一个表达式逐步累加，不用位置反推）。"""
    x = x0
    fd = 1.0 / LOGIC_FPS
    for _ in range(n):
        x = x + SPEED * fd
    return x


def hand_t(t0, n):
    """手算 n 个逻辑帧后的动画播放头（与 evaluate_animations 同一个表达式逐步累加）。"""
    t = t0
    fd = 1.0 / LOGIC_FPS
    for _ in range(n):
        t = t + fd * 1.0          # an.speed = 1.0
    return t


class Pair:
    """一对生产后端（同一份场景）+ 生产帧驱动 + 逐像素截图。"""

    def __init__(self, warm=4):
        _device()                                   # ★顺序前提：设备先建（见文件头）
        ctx, fbo = _gl_target()
        data = scene_data()
        self.gl = runtime.PlayerApp(None, W, H, ctx=ctx, scene_data=data)
        self.gl._external_fb = fbo
        self.gl.is_playing = True
        self.gl._clock.set_fps(logic_fps=LOGIC_FPS)
        self.vk = SD.SceneDriver()
        self.vk.is_playing = True
        self.vk.build_scene_from_data(scene_data())
        self.vk._clock.set_fps(logic_fps=LOGIC_FPS)
        _vk_renderer()
        # 同一串脚本级调用：起播动画（场景字典不落盘 playing 是设计如此）
        for eng in (self.gl, self.vk):
            eng.find_by_name('anim').animator.play('slide')
        self.last = (None, None)          # 最后一次渲染的两端画面（= 玩家最后看到的那帧）
        self.frames(warm)

    # ---- 生产帧 ----
    def gl_frame(self):
        """GL 生产渲染帧（loom_render.render）。墙钟下限项归零 = 无头直驱口径。"""
        self.gl._logic_wall_last = None
        self.gl.render(FRAME_DT)
        return read_gl()

    def vk_frame(self):
        """VK 生产渲染帧：vk_player.draw:643-725 的调用次序逐项镜像。"""
        d = self.vk
        d.advance_logic(FRAME_DT)                        # render/vk/player.py:674
        if getattr(d, '_interp', None) is not None:
            d._interp.alpha = d._clock.alpha             # render/vk/player.py:679-680
        vp, cam_pos = d.compute_frame_view_proj(aspect=W / H)        # render/vk/player.py:681
        _yaw, _pitch, _roll = ((d.yaw, d.pitch, 0.0) if getattr(d, 'orbit_mode', True)
                               else (d.camera_yaw, d.camera_pitch, d.camera_roll))
        import mathlib.matlib as matlib
        V = matlib.mat4_view_yaw_pitch(np, tuple(cam_pos), _yaw, _pitch, _roll)
        cam_basis = ((float(V[0, 0]), float(V[0, 1]), float(V[0, 2])),
                     (float(V[1, 0]), float(V[1, 1]), float(V[1, 2])))
        _vk_renderer().draw_frame(                         # render/vk/player.py:720
            _VkCtx(), d.models, d.lights, vp, cam_pos, engine=d,
            interp=getattr(d, '_interp', None), sky=getattr(d, 'skybox', None),
            ui=getattr(d, 'ui', None), hud_lines=None, cam_basis=cam_basis)
        return read_vk()

    def frames(self, n=1):
        """跑 n 个渲染帧；返回最后一帧的两端画面（n=0 → 预热结束那一刻的画面）。"""
        g, v = self.last
        for _ in range(n):
            g = self.gl_frame()
            v = self.vk_frame()
        self.last = (g, v)
        return g, v

    # ---- 同一串输入喂两端（内核唯一入口） ----
    def key(self, pg, down=True):
        ev = SimpleNamespace(type='KEYDOWN' if down else 'KEYUP', key=pg, mod=0, unicode='')
        return (self.gl.handle_key_event(ev), self.vk.handle_key_event(ev))

    def pause(self):
        """F9（生产键事件）：两端都进暂停。"""
        r = self.key(pygame.K_F9, True)
        self.key(pygame.K_F9, False)
        return r

    def resume(self):
        r = self.key(pygame.K_F9, True)
        self.key(pygame.K_F9, False)
        return r

    def step(self):
        """F10（生产键事件）：两端都置一次单步请求。"""
        r = self.key(pygame.K_F10, True)
        self.key(pygame.K_F10, False)
        return r

    def paused(self):
        return (bool(self.gl._logic_paused_state()), bool(self.vk._logic_paused_state()))

    def states(self):
        return (logic_state(self.gl), logic_state(self.vk))

    def x(self):
        return (float(self.gl.find_by_name('mover').position.x),
                float(self.vk.find_by_name('mover').position.x))

    def anim_time(self):
        return (float(self.gl.find_by_name('anim').animator.time),
                float(self.vk.find_by_name('anim').animator.time))

    def render_counters(self):
        """GL 生产渲染帧计数（_stage_frames，loom_render:1141）+ VK draw_frame 调用数。"""
        return (int(getattr(self.gl, '_stage_frames', -1)), int(_VK['draws']))


print()
print("=== 〇'. 夹具保真：两端都是生产类 + 生产构造式 + 同一份场景装配一致 ===")
_p0 = Pair()
check('GL 端是打包播放器 runtime.PlayerApp（生产入口）',
      type(_p0.gl) is runtime.PlayerApp, type(_p0.gl).__name__)
check('VK 端是 scene_driver.SceneDriver（生产入口）',
      type(_p0.vk) is SD.SceneDriver, type(_p0.vk).__name__)
check('夹具前提：两端装配出同名同序物体（同一份场景 = 同一串用户内容）',
      [m.name for m in _p0.gl.models] == [m.name for m in _p0.vk.models],
      ([m.name for m in _p0.gl.models], [m.name for m in _p0.vk.models]))
check('夹具前提：两端时钟都按生产入口设到 logic_fps=60（fixed_dt=1/60，1 帧=1 逻辑帧）',
      (_p0.gl._clock.fixed_dt, _p0.vk._clock.fixed_dt) == (1.0 / 60.0, 1.0 / 60.0),
      (_p0.gl._clock.fixed_dt, _p0.vk._clock.fixed_dt))
_g0, _v0 = _p0.frames(1)
check('夹具保真：两端都真的出了画面（非纯色/非全黑 —— 逐像素对拍的前提）',
      (float(_g0.std()) > 0.01) and (float(_v0.std()) > 0.01),
      ('GL std=%.4f' % float(_g0.std()), 'VK std=%.4f' % float(_v0.std())))
check('夹具前提：两端动画都在真的推进（animator.time 随逻辑帧前进，两端同值）',
      _p0.anim_time()[0] > 0.0 and _p0.anim_time()[0] == _p0.anim_time()[1],
      _p0.anim_time())
check('夹具前提：两端刚体都在真的下落（物理桥真的在驱动，不是空转）',
      float(_p0.gl.find_by_name('fall').position.y) < 2.5
      and float(_p0.vk.find_by_name('fall').position.y)
      == float(_p0.gl.find_by_name('fall').position.y),
      (float(_p0.gl.find_by_name('fall').position.y),
       float(_p0.vk.find_by_name('fall').position.y)))


# ============================ ① 暂停时画面冻结但渲染继续 ============================
print()
print("=== ①. 暂停期：逻辑状态逐值不变 + 渲染仍在跑 + 画面逐像素稳定 ===")
p = Pair()
rows = []
_s_gl, _s_vk = p.states()
check('① 暂停前两端逻辑状态逐值相等（同一份场景 + 同一串帧 → 同一位形）',
      _s_gl == _s_vk, 'GL 物体数=%d VK 物体数=%d' % (len(_s_gl), len(_s_vk)))
r = p.pause()
check('① F9 两端都被内核消费（返回 True）', r == (True, True), r)
check('① F9 后两端都进入暂停', p.paused() == (True, True), p.paused())
_c0 = count()
_r0 = p.render_counters()
_clk0 = (clock_state(p.gl), clock_state(p.vk))
imgs = []
t_wall = []
for i in range(10):
    t0 = time.perf_counter()
    g = p.gl_frame()
    v = p.vk_frame()
    t_wall.append(time.perf_counter() - t0)
    imgs.append((g, v))
    s_gl, s_vk = p.states()
    rows.append(('暂停第 %d 帧 · 逻辑状态' % (i + 1), s_gl, s_vk))
dc = dcount(_c0)
check('① 暂停 10 个渲染帧：两端逻辑帧计数**都不动**（Δ=0）', dc == (0, 0), dc)
check('① 暂停期逻辑状态逐帧不变（10 帧全部 == 暂停时刻快照，两端都成立）',
      all(g == _s_gl and v == _s_vk for (_lb, g, v) in rows),
      '；'.join('%s: GL=%r VK=%r' % (lb, g == _s_gl, v == _s_vk)
               for (lb, g, v) in rows if not (g == _s_gl and v == _s_vk))[:400])
seq_check('① 暂停期：两端逻辑状态逐帧逐项相等（位姿/动画时间/刚体速度）', rows)
_clk1 = (clock_state(p.gl), clock_state(p.vk))
check('① 暂停期时钟也冻结（alpha/steps/pending 三件都不动，两端同值）',
      _clk1 == _clk0, (_clk0, _clk1))
_rc = p.render_counters()
check('① 渲染仍在跑：GL _stage_frames +10 且 VK draw_frame 调用 +10（生产渲染计数器）',
      (_rc[0] - _r0[0], _rc[1] - _r0[1]) == (10, 10),
      'ΔGL=%d ΔVK=%d' % (_rc[0] - _r0[0], _rc[1] - _r0[1]))
_mean_dt = sum(t_wall) / len(t_wall)
_fps = 1.0 / _mean_dt if _mean_dt > 0 else 0.0
check('① 渲染真的在推进：每帧墙钟 > 0、FPS 有限且 > 0（无卡死/无零耗时假帧）',
      _mean_dt > 0.0 and math.isfinite(_fps) and _fps > 0.0,
      '平均帧长 %.1fms → FPS≈%.1f' % (_mean_dt * 1000.0, _fps))
_jit = p.gl.get_frame_jitter()
check('① GL 侧生产帧长滑窗也记了这些帧（_frame_dt 生产记账随渲染帧增长）',
      int(_jit[2]) >= 10, 'n=%d std=%.2fms' % (int(_jit[2]), _jit[0]))
check('① 画面逐像素稳定：暂停第 1 帧 == 第 10 帧（GL 与 VK 各自成立，MAE=0/MAX=0）',
      img_eq(imgs[0][0], imgs[-1][0]) and img_eq(imgs[0][1], imgs[-1][1]),
      'GL MAE=%.8f VK MAE=%.8f' % (metrics(imgs[0][0], imgs[-1][0])[0],
                                   metrics(imgs[0][1], imgs[-1][1])[0]))


# ============================ ② F10 单步恰好 1 个逻辑帧 ============================
print()
print("=== ②. F10 单步：逻辑帧计数恰好 +1 / +3，位移 == 手算 SPEED*fixed_dt ===")
rows = []
_x0 = p.x()
_t0 = p.anim_time()
check('② 暂停态两端 mover 的 x 逐值相等（单步前基线）', _x0[0] == _x0[1], _x0)
_c0 = count()
r = p.step()
check('② F10 两端都被内核消费（返回 True）', r == (True, True), r)
gD1 = p.gl_frame()
vD1 = p.vk_frame()
dc = dcount(_c0)
check('② 单步 1 次 → 两端逻辑帧计数**恰好 +1**（不是 0，不是 2）', dc == (1, 1), dc)
_x1 = p.x()
_t1 = p.anim_time()
rows.append(('单步 1 次 · mover.x', _x1[0], _x1[1], hand_x(_x0[0], 1)))
rows.append(('单步 1 次 · anim.time', _t1[0], _t1[1], hand_t(_t0[0], 1)))
tri_check('② 单步 1 次：GL / VK / 手算期望 三列逐值相等', rows)
_y_fall0 = float(p.gl.find_by_name('fall').position.y)
# 连按 2 次（共 3 次）
_c0 = count()
for i in range(2):
    p.step()
    p.gl_frame()
    p.vk_frame()
dc = dcount(_c0)
check('② 连按 3 次（再 2 次）→ 两端逻辑帧计数**恰好 +2**（累计 +3）', dc == (2, 2), dc)
_x3 = p.x()
_t3 = p.anim_time()
rows2 = [('单步 3 次 · mover.x', _x3[0], _x3[1], hand_x(_x0[0], 3)),
         ('单步 3 次 · anim.time', _t3[0], _t3[1], hand_t(_t0[0], 3))]
tri_check('② 连按 3 次：GL / VK / 手算期望 三列逐值相等', rows2)
check('② 单步期间物理也各走 1 步（落体 y 单调下降，两端逐值相等）',
      float(p.gl.find_by_name('fall').position.y) < _y_fall0
      and float(p.gl.find_by_name('fall').position.y)
      == float(p.vk.find_by_name('fall').position.y),
      (float(p.gl.find_by_name('fall').position.y),
       float(p.vk.find_by_name('fall').position.y)))
check('② 单步不会把两端逻辑状态带偏（两端逻辑状态仍逐值相等）',
      p.states()[0] == p.states()[1], 'GL/VK 快照不一致')


# ============================ ③ 恢复无欠账 ============================
print()
print("=== ③. 恢复无欠账：暂停 30 帧后恢复，首帧增量 == 正常一帧的量（不是 30） ===")
q = Pair()
rows = []
# 「正常一帧的量」：先量 3 个未暂停帧（每帧应恰好 1 个逻辑帧 = 手算 render_dt/fixed_dt）
_c0 = count()
for i in range(3):
    q.gl_frame()
    q.vk_frame()
_normal = dcount(_c0)
_hand_normal = int(round(FRAME_DT / (1.0 / LOGIC_FPS)))     # = 1
check('③ 正常一帧的量 == 手算 render_dt/fixed_dt（3 帧各 1 步）',
      _normal == (3 * _hand_normal, 3 * _hand_normal),
      '实测 Δ=%r 手算=%d 帧×%d 步' % (_normal, 3, _hand_normal))
r = q.pause()
check('③ F9 两端都进入暂停', q.paused() == (True, True), q.paused())
_x_before = q.x()
_c0 = count()
for i in range(30):
    q.gl_frame()
    q.vk_frame()
dc = dcount(_c0)
check('③ 暂停 30 个渲染帧：两端逻辑帧计数都不动（Δ=0）', dc == (0, 0), dc)
_x_paused = q.x()
check('③ 暂停 30 帧后位移仍是暂停时刻的值（不是 30 步的量）', _x_paused == _x_before,
      (_x_before, _x_paused))
r = q.resume()
check('③ F9 两端都恢复', q.paused() == (False, False), q.paused())
_c0 = count()
gR = q.gl_frame()
vR = q.vk_frame()
dc = dcount(_c0)
check('③ 恢复首帧：两端逻辑帧增量 == 正常一帧的量（1），**不补暂停期欠账**（不是 30）',
      dc == (_hand_normal, _hand_normal), 'Δ=%r 期望=(%d, %d)' % (dc, _hand_normal, _hand_normal))
_x_resume = q.x()
rows.append(('恢复首帧 · mover.x', _x_resume[0], _x_resume[1], hand_x(_x_paused[0], 1)))
tri_check('③ 恢复首帧位移 == 手算 1 步（不是 30 步）', rows)
check('③ 恢复后没有积压（两端 pending_steps 都为 0，accumulator 没留下暂停期的时间）',
      (q.gl._clock.pending_steps(), q.vk._clock.pending_steps()) == (0, 0),
      (q.gl._clock.pending_steps(), q.vk._clock.pending_steps()))
check('③ 恢复后两端逻辑状态逐值相等', q.states()[0] == q.states()[1], 'GL/VK 快照不一致')


# ============================ ④ 暂停期画面 == 暂停时刻画面 ============================
print()
print("=== ④. 暂停期画面 == 暂停时刻画面（逐像素）；暂停不跳变 / 恢复真的动 ===")
# 参照对（期望值来源 = **另一条生产路径**：正常推进 0/1 帧的画面）
ref0 = Pair()
g_r0, v_r0 = ref0.frames(0)          # 预热结束那一刻的画面 = 「正常推进 0 帧」
ref1 = Pair()
g_r1, v_r1 = ref1.frames(1)          # 再正常推进 1 个逻辑帧的画面
check('④ 参照前提：正常推进 1 个逻辑帧确实改变了画面（1 帧 != 0 帧 —— 参照对有牙）',
      (not img_eq(g_r0, g_r1)) and (not img_eq(v_r0, v_r1)),
      'GL mae=%.8f / VK mae=%.8f' % (metrics(g_r0, g_r1)[0], metrics(v_r0, v_r1)[0]))

s = Pair()
g_pre, v_pre = s.last
s.pause()
gA = s.gl_frame()
vA = s.vk_frame()
check('④ 暂停瞬间画面 == 暂停前最后一帧画面（按 F9 不得跳变；两端都要成立）',
      img_eq(gA, g_pre) and img_eq(vA, v_pre),
      'GL mae=%.8f max=%.6f / VK mae=%.8f max=%.6f'
      % (metrics(gA, g_pre)[0], metrics(gA, g_pre)[1],
         metrics(vA, v_pre)[0], metrics(vA, v_pre)[1]))
for i in range(10):
    gB = s.gl_frame()
    vB = s.vk_frame()
mA = metrics(gA, gB)
mB = metrics(vA, vB)
check('④ 暂停 10 帧后：两端画面都与暂停瞬间**逐像素相同**（MAE=0 且 MAX=0）',
      img_eq(gA, gB) and img_eq(vA, vB),
      'GL mae=%.8f max=%.6f / VK mae=%.8f max=%.6f' % (mA[0], mA[1], mB[0], mB[1]))
s.resume()
gC = s.gl_frame()
vC = s.vk_frame()
mC = metrics(gA, gC)
mCv = metrics(vA, vC)
check('④ 恢复并跑 1 帧后：两端画面都与暂停瞬间**不同**（证明恢复真的动了）',
      (not img_eq(gA, gC)) and (not img_eq(vA, vC)),
      'GL mae=%.8f max=%.6f / VK mae=%.8f max=%.6f' % (mC[0], mC[1], mCv[0], mCv[1]))
check('④ 恢复首帧 == 参照对「同一状态 + 正常 1 帧」的画面（逐像素；恢复后画面不跳变）',
      img_eq(gC, g_r1) and img_eq(vC, v_r1),
      'GL mae=%.8f / VK mae=%.8f' % (metrics(gC, g_r1)[0], metrics(vC, v_r1)[0]))
print('    （诊断）暂停瞬间画面 vs 参照「正常 0 帧 / 正常 1 帧」：')
print('      GL: vs 0 帧 mae=%.8f / vs 1 帧 mae=%.8f' % (metrics(gA, g_r0)[0],
                                                       metrics(gA, g_r1)[0]))
print('      VK: vs 0 帧 mae=%.8f / vs 1 帧 mae=%.8f' % (metrics(vA, v_r0)[0],
                                                       metrics(vA, v_r1)[0]))


# ============================ ⑤ 单步的画面推进 == 逻辑推进 ============================
print()
print("=== ⑤. 单步的画面推进 == 逻辑推进（== 参照对「正常 1/3 帧」的画面，逐像素） ===")
ref3 = Pair()
g_r3, v_r3 = ref3.frames(3)          # 正常推进 3 个逻辑帧的画面
check('⑤ 参照前提：正常推进 1 / 3 个逻辑帧的画面互不相同（参照对有牙）',
      (not img_eq(g_r1, g_r3)) and (not img_eq(v_r1, v_r3))
      and (not img_eq(g_r0, g_r3)) and (not img_eq(v_r0, v_r3)),
      'GL 1vs3 mae=%.8f / VK 1vs3 mae=%.8f' % (metrics(g_r1, g_r3)[0],
                                               metrics(v_r1, v_r3)[0]))
t = Pair()
t.pause()
gA2 = t.gl_frame()
vA2 = t.vk_frame()
t.step()
gD1 = t.gl_frame()
vD1 = t.vk_frame()
check('⑤ 单步 1 次的画面 == 参照对「正常推进 1 个逻辑帧」的画面（逐像素 —— 恰好 1 个 fixed_dt，'
      '不多不少）',
      img_eq(gD1, g_r1) and img_eq(vD1, v_r1),
      'GL mae=%.8f / VK mae=%.8f' % (metrics(gD1, g_r1)[0], metrics(vD1, v_r1)[0]))
check('⑤ 单步 1 次的画面 != 参照对「正常推进 0 帧」的画面（证明单步不是 0 帧的量）',
      (not img_eq(gD1, g_r0)) and (not img_eq(vD1, v_r0)),
      'GL mae=%.8f / VK mae=%.8f' % (metrics(gD1, g_r0)[0], metrics(vD1, v_r0)[0]))
t.step()
t.gl_frame()
t.vk_frame()
t.step()
gD3 = t.gl_frame()
vD3 = t.vk_frame()
check('⑤ 单步 3 次的画面 == 参照对「正常推进 3 个逻辑帧」的画面（逐像素）',
      img_eq(gD3, g_r3) and img_eq(vD3, v_r3),
      'GL mae=%.8f / VK mae=%.8f' % (metrics(gD3, g_r3)[0], metrics(vD3, v_r3)[0]))
check('⑤ 单步 3 次 != 单步 1 次（画面继续前进，不是停在同一帧）',
      (not img_eq(gD1, gD3)) and (not img_eq(vD1, vD3)),
      'GL mae=%.8f / VK mae=%.8f' % (metrics(gD1, gD3)[0], metrics(vD1, vD3)[0]))


# ============================ ⑥ 两端截图对拍（4 个时刻） ============================
print()
print("=== ⑥. 两端截图对拍：暂停瞬间 / 单步 1 / 单步 3 / 恢复后（MAE<=2e-4，A/B 门口径） ===")
u = Pair()
u.pause()
shots = {}
shots['暂停瞬间'] = (u.gl_frame(), u.vk_frame())
u.step()
shots['单步 1 次后'] = (u.gl_frame(), u.vk_frame())
u.step()
u.gl_frame()
u.vk_frame()
u.step()
shots['单步 3 次后'] = (u.gl_frame(), u.vk_frame())
u.resume()
shots['恢复后'] = (u.gl_frame(), u.vk_frame())
_rows = []
for name, (g, v) in shots.items():
    mae, mx, ncc = metrics(g, v)
    print('    %-12s GL vs VK: MAE=%.8f  MAX=%.6f  NCC=%.6f' % (name, mae, mx, ncc))
    _rows.append((name, mae, mx, ncc))
check('⑥ 4 个时刻两端截图逐像素相等或 MAE<=%.4g 且 NCC>=0.999'
      '（MAE 口径来源 test_ab_gl_vk DEFAULT_GATE）' % MAE_GATE,
      all(r[1] <= MAE_GATE and r[3] >= 0.999 for r in _rows),
      '；'.join('%s MAE=%.8f NCC=%.6f' % (r[0], r[1], r[3]) for r in _rows
               if not (r[1] <= MAE_GATE and r[3] >= 0.999)))
check('⑥ 4 个时刻之间画面确有变化（截图不是同一张图 —— 否则对拍无意义）',
      not img_eq(shots['暂停瞬间'][0], shots['单步 3 次后'][0])
      and not img_eq(shots['单步 3 次后'][0], shots['恢复后'][0]),
      'GL 逐像素比较')


print()
print("=== 汇总 ===")
print('PASS/FAIL 总判定：%s' % ('全绿' if ok else '有 FAIL'))
print('已知差异登记表：%r' % (KNOWN_DIFFS,))
