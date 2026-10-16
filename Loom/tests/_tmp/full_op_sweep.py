# -*- coding: utf-8 -*-
"""full_op_sweep.py — 全功能操作大巡检 (2026-09-06 用户指令)

范围: agent_commands._COMMANDS 全表 53 条, 按各命令参数契约实跑 (签名已
逐条核对 agent_commands.py 源码)。弹系统对话框的转人工 (SKIP-DIALOG)。
结果逐条记录 sweep_result.json + 台账补登。发现问题即修。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
PY = sys.executable

scene = os.path.join(LOOM, '保存', '场景.json')
out_json = os.path.join(HERE, 'sweep_result.json')

sys.path.insert(0, LOOM)
import guiloader  # noqa: E402


def write_settings(d):
    s = guiloader.load_settings('loom', base=LOOM)
    s.update(d)
    guiloader.save_settings('loom', s, base=LOOM)


def launch():
    cmd = [PY, '-u', os.path.join(LOOM, 'Loom.py'),
           '--open', scene, '--agent']
    proc = subprocess.Popen(cmd, cwd=LOOM,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    info = None
    t0 = time.time()
    while time.time() - t0 < 40:
        try:
            with open(os.path.join(LOOM, '.agent_port.json'),
                      encoding='utf-8') as f:
                cand = json.load(f)
            if cand.get('pid') == proc.pid and cand.get('port'):
                info = cand
                break
        except Exception:
            pass
        time.sleep(0.5)
    if info is None:
        proc.kill()
        raise RuntimeError('端口文件 40s 未就绪')
    return proc, info['port'], info['token']


def call(port, token, cmd_name, args=None, timeout=35):
    body = json.dumps({'cmd': cmd_name, 'args': args or {}}).encode('utf-8')
    req = urllib.request.Request(
        'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
        headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


results = []


def rec(name, args, resp, note=''):
    ok = bool(resp.get('ok'))
    err = resp.get('error') if not ok else None
    r = resp.get('result')
    rsum = None
    if isinstance(r, dict):
        rsum = {k: r[k] for k in list(r)[:5]}
    elif isinstance(r, list):
        rsum = 'list[%d]' % len(r)
    results.append({'cmd': name, 'args': args, 'ok': ok, 'error': err,
                    'result': rsum, 'note': note})
    print(('[OK]  ' if ok else '[FAIL]') + ' ' + name +
          (' ' + json.dumps(args, ensure_ascii=False)[:50] if args else '') +
          (' ERR=' + str(err)[:90] if err else ''), flush=True)


def run_sweep():
    proc, port, token = launch()

    def CR(name, args=None, **kw):
        resp = call(port, token, name, args, **kw)
        rec(name, args, resp)
        return resp.get('result', {}) if resp.get('ok') else None

    try:
        time.sleep(7.0)
        # ========== 状态/设置/指标 (5) ==========
        st = CR('status')
        CR('settings_get', {})
        CR('settings_get', {'key': 'fps_limit'})
        CR('settings_set', {'key': 'gravity', 'value': -9.8})
        CR('engine_metrics', {})

        # ========== 物体 CRUD (15) ==========
        CR('object_add', {'type': 'cube'})
        CR('object_add', {'type': 'sphere'})
        lst = CR('object_list', {})
        names = [m['name'] for m in (lst or {}).get('models', [])]
        target = names[-1] if names else None
        CR('object_select', {'name': target})
        CR('object_rename', {'name': target, 'new': 'sweep_obj'})
        CR('object_duplicate', {})          # 复制当前选中 (sweep_obj)
        CR('set_visible', {'name': 'sweep_obj', 'on': False})
        CR('set_visible', {'name': 'sweep_obj', 'on': True})
        CR('gizmo', {'mode': 'move'})
        CR('gizmo', {'mode': 'rotate'})
        CR('gizmo', {'mode': 'scale'})
        CR('undo', {})
        CR('redo', {})
        CR('set_transform', {'name': 'sweep_obj', 'x': 3.0, 'y': 2.0, 'z': 1.0,
                             'rx': 10.0, 'ry': 20.0, 'rz': 30.0,
                             'sx': 1.5, 'sy': 1.5, 'sz': 1.5})
        CR('inspect', {'name': 'sweep_obj'})

        # ========== 材质 (4) ==========
        CR('materials', {})
        CR('material_new', {'name': 'sweep_obj'})   # 对选中物新建材质
        CR('set_material', {'name': 'sweep_obj', 'index': 0})
        CR('set_saturation', {'name': 'sweep_obj', 'value': 1.5})

        # ========== 组件 (7) ==========
        CR('collider', {'name': 'sweep_obj', 'on': True})
        CR('rigidbody', {'name': 'sweep_obj', 'action': 'add'})
        CR('rigidbody', {'name': 'sweep_obj', 'action': 'gravity'})
        CR('audio', {'name': 'sweep_obj', 'action': 'add'})
        CR('animator', {'name': 'sweep_obj', 'action': 'add'})
        CR('script_add', {'sid': 'rotate', 'target': 'sweep_obj'})
        CR('scripts', {'name': 'sweep_obj'})
        CR('script_var', {'name': 'sweep_obj', 'index': 0,
                          'key': 'speed', 'value': 45.0})
        CR('script_remove', {'name': 'sweep_obj', 'index': 0})
        CR('rigidbody', {'name': 'sweep_obj', 'action': 'remove'})
        CR('audio', {'name': 'sweep_obj', 'action': 'remove'})
        CR('animator', {'name': 'sweep_obj', 'action': 'remove'})

        # ========== 光源/相机 (10) ==========
        CR('light_add', {'kind': 'point'})
        CR('light_set', {'name': '点光源', 'intensity': 2.0})
        CR('light_set', {'name': '点光源', 'shadow': True, 'mode': 'full'})
        CR('camera_add', {})
        camlst = CR('object_list', {})
        cams = [c['name'] for c in (camlst or {}).get('cameras', [])]
        cam_name = cams[-1] if cams else None    # 默认名 摄像机N (动态取)
        CR('camera_move', {'name': cam_name, 'x': 5.0, 'y': 5.0, 'z': 10.0})
        CR('camera_look', {'name': cam_name, 'yaw': 45.0, 'pitch': -20.0})
        CR('camera_active', {'name': cam_name})
        CR('camera_active', {})                 # 取消激活
        CR('camera_preview', {'name': cam_name})
        CR('camera_preview', {'off': True})
        CR('reparent', {'child': 'sweep_obj', 'parent': '立方体1'})
        CR('reparent', {'child': 'sweep_obj'})  # 脱父

        # ========== 播放/截图 (3) ==========
        CR('play', {'on': True})
        time.sleep(4.0)
        CR('play', {'on': False})
        time.sleep(1.0)
        CR('screenshot', {'file': os.path.join(HERE, 'sweep_shot.png'),
                          'full': True})

        # ========== Prefab (3) ==========
        CR('prefab_save', {})                   # 用工具栏 prefab 名 (prefab)
        CR('prefab_place', {})
        lst2 = CR('object_list', {})
        sobjs = [(m['name'], m['index']) for m in (lst2 or {}).get('models', [])
                 if m['name'] == 'sweep_obj']
        # 放实例后有重名 sweep_obj (本体+实例) — 按 index 精确指 (契约: 重名须 index)
        if len(sobjs) >= 2:
            CR('prefab_unlink', {'name': 'sweep_obj', 'index': sobjs[-1][1]})
        else:
            CR('prefab_unlink', {'name': 'sweep_obj'})

        # ========== 资产 (3) ==========
        al = CR('assets', {})
        akeys = [(a.get('type'), a.get('key')) for a in (al or {}).get('assets', [])]
        mat_keys = [k for t, k in akeys if t == 'material']
        if mat_keys:
            CR('asset_apply', {'type': 'material', 'key': mat_keys[0],
                               'name': 'sweep_obj'})
        else:
            rec('asset_apply', {'note': 'empty material assets'},
                {'ok': True, 'result': 'SKIP (无材质资产)'})
        CR('asset_save', {'what': 'material',
                          'path': os.path.join(LOOM, '材质')})

        # ========== 插件 (1) ==========
        CR('plugins', {})
        # plugin_button: 空插件表时报错=正确防御 (第 1 轮已验证), 正向路径
        # 依赖具体插件, GUI 侧人工验证。

        # ========== 场景管理 (2, 放最后清场) ==========
        CR('scene_new', {})
        CR('object_add', {'type': 'cube'})
        CR('scene_load', {'path': scene})
        time.sleep(1.0)

        # SKIP-DIALOG 人工项: scene_save (另存对话框) / import_obj (文件
        # 对话框; 命令行须 path + 白名单, 留人工)
    finally:
        try:
            call(port, token, 'quit', {'save': 'discard', 'after': 0.2})
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()


run_sweep()

n_ok = sum(1 for r in results if r['ok'])
n_fail = sum(1 for r in results if not r['ok'])
print('[sweep summary] total=%d ok=%d fail=%d' % (
    len(results), n_ok, n_fail), flush=True)
for r in results:
    if not r['ok']:
        print('  FAIL:', r['cmd'], r['error'], flush=True)

with open(out_json, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print('[done]', out_json, flush=True)
