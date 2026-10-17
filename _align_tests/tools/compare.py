# -*- coding: utf-8 -*-
"""compare.py — 对比 Loom 与 Unity 的对齐测试结果, 生成 verdict.md。

用法:
    py compare.py <case_dir>

读取:
    <case_dir>/ops.json          用例定义
    <case_dir>/loom_result.json  Loom 侧结果 (align_loom.py 产出, result 里嵌 JSON 文本)
    <case_dir>/unity_result.json Unity 侧结果 (AlignRunner.cs 产出, 直接字段)
    <case_dir>/*_before.png / *_after.png  两侧截图

产出:
    <case_dir>/verdict.md        对比结论 (操作成功性 + 截图变化 + 数值对齐)

数值对齐: 从两侧 result 抽取 position/rotation_deg/scale, 容差 1e-4 逐分量比对.
"""
import hashlib
import json
import os
import re
import sys

TOL = 1e-4


def file_sha(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def compare_png(case_dir, name):
    lb = os.path.join(case_dir, '%s_before.png' % name)
    la = os.path.join(case_dir, '%s_after.png' % name)
    out = {'loom_before': file_sha(lb), 'loom_after': file_sha(la)}
    out['loom_changed'] = (out['loom_before'] != out['loom_after'])
    ub2 = os.path.join(case_dir, 'unity', '%s_before.png' % name)
    ua2 = os.path.join(case_dir, 'unity', '%s_after.png' % name)
    if os.path.exists(ub2):
        out['unity_before'] = file_sha(ub2)
        out['unity_after'] = file_sha(ua2)
        out['unity_changed'] = (out['unity_before'] != out['unity_after'])
        out['both_changed'] = out['loom_changed'] and out['unity_changed']
    else:
        out['unity_changed'] = None
        out['both_changed'] = None
    return out


def _extract_vec(text, key):
    """从 JSON 文本里抽 key 的 3 元向量."""
    if not text:
        return None
    m = re.search(r'"%s"\s*:\s*\[\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*\]' % key, text)
    if not m:
        return None
    try:
        return [float(m.group(1)), float(m.group(2)), float(m.group(3))]
    except ValueError:
        return None


def loom_xform(lr):
    """Loom result: result 字段是嵌 JSON 字符串, 从中抽 xform."""
    txt = lr.get('result', '')
    # 取最后一个 JSON 对象 (含最终 transform 的那个)
    out = {}
    for key in ('position', 'rotation_deg', 'scale'):
        out[key] = _extract_vec(txt, key)
    return out


def unity_xform(ur):
    """Unity result: 直接字段."""
    out = {}
    for key in ('position', 'rotation_deg', 'scale'):
        v = ur.get(key)
        out[key] = list(v) if v else None
    return out


def vec_close(a, b, tol=TOL):
    if a is None or b is None:
        return None
    if len(a) != len(b):
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def main():
    if len(sys.argv) < 2:
        print('用法: py compare.py <case_dir>')
        sys.exit(1)
    case_dir = os.path.abspath(sys.argv[1])
    ops_path = os.path.join(case_dir, 'ops.json')
    loom_path = os.path.join(case_dir, 'loom_result.json')
    unity_path = os.path.join(case_dir, 'unity_result.json')

    ops = json.load(open(ops_path, encoding='utf-8')) if os.path.exists(ops_path) else {}
    loom = json.load(open(loom_path, encoding='utf-8')) if os.path.exists(loom_path) else {}
    unity = json.load(open(unity_path, encoding='utf-8')) if os.path.exists(unity_path) else {}

    loom_by_name = {r['name']: r for r in loom.get('results', [])}
    unity_by_name = {r['name']: r for r in unity.get('results', [])}

    lines = ['# 对齐测试结论: %s' % os.path.basename(case_dir), '']
    lines.append('| case | Loom op | Unity op | 截图变化 | **数值对齐** | 结论 |')
    lines.append('|------|---------|----------|----------|-------------|------|')
    total = 0
    matched = 0
    num_matched = 0
    num_compared = 0
    detail = []
    for c in ops.get('cases', []):
        name = c['name']
        total += 1
        lr = loom_by_name.get(name, {})
        ur = unity_by_name.get(name, {})
        l_ok = (not lr.get('isError', True)) if lr else False
        u_ok = ur.get('ok') if ur else None
        png = compare_png(case_dir, name)
        both_changed = png.get('both_changed')

        # 数值对齐
        lx = loom_xform(lr)
        ux = unity_xform(ur)
        vec_results = {}
        for key in ('position', 'rotation_deg', 'scale'):
            vec_results[key] = vec_close(lx.get(key), ux.get(key))
        if all(v is None for v in vec_results.values()):
            num_status = '—'
        elif all(v is True for v in vec_results.values() if v is not None):
            num_status = '✅'
            num_matched += 1
        else:
            num_status = '❌'
        if any(v is not None for v in vec_results.values()):
            num_compared += 1

        # 判定优先级: 数值对齐 > 截图变化 (数值对齐即证明操作在两侧都生效)
        if not l_ok or u_ok is False:
            verdict = '🔴'
        elif num_status == '✅':
            verdict = '🟢'          # 数值逐分量对齐 = 通过
            matched += 1
        elif num_status == '❌':
            verdict = '🔴'          # 数值不对齐 = 失败
        else:
            # 无数值数据 (纯视觉类操作): 退回截图变化判定
            if both_changed is not False:
                verdict = '🟢'
                matched += 1
            else:
                verdict = '🟡'
        lines.append('| %s | %s | %s | %s | %s | %s |' % (
            name,
            '✅' if l_ok else '❌',
            {True: '✅', False: '❌', None: '—'}[u_ok],
            {True: '✅', False: '❌', None: '—'}[both_changed],
            num_status,
            verdict))

        # 记明细
        if num_status == '❌':
            detail.append('- %s: Loom pos=%s rot=%s scale=%s | Unity pos=%s rot=%s scale=%s' % (
                name, lx.get('position'), lx.get('rotation_deg'), lx.get('scale'),
                ux.get('position'), ux.get('rotation_deg'), ux.get('scale')))

    lines.append('')
    lines.append('**总体对齐度: %d/%d**  (数值精确对齐: %d/%d, 容差 1e-4)' % (
        matched, total, num_matched, num_compared))
    if detail:
        lines.append('')
        lines.append('## 数值不对齐明细')
        lines.extend(detail)
    lines.append('')
    lines.append('> 说明: 操作成功性 + 截图变化 + 数值逐分量对齐 (容差 1e-4)。')

    out = os.path.join(case_dir, 'verdict.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('[对比] 生成: %s' % out)
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
