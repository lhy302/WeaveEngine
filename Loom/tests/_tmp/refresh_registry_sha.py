# -*- coding: utf-8 -*-
r"""refresh_registry_sha.py — registry.json sha256 回填工具 (M2b, 2026-09-08)

背景 (审计 P13):
    core_components\registry.json 的三个组件条目 sha256 为空串 →
    module_registry.py::_sha_gate 的语义是「空 = 放行, 非空 = 强制比对,
    不符则 AssemblyError」, 即加载器无任何完整性钉扎。本脚本把每个条目
    path 指向的真实文件 SHA256 回填进 sha256 字段, 让钉扎生效。

前置:
    DLL 必须已用 /Brepro 重编 (可复现构建), 否则每次重编 PE 时间戳变化
    → 回填后的 sha256 立即失效 → 下次 assemble 会 AssemblyError。
    build_all.bat 已在 [DLL 清单] 之后、skip_checks 判断之前调用本脚本。

用法:
    py -3.12 tests\_tmp\refresh_registry_sha.py [--root <引擎根>]
    --root 默认 = 本脚本上两级目录 (tests\_tmp\..\.. = 引擎根)

行为:
    · 逐个组件解析 path 并计算该文件 SHA256 (小写十六进制), 写回 sha256 字段。
      ★path 解析口径 (实测校准, 见下方「path 基准」说明):
        ① 先按「registry.json 所在目录」为基准 (core_components\<path>);
        ② 该位置不存在时, 回退到「引擎根」为基准 (<root>\<path>), 并打印一行
           基准说明。两种基准都命不中 → ERROR 退出码 1。
    · 文件不存在 → 打印 ERROR 并以退出码 1 结束 (绝不写回半截结果)。
    · 保持 JSON 结构 / 键顺序 / 其他字段不变; 写回 indent=2,
      ensure_ascii=False, 末尾保留一个换行。
    · 幂等: 连续运行两次, 第二次所有条目的新旧哈希相同。
    · 打印每条的 module_id / path / 旧 sha256 / 新 sha256,
      末尾打印 registry.json 自身的 SHA256。
退出码: 0 = 成功 (含「无需变更」), 1 = 失败 (文件缺失/JSON 坏/写回失败)。

path 基准说明 (与加载器对齐, 2026-09-08 实测):
    module_registry.py::assemble 的 base_dir 默认 = 引擎根 (_ENGINE_ROOT),
    _load_entry / _sha_gate 都用 os.path.join(self.base_dir, entry['path']),
    因此真实 registry.json 里 "core_components/module_ref.dll" 这类 path 是
    **引擎根相对**路径; 若强行按「registry.json 所在目录」拼接会得到
    core_components\core_components\module_ref.dll (不存在) → 无法回填。
    故本脚本采用「先注册表目录、再引擎根」的双基准解析: 两种布局都能正确
    回填, 且当同一 path 在两种基准下都存在时优先注册表目录并在输出中标注。
"""
import argparse
import collections
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(os.path.dirname(HERE))  # tests\_tmp -> tests -> ROOT


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_json_ordered(path):
    """读 JSON 且保持键顺序 (object_pairs_hook=OrderedDict)。"""
    with open(path, encoding='utf-8') as f:
        return json.load(f, object_pairs_hook=collections.OrderedDict)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='回填 registry.json 各组件 sha256 (M2b P13 完整性钉扎)')
    ap.add_argument('--root', default=DEFAULT_ROOT,
                    help='引擎根目录 (默认 %s)' % DEFAULT_ROOT)
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    reg_path = os.path.join(root, 'core_components', 'registry.json')
    if not os.path.isfile(reg_path):
        print('ERROR: registry.json 不存在: %s' % reg_path)
        return 1
    base_dir = os.path.dirname(reg_path)

    try:
        data = load_json_ordered(reg_path)
    except Exception as ex:
        print('ERROR: registry.json 解析失败: %s: %r' % (reg_path, ex))
        return 1

    comps = data.get('components')
    if not isinstance(comps, list):
        print('ERROR: registry.json 缺 components 列表: %s' % reg_path)
        return 1

    reg_sha_before = file_sha256(reg_path)
    print('registry.json : %s' % reg_path)
    print('引擎根 --root : %s' % root)
    print('条目数        : %d' % len(comps))
    print('-' * 78)
    print('%-14s %-40s %-12s %s' % ('module_id', 'path', '旧 sha256', '新 sha256'))
    print('-' * 78)

    changed = 0
    for i, ent in enumerate(comps):
        if not isinstance(ent, dict):
            print('ERROR: components[%d] 不是对象: %r' % (i, ent))
            return 1
        mid = ent.get('module_id', '<缺 module_id>')
        rel = ent.get('path')
        if not rel:
            print('ERROR: 条目 %s 缺 path 字段' % mid)
            return 1
        rel_n = str(rel).replace('/', os.sep)
        cand_reg = os.path.join(base_dir, rel_n)   # 基准①: registry.json 所在目录
        cand_root = os.path.join(root, rel_n)      # 基准②: 引擎根 (与加载器一致)
        if os.path.isfile(cand_reg):
            target, base_tag = cand_reg, 'registry目录'
        elif os.path.isfile(cand_root):
            target, base_tag = cand_root, '引擎根'
        else:
            print('ERROR: 条目 %s 的文件不存在: 试过 %s | %s'
                  % (mid, cand_reg, cand_root))
            return 1
        new_sha = file_sha256(target)
        old_sha = ent.get('sha256', '')
        old_show = old_sha if old_sha else '(空)'
        print('%-14s %-40s %-12s %s  [基准=%s]'
              % (mid, str(rel), old_show[:12], new_sha, base_tag))
        if old_sha != new_sha:
            changed += 1
        ent['sha256'] = new_sha

    text = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    try:
        with open(reg_path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
    except Exception as ex:
        print('ERROR: 写回失败: %s: %r' % (reg_path, ex))
        return 1

    reg_sha_after = file_sha256(reg_path)
    print('-' * 78)
    print('变更条目数    : %d / %d' % (changed, len(comps)))
    print('registry.json 自身 SHA256 (写回前): %s' % reg_sha_before)
    print('registry.json 自身 SHA256 (写回后): %s' % reg_sha_after)
    print('OK refresh_registry_sha: %d 条目已钉扎' % len(comps))
    return 0


if __name__ == '__main__':
    sys.exit(main())
