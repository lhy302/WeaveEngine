# -*- coding: utf-8 -*-
"""scripts.py 无头测试 (M27): 内置脚本数学 / 调度 / 参数覆盖 / on_start / 容错."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math
import engine as E
from engine import Point3D, GLEngine, GameObject
import scripts

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# ---- 轻量假引擎 (脚本只依赖 is_key / world_position / camera_target) ----
class FakeEngine:
    def __init__(self):
        self.camera_target = None
        self.keys = {}
        self.actions = dict(E.DEFAULT_ACTIONS)
        # M32 玩家控制器桩
        self.camera = Point3D(0, 0, 0)
        self.camera_yaw = 0.0
        self.camera_pitch = 0.0
        self.orbit_mode = True
        self.mouse_rel = (0, 0)
        # M39 鼠标锁定桩
        self.mouse_locked = True
    def set_mouse_locked(self, locked):
        self.mouse_locked = bool(locked)
    def toggle_mouse_locked(self):
        self.mouse_locked = not self.mouse_locked
    def is_key(self, name):
        return bool(self.keys.get(name, False))
    def get_action(self, name):
        for k in self.actions.get(name, (name,)):
            if self.keys.get(k, False):
                return True
        return False
    def world_position(self, m):
        return m.position
    # wasd_move 走 move_with_collision (M28); 本文件是无碰撞桩, 直接平移
    def move_with_collision(self, m, dx, dy, dz):
        m.position = Point3D(m.position.x + dx, m.position.y + dy, m.position.z + dz)
        return False
    # M41: 无激活相机/未启用俯仰角限制 -> 无限制 (玩家脚本兜底默认钳位)
    def player_pitch_limits(self):
        return None

class FakeObj:
    def __init__(self, pos=(0, 0, 0)):
        self.position = Point3D(*pos)
        self.rotation = Point3D(0, 0, 0)
        self.rigidbody = None
    def add_rigidbody(self, **kw):
        from engine import RigidbodyComponent
        self.rigidbody = RigidbodyComponent(**kw)
        return self.rigidbody

eng = FakeEngine()

# ---- 注册表 / 选项 ----
check("选项以'无'开头", scripts.script_options()[0] == (None, '无'))
check("选项含自转/公转/浮动/WASD/跟随",
      all(any(o[0] == sid for o in scripts.script_options())
          for sid in ('rotate', 'orbit', 'bob', 'wasd_move', 'camera_follow')))
check("脚本名唯一且非空", all(cls.script_id and cls.name for cls in scripts.SCRIPTS.values()))

# ---- 自转 (1s = 180°/90°) ----
o = FakeObj()
s = scripts.get_script('rotate')(); s.obj = o; s.engine = eng
s.vals['sx'] = 180.0; s.vals['sy'] = 90.0; s.vals['sz'] = 0.0
s.update(1.0)
check("自转 1s X=π Y=π/2",
      abs(o.rotation.x - math.pi) < 1e-6 and abs(o.rotation.y - math.pi / 2) < 1e-6,
      str(o.rotation))
s.update(1.0)
check("自转 2s 累计 X=2π", abs(o.rotation.x - 2 * math.pi) < 1e-6)
check("自转 Z 不转", o.rotation.z == 0.0)

# ---- 浮动 (基态=当前高度, sin 顶点=基+幅) ----
o = FakeObj((0, 2, 0))
s = scripts.get_script('bob')(); s.obj = o; s.engine = eng
s.vals['amp'] = 1.0; s.vals['freq'] = 1.0
s.on_start()
check("浮动记录基高", s._base_y == 2.0)
s.update(0.25)                                    # t=0.25 -> sin(π/2)=1
check("浮动 0.25s 顶=3", abs(o.position.y - 3.0) < 1e-6, str(o.position.y))
s.update(0.25)                                    # t=0.5 -> sin(π)=0
check("浮动 0.5s 回中=2", abs(o.position.y - 2.0) < 1e-6, str(o.position.y))

# ---- 公转 (绕原点, 半径1, 90°/s -> 1s 到 (0,0,1)) ----
o = FakeObj((1, 0, 0))
s = scripts.get_script('orbit')(); s.obj = o; s.engine = eng
s.on_start()
check("公转记录半径1", abs(s._rad - 1.0) < 1e-9)
s.vals['speed'] = 90.0
s.update(1.0)
check("公转 90° -> (0,0,1)",
      abs(o.position.x) < 1e-6 and abs(o.position.z - 1.0) < 1e-6, str(o.position))

# ---- WASD 移动 (W=+z, A=-x, 无键不动) ----
o = FakeObj()
s = scripts.get_script('wasd_move')(); s.obj = o; s.engine = eng
s.vals['speed'] = 2.0
eng.keys = {'w': True}
s.update(0.5)
check("WASD W 2速*0.5s -> z=1", abs(o.position.z - 1.0) < 1e-9, str(o.position))
eng.keys = {'a': True}
s.update(0.5)
check("WASD A -> x=-1", abs(o.position.x + 1.0) < 1e-9, str(o.position))
eng.keys = {}
s.update(0.5)
check("WASD 无键不动", abs(o.position.x + 1.0) < 1e-9 and abs(o.position.z - 1.0) < 1e-9)

# ---- 输入动作层 (M30b): get_action / 重映射 / 配置 round-trip ----
eg = E.GLEngine.__new__(E.GLEngine)   # 无窗口桩
eg.script_keys = {'w': True}
eg.actions = dict(E.DEFAULT_ACTIONS)
check("动作: 向前绑 w/Up, w 按下=True", eg.get_action('向前') is True)
eg.script_keys = {'Up': True}
check("动作: 二选一键 Up 按下也 True", eg.get_action('向前') is True)
eg.script_keys = {}
check("动作: 无键按下 False", eg.get_action('向前') is False)
eg.script_keys = {'j': True}
eg.rebind_action('跳跃', ['j'])          # 重映射: 跳跃从 space 改到 j
check("动作: 重映射后新键生效", eg.get_action('跳跃') is True)
eg.script_keys = {'space': True}
check("动作: 重映射后旧键失效", eg.get_action('跳跃') is False)
# 配置 round-trip (保存到临时文件再加载)
eg.actions = dict(E.DEFAULT_ACTIONS); eg.actions['跳跃'] = ['j']
import tempfile as _tf
_cfg = _tf.mktemp(suffix='.json')
eg.save_action_bindings(_cfg)
eg2 = E.GLEngine.__new__(E.GLEngine); eg2.actions = dict(E.DEFAULT_ACTIONS)
eg2._load_action_bindings(_cfg)
check("动作: 配置保存加载 round-trip", eg2.actions['跳跃'] == ['j'], str(eg2.actions['跳跃']))

# ---- 相机跟随 (target = 物体世界位置 + 偏移) ----
o = FakeObj((3, 1, 2))
s = scripts.get_script('camera_follow')(); s.obj = o; s.engine = eng
s.vals['oy'] = 2.0
s.update(0.1)
check("相机跟随 target=(3,3,2)", eng.camera_target == (3, 3, 2), str(eng.camera_target))

# ---- M32 玩家控制器 (第一/第三人称 + 跳跃) ----
# 第一人称: W 沿视角前方移动 (动作层) + 相机接管
o = FakeObj(); o.add_rigidbody()
s = scripts.get_script('first_person')(); s.obj = o; s.engine = eng
s.vals['speed'] = 5.0; s.vals['eye'] = 1.6; s.vals['jump_v'] = 6.0
s.on_start()                                  # yaw/pitch = 相机初始 (0)
eng.keys = {'w': True}                        # '向前'
s.update(1.0)                                 # 1s * 5 = 沿 +z 移动 5
check("第一人称: W 移动 5 沿 +z", abs(o.position.z - 5.0) < 1e-6, str(o.position))
check("第一人称: 相机 = 角色 + 眼高", eng.camera == Point3D(0, 1.6, 5), str(eng.camera))
check("第一人称: 关闭轨道相机", eng.orbit_mode is False)
# 鼠标转向
eng.mouse_rel = (500, 0)                      # 右移 500px * 0.002 = +1
s.update(0.0)
check("第一人称: 鼠标右移 yaw 增大", s.yaw > 0, "yaw=%.3f" % s.yaw)
# 跳跃 (挂刚体, 落地后)
o.rigidbody.velocity = Point3D(0, 0, 0)
eng.keys = {'space': True}                    # '跳跃'
s.update(0.0)
check("第一人称: 跳跃设 velocity.y", o.rigidbody.velocity.y == 6.0,
      str(o.rigidbody.velocity.y))
# 第三人称: 移动 + 相机在角色后方上方 (重置相机状态, 隔离 first_person 测试污染)
eng.camera_yaw = 0.0; eng.camera_pitch = 0.0
eng.keys = {'w': True}; eng.mouse_rel = (0, 0)
o2 = FakeObj()
s2 = scripts.get_script('third_person')(); s2.obj = o2; s2.engine = eng
s2.vals['dist'] = 6.0; s2.vals['height'] = 3.0
s2.on_start(); s2.update(1.0)
check("第三人称: W 移动且相机在角色后方", o2.position.z > 0
      and eng.camera.z < o2.position.z, "obj.z=%.2f cam.z=%.2f" % (o2.position.z, eng.camera.z))
# 独立跳跃脚本
o3 = FakeObj(); o3.add_rigidbody()
sj = scripts.get_script('jump')(); sj.obj = o3; sj.engine = eng
eng.keys = {'space': True}
sj.update(0.0)
check("跳跃: 独立脚本设 velocity.y", o3.rigidbody.velocity.y == 6.0,
      str(o3.rigidbody.velocity.y))

# ---- M39 鼠标锁定 (FPS: 播放锁定, Tab 释放/回锁, 释放状态鼠标不转视角) ----
o = FakeObj(); o.add_rigidbody()
s = scripts.get_script('first_person')(); s.obj = o; s.engine = eng
s.vals['sens'] = 0.002
eng.mouse_rel = (0, 0)
s.on_start()
check("M39: 播放锁定鼠标", eng.mouse_locked is True)
eng.keys = {'Tab': True}; eng.mouse_rel = (500, 0)   # Tab 按下帧 + 鼠标右移
s.update(0.0)
check("M39: Tab 释放锁定", eng.mouse_locked is False)
check("M39: 释放状态鼠标不转视角", abs(s.yaw) < 1e-9, "yaw=%.3f" % s.yaw)
eng.keys = {}; eng.mouse_rel = (0, 0)
s.update(0.0)
eng.keys = {'Tab': True}
s.update(0.0)                                        # 再按 Tab -> 回锁
check("M39: 再按 Tab 回锁", eng.mouse_locked is True)
eng.mouse_rel = (500, 0)
s.update(0.0)                                        # 回锁后鼠标转视角
check("M39: 回锁后鼠标转动视角", abs(s.yaw) > 0, "yaw=%.3f" % s.yaw)

# ---- M39 真实引擎解锁回锁逻辑 (特殊场景强制回锁, 退出正常回锁) ----
eg2 = E.GLEngine.__new__(E.GLEngine)
eg2.mouse_locked = False
eg2.mouse_unlock_requested = False
eg2._ui_capture_mouse = False
eg2.set_mouse_locked = lambda locked: setattr(eg2, 'mouse_locked', locked)  # mock 底层
eg2.toggle_mouse_locked()                            # 非特殊场景 Tab 解锁
check("M39: 非特殊场景 Tab 解锁", eg2.mouse_unlock_requested is True
      and eg2.mouse_locked is False)
eg2.set_ui_capture_mouse(True)                       # 进特殊场景(菜单/暂停)
check("M39: 特殊场景强制清解锁意图 + 显示鼠标",
      eg2.mouse_unlock_requested is False and eg2.mouse_locked is False)
eg2.set_ui_capture_mouse(False)                      # 退出特殊场景 -> 回锁
check("M39: 退出特殊场景鼠标回锁", eg2.mouse_locked is True)
eg2.toggle_mouse_locked()                            # 特殊场景下 Tab 不产生解锁意图
eg2.set_ui_capture_mouse(True)
eg2.toggle_mouse_locked()
check("M39: 特殊场景 Tab 不解锁意图", eg2.mouse_unlock_requested is False)

# ---- M38 游戏脚本目录加载 (Unity 项目脚本机制) ----
import tempfile as _tf2
_sd = _tf2.mkdtemp()
with open(os.path.join(_sd, 'my_script.py'), 'w', encoding='utf-8') as _f:
    _f.write("""import scripts\nfrom scripts import Script\n@scripts.register\nclass MySc(Script):\n    script_id='my_script'\n    name='我的脚本'\n    def update(self, dt): pass\n""")
n = scripts.load_script_dir(_sd)
check("游戏脚本目录: 加载 1 个", n == 1 and scripts.get_script('my_script') is not None,
      str(n))
check("游戏脚本: 注册进 SCRIPTS 可挂载",
      any(o[0] == 'my_script' for o in scripts.script_options()))
with open(os.path.join(_sd, '_skip.py'), 'w', encoding='utf-8') as _f:
    _f.write("raise RuntimeError('内部文件应跳过')")
with open(os.path.join(_sd, 'bad.py'), 'w', encoding='utf-8') as _f:
    _f.write("raise RuntimeError('bad')")
scripts.load_script_dir(_sd)
check("游戏脚本: 内部文件跳过 + 坏脚本不崩", True)
check("游戏脚本: 不存在目录返回 0", scripts.load_script_dir(os.path.join(_sd, 'none')) == 0)
# 2026-08-20 安全加固 (Qoder 报告中危1): 文件名白名单 [A-Za-z0-9_]+\.py
for _fn in ('a b.py', 'x.py.txt', '.hidden.py', '..evil.py', 'my_script.PY'):
    with open(os.path.join(_sd, _fn), 'w', encoding='utf-8') as _f:
        _f.write("raise RuntimeError('隐蔽文件名应被跳过')")
_before = set(scripts.SCRIPTS)
scripts.load_script_dir(_sd)
check("游戏脚本: 非白名单文件名跳过 (隐蔽文件名)", set(scripts.SCRIPTS) == _before)

# ---- 调度: update_scripts 实例化 + 参数覆盖 + 持续累计 ----
e = GLEngine.__new__(GLEngine)
m = GameObject(None, Point3D(0, 0, 0), Point3D(0, 0, 0))
m.name = '立方体'
m.script_id = 'rotate'
m.script_vars = {'sy': 180.0}                      # 只覆盖 sy
e.models = [m]
e.update_scripts(1.0)
check("update_scripts 参数覆盖生效 (sy=180°/s)",
      abs(m.rotation.y - math.pi) < 1e-6, str(m.rotation))
e.update_scripts(1.0)
check("update_scripts 同一实例继续累计", abs(m.rotation.y - 2 * math.pi) < 1e-6)
check("无脚本物体 _script=None", True)
m2 = GameObject(None, Point3D(0, 0, 0), Point3D(0, 0, 0))
m2.name = '静态'
e.models = [m, m2]
e.update_scripts(0.1)
check("无脚本物体跳过且清实例", m2._script is None)

# ---- on_start 只调一次 ----
class _Count(scripts.Script):
    script_id = '_test_count'
    name = '计数'
    params = ()
    def on_start(self):
        self.starts = getattr(self, 'starts', 0) + 1
scripts.SCRIPTS['_test_count'] = _Count
m3 = GameObject(None, Point3D(0, 0, 0), Point3D(0, 0, 0))
m3.name = '计数'
m3.script_id = '_test_count'
e.models = [m3]
e.update_scripts(0.1)
e.update_scripts(0.1)
check("on_start 只调一次", m3._script is not None and m3._script.starts == 1,
      "starts=%d" % (m3._script.starts if m3._script else -1))

# ---- 坏脚本容错: 抛异常 -> 标记 broken -> 之后跳过 ----
class _Bad(scripts.Script):
    script_id = '_test_bad'
    name = '坏'
    def update(self, dt):
        raise RuntimeError('boom')
scripts.SCRIPTS['_test_bad'] = _Bad
m4 = GameObject(None, Point3D(0, 0, 0), Point3D(0, 0, 0))
m4.name = '坏'
m4.script_id = '_test_bad'
e.models = [m3, m4]
e.update_scripts(0.1)
check("坏脚本被标记 broken", m4._script_broken and m4._script is None)
e.update_scripts(0.1)                              # 不再报错
check("坏脚本之后跳过 (不反复实例化)", m4._script is None and m4._script_broken)
check("同帧其他脚本不受影响", m3._script is not None and m3._script.starts == 1)

# ---- 未知脚本 id: 跳过 ----
m5 = GameObject(None, Point3D(0, 0, 0), Point3D(0, 0, 0))
m5.name = '未知'
m5.script_id = 'no_such_script'
e.models = [m5]
e.update_scripts(0.1)
check("未知脚本 id 跳过", m5._script is None and not m5._script_broken)

# ---- M25 多脚本: 一个物体挂多个脚本组件, 全部运行 ----
m6 = GameObject(None, Point3D(0, 2, 0), Point3D(0, 0, 0))
m6.name = '多脚本'
m6.add_script('rotate', {'sy': 90.0})
m6.add_script('bob', {'amp': 1.0, 'freq': 1.0})
e.models = [m6]
e.update_scripts(0.25)                          # t=0.25 -> bob 到顶点 3, rotate 22.5°
check("多脚本: 两个组件都运行", m6.scripts[0]._script is not None
      and m6.scripts[1]._script is not None)
check("多脚本: 自转 Y 推进 22.5°", abs(m6.rotation.y - math.pi / 8) < 1e-6,
      str(m6.rotation))
check("多脚本: 浮动到顶点 y=3", abs(m6.position.y - 3.0) < 1e-6, str(m6.position.y))
# 移除一个脚本组件 -> 只剩 rotate 继续跑
sc_removed = m6.remove_script(1)
check("remove_script 返回被移除组件", sc_removed is not None
      and sc_removed.script_id == 'bob')
e.update_scripts(0.25)
check("移除后只剩 rotate 运行", len(m6.scripts) == 1
      and m6.scripts[0]._script is not None
      and abs(m6.rotation.y - math.pi / 4) < 1e-6, str(m6.rotation))
# 清空全部脚本 -> 不再跑
m6.clear_scripts()
e.update_scripts(0.25)
check("clear_scripts 后无脚本", m6.scripts == [] and m6.script_id is None)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
