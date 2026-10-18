# -*- coding: utf-8 -*-
"""
agent_commands.py — Engine Agent 接口 EAI (2026-08-27)
====================================================================
让 Agent (Claude Code) 像开发人员一样操作编辑器 / 开发游戏 / 做功能
检查, 同时为 GUI 提供命令化控制台。核心 = 一层"命令执行器", 一个实现
三处使用:

  工具栏按钮 / 检查器控件  ─┐
  GUI 控制台 输入框         ─┼→ 命令执行器 (单一事实) → editor/窗口方法
  HTTP 127.0.0.1:端口      ─┘   (Agent 远程驱动, 与 GUI 操作同一条命令)

协议 (启动 --agent 时):
  端口/令牌: <程序目录>/.agent_port.json = {"port": 0, "token": "...",
              "pid": ..., "url": "http://127.0.0.1:<port>"}
  POST /cmd   {"cmd": "play", "args": {...}}  -> {"ok":true, "result":...}
      | 失败 {"ok":false, "error": "..."}; 令牌: 请求头 X-Agent-Token.
  GET  /logs?after=N  全量日志流 (自 N 之后的新行), {"seq":N, "lines":[...]}
  GET  /status        引擎状态摘要 (在线帧率/场景/选中摘要)
  命令全部在 Qt 主线程执行 (与 UI 一致, 无跨线程危险): HTTP 线程收命令
  -> 入队 -> QTimer 轮询 -> 主线程执行 -> 回填结果.

命令与 GUI 同义: GUI 里每个操作背后是一条命令方法 (qt_view._cmd_*),
这里映射同名命令, Agent 与用户的操作完全等价。新增 GUI 操作时把命令
也注册进 COMMANDS (命令表=GUI 功能清单, 台账见《未测试功能测试方向
指南.txt》2026-08-27 条)。

日志: LOG_RING 环形缓冲 (默认 2000 行) + seq; 命令执行/按钮点击/
错误都会记录, Agent 与 GUI 控制台共用 (调试日志加速 BUG 排查)。

用法: Loom.py 编辑器入口见 "--agent"; 无头测试直接调 COMMANDS/dispatch.
"""
import json
import os
import queue
import secrets
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_RING = deque(maxlen=2000)
_LOG_SEQ = 0
_LOG_LOCK = threading.Lock()

_COMMANDS = {}           # 命令名 -> fn(win, args) -> dict/值
_CMDS_DESC = {}          # 命令名 -> 用途说明 (GUI 控制台提示)


def log(msg):
    """统一调试日志环 (命令/错误/事件; GUI 控制台与 Agent /logs 共用)."""
    global _LOG_SEQ
    with _LOG_LOCK:
        _LOG_SEQ += 1
        seq = _LOG_SEQ
        LOG_RING.append((seq, time.strftime('%H:%M:%S'), str(msg)))
    return seq


def log_since(after):
    """since seq 之后的日志行 [(seq, time, text)...]."""
    with _LOG_LOCK:
        return [r for r in LOG_RING if r[0] > after]


def last_log_seq():
    """当前日志序号 (GUI 控制台挂载时取基线, 之后只拉增量; 远程用 /logs?after)."""
    with _LOG_LOCK:
        return _LOG_SEQ


# ---- 写路径白名单 (2026-08-28 二轮, 高危3: Agent 语句直达任意目录释放文件) ----
def _write_roots(win=None):
    """写路径白名单根: 程序目录 / 当前场景目录 / 用户目录.
    Agent (含提示词注入) 发出的写文件命令只能落这些根之下."""
    import guiloader
    roots = []
    try:
        roots.append(os.path.abspath(guiloader.program_dir()))
    except Exception:
        roots.append(os.path.abspath(
            os.path.dirname(os.path.abspath(sys.argv[0]))))
    try:
        ed = getattr(win, 'editor', None)
        sp = getattr(ed, '_scene_path', None)
        if sp:
            roots.append(os.path.abspath(os.path.dirname(sp)))
    except Exception:
        pass
    roots.append(os.path.expanduser('~'))
    # 系统临时目录: 写临时文件/测试场地是合法场景; 它不在病毒投放价值区
    # (Startup/桌面/文档才是), 且 exe 与脚本常走 Temp
    try:
        import tempfile
        roots.append(os.path.normpath(tempfile.gettempdir()))
    except Exception:
        pass
    # 去重保序
    out, seen = [], set()
    for r in roots:
        r = r.rstrip('\\/')
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _safe_write_path(path, purpose='写文件', win=None):
    """校验写路径在白名单内; 返回 (True, 规范化路径) 或 (False, 错误串).
    判定: 绝对路径化 + 无 .. 逃逸; 必须以某个白名单根为前缀, 且不是根
    本身 (根=目录, 防止把目录当文件写废)."""
    if not path or not isinstance(path, str):
        return False, '需要非空 path'
    full = os.path.abspath(os.path.normpath(path))
    for r in _write_roots(win):
        if full == r:
            return False, '路径是目录, 不是文件: %s' % full
        if full.startswith(r + os.sep) or full.startswith(r + '/'):
            return True, full
    return False, ('%s 越域: %s (白名单: 程序目录/场景目录/用户目录; '
                   '请改用白名单内路径)' % (purpose, full))


# 命令参数一律可能是字符串 (GUI 控制台输入 "on=false" / HTTP JSON 里写
# "false"), 裸 bool('false') == True —— 曾让 `play on=false` 反而开始播放.
_FALSE_WORDS = {'', '0', 'false', 'no', 'off', 'none', '否'}


def as_bool(v, default=False):
    """命令参数布尔化 (字符串 'false'/'0'/'no'/'off' 判假). 命令层统一入口."""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() not in _FALSE_WORDS


def as_float(v, default=0.0):
    """命令参数数值化 (控制台字符串/JSON 数字通吃; 非法值回默认)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def vec_set(obj, field, axis, v):
    """namedtuple 向量单轴写入: 重建整个元组, 只改 axis 分量 (其余不动).
    2026-08-22 修复记录: Point3D 是 namedtuple —— 对实例 setattr 无效 (会静默
    建错误属性); 整体重建 type(cur)(nv,nv,nv) 会把三个轴全写成一个值 (用户实测
    "拖 X 坐标 XYZ 被同时改"). 物体/光源/相机位置, 检查器数值行与 set_transform
    等命令**共用本函数** (qt_view._vec_set 即本函数别名, 单一事实)."""
    cur = getattr(obj, field)
    idx = 'XYZ'.index(str(axis).upper())
    setattr(obj, field, type(cur)(*(v if i == idx else c
                                    for i, c in enumerate(cur))))


def command(name, desc=""):
    """命令注册装饰器: @command('play', '播放/停止播放')"""
    def deco(fn):
        _COMMANDS[name] = fn
        _CMDS_DESC[name] = desc
        return fn
    return deco


def command_names():
    return {k: _CMDS_DESC.get(k, '') for k in _COMMANDS}


def dispatch(cmd, args, win):
    """执行一条命令 (win=LoomGUI 或桩). 返回 {"ok":..., "result"/"error"}.
    命令报错不会崩编辑器: 记录日志并返回错误."""
    fn = _COMMANDS.get(cmd)
    if fn is None:
        return {'ok': False, 'error': '未知命令: %s (可用: %s)'
                % (cmd, ' '.join(sorted(_COMMANDS)))}
    try:
        t0 = time.perf_counter()
        result = fn(win, args or {})
        ms = (time.perf_counter() - t0) * 1000
        # 契约统一 (2026-08-27): 命令用 {'error': ...} 表达"参数/前置条件不对"
        # 时, 外层也必须 ok=False —— 否则 Agent 看到 ok=true 就当成功了,
        # 错误藏在 result 里没人看 (远程 HTTP 与 GUI 控制台同此语义).
        if isinstance(result, dict) and result.get('error'):
            log('[命令] %s %s -> 拒绝: %s' % (cmd, args or '', result['error']))
            return {'ok': False, 'error': result['error'], 'result': result}
        log('[命令] %s %s -> ok (%.1fms)' % (cmd, args or '', ms))
        return {'ok': True, 'result': result}
    except _Ambiguous as e:
        # 重名歧义 = 输入问题, 不是崩溃: 拒绝但给出 index= 提示
        log('[命令] %s %s -> 重名歧义: %s' % (cmd, args or '', e))
        return {'ok': False, 'error': str(e)}
    except Exception as e:
        log('[命令] %s 失败: %r' % (cmd, e))
        return {'ok': False, 'error': repr(e)}


# ====================================================================
# 系统/视图
# ====================================================================
@command('quit', '退出编辑器: {save?=save|discard|cancel, after?} '
                  '({save} 只给 Agent 自动退出用; 你手敲 quit 就行)')
def cmd_quit(win, args):
    """延时关闭 (先把 HTTP 响应发回 Agent 再关窗口).
    2026-08-28 修复 (用户报告): 没保存直接关引擎会弹"是否保存"对话框 ——
    GUI 里那是保护, 但**远程 Agent** 下弹的是模态框: 窗口卡死在 ask() 上,
    命令永远等不到结果. 故 Agent 链路把三态决策显式化 (同一《A01 三态》契约):
      save=save     -> 先保存 (有路径直接存; 无路径报错退出中止)
      save=discard  -> 丢弃改动直接关 (跳过询问)
      save=cancel   -> 中止退出 (返回 ok, 不关窗口)
    不传 save 且场景脏 (= 人在编辑器里手敲 quit, 或浏览器试): 按 GUI 语义
    正常关窗口, 让 closeEvent 弹三态框给你选 —— 只有人有空去选才该弹框;
    Agent 不想弹框就明确给 save= (先 status 看 dirty 决策)."""
    ed = getattr(win, 'editor', None)
    dirty = False
    if ed is not None and hasattr(ed, 'scene_is_dirty'):
        try:
            dirty = bool(ed.scene_is_dirty())
        except Exception:
            dirty = False
    resolve = 'none'        # dirty 决断: 'save' | 'discard' | 'cancel'
    if dirty:
        choice = (args.get('save') or '').strip().lower()
        if choice == 'cancel':
            return {'quitting': False, 'dirty': True, 'cancelled': True}
        if choice == 'discard':
            resolve = 'discard'
        elif choice == 'save':
            path = args.get('path')
            if path:
                ok, full = _safe_write_path(path, 'quit save', win)
                if not ok:
                    return {'error': full}
                path = full
                if not ed._save_scene(path):
                    return {'error': '保存失败: %s (退出已中止)' % path}
            elif getattr(ed, '_scene_path', None):
                ed.save_scene()
            else:
                return {'error': '未保存改动且无场景文件: 传 save=discard 丢弃, '
                                 '或 path= 指定保存位置 (退出已中止)'}
            resolve = 'save'
        else:
            # 缺省= GUI 弹框默认项语义: 有对应文件先保存, 没文件只能丢弃
            # (命令行绝不弹模态框 —— 模态框会卡死命令链, 用户实测指出的问题)
            if getattr(ed, '_scene_path', None):
                ed.save_scene()
                resolve = 'save'
            else:
                resolve = 'discard'
    delay = as_float(args.get('after', 0.15), 0.15)
    # dirty 已由命令层决断 (save/discard): 关窗前先给窗口挂"跳过弹框"标记,
    # closeEvent 照此跳过 _confirm_unsaved —— 否则 win.close() 会在 closeEvent
    # 里弹"是否保存"模态框**再次**卡死整个链 (用户 2026-08-28 实测直接指出).
    try:
        if dirty:
            win._suppress_confirm = True      # qt_view.closeEvent 认这个标记
    except Exception:
        pass
    delay = as_float(args.get('after', 0.15), 0.15)
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            QTimer.singleShot(int(delay * 1000), win.close)
            return {'quitting': True, 'after': delay, 'dirty': dirty,
                    'resolved': resolve}
    except Exception:
        pass
    win.close()
    return {'quitting': True, 'after': 0, 'immediate': True, 'dirty': dirty,
            'resolved': resolve}


@command('status', '引擎状态摘要 (物体/光源/相机/选中/相机参数/帧率)')
def cmd_status(win, args):
    import math
    ed = win.editor
    sel = ed._selected() or ed._selected_light() or ed._selected_camera()
    fps = getattr(getattr(win, 'viewport', None), '_fps', None) or \
          getattr(win, '_fps', None)
    return {
        'scene': getattr(ed, 'scene_name', getattr(ed, 'name', None)),
        'models': [m.name for m in ed.models],
        'lights': [l.name for l in ed.lights],
        'cameras': [c.name for c in ed.cameras],
        'selected': getattr(sel, 'name', None),
        'playing': bool(getattr(ed, 'is_playing',
                                getattr(ed, 'playing', False))),
        # 未保存改动 (quit 前置检查; 2026-08-28): Agent 先 status 看到 dirty,
        # 退出时才不会撞上"是否保存"模态框
        'dirty': bool(ed.scene_is_dirty()) if hasattr(ed, 'scene_is_dirty') else False,
        'fps': fps,
        'camera': {'target': list(ed.camera_target),
                   'distance': ed.camera_distance,
                   'yaw_deg': round(math.degrees(ed.camera_yaw), 1),
                   'pitch_deg': round(math.degrees(ed.camera_pitch), 1)},
    }


@command('screenshot', '视口截图存 PNG, save 返回文件路径 (白名单外拒绝; '
                       'full=true 抓整窗含工具栏/状态栏 FPS|TPS)')
def cmd_screenshot(win, args):
    import uuid
    out = args.get('file')
    if not out:
        out = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                           '保存', 'shot_%s.png' % uuid.uuid4().hex[:8])
    else:
        ok, full = _safe_write_path(out, 'screenshot', win)
        if not ok:
            return {'error': full}
        out = full
    if args.get('full'):
        img = win.grab().toImage()       # 整窗 (含状态栏 FPS|TPS 读数)
    else:
        img = win.viewport.grab().toImage()
    if not img.save(out):
        return {'error': '截图保存失败: %s' % out}
    return {'file': out, 'size': [img.width(), img.height()]}


# ====================================================================
# 场景
# ====================================================================
@command('scene_new', '新建场景 (Agent/控制台语义: 直接重置, 不弹"是否保存"对话框)')
def cmd_scene_new(win, args):
    ed = win.editor
    ed._new_scene()
    return {'ok': True, 'scene': getattr(ed, 'scene_name', None),
            'models': [m.name for m in ed.models]}


@command('scene_save', '保存场景: {path} 存到指定文件; 无 path = 存回当前文件')
def cmd_scene_save(win, args):
    """save_scene_as() 是**无参**的 (它总是弹系统另存为对话框, Agent 环境会
    卡死); 带路径保存必须走低层 _save_scene(path) —— 与 _load_scene(path)
    对称 (2026-08-27 修: 原来传参给 save_scene_as 直接 TypeError)."""
    ed = win.editor
    path = args.get('path')
    if path:
        # 2026-08-28 二轮(高危3): 写路径白名单 —— 任意路径释放 = Agent 语
        # 句可达的病毒落点; 白名单外明确拒绝 (目录/场景/用户三根)
        ok, full = _safe_write_path(path, 'scene_save', win)
        if not ok:
            return {'error': full}
        out = ed._save_scene(full)
        if not out:
            return {'error': '保存失败 (播放中不能保存, 或路径不可写): %s' % full}
        return {'saved': out}
    if not getattr(ed, '_scene_path', None):
        return {'error': '当前场景还没有对应文件: 请传 path=完整路径 '
                         '(无 path 会弹系统另存为对话框, Agent 环境禁用)'}
    ok = ed.save_scene()
    return {'saved': ed._scene_path} if ok else {'error': '保存失败'}


@command('scene_load', '加载场景: {path} 直接换场 (无确认, 当前改动丢弃=恢复磁盘版本)')
def cmd_scene_load(win, args):
    ed = win.editor
    path = args.get('path')
    if not path:
        return {'error': 'scene_load 需要 path (丢丢弃恢复=传磁盘上已保存的场景路径;'
                        ' 无 path 会弹系统对话框, Agent 环境禁用)'}
    ed._load_scene(path)   # 低层: 直载不弹框不确认 (丢弃当前改动语义)
    return {'loaded': path}


# ====================================================================
# 物体
# ====================================================================
@command('object_add', '添加基元: cube|sphere|plane')
def cmd_object_add(win, args):
    typ = args.get('type', 'cube')
    win.editor._add_primitive(typ)
    return {'type': typ}


def _find_all(ed, name):
    """按名字找出**全部**同名目标 [(kind, obj, index)...].
    场景里重名是允许的 (复制/Prefab 实例常见), 命令层必须知道有没有歧义."""
    hits = []
    for kind, seq in (('model', ed.models), ('light', ed.lights),
                      ('camera', ed.cameras)):
        for i, o in enumerate(seq):
            if o.name == name:
                hits.append((kind, o, i))
    return hits


def _find(ed, name):
    """按名字找单个目标, 返回 (kind, obj, index); 找不到 (None, None, -1).
    重名时返回第一个 —— 需要区分歧义的调用点用 _find_all/_resolve."""
    hits = _find_all(ed, name)
    return hits[0] if hits else (None, None, -1)


@command('object_list', '场内全部物体/光源/相机 (带序号, 重名时用 index= 指定)')
def cmd_object_list(win, args):
    ed = win.editor
    sel = getattr(ed._selected(), 'name', None) if ed._selected() else None
    return {
        'models': [{'index': i, 'name': m.name, 'parent':
                    getattr(getattr(m, 'parent', None), 'name', None)}
                   for i, m in enumerate(ed.models)],
        'lights': [{'index': i, 'name': l.name, 'kind_of': getattr(l, 'kind', None)}
                   for i, l in enumerate(ed.lights)],
        'cameras': [{'index': i, 'name': c.name} for i, c in enumerate(ed.cameras)],
        'selected': sel,
    }


@command('object_select', '选中 {name?/index?} (物体名/光源名/相机名; 重名加 index=)')
def cmd_object_select(win, args):
    ed = win.editor
    name = args.get('name')
    if name is None:
        idx = int(as_float(args.get('index', 0), 0))
        if not 0 <= idx < len(ed.models):
            return {'error': 'index 越界: %d (物体数 %d)' % (idx, len(ed.models))}
        ed._select_model(idx)
        return {'selected': getattr(ed._selected(), 'name', None)}
    hits = _find_all(ed, name)
    if not hits:
        return {'error': '找不到: %s (先 object_list 看全部)' % name}
    if len(hits) > 1 and args.get('index') is not None:
        want = int(as_float(args['index'], -1))
        hits = [h for h in hits if h[2] == want] or hits
    kind, obj, i = hits[0]
    if kind == 'model':
        ed._select_model(i)
    elif kind == 'light':
        ed.selected_light_index = i
        ed.selected_index = ed.selected_camera_index = -1
    else:
        ed.selected_camera_index = i
        ed.selected_index = ed.selected_light_index = -1
    return {'selected': obj.name, 'kind': kind, 'index': i,
            'ambiguous': len(_find_all(ed, name)) > 1}


@command('object_rename', '改名: {name, new}')
def cmd_object_rename(win, args):
    ed = win.editor
    kind, obj, i = _find(ed, args.get('name'))
    if obj is None:
        return {'error': '找不到: %s' % args.get('name')}
    new = args.get('new')
    if kind == 'model':
        ed.rename(obj, new, obj.name)
    elif kind == 'light':
        ed.rename_light(obj, new, obj.name)
    else:
        ed.rename_camera(obj, new, obj.name)
    return {'renamed': [args.get('name'), new]}


@command('object_delete', '删除当前选中')
def cmd_object_delete(win, args):
    win.editor.delete_object()
    return {'ok': True}


@command('object_duplicate', '复制当前选中')
def cmd_object_duplicate(win, args):
    win.editor.duplicate_object()
    return {'ok': True}


@command('script_add', '给目标挂脚本: {sid, target} (缺省当前选中)')
def cmd_script_add(win, args):
    ed = win.editor
    target = args.get('target')
    if target:
        kind, obj, i = _find(ed, target)
        if obj is None:
            return {'error': '找不到: %s' % target}
    else:
        obj = ed._selected() or ed._selected_light() or ed._selected_camera()
    if obj is None:
        return {'error': '没有选中物体'}
    ed.add_script(obj, args.get('sid'))
    return {'sid': args.get('sid'), 'target': getattr(obj, 'name', None)}


# ====================================================================
# 编辑 / 播放 / 视图
# ====================================================================
@command('undo', '撤销一步')
def cmd_undo(win, args):
    win.editor._undo_action()
    return {'ok': True}


@command('redo', '重做一步')
def cmd_redo(win, args):
    win.editor._redo_action()
    return {'ok': True}


@command('gizmo', 'gizmo 模式: translate|rotate')
def cmd_gizmo(win, args):
    win.editor.set_gizmo_mode(args.get('mode', 'translate'))
    return {'mode': args.get('mode', 'translate')}


@command('play', '开/关播放: 缺省 toggle, on=true|false 指定态; '
                 'paused=true 进入播放即冻结逻辑帧 (物理对拍用)')
def cmd_play(win, args):
    state = args.get('on')
    ed = win.editor
    cur = bool(getattr(ed, 'is_playing', getattr(ed, 'playing', False)))
    if state is not None:
        state = as_bool(state)      # 'false' 是字符串, 不能裸 bool()
    if state is not None and state == cur:
        if cur and as_bool(args.get('paused'), False):
            ed._logic_paused = True
        return {'playing': cur, 'nochange': True}
    ed.toggle_play()
    now = bool(getattr(ed, 'is_playing', getattr(ed, 'playing', False)))
    if now and as_bool(args.get('paused'), False):
        # 进入播放即冻结: 渲染帧照跑但零逻辑, 直到 physics_simulate 显式步进.
        # 与 toggle_play 同一主线程操作, 中间无渲染帧插入 → 从零时刻起确定.
        ed._logic_paused = True
    return {'playing': now,
            'paused': bool(getattr(ed, '_logic_paused', False))}


@command('light_add', '添加光源: dir|point')
def cmd_light_add(win, args):
    win.editor._add_light(args.get('kind', 'dir'))
    return {'kind': args.get('kind', 'dir')}


@command('camera_add', '添加摄像机')
def cmd_camera_add(win, args):
    win.editor._add_camera()
    return {'ok': True}


@command('camera_active', '设为激活相机: {name} (缺省=取消激活)')
def cmd_camera_active(win, args):
    ed = win.editor
    name = args.get('name')
    if not name:
        ed.set_active_camera(None)
        return {'active': None}
    kind, obj, i = _find(ed, name)
    if obj is None:
        return {'error': '找不到相机: %s' % name}
    ed.set_active_camera(obj)
    return {'active': name}


@command('camera_move', '开发者轨道相机移动: {x,y,z} 绝对目标 或 {dx,dy,dz} 增量, 可选 {distance}')
def cmd_camera_move(win, args):
    ed = win.editor
    if 'x' in args:
        ed.camera_target = (float(args['x']), float(args['y']), float(args['z']))
    elif 'dx' in args:
        t = ed.camera_target
        ed.camera_target = (t[0] + float(args['dx']),
                            t[1] + float(args['dy']),
                            t[2] + float(args['dz']))
    if 'distance' in args:
        ed.camera_distance = float(args['distance'])
    return {'target': list(ed.camera_target), 'distance': ed.camera_distance}


@command('camera_look', '开发者相机视角: {yaw,pitch}(度) 绝对 或 {dyaw,dpitch}(度) 增量')
def cmd_camera_look(win, args):
    import math
    ed = win.editor
    if 'yaw' in args:
        ed.camera_yaw = math.radians(float(args['yaw']))
    elif 'dyaw' in args:
        ed.camera_yaw += math.radians(float(args['dyaw']))
    if 'pitch' in args:
        ed.camera_pitch = max(-1.55, min(1.55, math.radians(float(args['pitch']))))
    elif 'dpitch' in args:
        ed.camera_pitch = max(-1.55, min(1.55,
                                         ed.camera_pitch + math.radians(float(args['dpitch']))))
    return {'yaw_deg': round(math.degrees(ed.camera_yaw), 1),
            'pitch_deg': round(math.degrees(ed.camera_pitch), 1)}


# ---- 视角/移动 命令 = 结果注入 (2026-08-27 用户定原则) ----
# 连贯性操作 (右键滑动视角/中键平移/长按/拖拽) 一律不进命令行:
#   GUI 走老链路 (editor 事件处理, 直接向引擎发连贯操作);
#   命令层只暴露"一次性结果注入" (camera_move 绝对目标 / camera_look
#   绝对角度); Agent 需要连续观察时 = 多次注入结果命令串联 (频率自控),
#   或 GUI 内手动/老链路。camera_drive 等"模拟连贯驱动"命令已拆除
#   (2026-08-27), 避免两套逻辑改同一状态字段造成 GUI 滑动异常.
# 滑杆/拖条类: 只提供 set_* 结果注入命令 (检查器拖块本身不命令化).


# ====================================================================
# 播放器层插件命令化 (2026-08-27 用户补充): 插件 register_editor_button
# 注册的按钮 = GUI「插件」菜单 + EAI 命令 两条通路, 同一回调闭包执行.
# editor 层插件 (纯开发工具) 不做命令化 (对游戏执行无影响).
# ====================================================================
@command('plugins', '插件与已注册按钮清单 (播放器层插件命令化入口)')
def cmd_plugins(win, args):
    import plugin_loader
    loaded = plugin_loader.get_loaded()
    btns = []
    for text, cb, pid in plugin_loader.editor_buttons():
        btns.append({'plugin': pid, 'text': text})
    return {'plugins': [{'id': i, 'layer': e['layer'],
                         'kind': e['kind']} for i, e in loaded.items()],
            'buttons': btns}


@command('plugin_button', '运行插件按钮: {plugin, text} (与 GUI 菜单点击等价)')
def cmd_plugin_button(win, args):
    import plugin_loader
    pid = args.get('plugin')
    text = args.get('text')
    for t, cb, p in plugin_loader.editor_buttons():
        if t == text and (pid is None or p == pid or pid == 'all'):
            try:
                import time as _t
                _t0 = _t.perf_counter()
                cb()
                return {'plugin': p, 'text': t,
                        'ms': round((_t.perf_counter() - _t0) * 1000, 1)}
            except Exception as e:
                return {'error': '插件按钮失败: %r' % e}
    return {'error': '找不到插件按钮: plugin=%s text=%s (可用: %s)'
            % (pid, text, [b['text'] for b in cmd_plugins(win, {})['buttons']])}


# ====================================================================
# 结果注入命令 (P2②, 2026-08-27) — 覆盖检查器 / 层级 / 资源 / Prefab 的
# GUI 操作面。约定 (用户拍板的"连贯操作双链原则"):
#   · 命令层只做"一次到位的结果注入" (set_*), 不模拟拖拽/长按等连贯操作;
#   · 每条命令调用**与 GUI 完全相同的 EditorApp 方法** (commit_model /
#     toggle_collider / reparent ...), 于是撤销栈、脏标记、组件语义天然一致;
#   · 一条命令 = 一步撤销 (commit_* 包整批字段), 对齐"改完松手压一次栈".
# ====================================================================
def _resolve(ed, args, kinds=('model', 'light', 'camera')):
    """目标解析: {name} 缺省 = 当前选中. 返回 (kind, obj); 找不到 (None, None).
    重名时: 若 args 有 index=(该类型列表序号) 用之, 否则**拒绝并返回歧义清单**
    —— 命令层对上错对象比报错更糟 (曾把 Prefab 实例的 unlink 应用到同名源物体,
    源头被静默断开, 用户实锤"按钮没反应"的同类病根; 2026-08-27 修)."""
    name = args.get('name') or args.get('target')
    if name:
        hits = _find_all(ed, name)
        hits = [h for h in hits if h[0] in kinds]
        if not hits:
            return None, None
        if len(hits) > 1:
            idx = args.get('index')
            if idx is None:
                raise _Ambiguous(name, hits)
            idx = int(as_float(idx, -1))
            hits = [h for h in hits if h[2] == idx]
            if not hits:
                raise _Ambiguous(name, _find_all(ed, name))
        return hits[0][0], hits[0][1]
    for kind, getter in (('model', ed._selected), ('light', ed._selected_light),
                         ('camera', ed._selected_camera)):
        if kind in kinds:
            o = getter()
            if o is not None:
                return kind, o
    return None, None


class _Ambiguous(Exception):
    """重名歧义: 命令层拒绝执行, 提示用 index= (object_list 可看每个序号)."""

    def __init__(self, name, hits):
        super().__init__('重名 %r (匹配 %d 个, 需要 index= 指定序号, 先 run '
                         'object_list 查看): %s'
                         % (name, len(hits), [('%s#%d' % (k, i)) for k, _o, i in hits]))


def _no_target(kinds):
    return {'error': '没有目标: 传 name= 指定, 或先 object_select 选中 (可选类型: %s)'
            % '/'.join(kinds)}


def _commit(ed, kind, obj, label, apply_fn):
    """按目标类型走对应的 commit_* (与 GUI 同一条撤销路径)."""
    if kind == 'model':
        ed.commit_model(obj, label, apply_fn)
    elif kind == 'light':
        ed.commit_light(obj, label, apply_fn)
    else:
        ed.commit_camera(obj, label, apply_fn)


def _apply_fields(args, obj, spec):
    """把 args 里出现的字段写进 obj. spec = {参数名: (属性名, 转换函数)}.
    返回实际写入的 {属性: 值} (没传的参数一律不碰 —— 命令是"改我给的那些")."""
    done = {}
    for key, (attr, conv) in spec.items():
        if key not in args:
            continue
        val = conv(args[key])
        setattr(obj, attr, val)
        done[attr] = val
    return done


@command('engine_metrics', '引擎时钟只读指标: FPS/TPS/帧长std/逻辑暂停态/插值模式 '
                          '(方案一②观测面 + 分离功能自检, 无副作用)')
def cmd_engine_metrics(win, args):
    ed = win.editor
    out = {}
    for attr in ('fps', 'is_playing', '_logic_paused', '_logic_steps',
                 '_interp_mode', 'gravity'):
        out[attr.lstrip('_')] = getattr(ed, attr, None)
    for meth in ('get_tps', 'get_frame_jitter'):
        if hasattr(ed, meth):
            try:
                out[meth] = getattr(ed, meth)()
            except Exception as e:
                out[meth] = 'err:%r' % e
    clk = getattr(ed, '_clock', None)
    if clk is not None:
        out['clock'] = {'logic_fps': clk.logic_fps, 'alpha': round(clk.alpha, 4),
                        'steps': clk.steps, 'phys_steps': clk.phys_steps}
    # LOOM_PROFILE=1 时附阶段耗时快照 (编译版诊断用: exe 内存不可直读)
    st_t = getattr(ed, '_stage_times', None)
    if st_t:
        out['stage_times'] = dict(sorted(st_t.items(), key=lambda kv: -kv[1])[:40])
    # ★M3 (2026-09-09): 主线程分段归因快照 (帧数 + 逐段累计 ms + 调用数),
    #   供探针做 per-frame 归一化 (stage_times 本身是全程累计值, 不能直接当 ms/帧).
    if hasattr(ed, 'profile_snapshot'):
        try:
            out['mt_profile'] = ed.profile_snapshot()
        except Exception as e:
            out['mt_profile'] = 'err:%r' % e
    fb = getattr(ed, '_frame_buf', None)
    if fb is not None:
        out['frame_buffer'] = fb.metrics()
    rb = getattr(ed, '_render_buf', None)
    if rb is not None:
        out['render_buffer'] = rb.metrics()
    # 调度重构期1 (2026-09-07): NgilPool 观测面 (池计数/降级态)
    sp = getattr(ed, '_sched_pool', None)
    if sp is not None:
        try:
            out['sched_pool'] = sp.metrics_snapshot()
        except Exception:
            pass
    return out


@command('inspect', '读回目标完整状态: {name?} (Agent 自检/断言用, 无副作用)')
def cmd_inspect(win, args):
    ed = win.editor
    kind, obj = _resolve(ed, args)
    if obj is None:
        return _no_target(('model', 'light', 'camera'))
    out = {'kind': kind, 'name': obj.name}
    if kind == 'model':
        out.update({
            'position': list(obj.position), 'rotation': list(obj.rotation),
            'scale': list(obj.scale), 'visible': obj.visible,
            'saturation': getattr(obj, 'saturation', None),
            'parent': getattr(getattr(obj, 'parent', None), 'name', None),
            'prefab_ref': getattr(obj, 'prefab_ref', None),
            'material': getattr(getattr(getattr(obj, 'renderer', None),
                                        'material', None), 'name', None),
            'material_color': getattr(getattr(getattr(obj, 'renderer', None),
                                            'material', None), 'color', None),
            'collider': (None if getattr(obj, 'collider', None) is None
                         else {'enabled': obj.collider.enabled}),
            'rigidbody': (None if getattr(obj, 'rigidbody', None) is None
                          else {'use_gravity': obj.rigidbody.use_gravity,
                                'is_kinematic': obj.rigidbody.is_kinematic,
                                'mass': obj.rigidbody.mass,
                                'friction': obj.rigidbody.friction,
                                'restitution': obj.rigidbody.restitution,
                                'velocity': list(obj.rigidbody.velocity)}),
            'audio': (None if getattr(obj, 'audio_source', None) is None
                      else {'clip': obj.audio_source.clip,
                            'loop': obj.audio_source.loop,
                            'playing': obj.audio_source.playing,
                            'volume': obj.audio_source.volume}),
            'animator': (None if getattr(obj, 'animator', None) is None
                         else {'loop': obj.animator.loop,
                               'playing': obj.animator.playing,
                               'current': obj.animator.current,
                               'clips': list(obj.animator.clips or [])}),
            'scripts': [{'id': s.script_id, 'vars': dict(s.script_vars)}
                        for s in getattr(obj, 'scripts', [])],
        })
    elif kind == 'light':
        out.update({'position': list(obj.position), 'kind_of': obj.kind,
                    'intensity': obj.intensity, 'color': list(obj.color),
                    'shadow': obj.shadow, 'mode': getattr(obj, 'mode', None),
                    'shape': getattr(obj, 'shape', None),
                    'size': getattr(obj, 'size', None),
                    'range': getattr(obj, 'range', None),
                    'azimuth': getattr(obj, 'azimuth', None),
                    'elevation': getattr(obj, 'elevation', None),
                    'roll': getattr(obj, 'roll', None)})
    else:
        out.update({'position': list(obj.position), 'yaw': obj.yaw,
                    'pitch': obj.pitch, 'roll': obj.roll, 'fov': obj.fov,
                    'fov_locked': obj.fov_locked, 'pitch_lock': obj.pitch_lock,
                    'pitch_min': obj.pitch_min, 'pitch_max': obj.pitch_max,
                    'parent': getattr(getattr(obj, 'parent', None), 'name', None),
                    'active': (getattr(ed, 'active_camera', None) == obj.guid)})
    return out


@command('set_transform', '物体变换 (一步撤销): {name?, x,y,z | rx,ry,rz(度) | sx,sy,sz}')
def cmd_set_transform(win, args):
    import math
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    if not any(k in args for k in ('x', 'y', 'z', 'rx', 'ry', 'rz',
                                   'sx', 'sy', 'sz')):
        return {'error': '至少给一个字段: x/y/z (位置) rx/ry/rz (旋转度) sx/sy/sz (缩放)'}

    def apply():
        for key, axis in (('x', 'X'), ('y', 'Y'), ('z', 'Z')):
            if key in args:
                vec_set(m, 'position', axis, as_float(args[key]))
        for key, axis in (('rx', 'X'), ('ry', 'Y'), ('rz', 'Z')):
            if key in args:
                # 检查器旋转行是度制显示 / 引擎存弧度 (与 GUI 同一换算).
                # rotation 是 Point3D namedtuple: 必须整体重建 (vec_set),
                # setattr 会抛 AttributeError —— Qt 检查器就栽在这里.
                vec_set(m, 'rotation', axis, math.radians(as_float(args[key])))
        if any(k in args for k in ('sx', 'sy', 'sz')):
            cur = list(m.scale)
            for i, key in enumerate(('sx', 'sy', 'sz')):
                if key in args:
                    cur[i] = as_float(args[key], cur[i])
            m.set_scale(tuple(cur))
    _commit(ed, 'model', m, "命令: 变换", apply)
    return {'name': m.name, 'position': list(m.position),
            'rotation_deg': [round(math.degrees(v), 3) for v in m.rotation],
            'scale': list(m.scale)}


@command('set_visible', '显隐: {name?, on?} (缺 on = 切换, 同层级[显隐]按钮)')
def cmd_set_visible(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    want = None if args.get('on') is None else as_bool(args.get('on'))
    if want is None or want != bool(m.visible):
        ed.toggle_visible(m)        # GUI 同一入口 (自带撤销)
    return {'name': m.name, 'visible': bool(m.visible)}


@command('set_saturation', '饱和度: {name?, value 0..2}')
def cmd_set_saturation(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    v = max(0.0, min(2.0, as_float(args.get('value'), 1.0)))
    _commit(ed, 'model', m, "命令: 饱和度", lambda: setattr(m, 'saturation', v))
    return {'name': m.name, 'saturation': m.saturation}


@command('set_color', '改颜色: {name?, color=#RRGGBB} (材质单色覆盖)')
def cmd_set_color(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    color = args.get('color')
    if color is None:
        return {'error': '需要 color=#RRGGBB'}
    _commit(ed, 'model', m, "命令: 颜色",
            lambda: setattr(m, 'color', color if color else None))
    return {'name': m.name, 'color': m.color}


@command('set_normal_mode', '改法线模式: {name?, mode=flat|vertex}')
def cmd_set_normal_mode(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    mode = (args.get('mode') or '').lower()
    if mode not in ('flat', 'vertex'):
        return {'error': 'mode 只能 flat|vertex'}
    _commit(ed, 'model', m, "命令: 法线模式",
            lambda: setattr(m, 'normal_mode', mode))
    return {'name': m.name, 'normal_mode': m.normal_mode}


@command('materials', '材质列表 (索引/名字; set_material 用)')
def cmd_materials(win, args):
    ed = win.editor
    return {'materials': [{'index': i, 'name': mt.name}
                          for i, mt in enumerate(ed.materials)]}


@command('set_material', '换材质: {name?, index 或 material=材质名} (共享引用语义)')
def cmd_set_material(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    mats = ed.materials
    if not mats:
        return {'error': '场景没有材质 (先 material_new)'}
    key = args.get('material')
    if key is not None:
        idx = next((i for i, mt in enumerate(mats) if mt.name == key), None)
        if idx is None:
            return {'error': '找不到材质: %s (可用: %s)'
                    % (key, [mt.name for mt in mats])}
    else:
        idx = int(as_float(args.get('index'), -1))
        if not 0 <= idx < len(mats):
            return {'error': 'index 越界: %s (材质数 %d)' % (args.get('index'), len(mats))}
    ed.commit_model(m, "换材质",
                    lambda: setattr(m.renderer, 'material', mats[idx]))
    return {'name': m.name, 'material': mats[idx].name, 'index': idx}


@command('material_new', '新建材质并挂给目标: {name?} (同检查器[＋新建材质])')
def cmd_material_new(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    ed.new_material(m)
    return {'name': m.name,
            'material': getattr(m.renderer.material, 'name', None),
            'count': len(ed.materials)}


@command('set_texture', '设物体材质的颜色贴图: {name?, path=图片路径} 或 path="" 清除')
def cmd_set_texture(win, args):
    """M36 贴图: 从图片文件加载 albedo 贴图并绑到目标物体的材质上。
    path 为空 -> 清除贴图。加载失败返回 error (不改变原状态)。"""
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    path = args.get('path')
    mat = m.renderer.material
    if mat is None:
        return {'error': '物体无材质'}
    if path is None or path == '':
        ed.commit_model(m, "清除贴图", lambda: setattr(mat, 'albedo', None))
        return {'name': m.name, 'material': mat.name, 'albedo': None}
    # 相对路径基于引擎目录
    _root = os.path.dirname(os.path.abspath(__file__))
    ap = path if os.path.isabs(path) else os.path.join(_root, path)
    try:
        from loom_texture import Texture
        tex = Texture.from_file(
            ap, name=os.path.basename(ap),
            wrap=args.get('wrap', 'repeat'),
            filter_mode=args.get('filter_mode', 'trilinear'),
            aniso=as_float(args.get('aniso'), 1.0),
            max_size=int(as_float(args.get('max_size'), 0)),
            compression=args.get('compression', 'none'))
    except Exception as e:
        return {'error': '贴图加载失败: %r' % (e,)}
    ed.commit_model(m, "设贴图", lambda: setattr(mat, 'albedo', tex))
    return {'name': m.name, 'material': mat.name,
            'albedo': tex.name, 'size': [tex.width, tex.height],
            'guid': tex.guid}


@command('set_pbr', '设材质 PBR: {name?, metallic?, roughness?|smoothness?, on?} (对标 Unity Standard Shader)')
def cmd_set_pbr(win, args):
    """M36 PBR: 设金属度/粗糙度。smoothness 为 Unity 风格 (smoothness=1-roughness)。
    给了 metallic/roughness/smoothness 任一 -> 自动启用 PBR; on 可显式开关。"""
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    mat = m.renderer.material
    if mat is None:
        return {'error': '物体无材质'}

    def apply():
        if args.get('metallic') is not None:
            mat.metallic = as_float(args.get('metallic'), 0.0)
        if args.get('roughness') is not None:
            mat.roughness = as_float(args.get('roughness'), 0.5)
        elif args.get('smoothness') is not None:
            mat.roughness = 1.0 - as_float(args.get('smoothness'), 0.5)
        if args.get('on') is not None:
            mat.pbr = as_bool(args.get('on'))
        elif any(args.get(k) is not None
                 for k in ('metallic', 'roughness', 'smoothness')):
            mat.pbr = True
    ed.commit_model(m, "设 PBR", apply)
    return {'name': m.name, 'material': mat.name, 'metallic': mat.metallic,
            'roughness': mat.roughness, 'pbr': mat.pbr}


@command('set_lod', '设 LOD: {name?, bias?, screen?, on?} (对标 Unity LODGroup; 为基元自动生成低精度)')
def cmd_set_lod(win, args):
    """M36 LOD (对标 Unity LODGroup): 按屏幕占比切换网格精度。
    sphere 自动生成半精度低模; on=False 关闭 LOD; bias 为 LOD 偏移 (大=更高质量)。"""
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    r = m.renderer
    if args.get('bias') is not None:
        r.lod_bias = max(0.1, as_float(args.get('bias'), 1.0))
    if args.get('on') is not None and not as_bool(args.get('on')):
        def _off():
            r.lod_screen_levels = None
            r.lod_levels = None
            r._lod_cur = None
        ed.commit_model(m, "关闭 LOD", _off)
        return {'name': m.name, 'lod': None}
    # 自动生成: 基元 sphere -> 半精度低模; 其它基元 -> 无细分可降 (返回提示)
    prim = getattr(m, 'primitive', None)
    params = dict(getattr(m, 'params', None) or {})
    if prim == 'sphere':
        import mesh as _mesh
        hi = m.mesh
        lo = _mesh.create_sphere(
            params.get('radius', 0.5),
            max(3, int(params.get('stacks', 14)) // 2),
            max(6, int(params.get('slices', 28)) // 2))
        thr = max(0.0, min(1.0, as_float(args.get('screen'), 0.1)))

        def _on():
            r.lod_screen_levels = [(thr, hi), (0.0, lo)]
        ed.commit_model(m, "设 LOD", _on)
        return {'name': m.name, 'mode': 'screen', 'threshold': thr,
                'levels': 2, 'hi_verts': len(hi.vertices),
                'lo_verts': len(lo.vertices), 'bias': r.lod_bias}
    return {'name': m.name, 'error': '仅 sphere 基元支持自动 LOD (其它网格无细分可降)',
            'primitive': prim}


@command('set_env', '设材质环境反射贴图: {name?, paths=[6图] | color=#RRGGBB} (对标 Unity Reflection Probe)')
def cmd_set_env(win, args):
    """M36 环境反射: 从 6 面图片 (px,nx,py,ny,pz,nz) 或纯色创建 cubemap 并绑到材质。
    paths 空且无 color -> 清除环境贴图。"""
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    mat = m.renderer.material
    if mat is None:
        return {'error': '物体无材质'}
    paths = args.get('paths')
    color = args.get('color')
    if not paths and not color:
        ed.commit_model(m, "清除环境贴图", lambda: setattr(mat, 'env_map', None))
        return {'name': m.name, 'material': mat.name, 'env_map': None}
    _root = os.path.dirname(os.path.abspath(__file__))
    try:
        from loom_cubemap import Cubemap
        if paths:
            if isinstance(paths, str):
                paths = [p for p in paths.split(',') if p.strip()]
            ap = [p if os.path.isabs(p) else os.path.join(_root, p) for p in paths]
            cube = Cubemap.from_files(ap, name='环境贴图')
        else:
            cube = Cubemap.from_solid(color, size=16, name='环境贴图')
    except Exception as e:
        return {'error': '环境贴图创建失败: %r' % (e,)}
    ed.commit_model(m, "设环境贴图", lambda: setattr(mat, 'env_map', cube))
    return {'name': m.name, 'material': mat.name, 'env_map': cube.name,
            'size': cube.size, 'guid': cube.guid}


@command('collider', '碰撞器开关: {name?, on?} (缺 on = 切换)')
def cmd_collider(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    if getattr(m, 'collider', None) is None:
        return {'error': '该物体没有碰撞器组件'}
    want = None if args.get('on') is None else as_bool(args.get('on'))
    if want is None or want != bool(m.collider.enabled):
        ed.toggle_collider(m)
    return {'name': m.name, 'enabled': bool(m.collider.enabled)}


@command('rigidbody', '刚体: {name?, action=add|remove|gravity|set} '
                      '(set 精设 mass/use_gravity/is_kinematic/friction/restitution/velocity)')
def cmd_rigidbody(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    act = (args.get('action') or 'add').lower()
    if act == 'add':
        ed.add_rigidbody(m)
    elif act == 'remove':
        ed.remove_rigidbody(m)
    elif act == 'gravity':
        if getattr(m, 'rigidbody', None) is None:
            return {'error': '没有刚体 (先 rigidbody action=add)'}
        ed.toggle_rigidbody_gravity(m)
    elif act == 'set':
        rb = getattr(m, 'rigidbody', None)
        if rb is None:
            return {'error': '没有刚体 (先 rigidbody action=add)'}

        def _apply():
            if 'mass' in args:
                rb.mass = as_float(args['mass'], rb.mass)
            if 'use_gravity' in args:
                rb.use_gravity = as_bool(args['use_gravity'], rb.use_gravity)
            if 'is_kinematic' in args:
                rb.is_kinematic = as_bool(args['is_kinematic'], rb.is_kinematic)
            if 'friction' in args:
                rb.friction = as_float(args['friction'], rb.friction)
            if 'restitution' in args:
                rb.restitution = as_float(args['restitution'], rb.restitution)
            if 'velocity' in args and args['velocity']:
                v = list(args['velocity'])
                if len(v) == 3:
                    rb.velocity = type(rb.velocity)(float(v[0]), float(v[1]),
                                                    float(v[2]))
        ed.commit_model(m, '命令: 刚体参数', _apply)
    else:
        return {'error': 'action 只能 add|remove|gravity|set, 收到 %s' % act}
    rb = getattr(m, 'rigidbody', None)
    return {'name': m.name, 'action': act,
            'rigidbody': None if rb is None else {
                'use_gravity': rb.use_gravity,
                'is_kinematic': rb.is_kinematic,
                'mass': rb.mass,
                'friction': rb.friction,
                'restitution': rb.restitution,
                'velocity': list(rb.velocity)}}


@command('physics_simulate', '确定性推进 N 个逻辑帧 (物理对拍, 需在播放态): {frames=整数}')
def cmd_physics_simulate(win, args):
    """物理对拍专用: 直接驱动逻辑时钟跑 N 帧 (每帧 = _logic_frame 完整链路:
    脚本→物理子步×N→音频→动画→prep), 不依赖真实墙钟 — 结果可复现.
    命令与渲染同在主线程串行, 执行期间渲染帧不会插队."""
    ed = win.editor
    if not getattr(ed, 'is_playing', False):
        return {'error': '未在播放态: 先 play on=true (物理仅播放期运行)'}
    frames = int(as_float(args.get('frames'), 0))
    if frames <= 0:
        return {'error': 'frames 需为正整数, 收到 %r' % args.get('frames')}
    clk = ed._ensure_split()
    if clk is None:
        return {'error': '逻辑时钟未启用 (分离未开/NO_SPLIT)'}
    # 冻结引擎自走的逻辑帧 (渲染帧照跑但零逻辑), 只让本命令手动步进 —
    # 否则渲染帧按真实墙钟并发推进, 与手动帧叠加, 物理对拍不可复现.
    # reset 清 accumulator 欠账: play 后到本调用之间渲染帧已积压若干帧,
    # 不清则 step_once 会一并补跑, 起点污染 (实测 frame=1 已含~3帧).
    was_paused = getattr(ed, '_logic_paused', False)
    try:
        ed._logic_paused = True
        clk.reset()
        for _ in range(frames):
            clk.step_once()
    finally:
        ed._logic_paused = was_paused
    return {'frames': frames, 'fixed_dt': clk.fixed_dt,
            'sub_steps': clk.sub_steps, 'sub_dt': clk.sub_dt}


@command('audio', '音频源: {name?, action=add|remove|loop|play|clip|volume, clip?, value?}')
def cmd_audio(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    act = (args.get('action') or 'add').lower()
    if act == 'add':
        ed.add_audio_source(m)
    else:
        au = getattr(m, 'audio_source', None)
        if au is None:
            return {'error': '没有音频源 (先 audio action=add)'}
        if act == 'remove':
            ed.remove_audio_source(m)
        elif act == 'loop':
            ed.toggle_audio_loop(m)
        elif act == 'play':
            ed.toggle_audio_playing(m)
        elif act == 'clip':
            ed.set_audio_clip(m, args.get('clip') or '', au.clip)
        elif act == 'volume':
            v = max(0.0, min(1.0, as_float(args.get('value'), au.volume)))
            ed.commit_model(m, "命令: 音量", lambda: setattr(au, 'volume', v))
        else:
            return {'error': 'action 只能 add|remove|loop|play|clip|volume'}
    au = getattr(m, 'audio_source', None)
    return {'name': m.name, 'action': act,
            'audio': None if au is None else {'clip': au.clip, 'loop': au.loop,
                                              'playing': au.playing,
                                              'volume': au.volume}}


@command('animator', '动画组件: {name?, action=add|remove|loop|play|clip, clip?}')
def cmd_animator(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    act = (args.get('action') or 'add').lower()
    if act == 'add':
        ed.add_animator(m)
    else:
        an = getattr(m, 'animator', None)
        if an is None:
            return {'error': '没有动画组件 (先 animator action=add)'}
        if act == 'remove':
            ed.remove_animator(m)
        elif act == 'loop':
            ed.toggle_anim_loop(m)
        elif act == 'play':
            ed.toggle_anim_playing(m)
        elif act == 'clip':
            name = args.get('clip')
            if not name:
                return {'error': 'clip 缺参数 (可用: %s)' % list(an.clips or [])}
            ed.play_anim(m, name)
        else:
            return {'error': 'action 只能 add|remove|loop|play|clip'}
    an = getattr(m, 'animator', None)
    return {'name': m.name, 'action': act,
            'animator': None if an is None else {'loop': an.loop,
                                                 'playing': an.playing,
                                                 'current': an.current}}


@command('scripts', '可用脚本清单 (script_add 的 sid 取这里)')
def cmd_scripts(win, args):
    from scripts import script_options
    return {'scripts': [{'id': sid, 'name': nm} for sid, nm in script_options()
                        if sid is not None]}


@command('script_remove', '移除脚本: {name?, index} (检查器脚本行 × 按钮)')
def cmd_script_remove(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model', 'light', 'camera'))
    if m is None:
        return _no_target(('model',))
    i = int(as_float(args.get('index'), -1))
    if not 0 <= i < len(getattr(m, 'scripts', [])):
        return {'error': 'index 越界: %s (脚本数 %d)'
                % (args.get('index'), len(getattr(m, 'scripts', [])))}
    sid = m.scripts[i].script_id
    ed.remove_script(m, i)
    return {'name': m.name, 'removed': sid}


@command('script_var', '改脚本参数 (一步撤销): {name?, index, key, value}')
def cmd_script_var(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model', 'light', 'camera'))
    if m is None:
        return _no_target(('model',))
    i = int(as_float(args.get('index'), -1))
    if not 0 <= i < len(getattr(m, 'scripts', [])):
        return {'error': 'index 越界: %s' % args.get('index')}
    key = args.get('key')
    if not key:
        return {'error': '需要 key (参数名; inspect 可看已有参数)'}
    v = as_float(args.get('value'), 0.0)
    # active=False = 一次到位并压栈 (对齐 GUI 松手提交, 不是拖动中的活跃编辑)
    ed.set_script_var(m, i, key, v, False, 'cmd.svar.%d.%s' % (i, key))
    return {'name': m.name, 'index': i, key: m.scripts[i].script_vars.get(key)}


@command('light_set', '光源属性 (一步撤销): {name?, intensity,r,g,b,azimuth,elevation,'
         'roll,size,range,shadow,mode(full|beam),shape(circle|rect),x,y,z}')
def cmd_light_set(win, args):
    ed = win.editor
    kind, l = _resolve(ed, args, ('light',))
    if l is None:
        return _no_target(('light',))
    spec = {'intensity': ('intensity', as_float),
            'azimuth': ('azimuth', as_float), 'elevation': ('elevation', as_float),
            'roll': ('roll', as_float), 'size': ('size', as_float),
            'range': ('range', as_float),
            'shadow': ('shadow', as_bool), 'mode': ('mode', str),
            'shape': ('shape', str)}
    for k in ('mode', 'shape'):
        if k in args and args[k] not in (('full', 'beam') if k == 'mode'
                                         else ('circle', 'rect')):
            return {'error': '%s 只能 %s' % (k, 'full|beam' if k == 'mode'
                                            else 'circle|rect')}

    def apply():
        _apply_fields(args, l, spec)
        if any(c in args for c in 'rgb'):
            col = list(l.color)
            for i, c in enumerate('rgb'):
                if c in args:
                    col[i] = max(0.0, min(1.0, as_float(args[c], col[i])))
            l.color = tuple(col)
        for key, axis in (('x', 'X'), ('y', 'Y'), ('z', 'Z')):
            if key in args:
                vec_set(l, 'position', axis, as_float(args[key]))
    _commit(ed, 'light', l, "命令: 光源属性", apply)
    return cmd_inspect(win, {'name': l.name})


@command('camera_set', '摄像机属性 (一步撤销): {name?, yaw,pitch,roll,fov,'
         'fov_lock,pitch_lock,pitch_min,pitch_max,x,y,z}')
def cmd_camera_set(win, args):
    ed = win.editor
    kind, c = _resolve(ed, args, ('camera',))
    if c is None:
        return _no_target(('camera',))
    spec = {'yaw': ('yaw', as_float), 'pitch': ('pitch', as_float),
            'roll': ('roll', as_float), 'fov': ('fov', as_float),
            'pitch_min': ('pitch_min', as_float),
            'pitch_max': ('pitch_max', as_float),
            'pitch_lock': ('pitch_lock', as_bool)}

    def apply():
        _apply_fields(args, c, spec)
        for key, axis in (('x', 'X'), ('y', 'Y'), ('z', 'Z')):
            if key in args:
                vec_set(c, 'position', axis, as_float(args[key]))
    _commit(ed, 'camera', c, "命令: 摄像机属性", apply)
    if 'fov_lock' in args:
        # fov_locked 语义: True = 锁定玩家调整 (GUI 走 toggle, 这里做成 set)
        if as_bool(args['fov_lock']) != bool(c.fov_locked):
            ed.toggle_cam_fov_locked(c)
    return cmd_inspect(win, {'name': c.name})


@command('camera_preview', '相机预览 (附身看): {name?} / {off=true} 退出预览')
def cmd_camera_preview(win, args):
    ed = win.editor
    if as_bool(args.get('off')):
        ed.exit_camera_preview()
        return {'preview': None}
    kind, c = _resolve(ed, args, ('camera',))
    if c is None:
        return _no_target(('camera',))
    ed.toggle_camera_preview(c)
    return {'preview': getattr(getattr(ed, 'preview_camera', None), 'name', None)}


@command('reparent', '挂父/脱父: {child, parent?} (缺 parent = 脱父; 物体与相机各自成链)')
def cmd_reparent(win, args):
    ed = win.editor
    cname = args.get('child')
    if not cname:
        return {'error': '需要 child (物体名或相机名)'}
    kind, src, _i = _find(ed, cname)
    if src is None or kind == 'light':
        return {'error': '找不到可挂父的目标 (物体/相机): %s' % cname}
    pname = args.get('parent')
    if not pname:
        if getattr(src, 'parent', None) is None:
            return {'child': cname, 'parent': None, 'nochange': True}
        ed.detach(src) if kind == 'model' else ed.detach_camera(src)
        return {'child': cname, 'parent': None}
    kind2, dst, _j = _find(ed, pname)
    if dst is None:
        return {'error': '找不到父目标: %s' % pname}
    if dst is src:
        return {'error': '不能挂到自己身上'}
    if kind == 'model' and kind2 == 'model':
        # 与 GUI 拖拽同判据: 不许挂到自己的后代 (会成环)
        p = dst
        while p is not None:
            if p is src:
                return {'error': '不能挂到自己的子孙上 (会成环): %s' % pname}
            p = getattr(p, 'parent', None)
        ed.reparent(src, dst)
    elif kind == 'camera':
        ed.reparent_camera(src, dst)
    else:
        return {'error': '物体只能挂物体, 相机可挂物体/相机'}
    return {'child': cname, 'parent': pname}


@command('import_obj', '导入 .obj 模型: {path} (同工具栏[导入.obj], 免文件对话框)')
def cmd_import_obj(win, args):
    ed = win.editor
    path = args.get('path')
    if not path:
        return {'error': 'import_obj 需要 path (.obj 文件路径; 命令行无文件对话框)'}
    if not os.path.isfile(path):
        return {'error': '文件不存在: %s' % path}
    ed._import_obj(path)
    return {'imported': path,
            'model': getattr(ed._selected(), 'name', None),
            'count': len(ed.models)}


@command('prefab_save', 'Prefab 存模板: {path?} (缺省用工具栏 Prefab 名; 白名单外拒绝)')
def cmd_prefab_save(win, args):
    p = args.get('path')
    if p:
        ok, full = _safe_write_path(p, 'prefab_save', win)
        if not ok:
            return {'error': full}
        p = full
    win.editor._save_prefab(p)
    return {'saved': p or getattr(win.editor, 'prefab_name', None)}


@command('prefab_place', 'Prefab 放实例: {path?}')
def cmd_prefab_place(win, args):
    ed = win.editor
    ed._instantiate_prefab(args.get('path'))
    return {'placed': args.get('path') or getattr(ed, 'prefab_name', None),
            'count': len(ed.models)}


@command('prefab_unlink', '与 Prefab 断开连接: {name?}')
def cmd_prefab_unlink(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    ed.unlink_prefab(m)
    return {'name': m.name, 'prefab_ref': getattr(m, 'prefab_ref', None)}


@command('assets', '资源面板清单 (asset_apply/asset_place 的 type+key 取这里)')
def cmd_assets(win, args):
    # 资源面板每次现扫盘 (_scan_assets), 没有常驻 self.assets 列表 —— 命令
    # 走同一入口, 与面板看到的内容一致.
    return {'assets': [{'type': it['type'], 'key': it['key'],
                        'name': it.get('name')}
                       for it in win.editor._scan_assets()]}


def _asset_of(ed, args):
    """{type,key} -> 资产项 (与资源面板双击/按钮同一 _find_asset 入口)."""
    typ, key = args.get('type'), args.get('key')
    if not typ or not key:
        return None, {'error': '需要 type 与 key (先跑 assets 看清单)'}
    it = ed._find_asset((typ, key))
    if it is None:
        return None, {'error': '找不到资产: (%s, %s)' % (typ, key)}
    return it, None


@command('asset_apply', '材质资产应用到选中: {type, key, name?}')
def cmd_asset_apply(win, args):
    ed = win.editor
    it, err = _asset_of(ed, args)
    if err:
        return err
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    ed._apply_material_asset(it, m)
    return {'applied': args.get('key'), 'to': m.name}


@command('asset_place', '资产放入场景 (视口中心): {type, key}')
def cmd_asset_place(win, args):
    ed = win.editor
    it, err = _asset_of(ed, args)
    if err:
        return err
    ed._asset_drop_to_scene(it, (ed.width / 2, ed.height / 2))
    return {'placed': args.get('key'), 'count': len(ed.models)}


@command('asset_save', '存资产: {what=mesh|material, path?} (检查器两个"存…为资产"; 白名单外拒绝)')
def cmd_asset_save(win, args):
    ed = win.editor
    what = (args.get('what') or 'material').lower()
    p = args.get('path')
    if p:
        ok, full = _safe_write_path(p, 'asset_save', win)
        if not ok:
            return {'error': full}
        p = full
    if what == 'mesh':
        ed._save_mesh_asset(p)
    elif what == 'material':
        ed._save_material_asset(p)
    else:
        return {'error': 'what 只能 mesh|material'}
    return {'saved': what, 'path': p}


@command('set_audio_3d', '设置音频 3D 参数: {name?, category?, min_distance?, max_distance?, rolloff?}')
def cmd_set_audio_3d(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    a = obj.audio_source
    if a is None:
        return {'error': '物体无 AudioSource 组件 (先 audio action=add)'}
    # 显式校验 (组件 setter 静默回退, 命令层必须把错误告诉调用方)
    updates = {}
    if 'category' in args:
        cat = str(args['category']).strip().lower()
        if cat not in ('music', 'sfx', 'voice'):
            return {'error': 'category 只能是 music/sfx/voice, 收到 %r'
                    % (args['category'],)}
        updates['category'] = cat
    for k in ('min_distance', 'max_distance', 'rolloff'):
        if k in args:
            try:
                v = float(args[k])
            except (TypeError, ValueError):
                return {'error': '%s 必须是数字, 收到 %r' % (k, args[k])}
            if v <= 0:
                return {'error': '%s 必须大于 0, 收到 %r' % (k, v)}
            updates[k] = v
    mn = updates.get('min_distance', a.min_distance)
    mx = updates.get('max_distance', a.max_distance)
    if mx <= mn:
        return {'error': 'max_distance (%r) 必须大于 min_distance (%r)' % (mx, mn)}
    if not updates:
        return {'category': a.category, 'min_distance': a.min_distance,
                'max_distance': a.max_distance, 'rolloff': a.rolloff}

    def _apply():
        for k, v in updates.items():
            setattr(a, k, v)

    _commit(ed, kind, obj, '设置音频 3D', _apply)
    return {'category': a.category, 'min_distance': a.min_distance,
            'max_distance': a.max_distance, 'rolloff': a.rolloff}


@command('get_audio_3d', '查询音频 3D 参数: {name?}')
def cmd_get_audio_3d(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    a = obj.audio_source
    if a is None:
        return {'error': '物体无 AudioSource 组件'}
    return {'category': a.category, 'min_distance': a.min_distance,
            'max_distance': a.max_distance, 'rolloff': a.rolloff,
            'is_spatial': a.is_spatial()}


@command('set_layer', '设置物体 Layer: {name?, layer} (0~31)')
def cmd_set_layer(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    if args.get('layer') is None:
        return {'error': '需要 layer (0~31)'}
    lv = int(as_float(args['layer'], -1))
    if lv < 0 or lv > 31:
        return {'error': 'layer must be 0..31, got %r' % (args['layer'],)}
    _commit(ed, kind, obj, '设置 Layer', lambda: setattr(obj, 'layer', lv))
    return {'layer': obj.layer, 'layer_name': ed.layer_name(obj.layer)}


@command('set_tag', '设置物体 Tag: {name?, tag} (未注册自动注册; 非法字符拒绝)')
def cmd_set_tag(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    tg = args.get('tag')
    if not tg:
        return {'error': '需要 tag'}
    if isinstance(tg, str):
        tg = tg.strip()
    import layer_tag
    ok, reason = layer_tag.validate_tag(tg)
    if not ok:
        return {'error': reason}
    # EAI 宽松语义 (契约 §5.2): 未注册先注册再应用
    if not ed.tag_exists(tg):
        try:
            ed.register_tag(tg)
        except ValueError as e:
            return {'error': str(e)}
    _commit(ed, kind, obj, '设置 Tag', lambda: setattr(obj, 'tag', tg))
    return {'tag': obj.tag}


@command('get_layer_tag', '查询物体 Layer/Tag: {name?}')
def cmd_get_layer_tag(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    return {'layer': obj.layer, 'layer_name': ed.layer_name(obj.layer),
            'tag': obj.tag}


@command('list_tags', '列出所有已注册 Tag')
def cmd_list_tags(win, args):
    import layer_tag
    return {'tags': layer_tag.get_tags()}


@command('list_layers', '列出所有层编号与层名')
def cmd_list_layers(win, args):
    ed = win.editor
    return {'layers': {str(i): ed.layer_name(i) for i in range(32)}}


# ================= 2026-10-18 阶段5: UI 编辑命令 =================

_UI_TYPE_NAMES = ('panel', 'text', 'image', 'button', 'slider', 'toggle',
                  'progress_bar', 'scroll_view', 'input_field', 'dropdown',
                  'grid_layout')


def _push_ui_undo(win, cmd, auto_do=True):
    """UI 编辑撤销入口（2026-10-18 阶段5）.

    auto_do=True : 通过 undo.push 执行 cmd.do() 并压栈（默认，用于 ui_add/ui_remove）
    auto_do=False: 通过 undo.push_no_do 只压栈（用于 ui_set，字段已改完只需记录快照差异）

    2026-10-18 修复：无 undo_mgr 环境（PlayerApp 无撤销 / 冒烟桩）时：
      - auto_do=True : 手动执行 cmd.do() 完成实际修改（否则元素根本不会加/删）
      - auto_do=False: 跳过 do()（ui_set 已 setattr 完，幂等重复也无害但不必）
    """
    ed = getattr(win, 'editor', None)
    undo_mgr = getattr(ed, 'undo', None) if ed is not None else None
    if undo_mgr is None:
        if auto_do:
            try:
                cmd.do()
            except Exception:
                pass
        return
    try:
        if auto_do:
            undo_mgr.push(cmd)
        else:
            undo_mgr.push_no_do(cmd)
    except Exception:
        pass


def _ui_canvas(win, args):
    """按 args['canvas'] 取 Canvas（缺省=第 0 个）. 找不到返回 None."""
    ui = getattr(win.editor, 'ui', None)
    if ui is None or not ui.canvases:
        return None
    idx = int(as_float(args.get('canvas', 0), 0))
    if idx < 0 or idx >= len(ui.canvases):
        return None
    return ui.canvases[idx]


def _ui_parent(win, args):
    """找父元素: args['parent'] 指定 name, 缺省 = canvas root. 返回 (canvas, parent)."""
    c = _ui_canvas(win, args)
    if c is None:
        return None, None
    pname = args.get('parent')
    if not pname:
        return c, c.root
    hit = c.root.find(pname)
    if hit is None:
        return c, None
    return c, hit


def _ui_auto_name(parent, typ):
    """自动生成唯一 name（{typ}_{n}，从 0 开始找未占用的）."""
    n = 0
    while True:
        name = '%s_%d' % (typ, n)
        if parent.find(name) is None:
            return name
        n += 1


def _ui_to_dict(elem):
    """UIElement -> dict（用于 ui_list）."""
    return {
        'type': elem.ctype,
        'name': elem.name,
        'rect': list(elem.rect),
        'anchor': list(elem.anchor),
        'pivot': list(elem.pivot),
        'visible': bool(elem.visible),
        'enabled': bool(elem.enabled),
        'z_order': int(elem.z_order),
        'children': [_ui_to_dict(ch) for ch in elem.children],
    }


@command('ui_canvas_add', '添加 UI Canvas: {type?, width?, height?, z_order?} '
                          '(type=screen|world, 默认 screen)')
def cmd_ui_canvas_add(win, args):
    from loom_ui import Canvas
    ui = getattr(win.editor, 'ui', None)
    if ui is None:
        return {'error': '引擎没有 ui 字段'}
    typ = str(args.get('type', 'screen'))
    if typ not in ('screen', 'world'):
        return {'error': 'type 必须是 screen 或 world, 收到 %r' % typ}
    w = int(as_float(args.get('width', 800), 800))
    h = int(as_float(args.get('height', 600), 600))
    z = int(as_float(args.get('z_order', 0), 0))
    c = Canvas(canvas_type=typ, width=w, height=h, z_order=z)
    idx = len(ui.canvases)
    import undo as _undo_mod
    cmd = _undo_mod.UIAddCanvasCommand('添加 Canvas', win.editor, c, idx)
    _push_ui_undo(win, cmd)
    return {'canvas_type': typ, 'width': w, 'height': h, 'z_order': z,
            'total': len(ui.canvases)}


@command('ui_add', '添加 UI 元素: {type, name?, parent?, canvas?, ...字段} '
                   '(type: panel|text|image|button|slider|toggle|progress_bar|'
                   'scroll_view|input_field|dropdown|grid_layout)')
def cmd_ui_add(win, args):
    typ = str(args.get('type', ''))
    if typ not in _UI_TYPE_NAMES:
        return {'error': 'type 必须是以下之一: %s, 收到 %r'
                         % (', '.join(_UI_TYPE_NAMES), typ)}
    c, parent = _ui_parent(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号, 先 ui_list 查看）'}
    if parent is None:
        return {'error': '找不到父元素: %r' % args.get('parent')}
    name = args.get('name') or _ui_auto_name(parent, typ)
    import loom_ui

    kw = {'name': name}
    if 'rect' in args:
        kw['rect'] = tuple(args['rect'])
    if 'anchor' in args:
        kw['anchor'] = tuple(args['anchor'])
    if 'pivot' in args:
        kw['pivot'] = tuple(args['pivot'])
    if 'visible' in args:
        kw['visible'] = bool(args['visible'])
    if 'enabled' in args:
        kw['enabled'] = bool(args['enabled'])
    if 'z_order' in args:
        kw['z_order'] = int(as_float(args['z_order'], 0))

    def take(key, conv=lambda v: v):
        if key in args:
            kw[key] = conv(args[key])

    if typ == 'panel':
        take('bg_color', tuple)
        elem = loom_ui.Panel(**kw)
    elif typ == 'text':
        take('text', str)
        take('font_size', lambda v: int(as_float(v, 16)))
        take('color', tuple)
        take('align', str)
        take('wrap_width', lambda v: int(as_float(v, 0)))
        elem = loom_ui.Text(**kw)
    elif typ == 'image':
        take('texture_path', str)
        take('tint', tuple)
        take('fit', str)
        elem = loom_ui.Image(**kw)
    elif typ == 'button':
        take('text', str)
        take('font_size', lambda v: int(as_float(v, 16)))
        take('text_color', tuple)
        take('normal_color', tuple)
        take('hover_color', tuple)
        take('pressed_color', tuple)
        elem = loom_ui.Button(**kw)
    elif typ == 'slider':
        take('min_value', float)
        take('max_value', float)
        take('value', float)
        take('direction', str)
        take('track_color', tuple)
        take('fill_color', tuple)
        take('handle_color', tuple)
        elem = loom_ui.Slider(**kw)
    elif typ == 'toggle':
        take('is_on', bool)
        take('label', str)
        take('label_size', lambda v: int(as_float(v, 16)))
        take('box_color', tuple)
        take('check_color', tuple)
        take('label_color', tuple)
        elem = loom_ui.Toggle(**kw)
    elif typ == 'progress_bar':
        take('value', float)
        take('bg_color', tuple)
        take('fill_color', tuple)
        elem = loom_ui.ProgressBar(**kw)
    elif typ == 'scroll_view':
        take('content_size', tuple)
        take('scroll_pos', tuple)
        take('bg_color', tuple)
        take('bar_color', tuple)
        take('bar_width', lambda v: int(as_float(v, 8)))
        take('show_bar', bool)
        take('scroll_step', lambda v: int(as_float(v, 30)))
        elem = loom_ui.ScrollView(**kw)
    elif typ == 'input_field':
        take('text', str)
        take('placeholder', str)
        take('max_length', lambda v: int(as_float(v, 200)))
        take('bg_color', tuple)
        take('focus_bg_color', tuple)
        take('text_color', tuple)
        take('placeholder_color', tuple)
        take('cursor_color', tuple)
        take('font_size', lambda v: int(as_float(v, 16)))
        elem = loom_ui.InputField(**kw)
    elif typ == 'dropdown':
        take('options', list)
        take('selected_index', lambda v: int(as_float(v, 0)))
        take('bg_color', tuple)
        take('hover_color', tuple)
        take('list_bg', tuple)
        take('list_hover', tuple)
        take('text_color', tuple)
        take('font_size', lambda v: int(as_float(v, 14)))
        take('item_height', lambda v: int(as_float(v, 28)))
        elem = loom_ui.Dropdown(**kw)
    elif typ == 'grid_layout':
        take('cell_size', tuple)
        take('spacing', tuple)
        take('columns', lambda v: int(as_float(v, 4)))
        take('bg_color', tuple)
        elem = loom_ui.GridLayout(**kw)
    else:
        return {'error': '内部错误: type %r 未实现' % typ}

    idx = len(parent.children)
    # 2026-10-18 阶段5: 撤销（决策选项2，UI 编辑全进撤销栈）
    import undo as _undo_mod
    _push_ui_undo(win, _undo_mod.UIAddCommand('添加 UI 元素', win.editor,
                                              parent, elem, idx))
    return {'name': name, 'type': typ, 'parent': parent.name,
            'canvas': c.canvas_type, 'total': len(parent.children)}


@command('ui_set', '修改 UI 元素字段: {name, canvas?, ...字段} '
                   '(支持 rect/anchor/pivot/visible/enabled/z_order + type-specific)')
def cmd_ui_set(win, args):
    name = args.get('name')
    if not name:
        return {'error': '必须传 name=（先 ui_list 查看所有元素）'}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号）'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    if elem is c.root:
        return {'error': '不能修改 Canvas root（用 ui_add / ui_set 改具体元素）'}

    # 2026-10-18 阶段5: 改前快照（撤销用）
    import undo as _undo_mod
    before = _undo_mod.ui_elem_snapshot(elem)

    done = {}
    if 'rect' in args:
        elem.rect = tuple(args['rect'])
        done['rect'] = list(elem.rect)
    if 'anchor' in args:
        elem.anchor = tuple(args['anchor'])
        done['anchor'] = list(elem.anchor)
    if 'pivot' in args:
        elem.pivot = tuple(args['pivot'])
        done['pivot'] = list(elem.pivot)
    if 'visible' in args:
        elem.visible = bool(args['visible'])
        done['visible'] = elem.visible
    if 'enabled' in args:
        elem.enabled = bool(args['enabled'])
        done['enabled'] = elem.enabled
    if 'z_order' in args:
        elem.z_order = int(as_float(args['z_order'], 0))
        done['z_order'] = elem.z_order

    def take(key, conv=lambda v: v):
        if key in args and hasattr(elem, key):
            try:
                setattr(elem, key, conv(args[key]))
                done[key] = getattr(elem, key)
            except Exception as e:
                done[key] = 'error: %r' % e

    typ = elem.ctype
    if typ == 'panel':
        take('bg_color', tuple)
    elif typ == 'text':
        take('text', str)
        take('font_size', lambda v: int(as_float(v, 16)))
        take('color', tuple)
        take('align', str)
        take('wrap_width', lambda v: int(as_float(v, 0)))
    elif typ == 'image':
        take('texture_path', str)
        take('tint', tuple)
        take('fit', str)
    elif typ == 'button':
        take('text', str)
        take('font_size', lambda v: int(as_float(v, 16)))
        take('text_color', tuple)
        take('normal_color', tuple)
        take('hover_color', tuple)
        take('pressed_color', tuple)
    elif typ == 'slider':
        take('min_value', float)
        take('max_value', float)
        take('value', float)
        take('direction', str)
        take('track_color', tuple)
        take('fill_color', tuple)
        take('handle_color', tuple)
    elif typ == 'toggle':
        take('is_on', bool)
        take('label', str)
        take('label_size', lambda v: int(as_float(v, 16)))
        take('box_color', tuple)
        take('check_color', tuple)
        take('label_color', tuple)
    elif typ == 'progress_bar':
        take('value', float)
        take('bg_color', tuple)
        take('fill_color', tuple)
    elif typ == 'scroll_view':
        take('content_size', tuple)
        take('scroll_pos', tuple)
        take('bg_color', tuple)
        take('bar_color', tuple)
        take('bar_width', lambda v: int(as_float(v, 8)))
        take('show_bar', bool)
        take('scroll_step', lambda v: int(as_float(v, 30)))
    elif typ == 'input_field':
        take('text', str)
        take('placeholder', str)
        take('max_length', lambda v: int(as_float(v, 200)))
        take('bg_color', tuple)
        take('focus_bg_color', tuple)
        take('text_color', tuple)
        take('placeholder_color', tuple)
        take('cursor_color', tuple)
        take('font_size', lambda v: int(as_float(v, 16)))
    elif typ == 'dropdown':
        take('options', list)
        take('selected_index', lambda v: int(as_float(v, 0)))
        take('bg_color', tuple)
        take('hover_color', tuple)
        take('list_bg', tuple)
        take('list_hover', tuple)
        take('text_color', tuple)
        take('font_size', lambda v: int(as_float(v, 14)))
        take('item_height', lambda v: int(as_float(v, 28)))
    elif typ == 'grid_layout':
        take('cell_size', tuple)
        take('spacing', tuple)
        take('columns', lambda v: int(as_float(v, 4)))
        take('bg_color', tuple)
        if hasattr(elem, '_reflow'):
            try:
                elem._reflow()
            except Exception:
                pass

    if not done:
        return {'error': '没有可改的字段（检查参数名）', 'type': typ}
    # 2026-10-18 阶段5: 撤销（仅当字段真的有变化时压栈）
    import undo as _undo_mod
    after = _undo_mod.ui_elem_snapshot(elem)
    if after != before:
        _push_ui_undo(win, _undo_mod.UIStateCommand('修改 UI 属性',
                                                    win.editor, elem,
                                                    before, after), auto_do=False)
    return {'name': name, 'type': typ, 'changed': done}


@command('ui_remove', '删除 UI 元素: {name, canvas?}')
def cmd_ui_remove(win, args):
    name = args.get('name')
    if not name:
        return {'error': '必须传 name=（先 ui_list 查看所有元素）'}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号）'}
    if name == c.root.name:
        return {'error': '不能删除 Canvas root（用其他方式清空）'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    parent = elem.parent
    if parent is None:
        return {'error': '元素没有父节点，无法删除'}
    # 2026-10-18 阶段5: 撤销
    import undo as _undo_mod
    cmd = _undo_mod.UIRemoveCommand('删除 UI 元素', win.editor, elem)
    _push_ui_undo(win, cmd)
    return {'removed': name, 'parent': parent.name,
            'remaining': len(parent.children)}


@command('ui_list', '列出 UI 树: {canvas?} (缺省=全部 Canvas)')
def cmd_ui_list(win, args):
    ui = getattr(win.editor, 'ui', None)
    if ui is None:
        return {'error': '引擎没有 ui 字段'}
    only_canvas = args.get('canvas')
    out = []
    for i, c in enumerate(ui.canvases):
        if only_canvas is not None and int(as_float(only_canvas, -1)) != i:
            continue
        out.append({
            'index': i,
            'canvas_type': c.canvas_type,
            'width': c.width,
            'height': c.height,
            'z_order': c.z_order,
            'root': _ui_to_dict(c.root),
        })
    return {'canvases': out, 'total': len(ui.canvases)}


@command('ui_reparent', '移动 UI 元素到另一个父元素: {name, new_parent, canvas?, index?} '
                            '(new_parent 缺省 = Canvas root; 检查循环依赖)')
def cmd_ui_reparent(win, args):
    name = args.get('name')
    if not name:
        return {'error': '必须传 name=（先 ui_list 查看所有元素）'}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号）'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    if elem is c.root:
        return {'error': '不能移动 Canvas root'}

    new_parent_name = args.get('new_parent')
    if new_parent_name:
        new_parent = c.root.find(new_parent_name)
        if new_parent is None:
            return {'error': '找不到新父元素: %r' % new_parent_name}
    else:
        new_parent = c.root

    if new_parent is elem:
        return {'error': '不能把元素挂到自己下面'}
    # 循环依赖检查: new_parent 不能是 elem 的子孙
    p = new_parent
    while p is not None:
        if p is elem:
            return {'error': '不能把元素挂到自己的子孙下面（会造成循环）'}
        p = p.parent

    old_parent = elem.parent
    if old_parent is None:
        return {'error': '元素没有父节点，无法移动'}
    if old_parent is new_parent:
        return {'error': '新旧父元素相同（如需调整同级顺序用 ui_move_child）'}
    try:
        old_idx = old_parent.children.index(elem)
    except ValueError:
        old_idx = -1

    new_idx = None
    if 'index' in args:
        ni = int(as_float(args['index'], -1))
        if ni >= 0:
            new_idx = ni

    import undo as _undo_mod
    cmd = _undo_mod.UIReparentCommand('移动 UI 父节点', win.editor,
                                      elem, old_parent, old_idx,
                                      new_parent, new_idx)
    _push_ui_undo(win, cmd)
    return {'name': name, 'old_parent': old_parent.name,
            'new_parent': new_parent.name,
            'old_index': old_idx,
            'new_index': elem.parent.children.index(elem)
            if elem.parent is new_parent else -1}


@command('ui_move_child', '同一父元素内调整顺序: {name, to_index, canvas?}')
def cmd_ui_move_child(win, args):
    name = args.get('name')
    if not name:
        return {'error': '必须传 name=（先 ui_list 查看所有元素）'}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号）'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    if elem is c.root:
        return {'error': '不能移动 Canvas root'}
    parent = elem.parent
    if parent is None:
        return {'error': '元素没有父节点，无法移动'}
    if 'to_index' not in args:
        return {'error': '必须传 to_index=（同级列表中的目标位置，0 起）'}
    try:
        cur_idx = parent.children.index(elem)
    except ValueError:
        return {'error': '元素不在父节点列表中'}
    to_idx = int(as_float(args['to_index'], -1))
    if to_idx < 0 or to_idx >= len(parent.children):
        return {'error': 'to_index 范围超限（0~%d），收到 %d'
                         % (len(parent.children) - 1, to_idx)}
    if to_idx == cur_idx:
        return {'name': name, 'moved': False, 'index': cur_idx,
                'message': '位置相同，未移动'}

    import undo as _undo_mod
    cmd = _undo_mod.UIMoveChildCommand('调整 UI 顺序', win.editor,
                                       elem, cur_idx, to_idx)
    _push_ui_undo(win, cmd)
    return {'name': name, 'moved': True,
            'old_index': cur_idx, 'new_index': to_idx,
            'siblings': [ch.name for ch in parent.children]}


# ================= 2026-10-18 射线检测命令 =================

@command('raycast', '射线检测: {ox,oy,oz, dx,dy,dz, max_dist?, backend?} '
                     '返回最近命中 {hit: {name, distance, point} | null}')
def cmd_raycast(win, args):
    ed = win.editor
    try:
        ox = float(args['ox']); oy = float(args['oy']); oz = float(args['oz'])
        dx = float(args['dx']); dy = float(args['dy']); dz = float(args['dz'])
    except (KeyError, ValueError, TypeError):
        return {'error': '需要 ox/oy/oz/dx/dy/dz 六个数值参数'}
    max_dist = float(as_float(args.get('max_dist', 1000.0), 1000.0))
    backend = str(args.get('backend', 'auto'))
    ignore = None
    if args.get('ignore'):
        ignore = _find_model_by_name(ed, args['ignore'])
    r = ed.raycast((ox, oy, oz), (dx, dy, dz),
                   max_dist=max_dist, ignore_model=ignore, backend=backend)
    if r is None:
        return {'hit': None}
    model, dist, pt = r
    return {'hit': {'name': model.name,
                    'distance': round(float(dist), 4),
                    'point': [round(p, 4) for p in pt]}}


@command('raycast_all', '射线检测（全部命中）: 参数同上，返回 hits 列表按距离升序')
def cmd_raycast_all(win, args):
    ed = win.editor
    try:
        ox = float(args['ox']); oy = float(args['oy']); oz = float(args['oz'])
        dx = float(args['dx']); dy = float(args['dy']); dz = float(args['dz'])
    except (KeyError, ValueError, TypeError):
        return {'error': '需要 ox/oy/oz/dx/dy/dz 六个数值参数'}
    max_dist = float(as_float(args.get('max_dist', 1000.0), 1000.0))
    backend = str(args.get('backend', 'auto'))
    rs = ed.raycast_all((ox, oy, oz), (dx, dy, dz),
                        max_dist=max_dist, backend=backend)
    return {'hits': [{'name': m.name,
                      'distance': round(float(d), 4),
                      'point': [round(p, 4) for p in pt]}
                     for m, d, pt in rs]}


@command('raycast_screen', '屏幕坐标反投影射线: {px, py, max_dist?, backend?} '
                            '返回最近命中（与鼠标点选等价）')
def cmd_raycast_screen(win, args):
    ed = win.editor
    if 'px' not in args or 'py' not in args:
        return {'error': '需要 px/py（屏幕像素坐标）'}
    px = float(as_float(args['px'])); py = float(as_float(args['py']))
    max_dist = float(as_float(args.get('max_dist', 1000.0), 1000.0))
    backend = str(args.get('backend', 'auto'))
    r = ed.raycast_screen(px, py, max_dist=max_dist, backend=backend)
    if r is None:
        return {'hit': None}
    model, dist, pt = r
    return {'hit': {'name': model.name,
                    'distance': round(float(dist), 4),
                    'point': [round(p, 4) for p in pt]}}


def _find_model_by_name(ed, name):
    for m in getattr(ed, 'models', []) or []:
        if m.name == name:
            return m
    return None


@command('settings_get', '读编辑器设置: {key?} (fps_limit/cam_speed/多核 等)')
def cmd_settings_get(win, args):
    import guiloader
    s = guiloader.load_settings('loom')
    return s if not args.get('key') else {args['key']: s.get(args['key'])}


@command('settings_set', '写编辑器设置: {key, value} (与设置面板同一份 设置.json)')
def cmd_settings_set(win, args):
    import guiloader
    key = args.get('key')
    if not key:
        return {'error': '需要 key'}
    val = args.get('value')
    if isinstance(val, str):        # 控制台只能给字符串: 归一成 bool/数字
        low = val.strip().lower()
        if low in ('true', 'yes', 'on'):
            val = True
        elif low in ('false', 'no', 'off'):
            val = False
        else:
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    pass
    s = guiloader.load_settings('loom')
    s[key] = val
    guiloader.save_settings('loom', s)
    # 帧率档位改了要即时生效 (GUI 设置面板同款调用)
    if key == 'fps_limit' and hasattr(win, '_apply_fps_limit'):
        try:
            win._apply_fps_limit(val)
        except Exception as e:
            log('[命令] fps_limit 即时生效失败: %r' % e)
    elif key == 'logic_fps':
        try:
            v = int(val)
            ed = getattr(win, 'editor', None)
            eng = getattr(ed, 'engine', ed) if ed else None
            clk = getattr(eng, '_clock', None)
            if clk is not None and v > 0:
                clk.set_fps(logic_fps=v)
        except Exception as e:
            log('[命令] logic_fps 即时生效失败: %r' % e)
    return {'set': {key: val}, 'type': type(val).__name__}


# ====================================================================
# AGENT 桥: 端口/令牌 + HTTP 服务 (仅 127.0.0.1)
# ====================================================================
def port_file_path(base=None):
    base = base or os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base, '.agent_port.json')


def _write_port_file(base, port, token):
    data = {'port': port, 'token': token,
            'pid': os.getpid(),
            'url': 'http://127.0.0.1:%d' % port,
            'started': time.strftime('%Y-%m-%d %H:%M:%S')}
    path = port_file_path(base)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


class _CmdHandler(BaseHTTPRequestHandler):
    """POST /cmd {cmd,args} / GET /logs?after=N / GET /status / GET /"""
    service = None

    def log_message(self, fmt, *args):      # 静默 request 日志进 LOG_RING
        pass

    def _auth(self):
        """令牌校验 (2026-08-28 二轮中危2): ①hmac.compare_digest 常量时间
        比较 (原 == 存在时序侧信道); ②Host 头只认本机 (防 DNS rebinding/
        恶意网页向 127.0.0.1 发请求携带同 token 的真实场景覆盖率低, 但
        native bind 127.0.0.1 已是主边界, 这里再收一道)."""
        import hmac
        tok = self.headers.get('X-Agent-Token') or ''
        if not hmac.compare_digest(tok.encode('utf-8'),
                                   self.server.service.token.encode('utf-8')):
            return False
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost', '')

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._auth():
            return self._json(401, {'ok': False, 'error': 'bad token'})
        if self.path.startswith('/logs'):
            after = 0
            if 'after=' in self.path:
                try:
                    after = int(self.path.split('after=')[1].split('&')[0])
                except Exception:
                    after = 0
            return self._json(200, {'ok': True, 'seq': _LOG_SEQ,
                                    'lines': log_since(after)})
        if self.path.startswith('/status'):
            # self.service 是类属性 None (handler 实例上没有), 服务实例只在
            # self.server.service —— 曾写成 self.service.started 直接 500.
            return self._json(200, {'ok': True, 'pid': os.getpid(),
                                    'alive': self.server.service.started})
        return self._json(200, {'ok': True, 'service': 'loom-agent',
                                'commands': list(_COMMANDS)})

    def do_POST(self):
        if not self._auth():
            return self._json(401, {'ok': False, 'error': 'bad token'})
        if not self.path.startswith('/cmd'):
            return self._json(404, {'ok': False, 'error': 'not found'})
        try:
            req = json.loads(self.rfile.read(
                int(self.headers.get('Content-Length', 0)) or 0)
                .decode('utf-8'))
        except Exception as e:
            return self._json(400, {'ok': False, 'error': repr(e)})
        cmd, args = req.get('cmd'), req.get('args') or {}
        result = self.server.service.submit(cmd, args)
        self._json(200, result)


class AgentService:
    """EAI 服务: 命令队列 -> Qt 主线程执行 (qt_view QTimer 轮询 drain)."""

    def __init__(self, win, base=None):
        self.win = win
        self.base = base or os.path.dirname(os.path.abspath(sys.argv[0]))
        self.token = secrets.token_hex(16)
        self.queue = queue.Queue()
        self.server = None
        self.thread = None
        self.started = False
        self.port = 0

    def start(self):
        """启动 HTTP 服务 + 写端口文件 (Qt 事件循环前调用).
        serve_forever 线程异常会记录到日志并打印 (进程死不了,
        socket 释放; 此信息用于排查 "端口文件在但连不上")."""
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _CmdHandler)
        self.server.service = self

        def _serve():
            try:
                self.server.serve_forever(poll_interval=0.1)
            except Exception as e:          # noqa: 调试可见
                print('[agent] serve_forever 线程退出: %r' % e, flush=True)
                log('[agent] serve_forever 线程退出: %r' % e)
        self.thread = threading.Thread(target=_serve, daemon=True)
        self.thread.start()
        self.started = True
        self.port = self.server.server_address[1]
        _write_port_file(self.base, self.port, self.token)
        print('[agent] EAI serving on http://127.0.0.1:%d (pid=%d)'
              % (self.port, os.getpid()), flush=True)
        log('[agent] EAI 启动: http://127.0.0.1:%d' % self.port)
        # 2026-08-28 二轮(中危2): 不再打印 token 任何片段 (启动日志泄露面)
        return self.port

    def submit(self, cmd, args):
        """HTTP 线程调用: 入队 + 等主线程执行结果 (超时 30s)."""
        ev = threading.Event()
        self.queue.put((cmd, args, ev))
        if not ev.wait(30.0):
            return {'ok': False, 'error': '命令超时 (30s): %s' % cmd}
        return ev.result

    def drain(self):
        """Qt 主线程轮询 (QTimer): 执行队列命令, 回填结果."""
        while True:
            try:
                cmd, args, ev = self.queue.get_nowait()
            except queue.Empty:
                break
            ev.result = dispatch(cmd, args, self.win)
            ev.set()

    def stop(self):
        self.started = False
        if self.server:
            self.server.shutdown()
        try:
            os.remove(port_file_path(self.base))
        except Exception:
            pass


def load_agent_info(base=None):
    """Agent 侧: 读端口文件 -> (port, token, url, pid) 或 None."""
    path = port_file_path(base)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None
