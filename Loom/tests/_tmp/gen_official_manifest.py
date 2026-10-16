# -*- coding: utf-8 -*-
r"""gen_official_manifest.py — 从 registry.json 生成 official_manifest.py (A1).

职责: 把 registry.json 中 official=true 的条目的 (module_id, path, sha256)
写进 core_components/official_manifest.py (Python 常量模块, 编译后进 exe).

调用时机: build_all.bat 在 refresh_registry_sha.py 之后.
幂等: 连续两次运行, 第二次内容不变 (除生成时间戳).

与 refresh_registry_sha.py 的差异:
  · refresh 回填 registry.json (磁盘, 允许改) — 面向外部件信任闸
  · 本脚本生成 official_manifest.py (编译进 exe) — 面向官方件不可篡改基准

退出码: 0 = 成功; 1 = 失败 (registry 缺失 / 结构错 / 写失败).
"""
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(os.path.dirname(HERE))   # tests/_tmp -> tests -> ROOT


def load_json_ordered(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f, object_pairs_hook=collections.OrderedDict)


def main(argv=None):
    root = os.path.abspath(argv[0]) if argv else DEFAULT_ROOT
    reg_path = os.path.join(root, 'core_components', 'registry.json')
    out_path = os.path.join(root, 'core_components', 'official_manifest.py')
    if not os.path.isfile(reg_path):
        print('ERROR: registry.json 不存在: %s' % reg_path)
        return 1
    try:
        data = load_json_ordered(reg_path)
    except Exception as ex:
        print('ERROR: registry.json 解析失败: %r' % (ex,))
        return 1
    comps = data.get('components')
    if not isinstance(comps, list):
        print('ERROR: registry.json 缺 components 列表')
        return 1

    entries = []
    for c in comps:
        if not isinstance(c, dict):
            continue
        if not bool(c.get('official')):
            continue
        mid = c.get('module_id')
        path = c.get('path')
        sha = (c.get('sha256') or '').strip().lower()
        if not mid or not path or not sha:
            print('ERROR: 官方件 %r 缺 module_id/path/sha256' % (mid,))
            return 1
        entries.append((mid, path, sha))

    ts = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    lines = []
    lines.append('# -*- coding: utf-8 -*-')
    lines.append('"""official_manifest.py — 官方件出厂哈希基准 (编译进 exe, 外部改不动).')
    lines.append('')
    lines.append('本文件由 tests/_tmp/gen_official_manifest.py 从 core_components/registry.json')
    lines.append('自动生成 (build_all.bat 在 refresh_registry_sha.py 之后调用). 请勿手改.')
    lines.append('')
    lines.append('作用: 与 registry.json (磁盘, 可改) 职责分离 ——')
    lines.append('  · registry.json  = 花名册 (有哪些组件/装哪/启用否; 允许改, 装配灵活性来源)')
    lines.append('  · 本文件          = 出厂基准 (官方件应有的 SHA256; 编译进 exe 外部改不动)')
    lines.append('在 module_registry.assemble() 起始处校验: 官方件实际 SHA256 与基准不符 = 报警拒载.')
    lines.append('')
    lines.append('LOOM_DEV=1 时跳过校验 (开发期天天重编, SHA 一直在变).')
    lines.append('"""')
    lines.append('# 生成时间: %s' % ts)
    lines.append('OFFICIAL_MANIFEST = {')
    for mid, path, sha in entries:
        lines.append('    %r: {' % mid)
        lines.append('        "path": %r,' % path)
        lines.append('        "sha256": %r,' % sha)
        lines.append('    },')
    lines.append('}')
    text = '\n'.join(lines) + '\n'

    try:
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
    except Exception as ex:
        print('ERROR: 写 %s 失败: %r' % (out_path, ex))
        return 1

    print('gen_official_manifest: %d 官方件写入 %s' % (len(entries), out_path))
    for mid, path, sha in entries:
        print('  %-12s %-40s %s' % (mid, path, sha[:16]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
