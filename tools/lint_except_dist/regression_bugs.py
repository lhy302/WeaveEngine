# -*- coding: utf-8 -*-
"""regression_bugs.py — 验证审计报告 6 个 BUG 已修复（0.1.1）。

用法: python regression_bugs.py /path/to/loom_lint_except.py
退出码: 0 = 全部修复；1 = 有未修复项

期望值为"修复后"的行为：
  BUG-01: return {"ok": True}       → 1 ERROR（不再被当已上报）
  BUG-02: msg = "error: ..."         → 1 ERROR（Name 赋值不算上报）
  BUG-04: check_config()             → 1 ERROR（白名单已移除 check 前缀）
  BUG-05: except Exception: pass     → 1 ERROR / 0 WARN（宽异常提示合并进 ERROR message）
  BUG-06: except Exception: pass # _ignore_, 理由 → 0 / 0（_ignore_ 豁免宽异常 WARN）
"""
import json
import os
import subprocess
import sys
import tempfile

LINT = sys.argv[1] if len(sys.argv) > 1 else "loom_lint_except.py"

CASES = [
    ("BUG-01", 'def f():\n    try:\n        x = 1 / 0\n    except ValueError:\n        return {"ok": True}\n',
     (1, 0), "return {'ok': True} 应报 ERROR"),
    ("BUG-02", 'def f():\n    try:\n        x = 1 / 0\n    except ValueError:\n        msg = "error: something went wrong"\n',
     (1, 0), "Name 赋值字符串不应算上报"),
    ("BUG-04", 'def check_config():\n    return False\n\ndef f(cfg):\n    try:\n        return cfg["k"]\n    except KeyError:\n        check_config()\n',
     (1, 0), "check_config() 不应被白名单命中"),
    ("BUG-05", 'def f():\n    try:\n        x = 1 / 0\n    except Exception:\n        pass\n',
     (1, 0), "ERROR 与宽异常应合并为一条"),
    ("BUG-06", 'def f():\n    try:\n        x = 1 / 0\n    except Exception:\n        pass  # _ignore_, 这里确实无所谓\n',
     (0, 0), "_ignore_ 带理由应豁免宽异常 WARN"),
    ("OBS-01", 'def f():\n    try:\n        x = 1 / 0\n    except ValueError:\n        return True\n',
     (1, 0), "return True 应视为静默默认值（与 False 对称）"),
]

def run(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write(src)
        path = fh.name
    try:
        out = subprocess.run([sys.executable, LINT, path, "--json"],
                             capture_output=True, text=True, encoding="utf-8")
        data = json.loads(out.stdout)
        return data["errors"], data["warnings"], [v["kind"] for v in data["violations"]]
    finally:
        os.unlink(path)

def main():
    fails = 0
    for bug_id, src, expected, note in CASES:
        e, w, kinds = run(src)
        ok = (e, w) == expected
        print(("PASS" if ok else "FAIL"), bug_id,
              "实际=(%d,%d) 期望=(%d,%d) kinds=%r | %s"
              % (e, w, expected[0], expected[1], kinds, note))
        if not ok:
            fails += 1
    print()
    if fails:
        print("有 %d 项未修复" % fails)
        return 1
    print("全部已修复 [OK]")
    return 0

if __name__ == "__main__":
    sys.exit(main())
