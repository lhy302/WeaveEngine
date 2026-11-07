# -*- coding: utf-8 -*-

"""
test_plugin_register_rollback.py — 插件注册事务化 + 脚本 id 所有权 (scan_09 P-04/P-05)

背景 (审计 docs/audit/scan_09_scripting.md)
------------------------------------------
P-04 [PROVED/P1] 加载失败后残留部分注册, 且无法卸载:
    _try_scan_folder -> _load_one -> exec 成功 + 模块入 sys.modules ->
    reg(api) 里先 register_script / register_editor_button, 之后抛异常 ->
    except 只 append broken 并 continue; _LOADED 不写入 -> unload_plugin 走
    "插件未加载" 直接返回, 清理链不可达。结果: 加载器对用户说"失败/回退官方",
    但失败插件的脚本仍在检查器下拉可挂、按钮仍可点、模块常驻 sys.modules。

P-05 [PROVED/P1] 脚本 id 无所有权 (裁决 Q2=A: **禁止覆盖任何已存在 id**):
    插件注册 'rotate' 覆盖内建 -> 卸载按 api._sids pop('rotate') -> 内建自转
    从 SCRIPTS 永久消失 (检查器下拉少一项, 已挂物体静默不执行), 只有重启进程
    才由模块级 @register 恢复。两个插件共用同一 id 时, 卸载一个会删掉另一个的。

本文件断言修复后的行为:
  A 组: 部分注册后抛异常 -> broken, 且 SCRIPTS / 工具栏按钮 / sys.modules 全无残留,
        且不影响"别的插件/别的条目" (只回滚本次新增)。
  B 组: id 冲突 (内建 rotate / 另一插件已占用的 id) -> 加载被拒 + 报错含 "冲突",
        内建/先注册者原对象**身份不变**。
  C 组: 卸载只清自己的条目 (不误删内建)。
  D 组: 封装包内存加载 (load_plugin_from_pack) 同一套事务语义。
  E 组: 失败后把 entry.py 修好再 rescan -> 能正常加载 (失败不留下"中毒"状态)。

运行: python tests\test_plugin_register_rollback.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # Loom\

import plugin_loader
import scripts
from scripts import SCRIPTS

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _manifest(pid):
    return json.dumps({"id": pid, "name": "事务测试插件", "version": "0.1.0",
                       "entry": "entry.py"}, ensure_ascii=False)


def _plugin(tmp, name, pid, entry_src):
    d = os.path.join(tmp, 'plugins', 'player', name)
    _write(os.path.join(d, 'plugin.json'), _manifest(pid))
    _write(os.path.join(d, 'entry.py'), entry_src)


def _cleanup():
    for pid in list(plugin_loader._LOADED):
        plugin_loader.unload_plugin(pid, disable=False)
    plugin_loader._DISABLED.clear()
    plugin_loader._EDITOR_BUTTONS[:] = []
    for sid in list(SCRIPTS):
        if sid.startswith('probe_') or sid.startswith('tx_'):
            del SCRIPTS[sid]


def _modules_with(prefix):
    return [m for m in sys.modules if m.startswith(prefix)]


# ---- 部分注册后抛异常 ----
ENTRY_HALF = """# -*- coding: utf-8 -*-
class HalfScript:
    script_id = 'probe_half_sid'
    name = '半注册脚本'


def _cb():
    return 'clicked'


def register(api):
    api.register_script(HalfScript)
    api.register_editor_button('半注册按钮', _cb)
    raise RuntimeError('boom after registering')
"""

# ---- 覆盖内建 id ----
ENTRY_COLLIDE_BUILTIN = """# -*- coding: utf-8 -*-
class EvilRotate:
    script_id = 'rotate'
    name = '顶掉内建自转'


def register(api):
    api.register_script(EvilRotate)
"""

# ---- 两个插件抢同一个 id ----
ENTRY_SHARED_A = """# -*- coding: utf-8 -*-
class SharedA:
    script_id = 'probe_shared'
    name = '共享A'


def register(api):
    api.register_script(SharedA)
"""

ENTRY_SHARED_B = """# -*- coding: utf-8 -*-
class SharedB:
    script_id = 'probe_shared'
    name = '共享B'


def register(api):
    api.register_script(SharedB)
"""

ENTRY_OK_OWN = """# -*- coding: utf-8 -*-
class OwnScript:
    script_id = 'probe_own'
    name = '自己的脚本'


def register(api):
    api.register_script(OwnScript)
"""

ENTRY_FIXED_OK = """# -*- coding: utf-8 -*-
class FixedScript:
    script_id = 'probe_fixed'
    name = '修好后'


def register(api):
    api.register_script(FixedScript)
"""


# ====================================================================
# A 组: 部分注册 -> 抛异常 -> 全量回滚
# ====================================================================
def t_rollback_partial():
    _cleanup()
    tmp = tempfile.mkdtemp()
    _plugin(tmp, 'half', 'probe.half', ENTRY_HALF)
    r = plugin_loader.load_plugins(base=tmp)
    check("[A] 半注册插件 -> broken (loaded 为空)",
          r['loaded'] == [] and len(r['broken']) == 1
          and r['broken'][0]['id'] == 'probe.half'
          and 'RuntimeError' in r['broken'][0]['error'], r)
    check("[A] SCRIPTS 无残留", 'probe_half_sid' not in SCRIPTS)
    check("[A] 工具栏按钮无残留",
          not any(b[2] == 'probe.half' for b in plugin_loader.editor_buttons()),
          plugin_loader.editor_buttons())
    check("[A] sys.modules 无残留 (模块已摘除)",
          _modules_with('loom_plugin_probe_half') == [],
          _modules_with('loom_plugin_probe_half'))
    check("[A] 失败插件不在 _LOADED (与'未加载'语义一致)",
          plugin_loader.get_plugin('probe.half') is None)
    _cleanup()


def t_rollback_keeps_others():
    """回滚只撤本次新增: 别人已注册的条目/已存在的按钮不得被误删。"""
    _cleanup()

    class Foreign:
        script_id = 'probe_foreign'
        name = '别人的脚本'
    SCRIPTS['probe_foreign'] = Foreign
    plugin_loader._EDITOR_BUTTONS.append(('别人的按钮', lambda: 1, 'other.plugin'))
    try:
        tmp = tempfile.mkdtemp()
        _plugin(tmp, 'half', 'probe.half', ENTRY_HALF)
        plugin_loader.load_plugins(base=tmp)
        check("[A] 回滚不误删他人脚本", SCRIPTS.get('probe_foreign') is Foreign)
        check("[A] 回滚不误删他人按钮",
              any(b[0] == '别人的按钮' for b in plugin_loader.editor_buttons()),
              plugin_loader.editor_buttons())
    finally:
        _cleanup()


# ====================================================================
# B 组: id 冲突 -> 拒绝加载 + 原持有者身份不变
# ====================================================================
def t_conflict_builtin():
    _cleanup()
    builtin = scripts.get_script('rotate')
    check("[B] 前置: 内建 rotate 存在", builtin is not None
          and getattr(builtin, 'name', '') == '自转')
    tmp = tempfile.mkdtemp()
    _plugin(tmp, 'collide', 'probe.collide', ENTRY_COLLIDE_BUILTIN)
    r = plugin_loader.load_plugins(base=tmp)
    check("[B] 覆盖内建 id -> 拒绝加载 (broken 含 '冲突')",
          r['loaded'] == [] and len(r['broken']) == 1
          and '冲突' in r['broken'][0]['error'], r['broken'])
    check("[B] 内建 rotate 身份不变 (仍是原类)",
          SCRIPTS.get('rotate') is builtin and builtin.name == '自转',
          SCRIPTS.get('rotate'))
    check("[B] 冲突插件类未混入注册表",
          all(getattr(c, '__name__', '') != 'EvilRotate'
              for c in SCRIPTS.values()))
    _cleanup()


def t_conflict_between_plugins():
    _cleanup()
    tmp = tempfile.mkdtemp()
    _plugin(tmp, 'aaa', 'probe.pa', ENTRY_SHARED_A)
    _plugin(tmp, 'bbb', 'probe.pb', ENTRY_SHARED_B)
    r = plugin_loader.load_plugins(base=tmp)
    a_cls = SCRIPTS.get('probe_shared')
    check("[B] 先注册者生效 + 后注册者被拒 (id 冲突)",
          'probe.pa' in r['loaded'] and len(r['broken']) == 1
          and r['broken'][0]['id'] == 'probe.pb'
          and '冲突' in r['broken'][0]['error'], r)
    check("[B] 注册表里仍是 A 的类",
          a_cls is not None and getattr(a_cls, '__name__', '') == 'SharedA',
          a_cls)
    ok, err = plugin_loader.unload_plugin('probe.pa', disable=False)
    check("[B] 卸载 A 后 probe_shared 消失 (不再误删 B, 因为 B 根本没注册)",
          ok and 'probe_shared' not in SCRIPTS, err)
    check("[B] 内建 rotate 全程未受影响",
          getattr(SCRIPTS.get('rotate'), 'name', '') == '自转')
    _cleanup()


# ====================================================================
# C 组: 卸载只清自己的条目
# ====================================================================
def t_unload_only_own():
    _cleanup()
    tmp = tempfile.mkdtemp()
    _plugin(tmp, 'own', 'probe.own', ENTRY_OK_OWN)
    r = plugin_loader.load_plugins(base=tmp)
    check("[C] 正常插件 loaded + 注册", r['loaded'] == ['probe.own']
          and 'probe_own' in SCRIPTS, r)
    ok, err = plugin_loader.unload_plugin('probe.own', disable=False)
    check("[C] 卸载后自己的脚本消失", ok and 'probe_own' not in SCRIPTS, err)
    check("[C] 内建脚本不受影响",
          all(sid in SCRIPTS for sid in
              ('rotate', 'orbit', 'bob', 'wasd_move', 'camera_follow')))
    _cleanup()


# ====================================================================
# D 组: 封装包内存加载 (load_plugin_from_pack) 同一套事务语义
# ====================================================================
def t_pack_rollback():
    _cleanup()
    info = {"id": "probe.packfail", "name": "包内坏插件", "version": "0.1.0",
            "entry": "entry.py", "layer": "player", "capability": "render",
            "desc": "事务测试"}
    src = ("class PackScript:\n"
           "    script_id = 'probe_pack_sid'\n"
           "    name = '包内脚本'\n"
           "def register(api):\n"
           "    api.register_script(PackScript)\n"
           "    raise RuntimeError('pack boom')\n")
    raised = False
    try:
        plugin_loader.load_plugin_from_pack('probe.packfail', src, {}, info, 'player')
    except RuntimeError as e:
        raised = 'pack boom' in str(e)
    check("[D] 包内 register 抛异常 -> 向上抛 (不吞)", raised)
    check("[D] 包内失败无脚本残留", 'probe_pack_sid' not in SCRIPTS)
    check("[D] 包内失败无模块残留",
          _modules_with('loom_gameplugin_probe_packfail') == [],
          _modules_with('loom_gameplugin_probe_packfail'))
    # 正常包内插件仍能加载 (事务不误伤成功路径)
    ok_info = dict(info)
    ok_info['id'] = 'probe.packok'
    ok_src = ("class PackOk:\n"
              "    script_id = 'probe_pack_ok'\n"
              "    name = '包内正常'\n"
              "def register(api):\n"
              "    api.register_script(PackOk)\n")
    api, mod = plugin_loader.load_plugin_from_pack('probe.packok', ok_src, {},
                                                   ok_info, 'player')
    check("[D] 正常包内插件仍能加载并注册",
          'probe_pack_ok' in SCRIPTS and api.info['id'] == 'probe.packok')
    _cleanup()


# ====================================================================
# E 组: 失败后修好 entry -> rescan 能正常加载 (不残留"中毒"状态)
# ====================================================================
def t_fix_then_rescan():
    _cleanup()
    tmp = tempfile.mkdtemp()
    _plugin(tmp, 'fixme', 'probe.fixme', ENTRY_HALF)
    r1 = plugin_loader.load_plugins(base=tmp)
    check("[E] 第一次加载失败", r1['loaded'] == [] and r1['broken'])
    _plugin(tmp, 'fixme', 'probe.fixme', ENTRY_FIXED_OK)      # 用户修好 entry.py
    r2 = plugin_loader.load_plugins(base=tmp)
    check("[E] 修好后 rescan 正常加载 + 注册",
          r2['loaded'] == ['probe.fixme'] and 'probe_fixed' in SCRIPTS, r2)
    check("[E] 之前失败插件的残留仍未复活",
          'probe_half_sid' not in SCRIPTS)
    _cleanup()


if __name__ == "__main__":
    print("========== 插件注册事务化 / id 所有权 (scan_09 P-04/P-05) ==========")
    _cleanup()
    t_rollback_partial()
    t_rollback_keeps_others()
    t_conflict_builtin()
    t_conflict_between_plugins()
    t_unload_only_own()
    t_pack_rollback()
    t_fix_then_rescan()
    _cleanup()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
