# -*- coding: utf-8 -*-
"""loom_lint_except.py — 异常处理契约检查（模拟 Rust 的强制错误处理）

================================================================================
设计哲学
================================================================================
Rust 通过类型系统强制每个 Result 必须被处理（? / unwrap / match），
Python 没有这个机制，导致 "except: pass" 变成开发者的默认惰性选择。

本工具用静态分析模拟 Rust 的强制检查：
  每个 except 分支必须明确表达意图：
    A) 我处理了这个错误   → raise / 上报 / 日志 / UI / return error
    B) 我故意忽略这个错误 → # _ignore_, <为什么可以忽略>
    C) 我故意用宽异常兜底 → # _broad_, <为什么不能细化异常类型>

================================================================================
异常反馈方式清单（判定基准）
================================================================================
E1  raise / raise X from Y            → 调用方处理
E2  print(...) / sys.stdout.write    → 控制台输出
E3  print(..., file=sys.stderr)      → 错误流
E4  logging.* / logger.*             → 标准日志
E5  warnings.warn                    → 警告通道
E6  traceback.print_exc / format_exc → 含栈诊断
E7  _report_error(...) / self._error → 引擎统一通道（推荐）
E8  UI toast / 状态栏                → 用户可见
E9  写文件 loom_error.log            → 持久化
E10 return {'error': ...}            → 调用方判断
E11 crash_reporter                   → 崩溃转储
E12 assert / 硬错                    → 立即失败
E13 # _ignore_, <理由>               → 显式忽略（本工具标记）

E1–E12 = 已处理；E13 = 显式忽略；都没有 = 静默吞错。

================================================================================
标记协议（严格定义）
================================================================================
  # _ignore_, <理由>    → 声明"这个错误可以忽略"（无上报也可 PASS）
  # _broad_, <理由>     → 声明"这里必须用 Exception/BaseException 兜底"
  大小写不敏感；必须出现在 except handler 的行范围内。

判定表：
  ┌──────────────────────┬──────────┬───────────────────────┐
  │ 有上报                │ 有标记    │ 结果                   │
  ├──────────────────────┼──────────┼───────────────────────┤
  │ 是                    │ —        │ PASS（宽异常需 _broad_）│
  │ 否                    │ _ignore_ │ PASS                  │
  │ 否                    │ 无       │ ERROR（静默吞错）       │
  │ 否 / 是               │ _ignore_ 无理由 │ WARN（缺理由）   │
  │ 是 / 否               │ Exception 无 _broad_ │ WARN（宽异常未声明）│
  └──────────────────────┴──────────┴───────────────────────┘

================================================================================
用法
================================================================================
  py -3.12 tools/loom_lint_except.py                # 检查当前目录
  py -3.12 tools/loom_lint_except.py Loom/          # 检查指定目录
  py -3.12 tools/loom_lint_except.py --json         # JSON 输出（CI 用）
  py -3.12 tools/loom_lint_except.py --summary      # 只显示统计
  py -3.12 tools/loom_lint_except.py --strict-return # return None 也算 ERROR
  py -3.12 tools/loom_lint_except.py --no-broad     # 关闭宽异常检查

退出码：0 = 全部通过；1 = 有 ERROR；2 = 有 WARN 且 --warn-as-error
"""

import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

# ============================================================================
# 规则定义
# ============================================================================

# 标记：# _ignore_[, 理由] / # _broad_[, 理由]
# 理由用 [^#\n]* 而非 .*，允许一行里出现多个标记（如 "# _ignore_, a  # _broad_, b"）
MARKER_IGNORE_RE = re.compile(r'#\s*_ignore_\b(?:\s*,\s*([^#\n]*))?', re.IGNORECASE)
MARKER_BROAD_RE = re.compile(r'#\s*_broad_\b(?:\s*,\s*([^#\n]*))?', re.IGNORECASE)

# 上报调用白名单
REPORTING_NAMES = {
    # 引擎统一上报
    '_report_error', 'report_error', 'report', 'notify_error',
    'self._error', 'self.error', 'self._report_error', 'self._report',
    # 标准诊断
    'print', 'log', 'logger',
    'traceback', 'traceback.print_exc', 'traceback.format_exc',
    'print_exc', 'format_exc',
    'stderr', 'stdout', 'sys',
    # 日志模块
    'logging', 'warnings',
    # 自定义上报
    'crash_reporter', 'crash',
    # HTTP 响应
    '_json', 'send_response', 'send_error', 'send_header',
    # UI 通知
    'toast', 'notify', 'show_error', 'show_toast', 'flash',
    'set_status', 'show_status', 'report_to_ui',
    # 断言
    'assert_', 'ensure', 'require', 'check',
}

REPORTING_PREFIXES = (
    'print(', 'log(', 'logger.',
    'logging.', 'warnings.',
    'traceback.', 'sys.stderr', 'sys.stdout',
    'self._report', 'self.report', 'self._error',
    '_report_error', 'report_error',
    'crash_reporter.',
)

# 只认错误语义 key。'ok' / 'success' 会导致 {"ok": True}（出错却返回成功）被误判为已上报。
# 依据：README E10 只授权 return {'error': ...} 作为错误上报。
SENTINEL_KEYS = {'error', 'err', 'errors', 'failed'}

# 2026-10-20 审计修复 BUG-02：去掉裸 'error'（会命中 "no error" / "error_count" 等误报），
# 改为强信号 'error:'（带冒号，表示"错误: xxx"格式）。
ERROR_STRING_HINTS = (
    'error:', 'err:', 'err=', 'failed', 'fail:', 'exception',
    'traceback', 'invalid', '失败', '错误', '异常',
)

# 过宽异常类型
BROAD_EXC_TYPES = {'Exception', 'BaseException'}

STRICT_RETURN = False
CHECK_BROAD = True


# ============================================================================
# 工具函数
# ============================================================================

def match_marker(comment_text, regex):
    """匹配标记注释。返回 (matched, reason)。"""
    m = regex.search(comment_text)
    if not m:
        return False, False
    reason = (m.group(1) or '').strip()
    return True, bool(reason)


def name_of_call(node):
    """从 ast.Call 提取被调对象的可读名称。"""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = []
        cur = func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        parts.reverse()
        return '.'.join(parts)
    return None


def call_matches_whitelist(name):
    if not name:
        return False
    if name in REPORTING_NAMES:
        return True
    for prefix in REPORTING_PREFIXES:
        if name.startswith(prefix.rstrip('(')):
            return True
    if name + '(' in REPORTING_PREFIXES:
        return True
    return False


def string_contains_error_hint(s):
    if not isinstance(s, str):
        return False
    low = s.lower()
    return any(h in low for h in ERROR_STRING_HINTS)


def is_silent_default_literal(node):
    """判断 return 的值是否是"静默默认值"（None/0/False/''/[]/{}）。
    这类 return 丢失了错误信息——调用方无法区分"真的没有数据"和"出错了"。
    从 Rust 视角看是静默失败（应报 ERROR）。
    """
    if node is None:  # 裸 return
        return True
    if isinstance(node, ast.Constant):
        v = node.value
        # 2026-10-20 审计修复 OBS-01：True 与 False 对称。
        # except: return True 把失败包装成"成功"，是最危险的静默失败。
        if v is None or v is False or v is True:
            return True
        if isinstance(v, (int, float)) and v == 0:
            return True
        if isinstance(v, str) and v == '':
            return True
    if isinstance(node, ast.List) and not node.elts:
        return True
    if isinstance(node, ast.Dict):
        if not node.keys:
            return True
        # 2026-10-20 审计修复 BUG-01 补充：非空字面量 dict 不含错误键 → 静默返回。
        # 例：except: return {"ok": True} —— 出错却返回"成功"，调用方无法区分。
        # 保守限制：只处理所有 key/value 都是 ast.Constant 的 dict（变量 value 可能是错误对象，不判）。
        keys = set()
        all_literal = True
        for k in node.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
            else:
                all_literal = False
                break
        if all_literal:
            for v in node.values:
                if not isinstance(v, ast.Constant):
                    all_literal = False
                    break
        if all_literal and not (keys & SENTINEL_KEYS):
            return True
        return False
    return False


def expr_reports_error(node):
    """判断表达式是否把错误写进值（= 上报给调用方）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return string_contains_error_hint(node.value)
    if isinstance(node, ast.JoinedStr):
        for v in node.values:
            if isinstance(v, ast.Constant) and string_contains_error_hint(v.value):
                return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        if isinstance(node.left, ast.Constant) and string_contains_error_hint(node.left.value):
            return True
    if isinstance(node, ast.Dict):
        for k in node.keys:
            if isinstance(k, ast.Constant) and string_contains_error_hint(str(k.value)):
                return True
    return False


def analyze_handler_body(handler):
    """分析 except handler 体，返回 (has_handling, kind, only_pass_continue)。"""
    has_handling = False
    kind = None
    only_pass_continue = True

    for stmt in handler.body:
        if isinstance(stmt, ast.Pass) or isinstance(stmt, ast.Continue):
            continue
        only_pass_continue = False

        if isinstance(stmt, ast.Raise):
            if not has_handling:
                has_handling, kind = True, 'raise'
            continue

        # 2026-10-20 审计修复 BUG-02：
        # 只有赋值给容器元素（out[k] = ...）才可能是"往返回值里塞错误"。
        # 裸变量赋值（msg = "error: ..."）是局部变量，没人看得到，不算上报。
        # 依据：README E 清单未授权"给局部变量赋一个字符串"作为上报方式。
        if isinstance(stmt, ast.Assign):
            tgt0 = stmt.targets[0] if stmt.targets else None
            if isinstance(tgt0, ast.Subscript) and expr_reports_error(stmt.value):
                if not has_handling:
                    has_handling, kind = True, 'assign:error-string'
                continue
        if isinstance(stmt, ast.AugAssign):
            if isinstance(stmt.target, ast.Subscript) and expr_reports_error(stmt.value):
                if not has_handling:
                    has_handling, kind = True, 'augassign:error-string'
                continue

        for child in ast.walk(stmt):
            if isinstance(child, ast.Call):
                nm = name_of_call(child)
                if call_matches_whitelist(nm):
                    if not has_handling:
                        has_handling, kind = True, ('call:%s' % (nm or '?'))
                    break
            if isinstance(child, ast.Return):
                v = child.value
                if isinstance(v, ast.Dict):
                    keys = set()
                    for k in v.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.add(k.value)
                    if keys & SENTINEL_KEYS:
                        if not has_handling:
                            has_handling, kind = True, 'return:error-dict'
                        break
                if expr_reports_error(v):
                    if not has_handling:
                        has_handling, kind = True, 'return:error-string'
                    break
                # 2026-10-20: return 字面量常量（None/0/''/False/[]）丢失错误信息，
                # 不算"已处理"。只有 return {'error': ...} / return 变量才算。
                if is_silent_default_literal(v):
                    break
                if not STRICT_RETURN:
                    if not has_handling:
                        has_handling, kind = True, 'return:value'
                    break
        if has_handling:
            break

    return has_handling, kind, only_pass_continue


def exc_type_is_broad(handler):
    """判断 except 的类型是否过宽（Exception / BaseException / 裸 except）。"""
    if handler.type is None:
        return True, 'bare-except'
    try:
        s = ast.unparse(handler.type)
    except Exception:  # _ignore_, ast.unparse 对畸形 AST 节点会失败，此处返回保守值  # _broad_, 任何失败都说明 AST 无法字符串化
        return False, None
    # 精确匹配 Exception / BaseException
    if s in BROAD_EXC_TYPES:
        return True, s
    # 元组里含 Exception
    if isinstance(handler.type, ast.Tuple):
        for elt in handler.type.elts:
            try:
                es = ast.unparse(elt)
            except Exception:  # _ignore_, 元组单个元素无法解析时跳过该元素  # _broad_, 同上
                continue
            if es in BROAD_EXC_TYPES:
                return True, s
    return False, s


# ============================================================================
# 单文件分析
# ============================================================================

class ExceptVisitor(ast.NodeVisitor):
    def __init__(self, file_path, source, comments_by_line):
        self.file_path = file_path
        self.source = source
        self.comments_by_line = comments_by_line
        self.context_stack = []
        self.violations = []

    def _ctx(self):
        if not self.context_stack:
            return '<module>'
        return ' > '.join('%s:%s' % (t, n) for t, n in self.context_stack)

    def visit_FunctionDef(self, node):
        self.context_stack.append(('fn', node.name))
        try:
            self.generic_visit(node)
        finally:
            self.context_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.context_stack.append(('class', node.name))
        try:
            self.generic_visit(node)
        finally:
            self.context_stack.pop()

    def visit_Try(self, node):
        for handler in node.handlers:
            self._check_handler(handler)
        self.generic_visit(node)

    def _find_markers(self, handler):
        """在 handler 行范围内找标记。返回 (ignore_reason, broad_reason, lines)。"""
        start = handler.lineno
        end = getattr(handler, 'end_lineno', None) or start
        ignore_reason = None
        broad_reason = None
        ignore_line = None
        broad_line = None
        for ln in range(start, end + 1):
            for c in self.comments_by_line.get(ln, []):
                m, r = match_marker(c, MARKER_IGNORE_RE)
                if m:
                    ignore_reason = r
                    ignore_line = ln
                # 注意：不 continue —— 同一行里可能同时有 _ignore_ 和 _broad_
                m2, r2 = match_marker(c, MARKER_BROAD_RE)
                if m2:
                    broad_reason = r2
                    broad_line = ln
        return ignore_reason, broad_reason, ignore_line, broad_line

    def _check_handler(self, handler):
        exc_type_str = '?'
        try:
            if handler.type is not None:
                exc_type_str = ast.unparse(handler.type)
            else:
                exc_type_str = '<bare>'
        except Exception:  # _ignore_, AST 无法字符串化时用占位符，不影响后续判定  # _broad_, 同上
            exc_type_str = '<无法解析>'

        is_broad, broad_kind = exc_type_is_broad(handler)
        has_handling, handling_kind, only_pass_continue = analyze_handler_body(handler)
        ignore_reason, broad_reason, ignore_line, broad_line = self._find_markers(handler)

        # ---- 判定 1：静默吞错（ERROR）----
        # 2026-10-20 审计修复 BUG-05：ERROR 时不再额外 append 一条 broad WARN
        # （同一 file:line 双报会让用户修完 ERROR 后仍看到 WARN，误以为没修好）。
        # 宽异常提示合并进 ERROR 的 message。
        if not has_handling and ignore_reason is None:
            msg = ('except 体无任何上报（raise / print / 日志 / return error），'
                   '也无 _ignore_ 标记。二选一：'
                   '① 加日志/上报；② 若确实可忽略，加 "# _ignore_, <理由>"')
            if is_broad and CHECK_BROAD and broad_reason is None:
                msg += (' 此外：异常类型 %r 过宽，建议细化（如 ValueError / OSError），'
                        '确需宽兜底时加 "# _broad_, <为什么>"' % exc_type_str)
            self.violations.append({
                'file': self.file_path,
                'line': handler.lineno,
                'context': self._ctx(),
                'exc_type': exc_type_str,
                'severity': 'ERROR',
                'kind': 'silent-pass' if only_pass_continue else 'no-handling',
                'message': msg,
            })
            return

        # ---- 判定 2：有 _ignore_ 标记但缺理由（WARN）----
        if not has_handling and ignore_reason is False:
            self.violations.append({
                'file': self.file_path,
                'line': handler.lineno,
                'marker_line': ignore_line,
                'context': self._ctx(),
                'exc_type': exc_type_str,
                'severity': 'WARN',
                'kind': 'ignore-no-reason',
                'message': (
                    '有 _ignore_ 标记，但缺"为什么可以忽略"的理由。'
                    '推荐格式：# _ignore_, <可忽略的原因>'
                ),
            })

        # ---- 判定 3：过宽异常但无 _broad_ 声明（WARN）----
        # 2026-10-20 审计修复 BUG-06：加 ignore_reason is None 条件。
        # 依据 README 判定表第 2 行「无上报 + _ignore_ 带理由 → PASS」：
        # 用户已用 _ignore_ 显式声明"忽略"，再要求 _broad_ 是重复约束。
        # 原注释"降低为静默 / 还是报 WARN"自相矛盾，一并删除。
        if is_broad and CHECK_BROAD and broad_reason is None and ignore_reason is None:
            self.violations.append({
                'file': self.file_path,
                'line': handler.lineno,
                'context': self._ctx(),
                'exc_type': exc_type_str,
                'severity': 'WARN',
                'kind': 'broad-exception',
                'message': (
                    '过宽异常类型 %r。建议细化（如 ValueError / OSError）；'
                    '确需宽兜底时加 "# _broad_, <为什么>"'
                    % exc_type_str
                ),
            })


def collect_comments(source):
    comments = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                comments.setdefault(tok.start[0], []).append(tok.string)
    except tokenize.TokenError:  # _ignore_, 源码不完整（如多行字符串未闭合）时 tokenize 抛此异常，用已收集到的注释继续工作
        pass
    return comments


def check_file(path):
    try:
        source = Path(path).read_text(encoding='utf-8', errors='replace')
    except Exception as e:  # _broad_, 读文件可能遇到权限/编码/IO 等各类异常，统一返回 read-error 上报调用方
        return [{
            'file': str(path), 'line': 0, 'severity': 'ERROR',
            'kind': 'read-error', 'message': '读文件失败: %r' % e,
        }]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [{
            'file': str(path), 'line': e.lineno or 0, 'severity': 'ERROR',
            'kind': 'syntax-error', 'message': '语法错误: %s' % e.msg,
        }]

    comments = collect_comments(source)
    visitor = ExceptVisitor(str(path).replace('\\', '/'), source, comments)
    visitor.visit(tree)
    return visitor.violations


# ============================================================================
# CLI
# ============================================================================

# 2026-10-20 审计修复 BUG-03：只排除 __pycache__ 会把 venv / node_modules 里几千个
# 第三方 .py 也扫进来（第三方库没有义务遵守 _ignore_ 协议），报告被淹没。
# 与 try_it.py / lint_exe_entry.py 的 EXCLUDE_DIRS 对齐（此前两边不一致）。
EXCLUDE_DIRS = {'__pycache__', '.git', 'node_modules', 'venv', '.venv', 'env',
                '.idea', '.vscode', 'build', 'dist', '.tox', '.mypy_cache',
                '.pytest_cache', 'site-packages'}


def iter_py_files(paths):
    for p in paths:
        pp = Path(p)
        if pp.is_file() and pp.suffix == '.py':
            yield pp
        elif pp.is_dir():
            for f in pp.rglob('*.py'):
                parts = {x.lower() for x in f.parts}
                if parts & EXCLUDE_DIRS:
                    continue
                yield f


def main(argv):
    global STRICT_RETURN, CHECK_BROAD

    paths = []
    json_out = False
    summary_only = False
    warn_as_error = False
    for a in argv[1:]:
        if a == '--json':
            json_out = True
        elif a == '--summary':
            summary_only = True
        elif a == '--warn-as-error':
            warn_as_error = True
        elif a == '--strict-return':
            STRICT_RETURN = True
        elif a == '--no-broad':
            CHECK_BROAD = False
        elif a.startswith('-'):
            print('未知参数: %s' % a)
            return 2
        else:
            paths.append(a)

    if not paths:
        paths = ['.']

    all_v = []
    scanned = 0
    for f in iter_py_files(paths):
        scanned += 1
        all_v.extend(check_file(f))

    errors = [v for v in all_v if v['severity'] == 'ERROR']
    warns = [v for v in all_v if v['severity'] == 'WARN']

    if json_out:
        print(json.dumps({
            'scanned': scanned,
            'errors': len(errors),
            'warnings': len(warns),
            'violations': all_v,
        }, ensure_ascii=False, indent=2))
    elif summary_only:
        print('扫描文件: %d' % scanned)
        print('ERROR: %d' % len(errors))
        print('WARN : %d' % len(warns))
        # 按 kind 细分
        import collections
        ec = collections.Counter(v['kind'] for v in errors)
        wc = collections.Counter(v['kind'] for v in warns)
        if ec:
            print('  ERROR 细分:', dict(ec))
        if wc:
            print('  WARN  细分:', dict(wc))
    else:
        if errors:
            print('=' * 72)
            print('ERROR (%d) — 必须修复（模拟 Rust 编译错误）' % len(errors))
            print('=' * 72)
            for v in errors:
                print('  %s:%d  [%s]  exc=%s' % (
                    v['file'], v['line'], v['kind'], v.get('exc_type', '?')))
                print('    上下文: %s' % v.get('context', '<无>'))
                print('    %s' % v['message'])
        if warns:
            if errors:
                print()
            print('=' * 72)
            print('WARN (%d) — 建议修复' % len(warns))
            print('=' * 72)
            for v in warns:
                print('  %s:%d  [%s]  exc=%s' % (
                    v['file'], v['line'], v['kind'], v.get('exc_type', '?')))
                print('    上下文: %s' % v.get('context', '<无>'))
                print('    %s' % v['message'])
        print()
        print('=' * 72)
        print('扫描 %d 个文件 → ERROR %d / WARN %d'
              % (scanned, len(errors), len(warns)))
        if not errors and not warns:
            print('全部通过 [OK]')
        print('=' * 72)

    if errors:
        return 1
    if warns and warn_as_error:
        return 2
    return 0


if __name__ == '__main__':
    # Windows 控制台默认 GBK，遇到中文/特殊字符可能崩溃 —— 切 UTF-8 兜底
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:  # _ignore_, 老版本 Python 无 reconfigure 时静默降级  # _broad_, 编码设置失败不影响主流程
        pass
    sys.exit(main(sys.argv))
