# -*- coding: utf-8 -*-
"""
test_agent_commands.py — Engine Agent 接口 EAI 测试 (2026-08-27, 全无头).
覆盖: 命令注册/派发 (未知命令/异常隔离) / 高频命令语义 (对象增删改查/播放/
光源摄像机/撤销) / 日志环 log_since / AgentService: 端口文件+令牌+submit→
drain 往返 / HTTP 端到端 (POST /cmd 鉴权 401/200, GET /logs/).
无头 (免 Qt/pygame 窗口); 用 FakeWin/FakeEditor 桩验证命令契约.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))   # ui/ 上级

import agent_commands as ac

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


class FakeObj:
    def __init__(self, name):
        self.name = name
        self.pos = (0, 0, 0)


class FakeEditor:
    def __init__(self):
        self.models = [FakeObj('立方体')]
        self.lights = [FakeObj('平行光')]
        self.cameras = [FakeObj('摄像机')]
        self.playing = False
        self.scene_name = '场景1'
        self.gizmo_mode = 'translate'
        self.calls = []
        self.camera_target = (0.0, 0.0, 0.0)
        self.camera_distance = 10.0
        self.camera_yaw = 0.6
        self.camera_pitch = -0.35
        self.selected_index = 0
        self.selected_light_index = -1
        self.selected_camera_index = -1
        self.active_camera = None
        self._scene_path = None
        self._dirty = False

    def _selected(self):
        if 0 <= self.selected_index < len(self.models):
            return self.models[self.selected_index]
        return None

    def _selected_light(self):
        return None

    def _selected_camera(self):
        return None

    def _select_model(self, i):
        self.selected_index = i
        self.calls.append(('select_model', i))

    def _add_primitive(self, typ):
        self.models.append(FakeObj(typ))
        self.calls.append(('prim', typ))

    def _add_light(self, kind):
        self.lights.append(FakeObj('光_' + str(kind)))
        self.calls.append(('light', kind))

    def _add_camera(self):
        self.cameras.append(FakeObj('相机_2'))
        self.calls.append(('camera',))

    def rename(self, m, new, old):
        m.name = new
        self.calls.append(('rename', old, new))

    def rename_light(self, l, new, old):
        l.name = new

    def rename_camera(self, c, new, old):
        c.name = new

    def delete_object(self):
        self.calls.append(('delete',))

    def duplicate_object(self):
        self.calls.append(('dup',))

    def add_script(self, obj, sid):
        self.calls.append(('script', obj.name, sid))

    def _undo_action(self):
        self.calls.append(('undo',))

    def _redo_action(self):
        self.calls.append(('redo',))

    def new_scene_cmd(self):
        self.calls.append(('new',))

    def save_scene(self):
        self.calls.append(('save',))
        return True

    def save_scene_as(self, path):
        self.calls.append(('save_as', path))

    def _save_scene(self, path=None):
        self.calls.append(('_save_scene', path))
        return path

    def scene_is_dirty(self):
        return self._dirty

    def load_scene_cmd(self, path=None):
        self.calls.append(('load', path))

    def set_gizmo_mode(self, mode):
        self.gizmo_mode = mode

    def toggle_play(self):
        self.playing = not self.playing

    def set_active_camera(self, cam):
        self.active_camera = cam
        self.calls.append(('active_cam', getattr(cam, 'name', None)))


class FakeWin:
    def __init__(self):
        self.editor = FakeEditor()
        self.viewport = None
        self.closed = False

    def close(self):
        self.closed = True


_events = []


def _t_run():
    pass


# ============ 1. 命令注册表与派发 ============
def t_commands_registry():
    names = ac.command_names()
    check("注册表含核心命令", all(k in names for k in (
        'status', 'object_add', 'object_select', 'object_rename', 'undo',
        'redo', 'play', 'light_add', 'camera_add', 'camera_active',
        'screenshot', 'quit')), sorted(names))
    r = ac.dispatch('不存在的命令', {}, FakeWin())
    check("未知命令 -> ok=False 含'未知命令'", not r['ok']
          and '未知命令' in r['error'], r)


# ============ 2. 高频命令语义 ============
def t_command_semantics():
    win = FakeWin()
    ed = win.editor
    r = ac.dispatch('object_add', {'type': 'sphere'}, win)
    check("object_add sphere -> ok + 模型数+1",
          r['ok'] and len(ed.models) == 2 and ed.calls[-1] == ('prim', 'sphere'))
    r = ac.dispatch('object_select', {'name': 'sphere'}, win)
    check("object_select 名字选中", r['ok'] and r['result']['selected'] == 'sphere'
          and ed.selected_index == 1)
    r = ac.dispatch('object_rename', {'name': 'sphere', 'new': '球'}, win)
    check("object_rename", r['ok'] and ed.models[1].name == '球')
    r = ac.dispatch('undo', {}, win)
    check("undo", r['ok'] and ed.calls[-1] == ('undo',))
    r = ac.dispatch('play', {}, win)
    check("play 切换", r['ok'] and r['result']['playing'] is True)
    r = ac.dispatch('play', {'on': False}, win)
    check("play 指定关", r['ok'] and r['result']['playing'] is False)
    r = ac.dispatch('light_add', {'kind': 'point'}, win)
    check("light_add point", r['ok'] and ed.calls[-1] == ('light', 'point'))
    r = ac.dispatch('camera_add', {}, win)
    check("camera_add", r['ok'] and len(ed.cameras) == 2)
    r = ac.dispatch('camera_active', {'name': '摄像机'}, win)
    check("camera_active 设", r['ok'] and ed.active_camera.name == '摄像机')
    r = ac.dispatch('script_add', {'sid': 'first_person'}, win)
    check("script_add 挂到选中", r['ok']
          and ed.calls[-1] == ('script', '球', 'first_person'))
    r = ac.dispatch('gizmo', {'mode': 'rotate'}, win)
    check("gizmo rotate", r['ok'] and ed.gizmo_mode == 'rotate')
    # 2026-08-28 契约加固: 无 path 且无 _scene_path -> 拒绝 (save_scene() 会弹
    # 系统另存为框 = Agent/无头环境卡死), 只有已有关联文件才允许裸保存
    r = ac.dispatch('scene_save', {}, win)
    check("scene_save 无场景文件 -> 拒绝并提示 path=",
          not r['ok'] and 'path=' in r['error'], r)
    ed._scene_path = 'D:\\a\\b.json'
    r = ac.dispatch('scene_save', {}, win)
    check("scene_save 有 _scene_path -> 走 save_scene()", r['ok']
          and ed.calls[-1] == ('save',))
    r = ac.dispatch('status', {}, win)
    check("status 摘要 (物数/名)", r['ok']
          and len(r['result']['models']) == 2 and '球' in r['result']['models'],
          r['result'])


# ============ 3. 异常隔离 ============
def t_command_error_isolated():
    win = FakeWin()
    win.editor.rename = None      # 制造 AttributeError
    r = ac.dispatch('object_rename', {'name': '立方体', 'new': 'x'}, win)
    check("命令异常 -> ok=False + 记录日志不崩", not r['ok']
          and "'NoneType'" in r['error'], r)


# ============ 4. 日志环 ============
def t_log_ring():
    ac.log("测试行一")
    n = ac.log("测试行二")
    got = ac.log_since(n - 1)     # 只返回 > n-1 的行 = 仅 测试行二
    check("log_since(after=最后-1) 增量只含新行", len(got) == 1
          and got[0][2] == '测试行二', got)
    got2 = ac.log_since(0)
    check("log_since(0) 含两行", any(t == '测试行一' for _, _, t in got2)
          and any(t == '测试行二' for _, _, t in got2))


# ============ 4b. 播放器层插件命令化 (register_editor_button 复用) ============
def t_plugin_buttons():
    win = FakeWin()
    r = ac.dispatch('plugins', {}, win)
    check("plugins 命令返回清单结构",
          r['ok'] and 'plugins' in r['result'] and 'buttons' in r['result'], r['result'])
    # 模拟插件注册按钮 (与 plugin_loader.register_editor_button 同语义)
    import plugin_loader
    got = []
    plugin_loader._EDITOR_BUTTONS.append(('给球加力', lambda: got.append('kick'),
                                          'com.example.hi'))
    r = ac.dispatch('plugin_button', {'plugin': 'com.example.hi',
                                      'text': '给球加力'}, win)
    check("plugin_button 调用回调 (与 GUI 点击等价)",
          r['ok'] and r['result']['plugin'] == 'com.example.hi' and got == ['kick'], r)
    # 异常隔离 / 找不到: 2026-08-28 契约统一后都返回外层 ok=False + error
    plugin_loader._EDITOR_BUTTONS.append(('坏按钮', lambda: 1 / 0, 'com.example.bad'))
    r = ac.dispatch('plugin_button', {'text': '坏按钮'}, win)
    check("plugin_button 异常返回结果不崩", not r['ok'] and '插件按钮失败' in r['error'], r)
    r = ac.dispatch('plugin_button', {'text': '不存在'}, win)
    check("plugin_button 找不到提示可用清单", not r['ok'] and '找不到' in r['error'])
    plugin_loader._EDITOR_BUTTONS[:] = []


# ============ 4c. 2026-08-28 新语义: quit 三态 / 布尔归一 / object_list ============
def t_new_semantics():
    win = FakeWin()
    ed = win.editor

    # as_bool: 控制台/HTTP 给的全是字符串, 裸 bool('false')==True
    check("as_bool('false')/('0')/('no')/('off') 判假", not any(
        ac.as_bool(v) for v in ('false', '0', 'no', 'off', '')))
    check("as_bool('true')/('True')/1 判真",
          ac.as_bool('true') and ac.as_bool('True') and ac.as_bool(1))

    # play on='false' 必须停止 (曾把字符串当真值 -> 反而开始播放)
    ed.playing = True
    r = ac.dispatch('play', {'on': 'false'}, win)
    check("play on='false' 停止 (字符串判假)", r['ok'] and ed.playing is False, r)

    # object_list 带序号 (重名时 Agent 用 index= 指定)
    r = ac.dispatch('object_list', {}, win)
    check("object_list 三清单且带 index",
          r['ok'] and r['result']['models'][0]['index'] == 0
          and 'lights' in r['result'] and 'cameras' in r['result'])

    # quit 三态: 脏场景无 save= -> 命令层决断 (无 _scene_path -> 丢弃直接关,
    # 绝不弹模态框); cancel 中止; discard 关闭; 干净场景直接退
    ed._dirty = True
    ed._scene_path = None
    r = ac.dispatch('quit', {'after': 0}, win)
    check("quit 脏场景无 save= 及无文件 -> 丢弃决断并关窗 (无弹框)", r['ok']
          and r['result']['quitting'] and r['result']['resolved'] == 'discard'
          and win.closed is True, r)
    win.closed = False
    r = ac.dispatch('quit', {'after': 0, 'save': 'cancel'}, win)
    check("quit save=cancel 中止退出", r['ok']
          and r['result']['cancelled'] and win.closed is False)
    r = ac.dispatch('quit', {'after': 0, 'save': 'discard'}, win)
    check("quit save=discard 丢弃并关窗", r['ok']
          and r['result']['quitting'] and win.closed is True)
    # 有 _scene_path 时无 save= -> 走 save_scene() 决断
    ed._scene_path = 'D:\\a\\b.json'
    win.closed = False
    ed._dirty = True
    r = ac.dispatch('quit', {'after': 0}, win)
    check("quit 脏场景带文件无 save= -> 保存决断再关窗", r['ok']
          and r['result']['resolved'] == 'save' and win.closed is True
          and ed.calls[-1] == ('save',), r)
    # 干净场景: 无 save= 也直接退 (不该拿脏手续烦 Agent)
    ed._dirty = False
    win.closed = False
    r = ac.dispatch('quit', {'after': 0}, win)
    check("quit 干净场景直接退", r['ok'] and win.closed is True)


# ============ 4d. 写路径白名单 (2026-08-28 二轮, 高危3 辐射) ============
def t_write_whitelist():
    win = FakeWin()
    win.editor._scene_path = None
    # 越权: 不在 程序目录/用户目录/系统临时 的路径 -> 拒绝且 ok=False
    for vid, path in (('不存在的盘', r'C:\Windows\Temp\evil.json'),
                      ('项目根(非用户目录)', r'D:\my-project\_attack_range_普通插件释毒实验\route_pwned\evil.json')):
        r = ac.dispatch('scene_save', {'path': path}, win)
        check("scene_save 越权 %s -> 拒绝 (白名单外)" % vid,
              not r['ok'] and '越域' in r['error'], r)
    r = ac.dispatch('asset_save', {'what': 'material',
                                   'path': r'C:\Windows\Temp\evil.json'}, win)
    check("asset_save 越权 -> 拒绝", not r['ok'] and '越域' in r['error'], r)
    r = ac.dispatch('prefab_save', {'path': r'C:\Windows\Temp\evil.json'}, win)
    check("prefab_save 越权 -> 拒绝", not r['ok'] and '越域' in r['error'], r)
    r = ac.dispatch('screenshot', {'file': r'C:\Windows\Temp\evil.png'}, win)
    check("screenshot 越权 -> 拒绝", not r['ok'] and '越域' in r['error'], r)
    # 白名单内 (系统临时) -> 放行
    import tempfile
    okpath = os.path.join(tempfile.gettempdir(), 'ac_whitelist_ok.json')
    ok, full = ac._safe_write_path(okpath, 'test', win)
    check("白名单内路径放行 (系统临时)", ok is True and full == os.path.abspath(okpath))
    ok2, _ = ac._safe_write_path(r'C:\Windows\Temp\evil.json', 'test', win)
    check("越权路径不放行", ok2 is False)
    # 路径是白名单根本身 -> 拒绝 (目录不是文件)
    ok3, r3 = ac._safe_write_path(os.path.expanduser('~'), 'test', win)
    check("白名单根自身 -> 拒绝 (目录不是文件)", ok3 is False)
    # 场景目录维度: 有 _scene_path 时其所在目录也在白名单内
    win.editor._scene_path = r'D:\weird\scenes\a.json'
    ok4, _ = ac._safe_write_path(r'D:\weird\scenes\b.json', 'test', win)
    check("场景目录维度放行 (另一场景文件同目录)", ok4 is True)


# ============ 5. AgentService: 端口文件 + submit/drain + HTTP 端到端 ============
def t_service_http():
    with tempfile.TemporaryDirectory() as tmp:
        win = FakeWin()
        svc = ac.AgentService(win, base=tmp)
        port = svc.start()
        pf = ac.load_agent_info(tmp)
        check("端口文件写入 + 可读回", pf and pf['port'] == port
              and pf['token'] == svc.token and pf['url'].endswith(str(port)), pf)
        # ---- HTTP /cmd (无 token = 401) ----
        def post(cmd, args, token):
            req = urllib.request.Request(
                'http://127.0.0.1:%d/cmd' % port,
                data=json.dumps({'cmd': cmd, 'args': args}).encode('utf-8'),
                headers={'Content-Type': 'application/json',
                         'X-Agent-Token': token})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode('utf-8'))
        code, body = post('status', {}, 'wrong')
        check("HTTP 鉴权: 错 token -> 401", code == 401, (code, body))
        # submit 是同步等待主线程 drain 的: 投递线程 + 主线程 drain 模拟
        res = {}
        def _th_post():
            res['r'] = post('object_add', {'type': 'plane'}, svc.token)
        th = threading.Thread(target=_th_post)
        th.start()
        time.sleep(0.3)
        svc.drain()          # 模拟 Qt 主线程轮询 (命令真正执行点)
        th.join(10)
        check("HTTP POST /cmd 200 且主线程执行", th.is_alive() is False
              and res['r'][0] == 200 and res['r'][1]['ok'], res)
        check("drain 后命令已执行", len(win.editor.models) == 2
              and win.editor.models[1].name == 'plane')
        check("命令执行已记日志", any('object_add' in t for _, _, t in ac.LOG_RING))
        # ---- GET /logs ----
        req = urllib.request.Request(
            'http://127.0.0.1:%d/logs?after=%d' % (port, 0),
            headers={'X-Agent-Token': svc.token})
        with urllib.request.urlopen(req, timeout=10) as r:
            ldata = json.loads(r.read().decode('utf-8'))
        check("GET /logs 返回行", ldata['ok'] and len(ldata['lines']) > 0
              and any('object_add' in t for _, _, t in ldata['lines']), ldata['lines'][-2:])
        svc.stop()
        check("stop 后端口文件删除", ac.load_agent_info(tmp) is None)
        check("stop 幂等不崩", (svc.stop() or True))


if __name__ == "__main__":
    print("========== Engine Agent 接口 (EAI) 测试 ==========")
    t_commands_registry()
    t_command_semantics()
    t_command_error_isolated()
    t_log_ring()
    t_plugin_buttons()
    t_new_semantics()
    t_write_whitelist()
    t_service_http()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
    print("全部通过")
