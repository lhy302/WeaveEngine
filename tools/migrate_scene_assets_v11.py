# -*- coding: utf-8 -*-
"""migrate_scene_assets_v11.py — 一次性迁移：场景里的旧路径引用 -> 项目 Assets guid。

背景 (beta6 B1): v11 起场景只写资产 guid；旧场景里是
  sceneio.skybox / cameras[].skybox  = {"paths": [6 个相对路径]}
  materials[].albedo / normal_map    = {"path": 绝对路径, ...}
  materials[].env_map                = {"paths": [6 个绝对路径]}
本脚本把这些"路径引用"登记进 <场景目录>/Assets/assets.json，并把场景改写成 guid 引用。

用法:
  python tools/migrate_scene_assets_v11.py                # 默认扫 examples / Projects / docs/audit
  python tools/migrate_scene_assets_v11.py 某场景.json --dry-run --report 迁移报告.json
  python tools/migrate_scene_assets_v11.py --no-create    # 只迁已有项目（不新建 Assets/）

约定:
  · 只跑一次：跑完即删（仓库开发期"不新增兼容负担"约定）。加载侧仍保留
    一个 beta 周期的旧路径 fallback（读到旧字段会告警，见 sceneio._apply_material_texture）。
  · 不碰模型 obj 引用（params.obj）—— 模型子资源在 B2 批次处理。
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOOM = os.path.join(ROOT, 'Loom')
sys.path.insert(0, LOOM)

import sceneio  # noqa: E402
import loom_assets  # noqa: E402

TEXTURE_KEYS = ('mipmaps', 'wrap', 'filter_mode', 'aniso', 'max_size', 'compression')


def _scene_root(scene_path):
    return os.path.dirname(os.path.abspath(scene_path))


def _abs(base, p):
    p = str(p)
    return p if os.path.isabs(p) else os.path.join(base, p)


def migrate_scene(scene_path, dry_run=False, create=True):
    """单场景迁移 -> 报告 dict。"""
    scene_path = os.path.abspath(scene_path)
    rep = {'scene': scene_path, 'changed': 0, 'failures': [], 'skipped': [],
           'version_before': None, 'version_after': None, 'dry_run': bool(dry_run)}
    data = sceneio.load_scene_data(scene_path)
    if not isinstance(data, dict):
        rep['failures'].append('场景读不出/不是对象')
        return rep
    rep['version_before'] = data.get('version')
    root = _scene_root(scene_path)
    ctx = loom_assets.AssetContext.for_dir(root, create=(create and not dry_run))
    if ctx is None:
        rep['failures'].append('无法打开/创建项目资产库（可用 --no-create 只迁已有项目）')
        return rep

    def conv_cubemap(ref, where):
        if not isinstance(ref, dict) or not ref:
            return ref, False
        g = ref.get('guid')
        if isinstance(g, str) and g and ctx.owns(g, 'cubemap'):
            return ref, False
        paths = ref.get('paths')
        if not paths:
            return ref, False           # 纯色 cubemap: 无需迁移
        if len(paths) != 6:
            rep['failures'].append('%s: 六面图路径不是 6 个 (%d)' % (where, len(paths)))
            return ref, False
        abses = [_abs(root, p) for p in paths]
        guid, created, why = ctx.import_cubemap(abses, name=ref.get('name'))
        if guid is None:
            rep['failures'].append('%s: %s' % (where, why))
            return ref, False
        return {'guid': guid, 'name': ref.get('name')}, True

    n = 0
    for field, where in (('skybox', 'skybox'),):
        if field in data:
            new, ch = conv_cubemap(data.get(field), where)
            if ch:
                data[field] = new
                n += 1
    for i, cam in enumerate(data.get('cameras') or []):
        if isinstance(cam, dict) and cam.get('skybox'):
            new, ch = conv_cubemap(cam.get('skybox'), 'cameras[%d].skybox' % i)
            if ch:
                cam['skybox'] = new
                n += 1
    for mi, mat in enumerate(data.get('materials') or []):
        if not isinstance(mat, dict):
            continue
        for slot in ('albedo', 'normal_map'):
            ref = mat.get(slot)
            if not isinstance(ref, dict) or not ref:
                continue
            g = ref.get('guid')
            if isinstance(g, str) and g and ctx.owns(g, 'texture'):
                continue
            p = ref.get('path')
            if not p:
                continue
            src = _abs(root, p)
            if not os.path.isfile(src):
                rep['failures'].append('materials[%d].%s: 源图不存在 %s' % (mi, slot, src))
                continue
            imp = {k: ref[k] for k in TEXTURE_KEYS if k in ref}
            guid, created, why = ctx.import_texture(
                src, name=ref.get('name'), import_settings=imp,
                guid=(g if isinstance(g, str) and g else None))
            if guid is None:
                rep['failures'].append('materials[%d].%s: %s' % (mi, slot, why))
                continue
            mat[slot] = {'guid': guid, 'name': ref.get('name')}
            n += 1
        env = mat.get('env_map')
        if isinstance(env, dict) and env:
            new, ch = conv_cubemap(env, 'materials[%d].env_map' % mi)
            if ch:
                mat['env_map'] = new
                n += 1
    for oi, obj in enumerate(data.get('objects') or []):
        params = (obj or {}).get('params') if isinstance(obj, dict) else None
        if isinstance(params, dict) and params.get('obj'):
            rep['skipped'].append('objects[%d].params.obj（模型引用留到 B2）' % oi)

    data = sceneio.migrate(data)        # 版本升到 11（纯函数）
    rep['version_after'] = data.get('version')
    rep['changed'] = n
    if n and not dry_run:
        sceneio.save_json_atomic(scene_path, data)
    return rep


def _default_targets():
    out = []
    for d in (os.path.join(ROOT, 'examples'),
              os.path.join(LOOM, 'Projects'),
              os.path.join(ROOT, 'docs', 'audit')):
        if os.path.isdir(d):
            out.extend(sorted(glob.glob(os.path.join(d, '*.json'))))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-create', action='store_true')
    ap.add_argument('--report', default=None)
    a = ap.parse_args(argv)
    targets = a.paths or _default_targets()
    reports = []
    total = 0
    for t in targets:
        rep = migrate_scene(t, dry_run=a.dry_run, create=not a.no_create)
        reports.append(rep)
        total += rep['changed']
        print('[迁移] %s -> 改动 %d, 失败 %d%s' %
              (os.path.relpath(t, ROOT), rep['changed'], len(rep['failures']),
               ' (dry-run)' if a.dry_run else ''))
        for f in rep['failures'][:5]:
            print('        失败:', f)
    print('[迁移] 合计 %d 个文件, %d 处引用%s' %
          (len(reports), total, ' (dry-run, 未写盘)' if a.dry_run else ''))
    if a.report:
        with open(a.report, 'w', encoding='utf-8') as f:
            json.dump(reports, f, ensure_ascii=False, indent=2)
        print('[迁移] 报告:', a.report)
    bad = sum(1 for r in reports if r['failures'])
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
