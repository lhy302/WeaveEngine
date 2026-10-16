# -*- coding: utf-8 -*-
"""boot_check_check.py — A1 启动自检模块单元探针.

验证 4 场景:
  1. 正常: 所有官方件 sha 匹配 → ok=True
  2. 篡改: 临时改一个 DLL 字节 → 检出 modified → ok=False
  3. 缺失: 临时改名一个 DLL → 检出 missing → ok=False
  4. LOOM_DEV=1: 跳过校验 → ok=True

跑法: py -3.12 tests/_tmp/boot_check_check.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
os.chdir(BASE)

import boot_check
import module_registry

fails = []


def check(label, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + detail if detail else ''))
    if not cond:
        fails.append(label)


# 场景 1: 正常
reg_data = module_registry._read_registry(
    os.path.join(BASE, 'core_components', 'registry.json'))
ok, rep = boot_check.verify_official(reg_data, BASE)
ok_all = all(r['status'] == 'ok' for r in rep)
check('正常: ok=True 全部 status=ok', ok and ok_all,
      'statuses=%r' % [r['status'] for r in rep])

# 场景 2: 篡改 ckernels.dll 一个字节
target = os.path.join(BASE, 'ckernels', 'loom_kernels.dll')
bak = target + '.a1probe.bak'
shutil.copy2(target, bak)
try:
    with open(target, 'r+b') as f:
        f.seek(100)
        b = f.read(1)
        f.seek(100)
        f.write(bytes([b[0] ^ 0xFF]))
    ok2, rep2 = boot_check.verify_official(reg_data, BASE)
    mod_ck = any(r['module_id'] == 'ckernels' and r['status'] == 'modified'
                 for r in rep2)
    check('篡改: ok=False 且 ckernels=modified', (not ok2) and mod_ck,
          'ok=%s mod_ck=%s' % (ok2, mod_ck))
finally:
    shutil.move(bak, target)

# 场景 3: 缺失 pipeline.dll
target3 = os.path.join(BASE, 'core_components', 'pipeline', 'pipeline.dll')
bak3 = target3 + '.a1probe.bak'
shutil.move(target3, bak3)
try:
    ok3, rep3 = boot_check.verify_official(reg_data, BASE)
    miss_pl = any(r['module_id'] == 'pipeline' and r['status'] == 'missing'
                  for r in rep3)
    check('缺失: ok=False 且 pipeline=missing', (not ok3) and miss_pl,
          'ok=%s miss_pl=%s' % (ok3, miss_pl))
finally:
    shutil.move(bak3, target3)

# 场景 4: LOOM_DEV=1 跳过
ok4, rep4 = boot_check.verify_official(reg_data, BASE, dev_mode=True)
check('DEV: ok=True status=dev_skipped',
      ok4 and rep4 and rep4[0]['status'] == 'dev_skipped')

print('ALL PASS' if not fails else '%d FAIL: %r' % (len(fails), fails))
sys.exit(0 if not fails else 1)
