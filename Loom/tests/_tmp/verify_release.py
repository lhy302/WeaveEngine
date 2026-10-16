#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""verify_release.py — Loom 编译版投放校验 (M2b, 2026-09-08)

背景 (第三方审计 R-5 / P9):
    源侧 DLL 重编后 PE 头部时间戳会变, 导致投放副本 SHA256 **必然**不同。
    实测 pipeline.dll / module_ref.dll / loom_kernels.dll 各差 6 字节
    (偏移 248-250 / 256-258 与 14708-14710 / 5956-5958 / 11188-11190),
    全在 PE 头部 (TimeDateStamp + CheckSum 区)。registry.json 与
    pipeline_glue.py 逐字节一致 -> 功能等价, 但「投放 SHA256 5/5 一致」
    的可复现性声明不成立。

结论: 投放校验不能只用哈希。本脚本改用 **导出符号集合 + 关键字符串 + 大小**
    作硬判据, SHA256 降级为软信息 (文本文件仍以 SHA256 为硬判据)。

判据:
    硬判据 (任一不满足 -> FAIL)
        DLL      : 存在性 + 大小一致 + 导出符号集合完全一致 + module_id 字面量命中
        文本文件 : 存在性 + 大小一致 + SHA256 一致 (文本应逐字节相同)
    软信息 (不判 FAIL)
        DLL 的 SHA256 不一致 -> 标注「PE 时间戳差异（预期）」

用法:
    py -3.12 tests\_tmp\verify_release.py
    py -3.12 tests\_tmp\verify_release.py --snapshot
    py -3.12 tests\_tmp\verify_release.py --src <源侧 Loom> --dst <编译版 Loom>

退出码: 0 = 全部 PASS, 1 = 存在 FAIL (含编译版缺失)。

纯标准库 (不依赖 pefile), PE 导出表自行解析。只读, 不修改任何文件
(--snapshot 只写 tests\_tmp\release_snapshot_<YYYYMMDD>.json)。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import struct
import sys
import unicodedata

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DEFAULT_SRC = r"D:\my-project\Loom(py源代码-工作区)\Loom"
DEFAULT_DST = r"D:\my-project\Loom(编译版)\Loom"
HERE = os.path.dirname(os.path.abspath(__file__))

#: 校验对象白名单 (rel 用 "/" 书写, 落盘时按 os.sep 拼接)
#: kind=dll  -> 走 PE 导出表 + 关键字符串硬判据
#: kind=text -> 走 SHA256 硬判据 (文本应逐字节一致)
ITEMS = (
    {"rel": "core_components/pipeline/pipeline.dll", "kind": "dll",
     "module_id": "pipeline"},
    {"rel": "core_components/module_ref.dll", "kind": "dll",
     "module_id": "module_ref"},
    {"rel": "ckernels/loom_kernels.dll", "kind": "dll",
     "module_id": "ckernels"},
    {"rel": "core_components/registry.json", "kind": "text"},
    {"rel": "core_components/module_loader.py", "kind": "text"},
    {"rel": "core_components/module_registry.py", "kind": "text"},
    {"rel": "pipeline_glue.py", "kind": "text"},
)

PASS, FAIL, INFO = "PASS", "FAIL", "INFO"
SKIP_FMT = "SKIP: 编译版不存在 %s"


# ---------------------------------------------------------------------------
# 输出编码: 重定向(管道/文件)时强制 UTF-8, 便于日志与审计采集;
# 交互式控制台沿用本机编码 (中文 Windows 为 cp936), 避免终端乱码。
# ---------------------------------------------------------------------------
def setup_stdout() -> None:
    try:
        if sys.stdout.isatty():
            sys.stdout.reconfigure(errors="replace")
        else:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 老环境/被包装的 stdout
        pass


# ---------------------------------------------------------------------------
# PE 解析 (标准库实现, 等价 pefile 的最小读导出表能力)
# ---------------------------------------------------------------------------
class PEFormatError(Exception):
    """PE 结构不可解析。"""


def _u16(buf: bytes, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _cstr(buf: bytes, off: int, limit: int = 512) -> str:
    end = buf.find(b"\x00", off, off + limit)
    if end < 0:
        end = min(off + limit, len(buf))
    return buf[off:end].decode("ascii", "replace")


def parse_pe_exports(data: bytes) -> tuple:
    """解析 PE 导出表。

    路径: DOS header(e_lfanew) -> NT headers -> OptionalHeader.DataDirectory[0]
          (Export Table) -> IMAGE_EXPORT_DIRECTORY -> AddressOfNames 数组
          -> 逐名读 ASCII 字符串。

    返回 (dll_name, exports_sorted, info)；无导出表时 exports 为空列表。
    info 含 machine / time_date_stamp / sections / magic, 供报告引用。
    """
    if len(data) < 0x40:
        raise PEFormatError("文件过短, 不是 PE")
    if data[:2] != b"MZ":
        raise PEFormatError("缺 DOS 头 (MZ) 签名")

    e_lfanew = _u32(data, 0x3C)
    if e_lfanew <= 0 or e_lfanew + 0x18 > len(data):
        raise PEFormatError("e_lfanew 越界: 0x%X" % e_lfanew)
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise PEFormatError("缺 NT 头 (PE\\0\\0) 签名 @0x%X" % e_lfanew)

    coff = e_lfanew + 4
    machine = _u16(data, coff)
    n_sections = _u16(data, coff + 2)
    time_date_stamp = _u32(data, coff + 4)
    size_opt = _u16(data, coff + 16)

    opt = coff + 20
    if size_opt < 2 or opt + size_opt > len(data):
        raise PEFormatError("OptionalHeader 越界 (SizeOfOptionalHeader=%d)" % size_opt)
    magic = _u16(data, opt)
    if magic == 0x20B:          # PE32+
        dd_off = opt + 112
    elif magic == 0x10B:        # PE32
        dd_off = opt + 96
    else:
        raise PEFormatError("未知 OptionalHeader Magic 0x%X" % magic)
    if dd_off + 8 > opt + size_opt:
        raise PEFormatError("DataDirectory 越界")

    export_rva = _u32(data, dd_off)          # DataDirectory[0] = Export Table
    export_size = _u32(data, dd_off + 4)

    # 节表 -> RVA 映射
    sec_off = opt + size_opt
    sections = []
    for i in range(n_sections):
        base = sec_off + i * 40
        if base + 40 > len(data):
            break
        sections.append((
            data[base:base + 8].rstrip(b"\x00").decode("ascii", "replace"),
            _u32(data, base + 12),                       # VirtualAddress
            max(_u32(data, base + 8), _u32(data, base + 16)),  # VirtualSize/RawSize
            _u32(data, base + 20),                       # PointerToRawData
            _u32(data, base + 16),                       # SizeOfRawData
        ))
    if not sections:
        raise PEFormatError("节表为空")

    def rva_to_off(rva: int) -> int:
        for _name, vaddr, vspan, rawptr, _rawsize in sections:
            if vaddr <= rva < vaddr + vspan:
                off = rawptr + (rva - vaddr)
                if off < len(data):
                    return off
        raise PEFormatError("RVA 0x%X 无法映射到文件偏移" % rva)

    info = {
        "machine": "0x%04X" % machine,
        "time_date_stamp": time_date_stamp,
        "time_date_stamp_utc": datetime.datetime.fromtimestamp(
            time_date_stamp, datetime.timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC")
        if 0 < time_date_stamp < 4102444800 else "(无效)",
        "sections": len(sections),
        "magic": "PE32+" if magic == 0x20B else "PE32",
        "export_rva": export_rva,
        "export_size": export_size,
    }

    if export_rva == 0 or export_size == 0:
        return "", [], info

    ed = rva_to_off(export_rva)
    if ed + 40 > len(data):
        raise PEFormatError("IMAGE_EXPORT_DIRECTORY 越界")
    name_rva = _u32(data, ed + 12)
    n_functions = _u32(data, ed + 20)
    n_names = _u32(data, ed + 24)
    addr_names = _u32(data, ed + 32)
    info["n_functions"] = n_functions
    info["n_names"] = n_names

    dll_name = ""
    if name_rva:
        try:
            dll_name = _cstr(data, rva_to_off(name_rva))
        except PEFormatError:
            dll_name = ""

    names = []
    if n_names:
        names_off = rva_to_off(addr_names)
        for i in range(n_names):
            if names_off + i * 4 + 4 > len(data):
                break
            nrva = _u32(data, names_off + i * 4)
            try:
                names.append(_cstr(data, rva_to_off(nrva)))
            except PEFormatError:
                names.append("<bad-rva:0x%08X>" % nrva)
    return dll_name, sorted(set(names)), info


# ---------------------------------------------------------------------------
# 文件侧采集
# ---------------------------------------------------------------------------
def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mtime_of(path: str) -> str:
    try:
        return datetime.datetime.fromtimestamp(
            os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""


def probe(path: str, kind: str) -> dict:
    """采集一侧的信息。只读。"""
    rec = {
        "path": path,
        "exists": os.path.isfile(path),
        "size": None,
        "sha256": None,
        "mtime": "",
        "exports": [],
        "exports_error": "",
        "pe": {},
    }
    if not rec["exists"]:
        return rec
    rec["size"] = os.path.getsize(path)
    rec["sha256"] = sha256_of(path)
    rec["mtime"] = mtime_of(path)
    if kind == "dll":
        try:
            data = open(path, "rb").read()
            _dll_name, exports, info = parse_pe_exports(data)
            rec["exports"] = exports
            rec["pe"] = info
        except (PEFormatError, OSError, struct.error) as exc:
            rec["exports_error"] = "%s: %s" % (type(exc).__name__, exc)
    return rec


def find_key_strings(path: str, literals) -> dict:
    """在二进制里查 module_id 字面量; 返回 {literal: offset 或 -1}。"""
    hits = {}
    try:
        data = open(path, "rb").read()
    except OSError:
        return {lit: -1 for lit in literals}
    for lit in literals:
        hits[lit] = data.find(lit.encode("ascii"))
    return hits


def rec_sha_equal(a: dict, b: dict) -> bool:
    return bool(a["sha256"]) and a["sha256"] == b["sha256"]


def diff_offsets(a: bytes, b: bytes, cap: int = 8) -> tuple:
    """返回 (差异字节数, 差异偏移片段列表, 长度差)。"""
    n = min(len(a), len(b))
    offs = [i for i in range(n) if a[i] != b[i]]
    return len(offs), offs[:cap], abs(len(a) - len(b))


# ---------------------------------------------------------------------------
# 单项校验
# ---------------------------------------------------------------------------
def verify_item(item: dict, src_root: str, dst_root: str, index: int, total: int):
    rel = item["rel"]
    kind = item["kind"]
    src_path = os.path.join(src_root, rel.replace("/", os.sep))
    dst_path = os.path.join(dst_root, rel.replace("/", os.sep))

    src = probe(src_path, kind)
    dst = probe(dst_path, kind)

    checks = []          # (名称, 判定, 说明)
    notes = []           # 软信息

    # 1) 存在性
    if not src["exists"]:
        checks.append(("存在性", FAIL, "源侧缺失: %s" % src_path))
    elif not dst["exists"]:
        print(SKIP_FMT % dst_path)
        checks.append(("存在性", FAIL, "编译版缺失: %s" % dst_path))
    else:
        checks.append(("存在性", PASS, "源侧=有, 编译版=有"))

    both = src["exists"] and dst["exists"]

    # 2) 大小
    if both:
        if src["size"] == dst["size"]:
            checks.append(("大小", PASS, "%d B == %d B" % (src["size"], dst["size"])))
        else:
            checks.append(("大小", FAIL, "%d B != %d B (差 %+d)"
                           % (src["size"], dst["size"], dst["size"] - src["size"])))

    # 3) SHA256
    if both:
        same = src["sha256"] == dst["sha256"]
        if same:
            if kind == "text":
                checks.append(("SHA256", PASS, "一致 %s..." % src["sha256"][:16]))
            else:
                notes.append(("SHA256", INFO, "一致 %s..." % src["sha256"][:16]))
        else:
            if kind == "dll":
                notes.append(("SHA256", INFO, "不一致 → PE 时间戳差异（预期）"))
                notes.append(("", "", "  src=%s" % src["sha256"]))
                notes.append(("", "", "  dst=%s" % dst["sha256"]))
            else:
                checks.append(("SHA256", FAIL,
                               "文本文件不一致 → 内容已漂移 (src=%s dst=%s)"
                               % (src["sha256"][:16], dst["sha256"][:16])))

    # 4) 导出符号集合 (仅 DLL)
    if kind == "dll":
        if src["exports_error"]:
            checks.append(("导出符号", FAIL, "源侧 PE 解析失败: %s" % src["exports_error"]))
        elif dst["exports_error"]:
            checks.append(("导出符号", FAIL, "编译版 PE 解析失败: %s" % dst["exports_error"]))
        elif not src["exports"]:
            checks.append(("导出符号", FAIL, "源侧无导出表 (0 个导出)"))
        elif set(src["exports"]) == set(dst["exports"]):
            checks.append(("导出符号", PASS, "%d 个完全一致: %s"
                           % (len(src["exports"]), ", ".join(src["exports"]))))
        else:
            only_src = sorted(set(src["exports"]) - set(dst["exports"]))
            only_dst = sorted(set(dst["exports"]) - set(src["exports"]))
            checks.append(("导出符号", FAIL,
                           "集合不一致: 仅源侧=%s 仅编译版=%s"
                           % (only_src or "无", only_dst or "无")))

        # 5) 关键字符串 (module_id 字面量)
        lit = item.get("module_id")
        if lit:
            s_hits = find_key_strings(src_path, [lit]) if src["exists"] else {lit: -1}
            d_hits = find_key_strings(dst_path, [lit]) if dst["exists"] else {lit: -1}
            s_ok = s_hits.get(lit, -1) >= 0
            d_ok = d_hits.get(lit, -1) >= 0
            if s_ok and d_ok:
                checks.append(("关键字符串", PASS,
                               "'%s' 命中 (src@0x%X, dst@0x%X)"
                               % (lit, s_hits[lit], d_hits[lit])))
            else:
                miss = []
                if not s_ok:
                    miss.append("源侧")
                if not d_ok:
                    miss.append("编译版")
                checks.append(("关键字符串", FAIL,
                               "module_id 字面量 '%s' 在 %s 二进制中未命中 "
                               "(可能被编译器优化/改名, 需人工确认)"
                               % (lit, "/".join(miss))))

        # 6) PE 时间戳 / 字节差异 (软信息)
        if both and not rec_sha_equal(src, dst):
            try:
                a = open(src_path, "rb").read()
                b = open(dst_path, "rb").read()
                n_diff, sample, len_delta = diff_offsets(a, b)
                notes.append(("PE 时间戳", INFO,
                              "src=%s / dst=%s"
                              % (src["pe"].get("time_date_stamp_utc", "?"),
                                 dst["pe"].get("time_date_stamp_utc", "?"))))
                notes.append(("字节差异", INFO,
                              "%d 字节%s 偏移示例=%s"
                              % (n_diff,
                                 "" if len_delta == 0 else " (长度差 %d)" % len_delta,
                                 ", ".join(str(x) for x in sample) or "-")))
            except OSError:
                pass

    verdict = FAIL if any(c[1] == FAIL for c in checks) else PASS
    return {
        "rel": rel, "kind": kind, "index": index, "total": total,
        "module_id": item.get("module_id", ""),
        "src": src, "dst": dst,
        "checks": checks, "notes": notes, "verdict": verdict,
        "size_equal": (both and src["size"] == dst["size"]),
        "sha256_equal": (both and src["sha256"] == dst["sha256"]),
        "exports_equal": (kind == "dll" and bool(src["exports"])
                          and set(src["exports"]) == set(dst["exports"])),
    }


# ---------------------------------------------------------------------------
# 打印
# ---------------------------------------------------------------------------
def _dwidth(text: str) -> int:
    """终端显示宽度 (CJK 全角算 2 列), 用于表格对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _dwidth(text))


def print_report(records, src_root, dst_root) -> None:
    print("=== Loom M2b 投放校验 (导出符号 + 关键字符串 + 大小) ===")
    print("时间    : %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("源侧    : %s" % src_root)
    print("编译版  : %s" % dst_root)
    print("判据    : 硬=存在性/大小/导出符号(文本为SHA256)+module_id字符串; "
          "软=DLL SHA256 (PE 时间戳差异属预期)")
    print()

    for rec in records:
        tag = "DLL" if rec["kind"] == "dll" else "TEXT"
        print("--- [%d/%d] %s (%s) ---"
              % (rec["index"], rec["total"], rec["rel"], tag))
        for name, state, detail in rec["checks"]:
            print("  %s: %-4s %s" % (_pad(name, 12), state, detail))
        for name, state, detail in rec["notes"]:
            if name:
                print("  %s: %-4s %s" % (_pad(name, 12), state, detail))
            else:
                print("  %s  %-4s %s" % (_pad("", 12), "", detail))
        print("  %s: %s" % (_pad("判定", 12), rec["verdict"]))
        print()

    # 四列汇总表 (存在性 / 大小 / SHA256 / 导出符号)
    cols = [("#", 3), ("项目", 46), ("存在性", 8), ("大小", 8),
            ("SHA256", 8), ("导出符号", 10), ("判定", 4)]
    header = " ".join(_pad(t, w) for t, w in cols)
    print("=== 明细汇总 (存在性 / 大小 / SHA256 / 导出符号) ===")
    print(header)
    print("-" * _dwidth(header))
    for rec in records:
        by_name = {c[0]: c[1] for c in rec["checks"]}
        both = rec["src"]["exists"] and rec["dst"]["exists"]
        existence = by_name.get("存在性", FAIL)
        size = by_name.get("大小", "-" if both else FAIL)
        if rec["kind"] == "dll":
            sha = "INFO"          # 软信息: PE 时间戳差异不判 FAIL
            exports = by_name.get("导出符号", "-" if both else FAIL)
        else:
            sha = by_name.get("SHA256", "-" if both else FAIL)
            exports = "-"
        cells = [str(rec["index"]), rec["rel"], existence, size, sha,
                 exports, rec["verdict"]]
        print(" ".join(_pad(c, w) for c, (_t, w) in zip(cells, cols)))
    print("-" * _dwidth(header))
    print("注: DLL 的 SHA256 列为软信息 (PE 时间戳差异属预期, 不判 FAIL); "
          "文本文件 SHA256 为硬判据。")

    n_pass = sum(1 for r in records if r["verdict"] == PASS)
    n_fail = len(records) - n_pass
    print()
    print("=== 汇总: %d 项 PASS / %d 项 FAIL ===" % (n_pass, n_fail))


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------
def write_snapshot(records, src_root, dst_root, out_dir: str) -> str:
    day = datetime.datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(out_dir, "release_snapshot_%s.json" % day)

    def side(rec, key):
        s = rec[key]
        return {
            "path": s["path"],
            "exists": s["exists"],
            "size": s["size"],
            "sha256": s["sha256"],
            "mtime": s["mtime"],
            "exports": s["exports"],
        }

    payload = {
        "_format": "loom-release-snapshot/1.0",
        "_doc": ("Loom 投放时刻快照。硬判据 = 大小 + 导出符号集合 (+文本 SHA256); "
                 "DLL 的 SHA256 因 PE 时间戳可能两侧不同, 属预期, 仅供追溯。"),
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generated_by": "tests/_tmp/verify_release.py --snapshot",
        "src_root": src_root,
        "dst_root": dst_root,
        "items": [],
        "summary": {},
    }
    for rec in records:
        payload["items"].append({
            "rel": rec["rel"],
            "kind": rec["kind"],
            "module_id": rec["module_id"],
            "src": side(rec, "src"),
            "dst": side(rec, "dst"),
            "size_equal": rec["size_equal"],
            "exports_equal": rec["exports_equal"],
            "sha256_equal": rec["sha256_equal"],
            "verdict": rec["verdict"],
        })
    n_pass = sum(1 for r in records if r["verdict"] == PASS)
    payload["summary"] = {"total": len(records), "pass": n_pass,
                          "fail": len(records) - n_pass}

    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return out_path


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    setup_stdout()
    ap = argparse.ArgumentParser(
        description="Loom 编译版投放校验 (导出符号 + 关键字符串 + 大小)")
    ap.add_argument("--src", default=DEFAULT_SRC, help="源侧引擎根 (默认 %s)" % DEFAULT_SRC)
    ap.add_argument("--dst", default=DEFAULT_DST, help="编译版引擎根 (默认 %s)" % DEFAULT_DST)
    ap.add_argument("--snapshot", action="store_true",
                    help="校验后写 tests\\_tmp\\release_snapshot_<YYYYMMDD>.json")
    ap.add_argument("--snapshot-dir", default=HERE, help="快照输出目录 (默认脚本同目录)")
    args = ap.parse_args(argv)

    src_root = os.path.abspath(args.src)
    dst_root = os.path.abspath(args.dst)

    if not os.path.isdir(src_root):
        print("错误: 源侧目录不存在: %s" % src_root)
        return 1

    records = [verify_item(item, src_root, dst_root, i + 1, len(ITEMS))
               for i, item in enumerate(ITEMS)]
    print_report(records, src_root, dst_root)

    if args.snapshot:
        try:
            out = write_snapshot(records, src_root, dst_root, args.snapshot_dir)
            print()
            print("快照已写入: %s" % out)
        except OSError as exc:
            print("快照写入失败: %s" % exc)
            return 1

    return 0 if all(r["verdict"] == PASS for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
