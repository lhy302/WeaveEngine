# -*- coding: utf-8 -*-
"""无头测试: filedialog 结构体/对话框 + editor 保存目录 helper (不弹窗口)."""
import sys, os, tempfile, json, ctypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# ---------- filedialog ----------
import filedialog as fd
SIZE = ctypes.sizeof(fd.OPENFILENAMEW)
check("OPENFILENAMEW 大小=152 (64位)", SIZE == 152, "got %d" % SIZE)

def _ptr(dlg_ptr):
    return ctypes.cast(dlg_ptr, ctypes.POINTER(fd.OPENFILENAMEW)).contents

def fake_save(dlg_ptr):
    dlg = _ptr(dlg_ptr)
    src = ctypes.create_unicode_buffer(r"C:\Users\测试目录\我的场景")
    ctypes.memmove(dlg.lpstrFile, src, (len(src.value) + 1) * 2)
    return 1

def fake_cancel(dlg_ptr):
    return 0

p = fd._dialog(fake_save, "t", r"D:\my-project\保存", "场景",
               "场景\0*.json\0所有\0*.*\0\0", "json", 0x80000)
check("对话框读缓冲返回路径", p == os.path.normpath(r"C:\Users\测试目录\我的场景"), str(p))
p2 = fd._dialog(fake_cancel, "t", r"D:\my-project\保存", "场景",
                "场景\0*.json\0\0", "json", 0x80000)
check("取消返回 None", p2 is None)

# ---------- editor helpers ----------
import editor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 (随迁移自适应)
check("APP_DIR = 项目根", editor.APP_DIR == ROOT, editor.APP_DIR)
check("默认保存文件夹=应用目录/保存",
      editor.DEFAULT_SAVE_DIR == os.path.join(ROOT, "保存"),
      editor.DEFAULT_SAVE_DIR)

d = tempfile.mkdtemp()
check("空目录 -> base", editor.unique_default_name(d, "场景", ".json") == "场景")
open(os.path.join(d, "场景.json"), "w").write("")
check("base 冲突 -> base1", editor.unique_default_name(d, "场景", ".json") == "场景1")
open(os.path.join(d, "场景1.json"), "w").write("")
check("base/base1 冲突 -> base2",
      editor.unique_default_name(d, "场景", ".json") == "场景2")
check("带扩展名 base 去重", editor.unique_default_name(d, "场景.json", ".json") == "场景2")
check("空 base -> 场景", editor.unique_default_name(d, "", ".json") == "场景2")

sf = os.path.join(d, "state.json")
editor.save_last_dir(sf, os.path.join(d, "a.json"))
check("save_last_dir 写 state", os.path.exists(sf))
ld = editor.load_last_dir(sf)
check("load_last_dir 回读", ld == d, str(ld))
check("initial_dir(有 last) = last", editor.initial_dir(ld) == d)
editor.save_last_dir(sf, None)
check("save_last_dir(None) 不写", editor.load_last_dir(sf) == d)

# 失效目录兜底到默认保存目录
check("initial_dir(失效) -> 保存", editor.initial_dir(r"Z:\不存在\xxx") == editor.DEFAULT_SAVE_DIR)
check("initial_dir(None) -> 保存", editor.initial_dir(None) == editor.DEFAULT_SAVE_DIR)

# 筛选字符串 (含 \0)
check("场景筛选含 json", "*.json" in editor._SCENE_FILTER)
check("Prefab 筛选含 prefab", "*.prefab" in editor._PREFAB_FILTER)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
