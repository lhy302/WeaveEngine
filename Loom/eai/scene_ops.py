# -*- coding: utf-8 -*-
"""eai.scene_ops — 场景命令

我负责：scene_new / scene_save / scene_load。
我不负责：场景数据的序列化实现（在 scene/ 包）与资产库命令。
"""

import json
import os
from .registry import _CMD_SCOPE, command
from .whitelist import _safe_write_path

# ====================================================================
# 场景
# ====================================================================
@command('scene_new', '新建场景 (Agent/控制台语义: 直接重置, 不弹"是否保存"对话框)')
def cmd_scene_new(win, args):
    ed = win.editor
    ed._new_scene()
    return {'ok': True, 'scene': getattr(ed, 'scene_name', None),
            'models': [m.name for m in ed.models]}


@command('scene_save', '保存场景: {path} 存到指定文件; 无 path = 存回当前文件')
def cmd_scene_save(win, args):
    """save_scene_as() 是**无参**的 (它总是弹系统另存为对话框, Agent 环境会
    卡死); 带路径保存必须走低层 _save_scene(path) —— 与 _load_scene(path)
    对称 (2026-08-27 修: 原来传参给 save_scene_as 直接 TypeError)."""
    ed = win.editor
    path = args.get('path')
    if path:
        # 2026-08-28 二轮(高危3): 写路径白名单 —— 任意路径释放 = Agent 语
        # 句可达的病毒落点; 白名单外明确拒绝 (目录/场景/用户三根)
        # Q-B7-56-1 裁定① (2026-11-22): GUI「保存/另存为」点击 = 人类在系统
        # 对话框里亲手逐字确认的路径, 翻译成 scene_save 执行时放行该路径所在
        # 目录 —— 白名单挡的是 Agent 可注入的任意写, 人类对话框授权不受此限;
        # 命令行/远程 (scope='agent') 一律维持原白名单, 越域照旧拒绝。
        _extra = None
        if _CMD_SCOPE.current == 'user':
            _extra = [os.path.dirname(os.path.abspath(os.path.normpath(str(path))))]
        ok, full = _safe_write_path(path, 'scene_save', win, extra_roots=_extra)
        if not ok:
            return {'error': full}
        out = ed._save_scene(full)
        if not out:
            return {'error': '保存失败 (播放中不能保存, 或路径不可写): %s' % full}
        return {'saved': out}
    if not getattr(ed, '_scene_path', None):
        return {'error': '当前场景还没有对应文件: 请传 path=完整路径 '
                         '(无 path 会弹系统另存为对话框, Agent 环境禁用)'}
    ok = ed.save_scene()
    return {'saved': ed._scene_path} if ok else {'error': '保存失败'}


@command('scene_load', '加载场景: {path} 直接换场 (无确认, 当前改动丢弃=恢复磁盘版本)')
def cmd_scene_load(win, args):
    ed = win.editor
    path = args.get('path')
    if not path:
        return {'error': 'scene_load 需要 path (丢丢弃恢复=传磁盘上已保存的场景路径;'
                        ' 无 path 会弹系统对话框, Agent 环境禁用)'}
    # 2026-11-10 V-03: 失败必须 ok=False（以前无论成败都回 {'loaded': path}，
    # 静默假成功：路径不存在/JSON 坏/版本闸门拒绝/对象图成环 都报"已加载"）。
    if not os.path.isfile(path):
        return {'error': '场景文件不存在: %s' % path}
    try:
        with open(path, 'r', encoding='utf-8') as _f:
            _data = json.load(_f)
    except (OSError, ValueError) as e:
        return {'error': '场景读取失败: %r' % (e,)}
    if not isinstance(_data, dict):
        return {'error': '场景格式非法（顶层不是对象）: %s' % path}
    # B7-16: 场景契约唯一入口 prepare()（版本闸门 + 数据迁移）—— 与编辑器 / 播放器 /
    # 打包游戏走同一份实现。这里先跑一遍，是为了在**调用 _load_scene 之前**就能回
    # {'error': ...}（Agent 侧要看到原因，而不是只看到"加载未完成"）。
    import sceneio as _sio
    try:
        _data = _sio.prepare(_data)
    except _sio.SceneVersionError as e:
        return {'error': '场景版本不兼容: %s' % e}
    ed._load_scene(path)   # 低层: 直载不弹框不确认 (丢弃当前改动语义)
    # 复核：_load_scene 在播放态/对象图校验失败时是静默 return（不换场）
    _cur = getattr(ed, '_scene_path', None)
    if not _cur or os.path.normcase(os.path.abspath(_cur)) != os.path.normcase(
            os.path.abspath(path)):
        return {'error': '场景加载未完成（播放态或对象图校验拒绝），当前场景保持不变'}
    return {'loaded': path, 'ok': True}
