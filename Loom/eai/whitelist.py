# -*- coding: utf-8 -*-
"""eai.whitelist — 写路径白名单

我负责：Agent 写文件命令的落点校验（程序目录 / 场景目录 / 用户目录 / Temp，realpath 挡 junction）。
我不负责：具体命令如何使用这个校验结果。
"""

import os

# ---- 写路径白名单 (2026-08-28 二轮, 高危3: Agent 语句直达任意目录释放文件) ----
def _write_roots(win=None):
    """写路径白名单根: 程序目录 / 当前场景目录 / 用户目录.
    Agent (含提示词注入) 发出的写文件命令只能落这些根之下."""
    import guiloader
    roots = []
    try:
        roots.append(os.path.abspath(guiloader.program_dir()))
    except Exception:
        # 2026-11-09 修复: 旧兜底用 dirname(abspath(sys.argv[0]))，而本函数可能在
        # os.chdir() 之后被调用（test_eai_real 会 chdir 到引擎根）—— 相对 argv[0]
        # 二次拼接会得到不存在的 Loom/Loom/tests，于是 tests/_tmp 被判越域，
        # asset_save/screenshot 全部失败。改用本模块自身目录（= 引擎目录），与 cwd 无关。
        # Q-B7-38-1 包化: 本文件已在 eai/ 下, 取上一级 = 引擎目录 (与拆分前同值)。
        roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        ed = getattr(win, 'editor', None)
        sp = getattr(ed, '_scene_path', None)
        if sp:
            roots.append(os.path.abspath(os.path.dirname(sp)))
    except Exception:
        pass
    roots.append(os.path.expanduser('~'))
    # 系统临时目录: 写临时文件/测试场地是合法场景; 它不在病毒投放价值区
    # (Startup/桌面/文档才是), 且 exe 与脚本常走 Temp
    try:
        import tempfile
        roots.append(os.path.normpath(tempfile.gettempdir()))
    except Exception:
        pass
    # 去重保序
    out, seen = [], set()
    for r in roots:
        r = r.rstrip('\\/')
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _realpath(p):
    """os.path.realpath 容错包装 (Windows 上坏链接/怪字符不抛, 回落 abspath).

    2026-11-07 安全加固用: 白名单判定不能只比字符串前缀 —— 在 scripts/ 里放一个
    junction (指向系统目录) 后 "scripts/evil/x.py" 的字符串前缀完全合法,
    但它真实落在系统目录。realpath 会解析 junction/符号链接。"""
    try:
        return os.path.realpath(p)
    except (OSError, ValueError):
        return os.path.abspath(p)


def _safe_write_path(path, purpose='写文件', win=None, extra_roots=None):
    """校验写路径在白名单内; 返回 (True, 规范化路径) 或 (False, 错误串).
    判定: 绝对路径化 + 无 .. 逃逸; 必须以某个白名单根为前缀, 且不是根
    本身 (根=目录, 防止把目录当文件写废).

    2026-11-07 P1-4: 前缀比较改用 realpath (挡 junction/符号链接逃逸),
    返回的路径仍是 abspath (调用方与既有验收依赖这个字形, 不返回 realpath).
    extra_roots: 额外允许根 (MCP 服务传入它自己的工程目录 —— 工程不在
    程序目录/用户目录/临时目录时, 脚本写入不应被误杀)."""
    if not path or not isinstance(path, str):
        return False, '需要非空 path'
    full = os.path.abspath(os.path.normpath(path))
    real = _realpath(full)
    roots = list(_write_roots(win))
    if extra_roots:
        for r in extra_roots:
            if r:
                roots.append(os.path.abspath(os.path.normpath(str(r))))
    for r in roots:
        rr = _realpath(r)
        if real == rr:
            return False, '路径是目录, 不是文件: %s' % full
        if real.startswith(rr + os.sep) or real.startswith(rr + '/'):
            return True, full
    return False, ('%s 越域: %s (白名单: 程序目录/场景目录/用户目录; '
                   '请改用白名单内路径)' % (purpose, full))
