# -*- coding: utf-8 -*-
"""M34 音频系统: AudioSource 组件/播放状态同步/序列化/undo/缺失文件容错."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import undo as U
import sceneio as S
from mesh import create_cube

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

class MockAudio:
    """桩: 记录 play/stop 调用 (不真播, 无需音频设备). B2: owner 参数透传."""
    def __init__(self):
        self.played = []
        self.stopped = []
    def load(self, p):
        return None
    def play(self, path, loop=False, volume=1.0, owner=None):
        self.played.append((path, loop, volume, owner))
    def stop(self, path, owner=None):
        self.stopped.append((path, owner))
    def play_sound(self, path, volume=1.0):
        self.played.append((path, False, volume, None))

eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []; eng.materials = []; eng.lights = []
eng.current_model_index = 0
eng.audio = MockAudio()
E.GLEngine._build_gpu = lambda self, m: None

m = eng.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
a = m.add_audio_source(clip='x.wav', loop=True, volume=0.8)
check("加音频源后 object.audio_source 存在", m.audio_source is not None)
check("音频源字段 (clip/loop/volume)", a.clip == 'x.wav' and a.loop and a.volume == 0.8)

# ---- playing=False 不播; 变 True 触发 play; 变 False 触发 stop ----
eng.update_audio(0.1)
check("playing=False 不播", eng.audio.played == [], str(eng.audio.played))
a.playing = True
eng.update_audio(0.1)
check("playing=True 触发 play (loop/volume 透传)",
      [t[:3] for t in eng.audio.played] == [('x.wav', True, 0.8)],
      str(eng.audio.played))
check("play 带 owner=id(组件)", eng.audio.played[0][3] == id(a),
      str(eng.audio.played))
a.playing = False
eng.update_audio(0.1)
check("变 False 触发 stop (带 owner)", eng.audio.stopped[0][0] == 'x.wav'
      and eng.audio.stopped[0][1] == id(a), str(eng.audio.stopped))

# ---- 状态未变不重复播 ----
a.playing = True
eng.update_audio(0.1)
n = len(eng.audio.played)
eng.update_audio(0.1)
check("状态未变不重复播", len(eng.audio.played) == n, str(len(eng.audio.played)))

# ---- AudioSystem 缺失文件容错 (B2 双后端: ga 主 + pygame 兜底各测一遍) ----
asys = E.AudioSystem()
check("AudioSystem.load 缺失文件返回 None", asys.load(os.path.join('_nope', 'no.wav')) is None)
check("AudioSystem.play 缺失文件不崩", asys.play('no_such.wav') is None)
check("AudioSystem.play_sound 缺失不崩", asys.play_sound('no_such.wav') is None)
for _backend in ('game_audio', 'pygame'):
    _old = os.environ.get('LOOM_AUDIO_BACKEND')
    os.environ['LOOM_AUDIO_BACKEND'] = _backend
    a2 = E.AudioSystem()
    check("强制 %s 缺文件 load=None" % _backend,
          a2.load(os.path.join('_nope', 'no.wav')) is None)
    check("强制 %s 缺文件 play 不崩" % _backend, a2.play('no_such.wav') is None)
    a2.shutdown()
    if _old is None:
        os.environ.pop('LOOM_AUDIO_BACKEND', None)
    else:
        os.environ['LOOM_AUDIO_BACKEND'] = _old

# ---- B2: 中文路径必须走 game-audio 句柄 (2026-08-30 T1 修复: ga 收 str 转 UTF-8,
#      而 miniaudio 窄路径 fopen 用 ANSI 码页 -> 中文路径 FileLoadException;
#      修复 = 桥内 mbcs 编码传 bytes) ----
import wave as _wave
import struct as _struct
_ch_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_中文路径测试')
os.makedirs(_ch_dir, exist_ok=True)
_ch_wav = os.path.join(_ch_dir, 't1.wav')
with _wave.open(_ch_wav, 'wb') as _f:
    _f.setnchannels(1); _f.setsampwidth(2); _f.setframerate(8000)
    _f.writeframes(b''.join(_struct.pack('<h', int(4000 * (0.5 + 0.5 * 0)))
                            for _ in range(200)))   # 0.025s 静音帧
asys_cn = E.AudioSystem()
_h = asys_cn.load(_ch_wav)
_kind = _h['kind'] if _h else None
check("中文路径 load -> ga 句柄 (回退另判)",
      _kind == 'ga' or (asys_cn._ensure().mode != 'game_audio'), "kind=%s" % _kind)
if _kind == 'ga':
    asys_cn.play(_ch_wav, loop=False, volume=0.5)
    asys_cn.stop(_ch_wav)
    check("中文路径 play/stop 无异常", True)
asys_cn.shutdown()

# ---- B2: shutdown 幂等 + shutdown 后操作静默 ----
asys2 = E.AudioSystem()
_ = asys2.load('probe_missing.wav')    # 先触发后端 _ensure (若设备可用则 ga 已初始化)
asys2.shutdown()
asys2.shutdown()                       # 幂等
check("shutdown 幂等不崩", True)
check("shutdown 后 play 静默不崩", asys2.play('no_such.wav') is None)
check("shutdown 后 load 静默 None", asys2.load('no_such.wav') is None)

# ---- sceneio round-trip ----
d = S._emit_object(m)
check("sceneio audio_source 序列化", d.get('audio_source') is not None
      and d['audio_source']['clip'] == 'x.wav', str(d.get('audio_source')))
eng2 = E.GLEngine.__new__(E.GLEngine); eng2.models = []; eng2.materials = []
m2, _ = S._apply_object(eng2, d)
check("sceneio 加载 audio_source", m2.audio_source is not None
      and m2.audio_source.loop and m2.audio_source.volume == 0.8)

# ---- undo 还原音频源 ----
snap = U.snapshot(m)
m.remove_audio_source()
check("移除音频源后 None", m.audio_source is None)
U.apply_snapshot(m, snap)
check("undo 还原音频源", m.audio_source is not None and m.audio_source.clip == 'x.wav')

import shutil as _shutil
if os.path.isdir(_ch_dir):
    _shutil.rmtree(_ch_dir, ignore_errors=True)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
