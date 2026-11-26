# -*- coding: utf-8 -*-
"""eai.helpers — 命令参数归一助手

我负责：字符串→bool/float 归一、颜色解析 (parse_color)、向量字段归一与单轴写入 (vec_set)。
我不负责：任何命令语义（只做参数整形，不碰编辑器状态）。
"""

# 命令参数一律可能是字符串 (GUI 控制台输入 "on=false" / HTTP JSON 里写
# "false"), 裸 bool('false') == True —— 曾让 `play on=false` 反而开始播放.
_FALSE_WORDS = {'', '0', 'false', 'no', 'off', 'none', '否'}


def as_bool(v, default=False):
    """命令参数布尔化 (字符串 'false'/'0'/'no'/'off' 判假). 命令层统一入口."""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() not in _FALSE_WORDS


def as_float(v, default=0.0):
    """命令参数数值化 (控制台字符串/JSON 数字通吃; 非法值回默认)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# 2026-10-20 提到模块级（原在 cmd_ui_set 局部，cmd_ui_add 也要用）
# 2026-11-07 P0: 补齐此前漏掉的颜色字段 —— 漏掉的字段会落到 tuple()/setattr
# 默认转换上, 传 '#rrggbb' 字符串就变成 ('#','r','r',...) 坏元组, 渲染帧
# TypeError 直接把播放器打崩。凡是 UIElement 的颜色属性都必须在表内。
_COLOR_FIELDS = {
    'bg_color', 'color', 'tint', 'text_color', 'normal_color',
    'hover_color', 'pressed_color', 'track_color', 'fill_color',
    'handle_color', 'box_color', 'check_color', 'label_color',
    'stroke_color',
    # input_field / dropdown / scroll_view 的颜色字段 (2026-11-07 补齐)
    'focus_bg_color', 'placeholder_color', 'cursor_color',
    'list_bg', 'list_hover', 'bar_color',
}


def parse_color(v):
    """把颜色值统一成 RGBA 元组 (r,g,b,a)。
    支持: '#RRGGBB' -> (r,g,b,255); '#RRGGBBAA' -> (r,g,b,a);
          '#RGB' -> (r*17,g*17,b*17,255);
          [r,g,b] / (r,g,b) -> (r,g,b,255); [r,g,b,a] / (r,g,b,a) -> (r,g,b,a)。
    非法值抛 ValueError（调用方用 take() 捕获成 error: '...' 字段）。
    """
    if isinstance(v, str):
        s = v.strip().lstrip('#')
        if len(s) == 3:
            s = ''.join(c * 2 for c in s) + 'ff'
        elif len(s) == 6:
            s = s + 'ff'
        if len(s) != 8:
            raise ValueError('颜色格式非法 (需 #RRGGBB / #RRGGBBAA / #RGB): %r' % v)
        try:
            return (int(s[0:2], 16), int(s[2:4], 16),
                    int(s[4:6], 16), int(s[6:8], 16))
        except ValueError:
            raise ValueError('颜色十六进制非法: %r' % v)
    if isinstance(v, (list, tuple)):
        r = tuple(int(x) for x in v)
        if len(r) == 3:
            r = r + (255,)
        elif len(r) != 4:
            raise ValueError('颜色数组需 3 或 4 项: %r' % (v,))
        # 2026-11-07: 分量必须是 0-255 —— 越界元组同样会在渲染帧算出非法
        # u_color (color/255.0 > 1), 属于坏元组, 一律拒绝。
        for _c in r:
            if not 0 <= _c <= 255:
                raise ValueError('颜色分量越界 (需 0-255): %r' % (v,))
        return r
    raise ValueError('颜色类型不支持: %r' % (v,))


def _coerce_color_args(args, cmd='ui'):
    """颜色参数预解析 (2026-11-07 P0): 把 args 里所有颜色字段统一过 parse_color,
    变成 (r,g,b,a) 4 元组。非法值抛 ValueError —— 调用方转成
    {'error': ...} 返回, 绝不让坏元组流进渲染帧。

    ui_add 原来对颜色字段用裸 tuple(): tuple('#ff0000') -> ('#','f','f',...) 7 项,
    渲染帧 color[0]/255.0 抛 TypeError -> 播放器整帧异常退出 (P0)。
    这里是 ui_add / ui_set 共用的单一入口, 后续新字段只要进 _COLOR_FIELDS 即自动覆盖。
    返回新 dict, 不改调用方传进来的对象 (dispatch 日志仍按原参数打印)。"""
    out = dict(args)
    for k in _COLOR_FIELDS:
        if k in out:
            try:
                out[k] = parse_color(out[k])
            except ValueError as e:
                raise ValueError('%s 字段 %s 非法: %s' % (cmd, k, e))
    return out


# 几何字段: 名字 -> 需要的分量数 (rect 4 项, anchor/pivot 各 2 项)
_VEC_FIELDS = {'rect': 4, 'anchor': 2, 'pivot': 2}


def _as_vec(v, n, field, cmd='ui'):
    """rect/anchor/pivot 规整成长度 n 的浮点元组 (2026-11-07 收尾)。

    与颜色字段同一类坏输入: 原代码 `kw['rect'] = tuple(args['rect'])`,
    控制台/HTTP 传字符串时 tuple('0,0,100,20') 得到字符元组, loom_ui 的
    rect/anchor/pivot setter 有 try/except 会**静默丢弃** —— 命令回 ok=True
    但元素尺寸/锚点根本没变 (最难查的那种'没反应')。
    这里: 字符串按逗号/空白切分 (方便控制台 `rect=0,0,100,20`), 数组原样;
    项数/数值/NaN 任一不合法都抛 ValueError, 由调用方转成 {'error': ...}。"""
    if isinstance(v, str):
        parts = [p for p in v.replace(',', ' ').split() if p]
    elif isinstance(v, (list, tuple)):
        parts = list(v)
    else:
        raise ValueError('%s 字段 %s 需要数组或逗号分隔数字: %r' % (cmd, field, v))
    if len(parts) != n:
        raise ValueError('%s 字段 %s 需要 %d 个数 (收到 %d 项): %r'
                         % (cmd, field, n, len(parts), v))
    try:
        out = tuple(float(x) for x in parts)
    except (TypeError, ValueError):
        raise ValueError('%s 字段 %s 含非数值项: %r' % (cmd, field, v))
    for c in out:
        if c != c or c in (float('inf'), float('-inf')):
            raise ValueError('%s 字段 %s 含 NaN/Inf: %r' % (cmd, field, v))
    return out


def _coerce_vec_args(args, cmd='ui'):
    """rect/anchor/pivot 预解析 (与 _coerce_color_args 同款, 返回新 dict)。"""
    out = dict(args)
    for k, n in _VEC_FIELDS.items():
        if k in out:
            out[k] = _as_vec(out[k], n, k, cmd)
    return out


def vec_set(obj, field, axis, v):
    """namedtuple 向量单轴写入: 重建整个元组, 只改 axis 分量 (其余不动).
    2026-08-22 修复记录: Point3D 是 namedtuple —— 对实例 setattr 无效 (会静默
    建错误属性); 整体重建 type(cur)(nv,nv,nv) 会把三个轴全写成一个值 (用户实测
    "拖 X 坐标 XYZ 被同时改"). 物体/光源/相机位置, 检查器数值行与 set_transform
    等命令**共用本函数** (qt_view._vec_set 即本函数别名, 单一事实)."""
    cur = getattr(obj, field)
    idx = 'XYZ'.index(str(axis).upper())
    setattr(obj, field, type(cur)(*(v if i == idx else c
                                    for i, c in enumerate(cur))))
