# -*- coding: utf-8 -*-
"""T1_audio_chain.py — 验收链 T1 任务5: 真设备音频链路 (game_audio 后端).
生成 0.5s 440Hz 正弦 wav -> AudioBackend load/play 0.4s/stop/shutdown, 断言 mode=game_audio."""
import os
import sys
import time
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))   # Loom 包目录
from audio_backend import AudioBackend

# 0.5s 正弦 wav (与 gen_tone.py 同构)
sr = 44100
t = np.arange(sr // 2) / sr
data = (16000 * 0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
wav_path = os.path.join(HERE, 'tone_test.wav')
with wave.open(wav_path, 'wb') as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(sr)
    f.writeframes(data.tobytes())
print("wav 生成 OK:", wav_path)

b = AudioBackend()
h = b.load(wav_path)
print("mode =", b.mode, "| handle =", h is not None, "| repr =", repr(h))
assert b.mode == 'game_audio', '本机应为 game_audio 后端 (实际 %r)' % b.mode
assert h is not None, 'wav 应至少加载成功 (GA 或 pygame 回退)'
if h.get('kind') == 'ga':
    print("[提示] GA 句柄加载成功 (kind=ga)")
else:
    print("[提示] GA 加载路径失败, 已走 per-file pygame 回退 (kind=%s) —— 见 T1 报告问题清单" % h.get('kind'))
b.play(wav_path, loop=False)
time.sleep(0.4)
b.stop(wav_path)
b.shutdown()
print("GA 链路 OK (load->play 0.4s->stop->shutdown)")
