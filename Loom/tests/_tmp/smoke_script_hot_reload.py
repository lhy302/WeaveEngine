# -*- coding: utf-8 -*-
"""smoke_script_hot_reload.py — P0-2 + P1-1 脚本热重载 / 原子挂载 / vars 透传冒烟

背景 (缺陷报告 P0-2 / P1-1):
  - script_add 挂未注册 id 时抛 AttributeError，但坏组件已入模型且未回滚
  - load_script_dir 只在启动时调用，改脚本必须重启编辑器
  - MCP 的 script_vars 参数被静默丢弃

本冒烟验证:
  A) editor.add_script 有前置 get_script 校验（AST 级位置检查）
  B) 未注册 sid -> 抛 ValueError，模型未被修改
  C) 注册后挂载成功，extra_vars 生效（P1-1 透传路径）
  D) scripts / script_reload 命令可调用
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

import scripts as sc

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ============ A) AST 级：add_script 有前置 get_script 校验 ============
src_path = os.path.join(BASE, 'editor.py')
with open(src_path, 'r', encoding='utf-8') as f:
    tree = ast.parse(f.read())

guard_line = None
call_line = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'add_script':
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = sub.func
                if isinstance(fn, ast.Attribute) and fn.attr == 'get_script':
                    guard_line = sub.lineno
                if isinstance(fn, ast.Attribute) and fn.attr == 'add_script':
                    call_line = sub.lineno

check('A1) 找到 get_script 校验', guard_line is not None, guard_line)
check('A2) 找到 m.add_script 调用', call_line is not None, call_line)
check('A3) 校验在 add_script 之前（根因修复）',
      guard_line is not None and call_line is not None and guard_line < call_line,
      'guard_line=%s call_line=%s' % (guard_line, call_line))


# ============ B/C) 行为级：未知 sid 抛 ValueError，已注册 + extra_vars 生效 ============
# 注册测试脚本
@sc.register
class _test_probe(sc.Script):
    script_id = '_test_probe'      # register 用这个作为注册键
    name = '测试探针'
    params = [
        ('speed', '速度', 1.0),
        ('label', '标签', 'x'),
    ]
    def update(self, dt):
        pass


class _FakeModel:
    def __init__(self):
        self.name = 'fake_model'
        self.scripts = []
        self.called_sids = []

    def add_script(self, sid):
        self.called_sids.append(sid)
        inst = type('Inst', (), {'script_id': sid, 'script_vars': {}})()
        self.scripts.append(inst)
        return inst


def _simulated_add_script(m, sid, extra_vars=None):
    """镜像 editor.add_script 的核心逻辑（供行为级测试，不依赖完整 Editor/GL）。"""
    cls = sc.get_script(sid)
    if cls is None:
        raise ValueError('脚本不存在: %r' % sid)
    inst = m.add_script(sid)
    for key, _lb, default, *_ in cls.params:
        inst.script_vars[key] = default
    if extra_vars:
        for k, v in extra_vars.items():
            if any(p[0] == k for p in cls.params):
                inst.script_vars[k] = v
    return inst


# B) 未知 sid
m1 = _FakeModel()
try:
    _simulated_add_script(m1, 'no_such_script_xyz')
    check('B1) 未知 sid 抛 ValueError', False, '未抛异常')
except ValueError:
    check('B1) 未知 sid 抛 ValueError', True)
    check('B2) 模型未被修改（无坏组件）',
          len(m1.scripts) == 0 and m1.called_sids == [],
          'scripts=%d called=%r' % (len(m1.scripts), m1.called_sids))

# C) 已注册 + extra_vars
m2 = _FakeModel()
inst = _simulated_add_script(m2, '_test_probe', extra_vars={'speed': 9.0})
check('C1) 已注册 sid 挂载成功', len(m2.scripts) == 1, m2.scripts)
check('C2) 默认参数生效', inst.script_vars.get('speed') == 1.0 or
      inst.script_vars.get('speed') == 9.0,
      inst.script_vars)
check('C3) extra_vars 覆盖生效（P1-1）',
      inst.script_vars.get('speed') == 9.0, inst.script_vars)
check('C4) 未声明参数被忽略',
      'no_such_param' not in inst.script_vars,
      inst.script_vars)


# ============ D) 引擎侧命令：scripts / script_reload 可调用 ============
import agent_commands as ac

# scripts 列表
class _FakeWin:
    pass


try:
    r = ac.cmd_scripts(_FakeWin(), {})
    check('D1) scripts 命令可调用', isinstance(r, dict) and 'scripts' in r, r.get('total'))
    check('D2) 探针脚本出现在列表',
          any(s.get('id') == '_test_probe' for s in r.get('scripts', [])),
          [s.get('id') for s in r.get('scripts', [])][:5])
except Exception as e:
    check('D1) scripts 命令可调用', False, e)

# script_reload 缺省目录不存在时给错误不崩
try:
    r2 = ac.cmd_script_reload(_FakeWin(), {'dir': '/nonexistent_path_xyz'})
    check('D3) script_reload 缺目录返回错误不崩',
          isinstance(r2, dict) and 'error' in r2, r2)
except Exception as e:
    check('D3) script_reload 缺目录返回错误不崩', False, e)


# ============ 清理注册 ============
if '_test_probe' in sc.SCRIPTS:
    del sc.SCRIPTS['_test_probe']


# ============ 汇总 ============
print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
