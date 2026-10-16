# -*- coding: utf-8 -*-
"""
audio_backend.py — 音频双后端适配层 (2026-08-30 B2 换库)

主后端 = game-audio 2.1.0 (miniaudio C++20, 单 pyd, 静态链入零 DLL):
  wav/mp3/flac + 组/轨/RandomSoundContainer + 3D 声像 (特性储备);
兜底 = pygame.mixer (现状实现原样语义: wav/ogg)。

选择: LOOM_AUDIO_BACKEND = auto(默认) | game_audio | pygame
  auto = game-audio import+init 成功 → 用它, 否则 pygame; 两者皆失败 →
  置不可用, 一切操作静默 no-op (与现状"无设备 mixer 挂掉全静默"同语义)。

per-file 回退: game-audio 实测不支持 ogg/opus (-10 MA_INVALID_FILE, 文件本身有效)
  → 加载失败自动回退 pygame.mixer.Sound 播放, 兼容性零丢失。

句柄缓存: (path, owner) -> 句柄。game-audio 的 load_sound 每次返回新句柄且
  set_sound_volume/looping 是句柄级状态 → owner=组件身份 (id 组件), 同 clip 多
  组件各自独立音量 (比 pygame"同 Sound 共享音量"更强, 语义超集); pygame 侧保持
  现状 path 级 Sound 缓存。

异常分层 (全部捕获静默, 与现状容错一致):
  FileLoadException  = 文件缺失/不可解码 → per-file 回退 pygame → 仍失败 None 缓存
  NotInitializedException = shutdown 后调用 → 引擎正常路径不触发, 静默
  InvalidHandleException = 句柄已销毁 → 静默 (引擎正常路径不触发)
  AudioException 等其余  = 无设备/初始化失败 → 降级/不可用

★铁律: 退出必须 shutdown() (miniaudio 设备线程不关会挂死进程, 实测复现);
  引擎退出链调用 + atexit 兜底。Nuitka 无需新参数 (pyd 自动收录, 已试打包 PASS)。
"""
import atexit
import os

_MODE_ENV = 'LOOM_AUDIO_BACKEND'


def _ga_open_path(path):
    """game-audio 打开路径的编码适配 (2026-08-30 T1 实测修复):
    pybind11 收 str 转 UTF-8 std::string, 而 miniaudio 窄路径 fopen 用系统
    ANSI 码页 (中文系统=GBK) -> 含中文的绝对路径报 FileLoadException;
    实测传 bytes(ANSI 编码) 直接打开成功。纯 ASCII 路径原样传 (零开销)。"""
    try:
        path.encode('ascii')
        return path
    except UnicodeEncodeError:
        pass
    try:
        return path.encode('mbcs')      # 系统 ANSI 码页 (Windows 专用 codec)
    except UnicodeEncodeError:
        return path                     # 字符集不可编码: 原样传 (仍失败则回退 pygame)


class AudioBackend:
    """双后端: 选择/降级/回退 + 统一播放接口 (引擎 AudioSystem 委托)."""

    def __init__(self):
        self._mode = None          # 'game_audio' | 'pygame' | None(=不可用)
        self._init_done = False
        self._closed = False
        self._ga = None            # game_audio 模块
        self._mgr = None           # AudioManager 实例
        self._handles = {}         # (path, owner) -> {'kind','obj'} (ga 句柄/pygame Sound)
        self._py_sounds = {}       # path -> pygame.mixer.Sound (pygame 后端/回退共享)
        atexit.register(self.shutdown)   # 兜底: 进程退出前关设备线程

    # ---------------- 初始化 / 后端选择 ----------------
    def _ensure(self):
        """惰性初始化: 选定主后端 (只做一次). 失败自动降级, 再失败→不可用."""
        if not self._init_done:
            self._init_done = True
            want = os.environ.get(_MODE_ENV, 'auto').lower()
            if want in ('game_audio', 'auto'):
                if self._try_game_audio():
                    self._mode = 'game_audio'
                else:
                    self._mode = 'pygame'      # ga 失败 → 回退 pygame (强制同价)
            else:
                self._mode = 'pygame'
        return self._mode is not None

    def _try_game_audio(self):
        try:
            import game_audio as ga
            mgr = ga.AudioManager.get_instance()
            mgr.initialize()
            self._ga = ga
            self._mgr = mgr
            return True
        except Exception:
            self._ga = None
            self._mgr = None
            return False

    # ---------------- 加载 / 播放 / 停止 ----------------
    def _get_py(self, path):
        """pygame Sound (按 path 共享, 现状语义); 失败返回 None."""
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception:
            pass
        s = self._py_sounds.get(path)
        if s is not None:
            return s
        try:
            import pygame
            s = pygame.mixer.Sound(path)
        except Exception:
            s = None
        self._py_sounds[path] = s
        return s

    def load(self, path, owner=None):
        """加载/缓存句柄 (per (path, owner)); 失败 None (含 per-file 回退失败)."""
        if not path:
            return None
        key = (path, owner)
        ent = self._handles.get(key)
        if ent is not None or key in self._handles:
            return ent                      # 已缓存 (None 也缓存, 防反复重试)
        ent = None
        if self._ensure():
            if self._mode == 'game_audio':
                try:
                    h = self._mgr.load_sound(_ga_open_path(path))
                    ent = {'kind': 'ga', 'obj': h}
                except Exception:
                    ent = self._py_fallback(path)   # ga 加载失败 → per-file 回退
            else:                                   # pygame
                ent = self._py_fallback(path)
        self._handles[key] = ent
        return ent

    def _py_fallback(self, path):
        s = self._get_py(path)
        return {'kind': 'py', 'obj': s} if s is not None else None

    def play(self, path, loop=False, volume=1.0, owner=None):
        """播放 (与旧 pygame 语义一致: 每 play 重设音量; loop 前置设置稳定生效)."""
        ent = self.load(path, owner)
        if ent is None:
            return None
        v = max(0.0, min(1.0, float(volume)))
        try:
            if ent['kind'] == 'ga':
                self._mgr.set_sound_looping(ent['obj'], bool(loop))
                self._mgr.set_sound_volume(ent['obj'], v)
                self._mgr.play_sound(ent['obj'])
            else:
                ent['obj'].set_volume(v)
                ent['obj'].play(loops=-1 if loop else 0)
        except Exception:
            return None
        return None

    def stop(self, path, owner=None):
        """停止 (幂等; 未加载过/已停止均静默)."""
        ent = self._handles.get((path, owner))
        if ent is None:
            return
        try:
            if ent['kind'] == 'ga':
                self._mgr.stop_sound(ent['obj'])
            else:
                ent['obj'].stop()
        except Exception:
            pass

    # ---------------- 退出 ----------------
    def shutdown(self):
        """关闭设备 (幂等). ★不调会挂死进程 (miniaudio 设备线程)."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._mgr is not None:
                self._mgr.shutdown()
        except Exception:
            pass
        self._mgr = None

    @property
    def mode(self):
        """当前后端名: 'game_audio' | 'pygame' | None. (诊断/测试用)"""
        return self._mode
