# -*- coding: utf-8 -*-
"""anim_np_check.py — D2/A6 动画采样 numpy 化独立对拍网 (主线程接管, 2026-08-31).

对拍基准 = 改前旧实现直译 (纯 Python 逐帧线性扫, 从 git/组2 存档语义):
  dur>0 先取模; 从 i=1 起线性扫, 首个 t<=nxt.time 的段做线性插值
  f = 0.0 if span<=0 else (t-prev)/span; out[k] = a[j]+(b[j]-a[j])*f;
  缺通道保持 prev[k] 原对象; 扫完保持末帧原值原对象。

对拍目标 = engine.AnimationClip.sample 现实现 (快/慢双路径)。
断言 = 每个采样点 (t, 各通道) 与参考值 == 严格相等 (float ==, 逐位),
     不用近似容差 —— 目标就是逐位一致。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from engine import AnimationClip  # noqa: E402


# ---------- 改前旧实现直译 (参考基准) ----------
def ref_sample(frames, t):
    if not frames:
        return {}
    dur = frames[-1]['time']
    if dur > 0:
        t = t % dur
    prev = frames[0]
    for i in range(1, len(frames)):
        nxt = frames[i]
        if t <= nxt['time']:
            span = nxt['time'] - prev['time']
            f = 0.0 if span <= 0 else (t - prev['time']) / span
            out = {}
            for k in ('position', 'rotation', 'scale'):
                if k in prev and k in nxt:
                    a, b = prev[k], nxt[k]
                    out[k] = tuple(a[j] + (b[j] - a[j]) * f for j in range(3))
                elif k in prev:
                    out[k] = prev[k]
            return out
        prev = nxt
    return {k: prev[k] for k in ('position', 'rotation', 'scale') if k in prev}


TS = [0.0, 0.1, 0.25, 0.5, 0.7, 1.0, 1.3, 1.5, 1.9999999, 2.0, 2.5, 3.7,
      -0.3, 1e-9, 6.283185307179586, 12345.6789]


def cmp_case(name, frames, force_slow=False):
    """建 clip 采样对拍; force_slow=True 时用 monkeypatch 强制走慢路径
    (用于把'慢路径本身'也对上参考)。返回 FAIL 数。
    崩溃也算语义: 两边同类型异常 = 一致 (如 None 通道旧实现就是
    TypeError 崩溃, 新慢路径必须原样复现)。"""
    clip = AnimationClip([dict(fr) for fr in frames])
    fails = 0
    for t in TS:
        try:
            got, gerr = clip.sample(t), None
        except Exception as e:
            got, gerr = None, type(e).__name__
        try:
            want, werr = ref_sample([dict(fr) for fr in frames], t), None
        except Exception as e:
            want, werr = None, type(e).__name__
        if gerr is not None or werr is not None:
            if gerr != werr:
                fails += 1
                print(f"  FAIL {name} t={t}: 崩溃不一致 got_err={gerr} want_err={werr}")
            continue
        for k in ('position', 'rotation', 'scale'):
            g, w = got.get(k), want.get(k)
            if (g is None) != (w is None):
                fails += 1
                print(f"  FAIL {name} t={t} {k}: 通道有无不一致 got={g} want={w}")
            elif g is not None and tuple(g) != tuple(w):
                fails += 1
                print(f"  FAIL {name} t={t} {k}:\n    got  {g!r}\n    want {w!r}")
    # 缓存失效: 换 frames 列表对象后 sample 必须反映新数据
    clip2 = AnimationClip([dict(fr) for fr in frames])
    new_frames = [{'time': 0.0, 'position': (9.0, 9.0, 9.0)},
                  {'time': 1.0, 'position': (8.0, 8.0, 8.0)}]
    clip2.frames = new_frames
    got = clip2.sample(0.5)
    if got.get('position') != (8.5, 8.5, 8.5):
        fails += 1
        print(f"  FAIL {name} 缓存失效: 换列表后未重建 got={got.get('position')}")
    return fails


total = 0

# ① 三帧标准 (position only, 缺通道保持语义)
frames1 = [{'time': 0.0, 'position': (0.0, 0.0, 0.0)},
           {'time': 1.0, 'position': (0.0, 2.0, 0.0)},
           {'time': 2.0, 'position': (0.0, 0.0, 0.0)}]
total += cmp_case("①三帧标准", frames1)

# ② 全通道齐备 (快路径主形态) + 非整时间点
frames2 = [{'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)},
           {'time': 1.5, 'position': (3.3, -2.7, 1.1), 'rotation': (0.5, -1.2, 2.8), 'scale': (2.0, 0.5, 1.7)},
           {'time': 3.0, 'position': (-1.0, 4.2, 0.7), 'rotation': (3.1, 0.4, -0.9), 'scale': (0.8, 1.9, 0.6)}]
total += cmp_case("②全通道+非整点", frames2)

# ③ span=0 重帧 (f=0.0 分支)
frames3 = [{'time': 0.0, 'position': (0.0, 0.0, 0.0)},
           {'time': 1.0, 'position': (1.0, 1.0, 1.0)},
           {'time': 1.0, 'position': (5.0, 5.0, 5.0)},
           {'time': 2.0, 'position': (2.0, 0.0, 0.0)}]
total += cmp_case("③span=0重帧", frames3)

# ④ 单调非严格递增 + 越界时间 (取模循环)
frames4 = [{'time': 0.5, 'position': (1.0, 0.0, 0.0)},
           {'time': 1.0, 'position': (0.0, 1.0, 0.0)},
           {'time': 2.5, 'position': (0.0, 0.0, 1.0)}]
total += cmp_case("④首帧>0+循环", frames4)

# ⑤ 大 int 通道值 (>2^53, f64 不可精确表示 — 闸门豁漏点, 新旧都可转但舍入点不同)
big = 2 ** 53 + 3   # f64 舍入为 2^53+2? 实际 round-to-even: 2^53+3 -> 2^53+4? 由对拍裁决
frames5 = [{'time': 0.0, 'position': (big, 0.0, 0.0)},
           {'time': 1.0, 'position': (big, 1.0, 0.0)}]
total += cmp_case("⑤大int通道", frames5)

# ⑥ None 通道 (旧实现语义 = 插值时 TypeError 崩溃, 新慢路径须原样复现)
frames6 = [{'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': None},
           {'time': 1.0, 'position': (1.0, 1.0, 1.0), 'rotation': (0.0, 0.5, 0.0)}]
total += cmp_case("⑥None通道", frames6)

# ⑦ 乱序时间 (旧线性扫语义特殊: t<=nxt 命中即返 — 快路径闸门应挡下走慢路径)
frames7 = [{'time': 2.0, 'position': (2.0, 0.0, 0.0)},
           {'time': 1.0, 'position': (1.0, 0.0, 0.0)},
           {'time': 3.0, 'position': (3.0, 0.0, 0.0)}]
total += cmp_case("⑦乱序时间", frames7)

# ⑧ 单帧 (F<2 → 慢路径: 恒末帧) + 空帧
total += cmp_case("⑧单帧", [{'time': 1.0, 'position': (1.0, 2.0, 3.0)}])
total += cmp_case("⑨空帧", [])
total += cmp_case("⑩int通道值", [{'time': 0, 'position': (1, 2, 3)},
                                 {'time': 2, 'position': (5, 6, 7)}])

print()
print("总 FAIL 数:", total)
print("结果:", "ALL PASS ✅" if total == 0 else "有 FAIL ❌")
sys.exit(0 if total == 0 else 1)
