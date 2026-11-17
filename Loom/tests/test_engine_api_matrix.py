# -*- coding: utf-8 -*-
"""B7-24 门：引擎公共 API 矩阵（GL 的 GLEngine vs VK 的 SceneDriver）—— 差异只许缩小。

背景
----
beta7 批 0（B7-24）要定一份两端都必须实现的 IEngineAPI。在契约定稿之前，先立这道门：
两端的「公开方法集合」差异被冻结成基线，只许减小，不许增大。任何新增漂移（新写一个只有 GL 有的
公开方法）当场变红；任何修复（补上缺失方法）也必须同步从基线里删掉，否则红 —— 防止基线腐烂成
「一张过期的表」。

口径（v2，2026-11-17 按 Q-B7-24-2 裁决升级）
--------------------------------------------
- 成员 = 类体内 def（含 @property / @staticmethod / @classmethod）+ 公开类属性（赋值语句）；
- 名字不以单/双下划线开头（_private / __dunder__ 全部排除）；
- 递归收集基类（GL 侧 8 个 mixin 都算进来），同名按 MRO 最近者为准；
- 只看「存在性」，不看签名、不看语义（签名见 docs/design/契约_IEngineAPI_20261117.md，
  语义一致是 B7-22 与 P1~P5 门的事）。

口径变更留痕
------------
- v1（2026-11-17 首版）：不含普通类属性 → GL 105 / VK 38 / 共同 28 / GL 独有 77 / VK 独有 10。
  这是 beta6 审计口径，首版矩阵与 docs/audit/impl_B7-24_API矩阵_20261117.md 用的是它。
- v2（2026-11-17 人类裁决 Q-B7-24-2「属性面要进契约」后）：含普通类属性
  → GL 109 / VK 39 / 共同 29 / GL 独有 80 / VK 独有 10。
- v2.1（2026-11-17 B7-26 落地后）：VK 新增公开方法 update_audio（音频段，契约 A 类）
  → GL 109 / VK 40 / 共同 30 / GL 独有 79 / VK 独有 10。
- **v3（2026-11-17 S1+S2 门面收敛后，JVM 模型）**：新增 engine_core.EngineCore（后端无关内核），
  GLEngine 与 SceneDriver **都继承它** → 8 个后端无关 mixin（Transform/Physics/Input/Camera/
  FrameComponent/Profiler/LogicThread/Raycast）的 ~100 个方法两端共享，另有 3 个统一宿主事件入口
  handle_key_event / handle_text_input / handle_quit_request。
  → GL 112 / VK 82 / 共同 **72** / GL 独有 **40** / VK 独有 10。
- **v3.1（2026-11-17 S2-2 部分完成）**：11 个纯数据查询方法（Layer/Tag/查找/SendMessage/设置层标签）
  从 GLEngine 搬进 loom_scene_query.SceneQueryMixin（无 GPU 依赖）→ VK 82 → **93**，
  GL 独有 40 → **29**，共同 72 → **83**。
  差异从 79 条缩到 40 条，**这是「一个引擎」的直接证据**，不是「逐条补 VK」。
  新增的 3 条 GL 独有 = 3 个鼠标状态属性（mouse_locked / mouse_lock_allowed /
  mouse_unlock_requested），它们正是「脚本读状态在 VK 下 AttributeError」的实例。
- 两个口径的数字不可混用；本门自 v2 起以 109/39 为基线。

用法
----
    py -3.13 tests/test_engine_api_matrix.py          # 门（绿 = 无新增漂移）
    py -3.13 tests/test_engine_api_matrix.py --list   # 打印完整矩阵表（含定义点与调用分布）
"""
import ast
import os
import re
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.dirname(HERE)
REPO = os.path.dirname(LOOM)


class _Index:
    """AST 索引：只解析、不 import —— 门必须在无 GPU / 无窗口 / 无 GL 上下文时也能跑。"""

    def __init__(self):
        self.classes = {}
        self.imports = {}

    def load(self, path):
        if path in self.imports:
            return
        with open(path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=path)
        self.imports[path] = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ''
                base = os.path.dirname(path)
                if node.level:
                    for _ in range(node.level - 1):
                        base = os.path.dirname(base)
                    modpath = os.path.join(base, *mod.split('.')) + '.py' if mod else None
                else:
                    cand = os.path.join(LOOM, *mod.split('.')) + '.py'
                    modpath = cand if os.path.isfile(cand) else None
                for a in node.names:
                    self.imports[path][a.asname or a.name] = (modpath, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    cand = os.path.join(LOOM, *a.name.split('.')) + '.py'
                    self.imports[path][a.asname or a.name.split('.')[0]] = (
                        cand if os.path.isfile(cand) else None, a.name.split('.')[0])
            elif isinstance(node, ast.ClassDef):
                self.classes[(path, node.name)] = (node, [self._base(b) for b in node.bases])

    @staticmethod
    def _base(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return '?'

    def find_class(self, name, from_path):
        if (from_path, name) in self.classes:
            return (from_path, name)
        modpath, orig = self.imports.get(from_path, {}).get(name, (None, None))
        if modpath and os.path.isfile(modpath):
            self.load(modpath)
            return self.find_class(orig, modpath)
        return None

    def members(self, key, seen=None):
        """{name: (kind, rel_file, lineno, defining_class, doc_first_line)}，子类优先。"""
        if seen is None:
            seen = set()
        if key in seen or key not in self.classes:
            return {}
        seen.add(key)
        node, bases = self.classes[key]
        out = {}
        for b in bases:
            bk = self.find_class(b, key[0])
            if bk:
                for k, v in self.members(bk, seen).items():
                    out.setdefault(k, v)
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kinds = {self._base(d) for d in stmt.decorator_list}
                if kinds & {'property', 'cached_property'}:
                    kind = 'property'
                elif 'staticmethod' in kinds:
                    kind = 'staticmethod'
                elif 'classmethod' in kinds:
                    kind = 'classmethod'
                else:
                    kind = 'method'
                doc = (ast.get_docstring(stmt) or '').strip()
                first = doc.split(chr(10))[0].strip() if doc else ''
                out[stmt.name] = (kind,
                                  os.path.relpath(key[0], REPO).replace(os.sep, '/'),
                                  stmt.lineno, node.name, first)
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                val = stmt.value
                for tgt in targets:
                    if isinstance(tgt, ast.Name):
                        try:
                            vs = ast.unparse(val)[:60] if val is not None else ''
                        except Exception:
                            vs = ''
                        out[tgt.id] = ('attr',
                                       os.path.relpath(key[0], REPO).replace(os.sep, '/'),
                                       stmt.lineno, node.name, '%s = %s' % (tgt.id, vs))
        return out


def api_matrix():
    """返回 (gl, vk)：各自 {公开方法名: 元组}。"""
    idx = _Index()
    engine_py = os.path.join(LOOM, 'engine.py')
    driver_py = os.path.join(LOOM, 'scene_driver.py')
    idx.load(engine_py)
    idx.load(driver_py)
    gl = {k: v for k, v in idx.members(idx.find_class('GLEngine', engine_py)).items()
          if not k.startswith('_')}
    vk = {k: v for k, v in idx.members(idx.find_class('SceneDriver', driver_py)).items()
          if not k.startswith('_')}
    return gl, vk


# ------------------------------------------------- 冻结基线（只许缩小，不许增大）
# 每一项 = 今天「一端有、另一端没有」的公开方法。修完一条就从这里删掉一条，并写进 IEngineAPI 契约；
# 新增一条 = 门红。
EXPECTED_GL_ONLY = frozenset({
    'add_light', 'add_material', 'add_model', 'attach_model',
    'blit_texture', 'clear_scene', 'draw_lines', 'draw_screen_lines',
    'draw_screen_polygon', 'draw_screen_rect', 'draw_text_quad', 'draw_texture_quad',
    'find_model_by_guid', 'get_frame_jitter', 'get_logic_time_ratio', 'get_tps',
    'load_scene', 'pop_scissor', 'present_health', 'push_scissor',
    'remove_light', 'remove_subtree', 'render', 'reset_sky_state',
    'run', 'should_fallback_remote', 'step_logic_once', 'toggle_logic_paused',
    'update_scripts',
})

EXPECTED_VK_ONLY = frozenset({
    'apply_dev_camera_mouse', 'camera_distance', 'camera_pos', 'camera_target',
    'consume_mouse_input', 'feed_mouse_rel', 'load_from_data', 'render_pose',
    'script_keys', 'step',
})

# 计数断言（防「两端同时改名」这种集合差异看不出来的漂移）
EXPECTED_GL_TOTAL = 112
EXPECTED_VK_TOTAL = 93


def _call_groups():
    """调用点分布：{方法名: {分组: 次数}}。只做证据，不参与判定。"""
    groups = {}
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames
                       if d not in ('.git', 'archive', '__pycache__', 'player_runtime', 'node_modules')]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, REPO).replace(os.sep, '/')
            if rel.startswith('Loom/tests/_tmp'):
                continue
            if rel.startswith('Loom/tests/'):
                g = 'tests'
            elif rel.startswith('Loom/') and fn in ('editor.py', 'editor_app.py', 'editor_ui.py'):
                g = 'editor'
            elif rel.startswith('Loom/') and fn in ('run_player.py', 'vk_player.py', 'game_player.py',
                                                   'build_game.py', 'build_entry.py', 'runtime.py'):
                g = 'player_pack'
            elif rel.startswith('Loom/'):
                g = 'engine'
            elif rel.startswith('examples/') or rel.startswith('Projects/'):
                g = 'examples'
            elif rel.startswith('tools/'):
                g = 'tools'
            else:
                continue
            try:
                src = open(full, 'r', encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            for m in re.finditer(r'\.(\w+)\s*\(', src):
                groups.setdefault(m.group(1), Counter())[g] += 1
    return groups


def main():
    gl, vk = api_matrix()
    gl_only = sorted(set(gl) - set(vk))
    vk_only = sorted(set(vk) - set(gl))
    both = sorted(set(gl) & set(vk))

    if '--list' in sys.argv:
        calls = _call_groups()
        print("# 引擎公共 API 矩阵（口径见本文件 docstring）")
        print()
        print('GL GLEngine 公开方法 %d 个 / VK SceneDriver 公开方法 %d 个 / 共同 %d / '
              'GL 独有 %d / VK 独有 %d' % (len(gl), len(vk), len(both), len(gl_only), len(vk_only)))
        for title, table, names in (('GL 独有（VK 缺）', gl, gl_only),
                                    ('VK 独有（GL 缺）', vk, vk_only)):
            print()
            print('## ' + title)
            print()
            print('| 方法 | 类型 | 定义点 | 调用分布 | 说明 |')
            print('|---|---|---|---|---|')
            for n in names:
                kind, f, line, cls, doc = table[n]
                c = calls.get(n) or Counter()
                dist = ' '.join('%s=%d' % (k, c[k]) for k in
                                ('engine', 'editor', 'player_pack', 'examples', 'tests', 'tools') if c[k])
                print('| %s | %s | %s:%d (%s) | %s | %s |'
                      % (n, kind, f, line, cls, dist or '—', doc.replace('|', '/')[:60]))
        return 0

    ok = True

    def check(label, cond, detail=''):
        nonlocal ok
        print(('PASS ' if cond else 'FAIL ') + label + ('  ' + detail if detail else ''))
        if not cond:
            ok = False

    print("=== B7-24 引擎公共 API 矩阵门（差异只许缩小） ===")
    check('GL 公开方法数 = %d' % EXPECTED_GL_TOTAL, len(gl) == EXPECTED_GL_TOTAL,
          '实测 %d' % len(gl))
    check('VK 公开方法数 = %d' % EXPECTED_VK_TOTAL, len(vk) == EXPECTED_VK_TOTAL,
          '实测 %d' % len(vk))

    new_drift = sorted(set(gl_only) - EXPECTED_GL_ONLY)
    fixed_gl = sorted(EXPECTED_GL_ONLY - set(gl_only))
    check('没有新增「只有 GL 有」的公开方法', not new_drift,
          ('新增: %s' % ' '.join(new_drift)) if new_drift else '')
    check('基线里没有「已经补齐但没删行」的条目', not fixed_gl,
          ('已补齐请从 EXPECTED_GL_ONLY 删除: %s' % ' '.join(fixed_gl)) if fixed_gl else '')

    new_drift_vk = sorted(set(vk_only) - EXPECTED_VK_ONLY)
    fixed_vk = sorted(EXPECTED_VK_ONLY - set(vk_only))
    check('没有新增「只有 VK 有」的公开方法', not new_drift_vk,
          ('新增: %s' % ' '.join(new_drift_vk)) if new_drift_vk else '')
    check('VK 基线里没有「已经补齐但没删行」的条目', not fixed_vk,
          ('已补齐请从 EXPECTED_VK_ONLY 删除: %s' % ' '.join(fixed_vk)) if fixed_vk else '')

    print()
    print('  现状：GL %d / VK %d / 共同 %d / GL 独有 %d（基线 %d）/ VK 独有 %d（基线 %d）'
          % (len(gl), len(vk), len(both), len(gl_only), len(EXPECTED_GL_ONLY),
             len(vk_only), len(EXPECTED_VK_ONLY)))
    print('  分类与处置：docs/audit/impl_B7-24_API矩阵_20261117.md')
    print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
