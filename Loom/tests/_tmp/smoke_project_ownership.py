# -*- coding: utf-8 -*-
"""项目归属模型冒烟（2026-10-19 A2+B2+C3+D1）"""
import os, sys, json, tempfile, shutil
ROOT = r'D:\my-project - 副本\Loom(py源代码-工作区)'
HUB = os.path.join(ROOT, 'LoomHub')
sys.path.insert(0, HUB)
sys.path.insert(0, os.path.join(ROOT, 'Loom'))
os.chdir(HUB)

import hub_config as cfg

fails = []
def check(label, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + label + (('  ' + str(detail)) if detail else ''))
    if not cond: fails.append(label)

print('=== Part A: infer_engine_dir ===')
check('A1 Projects/ 路径推断',
      cfg.infer_engine_dir(r'D:\engines\Loom\0.1.0\Projects\a.json')
      == r'D:\engines\Loom\0.1.0')
check('A2 保存/ 路径推断（兼容）',
      cfg.infer_engine_dir(r'D:\engines\Loom\0.1.0\保存\a.json')
      == r'D:\engines\Loom\0.1.0')
check('A3 外部路径返回 None',
      cfg.infer_engine_dir(r'D:\my stuff\proj\a.json') is None)
check('A4 空值返回 None', cfg.infer_engine_dir(None) is None)
check('A5 相对路径无 Projects 返回 None',
      cfg.infer_engine_dir('a.json') is None)

print()
print('=== Part B: add_project 带 engine_dir ===')
tmp = tempfile.mkdtemp()
try:
    # monkey-patch projects 文件路径
    orig_proj = cfg.PROJECTS_FILE
    test_proj = os.path.join(tmp, 'projects.json')
    cfg.PROJECTS_FILE = test_proj
    # 清空
    cfg.save_projects([])

    # 显式 engine_dir
    cfg.add_project('p1', r'D:\eng\Loom\0.1\Projects\p1.json',
                    engine_dir=r'D:\eng\Loom\0.1')
    lst = cfg.load_projects()
    check('B1 显式 engine_dir 保存',
          lst[0].get('engine_dir') == r'D:\eng\Loom\0.1', lst[0].get('engine_dir'))

    # 自动推断
    cfg.add_project('p2', r'D:\eng\Loom\0.2\Projects\p2.json')
    lst = cfg.load_projects()
    p2 = [x for x in lst if x['name'] == 'p2'][0]
    check('B2 自动推断 engine_dir',
          p2.get('engine_dir') == r'D:\eng\Loom\0.2', p2.get('engine_dir'))

    # 外部项目
    cfg.add_project('ext', r'D:\random\ext.json')
    lst = cfg.load_projects()
    ext = [x for x in lst if x['name'] == 'ext'][0]
    check('B3 外部项目 engine_dir=None', ext.get('engine_dir') is None)

    cfg.PROJECTS_FILE = orig_proj
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print('=== Part C: scan_save_dir_projects 双目录扫描 ===')
tmp = tempfile.mkdtemp()
try:
    eng = os.path.join(tmp, 'engine')
    os.makedirs(os.path.join(eng, 'Projects'), exist_ok=True)
    os.makedirs(os.path.join(eng, '保存'), exist_ok=True)
    # 各造一个场景
    with open(os.path.join(eng, 'Projects', 'new.json'), 'w', encoding='utf-8') as f:
        f.write('{}')
    with open(os.path.join(eng, '保存', 'old.json'), 'w', encoding='utf-8') as f:
        f.write('{}')

    orig_proj = cfg.PROJECTS_FILE
    cfg.PROJECTS_FILE = os.path.join(tmp, 'projects.json')
    cfg.save_projects([])
    found = cfg.scan_save_dir_projects(engine_dir=eng)
    names = sorted(n for n, _ in found)
    check('C1 同时扫 Projects/ 和 保存/', names == ['new', 'old'], names)
    # 检查 engine_dir 归属
    lst = cfg.load_projects()
    all_eng = all(x.get('engine_dir') == eng for x in lst)
    check('C2 两个项目都归属到同一引擎', all_eng,
          [(x['name'], x.get('engine_dir')) for x in lst])
    cfg.PROJECTS_FILE = orig_proj
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print('=== Part D: interpreter_save_dir ===')
tmp = tempfile.mkdtemp()
try:
    orig_proj = cfg.PROJECTS_FILE
    orig_interp = cfg.INTERPRETERS_FILE
    cfg.INTERPRETERS_FILE = os.path.join(tmp, 'i.json')
    cfg.PROJECTS_FILE = os.path.join(tmp, 'p.json')
    info = {'name': 'Loom', 'version': '0.1.0', 'kind': 'py',
            'dir': tmp, 'main': 'Loom.py', 'main_py': 'Loom.py',
            'path': 'Loom.py', 'main_exe': 'Loom.exe'}
    cfg.save_interpreters([info])
    sd = cfg.interpreter_save_dir(info)
    check('D1 save_dir 以 Projects 结尾',
          sd.endswith('Projects'), sd)
    lsd = cfg.interpreter_legacy_save_dir(info)
    check('D2 legacy_save_dir 以 保存 结尾',
          lsd.endswith('保存'), lsd)
    cfg.PROJECTS_FILE = orig_proj
    cfg.INTERPRETERS_FILE = orig_interp
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print('FAILED %d 项: %s' % (len(fails), fails))
    sys.exit(1)
else:
    print('ALL PASS')
