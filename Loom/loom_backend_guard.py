# -*- coding: utf-8 -*-
"""loom_backend_guard.py — 渲染后端兼容性诊断 + 可见失败（2026-11-09 批次 A / 阶段 1）。

与 loom_gl_version.require_gl_version 同一风格：**单点实现 + 可读诊断 + 失败必须可见**。

本模块负责三件事：
  1) Vulkan 运行时 / API 版本地板（wgpu-native 地板 = **Vulkan 1.1**）：
     require_vulkan_api() 低于地板（或根本没有 loader）时抛 VkBackendInitError；
     该异常 segment = vulkan-init，与 run_player 的「可回退段」识别契约一致
     （识别靠类属性而非类身份，见 run_player._is_vk_error 的 P-02-06 注释）。
  2) 一段人可读诊断：device / driver / driver_info / backend / device_type / apiVersion。
  3) 阻塞式原生错误弹窗（Windows MessageBoxW，**零 Qt 依赖**）：换后端会改变用户预期，
     原因必须让用户当场看见；非 Windows / 无 user32 / LOOM_NO_DIALOG=1 时只打印不弹。

事实口径（写进文档的同一份）：
  · Vulkan 后端地板 = 1.1（wgpu-native 的最低要求）；Intel 核显需要 Skylake（6 代）+，
    且驱动为 2018 年之后的版本才会暴露 1.1+。
  · OpenGL 后端地板 = 4.3 core（见 loom_gl_version）。两者是**两条独立路径**：
    一条不满足不等于另一条也不满足，所以回退后必须各自复核。
"""
import ctypes
import os

# ---- Vulkan 地板（改这里 = 改全工程 VK 地板）----
VK_MIN_API_MAJOR = 1
VK_MIN_API_MINOR = 1

# 弹窗开关：测试/无头环境设 LOOM_NO_DIALOG=1（MessageBoxW 会阻塞等点击）
ENV_NO_DIALOG = 'LOOM_NO_DIALOG'


class VkBackendInitError(RuntimeError):
    """Vulkan 初始化段不可用（loader / API 版本 / 适配器 / 设备）—— 可回退 OpenGL。"""
    segment = 'vulkan-init'


def _vulkan_dll():
    """尽力加载 Vulkan loader；没有就返回 None（= 机器上没装 Vulkan 运行时）。"""
    names = ('vulkan-1.dll',) if os.name == 'nt' else ('libvulkan.so.1', 'libvulkan.so')
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


def vulkan_api_version():
    """返回 (major, minor, patch)；无 loader 返回 None，1.0 运行时返回 (1, 0, 0)。

    vkEnumerateInstanceVersion 是 Vulkan 1.1 才有的入口；1.0 运行时没有这个符号
    —— 这种情况按 (1, 0, 0) 处理，正好落在 1.1 地板之下。
    """
    dll = _vulkan_dll()
    if dll is None:
        return None
    try:
        fn = dll.vkEnumerateInstanceVersion
        fn.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
        fn.restype = ctypes.c_int32
        ver = ctypes.c_uint32(0)
        if fn(ctypes.byref(ver)) != 0:
            return None
        raw = int(ver.value)
        return ((raw >> 22) & 0x7F, (raw >> 12) & 0x3FF, raw & 0xFFF)
    except Exception:
        return (1, 0, 0)


def vulkan_api_text():
    """apiVersion 的一行文本（诊断与成功日志共用同一格式）。"""
    v = vulkan_api_version()
    if v is None:
        return '未知（未找到 Vulkan 运行时 / 加载器）'
    return '%d.%d.%d' % v


# 诊断字段的候选键：wgpu 0.32 用 device/driver/backend/device_type，
# wgpu 0.33 改名为 description/driver_description/backend_type/adapter_type（P2-1）。
_DIAG_KEYS = (
    ('device', ('device', 'description')),
    ('driver', ('driver', 'driver_description', 'driver_info')),
    ('backend', ('backend', 'backend_type')),
    ('adapter_type', ('device_type', 'adapter_type')),
    ('vendor', ('vendor',)),
)


def _pick(info, names):
    """按候选键取第一个非空值；缺失一律 'n/a'（不写「未知」冒充有值，P2-1）。"""
    for n in names:
        v = info.get(n)
        if v:
            return str(v)
    return 'n/a'


def adapter_info_dict(adapter):
    """把 wgpu AdapterInfo（dict 或对象）归一成普通 dict；读不到返回 {}。"""
    info = getattr(adapter, 'info', None)
    if info is None:
        return {}
    try:
        return dict(info)
    except Exception:
        out = {}
        for _name, keys in _DIAG_KEYS:
            for k in keys:
                v = getattr(info, k, None)
                if v is not None:
                    out[k] = v
        return out


def vk_diag_text(adapter_info=None, stage='init', extra=None):
    """多行诊断：打印与弹窗共用同一段文本（字段缺失写 n/a）。"""
    info = dict(adapter_info or {})
    lines = [
        '[VK] 设备: %s' % _pick(info, ('device', 'description')),
        '[VK] 驱动: %s (%s)' % (_pick(info, ('driver', 'driver_description', 'driver_info')),
                               _pick(info, ('driver_info', 'driver_version', 'driver_description'))),
        '[VK] 后端/类型: %s / %s' % (_pick(info, ('backend', 'backend_type')),
                                    _pick(info, ('device_type', 'adapter_type'))),
        '[VK] Vulkan API: %s（地板: %d.%d）' % (vulkan_api_text(),
                                                VK_MIN_API_MAJOR, VK_MIN_API_MINOR),
    ]
    if extra:
        lines.append('[VK] 失败段/原因: %s — %s'
                     % ('初始化（可回退 OpenGL）' if stage == 'init' else stage, extra))
    return '\n'.join(lines)


def require_vulkan_api(where='Vulkan 渲染', adapter_info=None):
    """Vulkan 地板硬门：loader 缺失或 apiVersion < 1.1 -> VkBackendInitError。

    返回 (major, minor, patch) 便于调用方记录；异常消息本身就是给用户看的那段，
    上层（run_player）原样打印 + 弹窗，不再二次包装。
    """
    ver = vulkan_api_version()
    if ver is None:
        lines = [
            '[VK] %s 不可用：未找到 Vulkan 运行时（vulkan-1.dll）—— 显卡驱动未安装 Vulkan 支持，或系统未安装 Vulkan 运行库。',
            '[VK] 需要 Vulkan %d.%d+（wgpu-native 地板）。' % (VK_MIN_API_MAJOR, VK_MIN_API_MINOR),
            '[VK] 提示: 升级显卡驱动（NVIDIA/AMD/Intel 官方驱动自带 Vulkan 运行库）。',
            '[VK] 本机诊断:',
        ]
        msg = '\n'.join(lines) + '\n' + vk_diag_text(adapter_info)
        print(msg)
        raise VkBackendInitError(msg)
    if (ver[0], ver[1]) < (VK_MIN_API_MAJOR, VK_MIN_API_MINOR):
        lines = [
            '[VK] %s 不可用：当前 Vulkan API 为 %d.%d.%d，低于地板 %d.%d（wgpu-native 要求）。',
            '[VK] 提示: 升级显卡驱动到 2018 年之后的版本；Intel 核显需要 Skylake（6 代）及以上且驱动支持 Vulkan 1.1。',
            '[VK] 本机诊断:',
        ]
        msg = ('\n'.join(lines) % (where, ver[0], ver[1], ver[2],
                                   VK_MIN_API_MAJOR, VK_MIN_API_MINOR)
               + '\n' + vk_diag_text(adapter_info))
        print(msg)
        raise VkBackendInitError(msg)
    return ver


def show_blocking_dialog(title, text):
    """阻塞式原生错误框（Windows；禁用/非 Windows 返回 False，只留日志）。

    为什么不用 Qt：这条路径可能在 Qt 起来之前（VK 初始化在 run_vk 内）就触发，
    再拉一个 QApplication 会把「换个后端」变成「起半个 GUI」。user32 足够且零依赖。
    """
    if os.environ.get(ENV_NO_DIALOG):
        return False
    if os.name != 'nt':
        return False
    try:
        fn = ctypes.windll.user32.MessageBoxW
        fn.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        fn.restype = ctypes.c_int
        MB_OK, MB_ICONERROR, MB_TOPMOST, MB_SETFOREGROUND = 0x0, 0x10, 0x40000, 0x10000
        rez = fn(None, text, title, MB_OK | MB_ICONERROR | MB_TOPMOST | MB_SETFOREGROUND)
        # P3②: MessageBoxW 返回 0 表示没弹出来（无桌面/被拒绝）—— 不能谎报已弹。
        return bool(rez)
    except Exception as e:
        print('[backend] 弹窗失败 (%r) —— 仅打印原因，不阻断回退' % (e,))
        return False
