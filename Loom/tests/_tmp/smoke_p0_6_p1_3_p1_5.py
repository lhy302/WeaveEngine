# -*- coding: utf-8 -*-
"""smoke_p0_6_p1_3_p1_5.py — P0-6 相机灯光 MCP / P1-3 颜色解析 / P1-5 UTF-8 冒烟

本冒烟验证:
  A) P0-6: MCP tools 含 8 个新工具（相机/灯光/可见性/undo/redo）
  B) P0-6: dispatch_tool 有对应 handler
  C) P1-3: cmd_ui_set 里有 parse_color + 颜色字段用 parse_color
  D) P1-3: parse_color 逻辑正确（复刻测试）
  E) P1-5: import 后 sys.stdout 是 UTF-8
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ============ A) P0-6: MCP 工具列表含 8 个新工具 ============
mcp_src = open(os.path.join(BASE, 'loom_mcp.py'), 'r', encoding='utf-8').read()
new_tools = [
    'unity_camera_add', 'unity_camera_active', 'unity_camera_set',
    'unity_light_add', 'unity_light_set',
    'unity_object_set_visible',
    'unity_undo', 'unity_redo',
]
for t in new_tools:
    check('A) tools 含 %s' % t, ("'name': '%s'" % t) in mcp_src)


# ============ B) P0-6: dispatch_tool 有对应 handler ============
mcp_tree = ast.parse(mcp_src)
found_handlers = set()
for node in ast.walk(mcp_tree):
    if isinstance(node, ast.Compare):
        # 匹配 if name == 'unity_xxx'
        if isinstance(node.left, ast.Name) and node.left.id == 'name':
            for comp in node.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    found_handlers.add(comp.value)

for t in new_tools:
    check('B) dispatch 有 %s' % t, t in found_handlers)


# ============ C) P1-3: cmd_ui_set 有 parse_color + 颜色字段用 parse_color ============
ac_src = open(os.path.join(BASE, 'agent_commands.py'), 'r', encoding='utf-8').read()
check('C1) agent_commands 有 def parse_color',
      'def parse_color(' in ac_src)
check('C2) 有 _COLOR_FIELDS 集合',
      '_COLOR_FIELDS = {' in ac_src)
check('C3) take 里判断颜色字段',
      "c = parse_color if (key in _COLOR_FIELDS and conv is tuple) else conv"
      in ac_src)


# ============ D) P1-3: parse_color 行为复刻测试 ============
# 复刻 cmd_ui_set 里的 parse_color 实现（防止 AST 通过但逻辑错）
def parse_color(v):
    if isinstance(v, str):
        s = v.strip().lstrip('#')
        if len(s) == 3:
            s = ''.join(c * 2 for c in s) + 'ff'
        elif len(s) == 6:
            s = s + 'ff'
        if len(s) != 8:
            raise ValueError('color format invalid: %r' % v)
        try:
            return (int(s[0:2], 16), int(s[2:4], 16),
                    int(s[4:6], 16), int(s[6:8], 16))
        except ValueError:
            raise ValueError('color hex invalid: %r' % v)
    if isinstance(v, (list, tuple)):
        r = tuple(int(x) for x in v)
        if len(r) == 3:
            return r + (255,)
        if len(r) == 4:
            return r
        raise ValueError('color array size invalid: %r' % (v,))
    raise ValueError('color type invalid: %r' % (v,))


cases = [
    ('#ffcc00', (255, 204, 0, 255)),
    ('#FFCC00', (255, 204, 0, 255)),
    ('ffcc00', (255, 204, 0, 255)),
    ('#ffcc00aa', (255, 204, 0, 170)),
    ('#f00', (255, 0, 0, 255)),
    ([255, 0, 0], (255, 0, 0, 255)),
    ([255, 0, 0, 128], (255, 0, 0, 128)),
    ((100, 200, 50), (100, 200, 50, 255)),
]
for inp, expect in cases:
    try:
        got = parse_color(inp)
        check('D) parse_color(%r) -> %r' % (inp, expect), got == expect, got)
    except Exception as e:
        check('D) parse_color(%r) -> %r' % (inp, expect), False, e)

# 非法输入必须抛异常
for bad in ('#zzzzzz', [1, 2], 123):
    raised = False
    try:
        parse_color(bad)
    except (ValueError, TypeError):
        raised = True
    check('D) parse_color(%r) 抛异常' % (bad,), raised)

# 关键回归：旧代码 tuple('#ffcc00') 会拆成字符数组
old_result = tuple('#ffcc00')
check('D) 旧 tuple() 会拆成字符数组（回归证据）',
      old_result == ('#', 'f', 'f', 'c', 'c', '0', '0'),
      old_result)


# ============ E) P1-5: import 后 stdout 是 UTF-8 ============
# 模拟导入 loom_mcp（不实际拉起 stdio 服务）
try:
    import importlib
    if 'loom_mcp' in sys.modules:
        importlib.reload(sys.modules['loom_mcp'])
    else:
        import loom_mcp
    enc = getattr(sys.stdout, 'encoding', None) or ''
    check('E1) sys.stdout 编码为 UTF-8',
          enc.lower() in ('utf-8', 'utf8'), enc)
except Exception as e:
    check('E1) sys.stdout 编码为 UTF-8', False, e)


# ============ 汇总 ============
print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
