# -*- coding: utf-8 -*-
"""loom_gl_version.py — OpenGL 地板版本门（2026-11-09 批次 A0 / 人类裁决 D1=B）。

口径变更：GL 地板 3.3 -> **4.3 core**（理由：3.3 属亮机卡级别，现代游戏起步即 DX11 同级）。

本模块只做两件事：
  · 从 moderngl 上下文取人可读的版本 / 显卡 / 厂商信息；
  · 低于地板就 **明确报错**（先打印 GL 版本 + 驱动 + 提示，再 raise）。

设计约束（硬）：失败必须可见 —— 绝不静默黑屏、不吞异常、不让界面停在「看起来在跑」的状态。

适用范围：**产品路径**（GLFW 窗口 / Qt 离屏播放器 / 编辑器视口）必须走此门。
测试与探测里「外部注入 ctx」（PlayerApp(ctx=...) / EditorApp(ctx=...)）不走此门 ——
注入方自担版本，否则无头测试会被硬门挡住（见 tests/test_skybox_engine_parity.py 的
create_standalone_context(require=330) 口径）。

着色器版本策略（同一裁决的一部分）：现有 #version 330 源码**不动**（4.3 core 驱动能编 330），
只有新增能力（SSBO / compute / 显式 layout）才写 #version 430，避免一次性升版的回归面。
"""

# ---- 地板常量（改这里 = 改全工程 GL 地板）----
GL_MIN_MAJOR = 4
GL_MIN_MINOR = 3
GL_MIN_VERSION_CODE = GL_MIN_MAJOR * 100 + GL_MIN_MINOR * 10        # 430

# 现有着色器源码统一的 GLSL 版本（新增能力前不动）
GLSL_EXISTING = 330
GLSL_NEW_FEATURES = 430


class GLVersionError(RuntimeError):
    """OpenGL 上下文低于地板版本（4.3 core）—— 拒绝继续渲染。"""


def gl_info(ctx):
    """返回 (GL_VERSION, GL_RENDERER, GL_VENDOR, version_code)；缺字段一律 ? 与 0。"""
    info = getattr(ctx, 'info', None) or {}
    try:
        code = int(getattr(ctx, 'version_code', 0) or 0)
    except (TypeError, ValueError):
        code = 0
    return (str(info.get('GL_VERSION', '?')),
            str(info.get('GL_RENDERER', '?')),
            str(info.get('GL_VENDOR', '?')),
            code)


def gl_version_text(ctx):
    """一行式版本描述（日志 / 报错共用同一格式）。"""
    ver, renderer, vendor, code = gl_info(ctx)
    return 'OpenGL %s | 显卡 %s | 厂商 %s | version_code=%d' % (ver, renderer, vendor, code)


def supports_gl(ctx, major=GL_MIN_MAJOR, minor=GL_MIN_MINOR):
    """上下文是否达到指定版本（默认地板 4.3）。"""
    _v, _r, _vd, code = gl_info(ctx)
    return code >= major * 100 + minor * 10


def require_gl_version(ctx, where='渲染'):
    """低于 4.3 core 就打印诊断并 raise GLVersionError（不返回假成功）。

    返回 version_code 便于调用方记录；异常消息本身就是给用户看的那段，
    上层（Loom.py / run_player / Qt 宿主）原样打印即可，不需要再包装。
    """
    ver, renderer, vendor, code = gl_info(ctx)
    if code >= GL_MIN_VERSION_CODE:
        return code
    lines = [
        '[GL] %s 需要 OpenGL %d.%d core 及以上，当前上下文不满足 —— 拒绝继续，以免出现「黑屏但进程还在跑」的假成功。',
        '[GL] 当前: OpenGL %s | version_code=%d',
        '[GL] 显卡/驱动: %s (%s)',
        '[GL] 提示: 先更新显卡驱动；显卡确实不支持 OpenGL %d.%d 时请联系开发者。',
        '[GL] 备选: 改用 Vulkan 后端 —— 启动参数 --backend vulkan（或设置 render_api=vulkan）。',
    ]
    msg = '\n'.join(lines) % (where, GL_MIN_MAJOR, GL_MIN_MINOR,
                              ver, code, renderer, vendor,
                              GL_MIN_MAJOR, GL_MIN_MINOR)
    print(msg)
    raise GLVersionError(msg)
