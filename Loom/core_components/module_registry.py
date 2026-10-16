# -*- coding: utf-8 -*-
"""module_registry.py — 注册表验证器 + 组装器 (DLL化战役 M1-2, 策略层)

地位: 规则权威文档 = core_components\\注册表格式与契约设计说明.txt (§6 校0-校8 /
§7 回退矩阵 / §8 LOOM_NO_DLL / §9 运行期弹出回退)。本模块是那份文档的实现者,
不另行发明机制; 改规则先改文档再改此处。

分工: module_loader.py = 机械层 (LoadLibrary/校验/热重载原语);
      本模块 = 策略层 (槽位模型 / 回退矩阵 / 拓扑 init / 运行期自愈)。

铁律 (报告 v1.3 §6): 兜底只对准用户注入 DLL (official=false);
  官方组件坏 = AssemblyError 报错, 绝不静默降级, 核心组件无 Python 冗余。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import module_loader as ml
import boot_check as bc

REGISTRY_FORMAT = 'loom-core-registry/1.0'
_ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOOP_CAP = 64          # 定点循环上限 (防死循环 → AssemblyError)

__all__ = ['AssemblyResult', 'assemble', 'REGISTRY_FORMAT']


# ---------------------------------------------------------------------------
# 注册表读取与结构校验
# ---------------------------------------------------------------------------
def _read_registry(path):
    """读 + 结构校验。任何结构问题 → AssemblyError (绝不带病运行)。"""
    if not os.path.isfile(path):
        raise ml.AssemblyError('注册表不存在: %s' % path)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (ValueError, OSError, UnicodeDecodeError) as e:
        raise ml.AssemblyError('注册表读取/解析失败: %s (%s)' % (path, e))
    if not isinstance(data, dict):
        raise ml.AssemblyError('注册表顶层必须是对象: %s' % path)
    fmt = data.get('_format')
    if fmt != REGISTRY_FORMAT:
        raise ml.AssemblyError(
            '注册表 _format 不符: %r != %r (path=%s)' % (fmt, REGISTRY_FORMAT, path))
    comps = data.get('components')
    if not isinstance(comps, list):
        raise ml.AssemblyError('components 必须是数组: %s' % path)
    for i, c in enumerate(comps):
        if not isinstance(c, dict):
            raise ml.AssemblyError('components[%d] 必须是对象 (path=%s)' % (i, path))
        for key, types in (('module_id', str), ('path', str), ('official', bool),
                           ('enabled', bool), ('provides', list), ('depends', list)):
            if key not in c:
                raise ml.AssemblyError(
                    'components[%d] 缺字段 %r (path=%s)' % (i, key, path))
            if not isinstance(c[key], types):
                raise ml.AssemblyError(
                    'components[%d].%s 类型错: %r (path=%s)' % (i, key, c[key], path))
        mid = c['module_id']
        if not mid or len(mid) > ml.LOOM_NAME_MAX:
            raise ml.AssemblyError(
                'components[%d].module_id 长度违约: %r (path=%s)' % (i, mid, path))
        for key in ('provides', 'depends'):
            for it in c[key]:
                if not isinstance(it, str) or not it:
                    raise ml.AssemblyError(
                        'components[%d].%s 含非字符串/空项: %r (path=%s)'
                        % (i, key, it, path))
        for key in ('sha256', 'note'):
            if key in c and not isinstance(c[key], str):
                raise ml.AssemblyError(
                    'components[%d].%s 类型错 (path=%s)' % (i, key, path))
    return data


def _writeback_enabled(registry_path, entries):
    """原子回写: 只把给定条目的 enabled 置 false, 其余键/顺序原样保留。"""
    if not entries:
        return
    with open(registry_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    targets = {(e['module_id'], os.path.normcase(os.path.normpath(e['path'])))
               for e in entries}
    changed = False
    for c in data.get('components', []):
        key = (c.get('module_id'),
               os.path.normcase(os.path.normpath(str(c.get('path', '')))))
        if key in targets and c.get('enabled') is not False:
            c['enabled'] = False
            changed = True
    if not changed:
        return
    tmp = registry_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, registry_path)


# ---------------------------------------------------------------------------
# 组装结果
# ---------------------------------------------------------------------------
class AssemblyResult(object):
    """一次组装的结果 + 运行期自愈入口。"""

    def __init__(self, registry_path, base_dir):
        self.registry_path = registry_path
        self.base_dir = base_dir
        self.modules = {}
        self.provides_map = {}
        self.report = []
        self._entries = {}          # module_id -> 激活条目 dict
        self._candidates = {}       # module_id -> [条目 dict, ...]
        self._persist = True
        self._seq = 0

    # -- 内部 ---------------------------------------------------------------
    def _next_seq(self):
        self._seq += 1
        return self._seq

    def _act(self, action, entry, reason=''):
        self.report.append({
            'seq': self._next_seq(),
            'action': action,
            'module_id': entry.get('module_id'),
            'path': entry.get('path'),
            'official': bool(entry.get('official', False)),
            'reason': reason,
        })

    def _load_entry(self, entry):
        """加载 + 校验一条目 → ModuleHandle (未 init)。失败抛 ModuleValidationFailed。"""
        path = os.path.join(self.base_dir, entry['path'].replace('/', os.sep))
        h = ml.ModuleHandle.load(path, expected_module_id=entry['module_id'])
        if bool(h.official) != bool(entry['official']):
            h.unload()
            raise ml.ModuleValidationFailed(
                'info.official 与注册表 official 不符: DLL=%d 条目=%s (path=%s)'
                % (h.official, entry['official'], path))
        if set(h.provides) != set(entry['provides']):
            h.unload()
            raise ml.ModuleValidationFailed(
                'provides 声明不符: DLL=%r 条目=%r (path=%s)'
                % (sorted(h.provides), sorted(entry['provides']), path))
        if set(h.depends) != set(entry['depends']):
            h.unload()
            raise ml.ModuleValidationFailed(
                'depends 声明不符: DLL=%r 条目=%r (path=%s)'
                % (sorted(h.depends), sorted(entry['depends']), path))
        return h

    def _sha_gate(self, entry):
        """校0 sha256 前置闸 (LoadLibrary 之前)。返回 (通过?, 原因)。

        官方条目 sha256 空 = 随引擎发行不钉指纹 (放行); 非空 = 强制比对,
        不符 → 官方坏 → AssemblyError (绝不静默降级)。
        """
        want = (entry.get('sha256') or '').strip().lower()
        if not want:
            return True, ''
        path = os.path.join(self.base_dir, entry['path'].replace('/', os.sep))
        if not os.path.isfile(path):
            return False, 'sha 闸: 文件不存在 %s' % path
        actual = ml.file_sha256(path)
        if actual != want:
            return False, 'sha256 不符: 实测 %s != 声明 %s' % (actual, want)
        return True, ''

    def _install(self, entry, h, action, reason=''):
        mid = entry['module_id']
        self.modules[mid] = h
        self._entries[mid] = entry
        for iface in h.provides:
            self.provides_map[iface] = mid
        self._act(action, entry, reason)

    def _reindex(self):
        """按在役集合重算 provides_map (弹出后不留悬空/误删)。"""
        self.provides_map.clear()
        for mid, h in self.modules.items():
            for iface in h.provides:
                self.provides_map.setdefault(iface, mid)

    def _pop(self, mid, reason, action='popped'):
        """从在役集合移除 (不 unload 由调用方决定) 并记录。返 True=已记账。"""
        entry = self._entries.pop(mid, None)
        h = self.modules.pop(mid, None)
        if h is not None:
            self._reindex()
        if entry is not None:
            self._act(action, entry, reason)
            return True
        return False

    def _fallback(self, slot, reason):
        """同槽位官方条目顶回。无官方可回退 → AssemblyError。"""
        for entry in self._candidates.get(slot, []):
            if bool(entry.get('official')) and entry.get('enabled'):
                h = self._load_entry(entry)
                h.init()
                self._install(entry, h, 'fallback', reason)
                return h
        raise ml.AssemblyError(
            '槽位 %s 无官方条目可回退 (reason=%s)' % (slot, reason))

    def _handle_failure(self, entry, reason, action='popped'):
        """§7 回退矩阵: 用户注入 → 弹出+禁用回写+官方顶回; 官方 → AssemblyError。"""
        mid = entry['module_id']
        if bool(entry['official']):
            raise ml.AssemblyError(
                '官方组件失败 (绝不静默降级): %s (path=%s, reason=%s)'
                % (mid, entry['path'], reason))
        if not self._pop(mid, reason, action=action):
            # 该条目尚未进在役集合 (如 sha 闸前置弹出) → 仍需记账
            self._act(action, entry, reason)
        if self._persist:
            try:
                _writeback_enabled(self.registry_path, [entry])
                self._act('writeback', entry, 'enabled=false 已回写')
            except Exception as e:                       # 回写失败不掩盖原失败
                self._act('writeback', entry, '回写失败: %r' % (e,))
        if any(bool(c.get('official')) and c.get('enabled')
               for c in self._candidates.get(mid, [])):
            self._fallback(mid, reason)
        return None

    # -- 公开 API -----------------------------------------------------------
    def get(self, module_id):
        """取在役句柄; 缺件 (跳过/弹出/不存在) 抛 ModuleNotAvailable。"""
        h = self.modules.get(module_id)
        if h is None:
            raise ml.ModuleNotAvailable(
                '槽位不可用: %r (registry=%s)' % (module_id, self.registry_path))
        return h

    def pop_and_fallback(self, module_id, reason, persist=True):
        """运行期自愈: 弹出坏句柄 → 禁用回写 → 官方顶回 → 返新句柄。"""
        entry = self._entries.get(module_id)
        h = self.modules.get(module_id)
        if entry is None:
            raise ml.AssemblyError(
                'pop_and_fallback: 槽位 %r 不在役 (reason=%s)' % (module_id, reason))
        if bool(entry['official']):
            raise ml.AssemblyError(
                'pop_and_fallback: 弹的是官方组件 %r — 无 Python 冗余可降级 (reason=%s)'
                % (module_id, reason))
        self._pop(module_id, reason, action='popped')
        if h is not None:
            try:
                h.deinit()
            except Exception:
                pass
            try:
                h.unload()
            except Exception:
                pass
        if persist:
            try:
                _writeback_enabled(self.registry_path, [entry])
                self._act('writeback', entry, '运行期弹出 → enabled=false 回写')
            except Exception as e:
                self._act('writeback', entry, '回写失败: %r' % (e,))
        return self._fallback(module_id, reason)

    def deinit_all(self):
        for mid, h in list(self.modules.items()):
            try:
                h.deinit()
            except Exception as e:
                sys.stderr.write('module_registry: deinit %s 失败 %r\n' % (mid, e))

    def shutdown(self):
        """deinit + unload 全部在役句柄 (幂等)。"""
        for mid, h in list(self.modules.items()):
            try:
                h.unload()
            except Exception as e:
                sys.stderr.write('module_registry: unload %s 失败 %r\n' % (mid, e))
        self.modules.clear()
        self.provides_map.clear()
        self._entries.clear()

    def summary(self):
        lines = ['registry = %s' % self.registry_path,
                 'modules  = %d (%s)' % (len(self.modules),
                                         ', '.join(sorted(self.modules)) or '-'),
                 'ifaces   = %d (%s)' % (len(self.provides_map),
                                         ', '.join(sorted(self.provides_map)) or '-')]
        by_action = {}
        for r in self.report:
            by_action[r['action']] = by_action.get(r['action'], 0) + 1
        lines.append('report   = %d 项 %s' % (len(self.report), by_action or '{}'))
        for r in self.report:
            lines.append('  #%d %-11s %-12s %s %s'
                         % (r['seq'], r['action'], r['module_id'] or '-',
                            'official' if r['official'] else 'injected', r['reason']))
        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# 组装主流程
# ---------------------------------------------------------------------------
def assemble(registry_path=None, base_dir=None, do_init=True, persist=True):
    """按注册表组装引擎核心组件 → AssemblyResult。

    规则见 注册表格式与契约设计说明.txt §5-§8。任何官方组件失败 / 结构错误 /
    歧义双官方 / 依赖环 → AssemblyError (绝不带病运行)。
    """
    base_dir = os.path.abspath(base_dir or _ENGINE_ROOT)
    registry_path = os.path.abspath(
        registry_path or os.path.join(base_dir, 'core_components', 'registry.json'))
    data = _read_registry(registry_path)

    # ---- A1 启动自检 (官方件出厂基准): 编译进 exe 的 official_manifest 为准 ----
    # 出厂模式有 modified/missing → AssemblyError (报警拒载).
    # LOOM_DEV=1 跳过 (开发期天天重编, SHA 一直在变).
    _boot_ok, _boot_report = bc.verify_official(data, base_dir)
    if not _boot_ok:
        raise ml.AssemblyError(
            '官方件出厂基准校验失败 (LOOM_DEV=1 可跳过):\n'
            + bc.format_report(_boot_report))

    res = AssemblyResult(registry_path, base_dir)
    res._persist = bool(persist)

    # ---- 槽位分组 + 结构规则 ----
    candidates = {}
    for c in data['components']:
        candidates.setdefault(c['module_id'], []).append(c)
    for mid, items in candidates.items():
        if len(items) > 2:
            raise ml.AssemblyError('槽位 %s 条目数 %d > 2 (只允许 官方+注入 各一)'
                                   % (mid, len(items)))
        for flag in (True, False):
            same = [c for c in items if bool(c['official']) is flag]
            if len(same) > 1:
                raise ml.AssemblyError(
                    '槽位 %s 存在 %d 条 official=%s 条目 (同槽位同身份重复)'
                    % (mid, len(same), flag))
    res._candidates = candidates

    skips = ml.no_dll_skips()
    order = [c['module_id'] for c in data['components']]
    seen_slot = set()
    slots = []
    for mid in order:
        if mid not in seen_slot:
            seen_slot.add(mid)
            slots.append(mid)

    # ---- 候选序: 注入(enabled) 优先 → 官方(enabled) 兜底 ----
    for slot in slots:
        items = candidates[slot]
        if '*' in skips or slot in skips:
            for c in items:
                res._act('skipped', c, 'LOOM_NO_DLL 逃生门')
            continue
        active = [c for c in items if c.get('enabled')]
        if not active:
            for c in items:
                res._act('skipped', c, '条目 enabled=false (不参与组装)')
            continue
        pick = None
        for c in active:
            if not bool(c['official']):
                pick = c
                break
        if pick is None:
            pick = active[0]

        # 校0 sha256 前置闸 (LoadLibrary 之前)
        ok, why = res._sha_gate(pick)
        if not ok:
            if bool(pick['official']):
                raise ml.AssemblyError('官方条目 sha256 校验失败: %s (path=%s)'
                                       % (why, pick['path']))
            res._handle_failure(pick, why, action='popped')
            continue
        try:
            h = res._load_entry(pick)
        except ml.ModuleValidationFailed as e:
            res._handle_failure(pick, str(e), action='popped')
            continue
        res._install(pick, h, 'loaded', '校验通过')

    # ---- 校6 接口冲突: 保官方弃歧义 ----
    for iface in sorted(set(res.provides_map)):
        holders = [mid for mid, h in res.modules.items() if iface in h.provides]
        if len(holders) <= 1:
            continue
        holders.sort(key=lambda m: (not bool(res.modules[m].official), m))
        for victim in holders[1:]:
            if bool(res.modules[victim].official):
                raise ml.AssemblyError(
                    '接口 %s 双官方提供: %r (引擎缺陷)' % (iface, holders))
            res._handle_failure(res._entries[victim],
                                '接口冲突: %s 已被 %s 提供' % (iface, holders[0]),
                                action='conflict')

    # ---- 校5 依赖满足 (级联: 弹一个可能连带弹出依赖它的) ----
    for _round in range(_LOOP_CAP):
        providers = {}
        for mid, h in res.modules.items():
            for iface in h.provides:
                providers.setdefault(iface, []).append(mid)
        bad = None
        for mid, h in res.modules.items():
            for dep in h.depends:
                others = [m for m in providers.get(dep, []) if m != mid]
                if not others:
                    bad = (mid, dep)
                    break
            if bad:
                break
        if bad is None:
            break
        mid, dep = bad
        res._handle_failure(res._entries[mid],
                            '依赖未满足: %s (depends %r)' % (mid, dep),
                            action='popped')
    else:
        raise ml.AssemblyError('依赖解析定点循环超上限 %d (疑似死循环)' % _LOOP_CAP)

    # ---- 校7 依赖环 + 拓扑序 ----
    topo, cyclic = _topo_order(res.modules)
    if cyclic:
        raise ml.AssemblyError('依赖环 (init 拓扑序无解): %s' % ', '.join(sorted(cyclic)))

    # ---- 校8 init (拓扑序; 失败按弹出规则, 依赖方连带弹出) ----
    if do_init:
        inited = []
        for mid in topo:
            h = res.modules.get(mid)
            if h is None:
                continue
            try:
                h.init()
            except ml.ModuleValidationFailed as e:
                res._handle_failure(res._entries[mid], 'init 失败: %s' % e,
                                    action='init_failed')
                continue
            inited.append(mid)
        # 级联: 弹出后其依赖方不再满足
        for _round in range(_LOOP_CAP):
            providers = {}
            for mid, h in res.modules.items():
                for iface in h.provides:
                    providers.setdefault(iface, []).append(mid)
            bad = None
            for mid, h in res.modules.items():
                for dep in h.depends:
                    if not [m for m in providers.get(dep, []) if m != mid]:
                        bad = (mid, dep)
                        break
                if bad:
                    break
            if bad is None:
                break
            mid, dep = bad
            res._handle_failure(res._entries[mid],
                                'init 后依赖未满足: %s (depends %r)' % (mid, dep),
                                action='popped')
    return res


def _topo_order(modules):
    """Kahn 拓扑排序 (依赖先行)。返回 (顺序, 环节点集)。"""
    indeg = {mid: 0 for mid in modules}
    edges = {mid: [] for mid in modules}
    providers = {}
    for mid, h in modules.items():
        for iface in h.provides:
            providers.setdefault(iface, []).append(mid)
    for mid, h in modules.items():
        for dep in h.depends:
            for src in providers.get(dep, []):
                if src != mid:
                    edges[src].append(mid)
                    indeg[mid] += 1
    queue = sorted([m for m, d in indeg.items() if d == 0])
    out = []
    while queue:
        n = queue.pop(0)
        out.append(n)
        for m in sorted(edges[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
        queue.sort()
    return out, set(modules) - set(out)
