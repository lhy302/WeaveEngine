# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


"""test_user_api_parity.py — **用户 API 等价门**（这是「不受后端影响」的终点判据）。

人类要求（2026-11-17/18，多次重申）：
  「两个后端暴露给用户的 API 都是一样的，选择哪个后端在用户端就是换个配置，
    类似于 JVM 虚拟机：不管底层用的什么后端，往上暴露的接口都一样。」

因此本门不满足于「方法名集合差异在缩小」，而是要求：
  ① **用户 API 集合两端完全相同**（USER_API 名单里的每一条，两端都必须有）；
  ② 任何仍只在一端存在的公开成员，**必须**登记在 BACKEND_ONLY_* 白名单里并写明理由；
  ③ 白名单里不许出现用户 API（防止把「没做」写成「后端内部」蒙混过关）。

为什么要有 ②：渲染原语（draw_lines / push_scissor / render / run …）**本来就不该是用户 API**，
它们是后端/宿主的内部契约。把它们直接补到另一端，只会让「用户 API」这个概念继续糊着。
正确做法是：用户面求同，后端面显式登记 + 说明「用户为什么不该感知到它」。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

import engine as E                                         # noqa: E402
import render.vk.driver as SD                                  # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


# ============ 用户 API（两端必须都有、同名同语义） ============
# 来源：契约 docs/design/契约_IEngineAPI_20261117.md（A 类 + 宿主事件入口）
# 本名单只列「当前还差的一端」—— 已两端都有的 88 条由 test_engine_api_matrix 的
# 「共同成员」覆盖；这里补上必须补齐的缺口，缺口清零即达标。
USER_API_PENDING = {
    'add_light',            # 加光源（纯数据：LightState + 后端钩子挂阴影贴图）
    'remove_light',         # 删光源（同上，释放阴影贴图）
    'clear_scene',          # 清空场景（数据 + 后端资源钩子）
    'load_scene',           # 按路径加载场景（用户最常用的场景切换 API）
    'remove_subtree',       # 删子树（Destroy 级）
    'get_tps',              # 实测 TPS（状态栏/HUD 读）
    'get_logic_time_ratio', # 逻辑时钟健康度（诊断口）
    'step_logic_once',      # F10 单步（用户功能，不是调试残留）
    'update_scripts',       # 脚本推进入口（宿主/测试会显式调）
}

# ============ 后端 / 宿主内部（允许只在一端，但必须写明理由） ============
BACKEND_ONLY_GL = {
    'render': 'GL 整帧入口（推进时钟 + 绘制 + 上屏）；VK 的整帧由 render/vk/player.py 的 draw 三段组成'
              '（advance_logic → 位姿/VP → VkRenderer.draw_frame），故 VK 侧不提供同名 render'
              '（Q-B7-24-5 T1：非同义 → 后端内部）',
    'run': 'GL 主运行循环；嵌入式宿主不进入（VK 播放器有自己的循环）',
    'draw_screen_lines': 'GL 立即模式屏幕绘制原语',
    'draw_screen_polygon': 'GL 立即模式屏幕绘制原语',
    'draw_text_quad': 'GL 立即模式文字绘制原语',
    'draw_texture_quad': 'GL 立即模式纹理绘制原语',
    'push_scissor': 'GL 立即模式状态栈（VK 走 pass 状态）',
    'pop_scissor': 'GL 立即模式状态栈',
    'blit_texture': 'GL 立即模式 GUI 合成（VK 走 world_canvas pass）',
    'present_health': 'GL 上屏健康快照（诊断）',
    'get_frame_jitter': 'GL 帧长统计（诊断；VK 走 engine_metrics 命令）',
    'should_fallback_remote': 'GL 上屏失败回退诊断',
    'reset_sky_state': 'GL 天空盒渲染状态失效（后端内部）',
    # S3（Q-B7-47-1 阶段 3）：draw_lines / overlay_scope 已补 VK 实现
    # （loom_pass_vk.VkEditorRenderMixin，同签名）→ 升为两端共有，从本白名单删除。
}
BACKEND_ONLY_VK = {
    # Q-B7-24-5（2026-11-22 人类裁决「旧形态名不再用」）后仍留在 VK 的四条：都是**非同义**才
    # 留下的后端内部入口（逐对理由见 docs/design/契约_IEngineAPI_20261117.md §4.3 T1 表）。
    'compute_frame_view_proj': 'VK 渲染帧的位姿/VP 计算（LOD 选模 + V@P，返回 (vp, cam_pos)）；'
                              'GL 的 render 是**整帧**（绘制+上屏），非同义 → 后端内部',
    'build_scene_from_data': 'VK 从**已解析 dict** 装配场景（GL 对应物是 sceneio.scene_from_dict）；'
                            '用户 API 是 load_scene(path)（两端同一函数对象）',
    'feed_mouse_rel': '宿主喂光标增量（GL 由 GLFW 回调内部做）',
    'consume_mouse_input': '宿主帧首结算鼠标增量（GL 内部做）',
    'apply_editor_camera_mouse': '编辑器(轨道)相机**鼠标输入**（滚轮推拉/右键转视角）；'
                                'GL 对应物是 editor._update_camera，非 apply_orbit_camera（后者是位姿合成）',
    'current_camera_position': '无参取当前相机世界位置（轨道反推 / 脚本 camera）；'
                               'GL 对应物是 self.camera 属性，非 camera_world_position(cam)（吃相机实体）',
    'camera_target': 'VK 轨道相机目标点（GL 侧是属性而非方法）',
    'camera_distance': 'VK 轨道相机距离（同上）',
    'script_keys': 'GL 是普通实例属性、VK 是 property（同语义，形态不同；is_key 才是 API）',
}

gl_pub = {n for n in dir(E.GLEngine) if not n.startswith('_')}
vk_pub = {n for n in dir(SD.SceneDriver) if not n.startswith('_')}

print("=== 一. 用户 API 必须两端都有 ===")
missing_vk = sorted(n for n in USER_API_PENDING if n not in vk_pub)
missing_gl = sorted(n for n in USER_API_PENDING if n not in gl_pub)
check('待补用户 API 在 VK 上全部存在', not missing_vk, 'VK 缺: %s' % missing_vk)
check('待补用户 API 在 GL 上全部存在（参照端）', not missing_gl, 'GL 缺: %s' % missing_gl)

print()
print("=== 二. 用户 API 两端是**同一份实现**（不是各写一遍） ===")
not_same = []
for n in sorted(USER_API_PENDING):
    g = getattr(E.GLEngine, n, None)
    v = getattr(SD.SceneDriver, n, None)
    if g is None or v is None:
        continue
    if g is not v:
        not_same.append(n)
check('已补齐的用户 API 两端是同一个函数对象', not not_same, '不是同一份: %s' % not_same)

print()
print("=== 三. 剩余差异必须全部登记为后端/宿主内部 ===")
gl_only = sorted(gl_pub - vk_pub)
vk_only = sorted(vk_pub - gl_pub)
unregistered_gl = [n for n in gl_only if n not in BACKEND_ONLY_GL]
unregistered_vk = [n for n in vk_only if n not in BACKEND_ONLY_VK]
check('GL 独有的公开成员都已登记（或已清零）', not unregistered_gl,
      '未登记: %s' % unregistered_gl)
check('VK 独有的公开成员都已登记（或已清零）', not unregistered_vk,
      '未登记: %s' % unregistered_vk)

print()
print("=== 四. 白名单不许夹带用户 API（防「没做」写成「后端内部」） ===")
overlap = sorted((set(BACKEND_ONLY_GL) | set(BACKEND_ONLY_VK)) & USER_API_PENDING)
check('白名单与用户 API 名单无交集', not overlap, '交集: %s' % overlap)
stale_gl = sorted(set(BACKEND_ONLY_GL) - set(gl_only))
stale_vk = sorted(set(BACKEND_ONLY_VK) - set(vk_only))
check('GL 白名单没有过期条目（已两端都有就该删）', not stale_gl, '过期: %s' % stale_gl)
check('VK 白名单没有过期条目（已两端都有就该删）', not stale_vk, '过期: %s' % stale_vk)

print()
print("=== 现状 ===")
print('  两端共同公开成员: %d' % len(gl_pub & vk_pub))
print('  GL 独有 %d（全部为后端/宿主内部）: %s' % (len(gl_only), ', '.join(gl_only)))
print('  VK 独有 %d（全部为后端/宿主内部）: %s' % (len(vk_only), ', '.join(vk_only)))
print('  待补用户 API: %s' % (', '.join(sorted(USER_API_PENDING))))

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
