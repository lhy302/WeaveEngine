# -*- coding: utf-8 -*-
"""loom_assets.py — 资产身份层（beta6 B1：项目级 Assets/ + assets.json + guid 引用）。

设计依据: docs/design/research_beta6_02_asset_guid.md
  · 资产正文 = 项目根下 Assets/<Type>/…；索引 = Assets/assets.json（唯一真相）
  · guid = uuid4().hex（沿用 sceneio.generate_guid 语义），全局唯一性由索引校验
  · 场景文件只写 guid；路径永不进场景
  · 解析失败一律返回 (obj, valid, reason) —— 与 beta5 skybox 口径一致
  · 热路径只 stat（mtime+size），sha256 只在导入/指纹不符时算

分层（复用 userpaths 的用户层契约，不发明新机制）:
  项目层  <项目根>/Assets/assets.json          —— 资产索引 + 指纹
  用户层  %LOCALAPPDATA%/Loom/projects/<pid>/assets.json —— 只存 delta（src/import 覆盖）
  模板层  引擎内置（builtin:xxx 逻辑 guid，B1 只预留，不启用）

边界:
  · 导入源文件可以在任意位置（用户从磁盘选），但会被**复制**进项目 Assets/
  · 解析出的路径必须在项目根内（越界 -> valid=False + reason）
"""
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid

ASSETS_DIR = 'Assets'
INDEX_FILE = 'assets.json'
SCHEMA = 1

KINDS = ('texture', 'cubemap', 'material', 'mesh', 'model')
KIND_DIRS = {'texture': 'Textures', 'cubemap': 'Cubemaps',
             'material': 'Materials', 'mesh': 'Meshes', 'model': 'Models'}
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.tga', '.gif')

# 贴图导入设置键（与 loom_texture.Texture / sceneio._emit_material 同名同义）
IMPORT_KEYS = ('mipmaps', 'wrap', 'filter_mode', 'aniso', 'max_size', 'compression')
DEFAULT_IMPORT = {'mipmaps': True, 'wrap': 'repeat', 'filter_mode': 'trilinear',
                  'aniso': 1.0, 'max_size': 0, 'compression': 'none'}

# ---- 材质真相源 (Q-B1-3=A): 资产库 value 与场景内联定义的规范化/比较 ----
MATERIAL_INLINE_KEYS = ('color', 'saturation', 'metallic', 'roughness', 'pbr',
                        'albedo', 'normal_map', 'env_map')


def _slot_key(ref):
    """材质贴图槽 -> 可比较键：('g', guid) / ('p', path) / ('s', solid) / None。"""
    if isinstance(ref, dict):
        g = ref.get('guid')
        if isinstance(g, str) and g:
            return ('g', g)
        p = ref.get('path')
        if p:
            return ('p', str(p))
        sc = ref.get('solid_color')
        if sc:
            return ('s', tuple(int(x) for x in sc))
        return None
    if isinstance(ref, str) and ref:
        return ('g', ref)          # 资产库 value 里贴图槽存的是裸 guid
    return None


def _num(v, default):
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return round(float(default), 6)


def material_canon(d):
    """材质定义（库 value 或场景内联 dict）-> 可比较的规范元组。"""
    if not isinstance(d, dict):
        return None
    color = d.get('color')
    if isinstance(color, str):
        color = color.strip().lower() or None
    return (str(d.get('name') or ''),
            color,
            _num(d.get('saturation', 1.0), 1.0),
            _num(d.get('metallic', 0.0), 0.0),
            _num(d.get('roughness', 0.5), 0.5),
            bool(d.get('pbr', False)),
            _slot_key(d.get('albedo')),
            _slot_key(d.get('normal_map')),
            _slot_key(d.get('env_map')))


def material_has_inline(d):
    """场景材质条目里是否带内联定义（只有 id/guid/name 的是**引用**）。"""
    if not isinstance(d, dict):
        return False
    return any(k in d and d.get(k) is not None for k in MATERIAL_INLINE_KEYS)


def material_value_from_dict(d):
    """场景内联材质 -> 资产库 value（贴图槽只保留 guid，路径属旧格式）。"""
    if not isinstance(d, dict):
        return {}
    v = {'name': d.get('name'), 'color': d.get('color'),
         'saturation': d.get('saturation', 1.0),
         'metallic': d.get('metallic', 0.0),
         'roughness': d.get('roughness', 0.5),
         'pbr': bool(d.get('pbr', False))}
    for slot in ('albedo', 'normal_map'):
        ref = d.get(slot)
        g = ref.get('guid') if isinstance(ref, dict) else None
        if isinstance(g, str) and g:
            v[slot] = g
    env = d.get('env_map')
    if isinstance(env, dict):
        if isinstance(env.get('guid'), str) and env['guid']:
            v['env_map'] = env['guid']
        elif env.get('solid_color'):
            v['env_map_solid'] = list(env['solid_color'])
    return v


def material_matches(value, inline):
    """库 value 与场景内联定义是否等价（同一 guid 的冲突判定用）。"""
    return material_canon(value) == material_canon(inline)


# 索引读缓存: (index_path, mtime_ns, size) -> index dict（只读共享；save 时清）
_CACHE = {}
_INDEX_LOCK = threading.RLock()      # 同进程多写者串行（跨进程靠写前重读+合并）
# 旧路径告警去重（同一进程同一 ref 只告警一次，避免刷屏）
_WARNED = set()


def new_guid():
    """新资产 guid（32 hex，与 sceneio.generate_guid 同格式）。"""
    return uuid.uuid4().hex


_ILLEGAL_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# D-06: Windows 保留设备名（含带扩展名形态）+ 文件名长度上限
_WIN_RESERVED = set(['CON', 'PRN', 'AUX', 'NUL']
                    + ['COM%d' % i for i in range(1, 10)]
                    + ['LPT%d' % i for i in range(1, 10)])
_NAME_STEM_MAX = 100        # 远低于 Win32 的 255，避免 OSError(22)


def safe_asset_name(name, default='asset'):
    """把用户给的 name 净化成安全文件名（P2-①/D-06）。

    只取 basename（去掉任何目录部分）、替换 Windows 非法字符、去掉首尾点/空格、
    '..' 折叠、保留名加后缀、截断超长 stem。返回值不会是 '' / '.' / '..'。
    """
    s = str(name or '').replace('\\', '/')
    s = s.rsplit('/', 1)[-1].strip()
    s = _ILLEGAL_NAME.sub('_', s)
    s = s.strip(' .')
    s = s.replace('..', '_')
    if not s:
        return default
    stem, ext = os.path.splitext(s)
    if not stem:                     # '.png' 这类形态：整串当 stem
        stem, ext = s, ''
    if stem.upper() in _WIN_RESERVED:
        stem = stem + '_'            # LPT1 -> LPT1_（可正常 stat/copy）
    if len(stem) > _NAME_STEM_MAX:
        stem = stem[:_NAME_STEM_MAX]
    if len(ext) > 16:
        ext = ext[:16]
    return (stem + ext) or default


def warn_once(key, msg):
    """同一 (key) 只打印一次；返回是否本次真的打印了。"""
    if key in _WARNED:
        return False
    _WARNED.add(key)
    print(msg)
    return True


# ---------------------------------------------------------------- 路径与校验

def _valid_root(root):
    """项目根规范化：空/None -> None（**禁止**把 '' 当 CWD 写 Assets/）。

    F-02: 旧行为 save_index('') = 往当前目录写 Assets/assets.json，
    编辑器未保存场景时会污染仓库根。所有写入口统一走这里。
    """
    if root is None:
        return None
    s = str(root).strip()
    if not s:
        return None
    return os.path.abspath(s)


def assets_dir(root):
    return os.path.join(os.path.abspath(root), ASSETS_DIR)


def index_path(root):
    return os.path.join(assets_dir(root), INDEX_FILE)


def user_index_path(root):
    """用户层 delta 路径（只读覆盖；写失败不影响项目层）。

    pid 优先读 <root>/.loom/project_id（userpaths.project_id 的落盘位置），
    缺失时用 sha1(realpath)[:8] —— **不在这里写文件**（加载路径必须无副作用）。
    """
    root = os.path.abspath(root)
    pid = None
    try:
        with open(os.path.join(root, '.loom', 'project_id'), 'r',
                  encoding='utf-8') as f:
            pid = f.read().strip() or None
    except OSError:
        pid = None
    if not pid:
        try:
            import userpaths
            pid = 'dir-' + userpaths.sha1_short(os.path.realpath(root))
        except Exception:
            pid = 'dir-' + hashlib.sha1(
                os.path.realpath(root).encode('utf-8', 'replace')).hexdigest()[:8]
    try:
        import userpaths
        return os.path.join(userpaths.user_root(), 'projects', pid, INDEX_FILE)
    except Exception:
        return os.path.join(root, '.loom', INDEX_FILE)


def is_inside(root, path):
    """path 是否在 root 内（realpath + commonpath；跨盘符视为越界）。"""
    try:
        r = os.path.realpath(os.path.abspath(root))
        p = os.path.realpath(os.path.abspath(path))
    except Exception:
        return False
    win = (os.name == 'nt') or (len(r) > 1 and r[1] == ':')
    if win:
        r, p = r.lower(), p.lower()
    try:
        return os.path.commonpath([r, p]) == r
    except ValueError:
        return False


def find_project_root(start_dir, max_up=10):
    """向上找项目根（以 <root>/Assets/assets.json 存在为唯一判据）。

    返回绝对路径或 None。**只有索引文件存在**才算项目 —— 光有名叫 Assets 的
    目录不算（Windows 大小写不敏感，Loom/assets/ 是引擎模板层，不能被误认）。
    """
    if not start_dir:
        return None
    cur = os.path.abspath(start_dir)
    for _ in range(max_up + 1):
        # 2026-11-11: **盘根不算项目根**。实测：某个探针在 D:\ 误建过 Assets/assets.json，
        # 之后 D:\ 下所有工程都会把它认成项目根（跨工程污染、测试互相踩）。
        _drive, _rest = os.path.splitdrive(cur)
        if _rest not in ('\\', '/', ''):
            if os.path.isfile(index_path(cur)):
                return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent
    return None


def sha256_file(path, chunk=1 << 16):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def fingerprint(path):
    """源文件指纹: sha256 + size + mtime（导入/重导入时算一次）。"""
    st = os.stat(path)
    return {'sha256': sha256_file(path), 'size': int(st.st_size),
            'mtime': float(st.st_mtime)}


def stat_fingerprint(path):
    """只 stat（热路径）：(size, mtime) 或 None（文件缺失）。"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (int(st.st_size), float(st.st_mtime))


# ---------------------------------------------------------------- 索引读写

def empty_index(project_root=None):
    return {'schema': SCHEMA, 'assets': {}}


def _warn_text(warns):
    """坏条目告警文本（load_index / inspect_index 共用，措辞必须点名"坏条目"）。"""
    if not warns:
        return None
    return ('索引有 %d 条坏条目已剔除: %s'
            % (len(warns), '; '.join(str(w) for w in warns[:3])))


def _index_snapshot(root):
    """索引读盘 + 校验的**单次快照**（按 mtime/size 缓存，避免重复解析/校验）。

    F-02: 校验改为纯字符串判定后，10k 条一次解析 ≈ 100ms；这里再把
    load_index / inspect_index / asset_list 的重复读盘合并成一次快照。
    """
    p = index_path(root)
    try:
        st = os.stat(p)
    except OSError:
        return {'state': 'missing', 'data': None, 'warnings': [],
                'reason': '资产索引不存在: %s' % p, 'path': p, 'stat': None}
    key = (p, st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        snap = {'state': 'corrupt', 'data': None, 'warnings': [],
                'reason': '资产索引损坏 (%r): %s' % (e, p), 'path': p, 'stat': st}
        _CACHE[key] = snap
        return snap
    ok, warns = validate_index(data, root)
    if not ok:
        snap = {'state': 'invalid', 'data': None, 'warnings': warns,
                'reason': '; '.join(warns[:3]), 'path': p, 'stat': st}
    else:
        snap = {'state': ('partial' if warns else 'ok'), 'data': data,
                'warnings': list(warns),
                'reason': (_warn_text(warns) if warns else None),
                'path': p, 'stat': st}
    _CACHE[key] = snap
    return snap


def load_index(root):
    """读项目层索引 -> (index|None, ok, reason).

    ok=False: 文件缺失 / JSON 损坏 / 结构非法（此时 index=None，**不可用**）
    ok=True + reason 非空 = **部分可用**（个别坏条目已剔除，reason 是告警文本）。
    逐条容错（Q-B1-2=A）：一条坏条目不再让整本索引作废。
    """
    snap = _index_snapshot(root)
    if snap['state'] in ('missing', 'corrupt', 'invalid'):
        return None, False, snap['reason']
    if snap['warnings']:
        _st = snap.get('stat')
        warn_once(('idx-partial', snap['path'],
                   getattr(_st, 'st_mtime_ns', 0) if _st is not None else 0),
                  '[资产] ' + _warn_text(snap['warnings']) + '（其余条目照常可用）')
    return snap['data'], True, snap['reason']


def inspect_index(root):
    """索引体检 -> {state, reason, warnings, count, path}。

    state: missing（文件不存在）/ corrupt（JSON 坏）/ invalid（结构非法、不可用）
           / partial（部分条目被剔除、其余可用）/ ok。
    供 asset_list / scene_assets_check 区分「缺文件」与「文件在但坏了」。
    """
    snap = _index_snapshot(root)
    data = snap.get('data') or {}
    return {'state': snap['state'], 'reason': snap['reason'],
            'warnings': list(snap.get('warnings') or []),
            'count': len(data.get('assets') or {}),
            'path': snap['path']}


def _norm_src(src):
    """src -> (规范化相对路径 | None, reason | None)。

    **纯字符串判定，零文件系统调用**（F-02: 旧实现每条 2×realpath = 1.0ms/条，
    10000 条约 8.6s）。realpath/越界检查推迟到真正解析（resolve）时做。
    """
    if not isinstance(src, str) or not src:
        return None, 'src 必须是非空字符串'
    if os.path.isabs(src):
        return None, 'src 不能是绝对路径'
    norm = src.replace('\\', '/')
    if len(norm) > 1 and norm[1] == ':':
        return None, 'src 不能带盘符'
    if norm.startswith('/'):
        return None, 'src 不能以 / 开头'
    parts = norm.split('/')
    if '..' in parts:
        return None, 'src 越界/相对路径'
    parts = [x for x in parts if x not in ('', '.')]
    norm = '/'.join(parts)
    if not norm:
        return None, 'src 非法'
    if not (norm == ASSETS_DIR or norm.startswith(ASSETS_DIR + '/')):
        return None, 'src 必须位于 Assets/ 之下'
    return norm, None


def validate_index(index, root=None):
    """逐条校验 -> (ok, warnings)。

    ok=False 只表示**整体不可用**（顶层不是对象 / 缺 assets 对象）；
    个别条目非法 -> 从 assets 里剔除并记 warning，其余照常可用（Q-B1-2=A）。
    """
    if not isinstance(index, dict):
        return False, ['索引顶层必须是对象']
    assets = index.get('assets')
    if not isinstance(assets, dict):
        return False, ["索引缺 'assets' 对象"]
    warnings = []
    bad = []
    for gid, e in assets.items():
        if not isinstance(gid, str) or not gid:
            bad.append(gid)
            warnings.append('asset guid 非法: %r' % (gid,))
            continue
        if not isinstance(e, dict):
            bad.append(gid)
            warnings.append('%s: 条目不是对象' % gid)
            continue
        kind = e.get('type')
        if kind not in KINDS:
            bad.append(gid)
            warnings.append('%s: 未知类型 %r' % (gid, kind))
            continue
        src = e.get('src')
        if src is not None:
            _norm, _why = _norm_src(src)
            if _why:
                bad.append(gid)
                warnings.append('%s: %s (收到 %r)' % (gid, _why, src))
                continue
        if 'import' in e and not isinstance(e.get('import'), dict):
            bad.append(gid)
            warnings.append('%s: import 必须是对象' % gid)
    for gid in bad:
        assets.pop(gid, None)
    return True, warnings


def _entry_is_valid(gid, entry, root):
    """单条校验（供合并时过滤：坏条目不得因"写前重读"被复活）。"""
    probe = {'schema': SCHEMA, 'assets': {gid: entry}}
    ok, warns = validate_index(probe, root)
    return ok and not warns and gid in probe['assets']


def save_index(root, index):
    """原子写项目层索引（tmp + fsync + replace）-> (path|None, reason|None)。

    无项目根（''/None）时**拒绝保存**并返回 reason（不把 CWD 当项目根）。
    """
    _orig = root
    # D-04 / Q-R6A-3=A: 写前**重新加载并合并**（按 guid 并集）——
    # 两个写者先后保存时不会互相覆盖丢条目（lost update）；本方案没有删除语义，
    # 所以并集是安全的；合并进来的条目要过单条校验，坏条目不会被自愈后的写回"复活"。
    root = _valid_root(root)
    if root is None:
        return None, '没有项目根（root=%r），拒绝写资产索引' % (_orig,)
    os.makedirs(assets_dir(root), exist_ok=True)
    p = index_path(root)
    with _INDEX_LOCK:
        merged = dict(index or {})
        merged['schema'] = SCHEMA
        merged.setdefault('assets', {})
        try:
            with open(p, 'r', encoding='utf-8') as f:
                cur = json.load(f)
        except (OSError, ValueError):
            cur = None
        if isinstance(cur, dict) and isinstance(cur.get('assets'), dict):
            for gid, e in cur['assets'].items():
                if gid in merged['assets']:
                    continue
                if _entry_is_valid(gid, e, root):
                    merged['assets'][gid] = e
        tmp = '%s.tmp.%d' % (p, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(merged, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    _CACHE.clear()
    return p, None


def _load_user_delta(root):
    try:
        with open(user_index_path(root), 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('assets'), dict):
            return data['assets']
    except (OSError, ValueError):
        pass
    return {}


def load_user_delta(root):
    """读用户层 delta（只读副本；asset_list / asset_get 展示用）。"""
    root = _valid_root(root)
    if root is None:
        return {}
    return dict(_load_user_delta(root) or {})


def _write_user_index(root, assets):
    p = user_index_path(root)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = '%s.tmp.%d' % (p, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'schema': SCHEMA, 'assets': assets}, f,
                      ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        return True, None
    except OSError as e:
        return False, '用户层 delta 写入失败 (%r)' % (e,)


def write_user_delta(root, guid, src=None, import_settings=None):
    """写用户层 delta（本机覆盖：src / import）-> (ok, reason)。

    F-02: 用户层此前**没有任何写入方**（全仓 0 writer），这条路径等于死代码；
    这里补上唯一写入口，并由 EAI 命令 asset_user_override 调用。
    """
    root = _valid_root(root)
    if root is None:
        return False, '没有项目根，拒绝写用户层 delta'
    if not isinstance(guid, str) or not guid:
        return False, 'guid 非法: %r' % (guid,)
    assets = dict(_load_user_delta(root) or {})
    ent = assets.get(guid)
    if not isinstance(ent, dict):
        ent = {}
    if src is not None:
        if not isinstance(src, str) or not src:
            return False, 'src 必须是非空字符串'
        _norm, _why = _norm_src(src)
        if _why:
            return False, 'src 非法: %s' % (_why,)
        ent['src'] = src
    if import_settings is not None:
        if not isinstance(import_settings, dict):
            return False, 'import 必须是对象'
        imp = dict(ent.get('import') or {})
        for k, v in import_settings.items():
            if k in IMPORT_KEYS:
                imp[k] = v
        ent['import'] = imp
    if not ent:
        return False, '没有可写的覆盖项（src / import 至少给一个）'
    assets[guid] = ent
    return _write_user_index(root, assets)


def clear_user_delta(root, guid=None):
    """清除用户层 delta（guid 为空 = 清空全部）-> (ok, reason)。"""
    root = _valid_root(root)
    if root is None:
        return False, '没有项目根，拒绝写用户层 delta'
    assets = dict(_load_user_delta(root) or {})
    if guid is None:
        assets = {}
    else:
        assets.pop(guid, None)
    return _write_user_index(root, assets)


# ---------------------------------------------------------------- 上下文

class AssetContext(object):
    """一次加载/保存期间的资产解析上下文（项目层 + 用户层 delta 合并视图）。"""

    def __init__(self, root, index, user_delta=None, warnings=None,
                 readonly=False):
        self.root = os.path.abspath(root)
        self.index = index if index is not None else empty_index(self.root)
        self.user_delta = user_delta or {}
        self.warnings = list(warnings or [])   # 索引/用户层告警（供 asset_list 上报）
        self.readonly = bool(readonly)         # dry-run: 不落盘、不复制文件
        self._dirty = False
        self.last_save_error = None            # 最近一次索引写入失败原因（F-02）
        self.errors = []            # [(where, guid, reason)] —— 供 sceneio 汇总

    def _warn(self, msg, key=None):
        if msg and msg not in self.warnings:
            self.warnings.append(msg)
            warn_once(key or ('ctx-warn', self.root, msg), '[资产] %s' % (msg,))

    # ---- 构造 ----
    @classmethod
    def for_dir(cls, d, create=False, readonly=False):
        """目录 -> 上下文；无项目索引且 create=False 时返回 None（旧路径模式）。

        空串/None 一律 None（F-02: 不把 CWD 当成项目根去建 Assets/）。
        """
        root_in = _valid_root(d)
        if root_in is None:
            return None
        root = find_project_root(root_in)
        if root is None:
            if not create:
                return None
            if not readonly:
                os.makedirs(assets_dir(root_in), exist_ok=True)
                _p, _why = save_index(root_in, empty_index(root_in))
                if _p is None:
                    warn_once(('idx-save', root_in), '[资产] %s' % (_why,))
                    return None
            return cls(root_in, empty_index(root_in), readonly=readonly)
        return cls.open_root(root, create=create, readonly=readonly)

    @classmethod
    def open_root(cls, root, create=False, readonly=False):
        root = _valid_root(root)
        if root is None:
            return None
        idx, ok, why = load_index(root)
        warnings = [why] if why else []
        if idx is None:
            if not create:
                return None
            # Q-B1-2=A: 索引坏了也允许自愈 —— 但**先备份**，绝不静默覆盖
            try:
                if os.path.isfile(index_path(root)) and not readonly:
                    bak = index_path(root) + '.bak-%s' % time.strftime('%Y%m%d-%H%M%S')
                    shutil.copy2(index_path(root), bak)
                    warnings.append('原索引不可用（%s）已备份为 %s' % (why, os.path.basename(bak)))
                    print('[资产] ' + warnings[-1])
            except OSError as e:
                warnings.append('原索引备份失败 (%r)' % (e,))
            if not readonly:
                os.makedirs(assets_dir(root), exist_ok=True)
                _p, _swhy = save_index(root, empty_index(root))
                if _p is None:
                    warnings.append('索引重建失败: %s' % (_swhy,))
                    print('[资产] ' + warnings[-1])
                    return None
            idx = empty_index(root)
        return cls(root, idx, _load_user_delta(root), warnings=warnings,
                   readonly=readonly)

    # ---- 读 ----
    def entry(self, guid):
        if not isinstance(guid, str) or not guid:
            return None
        e = self.index.get('assets', {}).get(guid)
        if isinstance(e, dict):
            return e
        return None

    def owns(self, guid, kind=None):
        e = self.entry(guid)
        if e is None:
            return False
        return kind is None or e.get('type') == kind

    def entries(self, kind=None):
        out = self.index.get('assets', {}) or {}
        if kind is None:
            return dict(out)
        return {g: e for g, e in out.items() if e.get('type') == kind}

    def resolve(self, guid, kind=None):
        """guid -> (abs_path|None, entry|None, valid, reason)。

        reason 非空但 valid=True = 资产可用但**过期**（源文件已变），调用方应出声。
        """
        e = self.entry(guid)
        if e is None:
            return None, None, False, '资产 guid 未在项目索引中: %s' % (guid,)
        if kind is not None and e.get('type') != kind:
            return None, e, False, '资产类型不符 (期望 %s, 实际 %r)' % (kind, e.get('type'))
        # 用户层 delta: 只允许覆盖 src/import（不换 guid 身份）
        # Q-B1-3 同口径: 非 dict 的 delta 只跳过 + 告警，**绝不抛**（曾击穿 F7）
        delta = self.user_delta.get(guid)
        if delta is not None and not isinstance(delta, dict):
            self._warn('用户层 delta 条目不是对象 (%s) -> 已忽略，按项目层解析'
                       % (guid,))
            delta = None
        src = (delta or {}).get('src') or e.get('src')
        if not src:
            return None, e, False, '资产没有 src（可能是内置/材质条目）: %s' % (guid,)
        abs_p = os.path.join(self.root, str(src).replace('/', os.sep))
        if not is_inside(self.root, abs_p):
            return None, e, False, '资产路径越界（必须在项目根内）: %s' % (src,)
        if e.get('type') == 'cubemap':
            # 目录型资产: 存在性由 cubemap() 逐面校验（缺面 reason 更精确）
            if not os.path.isdir(abs_p):
                return None, e, False, '资产目录缺失: %s' % (src,)
            # P2-③: 六面图指纹（逐面 sha256/size/mtime）—— 内容被替换必须出声。
            # 热路径只 stat；仅在 size/mtime 变化时才逐面算 sha（与 texture 同策略）。
            fs = e.get('face_stats')
            if isinstance(fs, dict) and fs:
                changed = []
                for fname, meta in fs.items():
                    if not isinstance(meta, dict):
                        continue
                    fp2 = os.path.join(abs_p, str(fname))
                    try:
                        st2 = os.stat(fp2)
                    except OSError:
                        return None, e, False, '六面图缺面: %s' % (fname,)
                    if (int(meta.get('size', -1)) == st2.st_size
                            and abs(float(meta.get('mtime', -1.0)) - st2.st_mtime) < 1e-6):
                        continue
                    try:
                        sha2 = sha256_file(fp2)
                    except OSError:
                        sha2 = None
                    if sha2 and sha2 != meta.get('sha256'):
                        changed.append(str(fname))
                if changed:
                    return abs_p, e, True, ('六面图内容已变更（%s，建议 asset_reimport）: %s'
                                            % (','.join(sorted(changed)), src))
            return abs_p, e, True, None
        if not os.path.isfile(abs_p):
            return None, e, False, '资产文件缺失: %s' % (src,)
        fp = e.get('fingerprint') or {}
        now = stat_fingerprint(abs_p)
        if fp and now is not None and (int(fp.get('size', -1)) != now[0]
                                      or float(fp.get('mtime', -1.0)) != now[1]):
            try:
                sha_now = sha256_file(abs_p)
            except OSError:
                return abs_p, e, True, '资产指纹读取失败: %s' % (src,)
            if fp.get('sha256') and sha_now != fp.get('sha256'):
                return abs_p, e, True, '资产内容已变更（sha256 不符，建议 asset_reimport）: %s' % (src,)
            # 仅时间戳变化、内容一致 -> 不算问题（不打扰用户，也不污染 scene_assets_check）
            return abs_p, e, True, None
        return abs_p, e, True, None

    # ---- 构建运行时对象 ----
    def _import_settings(self, entry, ref=None, guid=None):
        """导入设置优先级: 默认 < 项目条目 < **用户层 delta** < 场景内联覆盖。

        F-02: 旧实现只读 entry/ref，用户层 delta 的 import 从读入到失效都没被用过。
        """
        s = dict(DEFAULT_IMPORT)
        s.update(entry.get('import') or {})
        delta = self.user_delta.get(guid) if guid else None
        if isinstance(delta, dict) and isinstance(delta.get('import'), dict):
            for k in IMPORT_KEYS:
                if k in delta['import']:
                    s[k] = delta['import'][k]
        for k in IMPORT_KEYS:
            if isinstance(ref, dict) and k in ref:
                s[k] = ref[k]
        return s

    def texture(self, guid, ref=None):
        """guid -> (Texture|None, valid, reason)。"""
        from loom_texture import Texture
        p, e, ok, why = self.resolve(guid, 'texture')
        if not ok:
            return None, False, why
        s = self._import_settings(e, ref, guid)
        nm = e.get('name')
        if not nm and isinstance(ref, dict):
            nm = ref.get('name')
        try:
            tex = Texture.from_file(p, name=nm, guid=guid, **s)
        except Exception as exc:
            return None, False, '贴图解码失败 (%r): %s' % (exc, p)
        return tex, True, why

    def cubemap(self, guid, ref=None):
        """guid -> (Cubemap|None, valid, reason)。src = 目录，faces 见 entry['files']。"""
        from loom_cubemap import Cubemap
        p, e, ok, why = self.resolve(guid, 'cubemap')
        if not ok:
            return None, False, why
        if not os.path.isdir(p):
            return None, False, 'cubemap 资产 src 必须是目录: %s' % (e.get('src'),)
        files = e.get('files') or (['%s.png' % f for f in Cubemap.FACES])
        faces = [os.path.join(p, f) for f in files]
        missing = [f for f in files if not os.path.isfile(os.path.join(p, f))]
        if missing:
            return None, False, 'cubemap 缺面: %s' % (', '.join(missing),)
        try:
            cube = Cubemap.from_files(faces, name=e.get('name'),
                                      guid=guid)
        except Exception as exc:
            return None, False, 'cubemap 加载失败 (%r)' % (exc,)
        return cube, True, why

    def material(self, guid):
        """guid -> (Material|None, valid, reason)（资产库里的材质，供 material_id 回查）。"""
        e = self.entry(guid)
        if e is None or e.get('type') != 'material':
            return None, False, '材质资产不存在: %s' % (guid,)
        from loom_material import Material
        v = e.get('value') or {}
        try:
            mat = Material(color=v.get('color'), saturation=v.get('saturation', 1.0),
                           name=v.get('name'), guid=guid)
            mat.metallic = v.get('metallic', 0.0)
            mat.roughness = v.get('roughness', 0.5)
            mat.pbr = v.get('pbr', False)
        except Exception as exc:
            return None, False, '材质资产构造失败 (%r)' % (exc,)
        first_reason = None
        _kept = {}
        for slot in ('albedo', 'normal_map'):
            g = v.get(slot)
            if not g:
                continue
            tex, ok, why = self.texture(g)
            if tex is not None:
                setattr(mat, slot, tex)
            else:
                # P1-1 语义延续：库 value 里有的引用，解析失败也要保留，
                # 下次保存（sync_material）不会把它从库里抹掉。
                _kept[slot] = {'guid': g}
            if why and first_reason is None:
                first_reason = why
        g = v.get('env_map')
        if g:
            cube, ok, why = self.cubemap(g)
            if cube is not None:
                mat.env_map = cube
            else:
                _kept['env_map'] = {'guid': g}
            if why and first_reason is None:
                first_reason = why
        elif v.get('env_map_solid'):
            try:
                from loom_cubemap import Cubemap
                mat.env_map = Cubemap.from_solid(tuple(v['env_map_solid']),
                                                 name=v.get('name'), guid=guid + ':env')
            except Exception:
                pass
        if _kept:
            try:
                mat._asset_ref_slots = _kept
            except Exception:
                pass
        return mat, True, first_reason

    # ---- 材质真相源 (Q-B1-3=A) ----
    def material_value(self, guid):
        """资产库里该材质的 value（不存在返回 None）。"""
        e = self.entry(guid)
        if e is None or e.get('type') != 'material':
            return None
        return dict(e.get('value') or {})

    def material_matches(self, guid, inline):
        """库内 value 与场景内联定义是否等价（冲突规则用）。"""
        v = self.material_value(guid)
        return v is not None and material_matches(v, inline)

    def register_material_value(self, guid, value, name=None):
        """登记材质值（迁移脚本用；已存在不覆盖）-> (guid, migrated, reason)。"""
        if self.owns(guid, 'material'):
            return guid, False, None
        self.index.setdefault('assets', {})[guid] = {
            'type': 'material', 'src': None,
            'name': name or value.get('name') or '材质',
            'value': dict(value)}
        self._dirty = True
        return self._finish(guid)

    def sync_material(self, mat):
        """保存期：把材质（含本次编辑后的值）写回资产库。

        返回 (guid, migrated, reason)：migrated=True 表示「本次才登记进资产库」。
        库是唯一真相源，所以已存在的条目也会被本次值覆盖更新。
        """
        gid = getattr(mat, 'guid', None)
        if not gid:
            return None, False, '材质没有 guid'
        existed = self.owns(gid, 'material')
        g, _created, why = self.import_material(mat, guid=gid)
        return g, (bool(g) and not existed), why

    # ---- 写（导入）----
    def _unique_dest(self, kind, name, create=True):
        d = os.path.join(assets_dir(self.root), KIND_DIRS.get(kind, 'Misc'))
        if create:
            os.makedirs(d, exist_ok=True)
        stem, ext = os.path.splitext(safe_asset_name(name, 'asset'))
        stem = stem or 'asset'
        cand, n = stem + ext, 1
        while os.path.exists(os.path.join(d, cand)):
            n += 1
            cand = '%s_%d%s' % (stem, n, ext)
        dest = os.path.join(d, cand)
        if not is_inside(assets_dir(self.root), dest):
            raise ValueError('资产目标路径越界（必须是 Assets/ 之下）: %r' % (dest,))
        return dest

    def _find_by_sha(self, kind, sha):
        for gid, e in self.entries(kind).items():
            if (e.get('fingerprint') or {}).get('sha256') == sha:
                return gid
        return None

    def _entry_abs(self, entry):
        src = (entry or {}).get('src')
        if not src:
            return None
        return os.path.join(self.root, str(src).replace('/', os.sep))

    def _entry_body_ok(self, entry, kind):
        """索引条目指向的正文是否真的在盘上（D-05 去重/修复的前置检查）。"""
        abs_p = self._entry_abs(entry)
        if not abs_p:
            return False
        if kind == 'cubemap':
            if not os.path.isdir(abs_p):
                return False
            files = (entry or {}).get('files') or []
            return bool(files) and all(
                os.path.isfile(os.path.join(abs_p, f)) for f in files)
        return os.path.isfile(abs_p)

    def _repair_texture(self, guid, entry, src, fp):
        """D-05 / Q-R6A-2=A: 正文缺失 -> 按**同 guid** 重写，created=True。"""
        if self.readonly:
            return guid, False, '只读模式：正文缺失但未写盘'
        abs_p = self._entry_abs(entry)
        if abs_p and is_inside(assets_dir(self.root), abs_p):
            dest = abs_p
        else:
            dest = self._unique_dest('texture',
                                     os.path.basename(str((entry or {}).get('src') or src)),
                                     create=True)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
        except OSError as e:
            return None, False, '资产正文缺失且重写失败 (%r)' % (e,)
        entry['src'] = os.path.relpath(dest, self.root).replace(os.sep, '/')
        entry['fingerprint'] = fp
        self._dirty = True
        return self._finish(guid, '资产正文缺失，已按同 guid 重新落盘')

    def _repair_cubemap(self, guid, entry, abses, face_src, sha, total_bytes):
        """D-05: 六面图正文缺失 -> 按同 guid 重写六面。"""
        if self.readonly:
            return guid, False, '只读模式：六面图正文缺失但未写盘'
        from loom_cubemap import Cubemap
        abs_p = self._entry_abs(entry)
        if abs_p and is_inside(assets_dir(self.root), abs_p):
            dest = abs_p
        else:
            dest = os.path.join(assets_dir(self.root), KIND_DIRS['cubemap'],
                                safe_asset_name(guid, 'cubemap'))
        try:
            os.makedirs(dest, exist_ok=True)
            files, face_stats = [], {}
            for i, fname in enumerate(Cubemap.FACES):
                ext = os.path.splitext(abses[i])[1] or '.png'
                out = '%s%s' % (fname, ext)
                shutil.copy2(abses[i], os.path.join(dest, out))
                files.append(out)
                face_stats[out] = face_src[i]
        except OSError as e:
            return None, False, '六面图正文重写失败 (%r)' % (e,)
        entry['src'] = os.path.relpath(dest, self.root).replace(os.sep, '/')
        entry['files'] = files
        entry['face_stats'] = face_stats
        entry['fingerprint'] = {'sha256': sha, 'size': total_bytes,
                                'mtime': max(m['mtime'] for m in face_src)}
        self._dirty = True
        return self._finish(guid, '六面图正文缺失，已按同 guid 重新落盘')

    def import_texture(self, src, name=None, import_settings=None, guid=None):
        """导入贴图（复制进项目）-> (guid|None, created, reason)。"""
        src = os.path.abspath(src)
        if not os.path.isfile(src):
            return None, False, '源文件不存在: %s' % (src,)
        if os.path.splitext(src)[1].lower() not in IMAGE_EXTS:
            return None, False, '不支持的图片格式: %s' % (os.path.splitext(src)[1],)
        try:
            fp = fingerprint(src)
        except OSError as e:
            return None, False, '源文件读取失败 (%r)' % (e,)
        sha = fp['sha256']
        base_name = name or os.path.basename(src)
        if not os.path.splitext(base_name)[1]:
            # name 不带扩展名时补源文件扩展名（否则 Assets/Textures/<name> 没有后缀，
            # 解码器只能靠猜 -> 资产文件名不可读且易被误判）
            base_name += os.path.splitext(src)[1] or '.png'
        if guid:
            e = self.entry(guid)
            if e is not None:
                if (e.get('fingerprint') or {}).get('sha256') != sha:
                    return None, False, ('同 guid 指向不同内容（%s 已存在且内容不同）' % guid)
                if self._entry_body_ok(e, 'texture'):
                    return guid, False, None
                # D-05: 正文缺失 -> 修复而不是假成功
                return self._repair_texture(guid, e, src, fp)
        same = self._find_by_sha('texture', sha)
        if same is not None:
            e = self.entry(same) or {}
            if self._entry_body_ok(e, 'texture'):
                return same, False, None
            return self._repair_texture(same, e, src, fp)
        try:
            dest = self._unique_dest('texture', base_name, create=not self.readonly)
            if not self.readonly:
                shutil.copy2(src, dest)
        except (OSError, ValueError) as e:
            # D-06: 非法/超长名字等统一转成结构化 reason（不让调用方吃异常）
            return None, False, '资产写入失败 (%r): %s' % (e, os.path.basename(src))
        gid = guid or new_guid()
        imp = dict(DEFAULT_IMPORT)
        imp.update(import_settings or {})
        self.index.setdefault('assets', {})[gid] = {
            'type': 'texture', 'src': os.path.relpath(dest, self.root).replace(os.sep, '/'),
            'name': name or os.path.splitext(os.path.basename(src))[0],
            'import': imp, 'fingerprint': fp}
        self._dirty = True
        return self._finish(gid)

    def import_cubemap(self, paths, name=None, guid=None):
        """导入六面图（6 张图 -> Assets/Cubemaps/<name>/px..nz）-> (guid, created, reason)。"""
        if not isinstance(paths, (list, tuple)) or len(paths) != 6:
            return None, False, '六面图必须给 6 个路径 (px,nx,py,ny,pz,nz)'
        abses = [os.path.abspath(str(p)) for p in paths]
        for i, p in enumerate(abses):
            if not os.path.isfile(p):
                return None, False, '第 %d 面源文件不存在: %s' % (i, p)
        sha = hashlib.sha256()
        face_src = []
        total_bytes = 0
        for i, p in enumerate(abses):
            try:
                s = sha256_file(p)
                st = os.stat(p)
            except OSError as e:
                return None, False, '第 %d 面读取失败 (%r)' % (i, e)
            sha.update(s.encode('ascii'))
            total_bytes += int(st.st_size)
            face_src.append({'sha256': s, 'size': int(st.st_size),
                             'mtime': float(st.st_mtime)})
        sha = sha.hexdigest()
        if guid:
            e = self.entry(guid)
            if e is not None:
                if (e.get('fingerprint') or {}).get('sha256') != sha:
                    return None, False, ('同 guid 指向不同内容（%s 已存在且内容不同）' % guid)
                if self._entry_body_ok(e, 'cubemap'):
                    return guid, False, None
                return self._repair_cubemap(guid, e, abses, face_src, sha, total_bytes)
        same = self._find_by_sha('cubemap', sha)
        if same is not None:
            e = self.entry(same) or {}
            if self._entry_body_ok(e, 'cubemap'):
                return same, False, None
            return self._repair_cubemap(same, e, abses, face_src, sha, total_bytes)
        stem = safe_asset_name(
            name or os.path.basename(os.path.dirname(abses[0]))
            or os.path.splitext(os.path.basename(abses[0]))[0], 'cubemap')
        base = os.path.join(assets_dir(self.root), KIND_DIRS['cubemap'])
        if not self.readonly:
            os.makedirs(base, exist_ok=True)
        dest, n = os.path.join(base, stem), 1
        while os.path.isdir(dest):
            n += 1
            dest = os.path.join(base, '%s_%d' % (stem, n))
        if not is_inside(assets_dir(self.root), dest):
            return None, False, '六面图目标路径越界: %r' % (dest,)
        if not self.readonly:
            os.makedirs(dest, exist_ok=True)
        from loom_cubemap import Cubemap
        files = []
        face_stats = {}
        try:
            for i, fname in enumerate(Cubemap.FACES):
                ext = os.path.splitext(abses[i])[1] or '.png'
                out = '%s%s' % (fname, ext)
                if not self.readonly:
                    shutil.copy2(abses[i], os.path.join(dest, out))
                files.append(out)
                # P2-③: 逐面指纹（内容/时间戳），供 resolve 检测六面图被替换
                face_stats[out] = face_src[i]
        except OSError as e:
            return None, False, '六面图写入失败 (%r)' % (e,)
        gid = guid or new_guid()
        self.index.setdefault('assets', {})[gid] = {
            'type': 'cubemap', 'src': os.path.relpath(dest, self.root).replace(os.sep, '/'),
            'name': stem, 'files': files, 'face_stats': face_stats,
            'fingerprint': {'sha256': sha, 'size': total_bytes,
                            'mtime': max(m['mtime'] for m in face_src)}}
        self._dirty = True
        return self._finish(gid)

    def import_material(self, mat, guid=None):
        """材质资产（值 + 贴图 guid 引用）-> (guid, created, reason)。"""
        gid = guid or getattr(mat, 'guid', None) or new_guid()
        value = {'name': getattr(mat, 'name', None), 'color': getattr(mat, 'color', None),
                 'saturation': getattr(mat, 'saturation', 1.0),
                 'metallic': getattr(mat, 'metallic', 0.0),
                 'roughness': getattr(mat, 'roughness', 0.5),
                 'pbr': bool(getattr(mat, 'pbr', False))}
        reasons = []
        kept = getattr(mat, '_asset_ref_slots', None)
        kept = kept if isinstance(kept, dict) else {}
        for slot in ('albedo', 'normal_map'):
            tex = getattr(mat, slot, None)
            if tex is None:
                # P1-1 语义延续到资产库层：解析失败的槽位保留原 guid 引用，
                # 不因"这次没解析出来"把引用从库 value 里抹掉。
                _ref = kept.get(slot)
                _g = (_ref or {}).get('guid') if isinstance(_ref, dict) else None
                if isinstance(_g, str) and _g:
                    value[slot] = _g
                continue
            tg = getattr(tex, 'guid', None)
            if self.owns(tg, 'texture'):
                value[slot] = tg
                continue
            src = getattr(tex, 'path', None)
            if src and os.path.isfile(src):
                ng, created, why = self.import_texture(
                    src, name=getattr(tex, 'name', None), guid=tg,
                    import_settings={k: getattr(tex, k, None)
                                     for k in IMPORT_KEYS if hasattr(tex, k)})
                if ng:
                    value[slot] = ng
                elif why:
                    reasons.append('%s: %s' % (slot, why))
            else:
                reasons.append('%s: 贴图无源文件（无法登记）' % slot)
        env = getattr(mat, 'env_map', None)
        if env is None:
            _ref = kept.get('env_map')
            _g = (_ref or {}).get('guid') if isinstance(_ref, dict) else None
            if isinstance(_g, str) and _g:
                value['env_map'] = _g
        if env is not None:
            eg = getattr(env, 'guid', None)
            if self.owns(eg, 'cubemap'):
                value['env_map'] = eg
            elif getattr(env, 'paths', None):
                ng, created, why = self.import_cubemap(env.paths, name=getattr(env, 'name', None),
                                                       guid=eg)
                if ng:
                    value['env_map'] = ng
                elif why:
                    reasons.append('env_map: %s' % why)
            elif getattr(env, '_solid_color', None):
                value['env_map_solid'] = list(env._solid_color)
        self.index.setdefault('assets', {})[gid] = {
            'type': 'material', 'src': None,
            'name': value.get('name') or '材质', 'value': value}
        self._dirty = True
        return self._finish(gid, ('; '.join(reasons) or None))

    # ---- 持久化 ----
    def save(self):
        self.last_save_error = None
        if self._dirty and not self.readonly:
            _p, _why = save_index(self.root, self.index)
            self.last_save_error = _why
        self._dirty = False
        return index_path(self.root)

    def _finish(self, gid, reason=None):
        """落盘 + 把"索引写失败"并进 reason（不静默成功）。"""
        self.save()
        err = self.last_save_error
        if err:
            return gid, True, ('%s；索引写入失败: %s' % (reason, err))
        return gid, True, reason


# ---------------------------------------------------------------- 便捷函数

def context_for_scene(scene_dir, create=False, readonly=False):
    """场景目录 -> AssetContext|None（供 sceneio / scene_driver 统一入口）。"""
    try:
        return AssetContext.for_dir(scene_dir, create=create, readonly=readonly)
    except Exception as e:
        warn_once(('ctx', str(scene_dir)), '[资产] 项目资产索引不可用 (%r) -> 走旧路径模式' % (e,))
        return None
