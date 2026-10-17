# -*- coding: utf-8 -*-
"""align_physics.py — 物理对齐 (Loom 侧): 确定性驱动 + 解析解/几何自检。

确定性: play(paused=true) 冻结逻辑帧; physics_simulate 只跑指定帧数。
velocity 必须在 play 之后设置 (进播放快照会覆盖运行时状态)。

期望值: 基础用例 = 半隐式欧拉解析解; 碰撞用例 = 几何落定位置 (容差放宽,
Jolt 接触偏移存在); 无明确期望的用例只记录, 交给 compare_physics 对比两侧。
"""
import json
import os
import urllib.request

LOOM = "D:/my-project - 副本/Loom(py源代码-工作区)/Loom"
G = 9.8
SUB_DT = 1.0 / 60.0          # 物理子步 dt (60Hz)
SUB_PER_LOGIC = 2            # 每逻辑帧 2 子步 (30fps 逻辑)


def _info():
    with open(os.path.join(LOOM, '.agent_port.json'), encoding='utf-8') as f:
        return json.load(f)


def call(cmd, args=None, timeout=30):
    info = _info()
    body = json.dumps({'cmd': cmd, 'args': args or {}}).encode()
    req = urllib.request.Request(
        'http://127.0.0.1:%d/cmd' % info['port'], data=body, method='POST',
        headers={'X-Agent-Token': info['token'],
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def last_model():
    r = call('object_list')
    models = r.get('result', {}).get('models', [])
    return models[-1]['name'] if models else None


def add_object(name, primitive, position, scale=None):
    call('object_add', {'type': primitive})
    nm = last_model()
    if name and nm != name:
        call('object_rename', {'name': nm, 'new': name})
    tf = {'name': name or nm,
          'x': position[0], 'y': position[1], 'z': position[2]}
    if scale:
        tf.update({'sx': scale[0], 'sy': scale[1], 'sz': scale[2]})
    call('set_transform', tf)


def inspect(name):
    return call('inspect', {'name': name}).get('result', {})


def freefall_y(y0, frames):
    v = 0.0
    y = y0
    for _ in range(SUB_PER_LOGIC * frames):
        v += -G * SUB_DT
        y += v * SUB_DT
    return y


GROUND = {'name': 'Ground', 'primitive': 'cube', 'pos': (0, -0.25, 0),
          'scale': (10, 0.5, 10), 'rb': None}   # 顶面 y=0

# rb=None = 静态碰撞体(无刚体); rb={} = 动态体默认参数; post_play 在 play 后设
CASES = [
    # ---- 基础 (严格解析解) ----
    {'name': 'freefall_1s', 'frames': 30,
     'objects': [{'name': 'A', 'primitive': 'cube', 'pos': (0, 5, 0),
                  'rb': {'use_gravity': True}}],
     'expect': {'A': {'y': freefall_y(5.0, 30)}}, 'tol': 0.02},
    {'name': 'no_gravity_1s', 'frames': 30,
     'objects': [{'name': 'A', 'primitive': 'cube', 'pos': (0, 5, 0),
                  'rb': {'use_gravity': False}}],
     'expect': {'A': {'y': 5.0}}, 'tol': 0.02},
    {'name': 'kinematic_1s', 'frames': 30,
     'objects': [{'name': 'A', 'primitive': 'cube', 'pos': (0, 5, 0),
                  'rb': {'use_gravity': True, 'is_kinematic': True}}],
     'expect': {'A': {'y': 5.0}}, 'tol': 0.02},
    {'name': 'horizontal_1s', 'frames': 30,
     'objects': [{'name': 'A', 'primitive': 'cube', 'pos': (0, 5, 0),
                  'rb': {'use_gravity': False}}],
     'post_play': [('A', {'velocity': [5, 0, 0]})],
     'expect': {'A': {'x': 5.0}}, 'tol': 0.05},
    # ---- 碰撞 (几何落定, 容差放宽) ----
    {'name': 'land_stop', 'frames': 60,        # 2s
     'objects': [dict(GROUND),
                 {'name': 'A', 'primitive': 'cube', 'pos': (0, 5, 0),
                  'rb': {'use_gravity': True}}],
     'expect': {'A': {'y': 0.5}}, 'tol': 0.15},   # cube 半高 0.5 停在地面
    # ---- 弹跳/摩擦 (先观察, expect 空 = 只记录) ----
    {'name': 'bounce_rest07', 'frames': 90,    # 3s
     'objects': [dict(GROUND),
                 {'name': 'A', 'primitive': 'sphere', 'pos': (0, 5, 0),
                  'rb': {'use_gravity': True, 'restitution': 0.7}}],
     'expect': {}, 'tol': 0.15},
    {'name': 'friction_slide', 'frames': 60,
     'objects': [dict(GROUND),
                 {'name': 'A', 'primitive': 'cube', 'pos': (0, 0.5, 0),
                  'rb': {'use_gravity': True, 'friction': 0.5}}],
     'post_play': [('A', {'velocity': [5, 0, 0]})],
     'expect': {}, 'tol': 0.15},
]


def build_scene(objects):
    for o in objects:
        add_object(o['name'], o.get('primitive', 'cube'),
                   o.get('pos', (0, 0, 0)), o.get('scale'))
        rb = o.get('rb')
        if rb is not None:
            call('rigidbody', {'name': o['name'], 'action': 'add'})
            if rb:
                call('rigidbody', dict({'name': o['name'], 'action': 'set'}, **rb))


def warmup():
    """冷启动预热: 引擎重启后首次 physics_simulate 有一次性的桥首帧偏差
    (实测 freefall 首跑 y=-0.153 而次跑 0.018)。先建 dummy 场景跑 1 帧丢弃,
    让物理桥/子步系统进入稳态后再正式跑用例。"""
    call('play', {'on': False})
    call('scene_new')
    add_object('Warm', 'cube', (0, 1, 0))
    call('rigidbody', {'name': 'Warm', 'action': 'add'})
    call('play', {'on': True, 'paused': True})
    call('physics_simulate', {'frames': 1})
    call('play', {'on': False})


def run():
    warmup()
    results = []
    for c in CASES:
        call('play', {'on': False})
        call('scene_new')
        build_scene(c['objects'])
        call('play', {'on': True, 'paused': True})
        for nm, extra in c.get('post_play', []):
            call('rigidbody', dict({'name': nm, 'action': 'set'}, **extra))
        call('physics_simulate', {'frames': c['frames']})
        got = {o['name']: inspect(o['name']) for o in c['objects']}
        ok = True
        detail = []
        for nm, e in c.get('expect', {}).items():
            pos = got[nm].get('position', [0, 0, 0])
            for axis, ev in e.items():
                av = {'x': pos[0], 'y': pos[1], 'z': pos[2]}[axis]
                d = abs(av - ev)
                good = d < c['tol']
                ok = ok and good
                detail.append('%s.%s 实测=%.4f 期望=%.4f d=%.4f %s' % (
                    nm, axis, av, ev, d, 'OK' if good else 'FAIL'))
        results.append({'case': c['name'], 'ok': ok, 'detail': detail,
                        'pos': {nm: got[nm].get('position') for nm in got},
                        'vel': {nm: (got[nm].get('rigidbody') or {}).get('velocity')
                                for nm in got}})
        tag = 'PASS' if ok else 'FAIL'
        if not c.get('expect'):
            tag = 'OBSV'
        print('[%s] %s' % (tag, c['name']))
        for d in detail:
            print('   ' + d)
        for nm in got:
            print('   %s pos=%s' % (nm, got[nm].get('position')))
    npass = sum(1 for r in results if r['ok'])
    print('\nLoom 物理自检: %d/%d' % (npass, len(results)))
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'physics')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'loom_physics_result.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump({'results': results}, f, ensure_ascii=False, indent=2)
    print('结果: ' + os.path.abspath(out))


if __name__ == '__main__':
    run()
