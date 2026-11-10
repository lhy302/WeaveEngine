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

# 索引读缓存: (index_path, mtime_ns, size) -> index dict（只读共享；save 时清）
_CACHE = {}
# 旧路径告警去重（同一进程同一 ref 只告警一次，避免刷屏）
_WARNED = set()


def new_guid():
    """新资产 guid（32 hex，与 sceneio.generate_guid 同格式）。"""
    return uuid.uuid4().hex


_ILLEGAL_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_asset_name(name, default='asset'):
    """把用户给的 name 净化成安全文件名（P2-①: 不允许写出 Assets/ 之外）。

    只取 basename（去掉任何目录部分）、替换 Windows 非法字符、去掉首尾点/空格、
    '..' 折叠。返回值不会是 '' / '.' / '..'。
    """
    s = str(name or '').replace('\\', '/')
    s = s.rsplit('/', 1)[-1].strip()
    s = _ILLEGAL_NAME.sub('_', s)
    s = s.strip(' .')
    s = s.replace('..', '_')
    return s or default


def warn_once(key, msg):
    """同一 (key) 只打印一次；返回是否本次真的打印了。"""
    if key in _WARNED:
        return False
    _WARNED.add(key)
    print(msg)
    return True


def reset_caches():
    """测试用: 清空索引缓存与告警去重。"""
    _CACHE.clear()
    _WARNED.clear()


# ---------------------------------------------------------------- 路径与校验

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


def load_index(root):
    """读项目层索引 -> (index|None, ok, reason).

    ok=False: 文件缺失 / JSON 损坏 / 结构非法（此时 index=None，**不可用**）
    ok=True + reason 非空 = **部分可用**（个别坏条目已剔除，reason 是告警文本）。
    逐条容错（Q-B1-2=A）：一条坏条目不再让整本索引作废。
    """
    p = index_path(root)
    try:
        st = os.stat(p)
    except OSError:
        return None, False, '资产索引不存在: %s' % p
    key = (p, st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(key)
    if hit is not None:
        data, warns = hit
        return data, True, ('; '.join(warns) if warns else None)
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, False, '资产索引损坏 (%r): %s' % (e, p)
    ok, warns = validate_index(data, root)
    if not ok:
        return None, False, '; '.join(warns[:3])
    if warns:
        warn_once(('idx-partial', p, st.st_mtime_ns),
                  '[资产] 索引有 %d 条坏条目已剔除（其余照常可用）: %s'
                  % (len(warns), '; '.join(warns[:3])))
    _CACHE[key] = (data, list(warns))
    return data, True, ('; '.join(warns) if warns else None)


def inspect_index(root):
    """索引体检 -> {state, reason, warnings, count, path}。

    state: missing（文件不存在）/ corrupt（JSON 坏）/ invalid（结构非法、不可用）
           / partial（部分条目被剔除、其余可用）/ ok。
    供 asset_list / scene_assets_check 区分「缺文件」与「文件在但坏了」。
    """
    p = index_path(root)
    if not os.path.isfile(p):
        return {'state': 'missing', 'reason': '资产索引不存在: %s' % p,
                'warnings': [], 'count': 0, 'path': p}
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return {'state': 'corrupt', 'reason': '资产索引损坏 (%r)' % (e,),
                'warnings': [], 'count': 0, 'path': p}
    ok, warns = validate_index(data, root)
    if not ok:
        return {'state': 'invalid', 'reason': '; '.join(warns[:3]),
                'warnings': warns, 'count': 0, 'path': p}
    return {'state': ('partial' if warns else 'ok'),
            'reason': ('; '.join(warns[:3]) if warns else None),
            'warnings': warns, 'count': len(data.get('assets') or {}),
            'path': p}


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
            if not isinstance(src, str) or os.path.isabs(src):
                bad.append(gid)
                warnings.append('%s: src 必须是项目相对路径 (收到 %r)' % (gid, src))
                continue
            parts = src.replace('\\', '/').split('/')
            if '..' in parts:
                bad.append(gid)
                warnings.append('%s: src 越界/相对路径 (收到 %r)' % (gid, src))
                continue
            if not (src == ASSETS_DIR or src.startswith(ASSETS_DIR + '/')):
                bad.append(gid)
                warnings.append('%s: src 必须位于 Assets/ 之下 (收到 %r)'
                                % (gid, src))
                continue
            if root is not None and not is_inside(root, os.path.join(root, src)):
                bad.append(gid)
                warnings.append('%s: src 越界 (%r)' % (gid, src))
                continue
        if 'import' in e and not isinstance(e.get('import'), dict):
            bad.append(gid)
            warnings.append('%s: import 必须是对象' % gid)
    for gid in bad:
        assets.pop(gid, None)
    return True, warnings


def save_index(root, index):
    """原子写项目层索引（tmp + fsync + replace）。返回路径。"""
    os.makedirs(assets_dir(root), exist_ok=True)
    p = index_path(root)
    index = dict(index or {})
    index['schema'] = SCHEMA
    index.setdefault('assets', {})
    tmp = '%s.tmp.%d' % (p, os.getpid())
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    _CACHE.clear()
    return p


def _load_user_delta(root):
    try:
        with open(user_index_path(root), 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('assets'), dict):
            return data['assets']
    except (OSError, ValueError):
        pass
    return {}


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
        self.errors = []            # [(where, guid, reason)] —— 供 sceneio 汇总

    def _warn(self, msg, key=None):
        if msg and msg not in self.warnings:
            self.warnings.append(msg)
            warn_once(key or ('ctx-warn', self.root, msg), '[资产] %s' % (msg,))

    # ---- 构造 ----
    @classmethod
    def for_dir(cls, d, create=False, readonly=False):
        """目录 -> 上下文；无项目索引且 create=False 时返回 None（旧路径模式）。"""
        if d is None:
            return None
        root = find_project_root(d)
        if root is None:
            if not create:
                return None
            root = os.path.abspath(d)
            if not readonly:
                os.makedirs(assets_dir(root), exist_ok=True)
                save_index(root, empty_index(root))
            return cls(root, empty_index(root), readonly=readonly)
        return cls.open_root(root, create=create, readonly=readonly)

    @classmethod
    def open_root(cls, root, create=False, readonly=False):
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
                save_index(root, empty_index(root))
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
    def _import_settings(self, entry, ref=None):
        s = dict(DEFAULT_IMPORT)
        s.update(entry.get('import') or {})
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
        s = self._import_settings(e, ref)
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
        for slot in ('albedo', 'normal_map'):
            g = v.get(slot)
            if not g:
                continue
            tex, ok, why = self.texture(g)
            if tex is not None:
                setattr(mat, slot, tex)
            if why and first_reason is None:
                first_reason = why
        g = v.get('env_map')
        if g:
            cube, ok, why = self.cubemap(g)
            if cube is not None:
                mat.env_map = cube
            if why and first_reason is None:
                first_reason = why
        elif v.get('env_map_solid'):
            try:
                from loom_cubemap import Cubemap
                mat.env_map = Cubemap.from_solid(tuple(v['env_map_solid']),
                                                 name=v.get('name'), guid=guid + ':env')
            except Exception:
                pass
        return mat, True, first_reason

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

    def import_texture(self, src, name=None, import_settings=None, guid=None):
        """导入贴图（复制进项目）-> (guid|None, created, reason)。"""
        src = os.path.abspath(src)
        if not os.path.isfile(src):
            return None, False, '源文件不存在: %s' % (src,)
        if os.path.splitext(src)[1].lower() not in IMAGE_EXTS:
            return None, False, '不支持的图片格式: %s' % (os.path.splitext(src)[1],)
        fp = fingerprint(src)
        sha = fp['sha256']
        if guid:
            e = self.entry(guid)
            if e is not None:
                if (e.get('fingerprint') or {}).get('sha256') != sha:
                    return None, False, ('同 guid 指向不同内容（%s 已存在且内容不同）' % guid)
                return guid, False, None
        same = self._find_by_sha('texture', sha)
        if same is not None:
            return same, False, None
        base_name = name or os.path.basename(src)
        if not os.path.splitext(base_name)[1]:
            # name 不带扩展名时补源文件扩展名（否则 Assets/Textures/<name> 没有后缀，
            # 解码器只能靠猜 -> 资产文件名不可读且易被误判）
            base_name += os.path.splitext(src)[1] or '.png'
        dest = self._unique_dest('texture', base_name, create=not self.readonly)
        if not self.readonly:
            shutil.copy2(src, dest)
        gid = guid or new_guid()
        imp = dict(DEFAULT_IMPORT)
        imp.update(import_settings or {})
        self.index.setdefault('assets', {})[gid] = {
            'type': 'texture', 'src': os.path.relpath(dest, self.root).replace(os.sep, '/'),
            'name': name or os.path.splitext(os.path.basename(src))[0],
            'import': imp, 'fingerprint': fp}
        self._dirty = True
        self.save()
        return gid, True, None

    def import_cubemap(self, paths, name=None, guid=None):
        """导入六面图（6 张图 -> Assets/Cubemaps/<name>/px..nz）-> (guid, created, reason)。"""
        if not isinstance(paths, (list, tuple)) or len(paths) != 6:
            return None, False, '六面图必须给 6 个路径 (px,nx,py,ny,pz,nz)'
        abses = [os.path.abspath(str(p)) for p in paths]
        for i, p in enumerate(abses):
            if not os.path.isfile(p):
                return None, False, '第 %d 面源文件不存在: %s' % (i, p)
        sha = hashlib.sha256()
        for p in abses:
            sha.update(sha256_file(p).encode('ascii'))
        sha = sha.hexdigest()
        if guid:
            e = self.entry(guid)
            if e is not None:
                if (e.get('fingerprint') or {}).get('sha256') != sha:
                    return None, False, ('同 guid 指向不同内容（%s 已存在且内容不同）' % guid)
                return guid, False, None
        same = self._find_by_sha('cubemap', sha)
        if same is not None:
            return same, False, None
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
        total_bytes = 0
        for i, fname in enumerate(Cubemap.FACES):
            ext = os.path.splitext(abses[i])[1] or '.png'
            out = '%s%s' % (fname, ext)
            if not self.readonly:
                shutil.copy2(abses[i], os.path.join(dest, out))
            files.append(out)
            st = os.stat(abses[i])
            total_bytes += int(st.st_size)
            # P2-③: 逐面指纹（内容/时间戳），供 resolve 检测六面图被替换
            face_stats[out] = {'sha256': sha256_file(abses[i]),
                               'size': int(st.st_size), 'mtime': float(st.st_mtime)}
        gid = guid or new_guid()
        self.index.setdefault('assets', {})[gid] = {
            'type': 'cubemap', 'src': os.path.relpath(dest, self.root).replace(os.sep, '/'),
            'name': stem, 'files': files, 'face_stats': face_stats,
            'fingerprint': {'sha256': sha, 'size': total_bytes,
                            'mtime': max(os.stat(p).st_mtime for p in abses)}}
        self._dirty = True
        self.save()
        return gid, True, None

    def import_material(self, mat, guid=None):
        """材质资产（值 + 贴图 guid 引用）-> (guid, created, reason)。"""
        gid = guid or getattr(mat, 'guid', None) or new_guid()
        value = {'name': getattr(mat, 'name', None), 'color': getattr(mat, 'color', None),
                 'saturation': getattr(mat, 'saturation', 1.0),
                 'metallic': getattr(mat, 'metallic', 0.0),
                 'roughness': getattr(mat, 'roughness', 0.5),
                 'pbr': bool(getattr(mat, 'pbr', False))}
        reasons = []
        for slot in ('albedo', 'normal_map'):
            tex = getattr(mat, slot, None)
            if tex is None:
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
        self.save()
        return gid, True, ('; '.join(reasons) or None)

    # ---- 持久化 ----
    def save(self):
        if self._dirty and not self.readonly:
            save_index(self.root, self.index)
        self._dirty = False
        return index_path(self.root)


# ---------------------------------------------------------------- 便捷函数

def context_for_scene(scene_dir, create=False, readonly=False):
    """场景目录 -> AssetContext|None（供 sceneio / scene_driver 统一入口）。"""
    try:
        return AssetContext.for_dir(scene_dir, create=create, readonly=readonly)
    except Exception as e:
        warn_once(('ctx', str(scene_dir)), '[资产] 项目资产索引不可用 (%r) -> 走旧路径模式' % (e,))
        return None
