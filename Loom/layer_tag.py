# -*- coding: utf-8 -*-
"""layer_tag.py — 层与标签配置 (Layer/Tag 系统, 2026-10-18)

职责:
  - 读取/保存 <程序目录>/layer_tag.json
  - 提供默认层名 (0~7, Unity 同款) 与默认标签 (7 个, Unity 同款)
  - 损坏/缺失文件回退默认并落盘 (不阻止启动)
  - Tag 合法性校验 (长度/字符集/数量上限)

白盒契约: docs/design/LayerTag系统契约_20261018.md

设计约束:
  - 配置文件放程序目录 (与 设置.json 同级), 不放场景目录 ——
    layer/tag 是项目级概念, 所有场景共享; 场景目录可由 save_dir 改变,
    若配置跟随场景目录会导致切换后配置丢失或出现多套定义.
  - 层编号固定 0~31 (32 层位掩码), 未命名的层名为空串 (不落盘).
  - 标签 7 个内置恒在 (不可删除), 用户新增去重后追加.
  - 数量上限 1000, 长度上限 64, 字符集: 字母/数字/下划线/中文.
  - 任何异常都回退默认值, 引擎启动不受配置损坏影响.
"""
import json
import os
import re

import guiloader

MAX_TAGS = 1000
MAX_TAG_LEN = 64
MAX_LAYER_NAME_LEN = 32
LAYER_COUNT = 32

# Unity 同款默认层名 (0~7; 3/6/7 留空给用户自定义)
DEFAULT_LAYERS = {
    0: 'Default',
    1: 'TransparentFX',
    2: 'Ignore Raycast',
    4: 'Water',
    5: 'UI',
}

# Unity 同款默认标签 (7 个, 恒在)
DEFAULT_TAGS = [
    'Untagged', 'Respawn', 'Finish', 'EditorOnly',
    'MainCamera', 'Player', 'GameController',
]

# 标签字符集: 字母 / 数字 / 下划线 / 中文 (不含空格与标点)
_TAG_RE = re.compile(r'^[A-Za-z0-9_\u4e00-\u9fff]+$')


def config_path(base=None):
    """layer_tag.json 路径 = 程序目录下 (与 设置.json 同级)."""
    return os.path.join(guiloader.program_dir('loom', base), 'layer_tag.json')


def _normalize_layers(raw):
    """dict -> 补全 0~31 的层名表; 越界键/非字符串值丢弃."""
    out = {i: '' for i in range(LAYER_COUNT)}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < LAYER_COUNT and isinstance(v, str):
                out[idx] = v[:MAX_LAYER_NAME_LEN]
    return out


def _normalize_tags(raw):
    """list -> 内置 7 个恒在 + 用户项去重追加; 超上限截断."""
    out = list(DEFAULT_TAGS)
    seen = {t.lower() for t in out}
    for t in (raw if isinstance(raw, list) else []):
        if not isinstance(t, str):
            continue
        t = t.strip()
        if not t or t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
        if len(out) >= MAX_TAGS:
            break
    return out


def validate_tag(tag):
    """校验标签合法性. 返回 (ok, reason); 合法时 reason 为空串."""
    if not isinstance(tag, str):
        return False, 'tag 必须是字符串'
    tag = tag.strip()
    if not tag:
        return False, 'tag 不能为空'
    if len(tag) > MAX_TAG_LEN:
        return False, 'tag 长度不能超过 %d 字符' % MAX_TAG_LEN
    if not _TAG_RE.match(tag):
        return False, 'tag 只能包含字母/数字/下划线/中文'
    return True, ''


def save(layers, tags, base=None):
    """原子写 layer_tag.json (tmp + os.replace). 空名层不落盘."""
    path = config_path(base)
    data = {
        'version': 1,
        'layers': {str(k): v for k, v in sorted(layers.items())
                   if isinstance(v, str) and v},
        'tags': list(tags),
    }
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def load(base=None):
    """读 layer_tag.json -> (layers: dict[int,str], tags: list[str]).
    文件缺失/损坏时回退默认并尝试落盘; 任何异常都不阻止启动."""
    path = config_path(base)
    d = None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = None
    except Exception:
        d = None
    if d is None:
        # 缺失或损坏: 用默认值落盘 (写失败也继续, 只是下次启动再试),
        # 并直接返回默认值 —— 不能返回空表 (否则 layer_name(0) 变空串).
        try:
            save(DEFAULT_LAYERS, DEFAULT_TAGS, base)
        except Exception:
            pass
        return _normalize_layers(DEFAULT_LAYERS), _normalize_tags(DEFAULT_TAGS)
    return _normalize_layers(d.get('layers')), _normalize_tags(d.get('tags'))
