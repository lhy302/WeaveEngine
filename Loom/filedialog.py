# -*- coding: utf-8 -*-
r"""
filedialog.py — Windows 原生文件对话框 (GetSaveFileNameW / GetOpenFileNameW)

用 ctypes 直接调用 comdlg32, 弹出与记事本/Office 同款的系统原生对话框,
不依赖 tkinter. 供编辑器保存/加载场景、Prefab 存模板/放实例使用.

用法:
    import filedialog
    p = filedialog.save_file("保存场景", initial_dir=r"D:\x", default_name="场景",
                             filter_str="场景文件 (*.json)\\0*.json\\0所有文件 (*.*)\\0*.*\\0",
                             default_ext="json")
    p = filedialog.open_file("加载场景", initial_dir=r"D:\x",
                             filter_str="场景文件 (*.json)\\0*.json\\0所有文件 (*.*)\\0*.*\\0")
返回选中文件的完整路径; 用户取消返回 None.

filter_str 中每一项用 \\0 分隔 (C 字符串风格): "显示名\\0*.ext\\0显示名2\\0*.ext2\\0\\0"
"""
import ctypes
import os
from ctypes import wintypes

# ---- OPENFILENAME 标志 (commdlg.h) ----
OFN_OVERWRITEPROMPT = 0x00000002
OFN_HIDEREADONLY = 0x00000004
OFN_PATHMUSTEXIST = 0x00000800
OFN_FILEMUSTEXIST = 0x00001000
OFN_EXPLORER = 0x00080000

_MAX_FILE = 4096


class OPENFILENAMEW(ctypes.Structure):
    """64 位 Windows 下的 OPENFILENAMEW 结构体布局."""
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", ctypes.POINTER(ctypes.c_wchar)),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", ctypes.POINTER(ctypes.c_wchar)),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", wintypes.LPVOID),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", wintypes.LPVOID),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


_comdlg32 = ctypes.windll.comdlg32
_comdlg32.GetSaveFileNameW.restype = wintypes.BOOL
_comdlg32.GetSaveFileNameW.argtypes = [ctypes.POINTER(OPENFILENAMEW)]
_comdlg32.GetOpenFileNameW.restype = wintypes.BOOL
_comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(OPENFILENAMEW)]


def _parent_hwnd():
    """返回玩家运行时 GLFW 窗口句柄 (对话框模态置顶用), 失败返回 0 (则对话框独立).
    2026-10-18 A2: 原 pygame.display.get_wm_info 改 GLFW。
    - 玩家运行时（GLFW 窗口）: 从当前上下文窗口拿 HWND
    - 编辑器模式（Qt）: 无 GLFW 窗口，返回 0（对话框独立，Qt 有自己的模态）"""
    try:
        import glfw
        win = glfw.get_current_context()   # 返回当前线程已 make_current 的窗口
        if win:
            from loom_glfw_window import _make_hwnd
            hwnd = _make_hwnd(win)
            if hwnd:
                return hwnd
    except Exception:
        pass
    return 0


def _dialog(dialog_func, title, initial_dir, default_name, filter_str,
            default_ext, flags):
    """填充 OPENFILENAMEW 并调用. 成功返回规范化路径, 取消返回 None."""
    buf = ctypes.create_unicode_buffer(_MAX_FILE)
    if default_name:
        buf.value = default_name
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = _parent_hwnd()
    ofn.lpstrFilter = filter_str or ("所有文件 (*.*)\0*.*\0")
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buf, ctypes.POINTER(ctypes.c_wchar))
    ofn.nMaxFile = _MAX_FILE
    if initial_dir:
        ofn.lpstrInitialDir = initial_dir
    if title:
        ofn.lpstrTitle = title
    ofn.Flags = flags
    if default_ext:
        ofn.lpstrDefExt = default_ext
    if dialog_func(ctypes.byref(ofn)):
        return os.path.normpath(buf.value)
    return None


def save_file(title, initial_dir=None, default_name=None, filter_str=None,
              default_ext=None):
    """保存对话框. default_name 显示在文件名框 (冲突提示由 OFN_OVERWRITEPROMPT 处理)."""
    flags = (OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST | OFN_EXPLORER
             | OFN_HIDEREADONLY)
    return _dialog(_comdlg32.GetSaveFileNameW, title, initial_dir,
                   default_name, filter_str, default_ext, flags)


def open_file(title, initial_dir=None, filter_str=None):
    """打开对话框 (文件必须存在)."""
    flags = (OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_EXPLORER
             | OFN_HIDEREADONLY)
    return _dialog(_comdlg32.GetOpenFileNameW, title, initial_dir,
                   None, filter_str, None, flags)


# ---------------- 目录选择 (IFileOpenDialog 现代 / SHBrowseForFolderW 回退) ----------------
# 用户要求"调用系统文件管理器创建项目": 用与记事本/Office 同款的现代文件夹选择对话框
# (IFileOpenDialog + FOS_PICKFOLDERS), 失败自动回退经典 SHBrowseForFolderW.
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid_str(s):
    """'{Data1-Data2-Data3-Data4a-Data4b}' -> GUID 结构体 (Data4 由 p[3]+p[4] 拼 8 字节)."""
    p = s.strip("{}").split("-")
    return GUID(int(p[0], 16), int(p[1], 16), int(p[2], 16),
                (ctypes.c_ubyte * 8)(*bytes.fromhex(p[3] + p[4])))


def _choose_directory_modern(title="选择目录", initial_dir=None):
    """现代文件夹选择对话框 (IFileOpenDialog, Vista+). 返回目录路径, 取消 None.
    任何 COM 设置/调用失败抛异常, 由 choose_directory 回退到经典对话框."""
    _CFUNCTYPE = ctypes.CFUNCTYPE
    _HRESULT = ctypes.c_long
    _c_void_p = ctypes.c_void_p
    _c_uint = ctypes.c_uint
    _c_ulong = ctypes.c_ulong
    byref = ctypes.byref
    cast = ctypes.cast
    POINTER = ctypes.POINTER
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    ole32.CoInitialize(None)
    dlg = _c_void_p()
    try:
        hr = ole32.CoCreateInstance(byref(_guid_str("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")),
                                    None, 1,
                                    byref(_guid_str("{D57C7288-D4AD-4768-BE02-9D969532D960}")),
                                    byref(dlg))
        if hr != 0 or not dlg:
            raise OSError("CoCreateInstance IFileOpenDialog hr=%08x" % hr)
        vtbl = cast(dlg, POINTER(POINTER(_c_void_p)))[0]

        # IFileDialog vtable: 3=Show, 9=SetOptions, 12=SetFolder, 17=SetTitle, 20=GetResult
        _CFUNCTYPE(_HRESULT, _c_void_p, _c_uint)(vtbl[9])(dlg, 0x20)      # FOS_PICKFOLDERS
        if title:
            _CFUNCTYPE(_HRESULT, _c_void_p, wintypes.LPCWSTR)(vtbl[17])(dlg, title)
        if initial_dir and os.path.isdir(initial_dir):
            item = _c_void_p()
            hr = shell32.SHCreateItemFromParsingName(
                initial_dir, None, byref(_guid_str("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")),
                byref(item))
            if hr == 0 and item:
                _CFUNCTYPE(_HRESULT, _c_void_p, _c_void_p)(vtbl[12])(dlg, item)   # SetFolder
                _CFUNCTYPE(_c_ulong, _c_void_p)(cast(item, POINTER(POINTER(_c_void_p)))[0][2])(item)

        hr = _CFUNCTYPE(_HRESULT, _c_void_p, wintypes.HWND)(vtbl[3])(dlg, _parent_hwnd())  # Show
        result = None
        if hr == 0:
            item = _c_void_p()
            if _CFUNCTYPE(_HRESULT, _c_void_p, POINTER(_c_void_p))(vtbl[20])(dlg, byref(item)) == 0 and item:
                ivtbl = cast(item, POINTER(POINTER(_c_void_p)))[0]
                pstr = wintypes.LPWSTR()
                # IShellItem vtable 5=GetDisplayName; SIGDN_FILESYSPATH=0x80058000
                if _CFUNCTYPE(_HRESULT, _c_void_p, _c_uint, POINTER(wintypes.LPWSTR))(
                        ivtbl[5])(item, 0x80058000, byref(pstr)) == 0 and pstr:
                    result = os.path.normpath(pstr.value)
                    ole32.CoTaskMemFree(pstr)
                _CFUNCTYPE(_c_ulong, _c_void_p)(ivtbl[2])(item)             # item.Release()
        _CFUNCTYPE(_c_ulong, _c_void_p)(vtbl[2])(dlg)                       # dlg.Release()
        return result
    finally:
        ole32.CoUninitialize()


# ---------------- 目录选择 (经典 SHBrowseForFolderW, 回退用) ----------------
_BFFM_SETSELECTION = 0x400 + 103
_BIF_RETURNONLYFSDIRS = 0x1
_BIF_NEWDIALOGSTYLE = 0x40


def _browse_callback_proc(hwnd, uMsg, lParam, lpData):
    """BROWSEINFO 回调: 初始化时把初始目录设为传入路径 (lpData)."""
    if uMsg == 1:   # BFFM_INITIALIZED
        sel = ctypes.cast(lpData, ctypes.c_wchar_p)
        if sel.value:
            ctypes.windll.user32.SendMessageW(hwnd, _BFFM_SETSELECTION, 1, sel.value)
    return 0


def _choose_directory_classic(title="选择目录", initial_dir=None):
    """Windows 经典目录选择对话框 (SHBrowseForFolderW). 返回目录路径, 取消 None."""
    class BROWSEINFO(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", wintypes.LPWSTR),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", wintypes.UINT),
            ("lpfn", ctypes.c_void_p),
            ("lParam", ctypes.c_void_p),
            ("iImage", ctypes.c_int),
        ]

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    try:
        buf = ctypes.create_unicode_buffer(260)
        init = ctypes.c_wchar_p(initial_dir or "")
        cb = ctypes.CFUNCTYPE(ctypes.c_int, wintypes.HWND, ctypes.c_uint,
                              ctypes.c_uint, ctypes.c_void_p)(_browse_callback_proc)
        bi = BROWSEINFO()
        bi.hwndOwner = _parent_hwnd()
        bi.pszDisplayName = buf
        bi.lpszTitle = title or "选择目录"
        bi.ulFlags = _BIF_RETURNONLYFSDIRS | _BIF_NEWDIALOGSTYLE
        bi.lpfn = ctypes.cast(cb, ctypes.c_void_p)
        bi.lParam = ctypes.cast(init, ctypes.c_void_p)
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if pidl:
            path = ctypes.create_unicode_buffer(260)
            if shell32.SHGetPathFromIDListW(pidl, path):
                return os.path.normpath(path.value)
        return None
    finally:
        ole32.CoUninitialize()


def choose_directory(title="选择目录", initial_dir=None):
    """选择目录 (系统文件管理器风格): 现代 IFileOpenDialog 优先, 失败回退经典对话框."""
    try:
        return _choose_directory_modern(title, initial_dir)
    except Exception:
        return _choose_directory_classic(title, initial_dir)
