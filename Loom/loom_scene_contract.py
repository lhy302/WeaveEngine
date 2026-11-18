# -*- coding: utf-8 -*-
"""loom_scene_contract.py — **场景契约**：版本号 / 版本闸门 / 数据迁移（B7-16，2026-11-18）。

人类裁决原话：
  「场景迁移功能我好像也明确要求单独一个模块，因为**只是数据到数据的转换，不需要涉及
    复杂的内部操作**，且如果在特定场景下转换是有问题的话**修起来也容易**。」

所以本模块的定位是**纯数据 → 数据**：
  · 输入：场景 dict（json.load / 游戏包解出来的那一份）；
  · 输出：同一份 dict 的**当前版本**形态；
  · 不 import sceneio / engine / moderngl / wgpu / glfw，不建窗口、不碰 GPU、不建引擎实例
    —— `import loom_scene_contract` 可以单独跑（门：tests/test_scene_contract.py 用子进程
    断言 sys.modules 里没有引擎/GPU/窗口模块）。

对外契约（外部只用这 5 个名字）：
  CURRENT_VERSION    场景序列化版本 —— **唯一真源**（sceneio.SCENE_VERSION 是它的别名）
  SceneVersionError  闸门拒绝加载时抛的错误（sceneio 同名 re-export）
  gate(data)         版本闸门：场景要求的引擎版本高于当前引擎 -> 抛；通过 -> True
  migrate(data)      数据迁移：v1..v11 -> 当前版本（原地改并返回同一对象）
  prepare(data)      **唯一推荐入口**：gate + migrate 一次做完

我负责什么 / 我不负责什么：
  ✓ 版本号常量、版本串解析、闸门判定、跨版本的数据改写（纯数据）；
  ✗ 场景 -> 引擎装配（sceneio.scene_from_dict / scene_driver.build_*）、资产解析、天空盒、
    材质库、清场景 —— 那些要引擎状态，留在各自模块；
  ✗ 打开场景的**时机**（先校验再清空 / 失败可见）—— 由各入口调用 prepare() 保证，
    见 tests/test_scene_load_parity.py 的 ③-gate（R3）与 ③-newer（R5）。

为什么单独成文件（开发要求_功能解耦与模块化.md 规则 1/规则 3）：版本迁移是编辑器、GL 播放器、
VK 播放器、打包游戏、游戏包、Hub 校验**共同的**前置 —— 共同前置抽成独立库，而不是把六条路径
各自写一份（旧状：闸门 5 处重复调用、迁移只有 1 处调用点 -> 两端行为分叉，B7-17）。

纪律（门会检查）：本文件**不许** import sceneio / engine / 任何 GPU/窗口模块。
"""
import json
import math
import os
import uuid

from loom_scene_entities import wrap_deg   # 纯 math 工具（只依赖 math/uuid/loom_types）


CURRENT_VERSION = 12  # v12 (Q-B1-3=A 材质真相源): 场景 materials[] 只写引用, 定义在资产库

# ============================================================================
# beta6 C1/D7: 引擎版本闸门
# ----------------------------------------------------------------------------
# 背景: migrate() 只抬 version、不认"更高版本写下的新字段" —— 旧引擎读新场景
# 会把 animator.speed / clip_meta 等未知键**静默丢弃** (research_beta6_03 §④ R1)。
# 现在场景写入 min_engine_version(=当前引擎版本), 加载时低版本引擎明确拒绝。
# 兼容: 旧场景/第三方(Hub)写出的场景没有该字段 -> 不设闸, 行为与以前一致。
# ============================================================================
# 兜底常量：只在"产物里没有 解释器.json"时触发（旧包/手工拷贝）。
# 2026-11-10 起 build_engine / package_engine_compiled 都会把 解释器.json 带进
# dist 并在构建时断言版本一致 —— 正常产物必带，不应走到这里。
_ENGINE_VERSION_FALLBACK = '0.1.0.beta6'


def _read_engine_version():
    """当前引擎版本. 单一事实源 = 引擎目录 解释器.json; 读不到 -> 常量兜底."""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '解释器.json')
        with open(p, 'r', encoding='utf-8') as f:
            v = json.load(f).get('version')
        if isinstance(v, str) and v.strip():
            return v.strip()
    except Exception:
        pass
    return _ENGINE_VERSION_FALLBACK


ENGINE_VERSION = _read_engine_version()


class SceneVersionError(ValueError):
    """场景要求的引擎版本高于当前引擎 —— 明确拒绝加载 (不静默丢字段)."""


def parse_version(text):
    """版本串 -> 可比较 5 元组; 无法解析 -> None.

    '0.1.0.beta6' / '0.1.0-beta6' -> (0, 1, 0, 0, 6)   第 4 位 0 = 预发布
    '0.1.0'                       -> (0, 1, 0, 1, 0)   第 4 位 1 = 正式版
    '1.2'                         -> (1, 2, 0, 1, 0)
    '1.2.3+build.5'               -> (1, 2, 3, 1, 0)   (丢弃 '+' 之后的构建元数据)

    R6 F-02: 分隔符统一 ('.' / '-' / '_' 等价) —— 旧实现把 '0.1.0-beta6'
    判成不可解析, 而 gate 那时是"解析失败即放行" -> 闸门静默
    fail-open。现在解析失败在**要求侧**是拒绝 (见 gate)。
    """
    if not isinstance(text, str):
        return None
    s = text.strip().lower()
    if not s:
        return None
    s = s.split('+', 1)[0]              # 构建元数据不影响比较
    for ch in ('-', '_'):
        s = s.replace(ch, '.')
    nums = []
    beta = None
    for part in s.split('.'):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            nums.append(int(part))
        elif part.startswith('beta'):
            tail = part[4:]
            if tail and not tail.isdigit():
                return None
            beta = int(tail) if tail else 0
        else:
            return None                 # 未知段 (rc1/alpha/日期) -> 不可判定
    if not nums:
        return None
    while len(nums) < 3:
        nums.append(0)
    if beta is None:
        return (nums[0], nums[1], nums[2], 1, 0)
    return (nums[0], nums[1], nums[2], 0, beta)


def version_lt(current, required):
    """current 是否低于 required. 任一不可解析 -> False (无法判定则不拦)."""
    a = parse_version(current)
    b = parse_version(required)
    if a is None or b is None:
        return False
    return a < b


_VERSION_EXPECTED = '期望形如 "0.1.0.beta6" 的版本字符串 (支持 x.y.z 与 x.y.z-betaN)'


def gate(data, engine_version=None):
    """加载前版本闸门. 不满足抛 SceneVersionError(带原因), 通过返回 True.

    - **无该字段** (旧场景 / Hub 写出的场景) -> 不设闸 (向后兼容);
    - 字段**存在**但类型不对 (非 str: int/list/bool/null) 或为空串
      -> **拒绝** (R6 U-02=B: 发布版看不到 print, 静默放行等于埋雷);
    - 字段存在但**不可解析** -> 拒绝 (R6 F-02: 旧实现"解析失败即放行"
      等于闸门静默 fail-open —— 更旧的引擎会带着未知字段静默加载);
    - 引擎自身版本不可解析 -> 显式告警后放行 (无法比较; 但不静默, 打一行);
    - 当前引擎低于要求 -> 拒绝, 原因里同时给出"要求版本 / 当前版本".
    """
    if not isinstance(data, dict):
        return True
    if 'min_engine_version' not in data:
        return True                     # 旧场景/无字段 -> 不加闸
    need = data.get('min_engine_version')
    if not isinstance(need, str) or not need.strip():
        raise SceneVersionError(
            '场景 min_engine_version=%r 非法 (类型=%s): %s; 拒绝加载'
            ' (字段存在就必须合法, 旧场景请删掉该字段)'
            % (need, type(need).__name__, _VERSION_EXPECTED))
    need = need.strip()
    cur = engine_version if engine_version is not None else ENGINE_VERSION
    need_p = parse_version(need)
    if need_p is None:
        raise SceneVersionError(
            '场景 min_engine_version=%r 无法解析: %s; 拒绝加载'
            ' (无法判定版本要求时不放行, 以免旧引擎静默丢字段)'
            % (need, _VERSION_EXPECTED))
    cur_p = parse_version(cur)
    if cur_p is None:
        print('[场景] 当前引擎版本 %r 无法解析: 无法比较 min_engine_version=%r,'
              ' 本次放行 (请修正 解释器.json 的 version)' % (cur, need))
        return True
    if cur_p < need_p:
        raise SceneVersionError(
            '场景要求引擎 >= %s, 当前引擎 %s: 拒绝加载 (旧引擎读新场景会静默丢字段, '
            '请先升级引擎, 或用旧版引擎"导出兼容场景"后重试)' % (need, cur))
    return True

def _new_guid():
    """新对象 id（32 hex）。与 sceneio.generate_guid 同实现（uuid4().hex）——
    独立一份是为了让本模块**不 import sceneio**（契约模块必须能单独 import）。"""
    return uuid.uuid4().hex
def migrate(data):
    """版本迁移 (原地修改并返回). 旧格式/缺版本一律能加载.

    beta6 C1/D7: 第一步就过"引擎版本闸门" —— 场景要求更高版本时抛
    SceneVersionError (明确拒绝), 绝不带着未知字段静默加载。
    """
    gate(data)
    v = data.get('version', 1) if isinstance(data, dict) else 1
    if not isinstance(data, dict):
        data = {'version': CURRENT_VERSION, 'objects': []}
        v = CURRENT_VERSION
    if v < 1:
        data = {'version': CURRENT_VERSION, 'objects': list(data.get('objects', []))}
        v = CURRENT_VERSION
    if v < 3:
        # v1/v2 -> v3: 补光源数组 (旧存档无光源, 默认空)
        data.setdefault('lights', [])
    if v < 4:
        # v3 -> v4 (M25 组件化): 单 "script" 字段 -> "scripts" 数组 (物体可挂多个脚本)
        for obj in data.get('objects', []):
            sc = obj.get('script')
            if isinstance(sc, dict) and sc.get('id') and 'scripts' not in obj:
                obj['scripts'] = [sc]
            obj.pop('script', None)
    if v < 5:
        # v4 -> v5 (M23 材质资产): 补空材质库; 旧对象无 material_id,
        # _apply_object 会自动按颜色/饱和度自建材质, 无需改写对象.
        data.setdefault('materials', [])
    if v < 6:
        # v5 -> v6 (M28 碰撞体): 旧对象无 collider 字段 -> 加载时按类型自动派生
        # (球=球体, 其他=盒子), 无需改写对象.
        pass
    if v < 7:
        # v6 -> v7 (摄像机实体): 旧存档无摄像机, 补空数组 + active_camera 空
        data.setdefault('cameras', [])
        data.setdefault('active_camera', None)
    if v < 8:
        # v7 -> v8 (M29 光照遮挡/光束): 旧光源补 mode/shape/size/shadow 默认
        for lt in data.get('lights', []):
            lt.setdefault('mode', 'full')
            lt.setdefault('shape', 'circle')
            lt.setdefault('size', 5.0)
            lt.setdefault('shadow', True)
    if v < 9:
        # v8 -> v9 (M41 摄像机度制朝向): 旧摄像机 yaw/pitch 由弧度转度, 补 roll=0
        # 与俯仰角限制默认. **只改 cameras 数组; 顶层编辑器轨道 "camera" dict 仍是
        # 弧度 (那是导航相机不是 CameraState), 不碰.**
        for cm in data.get('cameras', []):
            cm['yaw']   = wrap_deg(math.degrees(cm.get('yaw', 0.0)), 0.0, 360.0)
            cm['pitch'] = wrap_deg(math.degrees(cm.get('pitch', 0.0)), -180.0, 180.0)
            cm['roll']  = wrap_deg(cm.get('roll', 0.0), -180.0, 180.0)
            cm.setdefault('pitch_lock', False)
            cm.setdefault('pitch_min', -85.0)
            cm.setdefault('pitch_max', 85.0)
    if v < 10:
        # v9 -> v10 (2026-08-16 相机物体化): 旧摄像机无父, 补 parent_id=None
        for cm in data.get('cameras', []):
            cm.setdefault('parent_id', None)
    if v < 12:
        # v11 -> v12 (Q-B1-3=A 材质真相源收敛到 Assets/assets.json):
        # migrate 保持纯函数 —— 不改写数据。加载侧按"资产库权威"解释：
        # 场景内联定义被忽略（不一致才告警），保存时只写引用。
        # 一次性抽出由 tools/migrate_scene_assets_v11.py（材质段）完成。
        pass
    if v < 11:
        # v10 -> v11 (beta6 B1 资产 guid): **不在 migrate 里改写数据**（保持纯函数、可重复）。
        # 旧 path/paths 字段由加载侧兼容读并告警（一个 beta 周期的 fallback）；
        # 真正的"路径 -> guid"补全交给一次性脚本 tools/migrate_scene_assets_v11.py。
        pass
    if v == 1:
        # v1: 扁平对象, 有 id 无 parent/prefab; 无 id 就生成一个
        for obj in data.get('objects', []):
            if not obj.get('id'):
                obj['id'] = _new_guid()
            obj.setdefault('parent_id', None)
            obj.setdefault('prefab_ref', None)
    data['version'] = CURRENT_VERSION
    return data

def prepare(data, migrate_fn=None):
    """**场景打开的唯一推荐入口**：先过版本闸门，再做数据迁移；返回同一份数据。

    顺序是契约的一部分（不是实现细节）：闸门必须在**任何状态变更之前**跑。
    R5 缺陷就是"先 clear_scene 再校验"，于是"加载更高版本场景失败"在 GL 上把当前场景
    清空、在 VK 上保留 —— 同一个失败，两端用户可见结果不同。

    migrate_fn：迁移实现注入点（默认本模块的 migrate）。sceneio 传入它自己 re-export 的
    `migrate` 符号，保证 `sceneio.migrate` 仍然是**真正被调用**的实现（历史调用点、
    monkeypatch 探针、tests/test_scene_load_parity.py ③-migrate 都按那个符号观察）。
    语义只有一份 —— 本函数不重复实现迁移。
    """
    gate(data)                                  # 1) 闸门（先于任何状态变更）
    return (migrate if migrate_fn is None else migrate_fn)(data)   # 2) 数据迁移
