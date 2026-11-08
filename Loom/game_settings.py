# -*- coding: utf-8 -*-
"""game_settings.py — 单游戏设置 (与 Unity PlayerPrefs / UE GameUserSettings 同角色)。

分层（契约 docs/design/用户配置目录契约_20261108.md §1/§2/§4）:
  · 模板层 = 游戏文件夹（exe 同级）的 游戏设置.json —— **只读**，运行时永不写；
  · 用户层 = userpaths.game_settings(game_id)（%LOCALAPPDATA%\Loom\games\…）；
  · 合并   = 模板为底 + 用户 delta 覆盖 + 未知键保留；
  · 旧形态 = 游戏配置.json / 旧版 游戏设置.json（含 game_id 时按 id 归位）。

测试/调试强制覆盖:
  LOOM_GAME_DIR  → 直接用该目录的 游戏设置.json（读写同一文件，旧语义）
  LOOM_GAME_ID   → 强制用户层 game_id
  LOOM_PROJECT_DIR → 按编辑器工程 id 落 projects\<pid>\settings.json

写入一律 tmp + os.replace，**失败上抛**（§7：禁止 except: pass / 假成功）。
"""
import json
import os
import sys
import time

FILE_NAME = "游戏设置.json"
LEGACY_FILE_NAME = "游戏配置.json"
SCHEMA = 1

UNLOCK_ACTION = "解锁鼠标"      # 引擎保留动作名 (可在 key_bindings 里改键)
# 2026-11-08 人类裁决: **默认不锁鼠标** —— 没人要求就不锁。
#   allowed=False 时引擎完全不触发锁定（脚本调 set_mouse_locked(True) 也无效）；
#   initial 仅在 allowed=True 时才有意义（默认 False）。
# 需要锁鼠标的游戏在 游戏设置.json 写 {"mouse_lock_allowed": true, "mouse_locked": true}，
# 或在脚本里显式 engine.set_mouse_lock_allowed(True)。
MOUSE_LOCK_ALLOWED_DEFAULT = False
MOUSE_LOCK_INITIAL_DEFAULT = False


# ---------------- 路径与标识 ----------------

def _userpaths():
    try:
        import userpaths
        return userpaths
    except Exception:
        return None


def game_dir():
    """游戏文件夹（模板层所在处）: LOOM_GAME_DIR > 主程序目录 > 当前目录。"""
    d = os.environ.get("LOOM_GAME_DIR")
    if d and os.path.isdir(d):
        return d
    try:
        main = os.path.abspath(sys.argv[0])
        if main:
            return os.path.dirname(main) or os.getcwd()
    except Exception:
        pass
    return os.getcwd()


def template_path():
    """只读模板: <游戏文件夹>/游戏设置.json."""
    return os.path.join(game_dir(), FILE_NAME)


def legacy_path():
    """更早形态（只读迁移源）: <游戏文件夹>/游戏配置.json."""
    return os.path.join(game_dir(), LEGACY_FILE_NAME)


def game_id():
    """本"游戏/工程"的稳定标识（契约 §3）。"""
    forced = os.environ.get("LOOM_GAME_ID")
    if forced:
        return str(forced)
    proj = os.environ.get("LOOM_PROJECT_DIR")
    if proj:
        up = _userpaths()
        if up is not None:
            try:
                pid, _created = up.project_id(proj)
                return "project-%s" % (pid,)
            except Exception:
                pass
        return "project-%s" % (os.path.basename(os.path.abspath(proj)) or "default",)
    d = game_dir()
    cfg = {}
    for _p in (legacy_path(), template_path()):
        try:
            _d = _read_json(_p)
        except ValueError as e:
            print("[配置] %r -> 忽略该层 (只用于取标识)" % (e,))
            _d = None
        if isinstance(_d, dict):
            cfg = _d
            break
    if isinstance(cfg, dict) and str(cfg.get("game_id") or "").strip():
        return str(cfg["game_id"]).strip()
    up = _userpaths()
    if up is not None:
        title = cfg.get("title") if isinstance(cfg, dict) else None
        return up.game_id_for(d, title)
    base = os.path.basename(os.path.abspath(d)) or "game"
    return base


def user_path(base_dir=None):
    """用户层文件（写者唯一落点）。

    base_dir 显式给出 = 调用方自行指定目录（测试/工具/上层已有路径覆盖时用，
    例如 run_player._SETTINGS_BASE）；否则 LOOM_GAME_DIR > 用户层。
    """
    if base_dir:
        return os.path.join(os.path.abspath(base_dir), FILE_NAME)
    d = os.environ.get("LOOM_GAME_DIR")
    if d and os.path.isdir(d):
        return os.path.join(d, FILE_NAME)
    up = _userpaths()
    gid = game_id()
    if up is None:
        return os.path.join(game_dir(), FILE_NAME)
    if gid.startswith("project-") and os.environ.get("LOOM_PROJECT_DIR"):
        return up.project_settings(gid[len("project-"):])
    return up.game_settings(gid)


def path():
    """兼容旧名：返回**用户层**路径（读写的落点；模板用 template_path()）。"""
    return user_path()


# ---------------- 低层 JSON ----------------

def _read_json(p):
    """读 JSON 文件：不存在 -> None；损坏 -> 上抛 ValueError（由调用方决定备份）。"""
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        raise
    except (ValueError, OSError) as e:
        raise ValueError("读取 %s 失败: %r" % (p, e))


def _extract(d):
    """把"新格式 {schema,values}"或"旧格式 plain dict"统一抽出值字典。"""
    if not isinstance(d, dict):
        return {}
    if "schema" in d and isinstance(d.get("values"), dict):
        return dict(d["values"])
    return dict(d)


def _atomic_write(p, data):
    """tmp + os.replace 原子写；任何失败上抛（§7）。"""
    up = _userpaths()
    d = os.path.dirname(os.path.abspath(p))
    if up is not None:
        up.ensure_dir(d)
    else:
        os.makedirs(d, exist_ok=True)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _backup(p):
    """把坏文件改名留证（*.bak-<ts>.json）。返回备份路径；失败返回 None 并告警。"""
    up = _userpaths()
    try:
        if up is not None:
            up.ensure_parent(p)
            dst = up.backup_path(p)
        else:
            dst = p + ".bak"
        os.replace(p, dst)
        print("[配置] 已备份损坏的配置: %s" % dst)
        return dst
    except OSError as e:
        print("[配置] 备份失败 (%r): %s" % (e, p))
        return None


# ---------------- 迁移（契约 §6） ----------------

def _migrate_legacy(cfg_exists):
    """把旧形态里可识别的键搬进 values（宁留勿丢）。返回 (values, notes)。"""
    values = {}
    notes = []
    srcs = []
    # 契约 §6-1 的"exe 旁 游戏设置.json"在本实现里就是**模板层**：它在 load()
    # 里已作为基底被合并（值天然生效），因此不再复制一份进 values —— 否则
    # values 会变成"模板快照"而不是用户 delta（违反 §4）。
    # 真正需要搬键的是更早形态 游戏配置.json（§6-2）：
    lp = legacy_path()
    if os.path.isfile(lp):
        srcs.append(lp)
    for p in srcs:
        try:
            raw = _read_json(p)
        except ValueError as e:
            notes.append("%s 不是合法 JSON (%r)，已跳过" % (os.path.basename(p), e))
            continue
        vals = _extract(raw)
        for k, v in vals.items():
            if k in ("schema", "values", "updated_at", "game_id", "origin", "app"):
                continue
            values.setdefault(k, v)
        if vals:
            notes.append("%s: 迁移 %d 个键" % (os.path.basename(p), len(vals)))
    return values, notes


# ---------------- 读取（模板 + 用户层合并） ----------------

def _read_layer(p):
    """读一层：返回 values；坏文件 -> 备份 + 空（写失败不阻断启动，但要出声）。"""
    try:
        raw = _read_json(p)
    except ValueError as e:
        print("[配置] %r -> 备份后按默认启动" % (e,))
        _backup(p)
        return {}
    if raw is None:
        return {}
    return _extract(raw)


def load():
    """合并配置（模板为底 + 用户 delta）。坏用户文件 -> 备份 + 默认。"""
    merged = {}
    tp = template_path()
    try:
        same = os.path.abspath(tp) == os.path.abspath(user_path())
    except OSError:
        same = False
    if not same:
        merged.update(_read_layer(tp))
    merged.update(_read_layer(user_path()))
    return merged


def read(key, default=None):
    return load().get(key, default)


def bootstrap():
    """首次使用: 建用户层文件 {schema:1, values:{}}（含一次旧格式迁移）。失败上抛。"""
    p = user_path()
    try:
        if os.path.isfile(p):
            return False
    except OSError:
        pass
    values, notes = _migrate_legacy(False)
    data = {"schema": SCHEMA, "game_id": game_id(), "origin": game_dir(),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "values": values}
    _atomic_write(p, data)
    if notes:
        print("[配置] 旧格式迁移: %s" % "; ".join(notes))
    return True


def set_value(key, value, base_dir=None):
    """写单个配置项（其它键保留，只落 delta）。返回写入后的 values；失败上抛。"""
    p = user_path(base_dir)
    values = _read_layer(p)
    values[key] = value
    data = {"schema": SCHEMA, "game_id": game_id(), "origin": game_dir(),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "values": values}
    _atomic_write(p, data)
    return values


# ---------------- 鼠标锁定 ----------------

def read_bool(key, default=False):
    v = read(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(v, (int, float)):
        return bool(v)
    if v is not None:
        print("[配置] %s 取值类型非法 (%r)，按默认 %r" % (key, v, default))
    return bool(default)


def mouse_lock_allowed():
    return read_bool("mouse_lock_allowed", MOUSE_LOCK_ALLOWED_DEFAULT)


def mouse_lock_initial():
    """启动时是否锁鼠标 (不允许锁定 -> 恒 False)。"""
    if not mouse_lock_allowed():
        return False
    return read_bool("mouse_locked", MOUSE_LOCK_INITIAL_DEFAULT)


# ---------------- 键位 ----------------

def read_key_bindings():
    """读本游戏的键位覆盖 {动作: [键...]}。

    坏值不再静默丢弃：动作名与键名都会出声告警（审计 P-01-11），
    整份不是 dict 时同样告警并返回 {}。
    """
    d = load().get("key_bindings")
    if d is None:
        return {}
    if not isinstance(d, dict):
        print("[配置] key_bindings 应为对象，实际 %s -> 忽略该层"
              % type(d).__name__)
        return {}
    out = {}
    for a, ks in d.items():
        name = str(a)
        if isinstance(ks, str):
            out[name] = [ks]
        elif isinstance(ks, (list, tuple)):
            keys = []
            for k in ks:
                if isinstance(k, str) and k:
                    keys.append(k)
                else:
                    print("[配置] key_bindings[%r] 含非法键名 %r -> 已丢弃" % (name, k))
            if keys:
                out[name] = keys
            else:
                print("[配置] key_bindings[%r] 无有效键名 -> 该动作保持上一层绑定" % (name,))
        else:
            print("[配置] key_bindings[%r] 取值类型非法 (%s) -> 忽略"
                  % (name, type(ks).__name__))
    return out


def _sanitize_keys(keys):
    if isinstance(keys, str):
        keys = [keys]
    out = []
    for k in (keys or []):
        if isinstance(k, str) and k:
            out.append(k)
        else:
            print("[配置] 键名非法 %r -> 已丢弃" % (k,))
    return out


def write_key_bindings(mapping):
    """批量写键位（只落用户层 delta）。返回写入的键位表；失败上抛。"""
    p = user_path()
    values = _read_layer(p)
    kb = values.get("key_bindings")
    if not isinstance(kb, dict):
        kb = {}
    for a, keys in (mapping or {}).items():
        ks = _sanitize_keys(keys)
        if ks:
            kb[str(a)] = ks
        else:
            kb.pop(str(a), None)
    values["key_bindings"] = kb
    data = {"schema": SCHEMA, "game_id": game_id(), "origin": game_dir(),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "values": values}
    _atomic_write(p, data)
    return kb


def write_key_binding(action, keys):
    """把单个动作的键位写进用户层（其它动作保留）。失败上抛。"""
    return write_key_bindings({str(action): keys})


# ---------------- 渲染后端 ----------------

BACKENDS = ("vulkan", "opengl", "auto")


def normalize(api):
    """归一后端名; 非法值返回 None。"""
    if api is None:
        return None
    a = str(api).strip().lower()
    return a if a in BACKENDS else None


def read_render_api():
    """读游戏设置里的渲染后端 (缺失/非法 -> None)。"""
    return normalize(read("render_api"))


def write_render_api(api, base_dir=None):
    """写渲染后端。返回 (ok, 归一值或 None, 错误信息或 None)。

    base_dir: 上层显式指定落点（测试隔离/调试覆盖），缺省走用户层。
    """
    a = normalize(api)
    if a is None:
        return False, None, "render_api 必须是 vulkan / opengl / auto"
    try:
        set_value("render_api", a, base_dir=base_dir)
    except Exception as e:
        return False, a, "写入失败: %r" % (e,)
    return True, a, None
