# -*- coding: utf-8 -*-
"""
test_scale_normalize.py — GameObject.scale 短元组归一化回归
(scan_01_core P-05, 2026-11-07)

背景
----
TransformComponent.scale / GameObject.scale 原样保存 tuple(v)。矩阵路径
(mat4_scale(s[0],s[1],s[2])) 与 SoA 快照 (_transform_snapshot 的 s[0..2])
都按 3 分量取; 一旦 scale=(1,2) 这类短元组进入场景, 渲染/物理帧内抛
IndexError: tuple index out of range。

修复: GameObject.scale setter (与构造入口) 统一归一化为 3 元组, 缺省分量补
1.0; 长度 >3 / 非数值序列显式 ValueError (不再把坏值拖到帧内炸)。

本文件断言:
  A: setter 短元组补齐 (1,2)->(1,2,1), (3,)->(3,1,1), 3 元组原样。
  B: 构造入口 scale=(1,2) 同样补齐。
  C: model_world_matrix / compute_world_matrices 对补齐后的缩放不再 IndexError,
     且缩放数值正确 (矩阵对角 = 缩放)。
  D: 非法输入 (长度 0/4、非数值、标量) 显式 ValueError。
  E: set_scale 便捷方法同走归一化; 写入仍 bump TransformComponent._xform_gen。
  F: 父链世界缩放合成使用补齐后的分量。

运行: python tests\test_scale_normalize.py   (无头, 无 GPU)
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

E.GLEngine._build_gpu = lambda self, m: None

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def mk(name, scale=(1, 1, 1)):
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


# ====================================================================
# A: setter 归一化
# ====================================================================
def t_setter_pad():
    m = mk('S')
    m.scale = (1, 2)
    check("[A] (1,2) -> (1,2,1)", tuple(m.scale) == (1.0, 2.0, 1.0), m.scale)
    m.scale = (3,)
    check("[A] (3,) -> (3,1,1)", tuple(m.scale) == (3.0, 1.0, 1.0), m.scale)
    m.scale = (1, 2, 3)
    check("[A] 3 元组原样", tuple(m.scale) == (1.0, 2.0, 3.0), m.scale)
    m.scale = E.Point3D(4, 5, 6)
    check("[A] Point3D 输入", tuple(m.scale) == (4.0, 5.0, 6.0), m.scale)


# ====================================================================
# B: 构造入口归一化
# ====================================================================
def t_ctor_pad():
    m = mk('C', scale=(1, 2))
    check("[B] ctor scale=(1,2) -> (1,2,1)", tuple(m.scale) == (1.0, 2.0, 1.0), m.scale)
    m2 = mk('C2', scale=(7,))
    check("[B] ctor scale=(7,) -> (7,1,1)", tuple(m2.scale) == (7.0, 1.0, 1.0), m2.scale)


# ====================================================================
# C: 矩阵路径不再 IndexError, 数值正确
# ====================================================================
def t_matrix_path():
    m = mk('M', scale=(1, 2))
    e = new_eng([m])
    try:
        M = e.model_world_matrix(m)
        ok = True
        err = None
    except Exception as ex:
        ok = False
        err = repr(ex)
        M = None
    check("[C] model_world_matrix 不抛 IndexError", ok, err)
    if ok:
        check("[C] 世界矩阵对角 = (1,2,1)", diag3(M) == (1.0, 2.0, 1.0), diag3(M))
    try:
        W = e.compute_world_matrices([m])
        ok2 = True
        err2 = None
    except Exception as ex:
        ok2 = False
        err2 = repr(ex)
        W = None
    check("[C] compute_world_matrices (SoA/批量路径) 不抛 IndexError", ok2, err2)
    if ok2:
        check("[C] 批量世界矩阵对角 = (1,2,1)", diag3(W[0]) == (1.0, 2.0, 1.0), diag3(W[0]))


# ====================================================================
# D: 非法输入显式报错
# ====================================================================
def t_reject_bad():
    m = mk('B')
    for bad in ((1, 2, 3, 4), (), 'abc', 5, [1, 2, 3, 4]):
        try:
            m.scale = bad
            raised = False
        except (ValueError, TypeError):
            raised = True
        check("[D] 非法 scale=%r 显式报错" % (bad,), raised)
    check("[D] 报错后原值未被破坏", tuple(m.scale) == (1.0, 1.0, 1.0), m.scale)


# ====================================================================
# E: set_scale + 变换代数
# ====================================================================
def t_set_scale_and_gen():
    m = mk('G')
    g0 = E.TransformComponent._xform_gen
    m.set_scale((1, 2))
    check("[E] set_scale 归一化", tuple(m.scale) == (1.0, 2.0, 1.0), m.scale)
    check("[E] scale 写入 bump _xform_gen", E.TransformComponent._xform_gen == g0 + 1,
          E.TransformComponent._xform_gen - g0)


# ====================================================================
# F: 父链世界缩放合成
# ====================================================================
def t_world_scale_chain():
    # 保世界挂父: 局部被换算, 世界缩放不变 (1,2,1)
    p = mk('P', scale=(2,))
    c = mk('C', scale=(1, 2))
    e = new_eng([p, c])
    e.set_parent(c, p)
    ws = e.world_scale(c)
    check("[F] 保世界挂父后世界缩放仍 (1,2,1)",
          (round(ws.x, 12), round(ws.y, 12), round(ws.z, 12)) == (1.0, 2.0, 1.0),
          (ws.x, ws.y, ws.z))
    check("[F] 局部缩放换算 (0.5,2,1)",
          tuple(round(float(v), 12) for v in c.scale) == (0.5, 2.0, 1.0), c.scale)
    # 不保世界挂父: 局部原样 (1,2,1) -> 世界 = 父*子 = (2,2,1)
    p2 = mk('P2', scale=(2,))
    c2 = mk('C2', scale=(1, 2))
    e2 = new_eng([p2, c2])
    e2.set_parent(c2, p2, preserve_world=False)
    ws2 = e2.world_scale(c2)
    check("[F] 不保世界: 父(2,) 子(1,2) 世界缩放 = (2,2,1)",
          (round(ws2.x, 12), round(ws2.y, 12), round(ws2.z, 12)) == (2.0, 2.0, 1.0),
          (ws2.x, ws2.y, ws2.z))


if __name__ == "__main__":
    print("========== GameObject.scale 短元组归一化 (scan_01 P-05) ==========")
    t_setter_pad()
    t_ctor_pad()
    t_matrix_path()
    t_reject_bad()
    t_set_scale_and_gen()
    t_world_scale_chain()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
