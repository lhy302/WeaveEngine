# -*- coding: utf-8 -*-
"""boot_check.py — 启动自检: 官方件 SHA256 出厂基准校验 (A1).

职责: 对 registry.json 中 official=true 的条目, 逐个计算磁盘文件 SHA256,
与编译进 exe 的 official_manifest.OFFICIAL_MANIFEST 比对.

接入点: module_registry.assemble() 在 _read_registry 之后, _sha_gate 之前调用.

失败分级 (与 docs/design/稳定性与启动自检设计.md §4 一致):
  · 官方件 SHA 不符 → status='modified' → 出厂模式报警拒载
  · 官方件缺失     → status='missing'  → 出厂模式报警拒载
  · manifest 缺失  → 报警拒载 (build_all.bat 应已生成; 开发期用 LOOM_DEV=1 覆盖)
  · LOOM_DEV=1     → 跳过校验 (开发期)

对外接口:
  verify_official(registry_data, engine_root, dev_mode=None) -> (ok, report)
    registry_data: _read_registry 返回的 dict (含 'components' 列表)
    engine_root:   引擎根目录 (拼 path 用)
    dev_mode:      None=读环境变量; True/False=显式指定
  report 每项: {'module_id', 'path', 'expected', 'actual', 'status'}
    status ∈ {'ok', 'modified', 'missing', 'manifest_missing'}
"""
import os

try:
    from module_loader import file_sha256
except ImportError:
    from .module_loader import file_sha256

try:
    from official_manifest import OFFICIAL_MANIFEST
except ImportError:
    from .official_manifest import OFFICIAL_MANIFEST


def _is_dev_mode(explicit=None):
    if explicit is not None:
        return bool(explicit)
    return os.environ.get('LOOM_DEV') == '1'


def verify_official(registry_data, engine_root, dev_mode=None):
    """校验官方件 SHA256 是否与出厂基准一致.

    返回 (ok: bool, report: list[dict]). ok=False 表示出厂模式下有 modified/missing.
    dev_mode=True 时永远返回 (True, [...status='dev_skipped'...]).
    """
    if _is_dev_mode(dev_mode):
        report = [{'module_id': '<all>', 'path': '', 'expected': '', 'actual': '',
                   'status': 'dev_skipped'}]
        return True, report

    if not OFFICIAL_MANIFEST:
        return False, [{'module_id': '<manifest>', 'path': '', 'expected': '',
                        'actual': '', 'status': 'manifest_missing'}]

    report = []
    ok = True
    comps = registry_data.get('components') or []
    for c in comps:
        if not isinstance(c, dict):
            continue
        if not bool(c.get('official')):
            continue
        mid = c.get('module_id') or '<missing_id>'
        rel = c.get('path') or ''
        entry = OFFICIAL_MANIFEST.get(mid)
        if entry is None:
            # 官方件在 manifest 里没有 → registry 与 manifest 不同步 (报警但不停)
            report.append({'module_id': mid, 'path': rel, 'expected': '',
                           'actual': '', 'status': 'manifest_missing'})
            ok = False
            continue
        abs_path = os.path.join(engine_root, rel.replace('/', os.sep))
        if not os.path.isfile(abs_path):
            report.append({'module_id': mid, 'path': rel,
                           'expected': entry['sha256'], 'actual': '',
                           'status': 'missing'})
            ok = False
            continue
        actual = file_sha256(abs_path)
        if actual != entry['sha256']:
            report.append({'module_id': mid, 'path': rel,
                           'expected': entry['sha256'], 'actual': actual,
                           'status': 'modified'})
            ok = False
        else:
            report.append({'module_id': mid, 'path': rel,
                           'expected': entry['sha256'], 'actual': actual,
                           'status': 'ok'})
    return ok, report


def format_report(report):
    """人类可读的报告文本 (启动时打印用)."""
    lines = ['[boot_check] 官方件出厂基准校验:']
    for r in report:
        st = r['status']
        if st == 'ok':
            lines.append('  [OK]   %-12s %s' % (r['module_id'], r['path']))
        elif st == 'modified':
            lines.append('  [MODIFIED] %-12s %s\n             期望 %s\n             实际 %s'
                         % (r['module_id'], r['path'],
                            r['expected'][:16], r['actual'][:16]))
        elif st == 'missing':
            lines.append('  [MISSING]  %-12s %s' % (r['module_id'], r['path']))
        elif st == 'manifest_missing':
            lines.append('  [MANIFEST-MISSING] %-12s %s' % (r['module_id'], r['path']))
        elif st == 'dev_skipped':
            lines.append('  [DEV]  LOOM_DEV=1, 跳过校验')
    return '\n'.join(lines)
