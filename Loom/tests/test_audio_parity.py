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


"""test_audio_parity.py — P4 面「音频播放状态」两端对拍门（无头，2026-11-19）。

上位判据（人类 2026-11-18，docs/guides/开发要求_后端API一致_JVM模型.md §1.3）：
  「两种后端没有用户可感知的差异……如同 JVM 虚拟机在任何 CPU 上都保证字节码解析效果
    一样，不管选择什么后端对用户脚本的表现一致。」

本门验的是**数据/状态面**，不是真听声音；**不依赖声卡**（见 ⑤ 组）。
六组（同一份场景 + 同一串脚本级调用 → 两端逐项相等，不是"各自为 True"）：
  ① 播放状态机   playing 置 True/False/再 True（= 播/停/暂停/恢复）、换 clip、改音量：
                 两端「音频实例状态」（是否播放中 / 3D 位置 / 循环标志 / 音量）逐项相等；
                 且后端收到的调用序列（play / play_spatial / stop / update_sound_position
                 + 全部参数）逐项相等；并用**独立判据**（pygame 通道占用）核对"真的在播/
                 真的停了"。
  ② 3D 听者同步  同一份场景相机 → 两端 sync_audio_listener 喂给后端的
                 (position, forward, up) 逐项相等，且 = 由场景文件手算的期望表；
                 再把相机走位，看两端是否都跟着变；并验"每逻辑帧同步一次"。
  ③ 每帧更新时序 逻辑帧 8 段里 update_audio 的**位置与调用次数**两端相等（实例级插桩记录
                 实际调用序列，不是只读源码顺序）；N 帧 → 恰好 N 次；绑死模式
                 （设置.json logic_fps<=0 = 用户可配置）下每渲染帧的音频段次数两端相等。
  ④ 暂停期行为   logic_paused 时两端音频段是否继续走（必须同决策）；暂停期置 playing=True
                 不得抢跑也不得积压；恢复首帧恰好 1 个逻辑帧 / 1 次音频段 / 只播 1 次；
                 F10 单步两端各 1 个逻辑帧。
  ⑤ 无音频设备   强制"无设备"（SDL 驱动不可用 = 生产 AudioBackend 的真实降级路径）时两端
                 都不崩、都静默（句柄缓存 None）、脚本 API 返回值相同、状态机照走。
  ⑥ 脚本 API 面  engine.audio.*（load/play/play_sound/stop）+ obj.add_audio_source /
                 remove_audio_source 在两端存在、返回值/副作用一致；「资源不存在」失败
                 路径两端一致；并在**真实注册脚本**的 on_start 里调音频 API（用户脚本最常
                 这么用）看两端表现与脚本健康度。

执行顺序 ①→②→③→④→⑥→⑤：⑤（无设备）要把 SDL 驱动临时改成不可用，放在最后，并在 finally
里恢复驱动 + 重新 init，避免污染其它组的前提（各组独立建 Pair，互不共享后端实例）。

两端生产入口（不拼假音频对象；§5 反模式 8）：
  GL : runtime.PlayerApp(None, 64, 64, ctx=离屏 GL 上下文, scene_data=场景)
       —— 打包播放器（build_entry / game_player / --run 全走它）；音频对象由
          engine.GLEngine.__init__:405 self.audio = AudioSystem() 建；
          逻辑帧 = engine._logic_frame:1146（8 段，含 update_audio:1195/1218）；
          渲染帧 = engine.advance_logic:1424（暂停门控在 :1452）。
  VK : scene_driver.SceneDriver() + load_from_data(场景)
       —— VK 播放器；音频对象惰性建（render/vk/driver.py:916 _ensure_audio）；
          逻辑帧 = scene_driver._logic_frame:883（8 段，含 update_audio:902）；
          渲染帧 = scene_driver.advance_logic:1043（暂停门控在 :1053）。
  两端音频段是**同一份实现**（loom_frame_components.py:54 模块级 update_audio /
  :25 sync_audio_listener），本门验「两端真的都调了、参数同源、结果逐项相等」。

观测手段（只加观测，不绕生产路径）：
  · _AudioSpy —— 把每个属性转给**生产** AudioSystem 的透明代理：存在的属性返回真绑定方法
    （真调用 → 真降级/真播），**缺的属性照样抛与生产逐字相同的 AttributeError**。它不实现
    任何音频语义，只记录「引擎向音频后端要了什么」；保真断言见 〇' 段。
  · 独立判据（反模式 3）："是否播放中"用 pygame 的 Sound.get_num_channels() 读**设备通道
    占用**，不取引擎自报；"是否静默"用生产 AudioBackend 的 _handles 缓存值。
  · 无设备不依赖声卡：LOOM_AUDIO_BACKEND=pygame（audio_backend.py 支持的生产配置）+
    SDL_AUDIODRIVER=dummy（SDL 空驱动，无需声卡即可完整跑 mixer）；⑤ 组把驱动临时改成
    不存在的名字 = 生产 AudioBackend 的真实「无设备」降级分支。

环境前提（只建输入前提，不改任何断言/语义）：
  · LOOM_LOGIC_SYNC=1 —— GL 的异步逻辑线程只在 Qt 宿主（_external_ctx=True）启用
    （render/gl/engine.py:1443 注释：「无头探针/测试直驱 advance_logic 时若也起线程会双驱」）。
    本门是离屏 ctx（_external_ctx=True），故按该注释走同步路径。
  · LOOM_NO_PHYSICS=1 —— 本门只验音频面，用生产开关关掉物理（段序里的物理段仍在）。
  · 本门不注入鼠标/键盘事件 → **不涉及光标落点协议**（P3 的 settle_cursor 不适用）。

已知差异登记表：**必须为空**（KNOWN_DIFFS）。任何「差不多」/阈值/容差都不许。

修前红（2026-11-19，HEAD=7567f34 实测；本门只交门 + 红证据，业务代码一行未改）：
  · P4-1（两端**同样**坏；用户可感知 = 3D 音效根本不播）：
    loom_components.AudioSystem（:1015-1058）**没有** play_spatial / set_listener /
    update_sound_position（只有 load/play/stop/play_sound/shutdown），而
    loom_frame_components.update_audio:71 调 host.audio.play_spatial(...)、
    sync_audio_listener:44 调 host.audio.set_listener(...)。
    后果：category 为 sfx/voice（**默认值 sfx**）且 playing=True 的 AudioSource → 音频段
    抛 AttributeError（GL render/gl/engine.py:1218 / VK render/vk/driver.py:902 一路抛到宿主）；
    set_listener 的 AttributeError 被 sync_audio_listener 的 except 吞掉 → 监听器**永远
    不同步**（静默）。2D（music）路径正常。归属：loom_components.py:1015（AudioSystem 缺
    3 个委托方法）+ loom_frame_components.py:44/71（调用方）。归 P4 新项。
  · P4-2（VK 听者不跟随相机）：sync_audio_listener 的相机输入源两端不同源 —— GL 的
    self.camera 每渲染帧由 render/gl/render.py:1053 apply_orbit_camera() 更新（runtime.py:174
    加载时也调一次）；VK **全仓没有** apply_orbit_camera 调用点（grep 实测 0 处），
    self.camera 恒为 render/vk/driver.py:616 的初始 (0,0,-5)，朝向取 camera_yaw/camera_pitch
    （:617 恒 0.0），而 VK 轨道相机实际用的是 yaw/pitch（render_pose:1257）。→ 即使修好
    P4-1，VK 的听者也钉在 (0,0,-5)、朝向钉在 0/0。归属：render/vk/driver.py:616-619 +
    无 apply_orbit_camera 调用点；共享函数 loom_frame_components.py:34-40 的取源顺序
    （getattr(host,'camera') 优先于 camera_pos）是放大器。
  · P4-3（VK 首帧前 engine.audio 是 None）：GL 在 __init__ 就建 AudioSystem，VK 是
    self.audio = None（render/vk/driver.py:659）+ 首帧 _ensure_audio 惰性建。脚本在 on_start
    里调 self.engine.audio.play_sound(...)（用户脚本最常这么用）→ GL 正常返回 None，
    VK 抛 AttributeError → 引擎把它当坏脚本（_script_broken=True）→ **该脚本在 VK 上
    整局不再运行**。归属：render/vk/driver.py:659。
  · P4-4（绑死模式 VK 没有音频段）：用户设置 logic_fps<=0（core_clock.split_enabled）时
    两端都进「旧绑死模式」。GL 的两条绑死路径都调 update_audio（render/gl/engine.py:1504 /
    render/gl/render.py:1126 _escape_door_step），VK 的 advance_logic:1109-1115 与
    _step_one_logic_frame:1133-1137 **都没有** update_audio → 该配置下 VK 的 AudioSource
    永不播/停（F10 单步同理）。归属：render/vk/driver.py:1109-1115 / :1133-1137。
  以上四条都是「本门红」的证据，**本任务只报告不修**（照 P1/P2/P3 先例按修前红提交）。

修后（2026-11-19，HEAD=788a998 之上）：**105 PASS / 0 FAIL**（修前 100 PASS / 5 FAIL）。
  · **P4-2 已修**（VK 听者跟随轨道相机）：轨道相机眼睛位置的公式抽成**唯一实现**
    `loom_camera.orbit_camera_eye`（GL 的 `CameraMixin.apply_orbit_camera` 与 VK 都调它）；
    VK 新增 `SceneDriver._sync_orbit_camera_state()`（语义/数值与 GL 的 apply_orbit_camera
    逐位一致），在两处调用：`load_from_data` 的轨道分支（= GL runtime.PlayerApp 加载路径
    同位置）与 `advance_logic` 帧首（= GL loom_render._prepare_main_pass 同位置，且在任何
    消费相机的地方之前、暂停分支之前）。VK 因数据结构差异（轨道角度在 `yaw/pitch`、玩家
    相机角度在 `camera_yaw/camera_pitch`，GL 两者共用一组）把轨道角度**镜像**到
    `camera_yaw/camera_pitch` —— 共享的 `sync_audio_listener` 读的正是后者。
    `sync_audio_listener` 的取源顺序**一行未动**（GL 行为零变化），`camera_pos` 里那份
    同公式拷贝改为调共享纯函数（数值不变）。
  · **P4-4 已修**（绑死模式 VK 补音频段）：`advance_logic` 的绑死分支与
    `_step_one_logic_frame` 的无时钟分支各补 `self.update_audio(...)`，位置与 GL 同
    （物理之后、LateUpdate/return 之前）。**以 GL 为准的核实**（`tests/_tmp/
    p44_gl_bound_f10_check.py` 实测）：GL **没有**独立的无时钟单步路径（step_logic_once
    只置 _step_requested，绑死分支不看它，暂停门控也只在 clk is not None 分支里），
    「绑死 + F10 单步」在 GL 上 = 1 个绑死渲染帧 = **1 次音频段**（实测 GL=1），
    故 VK 的无时钟单步分支**也要**调 audio（修前 VK=0）。
  · **两条「锁住缺陷」的结构探针已随修复翻转**（唯一改动的两条既有断言，行为面断言
    一条未动、条数 105 不变、无阈值/容差）：〇 段的 `self.update_audio(` 调用点计数
    5 → 7（VK 1 → 3），以及 `apply_orbit_camera(` 探针改为「公式只有 loom_camera.
    orbit_camera_eye 一份 + scene_driver 有加载/每渲染帧两处同步调用点」。理由：这两条
    探针的标题本身就写着缺陷（P4-2 / P4-4），修好后旧断言的前提被证明为假（反模式 4
    「先证明旧断言错了」），留着它们会把「已修的缺陷」写成「仍然存在」（反模式 10）。

未核（本门不覆盖，留痕）：
  · 设备级 3D 声像（左右声道/距离衰减曲线）：需 game_audio(miniaudio) + 真声卡；本门固定
    LOOM_AUDIO_BACKEND=pygame 以保证无设备可跑 → 3D **参数面**（位置/距离/衰减/监听器）
    已验，设备级声像**未核**。
  · 播放进度（秒）：两端生产代码都没有该 API（AudioSystem / AudioBackend 均无 get_pos /
    get_ticks；pygame 后端也未暴露），故本门以「3D 空间位置」作为位置面；进度秒 = 未核
    （两端均无该 API，不是两端差异）。
  · game_audio 后端的 per-file 回退路径（ogg/opus → pygame）未核（需该库 + 声卡）。
"""
import json
import math
import os
import struct
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # Loom/
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_DIALOG'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PHYSICS'] = '1'        # 本门只验音频面（生产开关）
os.environ['LOOM_LOGIC_SYNC'] = '1'        # 无头直驱 advance_logic（见文件头「环境前提」）
os.environ['SDL_AUDIODRIVER'] = 'dummy'    # SDL 空驱动：无需声卡即可跑完整 mixer
os.environ['LOOM_AUDIO_BACKEND'] = 'pygame'   # 生产支持的音频后端之一（无设备可跑）
os.environ.setdefault('LOOM_USER_ROOT', tempfile.mkdtemp(prefix='loom_p4_userroot_'))

import moderngl                                                  # noqa: E402
import pygame                                                    # noqa: E402

import loom_components                                           # noqa: E402
import loom_frame_components as LFC                              # noqa: E402
import runtime                                                   # noqa: E402  GL 打包播放器（生产入口）
import render.vk.driver as SD                                        # noqa: E402  VK 播放器（生产入口）
import sceneio                                                   # noqa: E402
from loom_components import AudioSystem                          # noqa: E402  生产音频门面
from scripts import Script, register                             # noqa: E402  脚本生产注册路径

ok = True
KNOWN_DIFFS = []        # 已知差异登记表：必须为空；发现差异 = 红并报告，不许登记糊过去
FRAME_DT = 1.0 / 60.0


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def seq_check(title, rows):
    """rows = [(label, gl值, vk值), ...]：逐行打 GL vs VK 对照表并比对。"""
    bad = [(lb, g, v) for (lb, g, v) in rows if g != v]
    for lb, g, v in rows:
        print('    %-34s GL=%-46s VK=%s' % (lb, g, v))
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


print("=== 〇. 结构：音频段唯一实现 / 两端生产调用点 / 音频门面唯一 / 历史名 ===")
_sync_defs = _grep_prod('def sync_audio_listener')
check('结构：sync_audio_listener 只由 loom_frame_components.py 实现（其它生产文件 0 处）',
      [p for (p, _l) in _sync_defs] == ['loom_frame_components.py'], _sync_defs)
_ua_defs = _grep_prod('def update_audio')
check('结构：update_audio 的定义恰好 3 处（loom_frame_components 的模块级函数 + '
      'FrameComponentMixin 方法，scene_driver 的 VK 方法）—— 没有第三份实现',
      sorted(p for (p, _l) in _ua_defs) == ['loom_frame_components.py',
                                            'loom_frame_components.py',
                                            'render/vk/driver.py'], _ua_defs)
for _hist in ('def _update_audio', 'def update_audio_impl', 'def _apply_audio',
              'def _sync_audio_listener_impl', 'def sync_listener'):
    _h = _grep_prod(_hist)
    check('结构：历史名/拷贝名 %r 在全部生产文件里不存在' % _hist, not _h, _h[:4])
src_has('loom_frame_components.py', 'return update_audio(self, dt)', True,
        'GL 的 FrameComponentMixin.update_audio 转调模块级共享实现（:111）')
src_has('loom_frame_components.py', 'return sync_audio_listener(self)', True,
        'GL 的 _sync_audio_listener 转调模块级共享实现（:103）')
src_has('render/vk/driver.py', 'return _lfc.update_audio(self, dt)', True,
        'VK 调的是同一份 loom_frame_components.update_audio（:943）')
src_has('render/vk/driver.py', 'return _lfc.sync_audio_listener(self)', True,
        'VK 的 _sync_audio_listener 也是同一份（:937）')
_ua_calls = _grep_prod('self.update_audio(')
# 2026-11-19 (P4-4 修复后): VK 由 1 处变 3 处 —— 逻辑帧 + **绑死分支** +
#   **无时钟单步分支**（后两处是本项修法）。本探针由「锁住缺陷」翻转为「锁住修复」:
#   条数不许再变少（少一处 = 又漏了一条绑死路径），也不许多（多一处 = 音频段重复跑）。
check('结构：self.update_audio( 的生产调用点恰好 7 处（GL: engine 逻辑帧 2 + 绑死 1 + '
      'loom_render 绑死 1；VK: scene_driver 逻辑帧 1 + 绑死 1 + 无时钟单步 1）',
      sorted(p for (p, _l) in _ua_calls) == ['render/gl/engine.py', 'render/gl/engine.py', 'render/gl/engine.py',
                                             'render/gl/render.py', 'render/vk/driver.py',
                                             'render/vk/driver.py', 'render/vk/driver.py'],
      _ua_calls)
_as_cls = _grep_prod('class AudioSystem')
check('结构：class AudioSystem 只在 loom_components.py（唯一音频门面）',
      [p for (p, _l) in _as_cls] == ['loom_components.py'], _as_cls)
_ab_cls = _grep_prod('class AudioBackend')
check('结构：class AudioBackend 只在 audio_backend.py（唯一设备后端）',
      [p for (p, _l) in _ab_cls] == ['audio_backend.py'], _ab_cls)
for _m in ('def play_spatial', 'def set_listener', 'def update_sound_position'):
    _h = _grep_prod(_m)
    check('结构：%s 只有 audio_backend.py 一份实现（AudioSystem 必须委托它）' % _m,
          [p for (p, _l) in _h] == ['audio_backend.py'], _h)
_ps = _grep_prod('def play_sound')
check('结构：def play_sound 只在 loom_components.py（两端同一个函数对象）',
      [p for (p, _l) in _ps] == ['loom_components.py'], _ps)
_ss = _grep_prod('def stop_sound')
check('结构：def stop_sound 在生产代码里 0 处（两端都没有这个名字 = 同一 API 面）',
      not _ss, _ss)
_aoc = _grep_prod('apply_orbit_camera(')
_vk_aoc = [h for h in _aoc if h[0].startswith('scene_driver')]
# 2026-11-19 (P4-2 修复后): VK **仍然**没有 apply_orbit_camera() 调用点 —— 它复用
#   的是同一个纯函数（loom_camera.orbit_camera_eye），不是 GL 那个读 camera_yaw/
#   camera_distance 的 mixin 方法（VK 的轨道角度在 self.yaw/self.pitch，字段不同构）。
#   本探针由「锁住缺陷」翻转为「锁住修复」: 公式只许有一份实现，且 VK 的
#   self.camera 必须由「加载 + 每渲染帧」两处同步调用合成。
_sync_aoc = _grep_prod('self._sync_orbit_camera_state()')
_eye_defs = _grep_prod('def orbit_camera_eye')
check('结构：VK 的 self.camera 由轨道相机合成（P4-2 已修）—— 公式只有 loom_camera.'
      'orbit_camera_eye 一份，scene_driver 有「加载 + 每渲染帧」两处同步调用点',
      not _vk_aoc
      and [p for (p, _l) in _eye_defs] == ['loom_camera.py']
      and sorted(p for (p, _l) in _sync_aoc) == ['render/vk/driver.py', 'render/vk/driver.py'],
      (_vk_aoc, _eye_defs, _sync_aoc))
src_has('render/gl/render.py', 'self.apply_orbit_camera()', True,
        'GL 每渲染帧把轨道相机合成到 self.camera（:1053，听者的输入源）')
src_has('render/vk/driver.py', 'self.audio = None', True,
        'VK 的音频对象初值 None（render/vk/driver.py:659，P4-3）')
src_has('render/gl/engine.py', 'self.audio = AudioSystem()', True,
        'GL 在 __init__ 就建好音频门面（render/gl/engine.py:405）')
check('已知差异登记表为空（不许登记任何容差）', not KNOWN_DIFFS, KNOWN_DIFFS)


# ============================ 夹具（生产入口 + 生产构造式） ============================

_GL_CTX = [None]
_WAV = {}


def _gl_ctx():
    if _GL_CTX[0] is None:
        _GL_CTX[0] = moderngl.create_standalone_context(require=330)
    return _GL_CTX[0]


def _mk_wav(name, secs, tone):
    """在 tests/_tmp/ 下造一个真 wav（夹具落点协议：只写 _tmp；gitignore 已忽略）。"""
    d = os.path.join(HERE, '_tmp')
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    if not os.path.exists(p):
        with wave.open(p, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            n = int(22050 * secs)
            w.writeframes(b''.join(struct.pack('<h', tone if (i // 10) % 2 else -tone)
                                   for i in range(n)))
    return p


_WAV['a'] = _mk_wav('p4_tone_a.wav', 0.5, 2000)
_WAV['b'] = _mk_wav('p4_tone_b.wav', 0.8, 3000)
_WAV['c'] = _mk_wav('p4_tone_c.wav', 0.3, 1000)
# 专用预加载音效（只用来让两端生产 AudioBackend 的惰性初始化跑起来；不挂任何物体，
# 因此不会污染 ①/⑤ 的句柄缓存对照表 —— 两端都有同一条，逐项相等不受影响）
_WAV['pre'] = _mk_wav('p4_tone_pre.wav', 0.2, 500)
_NOPE = os.path.join(HERE, '_tmp', 'p4_does_not_exist.wav')


class _Noop(Script):
    """占位脚本：让两端 _logic_prep 都产出碰撞对列表（否则 GL 派发 / VK 不派发，③ 组的
    段序会差一个 dispatch 段 —— 那是碰撞事件面的事，不属本门）。"""
    script_id = 'p4_noop_probe'

    def update(self, dt):
        pass


register(_Noop)

API_LOG = []          # ⑥ 组：脚本里调音频 API 的结果


class _AudioApiProbe(Script):
    """⑥ 组：**不吞异常**的真实脚本 —— 用户脚本在 on_start 里播一次性音效就是这样写的。"""
    script_id = 'p4_audio_api_raw'

    def on_start(self):
        API_LOG.append(('raw.on_start',))
        self.engine.audio.play_sound(_NOPE)      # 资源不存在：生产语义 = 静默返回 None
        API_LOG.append(('raw.on_start.done',))

    def update(self, dt):
        API_LOG.append(('raw.update',))


class _AudioApiProbeCaught(Script):
    """⑥ 组：逐项 catch 的探针 —— 用于比对两端「返回值 / 异常类型」。"""
    script_id = 'p4_audio_api_caught'

    def on_start(self):
        for label, fn in (
                ('play_sound(不存在)', lambda: self.engine.audio.play_sound(_NOPE)),
                ('stop(不存在)', lambda: self.engine.audio.stop(_NOPE)),
                ('load(不存在)', lambda: self.engine.audio.load(_NOPE)),
                ('play_sound(真文件)', lambda: self.engine.audio.play_sound(_WAV['a'], 0.4))):
            try:
                r = fn()
                API_LOG.append(('caught', label, 'ok', r))
            except Exception as e:
                API_LOG.append(('caught', label, 'raise', type(e).__name__))


register(_AudioApiProbe)
register(_AudioApiProbeCaught)


def _obj(gid, name, pos, clip=None, category='sfx', loop=False, volume=1.0,
         min_d=1.0, max_d=500.0, rolloff=1.0, scripts=None):
    d = {'id': gid, 'name': name, 'type': 'cube', 'params': {'size': 1},
         'position': list(pos), 'rotation': [0, 0, 0], 'scale': [1, 1, 1],
         'color': '#ffffff', 'visible': True}
    if clip is not None:
        d['audio_source'] = {'clip': clip, 'loop': loop, 'volume': volume,
                             'category': category, 'min_distance': min_d,
                             'max_distance': max_d, 'rolloff': rolloff}
    if scripts:
        d['scripts'] = [{'id': s, 'vars': {}} for s in scripts]
    return d


SCENE_CAM = {'target': [1.0, 2.0, 3.0], 'distance': 12.0, 'yaw': 0.9, 'pitch': -0.4}
CAM_OBJ = {'id': 'camP4', 'name': 'camP4', 'position': [0.0, 1.6, -3.0],
           'yaw': 90.0, 'pitch': 0.0, 'roll': 0.0, 'fov': 60.0}


def scene_audio(active_camera=False):
    """两端同一份场景：1 个 2D 音乐源 / 1 个 3D sfx 源 / 1 个 3D voice 源 /
    1 个无音频源对照（挂占位脚本，让两端都派发碰撞段）。位置取整数，两端
    world_position 逐位相同（夹具保真断言在 〇' 段）。"""
    return {
        'version': sceneio.SCENE_VERSION,
        'camera': dict(SCENE_CAM),
        'gravity': -9.8,
        'skybox': None,
        'objects': [
            _obj('g_music', 'music_one', (0, 0, 0), _WAV['a'], 'music',
                 loop=True, volume=0.5),
            _obj('g_sfx', 'sfx_one', (3, 0, 0), _WAV['b'], 'sfx',
                 loop=False, volume=0.8, min_d=1.0, max_d=50.0, rolloff=2.0),
            _obj('g_voice', 'voice_one', (0, 2, 0), _WAV['c'], 'voice',
                 loop=False, volume=1.0),
            _obj('g_silent', 'silent_one', (0, 0, 2), None,
                 scripts=['p4_noop_probe']),
        ],
        'lights': [], 'materials': [],
        'cameras': ([dict(CAM_OBJ)] if active_camera else []),
        'active_camera': ('camP4' if active_camera else None),
    }


def new_gl(scene):
    ctx = _gl_ctx()
    fbo = ctx.framebuffer(
        color_attachments=[ctx.renderbuffer((64, 64), components=4)],
        depth_attachment=ctx.depth_renderbuffer((64, 64)))
    e = runtime.PlayerApp(None, 64, 64, ctx=ctx, scene_data=scene)
    e._external_fb = fbo
    return e


def new_vk(scene):
    d = SD.SceneDriver()
    d.load_from_data(scene)
    return d


class _AudioSpy:
    """透明代理：属性一律转给**生产** AudioSystem；只记录「引擎调了哪些方法 + 参数」。

    它**不实现任何音频语义**：存在的属性返回真绑定方法（真调用 → 真降级/真播），缺的属性
    照样抛与生产逐字相同的 AttributeError。所以它只加观测，不绕生产路径（保真断言见 〇'）。
    """

    def __init__(self, real):
        object.__setattr__(self, '_real', real)
        object.__setattr__(self, 'attempts', [])

    def __getattr__(self, name):
        real = object.__getattribute__(self, '_real')
        att = object.__getattribute__(self, 'attempts')
        try:
            fn = getattr(real, name)
        except AttributeError:
            def _missing(*a, **k):
                att.append((name, a, k, 'MISSING'))
                raise AttributeError("'%s' object has no attribute '%s'"
                                     % (type(real).__name__, name))
            return _missing
        if not callable(fn):
            return fn

        def _wrapped(*a, **k):
            att.append((name, a, k, 'OK'))
            return fn(*a, **k)
        return _wrapped


class Pair:
    """一对生产后端（同一份场景），各自的生产音频段入口。"""

    def __init__(self, scene=None):
        scene = scene if scene is not None else scene_audio()
        self.gl = new_gl(scene)
        self.vk = new_vk(scene)
        # P4-3 取证：首帧前的脚本 API 面（GL 已建 / VK 还是 None）
        self.api_before_first_frame = [
            sorted(n for n in dir(self.gl.audio) if not n.startswith('_'))
            if self.gl.audio is not None else None,
            sorted(n for n in dir(self.vk.audio) if not n.startswith('_'))
            if self.vk.audio is not None else None,
        ]
        for h in (self.gl, self.vk):
            h.is_playing = True
            h.parallel = None
            h._collision_pool = None
            h._frame_pool = None
        # 预热一帧：VK 的生产惰性 _ensure_audio 在这一帧里建出 AudioSystem
        self.gl._logic_frame(FRAME_DT)
        self.vk._logic_frame(FRAME_DT)
        # 夹具前提：用一次**脚本级生产调用** load() 让两端 AudioBackend 的惰性初始化跑起来
        # （否则 _backend 恒 None，"句柄缓存 / 设备通道"这两个独立判据无从观测）。
        # 用专用音效，不挂任何物体 —— 两端各多一条同值记录，不影响逐项相等。
        for h in (self.gl, self.vk):
            h.audio.load(_WAV['pre'])
        self.spy = {'GL': _AudioSpy(self.gl.audio), 'VK': _AudioSpy(self.vk.audio)}
        self.gl.audio = self.spy['GL']
        self.vk.audio = self.spy['VK']

    def logic_frame(self, dt=FRAME_DT):
        """两端各跑 1 个逻辑帧（生产入口 _logic_frame）。返回两端异常信息。"""
        out = []
        for h in (self.gl, self.vk):
            try:
                h._logic_frame(dt)
                out.append(None)
            except Exception as e:
                out.append((type(e).__name__, str(e)))
        return out

    def clear_ops(self):
        for s in self.spy.values():
            s.attempts.clear()

    def _idmap(self, host):
        return {id(m.audio_source): m.name for m in host.models
                if getattr(m, 'audio_source', None) is not None}

    def ops(self, skip=('set_listener',)):
        """两端「引擎 → 音频后端」调用序列（owner 归一成模型名，路径归一成 basename）。

        skip 默认排除 set_listener —— 听者同步是 ② 组的观测面（每逻辑帧都发生），
        混进 ① 的播放状态机表只会变成噪音；② 组单独取 _listener_attempts()。
        """
        out = []
        for side, h in (('GL', self.gl), ('VK', self.vk)):
            idmap = self._idmap(h)
            lst = []
            for (name, args, kw, status) in self.spy[side].attempts:
                if name in skip:
                    continue
                a2 = []
                for v in args:
                    if isinstance(v, str):
                        a2.append(os.path.basename(v))
                    elif isinstance(v, tuple):
                        a2.append(tuple(v))
                    else:
                        a2.append(v)
                k2 = tuple(sorted((k, idmap.get(v, v)) for k, v in kw.items()))
                lst.append((name, tuple(a2), k2, status))
            out.append(tuple(lst))
        return out

    def comp_state(self):
        """两端「音频实例状态」：是否播放中 / 3D 位置 / 循环 / 音量 / 类别 / 缓存键。"""
        out = []
        for h in (self.gl, self.vk):
            st = {}
            for m in h.models:
                a = getattr(m, 'audio_source', None)
                if a is None:
                    st[m.name] = None
                    continue
                st[m.name] = {
                    'playing': bool(a.playing),
                    'loop': bool(a.loop),
                    'volume': float(a.volume),
                    'category': a.category,
                    'clip': (os.path.basename(a.clip) if a.clip else None),
                    'key': (None if a._key is None
                            else (os.path.basename(a._key[0]), bool(a._key[1]))),
                    'last_pos': tuple(getattr(a, '_last_pos', ()) or ()),
                    'min_d': float(a.min_distance),
                    'max_d': float(a.max_distance),
                    'rolloff': float(a.rolloff),
                }
            out.append(st)
        return out

    def backend_state(self):
        """生产 AudioBackend 的句柄缓存（= 「静默 / 真的加载了」的独立判据）。"""
        out = []
        for h in (self.gl, self.vk):
            b = getattr(h.audio, '_backend', None)
            if b is None:
                out.append({'mode': None, 'handles': ()})
                continue
            idmap = self._idmap(h)
            ent = {}
            for (path, owner), v in b._handles.items():
                ent[(idmap.get(owner, 'owner=%r' % (owner,)),
                     os.path.basename(path))] = (None if v is None else v['kind'])
            out.append({'mode': b.mode, 'handles': tuple(sorted(ent.items()))})
        return out

    def device_channels(self):
        """**独立判据**（反模式 3）：读 pygame 通道占用，不取引擎自报的 playing。"""
        out = []
        for h in (self.gl, self.vk):
            b = getattr(h.audio, '_backend', None)
            idmap = self._idmap(h)
            ch = {}
            if b is not None:
                for (path, owner), v in b._handles.items():
                    key = (idmap.get(owner, 'owner=%r' % (owner,)),
                           os.path.basename(path))
                    ch[key] = (int(v['obj'].get_num_channels())
                               if v is not None and v['kind'] == 'py' else None)
            out.append(tuple(sorted(ch.items())))
        return out

    def model(self, name):
        return ([m for m in self.gl.models if m.name == name][0],
                [m for m in self.vk.models if m.name == name][0])

    def set_field(self, name, **kw):
        """同一串脚本级操作：对两端同名物体的 audio_source 赋同一批字段。"""
        for m in self.model(name):
            a = m.audio_source
            for k, v in kw.items():
                setattr(a, k, v)

    def shutdown(self):
        for h in (self.gl, self.vk):
            try:
                real = getattr(h.audio, '_real', h.audio)
                if real is not None:
                    real.shutdown()
            except Exception:
                pass


print()
print("=== 〇'. 夹具保真：两端都是生产类 + 生产构造式 + 生产音频门面 ===")
_p0 = Pair()
check("GL 端是打包播放器 runtime.PlayerApp（生产入口）",
      type(_p0.gl) is runtime.PlayerApp, type(_p0.gl).__name__)
check("VK 端是 scene_driver.SceneDriver（生产入口）",
      type(_p0.vk) is SD.SceneDriver, type(_p0.vk).__name__)
check("两端音频门面都是生产 loom_components.AudioSystem（不是测试自搭的假音频对象）",
      type(_p0.spy['GL']._real) is AudioSystem
      and type(_p0.spy['VK']._real) is AudioSystem,
      (type(_p0.spy['GL']._real).__name__, type(_p0.spy['VK']._real).__name__))
check("观测代理保真：存在的属性转发到**生产**绑定方法（load 真的进生产 AudioBackend）",
      _p0.spy['GL'].load(_WAV['a']) is not None
      and (_WAV['a'], None) in _p0.spy['GL']._real._backend._handles,
      'load 返回值=%r' % (_p0.spy['GL'].load(_WAV['a']),))
# P4-1 修后（2026-11-19）：play_spatial 已是 AudioSystem 的公开方法 —— 修前它只是本断言
# 借用的「缺失方法」示例。这里换成**永远不存在**的名字，断言的意图与强度完全不变：验的是
# 「spy 不替生产对象兜底，异常文案与生产逐字相同」，而不是「play_spatial 缺失」。
_MISSING_NAME = 'p4_no_such_audio_method'
_msg_real = _msg_spy = None
try:
    getattr(_p0.spy['GL']._real, _MISSING_NAME)
except AttributeError as e:
    _msg_real = str(e)
try:
    getattr(_p0.spy['GL'], _MISSING_NAME)('x', (0, 0, 0))
except AttributeError as e:
    _msg_spy = str(e)
check("观测代理保真：spy 对缺失方法的异常文案 == 生产对象自己的文案（不替生产兜底）",
      _msg_real is not None and _msg_spy == _msg_real, (_msg_real, _msg_spy))
check("两端 world_position 逐位相同（3D 位置面的输入前提；整数坐标 + 无父链）",
      [tuple(_p0.gl.world_position(m)) for m in _p0.gl.models]
      == [tuple(_p0.vk.world_position(m)) for m in _p0.vk.models],
      ([tuple(_p0.gl.world_position(m)) for m in _p0.gl.models],
       [tuple(_p0.vk.world_position(m)) for m in _p0.vk.models]))
check("两端场景装配出同名同序的 4 个物体（同一份场景 = 同一串用户内容）",
      [m.name for m in _p0.gl.models] == [m.name for m in _p0.vk.models]
      == ['music_one', 'sfx_one', 'voice_one', 'silent_one'],
      ([m.name for m in _p0.gl.models], [m.name for m in _p0.vk.models]))
check("两端 audio_source 字段由同一份场景装配（clip/loop/volume/category 逐项相等）",
      _p0.comp_state()[0] == _p0.comp_state()[1],
      (_p0.comp_state()[0], _p0.comp_state()[1]))
_bs0 = _p0.backend_state()
check("音频后端是生产配置 LOOM_AUDIO_BACKEND=pygame 且两端都真的初始化成功（无设备可跑）",
      _bs0[0]['mode'] == _bs0[1]['mode'] == 'pygame', _bs0)
check("夹具前提：预加载音效让两端生产 AudioBackend 都真的缓存到句柄（惰性初始化已跑）",
      dict(_bs0[0]['handles']).get(('owner=None', 'p4_tone_pre.wav'), 'absent') == 'py'
      and dict(_bs0[1]['handles']).get(('owner=None', 'p4_tone_pre.wav'), 'absent') == 'py',
      _bs0)
_p0.shutdown()


# ============================ ① 播放状态机 ============================
print()
print("=== ①. 播放状态机：播/停/暂停/恢复/换 clip/改音量 → 两端实例状态 + 后端调用逐项相等 ===")
p = Pair()
rows = []


def step1(label, **fields):
    """一帧：先按同一串脚本级操作改两端字段，再各跑 1 个逻辑帧。"""
    if fields:
        p.set_field(fields.pop('_target'), **fields)
    p.clear_ops()
    errs = p.logic_frame()
    o = p.ops()
    c = p.comp_state()
    d = p.device_channels()
    b = p.backend_state()
    rows.append((label + ' ·后端调用', o[0], o[1]))
    rows.append((label + ' ·实例状态', c[0], c[1]))
    rows.append((label + ' ·句柄缓存', b[0]['handles'], b[1]['handles']))
    rows.append((label + ' ·设备通道数', d[0], d[1]))
    rows.append((label + ' ·帧内异常', errs[0], errs[1]))
    return o, c, d, b, errs


o, c, d, b, errs = step1('A 基线（无 playing）')
check('① 基线：两端都不播、后端调用都为空',
      o[0] == o[1] == () and d[0] == d[1]
      and all(v == 0 for (_k, v) in d[0] if v is not None), (o, d))

o, c, d, b, errs = step1('B music.playing=True（播）', _target='music_one', playing=True)
check('① 播：两端都向同一份后端要了 2D 播放（play(wav, loop=True, volume=0.5, '
      'owner=组件) —— 位置参数形式与生产一致）',
      o[0] == o[1] == (('play', ('p4_tone_a.wav', True, 0.5),
                        (('owner', 'music_one'),), 'OK'),),
      (o[0], o[1]))
check('① 播：**独立判据**（pygame 通道）两端都真的在播（>0 通道）',
      dict(d[0])[('music_one', 'p4_tone_a.wav')] > 0
      and dict(d[1])[('music_one', 'p4_tone_a.wav')] > 0, d)
check('① 播：两端实例状态（key=已播标志 / loop / volume）逐项相等',
      c[0]['music_one']['key'] == c[1]['music_one']['key'] == ('p4_tone_a.wav', True),
      (c[0]['music_one'], c[1]['music_one']))

o, c, d, b, errs = step1('C 再跑一帧（状态未变）')
check('① 去重：playing 未变时两端都不重复 play（0 次调用）', o[0] == o[1] == (), o)

o, c, d, b, errs = step1('D music.playing=False（停）', _target='music_one', playing=False)
check('① 停：两端都向同一份后端要了 stop(wav, owner)',
      o[0] == o[1] == (('stop', ('p4_tone_a.wav',), (('owner', 'music_one'),), 'OK'),),
      (o[0], o[1]))
check('① 停：**独立判据**两端都真的停了（0 通道）',
      dict(d[0])[('music_one', 'p4_tone_a.wav')] == 0
      and dict(d[1])[('music_one', 'p4_tone_a.wav')] == 0, d)

o, c, d, b, errs = step1('E music.playing=True（恢复）', _target='music_one', playing=True)
check('① 恢复：两端都重新 play 一次（且只一次）',
      o[0] == o[1] and len(o[0]) == 1 and o[0][0][0] == 'play', o)
check('① 恢复：**独立判据**两端又真的在播',
      dict(d[0])[('music_one', 'p4_tone_a.wav')] > 0
      and dict(d[1])[('music_one', 'p4_tone_a.wav')] > 0, d)

o, c, d, b, errs = step1('F music.volume=0.3（播放中改音量）', _target='music_one', volume=0.3)
check('① 改音量：两端实例状态都是 volume=0.3',
      c[0]['music_one']['volume'] == c[1]['music_one']['volume'] == 0.3,
      (c[0]['music_one']['volume'], c[1]['music_one']['volume']))
rows.append(('F 备注：播放中改音量两端都不重播（既有语义，非两端差异）',
             len(o[0]), len(o[1])))

o, c, d, b, errs = step1('G music.clip=另一个 wav（播放中换 clip）', _target='music_one',
                         clip=_WAV['c'])
check('① 换 clip：两端都按新 clip 重新 play（key 变化触发；volume 用当时的 0.3）',
      o[0] == o[1] and len(o[0]) == 1
      and o[0][0] == ('play', ('p4_tone_c.wav', True, 0.3), (('owner', 'music_one'),), 'OK'),
      (o[0], o[1]))
check('① 换 clip：两端 key 都变成新 clip',
      c[0]['music_one']['key'] == c[1]['music_one']['key'] == ('p4_tone_c.wav', True),
      (c[0]['music_one']['key'], c[1]['music_one']['key']))

o, c, d, b, errs = step1('H sfx.playing=True（3D 音效）', _target='sfx_one', playing=True)
check('① 3D 播：两端音频段都**不抛异常**（P4-1 修后（原缺陷：AudioSystem 缺 play_spatial））',
      errs[0] is None and errs[1] is None, errs)
check('① 3D 播：两端都**成功**向同一份后端要了 3D 播放 play_spatial'
      '(位置/距离/衰减/循环/音量)',
      o[0] == o[1] and len(o[0]) == 1 and o[0][0][0] == 'play_spatial'
      and o[0][0][3] == 'OK'
      and o[0][0][2] == (('loop', False), ('max_distance', 50.0), ('min_distance', 1.0),
                         ('owner', 'sfx_one'), ('rolloff', 2.0), ('volume', 0.8)),
      (o[0], o[1]))
check('① 3D 播：两端实例状态（_last_pos = 物体世界位置）逐项相等且 = (3.0,0.0,0.0)',
      c[0]['sfx_one']['last_pos'] == c[1]['sfx_one']['last_pos'] == (3.0, 0.0, 0.0),
      (c[0]['sfx_one']['last_pos'], c[1]['sfx_one']['last_pos']))

for h in (p.gl, p.vk):
    [m for m in h.models if m.name == 'sfx_one'][0].position = loom_components.Point3D(5.0, 0.0, 0.0)
o, c, d, b, errs = step1('I sfx 物体移动到 x=5（3D 跟随）')
check('① 3D 移动：两端音频段都不抛异常（P4-1 同一根因）',
      errs[0] is None and errs[1] is None, errs)
check('① 3D 移动：两端都**成功**向同一份后端要了 update_sound_position(新位置)',
      o[0] == o[1] and len(o[0]) == 1 and o[0][0][0] == 'update_sound_position'
      and o[0][0][3] == 'OK'
      and o[0][0][1] == ('p4_tone_b.wav', (5.0, 0.0, 0.0)), (o[0], o[1]))

o, c, d, b, errs = step1('J sfx.playing=False（3D 停）', _target='sfx_one', playing=False)
# 2026-11-19（P1-5）：本行原括注写的是**修前**状态（「P4-1 让 play_spatial 抛 -> _key 不推进
# -> 不产生 stop」），与修后事实不符（反模式 10）。P4-1 修好后 play_spatial 已是
# AudioSystem 的公开方法，_key 照常推进，两端**都**产生同一条 stop：
#   GL=('stop', ('p4_tone_b.wav',), (('owner', 'sfx_one'),), 'OK')
#   VK=('stop', ('p4_tone_b.wav',), (('owner', 'sfx_one'),), 'OK')
# 只改文案，check() 的表达式一字未动。
check('① 3D 停：两端表现逐项相等（P4-1 修后：play_spatial 可用 → _key 照常推进 → '
      '两端都产生同一条 stop；两端同）',
      o[0] == o[1] and errs[0] is None and errs[1] is None
      and c[0]['sfx_one']['key'] == c[1]['sfx_one']['key'] == ('p4_tone_b.wav', False),
      (o[0], o[1], errs, c[0]['sfx_one']['key'], c[1]['sfx_one']['key']))
seq_check('① 播放状态机：后端调用 / 实例状态 / 句柄缓存 / 设备通道 / 帧内异常，两端逐项相等',
          rows)
p.shutdown()


# ============================ ② 3D 听者同步 ============================
print()
print("=== ②. 3D 听者同步：相机 → 两端 set_listener(位置/朝向/上方向) 逐项相等且 = 期望表 ===")


def _orbit_eye(cam):
    """由场景相机块手算听者期望值（不取自任何一端 = 防「两端一起错」）。"""
    yaw, pitch, dist = cam['yaw'], cam['pitch'], cam['distance']
    t = cam['target']
    ez = (math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch))
    pos = (t[0] - dist * ez[0], t[1] - dist * ez[1], t[2] - dist * ez[2])
    fwd = (-ez[0], -ez[1], -ez[2])
    ey = (-math.sin(yaw) * math.sin(pitch), math.cos(pitch),
          -math.cos(yaw) * math.sin(pitch))
    return pos, fwd, ey


def _cam_basis_expected(cam):
    """由场景相机对象手算（无父链）：位置 = cam.position，前向 = -ez，上 = ey。"""
    yaw, pitch = math.radians(cam['yaw']), math.radians(cam['pitch'])
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    ey = (-sy * sp, cp, -cy * sp)
    ez = (sy * cp, sp, cy * cp)
    pos = tuple(float(v) for v in cam['position'])
    return pos, (-ez[0], -ez[1], -ez[2]), ey


def _listener_attempts(pair):
    out = []
    for side in ('GL', 'VK'):
        out.append([a for a in pair.spy[side].attempts if a[0] == 'set_listener'])
    return out


def _lt(att):
    return [(tuple(a[1][0]), tuple(a[1][1]), tuple(a[1][2]), a[3]) for a in att]


p = Pair(scene_audio(active_camera=True))
p.clear_ops()
p.logic_frame()
rows = []
att = _listener_attempts(p)
rows.append(('②a set_listener 尝试次数', len(att[0]), len(att[1])))
check('②a 两端真的都调了 sync_audio_listener（每个逻辑帧各 1 次）',
      len(att[0]) == len(att[1]) == 1, (len(att[0]), len(att[1])))
_exp_a = _cam_basis_expected(CAM_OBJ)
_got_a, _vkt_a = _lt(att[0]), _lt(att[1])
rows.append(('②a GL 听者', _got_a, _vkt_a))
check('②a 玩家相机路径：两端 (位置/前向/上方向) 逐项相等且 = 场景相机手算期望表',
      bool(_got_a) and _got_a == _vkt_a and _got_a[0][:3] == _exp_a,
      (_got_a, _vkt_a, _exp_a))
check('②a 玩家相机路径：两端 set_listener 都**真的生效**（不抛 AttributeError，P4-1）',
      bool(_got_a) and _got_a[0][3] == 'OK' and _vkt_a[0][3] == 'OK',
      (_got_a[0][3] if _got_a else None, _vkt_a[0][3] if _vkt_a else None))
for h in (p.gl, p.vk):
    cam = h.find_camera(h.active_camera)
    cam.position = loom_components.Point3D(7.0, 3.0, -1.0)
    h.apply_camera(cam)
p.clear_ops()
p.logic_frame()
att = _listener_attempts(p)
_got_b, _vkt_b = _lt(att[0]), _lt(att[1])
rows.append(('②a 相机走位后 GL 听者', _got_b, _vkt_b))
check('②a 相机走位后：两端听者位置都跟着相机变（逐项相等且 = 新相机位置）',
      bool(_got_b) and _got_b == _vkt_b and _got_b[0][0] == (7.0, 3.0, -1.0),
      (_got_b, _vkt_b))
seq_check('②a 玩家相机路径：set_listener 参数 + 是否生效，两端逐项相等', rows)
p.shutdown()

print()
p = Pair(scene_audio(active_camera=False))
p.clear_ops()
p.logic_frame()
att = _listener_attempts(p)
_exp_b = _orbit_eye(SCENE_CAM)
_got_c, _vkt_c = _lt(att[0]), _lt(att[1])
rows = [('②b 轨道相机 ·GL 听者', _got_c, _vkt_c)]
print('    期望（场景相机手算）= pos=%s fwd=%s up=%s' % _exp_b)
check('②b 轨道相机路径：两端 (位置/前向/上方向) 逐项相等',
      bool(_got_c) and _got_c == _vkt_c, (_got_c, _vkt_c))
check('②b 轨道相机路径：两端听者都 = 场景轨道相机手算期望（位置/前向/上方向）',
      bool(_got_c) and _got_c[0][:3] == _exp_b and _vkt_c[0][:3] == _exp_b,
      ('GL=%r VK=%r 期望=%r' % (_got_c[0][:3] if _got_c else None,
                                _vkt_c[0][:3] if _vkt_c else None, _exp_b)))
check('②b 轨道相机路径：两端 set_listener 都真的生效（P4-1 同一根因）',
      bool(_got_c) and _got_c[0][3] == 'OK' and _vkt_c[0][3] == 'OK',
      (_got_c[0][3] if _got_c else None, _vkt_c[0][3] if _vkt_c else None))
p.clear_ops()
for _ in range(3):
    p.logic_frame()
att = _listener_attempts(p)
rows.append(('②b 连跑 3 帧 set_listener 次数', len(att[0]), len(att[1])))
check('②b 听者每逻辑帧都同步一次（3 帧 → 两端各 3 次）',
      len(att[0]) == len(att[1]) == 3, (len(att[0]), len(att[1])))
seq_check('②b 轨道相机路径：set_listener 参数 / 生效状态 / 每帧同步次数，两端逐项相等',
          rows)
p.shutdown()


# ============================ ③ 每帧更新时序 ============================
print()
print("=== ③. 每帧更新时序：逻辑帧 8 段里 update_audio 的位置与调用次数两端相等 ===")

GL_SEGMENTS = [
    ('_dispatch_fixed_update', 'FixedUpdate'),
    ('_run_scripts', 'scripts'),
    ('update_animations', 'animations'),
    ('_physics_frame', 'physics'),
    ('update_audio', 'audio'),
    ('_logic_prep', 'prep'),
    ('_dispatch_collision_events', 'dispatch'),
]
VK_SEGMENTS = [
    ('_dispatch_fixed_update', 'FixedUpdate'),
    ('update_scripts', 'scripts'),
    ('_update_animations', 'animations'),
    ('_step_physics', 'physics'),
    ('update_audio', 'audio'),
    ('_logic_prep', 'prep'),
    ('_dispatch_collision_events', 'dispatch'),
]


def _trace(host, table):
    """实例级插桩：记录**实际调用顺序**（不是读源码顺序）+ 共享函数真实调用次数。"""
    seen, saved = [], []
    for attr, label in table:
        fn = getattr(host, attr, None)
        if fn is None:
            continue
        saved.append((attr, fn))

        def make(fn=fn, label=label):
            def wrapper(*a, **k):
                seen.append(label)
                return fn(*a, **k)
            return wrapper
        setattr(host, attr, make())
    it = getattr(host, '_interp', None)
    orig_adv = getattr(it, 'advance', None)
    if orig_adv is not None:
        def adv(*a, **k):
            seen.append('interp')
            return orig_adv(*a, **k)
        it.advance = adv
    return seen, saved, it, orig_adv


def _untrace(host, saved, it, orig_adv):
    for attr, fn in saved:
        setattr(host, attr, fn)
    if orig_adv is not None:
        it.advance = orig_adv


p = Pair()
rows = []
gl_cnt, vk_cnt = [], []
_seen_gl, _saved_gl, _it_gl, _adv_gl = _trace(p.gl, GL_SEGMENTS)
_seen_vk, _saved_vk, _it_vk, _adv_vk = _trace(p.vk, VK_SEGMENTS)
_orig_lfc = LFC.update_audio


def _count_shared(host_, dt):
    (gl_cnt if isinstance(host_, runtime.PlayerApp) else vk_cnt).append(1)
    return _orig_lfc(host_, dt)


LFC.update_audio = _count_shared
try:
    p.gl._logic_frame(FRAME_DT)
    p.vk._logic_frame(FRAME_DT)
finally:
    LFC.update_audio = _orig_lfc
    _untrace(p.vk, _saved_vk, _it_vk, _adv_vk)
    _untrace(p.gl, _saved_gl, _it_gl, _adv_gl)
print('    GL 段序: %s' % (' -> '.join(_seen_gl),))
print('    VK 段序: %s' % (' -> '.join(_seen_vk),))
rows.append(('③ 段序（含 physics/interp）', tuple(_seen_gl), tuple(_seen_vk)))
rows.append(('③ 共享 update_audio 真实调用次数/帧', len(gl_cnt), len(vk_cnt)))
check('③ 逻辑帧内段序逐项相等（含音频段位置）', _seen_gl == _seen_vk,
      'GL=%s VK=%s' % (_seen_gl, _seen_vk))
check('③ 音频段位置正确：在物理之后、prep 之前（两端同）',
      'audio' in _seen_gl and 'audio' in _seen_vk
      and _seen_gl.index('audio') > _seen_gl.index('physics')
      and _seen_gl.index('audio') < _seen_gl.index('prep')
      and _seen_vk.index('audio') > _seen_vk.index('physics')
      and _seen_vk.index('audio') < _seen_vk.index('prep'),
      (tuple(_seen_gl), tuple(_seen_vk)))
check('③ 每个逻辑帧音频段恰好 1 次（两端都是，且走的是同一份共享实现）',
      len(gl_cnt) == len(vk_cnt) == 1, (len(gl_cnt), len(vk_cnt)))
gl_cnt.clear()
vk_cnt.clear()
orig = LFC.update_audio


def _cnt(host_, dt):
    (gl_cnt if isinstance(host_, runtime.PlayerApp) else vk_cnt).append(1)
    return orig(host_, dt)


LFC.update_audio = _cnt
try:
    for _ in range(5):
        p.gl._logic_frame(FRAME_DT)
        p.vk._logic_frame(FRAME_DT)
finally:
    LFC.update_audio = orig
rows.append(('③ 连跑 5 帧音频段次数', len(gl_cnt), len(vk_cnt)))
check('③ 连跑 5 个逻辑帧 → 两端音频段都恰好 5 次（不重不漏）',
      len(gl_cnt) == len(vk_cnt) == 5, (len(gl_cnt), len(vk_cnt)))
seq_check('③ 每帧更新时序：段序 / 音频段位置 / 调用次数，两端逐项相等', rows)
p.shutdown()

print()
print("    —— ③-c 绑死模式（设置.json logic_fps<=0 = 用户可配置的旧模式）")
_UR = os.environ['LOOM_USER_ROOT']
os.makedirs(os.path.join(_UR, 'engine'), exist_ok=True)
with open(os.path.join(_UR, 'engine', 'settings.json'), 'w', encoding='utf-8') as _f:
    json.dump({'schema': 1, 'app': 'loom', 'values': {'logic_fps': 0}}, _f)
p = Pair()
rows = []
check('③-c 两端都进了绑死模式（_split_enable=False，时钟 None）',
      p.gl._split_enable is False and p.vk._split_enable is False
      and p.gl._clock is None and p.vk._clock is None,
      (p.gl._split_enable, p.vk._split_enable))
_c = {'GL': [], 'VK': []}
orig = LFC.update_audio


def _cnt2(host_, dt):
    _c['GL' if isinstance(host_, runtime.PlayerApp) else 'VK'].append(1)
    return orig(host_, dt)


LFC.update_audio = _cnt2
try:
    for _ in range(3):
        p.gl.advance_logic(1.0 / 30.0)
        p.vk.advance_logic(1.0 / 30.0)
finally:
    LFC.update_audio = orig
rows.append(('③-c 绑死模式 3 个渲染帧音频段次数', len(_c['GL']), len(_c['VK'])))
# 2026-11-20（独立审核 P1-5 的姊妹括注，test_audio_parity.py:809 同类）：本行及 ⑥-1/⑥-6 的
# 括注原写的是**修前**缺陷状态（P4-3/P4-4 已于 f8239f2/788a998 修完），与修后事实不符（反模式 10）。
# 只改文案，check() 表达式一字未动。
check('③-c 绑死模式：每渲染帧音频段调用次数两端相等（P4-4 修后（原缺陷：VK 绑死路径没有 update_audio））',
      len(_c['GL']) == len(_c['VK']) == 3, (len(_c['GL']), len(_c['VK'])))
seq_check('③-c 绑死模式：音频段调用次数，两端逐项相等', rows)
p.shutdown()
os.remove(os.path.join(_UR, 'engine', 'settings.json'))


# ============================ ④ 暂停期行为 ============================
print()
print("=== ④. 暂停期：logic_paused 时两端音频段同决策（都冻结）+ 恢复无积压 ===")
p = Pair()
rows = []
_c = {'GL': [], 'VK': []}
orig = LFC.update_audio


def _cnt3(host_, dt):
    _c['GL' if isinstance(host_, runtime.PlayerApp) else 'VK'].append(1)
    return orig(host_, dt)


def drive(label, frames=1, dt=1.0 / 30.0):
    """两端各跑 frames 个渲染帧（生产入口 advance_logic），返回音频段调用次数。"""
    _c['GL'].clear()
    _c['VK'].clear()
    LFC.update_audio = _cnt3
    try:
        res = []
        for _ in range(frames):
            res.append((p.gl.advance_logic(dt), p.vk.advance_logic(dt)))
    finally:
        LFC.update_audio = orig
    rows.append((label + ' ·音频段次数', len(_c['GL']), len(_c['VK'])))
    # 音频段次数 == 逻辑帧次数（③ 组已证「每逻辑帧恰好 1 次」），故不再另列逻辑步数行：
    # advance_logic 的返回值 GL=None / VK=(steps, phys_steps) 属时钟/宿主面（P6），
    # 不属本门（见文件头「未核」）。
    return len(_c['GL']), len(_c['VK']), res


g, v, _r = drive('④-0 运行态 1 帧')
check('④-0 运行态：两端每渲染帧都跑音频段（各 1 次）', g == v == 1, (g, v))
for h in (p.gl, p.vk):
    h.set_logic_paused(True)
check('④ 两端都进了暂停态（set_logic_paused 是内核共享实现）',
      p.gl._logic_paused_state() is True and p.vk._logic_paused_state() is True,
      (p.gl._logic_paused_state(), p.vk._logic_paused_state()))
g, v, _r = drive('④-1 暂停期 3 帧', frames=3)
check('④-1 暂停期：两端音频段都**冻结**（3 个渲染帧 0 次）', g == v == 0, (g, v))
p.set_field('music_one', playing=False)
p.clear_ops()
for h in (p.gl, p.vk):
    h.models[0].audio_source.playing = True
g, v, _r = drive('④-2 暂停期置 playing=True 再跑 2 帧', frames=2)
_o = p.ops()
check('④-2 暂停期：两端都不产生任何后端调用（音频段冻结，不抢跑）',
      _o[0] == _o[1] == (), (_o[0], _o[1]))
check('④-2 暂停期：两端实例状态仍同步（playing=True / 已播标志未变）',
      p.comp_state()[0]['music_one']['key'] == p.comp_state()[1]['music_one']['key'],
      (p.comp_state()[0]['music_one'], p.comp_state()[1]['music_one']))
for h in (p.gl, p.vk):
    h.set_logic_paused(False)
p.clear_ops()
g, v, _r = drive('④-3 恢复首帧')
_o = p.ops()
check('④-3 恢复首帧：两端都恰好跑 1 个逻辑帧 / 1 次音频段（无积压）',
      g == v == 1 and len(_r) == 1, (g, v, _r))
check('④-3 恢复首帧：暂停期挂起的 playing 只播 1 次（两端都不重复播）',
      _o[0] == _o[1] and len(_o[0]) == 1 and _o[0][0][0] == 'play', (_o[0], _o[1]))
for h in (p.gl, p.vk):
    h.set_logic_paused(True)
    h.models[0].audio_source.playing = False
drive('④-4 暂停态前置帧（吸收）', frames=1)
p.clear_ops()
_c['GL'].clear()
_c['VK'].clear()
LFC.update_audio = _cnt3
try:
    p.gl.step_logic_once()
    p.vk.step_logic_once()
    p.gl.advance_logic(1.0 / 30.0)
    p.vk.advance_logic(1.0 / 30.0)
finally:
    LFC.update_audio = orig
rows.append(('④-4 F10 单步 ·音频段次数', len(_c['GL']), len(_c['VK'])))
check('④-4 暂停态 F10 单步：两端都恰好跑 1 个逻辑帧 / 1 次音频段',
      len(_c['GL']) == len(_c['VK']) == 1, (len(_c['GL']), len(_c['VK'])))
for h in (p.gl, p.vk):
    h.set_logic_paused(False)
seq_check('④ 暂停期行为：冻结 / 恢复 / F10 单步，两端逐项相等', rows)
p.shutdown()


# ============================ ⑥ 脚本 API 面 ============================
print()
print("=== ⑥. 脚本 API 面：engine.audio.* / add_audio_source 存在性 + 返回值 + 副作用 + 失败路径 ===")
p = Pair(scene_audio(active_camera=True))
rows = []
rows.append(('⑥-1 首帧前 engine.audio 的公开 API 面',
             (tuple(p.api_before_first_frame[0])
              if p.api_before_first_frame[0] is not None else '<None>'),
             (tuple(p.api_before_first_frame[1])
              if p.api_before_first_frame[1] is not None else '<None>')))
check('⑥-1 首帧前两端 engine.audio 都是同一套公开 API（P4-3 修后（原缺陷：VK 首帧前是 None））',
      p.api_before_first_frame[0] == p.api_before_first_frame[1]
      and p.api_before_first_frame[0] is not None, p.api_before_first_frame)
_gl_api = sorted(n for n in dir(p.spy['GL']._real) if not n.startswith('_'))
_vk_api = sorted(n for n in dir(p.spy['VK']._real) if not n.startswith('_'))
rows.append(('⑥-2 运行时 engine.audio 公开 API', tuple(_gl_api), tuple(_vk_api)))
check('⑥-2 运行时两端 engine.audio 是**同一个类**的同一套 API',
      type(p.spy['GL']._real) is type(p.spy['VK']._real) is AudioSystem
      and _gl_api == _vk_api, (_gl_api, _vk_api))
for _n in ('load', 'play', 'play_sound', 'stop', 'shutdown'):
    check('⑥-2 两端 audio.%s 是同一个函数对象（§2 用户 API 要求）' % _n,
          getattr(AudioSystem, _n) is getattr(type(p.spy['VK']._real), _n),
          'AudioSystem.%s' % _n)
rows.append(('⑥-3 load(不存在)', p.gl.audio.load(_NOPE), p.vk.audio.load(_NOPE)))
rows.append(('⑥-3 play(不存在)', p.gl.audio.play(_NOPE), p.vk.audio.play(_NOPE)))
rows.append(('⑥-3 play_sound(不存在)', p.gl.audio.play_sound(_NOPE), p.vk.audio.play_sound(_NOPE)))
rows.append(('⑥-3 stop(不存在)', p.gl.audio.stop(_NOPE), p.vk.audio.stop(_NOPE)))
check('⑥-3 资源不存在：两端返回值一致（都是 None）且都不抛',
      p.gl.audio.load(_NOPE) is None and p.vk.audio.load(_NOPE) is None
      and p.gl.audio.play_sound(_NOPE) is None and p.vk.audio.play_sound(_NOPE) is None,
      rows[-4:])
check('⑥-3 资源不存在：两端后端都**缓存了失败**（_handles[(path,None)] is None，静默不重试）',
      p.spy['GL']._real._backend._handles.get((_NOPE, None), 'absent') is None
      and p.spy['VK']._real._backend._handles.get((_NOPE, None), 'absent') is None,
      (p.spy['GL']._real._backend._handles.get((_NOPE, None), 'absent'),
       p.spy['VK']._real._backend._handles.get((_NOPE, None), 'absent')))
p.clear_ops()
r_gl = p.gl.audio.play_sound(_WAV['a'], 0.4)
r_vk = p.vk.audio.play_sound(_WAV['a'], 0.4)
rows.append(('⑥-4 play_sound(真文件) 返回值', r_gl, r_vk))
rows.append(('⑥-4 play_sound 后端调用', p.ops()[0], p.ops()[1]))
check('⑥-4 play_sound(真文件)：两端返回值一致、后端调用一致（play_sound(wav, 0.4)）',
      r_gl == r_vk is None and p.ops()[0] == p.ops()[1]
      and p.ops()[0][0] == ('play_sound', ('p4_tone_a.wav', 0.4), (), 'OK'),
      (r_gl, r_vk, p.ops()))
_ch = p.device_channels()
check('⑥-4 play_sound(真文件)：**独立判据**两端那个 Sound 都真的占了通道（>0）',
      dict(_ch[0]).get(('owner=None', 'p4_tone_a.wav'), 0) > 0
      and dict(_ch[1]).get(('owner=None', 'p4_tone_a.wav'), 0) > 0, _ch)
_gm, _vm = p.model('silent_one')
_gc = _gm.add_audio_source(clip=_WAV['b'], loop=False, volume=0.25,
                           category='music', min_distance=2.0,
                           max_distance=40.0, rolloff=1.5)
_vc = _vm.add_audio_source(clip=_WAV['b'], loop=False, volume=0.25,
                           category='music', min_distance=2.0,
                           max_distance=40.0, rolloff=1.5)
_rows_5 = [(k, getattr(_gc, k), getattr(_vc, k)) for k in
           ('clip', 'loop', 'volume', 'category', 'min_distance', 'max_distance',
            'rolloff', 'playing', '_key')]
rows.append(('⑥-5 add_audio_source 组件字段', tuple((k, g) for (k, g, _v) in _rows_5),
             tuple((k, v) for (k, _g, v) in _rows_5)))
check('⑥-5 add_audio_source：两端组件字段逐项相等（含默认 playing=False / _key=None）',
      all(g == v for (_k, g, v) in _rows_5), _rows_5)
_gm.remove_audio_source()
_vm.remove_audio_source()
rows.append(('⑥-5 remove_audio_source 后', _gm.audio_source, _vm.audio_source))
check('⑥-5 remove_audio_source：两端都清空（audio_source is None）',
      _gm.audio_source is None and _vm.audio_source is None,
      (_gm.audio_source, _vm.audio_source))
# ⑥-6 关键：脚本必须**随场景一起装配**（= 真实场景文件的 scripts 字段），这样它的
# on_start 发生在**第一帧**里 —— 也就是 VK 还没惰性建出 engine.audio 的那一刻（P4-3）。
# 这里不预热、不装观测代理，跑的就是纯生产路径。
_scene6 = scene_audio()
for _o in _scene6['objects']:
    _o['scripts'] = [{'id': 'p4_audio_api_caught', 'vars': {}},
                     {'id': 'p4_audio_api_raw', 'vars': {}}]


def _first_frame(side):
    API_LOG.clear()
    if side == 'GL':
        h = new_gl(_scene6)
        h.is_playing = True
        h.parallel = None
        h._collision_pool = None
        h._frame_pool = None
    else:
        h = new_vk(_scene6)
        h.is_playing = True
        h.parallel = None
        h._collision_pool = None
        h._frame_pool = None
    h._logic_frame(FRAME_DT)
    log = list(API_LOG)
    broken = sorted((m.name, sc.script_id, bool(sc._script_broken))
                    for m in h.models for sc in m.scripts
                    if sc.script_id in ('p4_audio_api_raw', 'p4_audio_api_caught'))
    return h, log, broken


_gl6, _gl_log, _gl_broken = _first_frame('GL')
_vk6, _vk_log, _vk_broken = _first_frame('VK')
# 比对用**聚合**（每条结果出现几次），不依赖脚本派发顺序 —— 派发顺序属脚本面，
# 不是音频面；这里要锁的是「同一份脚本调音频 API 得到同一批结果」。
from collections import Counter as _Counter
_gl_agg = tuple(sorted(_Counter(_gl_log).items(), key=lambda kv: str(kv[0])))
_vk_agg = tuple(sorted(_Counter(_vk_log).items(), key=lambda kv: str(kv[0])))
rows.append(('⑥-6 脚本 on_start 调音频 API 的结果（聚合）', _gl_agg, _vk_agg))
rows.append(('⑥-6 脚本是否被引擎判成坏脚本', tuple(_gl_broken), tuple(_vk_broken)))
check('⑥-6 同一份脚本在 on_start 里调 audio.play_sound/stop/load：两端结果逐项相等'
      '（聚合口径，不依赖脚本派发顺序）', _gl_agg == _vk_agg, (_gl_agg, _vk_agg))
check('⑥-6 脚本健康度：两端都不把脚本判成坏脚本（P4-3 修后（原缺陷：VK 上 on_start 抛 AttributeError））',
      _gl_broken == _vk_broken and all(not b for (_n, _s, b) in _gl_broken),
      (_gl_broken, _vk_broken))
for _h in (_gl6, _vk6):
    try:
        _h.audio.shutdown()
    except Exception:
        pass
seq_check('⑥ 脚本 API 面：存在性 / 返回值 / 副作用 / 失败路径 / on_start 脚本，两端逐项相等',
          rows)
p.shutdown()


# ============================ ⑤ 无音频设备降级 ============================
print()
print("=== ⑤. 无音频设备：强制无设备（生产 AudioBackend 真实降级路径）两端行为一致 ===")
print("    （做法：SDL 驱动改成不存在的名字 + mixer.quit() → pygame.mixer.init() 失败；"
      "两端走同一个生产 AudioBackend 的静默降级分支）")
pygame.mixer.quit()
_prev_drv = os.environ.get('SDL_AUDIODRIVER')
os.environ['SDL_AUDIODRIVER'] = 'p4_no_such_audio_driver'
try:
    p = Pair(scene_audio())
    _init_failed = None
    try:
        pygame.mixer.init()
        _init_failed = False
    except Exception:
        _init_failed = True
    pygame.mixer.quit()
    rows = []
    check('⑤ 夹具前提：本机此刻真的没有可用音频设备（pygame.mixer.init 抛）',
          _init_failed is True, _init_failed)
    p.set_field('music_one', playing=True)
    p.clear_ops()
    errs = p.logic_frame()
    _o = p.ops()
    _b = p.backend_state()
    _c2 = p.comp_state()
    rows.append(('⑤ 无设备 ·帧内异常', errs[0], errs[1]))
    rows.append(('⑤ 无设备 ·后端调用', _o[0], _o[1]))
    rows.append(('⑤ 无设备 ·句柄缓存（None = 静默）', _b[0]['handles'], _b[1]['handles']))
    rows.append(('⑤ 无设备 ·实例状态（状态机照走）', _c2[0], _c2[1]))
    check('⑤ 无设备：两端都不崩（音频段不抛）', errs[0] is None and errs[1] is None, errs)
    check('⑤ 无设备：两端都对同一份后端要了 play（引擎侧行为不变，失败在设备层）',
          _o[0] == _o[1] and len(_o[0]) == 1 and _o[0][0][0] == 'play', (_o[0], _o[1]))
    check('⑤ 无设备：两端都静默（后端句柄缓存是 None，不崩也不响）',
          dict(_b[0]['handles'])[('music_one', 'p4_tone_a.wav')] is None
          and dict(_b[1]['handles'])[('music_one', 'p4_tone_a.wav')] is None, _b)
    check('⑤ 无设备：两端实例状态仍逐项相等（状态机照走，已播标志已推进）',
          _c2[0] == _c2[1]
          and _c2[0]['music_one']['key'] == ('p4_tone_a.wav', True),
          (_c2[0]['music_one'], _c2[1]['music_one']))
    rows.append(('⑤ 无设备 ·load 返回值', p.gl.audio.load(_WAV['b']), p.vk.audio.load(_WAV['b'])))
    rows.append(('⑤ 无设备 ·play 返回值', p.gl.audio.play(_WAV['b']), p.vk.audio.play(_WAV['b'])))
    rows.append(('⑤ 无设备 ·play_sound 返回值',
                 p.gl.audio.play_sound(_WAV['b']), p.vk.audio.play_sound(_WAV['b'])))
    check('⑤ 无设备：两端脚本 API 返回值一致（都是 None）且都不抛',
          p.gl.audio.load(_WAV['b']) is None and p.vk.audio.load(_WAV['b']) is None
          and p.gl.audio.play(_WAV['b']) is None and p.vk.audio.play(_WAV['b']) is None,
          rows[-3:])
    p.set_field('music_one', playing=False)
    p.clear_ops()
    errs = p.logic_frame()
    _o = p.ops()
    rows.append(('⑤ 无设备 ·停帧', _o[0], _o[1]))
    check('⑤ 无设备：停也一致（两端都调 stop、都不崩）',
          errs[0] is None and errs[1] is None and _o[0] == _o[1]
          and len(_o[0]) == 1 and _o[0][0][0] == 'stop', (_o[0], _o[1], errs))
    seq_check('⑤ 无音频设备：异常 / 后端调用 / 句柄缓存 / 实例状态 / 返回值，两端逐项相等',
              rows)
    p.shutdown()
finally:
    if _prev_drv is None:
        os.environ['SDL_AUDIODRIVER'] = 'dummy'
    else:
        os.environ['SDL_AUDIODRIVER'] = _prev_drv
    try:
        pygame.mixer.quit()
        pygame.mixer.init()
    except Exception as _e:
        print('    （恢复音频驱动时告警: %r）' % (_e,))


# ============================ 收尾 ============================
print()
print("=== 收尾：释放音频设备（★miniaudio 设备线程不关会挂死进程）+ 清 pygame 通道 ===")
_clean = True
try:
    pygame.mixer.stop()
    pygame.mixer.quit()
except Exception as _e:
    _clean = False
    print('FAIL 收尾失败: %r' % (_e,))
check('收尾：pygame mixer 已关闭（不把设备线程带出进程）',
      _clean and pygame.mixer.get_init() is None, pygame.mixer.get_init())

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
