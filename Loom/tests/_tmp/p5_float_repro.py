# -*- coding: utf-8 -*-
"""P5 复现矩阵: "碰撞器启用+重力开=浮空" —— 用户视角操作序 (真 EditorApp+GL+桥).

背景: P2/p2_float_probe/p2_editor_probe 三路均未复现 (直接构造模型);
本探针以**用户真实操作序** (界面按钮的编辑器命令路径) 重放 ——
  加物体(_add_primitive) → 刚体(ed.add_rigidbody=检查器按钮同函数) →
  碰撞器(ed.toggle_collider=检查器按钮同函数, 含"开启"点击语义演绎) → 播放.

每个变体: 新场景 → setup → toggle_play → 逐帧 render(0.016) 采样 → 报告.
用法: py -3.12 tests\\_tmp\\p5_float_repro.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ['LOOM_NO_PARALLEL'] = '1'

import editor                                  # noqa: E402
import agent_commands as ac                    # noqa: E402
import physics_bridge as B                     # noqa: E402

editor.STATE_FILE = os.path.join(HERE, "ed_state_p5.json")

print("culverin 可用:", B.cv_available)
if not B.cv_available:
    print("!! 无库: 桥不可用, 本探针全部无效 (改在安装 culverin 的 py3.12 环境跑)")
    sys.exit(1)

FRAMES = 150                                   # 2.5s @60fps
DT = 1.0 / 60.0


def spy_entry(br, m):
    if br is None:
        return "桥=None"
    e = next((e for e in br._entries if e['model'] is m), None)
    if e is None:
        return "无体"
    try:
        act = br._w.is_active(e['handle'])
    except Exception:
        act = '?'
    return "motion=%s active=%s guard=%d id=%d" % (
        e['motion'], act, e.get('guard_left', -1), e['id'])


def run_case(name, setup, expect_fall=True, frames=FRAMES):
    ed = editor.EditorApp(1280, 800)
    ed._new_scene()
    setup(ed)
    target = ed.models[-1]
    y0 = target.position.y
    ed.toggle_play()
    br = ed._phys_bridge
    log = []
    for i in range(frames):
        ed.render(DT)
        if i % 25 == 0:
            e = next((e for e in br._entries if e['model'] is target), None)
            log.append("帧%03d y=%.4f vy=%s | entry=%s active=%d 体数=%d" % (
                i, target.position.y,
                ("%.4f" % target.rigidbody.velocity.y) if target.rigidbody else "无rb",
                ("motion=%s guard=%d id=%d" % (e['motion'], e.get('guard_left', -1), e['id']))
                if e else "无体",
                br.active_count, br.body_count))
    y1 = target.position.y
    vy = target.rigidbody.velocity.y if target.rigidbody else None
    # 先记后退场
    mov_summary = [
        "y0=%.3f y1=%.3f vy=%s active=%d 体数=%d" % (
            y0, y1, ("%.4f" % vy) if vy is not None else "无rb",
            br.active_count, br.body_count),
    ] + log
    ed.toggle_play()
    moved = abs(y1 - y0) > 1e-3
    verdict = ("↓↓下落OK" if (expect_fall and moved) else
               ("!★浮空★" if (expect_fall and not moved) else "(预期不落)"))
    print("[%s] %s" % (verdict, name))
    for line in mov_summary:
        print("   " + line)
    return y0, y1, moved


# ---------------- 变体矩阵 ----------------
def m_base(ed):
    ed._add_primitive('cube')
    m = ed.models[-1]
    ed.add_rigidbody(m)

def m_collider_click(ed):
    ed._add_primitive('sphere')
    m = ed.models[-1]
    ed.add_rigidbody(m)
    ed.toggle_collider(m)                      # enabled=True -> False
    ed.toggle_collider(m)                      # False -> True (用户"开启")

def m_collider_once(ed):
    ed._add_primitive('cube')
    m = ed.models[-1]
    ed.add_rigidbody(m)
    ed.toggle_collider(m)                      # 一次: enabled=True -> False

def m_with_ground(ed):
    ed._add_primitive('plane')
    ed._add_primitive('sphere')
    m = ed.models[-1]
    ed.add_rigidbody(m)

def m_scale3(ed):
    ed._add_primitive('cube')
    m = ed.models[-1]
    m.set_scale((3.0, 3.0, 3.0))
    ed.add_rigidbody(m)

def m_parented(ed):
    ed._add_primitive('cube')
    parent = ed.models[-1]
    parent.set_scale((4.0, 1.0, 4.0))
    ed._add_primitive('sphere')
    child = ed.models[-1]
    child.position = editor.Point3D(0.0, 1.5, 0.0)
    ed.set_parent(child, parent, preserve_world=False)
    ed.add_rigidbody(child)

def m_shape_none(ed):
    ed._add_primitive('sphere')
    m = ed.models[-1]
    m.collider.shape = 'none'
    ed.add_rigidbody(m)

_WIN = None


class WinStub:
    def __init__(self, ed):
        self.editor = ed
        self.viewport = None
    def close(self):
        pass


def m_eai_chain(ed):
    global _WIN
    _WIN = WinStub(ed)
    r1 = ac.dispatch('object_add', {'type': 'cube'}, _WIN)
    assert r1.get('ok'), r1
    r2 = ac.dispatch('object_select', {'name': ed.models[-1].name}, _WIN)
    r3 = ac.dispatch('rigidbody', {'action': 'add'}, _WIN)
    assert r3.get('ok'), r3
    r4 = ac.dispatch('collider', {}, _WIN)              # 缺 on = 切换一次
    r5 = ac.dispatch('collider', {'on': True}, _WIN)    # 显式开到启用
    print("   EAI: object_add=%s | rigidbody=%s | collider=%s | on=%s"
          % (r1.get('result'), r3.get('result'), r4.get('result'), r5.get('result')))

def m_gravity_toggle(ed):
    ed._add_primitive('cube')
    m = ed.models[-1]
    ed.add_rigidbody(m)
    ed.toggle_rigidbody_gravity(m)             # 到"不受重力"
    ed.toggle_rigidbody_gravity(m)             # 回到"受重力"


if __name__ == '__main__':
    print("=== P5 用户视角复现矩阵 (每个变体独立 EditorApp) ===")
    run_case("M0 基准: 立方体+刚体+默认碰撞器 (无地面)", m_base)
    run_case("M1 球体+刚体+碰撞器 关→开 两次", m_collider_click)
    run_case("M2 用户点一次\"碰撞器\"钮 (启用→禁用)", m_collider_once)
    run_case("M3 地面+球+刚体", m_with_ground)
    run_case("M4 scale=3 大盒+刚体", m_scale3)
    run_case("M5 父盒(4,1,4)+子球刚体", m_parented)
    run_case("M6 碰撞器 shape=none+刚体 (桥不建体已知差异)", m_shape_none)
    run_case("M7 EAI 命令链 (object_add→rigidbody→collider→play)", m_eai_chain)
    run_case("M8 刚体重力 开→关→开", m_gravity_toggle)

    print("\n== M9 播放中操作链 ==")
    ed2 = editor.EditorApp(1280, 800)
    ed2._new_scene()
    ed2._add_primitive('sphere')               # 只加物体
    m9 = ed2.models[-1]
    ed2.toggle_play()
    br = ed2._phys_bridge
    ed2.add_rigidbody(m9)                      # 播放中加刚体
    print("   播放中 add_rigidbody 后: %s | active=%d" % (spy_entry(br, m9), br.active_count))
    for i in range(90):
        ed2.render(DT)
        if i % 30 == 0:
            print("   帧%03d y=%.4f vy=%.4f | %s | active=%d"
                  % (i, m9.position.y, m9.rigidbody.velocity.y,
                     spy_entry(br, m9), br.active_count))
    ed2.toggle_collider(m9)                    # 播放中关碰撞器 (有体->无体)
    print("   播放中 toggle_collider 后: %s" % spy_entry(br, m9))
    for i in range(90):
        ed2.render(DT)
        if i % 30 == 0:
            print("   帧%03d y=%.4f vy=%.4f | %s | active=%d"
                  % (i, m9.position.y, m9.rigidbody.velocity.y,
                     spy_entry(br, m9), br.active_count))
    ed2.toggle_play()
    print("=== 完成 ===")
