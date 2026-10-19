# -*- coding: utf-8 -*-
"""smoke_stable_guid.py — P0-3 稳定 ID / GUID 寻址冒烟

背景 (缺陷报告 P0-3):
  - object_list/create 不返回 id
  - name_or_id 不支持 GUID
  - 重名静默改名但返回成功

本冒烟用 mock 编辑器验证修复：
  A) _find_all 支持 guid 精确匹配
  B) cmd_object_add 返回 guid
  C) cmd_object_list 每项带 guid
  D) cmd_object_rename 冲突时返回 error 而非假成功
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

import agent_commands as ac

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ============ Mock 对象 ============
class _MockObj:
    def __init__(self, name, guid, kind='model'):
        self.name = name
        self.guid = guid
        self.kind = kind
        self.parent = None

    def __repr__(self):
        return 'Obj(%s,%s)' % (self.name, self.guid)


class _MockEditor:
    def __init__(self):
        self.models = []
        self.lights = []
        self.cameras = []
        self._renamed_to = None   # 模拟 rename 成功时设为新名

    def _selected(self):
        return self.models[0] if self.models else None

    def _selected_light(self):
        return None

    def _selected_camera(self):
        return None

    def rename(self, m, new, old):
        # 模拟 P0-3 修复前的行为：重名时只静默返回不改名
        if any(o is not m and o.name == new for o in self.models):
            return  # 静默失败（不抛异常）
        m.name = new

    def _add_primitive(self, typ):
        # 模拟修复后的返回 model
        m = _MockObj(name='%s%d' % (typ, len(self.models) + 1),
                     guid='guid_%d_%s' % (len(self.models), typ))
        self.models.append(m)
        return m


class _MockWin:
    def __init__(self):
        self.editor = _MockEditor()


# ============ A) _find_all 支持 guid ============
ed = _MockEditor()
o1 = _MockObj('crate', 'abc123')
o2 = _MockObj('crate', 'def456')   # 重名不同 guid
ed.models = [o1, o2]

hits = ac._find_all(ed, 'abc123')
check('A1) 按 guid 精确命中唯一 1 个', len(hits) == 1, hits)
if hits:
    check('A2) 命中的是 guid 对应的对象', hits[0][1] is o1)

hits2 = ac._find_all(ed, 'crate')
check('A3) 按 name 命中全部同名 2 个', len(hits2) == 2, hits2)

hits3 = ac._find_all(ed, 'nonexistent')
check('A4) 不存在的 guid/name 返回空', len(hits3) == 0)


# ============ B) cmd_object_add 返回 guid ============
win = _MockWin()
r = ac.cmd_object_add(win, {'type': 'cube'})
check('B1) object_add 返回 dict', isinstance(r, dict), r)
check('B2) 含 guid 字段', 'guid' in r and r['guid'], r)
check('B3) 含 name 字段', 'name' in r and r['name'], r)
check('B4) guid 与模型上的 guid 一致',
      r.get('guid') == win.editor.models[-1].guid, r)


# ============ C) cmd_object_list 带 guid ============
win2 = _MockWin()
win2.editor.models = [_MockObj('a', 'g1'), _MockObj('b', 'g2')]
rl = ac.cmd_object_list(win2, {})
check('C1) object_list 返回 models', 'models' in rl, rl.get('selected'))
check('C2) 每项带 guid',
      all('guid' in m for m in rl['models']),
      [m.get('guid') for m in rl['models']])
check('C3) guid 值正确',
      [m['guid'] for m in rl['models']] == ['g1', 'g2'],
      [m['guid'] for m in rl['models']])


# ============ D) cmd_object_rename 冲突如实返回 ============
win3 = _MockWin()
win3.editor.models = [_MockObj('crate', 'g1'), _MockObj('barrel', 'g2')]

# 成功改名
r_ok = ac.cmd_object_rename(win3, {'name': 'g1', 'new': 'crate_new'})
check('D1) 成功改名返回 renamed', 'renamed' in r_ok, r_ok)
check('D2) actual == 请求的新名',
      r_ok.get('actual') == 'crate_new', r_ok)
check('D3) 返回 guid', r_ok.get('guid') == 'g1', r_ok)

# 冲突改名（新名与现有 barrel 重名）
r_conflict = ac.cmd_object_rename(win3, {'name': 'crate_new', 'new': 'barrel'})
check('D4) 冲突改名返回 error（不再假成功）',
      'error' in r_conflict, r_conflict)
check('D5) 冲突时 actual 保持原名',
      r_conflict.get('actual') == 'crate_new', r_conflict)


# ============ 汇总 ============
print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
