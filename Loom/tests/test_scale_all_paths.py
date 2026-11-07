# -*- coding: utf-8 -*-
"""test_scale_all_paths.py — scale 的**所有**写入路径都归一化到 3 分量.

背景 (_fix_summary §5 遗留 2)
----------------------------
scan_01 P-05 首轮只修了 GameObject.scale setter / 构造入口; 直写
m.transform.scale = (1, 2) 仍可把短元组塞进 TransformComponent._scale, 随后
mat4_scale / SoA 快照按 s[0]/s[1]/s[2] 取分量 -> IndexError。

F8 已在 loom_components.TransformComponent 的构造器与 scale setter 共用
_normalize_scale。本文件把**所有公开写入路径**逐条锁死, 防止以后新增旁路:
  A: TransformComponent 构造入口 (短元组/None/Point3D)。
  B: TransformComponent.scale 直写 (原漏洞路径)。
  C: GameObject 构造入口。
  D: GameObject.scale setter。
  E: GameObject.set_scale 便捷方法。
  F: 非法输入 (长度 0/>3/非数值/标量) 在所有入口都显式 ValueError, 且旧值不被破坏。
  G: 直写后的矩阵/批量 SoA 路径不再 IndexError, 对角数值正确。
  H: 直写仍 bump TransformComponent._xform_gen (编辑态插值对齐依赖)。
  I: 父链世界缩放合成使用补齐后的 3 分量。

运行: python tests\test_scale_all_paths.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

import numpy as np

import engine as E
from mesh import create_cube
from loom_components import TransformComponent

E.GLEngine._build_gpu = lambda self, m: None

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name
          + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


def mk(name='S', scale=(1, 1, 1)):
    m = E.GameObject(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                     name=name, scale=scale)
    m.guid = uuid.uuid4().hex
    return m


def new_eng(models):
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = models
    e.materials = []
    e.lights = []
    e.cameras = []
    e.active_camera = None
    e.current_model_index = 0
    return e


def diag3(M):
    return tuple(round(float(v), 12) for v in np.diag(M)[:3])


def _raises_value(fn):
    try:
        fn()
        return False
    except ValueError:
        return True
    except TypeError:
        return True


# ====================================================================
# A: TransformComponent 构造入口
# ====================================================================
def t_transform_ctor():
    print("=== A: TransformComponent 构造入口 ===")
    t = TransformComponent(E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), (1, 2))
    check("[A] ctor (1,2) -> (1,2,1)", tuple(t.scale) == (1.0, 2.0, 1.0), t.scale)
    t = TransformComponent(E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), (3,))
    check("[A] ctor (3,) -> (3,1,1)", tuple(t.scale) == (3.0, 1.0, 1.0), t.scale)
    t = TransformComponent(E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), None)
    check("[A] ctor None -> (1,1,1)", tuple(t.scale) == (1.0, 1.0, 1.0), t.scale)
    t = TransformComponent(E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                           E.Point3D(4, 5, 6))
    check("[A] ctor Point3D", tuple(t.scale) == (4.0, 5.0, 6.0), t.scale)


# ====================================================================
# B: TransformComponent.scale 直写 (原漏洞路径)
# ====================================================================
def t_transform_setter():
    print("=== B: TransformComponent.scale 直写 ===")
    t = TransformComponent(E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), (1, 1, 1))
    t.scale = (1, 2)
    check("[B] 直写 (1,2) -> (1,2,1)", tuple(t.scale) == (1.0, 2.0, 1.0), t.scale)
    t.scale = [7]
    check("[B] 直写 list [7] -> (7,1,1)", tuple(t.scale) == (7.0, 1.0, 1.0), t.scale)
    t.scale = (1, 2, 3)
    check("[B] 直写 3 元组原样", tuple(t.scale) == (1.0, 2.0, 3.0), t.scale)

    m = mk()
    m.transform.scale = (1, 2)
    check("[B] m.transform.scale 直写 -> (1,2,1)",
          tuple(m.scale) == (1.0, 2.0, 1.0), m.scale)


# ====================================================================
# C/D/E: GameObject 构造 / setter / set_scale
# ====================================================================
def t_gameobject_paths():
    print("=== C/D/E: GameObject 入口 ===")
    m = mk('C', scale=(1, 2))
    check("[C] ctor scale=(1,2) -> (1,2,1)",
          tuple(m.scale) == (1.0, 2.0, 1.0), m.scale)

    m = mk('D')
    m.scale = (1, 2)
    check("[D] m.scale=(1,2) -> (1,2,1)", tuple(m.scale) == (1.0, 2.0, 1.0), m.scale)

    m = mk('E')
    m.set_scale((1, 2))
    check("[E] set_scale((1,2)) -> (1,2,1)",
          tuple(m.scale) == (1.0, 2.0, 1.0), m.scale)
    m.set_scale(E.Point3D(2, 3, 4))
    check("[E] set_scale(Point3D)", tuple(m.scale) == (2.0, 3.0, 4.0), m.scale)


# ====================================================================
# F: 非法输入在所有入口显式报错 + 旧值不被破坏
# ====================================================================
def t_reject_bad_all_paths():
    print("=== F: 非法输入显式 ValueError (所有入口) ===")
    bads = [(1, 2, 3, 4), (), 'abc', 5, [1, 2, 3, 4]]
    t = TransformComponent(E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), (2, 2, 2))
    for bad in bads:
        ok = _raises_value(lambda bad=bad: setattr(t, 'scale', bad))
        check("[F] TransformComponent 拒绝 %r" % (bad,), ok)
    check("[F] 报错后 TransformComponent 旧值不变",
          tuple(t.scale) == (2.0, 2.0, 2.0), t.scale)

    m = mk('F', scale=(2, 2, 2))
    for bad in bads:
        ok = _raises_value(lambda bad=bad: setattr(m, 'scale', bad))
        check("[F] GameObject.scale 拒绝 %r" % (bad,), ok)
    check("[F] 报错后 GameObject 旧值不变",
          tuple(m.scale) == (2.0, 2.0, 2.0), m.scale)
    for bad in bads:
        ok = _raises_value(lambda bad=bad: setattr(m.transform, 'scale', bad))
        check("[F] m.transform.scale 拒绝 %r" % (bad,), ok)


# ====================================================================
# G: 矩阵 / 批量 SoA 路径不再 IndexError
# ====================================================================
def t_matrix_after_direct_write():
    print("=== G: 直写后矩阵路径 ===")
    m = mk('M')
    m.transform.scale = (1, 2)              # 原漏洞: 短元组直写
    e = new_eng([m])
    try:
        M = e.model_world_matrix(m)
        ok = True
        err = None
    except Exception as ex:                 # noqa: BLE001
        ok = False
        err = repr(ex)
        M = None
    check("[G] model_world_matrix 不抛 IndexError", ok, err)
    if ok:
        check("[G] 世界矩阵对角 = (1,2,1)", diag3(M) == (1.0, 2.0, 1.0), diag3(M))
    try:
        W = e.compute_world_matrices([m])
        ok2 = True
        err2 = None
    except Exception as ex:                 # noqa: BLE001
        ok2 = False
        err2 = repr(ex)
        W = None
    check("[G] compute_world_matrices 不抛 IndexError", ok2, err2)
    if ok2:
        check("[G] 批量对角 = (1,2,1)", diag3(W[0]) == (1.0, 2.0, 1.0), diag3(W[0]))


# ====================================================================
# H: 直写 bump 变换代
# ====================================================================
def t_gen_bump():
    print("=== H: 直写 bump _xform_gen ===")
    m = mk('G')
    g0 = E.TransformComponent._xform_gen
    m.transform.scale = (1, 2)
    check("[H] m.transform.scale 直写 bump 1 次",
          E.TransformComponent._xform_gen == g0 + 1,
          E.TransformComponent._xform_gen - g0)
    g1 = E.TransformComponent._xform_gen
    m.scale = (2, 2, 2)
    check("[H] m.scale setter bump 1 次",
          E.TransformComponent._xform_gen == g1 + 1,
          E.TransformComponent._xform_gen - g1)


# ====================================================================
# I: 父链世界缩放
# ====================================================================
def t_parent_chain_scale():
    print("=== I: 父链世界缩放 (短元组直写) ===")
    p = mk('P', scale=(2,))
    c = mk('C')
    c.transform.scale = (1, 2)              # 直写短元组
    e = new_eng([p, c])
    e.set_parent(c, p, preserve_world=False)
    ws = e.world_scale(c)
    got = (round(ws.x, 12), round(ws.y, 12), round(ws.z, 12))
    check("[I] 父(2,) * 子(1,2,1) -> 世界 (2,2,1)", got == (2.0, 2.0, 1.0), got)


if __name__ == "__main__":
    print("========== scale 所有写入路径归一化 (_fix_summary §5 遗留 2) ==========")
    t_transform_ctor()
    t_transform_setter()
    t_gameobject_paths()
    t_reject_bad_all_paths()
    t_matrix_after_direct_write()
    t_gen_bump()
    t_parent_chain_scale()
    print()
    if _fails:
        print("总结果: FAIL", _fails)
        sys.exit(1)
    print("总结果: ALL PASS")
