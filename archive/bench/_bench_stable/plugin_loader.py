# -*- coding: utf-8 -*-
"""
plugin_loader.py — Loom 插件加载器 (L1 分级重设计, 2026-08-27)
====================================================================
承接《Loom插件系统分级方案.txt》: 三类插件、两种信任、两层注入。

目录结构 (程序目录 = 源码 Loom 目录 / 编译版 exe 目录):
  plugins/editor/   普通插件 - 只注入编辑器层 (开发者工具, 封装不带)
  plugins/player/   普通插件 - 只注入播放器层 (游戏刚需, 封装打包带走)
  core_plugins/<类别>/<插件>/   核心插件 - 替换引擎核心 (gui/render/physics/
                                input...), 全权, 人工信任闸 + 哈希 + 重启生效
  插件信任.json                 核心插件信任记录 {id: {path, files{sha256}, time}}

分级语义:
  - 普通插件 (plugins/): 受限执行环境 (防投放误用; 非真沙箱, 见 docstring#受限)
  - 核心插件 (core_plugins/): 全权, 安装须信任确认 (弹窗) + 全文件 SHA256
    校验; 未信任/被改过 = 不加载 (记 untrusted 供 UI 弹窗); 确认写信任表
    后重启生效。
  - mode: 'editor' (默认, Loom.exe 编辑器) -> 普通插件受限; 'player'
    (玩家运行时 / 游戏封装) -> 全权加载 (内容已由可信链路供给)。

受限执行环境 (普通插件, 防君子不防小人 —— Python 元编程绕道防不住):
  - 受限 builtins: 无 open/exec/eval/compile/globals/locals/setattr 等
  - import 白名单: 纯标准库计算/数据结构模块 math/re/collections/itertools/
    functools/dataclasses/typing/random/copy/json (2026-08-28: scripts/engine/
    matlib 已移出 —— 命名空间真实含 os/sys/np 或依赖后端, 见
    _RESTRICTED_MODULES 注释, 引擎能力一律走 api.*)
  - 文件系统: 插件资源走 api.read_asset(name) (限插件目录, 只读)
  - 动态代码: exec/eval 不可用; __import__ 换白名单版
  - **信任级别**: 本环境拦截"随手抓系统" (直写/直导入/拼接名), **不拦截
    有意元编程** (__import__.__globals__ / __subclasses__ 属性链是 Python
    语言机制, 进程内无隔离方案) —— 带毒插件与带毒脚本同级威胁, 只投放
    可信来源; 真正隔离方案 (插件子进程最小权限) 见《Loom插件系统分级方案.txt》L2 待办

插件目录结构 (投放式, 放进即装/删掉即卸载):
  plugins/player/<任意目录名>/
      plugin.json   {"id","name","version","entry", 可选 "min_engine","deps"}
      entry.py      def register(api): ... (必需)
  核心插件 plugin.json 额外必填: "layer": "editor"|"player",
      "capability": "<可替换功能类别>", "desc": "用途说明" (信任确认框展示)
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import types

# ---- 常量 ----
PLUGIN_DIR_NAME = 'plugins'
CORE_PLUGIN_DIR_NAME = 'core_plugins'
MANIFEST = 'plugin.json'
ENTRY = 'entry.py'
TRUST_FILE = '插件信任.json'
CURRENT_VERSION = '1.0.0'   # 与 解释器.json 同步 (合同第九节)
LAYERS = ('editor', 'player')
CORE_CATEGORIES = None      # 功能类别不限白名单, 目录即类别 (gui/render/...)

# 程序目录解析 (cwd 无关): 源码 = 本文件所在目录; 编译版 = exe 目录
if getattr(sys, 'frozen', False):
    _PROGRAM_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
else:
    _PROGRAM_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- 校验正则 (宽松但防注入/防重名污染) ----
_ID_SEG = re.compile(r'^[A-Za-z0-9_-]+$')
_VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')
_ENGINE_RE = re.compile(r'^\d+\.\d+$')
_ENTRY_RE = re.compile(r'^[A-Za-z0-9_.-]+\.py$')

# ---- 全局状态 ----
_LOADED = {}          # id -> {'info','path','layer','kind','api','mod'}
_DISABLED = set()     # 会话禁用 (卸载按钮): 重扫跳过, 重启恢复 (放进即装语义)
_EDITOR_BUTTONS = []  # [(text, callback, plugin_id)] 跨层按钮注册表
_MODE = 'editor'      # 'editor' 普通插件受限 | 'player' 玩家进程全权


def set_mode(mode):
    """进程角色: 'editor'(默认, 普通插件受限) | 'player'(全权).
    玩家运行时 / 游戏封装加载前调用, 语义见模块 docstring."""
    global _MODE
    if mode not in ('editor', 'player'):
        raise ValueError('mode 必须是 editor|player')
    _MODE = mode


def get_mode():
    return _MODE


def _id_ok(pid):
    if not isinstance(pid, str) or not pid or len(pid) > 64:
        return False
    return all(_ID_SEG.match(s) for s in pid.split('.'))


def _engine_ok(min_engine):
    """min_engine <= CURRENT_VERSION (major.minor 段比较, 支持 beta 引擎)."""
    if not min_engine:
        return True
    m = _ENGINE_RE.match(min_engine)
    if not m:
        return False

    def _mm(sv):
        mm = re.match(r'^(\d+)\.(\d+)', sv)
        return (int(mm.group(1)), int(mm.group(2))) if mm else None
    a, b = _mm(min_engine), _mm(CURRENT_VERSION)
    return a is not None and b is not None and a <= b


# ====================================================================
# 普通插件受限执行环境 (2026-08-27: 限制危险权利; 2026-08-28 靶场后收口)
# ====================================================================
# 受限 import 检查函数 + 白名单/黑名单常量在 plugin_sandbox.py (V06 修复):
# 函数的 __globals__ 属性是语言机制 —— 检查函数定义在"零 import"沙箱模块,
# 攻击者 __import__.__globals__ 只能榨出字符串/常量, 拿不到 os/sys/importlib.
# 白名单收窄历史 (攻击靶场 _attack_range_普通插件释毒实验 实测):
#   scripts/engine/matlib 已移出 —— ①engine/scripts 命名空间真实含
#   os/sys/np/pygame (import engine → engine.os.open 直写任意文件 = V04;
#   engine.np.savetxt 写文件 = V07); ②投影救不了 (暴露名函数的 __globals__
#   同样泄); ③matlib 首参是 numpy/cupy 后端, 受限环境用不上.
#   插件要引擎能力一律走 api.* (L1: register_script / register_editor_button
#   / read_asset)。
from plugin_sandbox import (          # noqa: E402
    _RESTRICTED_MODULES, _BANNED_MODULES, restricted_import,
)


def _restricted_import(name, globals_=None, locals_=None, fromlist=(),
                       level=0):
    """受限 __import__ 转发到沙箱实现.
    **本转发函数为什么只是薄壳**: 受限插件得到的 __import__ 对象必须定义在
    plugin_sandbox.py (函数 __globals__ 语言机制暴露定义模块), 其命名空间
    "榨无可榨" (V06 修复)。plugin_loader 侧同样的名字仅供内部一致性调用,
    绝不把这个转发函数放进受限 builtins (那是 V06 复活点, test 有断言)。"""
    return restricted_import(name, globals_, locals_, fromlist, level)


# 受限 builtins 白名单 (名字 -> 诚实列表; 未列出的均不可用)
_RESTRICTED_BUILTIN_NAMES = (
    # 常量
    'None', 'True', 'False',
    # 语句/类机制必需 (无害, 仅语言运行); __build_class__ 缺了 class 语句直接崩
    '__build_class__', '__debug__',
    # 异常全家
    'Exception', 'ArithmeticError', 'AssertionError', 'AttributeError',
    'BaseException', 'EOFError', 'FileNotFoundError', 'ImportError',
    'IndexError', 'KeyError', 'LookupError', 'MemoryError', 'NameError',
    'NotImplementedError', 'OSError', 'OverflowError', 'RecursionError',
    'RuntimeError', 'StopAsyncIteration', 'StopIteration', 'SyntaxError',
    'TypeError', 'UnboundLocalError', 'ValueError', 'ZeroDivisionError',
    'Warning', 'UserWarning', 'FloatingPointError', 'InterruptedError',
    'SystemError',
    # 纯数据/计算/常用 (无系统副作用)
    'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'bytearray', 'bytes',
    'callable', 'chr', 'complex', 'dict', 'divmod', 'enumerate', 'filter',
    'float', 'frozenset', 'hash', 'hex', 'id', 'int', 'isinstance',
    'issubclass', 'iter', 'len', 'list', 'map', 'max', 'min', 'next',
    'oct', 'ord', 'pow', 'print', 'range', 'repr', 'reversed', 'round',
    'set', 'slice', 'sorted', 'str', 'sum', 'tuple', 'zip',
    # 语言/对象机制 (纯语义; 2026-08-28 二轮收口: getattr/setattr/delattr/
    # hasattr/dir/vars/locals/globals **全部移除** —— 复扫实锤: 这些"检索
    # 原语"是 AST 门禁唯一的破绽面 (别名化 g=getattr 即绕), 普通插件正常
    # 写法 0 依赖; 保留 object/type/super 等 class/属性机制本身, 但黑面
    # 属性名 (__globals__/__class__/__subclasses__ 等) 仍由 AST 门禁拦,
    # 无检索原语后无法绕道取面)
    'object', 'type', 'super', 'property', 'staticmethod', 'classmethod',
)


def _restricted_builtins():
    """构造受限 builtins dict (模块 __builtins__ 用): 含白名单名字 +
    受限 __import__. 注意: 该环境防误用不开方为安全边界 (元编程可绕).
    2026-08-28: d['__import__'] 必须是 **plugin_sandbox.restricted_import**
    (定义在零依赖沙箱模块)。若换成 plugin_loader 的 _restricted_import 转发
    函数, 插件 __import__.__globals__ 又回到本模块命名空间 (含 os) —— V06
    复活 (test_restricted_v06_shortcut 守护)。"""
    import builtins as _b
    d = {n: getattr(_b, n) for n in _RESTRICTED_BUILTIN_NAMES}
    d['__import__'] = restricted_import
    return d


# ---- 受限入口 AST 审查 (2026-08-28, 渗透靶场 V05 收口) ----
# 拦"元编程黑面"的直接书写 (V05 实锤路径: __subclasses__/__globals__/
# __builtins__/__class__/__bases__/__mro__ 属性访问 + vars/locals/globals/
# dir/getattr(黑面名) 调用)。AST 拦的是"直接写" —— 正常插件 (api.register_
# script/register_editor_button/read_asset + 纯数学) 0 误伤; 刻意混淆仍可绕
# (诚实档位=防误用拦阻, 真安全边界 = L2 子进程最小权限, 见方案文档)。
_RESTRICTED_ATTR_NAMES = frozenset((
    '__globals__', '__subclasses__', '__builtins__', '__class__',
    '__bases__', '__mro__', '__dict__', '__reduce__', '__reduce_ex__',
    '__getattribute__', '__setattr__', '__getattr__',
))
_RESTRICTED_RETRIEVER_FUNCS = frozenset((
    'vars', 'locals', 'globals', 'dir', 'getattr',
))


def _entry_ast_check(src, path):
    """AST 静态审查受限插件入口; 返回 (None, None) = 通过, (id, 原因) = 拒绝.
    只审计属性名与检索调用, 不做语义分析 (防御=门槛, 非沙箱)."""
    import ast
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as e:
        return 'syntax', 'entry.py 语法错误: %s' % e

    def bad_attr(name):
        return name in _RESTRICTED_ATTR_NAMES

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if bad_attr(node.attr):
                return 'meta-attr', ('受限: 元编程属性 `.%s` 被禁止 '
                                     '(AST 审查, V05 靶场路径)' % node.attr)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _RESTRICTED_RETRIEVER_FUNCS:
                return 'retriever', '受限: %s() 被禁止 (AST 审查, 元编程检索工具)' % fn.id
            if isinstance(fn, ast.Attribute) and bad_attr(fn.attr):
                return 'meta-call', '受限: `.%s()` 被禁止 (AST 审查)' % fn.attr
            # getattr(x, '__globals__') 字符串参数形态
            if isinstance(fn, ast.Name) and fn.id == 'getattr' and node.args:
                a1 = node.args[1] if len(node.args) > 1 else None
                if isinstance(a1, ast.Constant) and isinstance(a1.value, str) \
                        and bad_attr(a1.value):
                    return 'getattr-meta', '受限: getattr(..., %r) 被禁止 (AST 审查)' % a1.value
    return None, None


def _load_entry_restricted(entry_path, mod_name):
    """受限方式加载插件 entry.py: 编译 + 受限 builtins exec.
    模块内函数/类方法执行时沿用模块受限 builtins (函数 globals=模块 dict).
    2026-08-28 (V06 修复): 加载前先剥离沙箱模块 dict 的 __builtins__ ——
    否则受限插件 __import__.__globals__['__builtins__'] 拿到真 builtins
    (open/eval 全在)。沙箱模块内的函数均已"定义时绑定"所需内建, 剥离后
    白名单放行照常 (plugin_sandbox 模块 docstring 有完整设计说明)。
    2026-08-28 (V05 收口): entry 源码先过 _entry_ast_check (元编程黑面直写
    `.__subclasses__`/`.__globals__`/`.`__builtins__` 等直接拒绝加载)。"""
    import plugin_sandbox
    plugin_sandbox._strip_builtins()
    with open(entry_path, 'r', encoding='utf-8') as f:
        src = f.read()
    why, detail = _entry_ast_check(src, entry_path)
    if why:
        raise ValueError('%s: %s' % (why, detail))
    code = compile(src, entry_path, 'exec')
    mod = types.ModuleType(mod_name)
    mod.__file__ = entry_path
    ns = mod.__dict__
    ns['__builtins__'] = _restricted_builtins()
    exec(code, ns)
    sys.modules[mod_name] = mod
    return mod


# ====================================================================
# 清单校验
# ====================================================================
def _parse_manifest(dir_path, core=False):
    """读并校验插件目录 plugin.json. 返回 (info, None) 或 (None, 错误).
    core=True 时额外必填: layer(editor|player)/capability/desc."""
    mpath = os.path.join(dir_path, MANIFEST)
    try:
        with open(mpath, 'r', encoding='utf-8') as f:
            info = json.load(f)
    except Exception as e:
        return None, '%s 读取/解析失败: %r' % (MANIFEST, e)
    if not isinstance(info, dict):
        return None, '%s 顶层必须是对象' % MANIFEST
    for key in ('id', 'name', 'version', 'entry'):
        if not isinstance(info.get(key), str) or not info[key].strip():
            return None, '%s 缺必填字段: %s' % (MANIFEST, key)
    if not _id_ok(info['id']):
        return None, '插件 id 非法: %r (反向域名风格)' % info['id']
    if not _VERSION_RE.match(info['version']):
        return None, '插件 version 非法: %r (需 x.y.z)' % info['version']
    if not _ENTRY_RE.match(info['entry']):
        return None, '插件 entry 非法: %r (仅允许合法 .py 文件名)' % info['entry']
    entry_path = os.path.join(dir_path, info['entry'])
    if not os.path.isfile(entry_path):
        return None, '入口文件不存在: %s' % info['entry']
    if not _engine_ok(info.get('min_engine')):
        return None, ('需要引擎 %s, 当前 %s' % (info.get('min_engine'),
                                               CURRENT_VERSION))
    if 'deps' in info and not (isinstance(info['deps'], list)
                               and all(isinstance(d, str) for d in info['deps'])):
        return None, 'deps 必须是字符串数组'
    if core:
        # 核心插件更严: 注入层必须显式声明 (防按功能类别臆断)
        if info.get('layer') not in LAYERS:
            return None, '核心插件必须显式声明 "layer": "editor" 或 "player"'
        if not (isinstance(info.get('capability'), str)
                and info['capability'].strip()):
            return None, '核心插件缺 capability (替换哪个功能: gui/render/physics/input...)'
        if not (isinstance(info.get('desc'), str) and info['desc'].strip()):
            return None, '核心插件缺 desc (用途说明, 信任确认框展示)'
    return info, None


# ====================================================================
# 核心插件信任闸 (全权插件的安全边界 = 人工确认 + 哈希)
# ====================================================================
def trust_path(base=None):
    return os.path.join(base or _PROGRAM_DIR, TRUST_FILE)


def _hash_dir(d):
    """目录递归全文件 SHA256: {相对路径: 十六进制指纹}."""
    out = {}
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, d).replace('\\', '/')
            with open(p, 'rb') as fh:
                out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return out


def _load_trust(base=None):
    try:
        with open(trust_path(base), 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_trust(t, base=None):
    path = trust_path(base)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(t, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def core_trust_state(info, dir_path, base=None):
    """核心插件信任状态: 'trusted' | 'untrusted' | 'modified'.
    modified = 已信任但文件指纹变化 (权限更高警惕: 拒绝加载 + 重新确认)."""
    rec = _load_trust(base).get(info['id'])
    if not rec or rec.get('path') != dir_path:
        return 'untrusted'
    if rec.get('files') != _hash_dir(dir_path):
        return 'modified'
    return 'trusted'


def confirm_core_trust(plugin_id, dir_path, base=None):
    """确认信任 (UI 弹窗用户点击后调用): 记录路径 + 全文件 SHA256.
    写表成功返回 True, 失败返回 False (不记录, 下次继续弹窗)."""
    t = _load_trust(base)
    t[plugin_id] = {'path': dir_path, 'files': _hash_dir(dir_path),
                    'time': time.strftime('%Y-%m-%d %H:%M:%S')}
    try:
        _save_trust(t, base)
        return True
    except Exception as e:
        print('[插件] 写信任表失败: %r' % e)
        return False


def forget_core_trust(plugin_id, base=None):
    """撤销信任记录 (插件被删/用户想重新确认时)."""
    t = _load_trust(base)
    if plugin_id in t:
        del t[plugin_id]
        try:
            _save_trust(t, base)
        except Exception:
            pass


# ====================================================================
# 插件 API (register 钩子)
# ====================================================================
class PluginAPI:
    """插件注册 API. 普通插件受限 (script/button/read_asset); 核心同 API
    但不受限. 未开放扩展点记 pending, L2+ 开放 (每扩展点先过权限评审)."""

    def __init__(self, info, kind='standard', layer='editor', path=''):
        self.info = info
        self.kind = kind                 # 'standard' | 'core'
        self.layer = layer               # 'editor' | 'player' (注入主体层)
        self.pending = []
        self._sids = set()
        self._path = path                # 插件目录 (read_asset 根)

    def register(self, kind, item):
        if kind == 'script':
            self.register_script(item)
            return
        self.pending.append((kind, item))
        print('[插件] %s 使用了暂未开放的扩展点 "%s" (记入待办, L2+ 开放)' %
              (self.info['id'], kind))

    def register_script(self, cls):
        """注册行为脚本类 (与 scripts.SCRIPTS @register 同池, 检查器可挂)."""
        from scripts import SCRIPTS
        sid = getattr(cls, 'script_id', None)
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError('register_script 需要 Script 子类且 '
                             'script_id 非空字符串')
        SCRIPTS[sid] = cls
        self._sids.add(sid)

    def register_editor_button(self, text, callback):
        """(路 A 跨层界面补充) 插件在编辑器侧注册操作按钮 -> 工具栏「插件」
        菜单展示. 不影响注入层声明 (逻辑层仍按 layer 封装). 回调与插件
        同环境执行 (普通插件=受限)."""
        if not (isinstance(text, str) and text.strip()):
            raise ValueError('register_editor_button 需要非空按钮文字')
        if not callable(callback):
            raise ValueError('register_editor_button 回调必须是可调用对象')
        for i, (t, _, pid) in enumerate(_EDITOR_BUTTONS):
            if pid == self.info['id'] and t == text:
                _EDITOR_BUTTONS[i] = (text, callback, self.info['id'])
                return
        _EDITOR_BUTTONS.append((text, callback, self.info['id']))

    def read_asset(self, name):
        """读插件包内文本资源 (仅限插件目录内, 相对路径, 只读).
        普通插件文件系统的唯一入口; 越界/缺失抛 ValueError."""
        if not self._path:
            raise ValueError('read_asset 不可用: 无插件目录')
        root = os.path.normpath(self._path)
        full = os.path.normpath(os.path.join(root, name))
        if not full.startswith(root + os.sep):
            raise ValueError('read_asset 越界: %s' % name)
        with open(full, 'r', encoding='utf-8') as f:
            return f.read()


def editor_buttons():
    """编辑器跨层按钮注册表 [(text, callback, plugin_id)...] (qt_view 用)."""
    return list(_EDITOR_BUTTONS)


# ====================================================================
# 加载 / 卸载
# ====================================================================
def plugin_root(base=None):
    """普通插件根目录 = <程序目录>/plugins."""
    return os.path.join(base or _PROGRAM_DIR, PLUGIN_DIR_NAME)


def plugin_dir(layer=None, base=None):
    """普通插件可放目录: plugin_dir('loom')=plugins 根 (兼容旧调用);
    plugin_dir('editor'|'player') = 对应层目录; 缺省=根."""
    if layer is None or layer == 'loom':
        return plugin_root(base)
    if layer in LAYERS:
        return os.path.join(plugin_root(base), layer)
    raise ValueError('layer 必须是 editor|player, 收到 %r' % layer)


def core_plugin_root(base=None):
    return os.path.join(base or _PROGRAM_DIR, CORE_PLUGIN_DIR_NAME)


def _load_one(dir_path, info, kind, layer):
    """加载单插件 entry.py (普通插件按 _MODE 受限/全权, 核心恒全权).
    返回 (api, mod); 异常向上抛由调用方隔离."""
    api = PluginAPI(info, kind=kind, layer=layer, path=dir_path)
    entry_path = os.path.join(dir_path, info['entry'])
    mod_name = 'loom_plugin_' + re.sub(r'[^A-Za-z0-9_]', '_', info['id'])
    if kind == 'standard' and _MODE == 'editor':
        mod = _load_entry_restricted(entry_path, mod_name)
    else:
        spec = importlib.util.spec_from_file_location(mod_name, entry_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    reg = getattr(mod, 'register', None)
    if not callable(reg):
        raise ValueError('entry.py 未提供 register(api) 钩子')
    reg(api)
    return api, mod


def _try_scan_folder(folder, kind, result, base, seen):
    """扫一层插件目录 (folder 内每个子目录=一个插件), 逐个检验+加载."""
    if not os.path.isdir(folder):
        return
    for fname in sorted(os.listdir(folder)):
        d = os.path.join(folder, fname)
        if not os.path.isdir(d):
            continue
        info, err = _parse_manifest(d, core=(kind == 'core'))
        if info is None:
            result['broken'].append({'id': fname, 'error': err})
            print('[插件] 跳过「%s」: %s' % (fname, err))
            continue
        if info['id'] in seen:
            result['broken'].append({'id': fname,
                                     'error': '插件 id 重复: %s' % info['id']})
            print('[插件] 跳过「%s」: 插件 id 重复 (%s)' % (fname, info['id']))
            continue
        seen.add(info['id'])
        # ---- 核心插件信任闸 (未信任/被改过 = 不加载, 等 UI 确认) ----
        if kind == 'core':
            state = core_trust_state(info, d, base)
            if state != 'trusted':
                result['untrusted'].append(
                    {'id': info['id'], 'path': d, 'info': info,
                     'state': state, 'kind': 'core'})
                print('[插件] 核心「%s」%s, 等待信任确认 (确认后重启生效)'
                      % (info['id'], '未信任' if state == 'untrusted'
                         else '文件被修改'))
                continue
        if kind == 'standard':
            layer = os.path.basename(folder)   # 目录即声明 (editor|player)
        else:
            layer = info['layer']              # 核心: 清单显式 (校验必填)
        # ---- 幂等 / 禁用 ----
        cur = _LOADED.get(info['id'])
        if cur is not None and cur['path'] == d:
            continue
        if info['id'] in _DISABLED:
            continue
        try:
            api, mod = _load_one(d, info, kind, layer)
        except Exception as e:
            result['broken'].append({'id': info['id'], 'error': repr(e)})
            print('[插件] 加载「%s」失败, 已跳过回退官方: %r'
                  % (info['id'], e))
            continue
        _LOADED[info['id']] = {'info': info, 'path': d,
                               'layer': layer, 'kind': kind,
                               'api': api, 'mod': mod}
        result['loaded'].append(info['id'])
        print('[插件] 已加载「%s」%s v%s (%s层%s)' % (
            info['id'], info.get('name', ''), info['version'], layer,
            ' 核心' if kind == 'core' else ''))


def load_plugins(base=None):
    """扫描并加载全部插件:
       plugins/editor/* + plugins/player/* (普通, 目录即声明注入层)
       core_plugins/<类别>/* (核心, 清单必须声明 layer; 信任闸)
    返回 {'loaded': [id...], 'broken': [{id,error}...],
          'untrusted': [{id,path,info,state}...]}."""
    base = base or _PROGRAM_DIR
    result = {'loaded': [], 'broken': [], 'untrusted': []}
    seen = set()
    # 普通插件: editor + player 两层
    for layer in LAYERS:
        _try_scan_folder(os.path.join(plugin_root(base), layer),
                         'standard', result, base, seen)
    # 核心插件: core_plugins/<类别>/<插件>
    core = core_plugin_root(base)
    if os.path.isdir(core):
        for cat in sorted(os.listdir(core)):
            cat_dir = os.path.join(core, cat)
            if os.path.isdir(cat_dir):
                _try_scan_folder(cat_dir, 'core', result, base, seen)
    return result


def _load_from_src(src, mod_name):
    """从内存源码加载模块 (封装游戏 .lpc 的 entry 用): 编译+exec, 不落盘.
    全权环境 (内容已由封装/信任链路供给), exec 自动携带标准 builtins."""
    code = compile(src, '<plugin:%s>' % mod_name, 'exec')
    mod = types.ModuleType(mod_name)
    mod.__file__ = '<plugin:%s>' % mod_name
    exec(code, mod.__dict__)
    sys.modules[mod_name] = mod
    return mod


def load_plugin_from_pack(plugin_id, entry_src, assets, info, layer):
    """封装游戏玩家端: 从解密后的插件包加载单插件 (全权, 内容已可信).
    assets = {相对路径: bytes} (插件资源, 供 read_asset 类扩展; L1 仅 entry).
    返回 (api, mod) 或抛异常. 供 game_player 用."""
    api = PluginAPI(info, kind='core', layer=layer, path='')
    mod_name = 'loom_gameplugin_' + re.sub(r'[^A-Za-z0-9_]', '_',
                                           info['id'])
    mod = _load_from_src(entry_src, mod_name)
    reg = getattr(mod, 'register', None)
    if not callable(reg):
        raise ValueError('entry.py 未提供 register(api) 钩子')
    reg(api)
    return api, mod


def scan_player_plugins(base=None):
    """封装收集 (build_game 用): 播放器层全部插件目录及清单 =
    plugins/player/* (普通) + core_plugins/**/layer=player (核心).
    返回 [{id,path,kind,layer,info}]; 只用清单不作执行."""
    base = base or _PROGRAM_DIR
    out = []
    seen = set()
    # 普通 player 层
    player_dir = os.path.join(plugin_root(base), 'player')
    if os.path.isdir(player_dir):
        for fname in sorted(os.listdir(player_dir)):
            d = os.path.join(player_dir, fname)
            if not os.path.isdir(d):
                continue
            info, err = _parse_manifest(d)
            if info is None or info['id'] in seen:
                continue
            seen.add(info['id'])
            out.append({'id': info['id'], 'path': d,
                        'kind': 'standard', 'layer': 'player', 'info': info})
    # 核心 player 层 (清单 layer=player)
    core = core_plugin_root(base)
    if os.path.isdir(core):
        for cat in sorted(os.listdir(core)):
            cat_dir = os.path.join(core, cat)
            if not os.path.isdir(cat_dir):
                continue
            for fname in sorted(os.listdir(cat_dir)):
                d = os.path.join(cat_dir, fname)
                if not os.path.isdir(d):
                    continue
                info, err = _parse_manifest(d, core=True)
                if info is None or info.get('layer') != 'player':
                    continue
                if info['id'] in seen:
                    continue
                seen.add(info['id'])
                out.append({'id': info['id'], 'path': d,
                            'kind': 'core', 'layer': 'player', 'info': info})
    return out


# ====================================================================
# 卸载 / 重扫 (兼容旧 API)
# ====================================================================
def unload_plugin(plugin_id, disable=True):
    """卸载已加载插件: 调 deactivate 钩子 + 清理注册脚本/按钮 + 移出 _LOADED.
    disable=True = 手动卸载 (会话禁用, 重扫跳过, 重启恢复);
    disable=False = 目录消失清理 (目录回来仍加载)."""
    entry = _LOADED.get(plugin_id)
    if entry is None:
        return False, '插件未加载: %s' % plugin_id
    try:
        deact = getattr(entry['mod'], 'deactivate', None)
        if callable(deact):
            deact(entry['api'])
        from scripts import SCRIPTS
        for sid in entry['api']._sids:
            SCRIPTS.pop(sid, None)
        _EDITOR_BUTTONS[:] = [b for b in _EDITOR_BUTTONS
                              if b[2] != plugin_id]
    except Exception as e:
        return False, repr(e)
    del _LOADED[plugin_id]
    if disable:
        _DISABLED.add(plugin_id)
    print('[插件] 已卸载「%s」%s' % (
        plugin_id, '(会话禁用)' if disable else '(目录清理)'))
    return True, None


def load_plugin(plugin_id, base=None):
    """手动加载单个插件 (设置面板'加载'按钮): 取消会话禁用 + 全量重扫.
    核心插件会先过信任闸 (未信任/被改无法手动拉起来)."""
    _DISABLED.discard(plugin_id)
    return load_plugins(base)


def rescan_plugins(base=None):
    """重新扫描: 加载新增 + 卸载目录已消失的. 手动禁用保持禁用."""
    result = load_plugins(base)
    for pid in list(_LOADED):
        if not os.path.isdir(_LOADED[pid]['path']):
            ok, err = unload_plugin(pid, disable=False)
            print('[插件] 目录已消失, 卸载「%s」: %s'
                  % (pid, err if not ok else '成功'))
    return result


def get_loaded():
    return dict(_LOADED)


def get_plugin(plugin_id):
    return _LOADED.get(plugin_id)


def list_untrusted(base=None):
    """当前未信任/被改的核心插件详情 (启动弹窗用, 不做加载)."""
    r = load_plugins(base)
    return r['untrusted']
