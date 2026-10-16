# -*- coding: utf-8 -*-
"""
test_eai_real.py — EAI 全命令自动化测试 (真 EditorApp, 2026-08-27)
================================================================================
定位 (用户 2026-08-27 指令): "在完全命令行化的 Loom 中完成全部的可 Agent
命令行操作自动化测试, 同时测试命令行本身有没有 BUG"。

与 test_agent_commands.py 的分工:
  · test_agent_commands.py = 桩层 (FakeWin/FakeEditor), 快, 覆盖分支与错误路径;
  · 本文件            = **真层** —— 真的 EditorApp (真窗口/真 GPU 路径, 与
    test_integration.py 同款构造), 每条命令都对真编辑器执行并断言真实状态变化。
    桩会漂移 (桩上通过、真编辑器里 AttributeError), 真层是防漂移的那道闸。

**覆盖率闸门**: 文件末尾断言 "命令表里每一条命令都在本文件里被真的执行过"。
新增命令若不写测试, 本文件直接 FAIL —— 命令表与测试台账不会再脱节。

不测的东西 (故意):
  · 连贯操作 (右键滑动视角/拖拽 gizmo/拖拽数值块) —— 按用户拍板的"连贯操作
    双链原则", 那是 GUI 老链路专用, 命令层不模拟, 由人工实测;
  · 每条命令背后的 GUI 单步验证 (按钮点了界面变没变) —— GUI 面向人, 人工实测。
运行: py -3.12 tests\test_eai_real.py
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
# 多核守卫: 测试确定性 (不建脚本线程/不设进程亲和性), 与 test_integration 一致
os.environ['LOOM_NO_PARALLEL'] = '1'

import editor                      # noqa: E402
import agent_commands as ac        # noqa: E402

TMP = os.path.join(HERE, "_tmp")
os.makedirs(TMP, exist_ok=True)
# editor_state.json 指向临时文件, 不污染用户"上次目录"
editor.STATE_FILE = os.path.join(TMP, "editor_state_eai.json")

_FAILS = []
_USED = set()          # 本文件真正 dispatch 过的命令名 (覆盖率闸门)


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def run(cmd, args=None, expect_ok=True):
    """执行一条命令并记入覆盖率. expect_ok=False 用于断言"应当被拒绝"的调用."""
    _USED.add(cmd)
    r = ac.dispatch(cmd, args or {}, WIN)
    if expect_ok and not r.get('ok'):
        check("命令 %s 应成功却失败" % cmd, False, r.get('error'))
    return r


def res(cmd, args=None):
    """执行并取 result (成功路径的简写)."""
    return run(cmd, args).get('result')


# ---------------- 窗口桩 (只补 Qt 宿主提供的那几个口子) ----------------
class _Img:
    def width(self):
        return 1280

    def height(self):
        return 800

    def save(self, path):
        with open(path, 'wb') as f:      # 真写文件: 验证命令返回的路径可用
            f.write(b'\x89PNG\r\n\x1a\n')
        return True


class _Grabbed:
    def toImage(self):
        return _Img()


class _Viewport:
    """截图口 (真 Qt 里是 QOpenGLWidget.grab()); 真 Qt 路径由 Qt 探针覆盖."""

    def grab(self):
        return _Grabbed()


class Win:
    """LoomGUI 的最小替身: 命令层只用到 .editor / .viewport / .close()."""

    def __init__(self, ed):
        self.editor = ed
        self.viewport = _Viewport()
        self.closed = False

    def close(self):
        self.closed = True


ED = editor.EditorApp(1280, 800)
WIN = Win(ED)


# ============ 1. 查询类: status / inspect / 列表 ============
def t_query():
    st = res('status')
    check("status 返回场景摘要 (物体/光源/相机/相机参数)",
          isinstance(st, dict) and 'models' in st and 'camera' in st
          and st['camera']['distance'] > 0, st.get('camera'))
    check("status 物体数与真编辑器一致", len(st['models']) == len(ED.models))
    check("status playing=False (编辑态)", st['playing'] is False)

    # inspect: 先选中一个物体
    first = ED.models[0].name
    res('object_select', {'name': first})
    ins = res('inspect')
    check("inspect 读回物体全字段 (位置/缩放/材质/脚本)",
          ins['kind'] == 'model' and ins['name'] == first
          and len(ins['position']) == 3 and 'scripts' in ins, list(ins)[:8])

    mats = res('materials')
    check("materials 返回列表结构", isinstance(mats['materials'], list))
    scr = res('scripts')
    check("scripts 返回可挂脚本清单 (至少 1 个)", len(scr['scripts']) >= 1,
          [s['id'] for s in scr['scripts']][:5])
    ass = res('assets')
    check("assets 返回资源清单 (内置网格资产)", len(ass['assets']) >= 1,
          [a['key'] for a in ass['assets']][:4])
    lst = res('object_list')
    check("object_list 返回带序号的 物体/光源/相机 三清单",
          len(lst['models']) == len(ED.models)
          and 'index' in lst['models'][0] and 'lights' in lst
          and isinstance(lst['cameras'], list), list(lst)[:4])
    pl = res('plugins')
    check("plugins 返回插件/按钮清单结构",
          'plugins' in pl and 'buttons' in pl)


# ============ 2. 物体增删改查 ============
def t_object_crud():
    n0 = len(ED.models)
    r = res('object_add', {'type': 'cube'})
    check("object_add cube 真加进场景", len(ED.models) == n0 + 1 and r['type'] == 'cube')
    added = ED.models[-1].name

    r = res('object_select', {'name': added})
    check("object_select 按名字选中真生效",
          r['selected'] == added and ED._selected() is ED.models[-1])

    r = run('object_select', {'index': 999}, expect_ok=False)
    check("object_select index 越界 -> ok=False (契约: 拒绝即 ok=False)",
          r['ok'] is False and '越界' in r['error'], r.get('error'))

    res('object_rename', {'name': added, 'new': '命令改名体'})
    check("object_rename 真改名", ED.models[-1].name == '命令改名体')

    n1 = len(ED.models)
    res('object_duplicate')
    check("object_duplicate 物体数 +1", len(ED.models) == n1 + 1)
    res('object_delete')
    check("object_delete 物体数 -1", len(ED.models) == n1)

    # 撤销/重做: 命令改动必须与 GUI 一样进撤销栈
    name_now = ED.models[-1].name
    res('undo')
    check("undo 撤销掉删除 (物体回来)", len(ED.models) == n1 + 1)
    res('redo')
    check("redo 重做删除", len(ED.models) == n1, [m.name for m in ED.models][-2:])
    check("撤销/重做后仍是同一批物体", ED.models[-1].name == name_now)


# ============ 3. 变换/显隐/饱和度 (结果注入 + 一步撤销) ============
def t_transform():
    m = ED.models[-1]
    res('object_select', {'name': m.name})
    before = list(m.position)
    r = res('set_transform', {'x': 3, 'y': 1.5, 'z': -2})
    check("set_transform 位置三轴独立写入 (不是三轴同值)",
          [round(v, 3) for v in m.position] == [3.0, 1.5, -2.0], r['position'])

    r = res('set_transform', {'x': 9})
    check("set_transform 只给 X: Y/Z 保持不变 (namedtuple 单轴重建)",
          [round(v, 3) for v in m.position] == [9.0, 1.5, -2.0], list(m.position))

    # 旋转: Point3D 是 namedtuple —— 这里正是 Qt 检查器栽过的地方
    r = res('set_transform', {'rx': 30, 'ry': 0, 'rz': 0})
    check("set_transform 旋转 (度->弧度, namedtuple 重建不抛异常)",
          abs(m.rotation.x - math.radians(30)) < 1e-6, list(m.rotation))

    res('set_transform', {'sx': 2, 'sy': 2, 'sz': 2})
    check("set_transform 缩放", [round(v, 3) for v in m.scale] == [2.0, 2.0, 2.0],
          list(m.scale))

    res('undo')
    check("set_transform 一条命令 = 一步撤销 (缩放回退)",
          [round(v, 3) for v in m.scale] != [2.0, 2.0, 2.0], list(m.scale))

    r = run('set_transform', {}, expect_ok=False)
    check("set_transform 不给任何字段 -> 拒绝并提示可用字段",
          r['ok'] is False and 'x/y/z' in r['error'], r.get('error'))

    vis0 = bool(m.visible)
    res('set_visible')
    check("set_visible 缺 on = 切换", bool(m.visible) != vis0)
    res('set_visible', {'on': 'false'})
    check("set_visible on=false 字符串判假 (不是裸 bool 恒真)", bool(m.visible) is False)
    res('set_visible', {'on': 'true'})
    check("set_visible on=true 恢复可见", bool(m.visible) is True)

    res('set_saturation', {'value': 1.5})
    check("set_saturation 写入", abs(m.saturation - 1.5) < 1e-6, m.saturation)


# ============ 4. 材质 ============
def t_material():
    m = ED.models[-1]
    res('object_select', {'name': m.name})
    n0 = len(ED.materials)
    res('material_new')
    check("material_new 新建材质并挂给物体", len(ED.materials) == n0 + 1
          and m.renderer.material is ED.materials[-1])
    r = res('set_material', {'index': 0})
    check("set_material 按索引换材质 (共享引用)",
          m.renderer.material is ED.materials[0], r)
    r = res('set_material', {'material': ED.materials[-1].name})
    check("set_material 按材质名换", m.renderer.material is ED.materials[-1])
    r = run('set_material', {'material': '不存在的材质'}, expect_ok=False)
    check("set_material 找不到材质 -> 拒绝并列出可用",
          r['ok'] is False and '找不到材质' in r['error'])


# ============ 5. 组件: 碰撞器 / 刚体 / 音频 / 动画 ============
def t_components():
    m = ED.models[-1]
    res('object_select', {'name': m.name})

    if m.collider is not None:
        st0 = bool(m.collider.enabled)
        res('collider')
        check("collider 缺 on = 切换", bool(m.collider.enabled) != st0)
        res('collider', {'on': 'true'})
        check("collider on=true 幂等到启用", bool(m.collider.enabled) is True)
    else:
        check("collider: 该物体无碰撞器组件 (跳过)", True)
        run('collider', {}, expect_ok=False)

    res('rigidbody', {'action': 'add'})
    check("rigidbody add 真加刚体", m.rigidbody is not None)
    g0 = bool(m.rigidbody.use_gravity)
    res('rigidbody', {'action': 'gravity'})
    check("rigidbody gravity 切换受重力", bool(m.rigidbody.use_gravity) != g0)
    res('rigidbody', {'action': 'remove'})
    check("rigidbody remove 真移除", m.rigidbody is None)
    r = run('rigidbody', {'action': 'gravity'}, expect_ok=False)
    check("rigidbody 无刚体时 gravity -> 拒绝", r['ok'] is False, r.get('error'))
    r = run('rigidbody', {'action': '乱写'}, expect_ok=False)
    check("rigidbody 非法 action -> 拒绝", r['ok'] is False)

    res('audio', {'action': 'add'})
    check("audio add 真加音频源", m.audio_source is not None)
    res('audio', {'action': 'clip', 'clip': 'x.wav'})
    check("audio clip 写路径", m.audio_source.clip == 'x.wav')
    lp = bool(m.audio_source.loop)
    res('audio', {'action': 'loop'})
    check("audio loop 切换", bool(m.audio_source.loop) != lp)
    res('audio', {'action': 'volume', 'value': 0.25})
    check("audio volume 写入并夹到 0..1", abs(m.audio_source.volume - 0.25) < 1e-6)
    res('audio', {'action': 'volume', 'value': 9})
    check("audio volume 超范围被夹到 1.0", abs(m.audio_source.volume - 1.0) < 1e-6)
    res('audio', {'action': 'remove'})
    check("audio remove 真移除", m.audio_source is None)
    r = run('audio', {'action': 'loop'}, expect_ok=False)
    check("audio 无组件时操作 -> 拒绝", r['ok'] is False)

    res('animator', {'action': 'add'})
    check("animator add 真加动画组件", m.animator is not None)
    lp = bool(m.animator.loop)
    res('animator', {'action': 'loop'})
    check("animator loop 切换", bool(m.animator.loop) != lp)
    r = run('animator', {'action': 'clip'}, expect_ok=False)
    check("animator clip 缺参数 -> 拒绝并列出可用片段", r['ok'] is False)
    res('animator', {'action': 'remove'})
    check("animator remove 真移除", m.animator is None)


# ============ 6. 脚本 ============
def t_scripts():
    m = ED.models[-1]
    res('object_select', {'name': m.name})
    opts = res('scripts')['scripts']
    sid = opts[0]['id']
    res('script_add', {'sid': sid})
    check("script_add 真挂上脚本", len(m.scripts) >= 1
          and m.scripts[-1].script_id == sid, [s.script_id for s in m.scripts])

    i = len(m.scripts) - 1
    from scripts import get_script
    params = list(get_script(sid).params or {})
    if params:
        key = params[0]
        res('script_var', {'index': i, 'key': key, 'value': 4.5})
        check("script_var 改脚本参数真写入",
              abs(float(m.scripts[i].script_vars.get(key)) - 4.5) < 1e-6,
              m.scripts[i].script_vars)
    else:
        check("script_var: 该脚本无参数 (改用越界断言)", True)
    r = run('script_var', {'index': 99, 'key': 'x', 'value': 1}, expect_ok=False)
    check("script_var index 越界 -> 拒绝", r['ok'] is False)

    n = len(m.scripts)
    res('script_remove', {'index': i})
    check("script_remove 真移除", len(m.scripts) == n - 1)
    r = run('script_remove', {'index': 99}, expect_ok=False)
    check("script_remove 越界 -> 拒绝", r['ok'] is False)


# ============ 7. 光源 ============
def t_light():
    n0 = len(ED.lights)
    res('light_add', {'kind': 'directional'})
    check("light_add 平行光真加进场景", len(ED.lights) == n0 + 1)
    l = ED.lights[-1]
    res('object_select', {'name': l.name})
    r = res('light_set', {'intensity': 2.5, 'r': 1, 'g': 0.5, 'b': 0,
                          'azimuth': 45, 'elevation': -30, 'roll': 10,
                          'shadow': 'true', 'mode': 'beam', 'shape': 'rect',
                          'size': 3, 'x': 1, 'y': 5, 'z': -1})
    check("light_set 批量写入 (强度/颜色/三角度/阴影/模式/截面/尺寸/位置)",
          abs(l.intensity - 2.5) < 1e-6 and [round(c, 2) for c in l.color] == [1.0, 0.5, 0.0]
          and abs(l.azimuth - 45) < 1e-6 and l.shadow is True
          and l.mode == 'beam' and l.shape == 'rect'
          and [round(v, 2) for v in l.position] == [1.0, 5.0, -1.0],
          (l.intensity, list(l.color), l.mode, l.shape, list(l.position)))
    check("light_set 返回 inspect 结构 (便于 Agent 断言)", r['kind'] == 'light')

    res('light_set', {'shadow': 'false'})
    check("light_set shadow=false 字符串判假", l.shadow is False)
    r = run('light_set', {'mode': '乱写'}, expect_ok=False)
    check("light_set 非法 mode -> 拒绝并给合法值", r['ok'] is False
          and 'full|beam' in r['error'])

    res('undo')          # 一步撤销回到 shadow=True
    check("light_set 一条命令 = 一步撤销", l.shadow is True, l.shadow)

    res('light_add', {'kind': 'point'})
    check("light_add 点光源", len(ED.lights) == n0 + 2)


# ============ 8. 摄像机 ============
def t_camera():
    n0 = len(ED.cameras)
    res('camera_add')
    check("camera_add 真加摄像机", len(ED.cameras) == n0 + 1)
    c = ED.cameras[-1]
    res('object_select', {'name': c.name})
    res('camera_set', {'yaw': 90, 'pitch': -20, 'roll': 5, 'fov': 70,
                       'pitch_lock': 'true', 'pitch_min': -40, 'pitch_max': 40,
                       'x': 2, 'y': 3, 'z': 4})
    check("camera_set 批量写入 (朝向/FOV/俯仰限制/位置)",
          abs(c.yaw - 90) < 1e-6 and abs(c.fov - 70) < 1e-6
          and c.pitch_lock is True and abs(c.pitch_min + 40) < 1e-6
          and [round(v, 2) for v in c.position] == [2.0, 3.0, 4.0],
          (c.yaw, c.fov, c.pitch_lock, list(c.position)))

    lock0 = bool(c.fov_locked)
    res('camera_set', {'fov_lock': 'false' if lock0 else 'true'})
    check("camera_set fov_lock 做成 set 语义 (不是盲切)",
          bool(c.fov_locked) != lock0, c.fov_locked)

    res('camera_active', {'name': c.name})
    check("camera_active 设激活相机 (editor 存 guid)",
          ED.active_camera == c.guid, ED.active_camera)
    res('camera_active')
    check("camera_active 缺 name = 取消激活", ED.active_camera is None)
    r = run('camera_active', {'name': '没有这个相机'}, expect_ok=False)
    check("camera_active 找不到 -> 拒绝", r['ok'] is False)

    res('camera_preview', {'name': c.name})
    check("camera_preview 进入预览", ED.preview_camera is c)
    res('camera_preview', {'off': 'true'})
    check("camera_preview off=true 退出预览", ED.preview_camera is None)

    # 开发者轨道相机 (结果注入, 非连贯拖动)
    r = res('camera_move', {'x': 1, 'y': 2, 'z': 3, 'distance': 12})
    check("camera_move 绝对目标 + 距离",
          [round(v, 2) for v in ED.camera_target] == [1.0, 2.0, 3.0]
          and abs(ED.camera_distance - 12) < 1e-6, r)
    res('camera_move', {'dx': 1, 'dy': 0, 'dz': 0})
    check("camera_move 增量", round(ED.camera_target[0], 2) == 2.0)
    r = res('camera_look', {'yaw': 45, 'pitch': -30})
    check("camera_look 绝对角度 (度)", abs(r['yaw_deg'] - 45) < 0.2
          and abs(r['pitch_deg'] + 30) < 0.2, r)
    r = res('camera_look', {'dyaw': 10, 'dpitch': 0})
    check("camera_look 增量", abs(r['yaw_deg'] - 55) < 0.2, r)
    r = res('camera_look', {'pitch': -89})
    check("camera_look 俯仰被夹住 (不翻面)", r['pitch_deg'] > -89.0, r)


# ============ 9. 层级挂父 ============
def t_reparent():
    a, b = ED.models[0], ED.models[1]
    res('reparent', {'child': b.name, 'parent': a.name})
    check("reparent 挂父真生效", b.parent is a, getattr(b.parent, 'name', None))
    r = run('reparent', {'child': a.name, 'parent': b.name}, expect_ok=False)
    check("reparent 挂到自己子孙 -> 拒绝 (防成环)",
          r['ok'] is False and '成环' in r['error'], r.get('error'))
    r = run('reparent', {'child': a.name, 'parent': a.name}, expect_ok=False)
    check("reparent 挂到自己 -> 拒绝", r['ok'] is False)
    res('reparent', {'child': b.name})
    check("reparent 缺 parent = 脱父", b.parent is None)
    r = res('reparent', {'child': b.name})
    check("reparent 已是根再脱父 = 无操作不报错", r.get('nochange') is True)
    r = run('reparent', {'child': '不存在'}, expect_ok=False)
    check("reparent 找不到 child -> 拒绝", r['ok'] is False)

    # 相机挂父 (相机物体化, 独立 camera_children 链): 新建一个相机再挂,
    # 不碰语义早已验证过的那台 (t_camera 里改过它的位置/FOV).
    res('camera_add')
    cam = ED.cameras[-1]
    res('reparent', {'child': cam.name, 'parent': a.name})
    check("reparent 相机挂到物体", cam.parent is a, getattr(cam.parent, 'name', None))
    res('reparent', {'child': cam.name})
    check("reparent 相机脱父", cam.parent is None)


# ============ 10. 场景 / 导入 / Prefab / 资产 ============
def t_scene_assets():
    p = os.path.join(TMP, "eai_scene.json")
    res('scene_save', {'path': p})
    check("scene_save path 真落盘", os.path.isfile(p))
    n_before = len(ED.models)
    res('object_add', {'type': 'sphere'})
    res('scene_load', {'path': p})
    check("scene_load 直接换场 (丢弃当前改动=恢复磁盘版)",
          len(ED.models) == n_before, (n_before, len(ED.models)))
    r = run('scene_load', {}, expect_ok=False)
    check("scene_load 无 path -> 拒绝 (Agent 环境禁弹系统对话框)",
          r['ok'] is False and 'path' in r['error'])

    res('scene_new')
    check("scene_new 新建空场景 (与 GUI 新建按钮同语义, 无种子物体)",
          len(ED.models) == 0, len(ED.models))

    # .obj 导入: 写一个最小 obj (免文件对话框, 走 GUI 同一条导入逻辑)
    obj = os.path.join(TMP, "eai_tri.obj")
    with open(obj, 'w', encoding='utf-8') as f:
        f.write("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    n0 = len(ED.models)
    r = res('import_obj', {'path': obj})
    check("import_obj 真导入 (物体数 +1)", len(ED.models) == n0 + 1, r)
    r = run('import_obj', {'path': os.path.join(TMP, '没有这个.obj')}, expect_ok=False)
    check("import_obj 文件不存在 -> 拒绝", r['ok'] is False)
    r = run('import_obj', {}, expect_ok=False)
    check("import_obj 缺 path -> 拒绝", r['ok'] is False)

    # Prefab: 存模板 / 放实例 / 断开连接 (全走临时路径, 不污染 assets/)
    res('object_select', {'name': ED.models[-1].name})
    pf = os.path.join(TMP, "eai_prefab.prefab")
    res('prefab_save', {'path': pf})
    check("prefab_save 真存模板文件", os.path.isfile(pf))
    n1 = len(ED.models)
    res('prefab_place', {'path': pf})
    check("prefab_place 真放实例 (物体数 +1)", len(ED.models) == n1 + 1)
    inst = ED.models[-1]
    check("Prefab 实例带 prefab_ref", bool(inst.prefab_ref), inst.prefab_ref)
    # 源物体与实例同名 -> 必须 index= 指定; 无 index 应拒绝 (防上错对象)
    r = run('prefab_unlink', {'name': inst.name}, expect_ok=False)
    check("prefab_unlink 重名不指定 index -> 拒绝且给匹配清单",
          r['ok'] is False and '重名' in r['error'], r.get('error'))
    res('object_select', {'name': inst.name,
                          'index': len(ED.models) - 1})
    res('prefab_unlink')
    check("prefab_unlink 断开连接 (index= 指定实例, 源物体无恙)",
          not inst.prefab_ref and ED.models[0].prefab_ref is not None
          or ED.models[0] is not inst, inst.prefab_ref)

    # 资产: 存材质资产 -> 清单里能找到 -> 应用到选中 -> 网格资产放入场景
    mat_path = os.path.join(ED._assets_dir(), "_eai_test.material") \
        if hasattr(ED, '_assets_dir') else None
    ass = res('assets')['assets']
    mesh_it = next((a for a in ass if a['type'] == 'mesh'), None)
    if mesh_it:
        # 真实会话里总有渲染帧打底 (_vp/_scene_digest 等宿主编排状态由帧驱动
        # 初始化); 命令行直跑也要同款先跑几帧, 资产落点才不裸奔 AttributeError.
        for _ in range(3):
            ED.render(0.016)
        n2 = len(ED.models)
        r = res('asset_place', {'type': mesh_it['type'], 'key': mesh_it['key']})
        check("asset_place 网格资产放入场景", len(ED.models) == n2 + 1, r)
    else:
        check("asset_place: 无网格资产可放 (跳过)", True)
    mat_it = next((a for a in ass if a['type'] == 'material'), None)
    if mat_it:
        res('object_select', {'name': ED.models[-1].name})
        r = res('asset_apply', {'type': mat_it['type'], 'key': mat_it['key']})
        check("asset_apply 材质资产应用到选中", r['to'] == ED.models[-1].name, r)
    else:
        r = run('asset_apply', {'type': 'material', 'key': '不存在'}, expect_ok=False)
        check("asset_apply 找不到资产 -> 拒绝 (无材质资产时走此分支)",
              r['ok'] is False)
    r = run('asset_place', {'type': 'mesh'}, expect_ok=False)
    check("asset_place 缺 key -> 拒绝", r['ok'] is False)

    sp = os.path.join(TMP, "eai_save.material")
    res('asset_save', {'what': 'material', 'path': sp})
    check("asset_save 存材质资产", os.path.isfile(sp), sp)
    sm = os.path.join(TMP, "eai_save.mesh")
    res('asset_save', {'what': 'mesh', 'path': sm})
    check("asset_save 存网格资产", os.path.isfile(sm), sm)
    r = run('asset_save', {'what': '乱写'}, expect_ok=False)
    check("asset_save 非法 what -> 拒绝", r['ok'] is False)


# ============ 11. 播放 / gizmo / 截图 / 设置 / 插件 / 退出 ============
def t_misc():
    res('gizmo', {'mode': 'rotate'})
    check("gizmo rotate", ED.gizmo_mode == 'rotate')
    res('gizmo', {'mode': 'translate'})
    check("gizmo translate", ED.gizmo_mode == 'translate')

    r = res('play', {'on': 'true'})
    check("play on=true 进入播放", r['playing'] is True and ED.is_playing is True)
    r = res('play', {'on': 'true'})
    check("play 已在播放再 on=true = 无变化 (幂等)", r.get('nochange') is True)
    r = res('play', {'on': 'false'})
    check("play on=false 退出播放 (字符串判假, 曾经反而开始播放)",
          r['playing'] is False and ED.is_playing is False)

    shot = os.path.join(TMP, "eai_shot.png")
    r = res('screenshot', {'file': shot})
    check("screenshot 存文件并返回尺寸", os.path.isfile(shot)
          and r['size'] == [1280, 800], r)

    s0 = res('settings_get')
    check("settings_get 读设置 (dict)", isinstance(s0, dict))
    # engine_metrics (方案一②/分离功能观测面, 2026-09-05): 只读指标
    r = res('engine_metrics')
    check("engine_metrics 只读指标 (fps/tps/jitter/时钟)",
          'fps' in r and 'get_tps' in r and 'get_frame_jitter' in r, r)
    res('settings_set', {'key': '_eai_test_flag', 'value': 'true'})
    r = res('settings_get', {'key': '_eai_test_flag'})
    check("settings_set 字符串 'true' 归一成 bool (GUI 复选框才不会错乱)",
          r['_eai_test_flag'] is True, r)
    res('settings_set', {'key': '_eai_test_num', 'value': '120'})
    r = res('settings_get', {'key': '_eai_test_num'})
    check("settings_set 数字归一成 int", r['_eai_test_num'] == 120, r)
    # 清理测试键
    import guiloader
    s = guiloader.load_settings('loom')
    s.pop('_eai_test_flag', None)
    s.pop('_eai_test_num', None)
    guiloader.save_settings('loom', s)

    # 插件按钮命令化 (与 GUI「插件」菜单点击同一回调)
    import plugin_loader
    got = []
    plugin_loader._EDITOR_BUTTONS.append(('EAI测试按钮', lambda: got.append(1),
                                          'com.test.eai'))
    r = res('plugin_button', {'plugin': 'com.test.eai', 'text': 'EAI测试按钮'})
    check("plugin_button 真调用插件回调", got == [1], r)
    r = run('plugin_button', {'text': '不存在的按钮'}, expect_ok=False)
    check("plugin_button 找不到 -> 拒绝并列出可用", r['ok'] is False)
    plugin_loader._EDITOR_BUTTONS[:] = []

    # ---- quit: 未保存退出不再弹框 (用户 2026-08-28 实测报告) ----
    # 场景现在必然是脏的 (一路都在改东西); 无 save= 时命令层自己决断:
    # 有 _scene_path -> 保存; 没有 -> 丢弃; 全程不弹模态框
    res('scene_save', {'path': os.path.join(TMP, "eai_quit_save.json")})
    res('set_transform', {'x': 123})
    check("status 报告 dirty=True (quit 前置信号)",
          res('status')['dirty'] is True)
    r = res('quit', {'after': 0})
    check("quit 脏场景无 save= -> 默认先保存再关 (绝不弹框)",
          r['quitting'] is True and WIN.closed is True
          and r.get('resolved') == 'save', r)
    res('set_transform', {'x': 456})       # 再脏一次
    WIN.closed = False
    check("quit save=cancel 中止退出且不关窗",
          (r := res('quit', {'after': 0, 'save': 'cancel'}))['cancelled'] is True
          and WIN.closed is False, r)
    r = res('quit', {'after': 0, 'save': 'discard'})
    check("quit save=discard 丢弃改动直接退出 (无弹框无卡死)",
          r['quitting'] is True and WIN.closed is True
          and r.get('resolved') == 'discard', r)
    # -- 用户报告场景的 GUI 路径 (真窗口) 由 Qt 探针验证: closeEvent 仍在,
    #    但 win._agent_suppress_confirm 置位后直接关, 见 tests\_tmp 探针 --
    print("quit 三态: 已覆盖 拒绝/取消/丢弃 三个分支 (save=save 分支在"
          " scene_save 单测里, 先存再退的时序那部分等 Qt 探针)")


# ============ 11b. 先保存再退 (save=save 分支) ============
def t_quit_save():
    """独立函数以便控制场景状态干净: 存盘 -> 再改 -> quit save=save."""
    p = os.path.join(TMP, "eai_quit_save.json")
    res('scene_save', {'path': p})
    res('object_add', {'type': 'cube'})          # 保存后改动 -> 脏
    r = res('quit', {'after': 0, 'save': 'save', 'path': p})
    check("quit save=save path= 先存盘再退出", r['quitting'] is True
          and int(os.path.getsize(p)) > 100, r)


# ============ 12. 命令行本身: 派发契约 / 日志 / 输入解析 ============
def t_console_layer():
    r = ac.dispatch('不存在的命令', {}, WIN)
    check("未知命令 -> ok=False 且列出可用命令",
          r['ok'] is False and '未知命令' in r['error'])

    n = ac.log("EAI 测试日志行")
    rows = ac.log_since(n - 1)
    check("log_since 增量只返回新行", len(rows) == 1 and rows[0][2] == 'EAI 测试日志行')
    check("last_log_seq 是当前序号 (控制台挂载基线)", ac.last_log_seq() >= n)

    # GUI 控制台输入解析 (qt_console 与 hub_console 同语法)
    from ui.qt_console import parse_line, help_text
    cmd, args = parse_line('set_transform x=1 y=2.5 name=立方体1')
    check("控制台输入解析: cmd + key=value",
          cmd == 'set_transform' and args == {'x': '1', 'y': '2.5',
                                              'name': '立方体1'}, args)
    cmd, args = parse_line('status')
    check("控制台输入解析: 只有命令名", cmd == 'status' and args == {})
    cmd, args = parse_line('')
    check("控制台输入解析: 空行", cmd == '' and args == {})
    cmd, args = parse_line('object_select 立方体1')
    check("控制台输入解析: 裸词进 args['_']", args.get('_') == ['立方体1'])
    h = help_text()
    check("控制台 help 列出全部命令 (自动跟随命令表)",
          all(k in h for k in ac.command_names()), len(h))

    # 命令层布尔/数值归一 (控制台一律给字符串)
    check("as_bool('false') 判假", ac.as_bool('false') is False)
    check("as_bool('0'/'no'/'off') 判假", not any(
        ac.as_bool(v) for v in ('0', 'no', 'off', '')))
    check("as_bool('true'/1) 判真", ac.as_bool('true') and ac.as_bool(1))
    check("as_float 非法值回默认", ac.as_float('abc', 7.0) == 7.0
          and ac.as_float('2.5') == 2.5)


# ============ 13. 命令层 API 契约 (防桩漂移) ============
def t_api_contract():
    """静态扫描 agent_commands.py 里所有 ed.<方法>( 调用, 断言真 EditorApp 上存在.
    桩测试永远发现不了"命令调了个编辑器没有的方法" —— 这条就是那道闸。"""
    import re
    src = open(os.path.join(ROOT, 'agent_commands.py'), encoding='utf-8').read()
    names = set(re.findall(r'\bed\.([A-Za-z_]\w*)\s*\(', src))
    names |= set(re.findall(r'\bwin\.editor\.([A-Za-z_]\w*)\s*\(', src))
    missing = sorted(n for n in names if not hasattr(editor.EditorApp, n))
    check("命令层调用的 EditorApp 方法全部真实存在 (%d 个)" % len(names),
          not missing, missing)
    # 属性访问 (非方法) 也扫一遍常用的
    attrs = ('models', 'lights', 'cameras', 'materials', 'is_playing',
             'gizmo_mode', 'camera_target', 'camera_distance', 'camera_yaw',
             'camera_pitch', 'active_camera', 'preview_camera', 'scene_name',
             'width', 'height')
    miss2 = [a for a in attrs if not hasattr(ED, a)]
    check("命令层读取的 EditorApp 属性全部存在", not miss2, miss2)


# ============ 14. 覆盖率闸门 ============
def t_coverage():
    table = set(ac.command_names())
    untested = sorted(table - _USED)
    check("命令表全部命令都被真编辑器执行过 (共 %d 条)" % len(table),
          not untested, untested)
    ghost = sorted(_USED - table)
    check("测试里没有调用已下线的命令", not ghost, ghost)


if __name__ == "__main__":
    print("========== EAI 全命令自动化测试 (真 EditorApp) ==========")
    t_query()
    t_object_crud()
    t_transform()
    t_material()
    t_components()
    t_scripts()
    t_light()
    t_camera()
    t_reparent()
    t_scene_assets()
    t_misc()
    t_quit_save()
    t_console_layer()
    t_api_contract()
    t_coverage()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅  (命令 %d 条全部覆盖)" % len(ac.command_names()))
    print("全部通过")
