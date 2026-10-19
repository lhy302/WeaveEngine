# -*- coding: utf-8 -*-
"""
scripts.py — 物体脚本系统 (M27: 从"摆静态场景"跨到"做能动的游戏")

设计 (设计总纲: 引擎必须是"做东西"的工具):
  - 每个内置/自定义脚本是一个 Script 子类, 用 @register 注册进 SCRIPTS.
  - 物体 (GameObject, M25 组件化) 挂 ScriptComponent 列表 (可多个), 每个组件
    存 script_id + script_vars (参数覆盖), 不含运行实例.
  - 播放期引擎对挂了脚本的物体实例化 Script, 绑定 obj/engine:
      进入播放调一次 on_start(), 每帧调 update(dt).
  - 脚本可做的事:
      · 改自身变换: obj.position / obj.rotation / obj.scale
      · 改相机: engine.camera_target / camera_yaw / camera_distance 等 (轨道相机)
      · 读输入: engine.is_key('w'/'space'/'Left'...) —— 见 engine._KEYMAP
      · 读引擎: engine.models / engine.world_position(obj) / engine.lights
      · 碰撞 (M28): engine.move_with_collision(obj, dx,dy,dz) 带碰撞移动
        (被挡返回 True), engine.get_collisions(obj) 查询碰撞物体列表.
        所有物体默认有碰撞体 (球=球体, 其他=盒子), 纯装饰可把检查器里
        碰撞体禁用/设 none.
  - 参数规格: params = ((key, label, default, vmin, vmax, fmt), ...),
    检查器据此画拖拽滑块, 值存进 script_vars 并随场景序列化.

内置脚本即"实用工具"的最小行为库: 自转/公转/浮动 (演示用) +
WASD移动/相机跟随 (组合起来 = 一个能跑的最小第三人称演示)。
"""
import math
import os
import re
import sys
import types
from engine import Point3D

# 脚本注册表: script_id -> Script 子类 (dict 保持注册顺序)
SCRIPTS = {}


def register(cls):
    """类装饰器: 把脚本登记进 SCRIPTS (键 = cls.script_id)"""
    SCRIPTS[cls.script_id] = cls
    return cls


def make_lua_script_class(script_id, name, lua_code):
    """M4: 为 Lua 脚本生成动态 Script 子类适配器, 桥接至 script.dll 嵌入式 Lua 5.4 VM"""
    class DynamicLuaScript(Script):
        def __init__(self):
            super().__init__()
            self._lua = None

        def on_start(self):
            try:
                import script_glue as _sg
                self._lua = _sg.LoomLuaScript(lua_code)
                p = self.obj.position
                r = self.obj.rotation
                self._lua.bind_entity((p.x, p.y, p.z), (r.x, r.y, r.z), getattr(self.obj, 'name', '') or "")
                cam = getattr(self.engine, 'camera_target', None)
                if cam:
                    self._lua.bind_camera(cam)
                self._lua.call_start()
            except Exception as e:
                print("[Lua脚本] %s 启动失败: %r" % (name, e))

        def update(self, dt):
            if self._lua is not None and not self._lua._broken:
                p = self.obj.position
                r = self.obj.rotation
                self._lua.bind_entity((p.x, p.y, p.z), (r.x, r.y, r.z), getattr(self.obj, 'name', '') or "")
                e = self.engine
                if hasattr(e, 'keys'):
                    for k, v in e.keys.items():
                        self._lua.set_key(k, v)
                if hasattr(e, 'actions'):
                    for act in e.actions:
                        self._lua.set_action(act, e.get_action(act))
                cam = getattr(e, 'camera_target', None)
                if cam:
                    self._lua.bind_camera(cam)
                self._lua.call_update(dt)
                buf_p = self._lua._pos_buf
                buf_r = self._lua._rot_buf
                self.obj.position = Point3D(float(buf_p[0]), float(buf_p[1]), float(buf_p[2]))
                self.obj.rotation = Point3D(float(buf_r[0]), float(buf_r[1]), float(buf_r[2]))
                if cam:
                    buf_c = self._lua._cam_buf
                    e.camera_target = (float(buf_c[0]), float(buf_c[1]), float(buf_c[2]))

    DynamicLuaScript.script_id = script_id
    DynamicLuaScript.name = name
    return DynamicLuaScript

_SCRIPT_FNAME_RE = re.compile(r'^[A-Za-z0-9_]+\.(py|lua)$')  # M4: 支持 .py 与 .lua 脚本


def load_script_dir(directory):
    r"""M38: 加载"游戏脚本目录"里的 .py 与 .lua 脚本 (Unity 项目脚本机制).
    目录里每个 .py/.lua 文件动态加载 —— 自动注册进 SCRIPTS,
    之后检查器可挂载、运行时实例化. 引擎启动时扫描 exe/引擎旁的 scripts/ 目录.
    文件名白名单 [A-Za-z0-9_]+\.(py|lua) (安全加固),
    跳过 _ 开头(内部文件). 坏脚本打印不崩. 返回成功加载数."""
    import importlib.util
    if not directory or not os.path.isdir(directory):
        return 0
    count = 0
    for fname in sorted(os.listdir(directory)):
        if not _SCRIPT_FNAME_RE.match(fname):
            continue
        path = os.path.join(directory, fname)
        if fname.endswith('.lua'):
            try:
                sid = os.path.splitext(fname)[0]
                with open(path, 'r', encoding='utf-8') as f:
                    code = f.read()
                cls = make_lua_script_class(sid, sid, code)
                register(cls)
                count += 1
            except Exception as e:
                print("[脚本] 加载 Lua 游戏脚本 %s 失败: %r" % (fname, e))
            continue
        try:
            spec = importlib.util.spec_from_file_location(fname[:-3], path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            count += 1
        except Exception as e:
            print("[脚本] 加载游戏脚本 %s 失败: %r" % (fname, e))
    return count


def register_sources(sources):
    """2026-08-22 发布链路: 从内存源码加载游戏脚本 (游戏包.lsc 内, 不落盘明文).
    M4: 完整支持 .lua 与 .py 混合脚本. 坏脚本打印不崩. 返回成功加载数."""
    count = 0
    for i, item in enumerate(sources):
        if isinstance(item, dict):
            name, source = item['name'], item['source']
        else:
            name, source = item
        sname = str(name)
        if sname.endswith('.lua'):
            try:
                sid = os.path.splitext(sname)[0]
                cls = make_lua_script_class(sid, sid, source)
                register(cls)
                count += 1
            except Exception as e:
                print('[脚本] 游戏包 Lua 脚本 %s 加载失败: %r' % (name, e))
            continue
        mod_name = 'game_script_%d_%s' % (i, re.sub(r'[^A-Za-z0-9_]', '_',
                                                    sname).strip('_') or 'x')
        try:
            mod = types.ModuleType(mod_name)
            mod.__file__ = '<game_pack:%s>' % name
            exec(compile(source, '<game_pack:%s>' % name, 'exec'), mod.__dict__)
            sys.modules[mod_name] = mod
            count += 1
        except Exception as e:
            print('[脚本] 游戏包脚本 %s 加载失败: %r' % (name, e))
    return count


def get_script(script_id):
    """按 id 取脚本类 (未注册返回 None)"""
    return SCRIPTS.get(script_id)


def script_options():
    """脚本下拉选项: [(None, '无'), (id, 名称), ...] (注册顺序)"""
    return [(None, '无')] + [(sid, SCRIPTS[sid].name) for sid in SCRIPTS]


class Script:
    """脚本基类. 子类覆盖 script_id/name/params, 实现 on_start/update."""
    script_id = None   # 唯一标识 (小写蛇形, 序列化用)
    name = '脚本'
    params = ()        # ((key, label, default, vmin, vmax, fmt), ...)
    # 2026-10-18 第1档序12 执行顺序（语义对齐 Unity Script Execution Order）:
    # 数值小的先执行（默认 0）；同 order 保持"物体顺序 + 脚本列表顺序"（稳定排序）。
    # 用法：子类里写 order = -100 让它比默认脚本更早 update。
    order = 0

    def __init__(self):
        self.obj = None       # 宿主物体 (GameObject)
        self.engine = None    # 引擎 (GLEngine/EditorApp/PlayerApp)
        self.vals = {}        # 参数 key -> 当前值
        # 2026-10-18 协程（决策 A1+B1）：Python generator 作为协程
        # 生命周期与 Script 实例绑定：sc._script=None 时整批 drop，无需手动清理
        self._coroutines = []  # [(gen, {'wait_t': 0.0, 'wait_until': None, 'wait_while': None})]
        for key, _label, default, *_ in self.params:
            self.vals[key] = default

    def on_enable(self):
        """脚本实例被启用时调用一次 (进播放/脚本刚挂载; 早于 on_start).
        C1 (2026-10-16): 与 on_start 同期触发, 用于"组件启用"语义对齐 Unity."""
        pass

    def on_start(self):
        """进入播放时调用一次 (obj/engine 已绑定, 可读宿主初值/记录基态)"""
        pass

    def on_disable(self):
        """脚本实例被禁用时调用 (停止播放/脚本卸下; 晚于最后一次 update).
        C1: 用于释放/复位脚本持有的外部资源."""
        pass

    def on_destroy(self):
        """宿主物体被删除时调用 (remove_model/remove_subtree/clear_scene).
        C1: 用于物体级资源清理; 与 on_disable 的区别: on_disable 是"暂停",
        on_destroy 是"物体永久消失"."""
        pass

    def on_collision_stay(self, other):
        """持续接触每逻辑帧调用 (other=对方物体). C1: 对齐 Unity OnCollisionStay.
        注意: 未定义本方法的脚本走零开销快路径 (不进入 stay 派发)."""
        pass

    # ---- 2026-10-18 阶段1档序17 Trigger (路线见 §2.7) ----
    # 语义对齐 Unity OnTriggerEnter/Exit/Stay:
    #   1) 双方 collider.is_trigger 任一为 True 时派发本组事件 (而非 on_collision_*)
    #   2) 物理层 is_sensor 保证不产生接触力 (可重叠穿过)
    #   3) 双方都有脚本时, 双方各自收到对方的 on_trigger_* (与 on_collision_* 同语义)
    #   4) 未定义本方法的脚本走零开销快路径 (与 stay 机制同)
    def on_trigger_enter(self, other):
        """进入触发区 (other=对方物体). 对应 Unity OnTriggerEnter."""
        pass

    def on_trigger_exit(self, other):
        """离开触发区. 对应 Unity OnTriggerExit."""
        pass

    def on_trigger_stay(self, other):
        """持续处于触发区每逻辑帧. 对应 Unity OnTriggerStay.
        未定义本方法的脚本走零开销快路径."""
        pass

    # ---- 2026-10-18 第1档序10 FixedUpdate / 序11 LateUpdate / 序12 执行顺序 ----
    def on_fixed_update(self, fixed_dt):
        """固定步钩子（语义对齐 Unity FixedUpdate）：每个逻辑帧调用一次，
        在物理子步之前（用户改速度/位置本步物理生效）。

        调用频率：固定 TPS（通常 30），与渲染帧率解耦。
        dt 参数：fixed_dt（恒为 sub_steps × sub_dt，与 _logic_frame 一致）。
        """
        pass

    def on_late_update(self, render_dt):
        """晚更新钩子（语义对齐 Unity LateUpdate）：每个渲染帧调用一次，
        在所有 update 之后、UI 渲染之前（相机跟随、HUD 同步用）。

        dt 参数：render_dt（渲染帧实际 dt）。
        """
        pass


    # ---- 2026-10-18 协程（决策 A1 generator 风格 + B1 Script 作用域）----
    def start_coroutine(self, gen):
        """启动一个协程（generator）。用法：

            def my_coro(self):
                yield self.wait(2.0)                              # 等 2 秒
                self.obj.position = Point3D(0, 5, 0)
                yield self.wait_until(lambda: self.obj.position.y < 1)  # 等到落下
                print("落地了")

            def on_start(self):
                self.start_coroutine(self.my_coro())

        协程与脚本生命周期绑定：脚本实例销毁（sc._script=None）时自动清理。
        返回 generator 本身（可用于 stop_coroutine 停止）。
        """
        if not hasattr(gen, 'send'):
            raise TypeError(
                "start_coroutine 需要 generator 对象，收到 %r" % type(gen))
        self._coroutines.append(
            (gen, {'wait_t': 0.0, 'wait_until': None, 'wait_while': None}))
        return gen

    def stop_coroutine(self, gen):
        """停止指定协程（按 generator 引用）。返回 True 表示找到并停止。"""
        for entry in list(self._coroutines):
            if entry[0] is gen:
                self._coroutines.remove(entry)
                try:
                    gen.close()
                except Exception:
                    pass
                return True
        return False

    def stop_all_coroutines(self):
        """停止本脚本上的所有协程。"""
        for entry in list(self._coroutines):
            try:
                entry[0].close()
            except Exception:
                pass
        self._coroutines.clear()

    def coroutine_count(self):
        """当前活跃协程数（诊断用）。"""
        return len(self._coroutines)

    def wait(self, seconds):
        """协程暂停 N 秒。用法: yield self.wait(2.0)  ← yield 不是 yield from"""
        return float(seconds)

    def wait_until(self, pred):
        """协程等到 pred() 为真。用法: yield self.wait_until(lambda: ...)"""
        return ('until', pred)

    def wait_while(self, pred):
        """协程等到 pred() 为假。用法: yield self.wait_while(lambda: ...)"""
        return ('while', pred)

    def wait_frame(self):
        """协程等 1 帧。用法: yield self.wait_frame()"""
        return None

    def _drive_coroutines(self, dt):
        """内部方法：由引擎 update_scripts 每帧推进本脚本的所有协程。"""
        if not self._coroutines:
            return
        for entry in list(self._coroutines):
            gen, state = entry
            try:
                should_resume = False
                if state['wait_t'] > 0:
                    state['wait_t'] -= dt
                    if state['wait_t'] <= 0:
                        state['wait_t'] = 0.0
                        should_resume = True
                elif state['wait_until'] is not None:
                    try:
                        if state['wait_until']():
                            state['wait_until'] = None
                            should_resume = True
                    except Exception as e:
                        print("[脚本] wait_until 谓词异常 (%s): %r"
                              % (self.script_id or '?', e))
                        self._coroutines.remove(entry)
                        continue
                elif state['wait_while'] is not None:
                    try:
                        if not state['wait_while']():
                            state['wait_while'] = None
                            should_resume = True
                    except Exception as e:
                        print("[脚本] wait_while 谓词异常 (%s): %r"
                              % (self.script_id or '?', e))
                        self._coroutines.remove(entry)
                        continue
                else:
                    should_resume = True

                if not should_resume:
                    continue

                yielded = gen.send(None)
                if yielded is None:
                    pass   # 等 1 帧
                elif isinstance(yielded, (int, float)):
                    state['wait_t'] = float(yielded)
                elif callable(yielded):
                    state['wait_until'] = yielded
                elif isinstance(yielded, tuple) and len(yielded) == 2:
                    kind, arg = yielded
                    if kind == 'until' and callable(arg):
                        state['wait_until'] = arg
                    elif kind == 'while' and callable(arg):
                        state['wait_while'] = arg
                    else:
                        print("[脚本] 未知协程指令 (%s): %r"
                              % (self.script_id or '?', yielded))
                else:
                    print("[脚本] 未知协程产出类型 (%s): %r"
                          % (self.script_id or '?', type(yielded)))
            except StopIteration:
                self._coroutines.remove(entry)
            except Exception as e:
                print("[脚本] 协程异常 (%s): %r"
                      % (self.script_id or '?', e))
                try:
                    gen.close()
                except Exception:
                    pass
                self._coroutines.remove(entry)

    def update(self, dt):
        """每帧播放期调用. dt 为秒."""
        pass


# ================ 内置脚本 ================

@register
class RotateScript(Script):
    """自转: 绕自身轴旋转 (角度/秒)"""
    script_id = 'rotate'
    name = '自转'
    params = (('sx', 'X速度°', 0.0, -720, 720, '%.1f'),
              ('sy', 'Y速度°', 90.0, -720, 720, '%.1f'),
              ('sz', 'Z速度°', 0.0, -720, 720, '%.1f'))

    def update(self, dt):
        o = self.obj
        o.rotation = Point3D(o.rotation.x + math.radians(self.vals['sx']) * dt,
                             o.rotation.y + math.radians(self.vals['sy']) * dt,
                             o.rotation.z + math.radians(self.vals['sz']) * dt)


@register
class OrbitScript(Script):
    """公转: 绕世界中心点旋转 (默认原点), 保持进入播放时的半径与高度差"""
    script_id = 'orbit'
    name = '公转'
    params = (('cx', '中心X', 0.0, -50, 50, '%.1f'),
              ('cy', '中心Y', 0.0, -50, 50, '%.1f'),
              ('cz', '中心Z', 0.0, -50, 50, '%.1f'),
              ('speed', '转速°', 45.0, -360, 360, '%.1f'))

    def on_start(self):
        c = (self.vals['cx'], self.vals['cy'], self.vals['cz'])
        p = self.engine.world_position(self.obj)
        self._dy = p.y - c[1]                       # 保持高度差
        self._ang = math.atan2(p.z - c[2], p.x - c[0])
        self._rad = math.hypot(p.x - c[0], p.z - c[2])

    def update(self, dt):
        self._ang += math.radians(self.vals['speed']) * dt
        c = (self.vals['cx'], self.vals['cy'], self.vals['cz'])
        self.obj.position = Point3D(c[0] + self._rad * math.cos(self._ang),
                                    c[1] + self._dy,
                                    c[2] + self._rad * math.sin(self._ang))


@register
class BobScript(Script):
    """浮动: 沿 Y 上下正弦浮动 (以进入播放时的高度为基)"""
    script_id = 'bob'
    name = '浮动'
    params = (('amp', '幅度', 0.5, 0.0, 5.0, '%.2f'),
              ('freq', '频率', 1.0, 0.0, 10.0, '%.2f'))

    def on_start(self):
        self._base_y = self.obj.position.y
        self._t = 0.0

    def update(self, dt):
        self._t += dt
        o = self.obj
        o.position = Point3D(o.position.x,
                             self._base_y + self.vals['amp'] * math.sin(
                                 self.vals['freq'] * self._t * 2 * math.pi),
                             o.position.z)


@register
class WASDMoveScript(Script):
    """WASD 移动 (世界轴): W=+z 前, S=-z 后, A=-x 左, D=+x 右.
    M30b: 改用输入动作层 get_action('向前/向后/向左/向右') —— 键位重映射(输入配置.json)
    后脚本自动跟随, 不用改脚本. 走 move_with_collision (M28) 撞到碰撞体被挡下."""
    script_id = 'wasd_move'
    name = 'WASD移动'
    params = (('speed', '速度', 3.0, 0.0, 30.0, '%.1f'),)

    def update(self, dt):
        a = self.engine.get_action
        dx = (1 if a('向右') else 0) - (1 if a('向左') else 0)
        dz = (1 if a('向前') else 0) - (1 if a('向后') else 0)
        if dx or dz:
            s = self.vals['speed'] * dt
            self.engine.move_with_collision(self.obj, dx * s, 0.0, dz * s)


@register
class CameraFollowScript(Script):
    """相机跟随: 轨道相机目标锁定本物体世界位置 (+偏移). 与 WASD移动组合 =
    一个最小第三人称演示 (相机自动跟着玩家走)."""
    script_id = 'camera_follow'
    name = '相机跟随'
    params = (('oy', '高度偏移', 2.0, -10, 10, '%.1f'),
              ('oz', '距离偏移', 0.0, -10, 10, '%.1f'))

    def update(self, dt):
        p = self.engine.world_position(self.obj)
        self.engine.camera_target = (p.x, p.y + self.vals['oy'],
                                     p.z + self.vals['oz'])


# ================ 物理脚本 (M28: 简单碰撞) ================
# 依赖引擎碰撞: engine.move_with_collision(obj, dx,dy,dz) 带碰撞移动,
# engine.get_collisions(obj) 查询碰撞 —— 详见 scripts.py 顶部 docstring.

@register
class FallScript(Script):
    """重力落地: 自由落体, 碰到下面的碰撞体就停住 (最基本物理演示).
    把球/立方体放到平面上方, 挂上它, 按播放就能看到落体+落地.
    碰撞体: 所有物体默认都有 (球=球体, 其他=盒子); 纯装饰可关掉."""
    script_id = 'fall'
    name = '重力落地'
    params = (('g', '重力', -9.8, -30.0, -1.0, '%.1f'),)

    def on_start(self):
        self._vy = 0.0

    def update(self, dt):
        self._vy += self.vals['g'] * dt
        hit = self.engine.move_with_collision(self.obj, 0.0, self._vy * dt, 0.0)
        if hit:
            self._vy = 0.0


@register
class BounceScript(Script):
    """弹跳: 重力下落, 碰到下面碰撞体反弹 (衰减). 演示"碰撞响应"最直观的一档."""
    script_id = 'bounce'
    name = '弹跳'
    params = (('g', '重力', -9.8, -30.0, -1.0, '%.1f'),
              ('rest', '弹力', 0.7, 0.0, 1.0, '%.2f'))

    def on_start(self):
        self._vy = 0.0

    def update(self, dt):
        self._vy += self.vals['g'] * dt
        hit = self.engine.move_with_collision(self.obj, 0.0, self._vy * dt, 0.0)
        if hit and self._vy < 0:
            self._vy = -self._vy * self.vals['rest']


# ==================== 玩家控制器 (M32, 承接 Unity 玩家控制 + 输入动作层) ====================
@register
class FirstPersonScript(Script):
    """第一人称玩家控制器: WASD 沿视角前方移动 (带碰撞) + 鼠标转动视角 + 跳跃.
    挂到角色物体 (建议加刚体受重力); 播放期脚本接管相机 = 角色眼高视角."""
    script_id = 'first_person'
    name = '第一人称'
    params = (('speed', '速度', 5.0, 0.0, 30.0, '%.1f'),
              ('eye', '眼高', 1.6, 0.0, 5.0, '%.1f'),
              ('sens', '鼠标灵敏度', 0.002, 0.0, 0.01, '%.3f'),
              ('jump_v', '跳跃速度', 6.0, 0.0, 20.0, '%.1f'))

    def on_start(self):
        self.yaw = self.engine.camera_yaw
        self.pitch = self.engine.camera_pitch
        self._tab_was = False
        sml = getattr(self.engine, 'set_mouse_locked', None)   # M39: 播放锁定鼠标
        if sml is not None:
            sml(True)

    def update(self, dt):
        e = self.engine
        # M39: Tab 切换鼠标锁定 (按下帧检测); 释放状态鼠标滑动不转视角
        tab = e.is_key('Tab')
        if tab and not self._tab_was:
            e.toggle_mouse_locked()
        self._tab_was = tab
        if getattr(e, 'mouse_locked', True):   # 仅锁定状态用鼠标转视角
            mx, my = getattr(e, 'mouse_rel', (0, 0))
            self.yaw += mx * self.vals['sens']
            # M41: 激活相机开俯仰角限制则夹到 [pitch_min,pitch_max], 否则默认 ±1.5rad
            lim = e.player_pitch_limits()
            self.pitch = (max(lim[0], min(lim[1], self.pitch - my * self.vals['sens']))
                          if lim else max(-1.5, min(1.5,
                                                    self.pitch - my * self.vals['sens'])))
        # WASD 沿视角前方水平移动 (带碰撞, 撞墙被挡)
        fwd = (math.sin(self.yaw), 0.0, math.cos(self.yaw))
        right = (math.cos(self.yaw), 0.0, -math.sin(self.yaw))
        a = e.get_action
        dx = (1 if a('向右') else 0) - (1 if a('向左') else 0)
        dz = (1 if a('向前') else 0) - (1 if a('向后') else 0)
        if dx or dz:
            s = self.vals['speed'] * dt
            e.move_with_collision(self.obj,
                                  right[0] * dx * s + fwd[0] * dz * s, 0.0,
                                  right[2] * dx * s + fwd[2] * dz * s)
        # 跳跃 (需刚体; 仅当已落地/速度接近 0)
        rb = getattr(self.obj, 'rigidbody', None)
        if a('跳跃') and rb is not None and abs(rb.velocity.y) < 0.01:
            rb.velocity = Point3D(rb.velocity.x, self.vals['jump_v'],
                                  rb.velocity.z)
        # 接管相机: 位置 = 角色 + 眼高, 朝向 = 脚本 yaw/pitch (关闭轨道相机)
        # ★2026-09-06 相机统一 (用户定案): 播放态相机逻辑 = 编辑态轨道相机
        # (target/yaw/pitch/distance 四元组驱动, apply_orbit_camera 合成)。
        # 玩家脚本不再写相机 —— 旧"每逻辑帧强写 e.camera"与开发者 WASD
        # 移动互冲 (双驱动源, 谁后写谁赢), 是开发者相机移动 BUG 的总根。
        # 角色移动/跳跃不受影响; 相机跟随由开发者视角自行控制。
        # (orbit_mode 也不再切换 — 播放/编辑同一轨道几何)


@register
class ThirdPersonScript(Script):
    """第三人称玩家控制器: 角色移动 (相机前方) + 鼠标转向 + 相机跟在角色后方上方.
    挂到角色物体 (建议加刚体); 相机距离/高度可调."""
    script_id = 'third_person'
    name = '第三人称'
    params = (('speed', '速度', 5.0, 0.0, 30.0, '%.1f'),
              ('dist', '相机距离', 6.0, 1.0, 30.0, '%.1f'),
              ('height', '相机高度', 3.0, 0.0, 10.0, '%.1f'),
              ('sens', '鼠标灵敏度', 0.002, 0.0, 0.01, '%.3f'))

    def on_start(self):
        self.yaw = self.engine.camera_yaw
        self.pitch = self.engine.camera_pitch
        self._tab_was = False
        sml = getattr(self.engine, 'set_mouse_locked', None)   # M39: 播放锁定鼠标
        if sml is not None:
            sml(True)

    def update(self, dt):
        e = self.engine
        # M39: Tab 切换鼠标锁定; 释放状态鼠标滑动不转视角
        tab = e.is_key('Tab')
        if tab and not self._tab_was:
            e.toggle_mouse_locked()
        self._tab_was = tab
        if getattr(e, 'mouse_locked', True):
            mx, my = getattr(e, 'mouse_rel', (0, 0))
            self.yaw += mx * self.vals['sens']
            # M41: 激活相机开俯仰角限制则夹到 [pitch_min,pitch_max], 否则默认 ±1.4rad
            lim = e.player_pitch_limits()
            self.pitch = (max(lim[0], min(lim[1], self.pitch - my * self.vals['sens']))
                          if lim else max(-1.4, min(1.4,
                                                    self.pitch - my * self.vals['sens'])))
        fwd = (math.sin(self.yaw), 0.0, math.cos(self.yaw))
        right = (math.cos(self.yaw), 0.0, -math.sin(self.yaw))
        a = e.get_action
        dx = (1 if a('向右') else 0) - (1 if a('向左') else 0)
        dz = (1 if a('向前') else 0) - (1 if a('向后') else 0)
        if dx or dz:
            s = self.vals['speed'] * dt
            e.move_with_collision(self.obj,
                                  right[0] * dx * s + fwd[0] * dz * s, 0.0,
                                  right[2] * dx * s + fwd[2] * dz * s)
        # 角色朝向 yaw (播放期脚本控制)
        self.obj.rotation = Point3D(0, self.yaw, 0)
        # 相机统一 (2026-09-06 用户定案): 脚本不再写相机 (见 first_person 注)


@register
class JumpScript(Script):
    """跳跃 (M32): 挂到带刚体的角色, 按'跳跃'动作给向上速度 (落地后才能再跳).
    可与 wasd_move/first_person 等组合."""
    script_id = 'jump'
    name = '跳跃'
    params = (('v', '跳跃速度', 6.0, 0.0, 20.0, '%.1f'),)

    def update(self, dt):
        rb = getattr(self.obj, 'rigidbody', None)
        if rb is None:
            return
        if self.engine.get_action('跳跃') and abs(rb.velocity.y) < 0.01:
            rb.velocity = Point3D(rb.velocity.x, self.vals['v'], rb.velocity.z)


@register
class CountTouchScript(Script):
    """触碰计数彩球 (2026-08-22 教学演示, M33 运行时 UI 配套):
    挂在彩球上, 玩家(名字='玩家')碰到 -> 彩球消失, 右上角 HUD 计数 +1.
    展示三件事: ①脚本里做碰撞判定 (engine.get_collisions);
    ②运行时 UI (engine.ui.text 每帧声明, 引擎画在游戏 HUD 层);
    ③脚本 self.engine / self.obj / self.vals 用法 (教学参考脚本).
    生产建议: 碰撞判定用正式碰撞事件/按 guid 区分对象, 名字字符串仅供教学."""
    script_id = 'count_touch'
    name = '触碰计数彩球'
    params = ()

    def on_start(self):
        self.hits = getattr(self.engine, '_count_hits', 0)
        self._hit_printed = False   # 已碰到标志
        # 2026-10-18: RuntimeUI 淘汰, 改用 Canvas UI 保留模式 —— on_start 建一次元素,
        # update 只改 text 属性 (不再每帧声明命令).
        import loom_ui
        e = self.engine
        canvas = e.ui.default_canvas()
        self._hud_text = loom_ui.Text(
            name='_count_touch_hud',
            rect=(20, 20, 500, 30),
            text='碰到的彩球: %d' % self.hits,
            font_size=22,
            color=(255, 255, 255))
        canvas.root.add_child(self._hud_text)

    def update(self, dt):
        e = self.engine
        if self._hit_printed:
            return
        for other in e.get_collisions(self.obj):
            if other.name == '玩家':
                self._hit_printed = True
                self.hits += 1
                e._count_hits = self.hits
                e.remove_model(self.obj)
                # 修复 (2026-10-14 小游戏实测): 物体已移除, 必须立即 return ——
                # 否则下方 e.models.index(self.obj) 对已移除物体抛 ValueError。
                return
        # 用"剩余第一个球"当 HUD 载体 (简单转移, 教学用)
        if e.models and e.models.index(self.obj) == 0:
            total = sum(1 for m in e.models if m.name.startswith('彩球'))
            if self._hud_text is not None:
                self._hud_text.text = "碰到的彩球: %d  (剩余 %d)" % (self.hits, total)
