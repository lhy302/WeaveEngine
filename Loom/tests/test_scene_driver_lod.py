# -*- coding: utf-8 -*-
"""test_scene_driver_lod.py — LOD 进场景序列化 + 每帧世界矩阵不再全量重算.

scan_05 P-01/P-02 (裁决 A: LOD 进场景序列化):
  · 播放器是独立进程, 只吃场景文件 —— 场景不序列化 lod_* 时 renderer.lod_levels
    恒 None, _update_lod 的选模永不命中 (纯负: 每帧白算全量世界矩阵 2.2ms)。
  · 本文件锁: 场景数据的 lod_levels / lod_screen_levels / lod_bias 能被还原
    (距离模式升序 / 屏幕占比降序 / bias 下限), 选模结果与 GL 同语义;
  · 没有 LOD 物体时 _update_lod **零矩阵开销** (早退);
  · 有 LOD 物体时按变换戳缓存世界位置 (物体不动 -> 不重算)。

附带锁住同批修的两条输入契约 (scan_05 P-06 滚轮帧末清零 / P-08 输入注册限次)
以及 P-07 回调链式转发、P-09 滚轮消费合并的判定助手。
"""
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


import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

import scene_driver as SD
from loom_types import Point3D

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


def _sphere_obj(**extra):
    o = {"id": "s1", "name": "球", "type": "sphere", "params": {"radius": 0.5},
         "position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1],
         "color": "#4a8fd0", "visible": True, "scripts": []}
    o.update(extra)
    return o


def _scene(objects, dist=10.0):
    return {"version": 10, "materials": [], "lights": [], "cameras": [],
            "camera": {"target": [0, 0, 0], "distance": dist,
                       "yaw": 0.0, "pitch": 0.0},
            "objects": objects}


HI = {"type": "sphere", "params": {"radius": 0.5, "stacks": 16, "slices": 24}}
LO = {"type": "sphere", "params": {"radius": 0.5, "stacks": 4, "slices": 6}}


# ============ 1. 场景序列化 -> renderer 字段 ============
def t_lod_from_scene_data():
    print("=== LOD 进场景序列化 (scan_05 P-02, 裁决 A) ===")
    d = SD.SceneDriver()
    d.load_from_data(_scene([_sphere_obj(
        lod_levels=[[30.0, LO], [5.0, HI]],          # 故意乱序: 解析后按升序
        lod_screen_levels=[[0.1, HI], [0.0, LO]],
        lod_bias=2.0)]))
    r = d.models[0].renderer
    check("lod_levels 已从场景还原", r.lod_levels is not None,
          None if r.lod_levels is None else len(r.lod_levels))
    if r.lod_levels:
        check("距离级别按升序 (5 在前)",
              [t for t, _ in r.lod_levels] == [5.0, 30.0],
              [t for t, _ in r.lod_levels])
        check("级别里的网格引用解析成 Mesh",
              len(r.lod_levels[0][1].vertices) == len(HI and
                  __import__('mesh').create_sphere(0.5, 16, 24).vertices),
              len(r.lod_levels[0][1].vertices))
    if r.lod_screen_levels:
        check("屏幕占比级别按降序 (0.1 在前)",
              [t for t, _ in r.lod_screen_levels] == [0.1, 0.0],
              [t for t, _ in r.lod_screen_levels])
    check("lod_bias 恢复", abs(float(r.lod_bias) - 2.0) < 1e-9, r.lod_bias)


def t_lod_bad_data_tolerated():
    print("=== LOD 坏字段容错 ===")
    cases = [
        ("lod_levels 是字符串", {"lod_levels": "oops"}),
        ("级别项缺阈值", {"lod_levels": [[HI]]}),
        ("阈值非数", {"lod_levels": [["x", HI]]}),
        ("网格引用不可识别", {"lod_levels": [[5.0, {"nope": 1}]]}),
        ("lod_bias=None", {"lod_bias": None}),
        ("lod_bias=0 (钳到 0.1)", {"lod_bias": 0}),
    ]
    for name, extra in cases:
        err = None
        r = None
        try:
            d = SD.SceneDriver()
            d.load_from_data(_scene([_sphere_obj(**extra)]))
            r = d.models[0].renderer
            d.render_pose(aspect=1.5)
        except BaseException as e:              # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, e)
        check("坏 LOD 段不崩: %s" % name, err is None, err)
        if err is None and name.startswith("lod_bias=0"):
            check("  bias<=0 钳到 0.1 (与 set_lod 同)", abs(float(r.lod_bias) - 0.1) < 1e-9,
                  r.lod_bias)


# ============ 2. 选模语义 (与 GL 同) ============
def t_distance_selection():
    print("=== 距离模式选模 ===")
    d = SD.SceneDriver()
    d.load_from_data(_scene([_sphere_obj(lod_levels=[[5.0, HI], [30.0, LO]])]))
    m = d.models[0]
    hi, lo = m.renderer.lod_levels[0][1], m.renderer.lod_levels[1][1]
    picks = []
    for dist in (3.0, 20.0):
        d.distance = dist
        d.render_pose(aspect=1.5)
        picks.append("hi" if m.mesh is hi else ("lo" if m.mesh is lo else "?"))
    check("距离 3 -> 高模, 距离 20 -> 低模", picks == ["hi", "lo"], picks)


def t_screen_selection():
    print("=== 屏幕占比模式选模 ===")
    d = SD.SceneDriver()
    d.load_from_data(_scene([_sphere_obj(lod_screen_levels=[[0.1, HI], [0.0, LO]])]))
    m = d.models[0]
    hi, lo = m.renderer.lod_screen_levels[0][1], m.renderer.lod_screen_levels[1][1]
    picks = []
    for dist in (2.0, 10.0):
        d.distance = dist
        d.render_pose(aspect=1.5)
        picks.append("hi" if m.mesh is hi else ("lo" if m.mesh is lo else "?"))
    check("近处 (占比大) -> 高模, 远处 -> 低模", picks == ["hi", "lo"], picks)


# ============ 3. 世界矩阵开销: 早退 + 缓存 ============
class _MatCounter:
    """替换 scene_driver.object_world_matrix, 统计真实矩阵计算次数."""

    def __init__(self):
        self.n = 0
        self._orig = SD.object_world_matrix

    def __enter__(self):
        orig = self._orig

        def _wrapped(m):
            self.n += 1
            return orig(m)

        SD.object_world_matrix = _wrapped
        return self

    def __exit__(self, *a):
        SD.object_world_matrix = self._orig
        return False


def t_no_lod_zero_cost():
    print("=== 无 LOD 物体: 早退 (scan_05 P-01) ===")
    objs = [{"id": "o%d" % i, "name": "o%d" % i, "type": "cube",
             "params": {"size": 1.0}, "position": [i * 0.5 - 5, 0, 0],
             "rotation": [0, 0, 0], "scale": [1, 1, 1], "color": "#808080",
             "visible": True, "scripts": []} for i in range(20)]
    d = SD.SceneDriver()
    d.load_from_data(_scene(objs))
    with _MatCounter() as c:
        for _ in range(3):
            d.render_pose(aspect=1.5)
    check("20 物体无 LOD: 3 帧内 0 次世界矩阵计算", c.n == 0, c.n)


def t_lod_matrix_cache():
    print("=== 有 LOD 物体: 变换未变 -> 复用缓存 ===")
    d = SD.SceneDriver()
    d.load_from_data(_scene([_sphere_obj(lod_levels=[[5.0, HI], [30.0, LO]])]))
    m = d.models[0]
    with _MatCounter() as c:
        d.render_pose(aspect=1.5)
        first = c.n
        for _ in range(5):
            d.render_pose(aspect=1.5)
        cached = c.n
        m.position = Point3D(1.0, 0.0, 0.0)      # 物体动 -> 缓存失效
        d.render_pose(aspect=1.5)
        moved = c.n
    check("首帧算 1 次世界矩阵", first == 1, first)
    check("后续 5 帧静止: 不再重算", cached == first, cached)
    check("物体移动后重算 1 次", moved == first + 1, moved)


# ============ 4. 滚轮帧末清零 (scan_05 P-06) ============
def t_wheel_reset_each_frame():
    print("=== 滚轮帧末清零 (P-06) ===")
    for dev in (False, True):
        d = SD.SceneDriver()
        d.load_from_data(_scene([_sphere_obj()], dist=10.0))
        d.dev_mouse_enabled = dev
        seen = []
        for _ in range(3):
            d.mouse_wheel = 2
            d.advance_logic(1 / 60.0)
            seen.append(d.mouse_wheel)
        check("dev_mouse=%s: 每帧读数后归零" % dev, seen == [0, 0, 0], seen)
    d = SD.SceneDriver()
    d.load_from_data(_scene([_sphere_obj()], dist=10.0))
    d.dev_mouse_enabled = True
    before = d.distance
    d.mouse_wheel = 3
    d.advance_logic(1 / 60.0)
    check("dev_mouse=1 时滚轮仍按 GL 公式推拉 (distance 变小)",
          d.distance < before, (before, d.distance))


# ============ 5. vk_player 侧助手 (P-07/P-08/P-09) ============
def t_vk_helpers():
    print("=== vk_player 助手: 回调链 / 重试预算 / 滚轮消费 ===")
    import vk_player as VP

    # (a) 链式转发: 先库回调, 后自己的
    order = []
    store = {}

    class _FakeSetter:
        def __init__(self):
            self.registered = None

        def __call__(self, win, cb):
            prev = self.registered
            self.registered = cb
            return prev

    setter = _FakeSetter()
    setter.registered = lambda *a: order.append("lib")     # 库已注册的回调
    VP._chain_callback(setter, "win", lambda *a: order.append("mine"), 'key')
    setter.registered("w", 1, 2, 3, 4)
    check("链式转发: 先库回调再自己", order == ["lib", "mine"], order)

    setter2 = _FakeSetter()           # 库没注册任何回调
    ret = VP._chain_callback(setter2, "win", lambda *a: order.append("mine2"), 'key')
    check("库无回调时退化为直接注册", ret is None)

    # (b) 重试预算: 只尝试 limit 次, 之后不再打印/重试
    r = VP._InputRetry(limit=3)
    tries = 0
    while r.can_try():
        tries += 1
        r.failed("句柄验活失败")
        if tries > 10:
            break
    check("失败 3 次后停止重试 (不再每帧)", tries == 3 and r.given_up, (tries, r.given_up))
    n_before = r.attempts
    r.failed("又失败")                # 终态后再调用不增加计数
    check("终态后不再累计尝试次数", r.attempts == n_before, r.attempts)

    # (c) 滚轮消费判定: ScrollView 可滚 -> 被消费; 不可滚 / 无滚动区 -> 不消费
    class _SV:
        def __init__(self, can):
            self._can = can

        def can_scroll(self):
            return self._can

    class _UI:
        def __init__(self, hit, can=True):
            self._hit = hit
            self._can = can

        def _hit_scroll_view(self, pos):
            if self._hit is None:
                return None
            return _SV(self._can)

    check("指针下有可滚 ScrollView -> 认为滚轮被 UI 消费",
          VP._wheel_taken_by_scrollview(_UI("hit", True), (1, 1)) is True)
    check("ScrollView 内容不溢出 (can_scroll=False) -> 不算消费",
          VP._wheel_taken_by_scrollview(_UI("hit", False), (1, 1)) is False)
    check("指针下没有 ScrollView -> 不算消费",
          VP._wheel_taken_by_scrollview(_UI(None), (1, 1)) is False)
    check("判不了的 UI 保守认为已消费 (保持旧行为)",
          VP._wheel_taken_by_scrollview(object(), (1, 1)) is True)
    check("ui=None -> 不消费", VP._wheel_taken_by_scrollview(None, (1, 1)) is False)


def main():
    t_lod_from_scene_data()
    t_lod_bad_data_tolerated()
    t_distance_selection()
    t_screen_selection()
    t_no_lod_zero_cost()
    t_lod_matrix_cache()
    t_wheel_reset_each_frame()
    t_vk_helpers()
    print("=" * 60)
    if _fails:
        print("失败:", _fails)
        return 1
    print("ALL PASS")
    return 0


if __name__ == '__main__':
    sys.exit(main())
