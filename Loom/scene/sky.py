# -*- coding: utf-8 -*-
"""scene/sky.py — **天空盒**解析/发射（B2 自 sceneio.py 拆出，函数体逐字一致）。

内容（= 旧 sceneio.py 同名段）:
  DEFAULT_SKYBOX_COLOR / DEFAULT_SKYBOX_NAME / default_skybox（Q1=A 默认蓝天）
  parse_color（Q4=A 颜色白盒契约）/ _inside_scene_dir（A3=B 场景目录边界）
  skybox_from_dict / _apply_skybox / _scene_skybox_from_data /
  _apply_skybox_or_default / _emit_skybox / _emit_skybox_checked
"""
import os




# ---------------- 天空盒 (beta5 Q1/Q4/Q5/Q6, 人类裁决 2026-11-09) ----------------
# 白盒契约:
#   · Q1=A 新建场景、以及"没有 skybox 键 / 值为 null"的场景 -> **默认纯色蓝天**;
#     默认值只在本文件定义一次 (DEFAULT_SKYBOX_COLOR), 其它模块不得再写字面量。
#   · Q3=A 相机级 skybox 非 None 时优先（"生效的那一个"由 editor 算好交给 engine._skybox）。
#   · Q4=A 颜色只认 0..255 的整数（或整值浮点）; 0-1 浮点 / 越界 / 长度错 -> 明确报错，
#     不得用 int() 静默截断（历史病灶: [0.2,0.4,0.8] -> int -> (0,0,0) 全黑）。
#   · Q5=A 解析失败必须可见: 打印原因, 并让调用方拿到 (valid, reason)。
#   · Q6=A 六面图 paths 以**相对场景目录**的形式序列化, 加载时按 base_dir 解析; 缺文件报错。
#   · A3=B 六面图**必须位于场景目录内（允许子目录）**：
#         加载时绝对路径与 `..` 越界一律拒绝（valid=False + reason 点名）；
#         保存时若算出的相对路径越界（绝对 / `..` 开头 / 跨盘符）-> **不写出该天空盒**
#         并把原因记进 _skybox_valid/_skybox_error（绝不静默写一个将来加载必然失败的值）。
DEFAULT_SKYBOX_COLOR = (58, 155, 213, 255)      # #3A9BD5 —— 默认蓝天（白盒契约）

DEFAULT_SKYBOX_NAME = '默认蓝天'



def default_skybox():
    """Q1=A: 默认纯色天空盒（新建场景 / 场景无 skybox 键 / 值解析失败时使用）。"""
    from assets.cubemap import Cubemap
    return Cubemap.from_solid(DEFAULT_SKYBOX_COLOR, name=DEFAULT_SKYBOX_NAME)



def parse_color(v):
    """Q4=A 颜色白盒契约 -> ((r,g,b,a) | None, reason | None).

    接受: '#RRGGBB' / '#RRGGBBAA' / [r,g,b] / [r,g,b,a]，通道必须是 0..255 的 int
    （bool 不算）或**整值浮点**（58.0 可以, 0.2 不行）。
    拒绝（Q4=A 收严，P2-3）: '# 前缀缺失'（'3A9BD5' 不再放行）、0-1 浮点、nan/inf、
    越界、长度不是 3/4、非数值 —— 每条都带各自的原因，便于调用方提示。
    """
    import math as _m
    import re as _re
    if isinstance(v, str):
        s = v.strip()
        m = _re.match(r'^#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$', s)
        if not m:
            return None, ('颜色字符串必须是 #RRGGBB 或 #RRGGBBAA（**必须带 # 前缀**）: %r'
                          % (v,))
        h, a = m.group(1), (m.group(2) or 'FF')
        return ((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16),
                 int(a, 16)), None)
    if not isinstance(v, (list, tuple)):
        return None, '颜色必须是 #RRGGBB 字符串或 [r,g,b(,a)] 数组: %r' % (v,)
    if len(v) not in (3, 4):
        return None, '颜色数组必须是 3 或 4 个通道: 收到 %d 个 %r' % (len(v), v)
    out = []
    for i, x in enumerate(v):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None, '颜色通道 #%d 必须是数值: %r' % (i, x)
        if isinstance(x, float):
            if not _m.isfinite(float(x)):
                return None, ('颜色通道 #%d 不是有限数 (nan/inf): %r'
                              % (i, x))          # P2-3: 不再误报成"0-1 浮点"
            if not float(x).is_integer():
                return None, ('颜色通道 #%d=%r 不是 0..255 的整数（看起来是 0-1 浮点）; '
                              '请乘 255, 或用 #RRGGBB' % (i, x))
            x = int(x)
        if not (0 <= int(x) <= 255):
            return None, '颜色通道 #%d=%r 超出 0..255' % (i, x)
        out.append(int(x))
    if len(out) == 3:
        out.append(255)
    return tuple(out), None



def _inside_scene_dir(abs_path, base_dir):
    """A3=B: 路径必须落在场景目录（含子目录）内 -> (ok, reason)。

    用 realpath + commonpath 比较（Windows 下不区分大小写，且 realpath 会解析
    符号链接/8.3 短名）；跨盘符时 commonpath 抛 ValueError -> 视为越界。
    """
    try:
        root = os.path.realpath(os.path.abspath(base_dir))
        p = os.path.realpath(os.path.abspath(abs_path))
    except Exception as e:
        return False, '路径规范化失败: %r' % (e,)
    win = (os.name == 'nt') or (len(root) > 1 and root[1] == ':')
    root_c, p_c = (root.lower(), p.lower()) if win else (root, p)
    try:
        same = (os.path.commonpath([root_c, p_c]) == root_c)
    except ValueError:
        return False, '与场景目录不在同一盘符（越界）'
    if same:
        return True, None
    return False, '不在场景目录内'



def skybox_from_dict(d, base_dir=None, ctx=None):
    """Q5=A/Q6=A: dict -> (cube | None, valid: bool, reason | None).

    v11 新增: {"guid": ...} = 项目资产（走 ctx 解析，越界/缺文件都给 reason）。
    paths 的相对项按 base_dir（场景目录）解析；成功时把**原始（可能相对的）paths**
    记到 cube._source_paths，供 _emit_skybox 原样回写。
    """
    if not isinstance(d, dict):
        # P1-2（回归修复）: 场景里的 'skybox' 可能是 str / list / int / bool（手改或旧工具写入）。
        # 绝不能走到 d.get() 抛 AttributeError —— 那会让整个 scene_from_dict 崩，而编辑器
        # _load_scene 此时已经改掉 _scene_path、清空了旧模型 => 用户直接丢当前场景（违背 F7）。
        return None, False, "'skybox' 必须是对象 (dict)，实际 %s: %r" % (
            type(d).__name__, d)
    if not d:
        return None, False, '缺少 guid/paths/solid_color'
    _guid = d.get('guid')
    _legacy_payload = ('paths' in d) or ('solid_color' in d)
    if isinstance(_guid, str) and _guid and not _legacy_payload:
        # 只有 "纯 guid 引用" 才是项目资产；带 paths/solid_color 的是 beta5 旧字段
        # （guid 只是历史身份），继续走旧解析 —— 兼容闸门。
        if ctx is None:
            return None, False, ('天空盒是资产 guid (%s) 但当前项目没有资产索引'
                                 '（缺 Assets/assets.json）' % (_guid,))
        cube, _ok, _why = ctx.cubemap(_guid, d)
        if cube is None:
            return None, False, '天空盒资产解析失败: %s' % (_why,)
        return cube, True, _why
    try:
        from assets.cubemap import Cubemap
    except Exception as e:
        return None, False, 'Cubemap 模块不可用: %r' % (e,)
    paths = d.get('paths')
    if paths:
        if not isinstance(paths, (list, tuple)) or len(paths) != 6:
            return None, False, ('paths 必须是 6 个路径 (px,nx,py,ny,pz,nz): 收到 %r'
                                 % (paths,))
        # A3=B（人类裁决 2026-11-09）: 六面图**必须位于场景目录内（允许子目录）**;
        # 绝对路径与 `..` 越界一律拒绝（换机/越权读盘都不允许）。
        root = os.path.abspath(base_dir or os.getcwd())
        abs_paths = []
        for i, p in enumerate(paths):
            q = str(p)
            if os.path.isabs(q):
                return None, False, ('第 %d 面是绝对路径 (%s); 六面图必须放在场景目录'
                                     '（含子目录）内, 请改用相对路径' % (i, q))
            q = os.path.join(root, q)
            _ok, _why = _inside_scene_dir(q, root)
            if not _ok:
                return None, False, ('第 %d 面%s (%s); 六面图必须放在场景目录'
                                     '（含子目录）内' % (i, _why, os.path.abspath(q)))
            if not os.path.isfile(q):
                return None, False, '第 %d 面图片不存在: %s' % (i, os.path.abspath(q))
            abs_paths.append(os.path.abspath(q))
        try:
            cube = Cubemap.from_files(abs_paths, name=d.get('name'),
                                      guid=d.get('guid'))
        except Exception as e:
            return None, False, '六面图加载失败: %r' % (e,)
        cube._source_paths = [str(p) for p in paths]        # Q6: 保留相对形式
        return cube, True, None
    solid = d.get('solid_color')
    if solid is not None:
        rgba, reason = parse_color(solid)
        if rgba is None:
            return None, False, reason
        try:
            cube = Cubemap.from_solid(rgba, name=d.get('name'), guid=d.get('guid'))
        except Exception as e:
            return None, False, '纯色天空盒创建失败: %r' % (e,)
        return cube, True, None
    return None, False, '缺少 paths/solid_color'



def _apply_skybox(d, base_dir=None, ctx=None):
    """dict -> Cubemap 实例（兼容旧签名）。失败: **出声** + 返回 None（Q5=A）。"""
    cube, valid, reason = skybox_from_dict(d, base_dir, ctx)
    if not valid and d:
        print('[场景] 天空盒解析失败: %s' % (reason,))
    return cube



def _scene_skybox_from_data(data, base_dir=None, ctx=None):
    """场景级天空盒 -> (cube, valid, reason)；Q1=A: 缺键/null -> 默认蓝。

    有值但解析失败: 出声 + 回退默认蓝（保证"打开场景一定有天空盒"），valid=False
    由调用方转成可查询的 _skybox_valid/_skybox_error（skybox_get 用）。
    """
    d = data.get('skybox')
    # 只有"没写"(None) 或空对象才按缺省处理；非 dict（str/list/int/bool…）是**坏值**，
    # 必须 valid=False 报出来（P1-2），不能悄悄当成"没配"。
    if d is None or (isinstance(d, dict) and not d):
        return default_skybox(), True, None
    cube, valid, reason = skybox_from_dict(d, base_dir, ctx)
    if valid:
        return cube, True, None
    print('[场景] 天空盒解析失败 (%s) -> 回退默认蓝天盒' % (reason,))
    return default_skybox(), False, reason



def _apply_skybox_or_default(d, base_dir=None, ctx=None):
    """只要 cube 的便捷口（场景级）；缺键/null/解析失败都回落默认蓝。"""
    cube, _valid, _reason = _scene_skybox_from_data({'skybox': d}, base_dir, ctx)
    return cube



def _emit_skybox(cube, base_dir=None, ctx=None):
    """Cubemap -> dict（None 时返回 None）；**不做越界判定**（那是 _emit_skybox_checked 的事）。

    Q6=A: paths 写**相对当前场景目录**的形式。给了 base_dir 就**一律重算**
    （P1-3 回归修复: _source_paths 只是内存态；"新建后首次另存/另存为到别的目录"必须
    按新目录重算，否则重载按新目录解析 -> valid=False -> 静默回退默认蓝丢资产）。
    无 base_dir 时才退回内存态形式；再无则写绝对路径。
    """
    if cube is None:
        return None
    out = {"name": getattr(cube, 'name', None),
           "guid": getattr(cube, 'guid', None)}
    if ctx is not None and ctx.owns(getattr(cube, 'guid', None), 'cubemap'):
        return out                       # 项目资产: 只写 guid（路径不落盘）
    paths = getattr(cube, 'paths', None)
    if paths:
        if base_dir:
            rel = []
            for p in paths:
                try:
                    rel.append(os.path.relpath(p, base_dir))
                except Exception:
                    rel.append(str(p))      # 跨盘符无法 relpath -> 保绝对
            out["paths"] = rel
        elif getattr(cube, '_source_paths', None):
            out["paths"] = [str(p) for p in cube._source_paths]
        else:
            out["paths"] = list(paths)
        return out
    solid = getattr(cube, '_solid_color', None)
    if solid:
        out["solid_color"] = [int(c) for c in solid]
        return out
    return None   # 无可用来源（内存态 cubemap 无法序列化）



def _emit_skybox_checked(cube, base_dir=None, ctx=None):
    """A3=B（人类裁决 2026-11-09）: 落盘前的路径限制检查 -> (dict | None, reason | None).

    规则: 六面图**必须位于场景目录内（允许子目录）**。给了 base_dir 时逐面算相对路径:
      · 跨盘符 / 算出来是绝对路径 / 以 '..' 开头  -> **不写出**（整体返回 None）并给 reason；
      · 调用方负责出声，并把 reason 记进 engine._skybox_valid/_skybox_error，
        绝不静默写一个"将来加载必然失败"的值（那等于丢资产还看不见）。
    无 base_dir 的旧调用（不落盘的场合）沿用 _emit_skybox 的行为，不判越界。
    """
    if cube is None:
        return None, None
    if ctx is not None and ctx.owns(getattr(cube, 'guid', None), 'cubemap'):
        return _emit_skybox(cube, base_dir, ctx), None
    if not base_dir or not getattr(cube, 'paths', None):
        return _emit_skybox(cube, base_dir, ctx), None
    root = os.path.abspath(base_dir)
    rel = []
    for i, p in enumerate(cube.paths):
        try:
            r = os.path.relpath(os.path.abspath(str(p)), root)
        except Exception:
            return None, ('第 %d 面与场景目录不在同一盘符 (%s); 六面图必须放在场景目录'
                          '（含子目录）内 -> 本次不写入' % (i, p))
        if os.path.isabs(r) or r.split(os.sep)[0] == '..' or r.split('/')[0] == '..':
            return None, ('第 %d 面不在场景目录内 (%s); 六面图必须放在场景目录（含子目录）'
                          '内 -> 本次不写入' % (i, r))
        rel.append(r)
    out = {"name": getattr(cube, 'name', None),
           "guid": getattr(cube, 'guid', None),
           "paths": rel}
    return out, None
