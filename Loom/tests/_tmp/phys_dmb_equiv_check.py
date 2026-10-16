# -*- coding: utf-8 -*-
"""phys_dmb_equiv_check.py — _dirty_mask_batch 旧/新实现等价性对拍 (2026-09-07)

重帧治理改动: dmb 吸收祖先传播 + 跨子步缓存 (四键: ids/位姿/sync/父链拓扑)。
对拍闸门:
  E1 基础 dirty (无父链): 新实现 == 旧实现 (逐体 _model_dirty 语义)
  E2 祖先传播: 链式 A(根脏)->B->C -> B/C 全脏; 孤根不传播
  E3 reparent 拓扑变化必 miss (preserve_world=True 世界位姿不变场景)
  E4 子步间缓存命中: rows/sync/拓扑全等 -> 结果同上次; sync 变 -> miss
  E5 缓存污染防护: 调用方写返回 dict 不影响下次命中结果
  E6 空 entries / 单体 / 全脏 / 全净 边界
纯逻辑 (mock 模型, 无 culverin 依赖), tests 直调。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)


class P3:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = float(x), float(y), float(z)


class M:
    def __init__(self, name, pos=(0, 0, 0), rot=(0, 0, 0)):
        self.name = name
        self.position = P3(*pos)
        self.rotation = P3(*rot)
        self.parent = None


ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


from physics_bridge import PhysicsWorldBridge

# 旧实现参考 (批5 原版: dmb 基础 + pre_step 传播, 移到模块函数复刻)
def _old_dmb(bridge, entries):
    dirty = {}
    for e in entries:
        m = e['model']
        sync = bridge._sync_of(m)
        dirty[id(m)] = ((m.position.x, m.position.y, m.position.z) != sync[0]
                        or (m.rotation.x, m.rotation.y, m.rotation.z) != sync[1])
    return dirty


def _old_propagate(bridge, entries, dirty):
    id2idx = {idd: i for i, idd in enumerate(id(e['model']) for e in entries)}
    parents = [id2idx.get(id(getattr(e['model'], 'parent', None)), -1)
               for e in entries]
    n = len(entries)
    dirty = dict(dirty)
    if n:
        import numpy as np
        dmask = np.array([dirty.get(id(e['model']), False)
                          for e in entries], dtype=bool)
        pmask = dmask.copy()
        for _ in range(n):
            added = np.zeros(n, dtype=bool)
            has_parent = np.where(np.array(parents) >= 0)[0]
            for i in has_parent:
                pi = parents[i]
                if pmask[pi] and not pmask[i]:
                    added[i] = True
            if not added.any():
                break
            pmask |= added
        for i in range(n):
            if pmask[i]:
                dirty[id(entries[i]['model'])] = True
    return dirty


def mk_bridge():
    br = PhysicsWorldBridge.__new__(PhysicsWorldBridge)
    br.enabled = False        # 不碰 culverin
    br._entries = []
    br._next_id = 0
    br._last_sync = {}
    br._dmb_cache = None
    br._tmp_cache = {}
    br._free = []
    return br


def ents(*models):
    return [{'model': m} for m in models]


# ---- E1 基础 dirty (无父链) ----
br = mk_bridge()
a = M('a', pos=(1, 2, 3), rot=(0.1, 0.2, 0.3))
b = M('b', pos=(4, 5, 6))
br._sync_of(a)
br._sync_of(b)
new1 = br._dirty_mask_batch(ents(a, b))
old1 = _old_propagate(br, ents(a, b), _old_dmb(br, ents(a, b)))
check("E1 基础 dirty 逐体等价 (全净)", new1 == old1 and not any(new1.values()))
a.position = P3(9, 9, 9)          # 改 a -> 脏
new1b = br._dirty_mask_batch(ents(a, b))
old1b = _old_propagate(br, ents(a, b), _old_dmb(br, ents(a, b)))
check("E1b 改位后脏标记等价 (a 脏 b 净)", new1b == old1b
      and new1b[id(a)] is True and new1b[id(b)] is False,
      str({k: v for k, v in new1b.items()}))

# ---- E2 祖先传播 (链式) ----
br2 = mk_bridge()
root = M('root', pos=(0, 0, 0))
mid = M('mid', pos=(1, 0, 0))
leaf = M('leaf', pos=(2, 0, 0))
mid.parent = root
leaf.parent = mid
solo = M('solo', pos=(5, 5, 5))
for m in (root, mid, leaf, solo):
    br2._sync_of(m)
r1 = br2._dirty_mask_batch(ents(root, mid, leaf, solo))
o1 = _old_propagate(br2, ents(root, mid, leaf, solo), _old_dmb(br2, ents(root, mid, leaf, solo)))
check("E2 全净传播等价", r1 == o1 and not any(r1.values()))
root.position = P3(1, 1, 1)       # 根脏 -> 链传播
r2 = br2._dirty_mask_batch(ents(root, mid, leaf, solo))
o2 = _old_propagate(br2, ents(root, mid, leaf, solo), _old_dmb(br2, ents(root, mid, leaf, solo)))
check("E2b 根脏链式传播等价 (mid/leaf 脏, solo 净)",
      r2 == o2 and r2[id(mid)] and r2[id(leaf)] and not r2[id(solo)])

# ---- E3 reparent 拓扑变化必 miss ----
# leaf 脏 -> 传播到 (无子). 现把 leaf 挂到 root 下 (preserve_world 世界不变),
# 再让 root 脏 -> 新拓扑下 leaf 应脏; 旧缓存若不失效会漏传播.
br3 = mk_bridge()
r3 = M('r3', pos=(0, 0, 0))
c3 = M('c3', pos=(3, 0, 0))
s3 = M('s3', pos=(9, 9, 9))
for m in (r3, c3, s3):
    br3._sync_of(m)
br3._dirty_mask_batch(ents(r3, c3, s3))          # 首抓建缓存
c3.parent = r3                                    # reparent (世界位姿不变)
r3.position = P3(2, 2, 2)                         # root 脏 -> 新拓扑 c3 应传播脏
r3n = br3._dirty_mask_batch(ents(r3, c3, s3))
check("E3 reparent 后传播闭包刷新 (c3 随父脏)",
      r3n[id(c3)] is True and r3n[id(s3)] is False,
      str({k: v for k, v in r3n.items()}))

# ---- E4 子步间缓存命中 / sync 变 miss ----
br4 = mk_bridge()
m4 = M('m4', pos=(1, 1, 1))
br4._sync_of(m4)
d_first = br4._dirty_mask_batch(ents(m4))         # 建缓存
d_hit = br4._dirty_mask_batch(ents(m4))           # 应命中 (同结果)
check("E4 全净二次调用同结果 (命中路径)", d_hit == d_first and not d_hit[id(m4)])
sync4 = br4._sync_of(m4)
sync4[0] = (1.0, 1.0, 1.0)                        # 模拟 pre_step 推位姿后对齐 sync
# rows 仍 (1,1,1) == sync -> 不脏; 缓存须 miss 后重算出 False
d_after = br4._dirty_mask_batch(ents(m4))
check("E4b sync 变化后重算正确 (仍不脏)", d_after == {id(m4): False})
m4.position = P3(5, 5, 5)                         # 真脏
d_dirty = br4._dirty_mask_batch(ents(m4))
check("E4c 位姿变 -> miss -> 脏", d_dirty == {id(m4): True})

# ---- E5 缓存污染防护 ----
br5 = mk_bridge()
m5 = M('m5', pos=(1, 1, 1))
br5._sync_of(m5)
d5 = br5._dirty_mask_batch(ents(m5))
d5[id(m5)] = "POLLUTED"                           # 调用方乱写返回 dict
d5b = br5._dirty_mask_batch(ents(m5))
check("E5 写返回 dict 不污染缓存", d5b == {id(m5): False}, str(d5b))

# ---- E6 边界 ----
br6 = mk_bridge()
check("E6 空 entries -> {}", br6._dirty_mask_batch([]) == {})
m6 = M('m6')
br6._sync_of(m6)
check("E6b 单体全净", br6._dirty_mask_batch(ents(m6)) == {id(m6): False})
m6.rotation = P3(1.0, 0, 0)
check("E6c 单体旋转脏", br6._dirty_mask_batch(ents(m6)) == {id(m6): True})

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
