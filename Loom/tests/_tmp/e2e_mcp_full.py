
# -*- coding: utf-8 -*-
"""MCP 全功能自动化验收：起真实编辑器 -> 真 MCP stdio 协议 -> 逐操作验证。"""
import os, sys, json, time, subprocess
from PIL import ImageGrab

LOOM = r"D:\\my-project - 副本\\Loom(py源代码-工作区)\\Loom"
PORTF = os.path.join(LOOM, ".agent_port.json")
SHOTS = os.path.join(LOOM, "tests", "_tmp", "e2e_full")
os.makedirs(SHOTS, exist_ok=True)
try: os.remove(PORTF)
except Exception: pass

env = dict(os.environ); env['LOOM_AGENT_PACE_MS'] = '120'
env['PYTHONIOENCODING'] = 'utf-8'
ed = None; mcp = None
steps = []
def shot(tag):
    try:
        time.sleep(0.5); ImageGrab.grab().save(os.path.join(SHOTS, tag + '.png'))
    except Exception as e:
        print('  [shot fail]', tag, repr(e))

try:
    # ---------- 1) 起编辑器 ----------
    ed = subprocess.Popen([sys.executable, 'Loom.py', '--agent'], cwd=LOOM, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    info = None
    for _ in range(160):
        if os.path.exists(PORTF):
            try:
                info = json.load(open(PORTF, encoding='utf-8')); break
            except Exception: pass
        time.sleep(0.25)
    if not info:
        print('FAIL 编辑器未就绪'); sys.exit(2)
    print('编辑器就绪 port=%d pid=%d' % (info['port'], ed.pid))
    time.sleep(3.0)

    # ---------- 2) 起 MCP 服务 ----------
    mcp = subprocess.Popen([sys.executable, 'loom_mcp.py'], cwd=LOOM, env=env,
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1)
    _id = [0]
    def rpc(method, params=None):
        _id[0] += 1
        req = {'jsonrpc': '2.0', 'id': _id[0], 'method': method}
        if params: req['params'] = params
        mcp.stdin.write(json.dumps(req, ensure_ascii=False) + '\n'); mcp.stdin.flush()
        line = mcp.stdout.readline()
        if not line: raise RuntimeError('MCP 无响应/进程退出')
        return json.loads(line)

    def call(name, args=None):
        r = rpc('tools/call', {'name': name, 'arguments': args or {}})
        if 'error' in r: return {'isError': True, 'text': 'JSONRPC-ERR ' + str(r['error'])[:200]}
        res = r.get('result') or {}
        txt = ''
        try: txt = res['content'][0]['text']
        except Exception: txt = json.dumps(res, ensure_ascii=False)[:300]
        return {'isError': bool(res.get('isError')), 'text': txt}

    def step(label, name, args=None, need=None):
        t0 = time.time()
        try:
            r = call(name, args)
            ok = (not r['isError']) and (need is None or need in r['text'])
            steps.append({'label': label, 'tool': name, 'ok': bool(ok),
                          'ms': int((time.time()-t0)*1000), 'text': r['text'][:400]})
        except Exception as e:
            steps.append({'label': label, 'tool': name, 'ok': False, 'ms': 0, 'text': 'EXC ' + repr(e)})
        s = steps[-1]
        print(('PASS' if s['ok'] else 'FAIL'), label, '|', s['text'][:110].replace('\n', ' '))

    # ---------- 3) 协议握手 ----------
    r = rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'e2e'}})
    proto = (r.get('result') or {}).get('protocolVersion')
    steps.append({'label': 'initialize 握手', 'tool': 'initialize', 'ok': bool(proto), 'ms': 0, 'text': str(proto)})
    print(('PASS' if proto else 'FAIL'), 'initialize | protocolVersion=', proto)
    tl = rpc('tools/list')
    n_tools = len(((tl.get('result') or {}).get('tools')) or [])
    steps.append({'label': 'tools/list', 'tool': 'tools/list', 'ok': n_tools >= 70, 'ms': 0, 'text': 'tools=%d' % n_tools})
    print(('PASS' if n_tools >= 70 else 'FAIL'), 'tools/list |', n_tools, '个工具')
    for m in ('resources/list', 'prompts/list'):
        rr = rpc(m)
        ok = 'result' in rr
        steps.append({'label': m, 'tool': m, 'ok': ok, 'ms': 0, 'text': json.dumps(rr.get('result'))[:120]})
        print(('PASS' if ok else 'FAIL'), m)

    # ---------- 4) 场景与物体 ----------
    step('新建空场景', 'unity_scene_new')
    step('创建立方体', 'unity_gameobject_create', {'primitive': 'cube', 'name': 'AI_Cube', 'position': [0, 0.5, 0]}, need='AI_Cube')
    step('创建球体', 'unity_gameobject_create', {'primitive': 'sphere', 'name': 'AI_Sphere', 'position': [2, 0.5, 0]}, need='AI_Sphere')
    step('创建平面', 'unity_gameobject_create', {'primitive': 'plane', 'name': 'AI_Plane', 'position': [0, 0, 0]}, need='AI_Plane')
    step('列出物体', 'unity_gameobject_list', None, need='AI_Cube')
    shot('01_created')
    step('选中立方体', 'unity_gameobject_select', {'name_or_id': 'AI_Cube'}, need='AI_Cube')
    step('改位置', 'unity_transform_set', {'name_or_id': 'AI_Cube', 'position': [1.5, 1.0, 0.5]})
    step('改颜色', 'unity_material_set', {'name_or_id': 'AI_Cube', 'color': '#FF8800'})
    step('隐藏', 'unity_object_set_visible', {'name_or_id': 'AI_Cube', 'visible': False})
    step('显示', 'unity_object_set_visible', {'name_or_id': 'AI_Cube', 'visible': True})
    shot('02_transformed')
    step('加平行光', 'unity_light_add', {'kind': 'dir'})
    step('加相机', 'unity_camera_add')
    step('射线检测', 'loom_raycast', {'ox': 0, 'oy': 5, 'oz': 0, 'dx': 0, 'dy': -1, 'dz': 0})
    step('按名查找', 'loom_find_by_name', {'model': 'AI_Cube'}, need='AI_Cube')
    step('UI 文本', 'loom_ui_add', {'type': 'text', 'name': 'AI_Title', 'text': 'E2E'}, need='AI_Title')

    # ---------- 5) 批次撤销 ----------
    step('批次开始', 'loom_eai_call', {'cmd': 'agent_batch_begin', 'args': {}})
    for i in range(3):
        step('批次内创建 %d' % i, 'unity_gameobject_create',
             {'primitive': 'cube', 'name': 'BATCH_%d' % i, 'position': [i * 1.5, 0.5, 3]}, need='BATCH_%d' % i)
    step('批次结束', 'loom_eai_call', {'cmd': 'agent_batch_end', 'args': {}})
    shot('03_batch')
    step('一步撤销批次', 'unity_undo')
    r = call('unity_gameobject_list')
    gone = ('BATCH_0' not in r['text']) and ('BATCH_1' not in r['text']) and ('BATCH_2' not in r['text'])
    steps.append({'label': '批次撤销后 3 个物体消失', 'tool': 'unity_gameobject_list', 'ok': gone, 'ms': 0, 'text': r['text'][:200]})
    print(('PASS' if gone else 'FAIL'), '批次撤销后 3 个物体消失')
    step('一步重做批次', 'unity_redo')
    r = call('unity_gameobject_list')
    back = all(('BATCH_%d' % i) in r['text'] for i in range(3))
    steps.append({'label': '重做后 3 个物体恢复', 'tool': 'unity_gameobject_list', 'ok': back, 'ms': 0, 'text': r['text'][:200]})
    print(('PASS' if back else 'FAIL'), '重做后 3 个物体恢复')

    # ---------- 6) 播放 + 物理 ----------
    step('进入播放', 'unity_playmode_toggle', {'on': True})
    shot('04_playing')
    step('物理推进 10 帧', 'unity_physics_simulate', {'frames': 10})
    step('退出播放', 'unity_playmode_toggle', {'on': False})

    # ---------- 7) 视口截图 / 存档往返 ----------
    vp = os.path.join(SHOTS, '05_viewport.png')
    step('视口截图', 'unity_capture_viewport', {'path': vp})
    sp = os.path.join(LOOM, 'tests', '_tmp', 'e2e_full', 'AI_E2E.json')
    step('保存场景', 'unity_scene_save', {'path': sp})
    step('新建空场景', 'unity_scene_new')
    step('加载场景', 'unity_scene_load', {'path': sp})
    r = call('unity_gameobject_list')
    restored = 'AI_Cube' in r['text']
    steps.append({'label': '存档往返后物体恢复', 'tool': 'unity_gameobject_list', 'ok': restored, 'ms': 0, 'text': r['text'][:200]})
    print(('PASS' if restored else 'FAIL'), '存档往返后物体恢复')

    # ---------- 8) 诊断 ----------
    step('引擎指标', 'diag_get_engine_metrics')
    step('控制台日志', 'diag_get_console_logs')
    step('检查物体', 'diag_inspect_gameobject', {'name_or_id': 'AI_Cube'}, need='AI_Cube')

    # ---------- 9) 收尾 ----------
    step('退出编辑器(丢弃)', 'loom_eai_call', {'cmd': 'quit', 'args': {'save': 'discard'}})
finally:
    try:
        if mcp: mcp.terminate()
    except Exception: pass
    time.sleep(0.5)
    try:
        if ed: ed.terminate()
    except Exception: pass
    try:
        if ed:
            ed.wait(timeout=10)
    except Exception:
        try: ed.kill()
        except Exception: pass

total = len(steps); okn = sum(1 for s in steps if s['ok'])
print('\n' + '=' * 70)
print('MCP 全功能验收: %d/%d 通过' % (okn, total))
fails = [s for s in steps if not s['ok']]
for s in fails:
    print('  FAIL', s['label'], '|', s['tool'], '|', s['text'][:160].replace('\n', ' '))
out = os.path.join(LOOM, '..', 'docs', 'audit', 'e2e_mcp_report.json')
json.dump({'total': total, 'passed': okn, 'steps': steps}, open(out, 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('报告:', os.path.abspath(out))
sys.exit(0 if okn == total else 1)
