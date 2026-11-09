# -*- coding: utf-8 -*-
"""test_backend_fallback_policy.py — 后端回退策略的白盒契约（2026-11-09 裁决 A + Q1/Q2）。

基准:
  · 默认后端仍是 vulkan（设置里的 render_api）；
  · **Vulkan 初始化失败**（无 loader / 无适配器 / apiVersion < 1.1 / 设备创建失败）：
    打印 [VK] 诊断（设备/驱动/apiVersion）+ 把用户层 游戏设置.json 的 render_api 写成
    opengl + **同进程立即改走 GL 4.3**（不退出、不闪退），且**只弹一次**窗；
  · **Q1 显式 --backend vulkan 失败**：**不改写用户配置**（尊重显式选择），本次仍走 GL；
  · **Q2 只写游戏设置.json（用户层 delta）**，引擎层 设置.json **一个字节都不动**；
  · GL 单独失败（含"上次回退成 opengl、但本机 GL < 4.3"的第二次启动）也必须可见：
    弹窗 + 原因 + SystemExit(1)；
  · GL 也不可用（双错）-> 一个「两条后端都不可用」弹窗 + 两条原因 + SystemExit(1)；
  · 渲染循环内失败 (VkRunError) 不回退、不改配置、不弹窗。

另含: VK 诊断字段兼容（wgpu 0.32 device/driver/device_type 与 0.33 description/
adapter_type/backend_type，缺失写 n/a）与初始化失败后**关闭残留 VK 空窗**。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')
os.environ['LOOM_NO_DIALOG'] = '1'      # 弹窗在测试里被 stub，这里再兜一层防阻塞

import run_player
import loom_backend_guard as G
from loom_gl_version import GLVersionError

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


class _FakeEngine:
    """GL 播放器替身：只记 run()，不建窗。"""
    models = []

    def __init__(self):
        self.ran = False

    def run(self):
        self.ran = True
        return None


class _Harness:
    """隔离配置目录 + 桩后端 + 弹窗记录（不真弹）。"""

    def __init__(self, tmpdir, api='vulkan'):
        self.tmp = tmpdir
        self.path = os.path.join(tmpdir, '设置.json')      # 引擎层（只读断言）
        self.write_engine(api)
        self.calls = []
        self.dialogs = []
        self._orig = (run_player._run_vulkan, run_player._open_opengl,
                      run_player._run_opengl, run_player._SETTINGS_BASE,
                      run_player.show_blocking_dialog)

    def write_engine(self, api):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'gui': 'LoomGUI', 'render_api': api}, f)

    def engine_bytes(self):
        with open(self.path, 'rb') as f:
            return f.read()

    def user_path(self):
        import game_settings
        return game_settings.user_path(base_dir=self.tmp)

    def user_api(self):
        p = self.user_path()
        if not os.path.isfile(p):
            return None
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        return (d.get('values') or {}).get('render_api')

    def install(self, vk=None, gl_raises=None):
        run_player._SETTINGS_BASE = self.tmp
        run_player._BOOTSTRAP_KEY[0] = None

        def _vk(scene=None, **kw):
            self.calls.append('vk')
            if vk is not None:
                raise vk
            return 'vk'

        def _open(scene=None, **kw):
            self.calls.append('gl')
            if gl_raises is not None:
                raise gl_raises
            return _FakeEngine()

        run_player._run_vulkan = _vk
        run_player._open_opengl = _open
        run_player._run_opengl = lambda scene=None, **kw: 'gl'

        def _dlg(title, text):
            self.dialogs.append((title, text))
            return True

        run_player.show_blocking_dialog = _dlg

    def restore(self):
        (run_player._run_vulkan, run_player._open_opengl,
         run_player._run_opengl, run_player._SETTINGS_BASE,
         run_player.show_blocking_dialog) = self._orig
        run_player._BOOTSTRAP_KEY[0] = None
        os.environ.pop('LOOM_GAME_DIR', None)


def _capture(fn):
    buf = io.StringIO()
    out, exc, ret = '', None, None
    with contextlib.redirect_stdout(buf):
        try:
            ret = fn()
        except BaseException as e:
            exc = e
    out = buf.getvalue()
    return out, exc, ret


def t_default_path_in_process_fallback(tmp):
    """非显式（配置/默认走到 vulkan）初始化失败 -> 诊断+落用户层+同进程 GL，只弹一次。"""
    print('=== A. 默认路径: VK 初始化失败 -> 同进程 GL ===')
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError(
        '[VK] Vulkan API: 1.0.0（地板: 1.1）\n[VK] 设备: 假设备'))
    before = h.engine_bytes()
    nxt = None
    try:
        out, exc, ret = _capture(lambda: run_player.run_backend('vulkan', 'x.json'))
        nxt = run_player.resolve_backend(None)
    finally:
        h.restore()
    check('A1 不退出（不再崩一次）', exc is None, type(exc).__name__)
    check('A1 调用序 vk -> gl', h.calls == ['vk', 'gl'], h.calls)
    check('A1 打印 [VK] 诊断', '[VK]' in out and '1.1' in out, out.strip()[:120])
    check('A1 只弹一次窗', len(h.dialogs) == 1, len(h.dialogs))
    check('A1 弹窗文案: 已自动切换 OpenGL',
          h.dialogs and '自动切换为 OpenGL' in h.dialogs[0][1],
          h.dialogs[0][1][:120] if h.dialogs else '')
    check('A1 用户层 游戏设置.json 写 opengl', h.user_api() == 'opengl', h.user_api())
    check('A1 引擎层 设置.json 一字节未变（Q2）',
          h.engine_bytes() == before, len(before))
    check('A1 下次启动解析为 opengl', nxt == 'opengl', nxt)


def t_explicit_vulkan_keeps_config(tmp):
    """Q1: 显式 --backend vulkan 失败 -> 不改写用户配置，本次仍走 GL。"""
    print('=== B. 显式 --backend vulkan -> 不改配置、本次降级 ===')
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError('adapter 为空 (无 Vulkan 设备)'))
    before = h.engine_bytes()
    try:
        out, exc, ret = _capture(lambda: run_player.run_backend('vulkan', 'x.json', explicit=True))
        user_before = h.user_api()
    finally:
        h.restore()
    check('B1 显式手选也当场降级（不退出）', exc is None and h.calls == ['vk', 'gl'],
          (type(exc).__name__, h.calls))
    check('B1 不改写用户配置（Q1）', user_before is None, user_before)
    check('B1 引擎层仍未被改（Q2）', h.engine_bytes() == before, len(before))
    check('B1 明确提示不改写配置', '不改写用户配置' in out, out.strip()[-120:])
    check('B1 只弹一次窗', len(h.dialogs) == 1, len(h.dialogs))


def t_auto_falls_back_and_persists(tmp):
    """auto: 回退 GL 并把用户层写成 opengl（下次启动不再空试 VK）。"""
    print('=== E. --backend auto -> GL + 落用户层 ===')
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError('adapter 为空'))
    try:
        out, exc, ret = _capture(lambda: run_player.run_backend('auto', 'x.json'))
        user_api = h.user_api()
    finally:
        h.restore()
    check('E1 auto: 回退到 GL', exc is None and h.calls == ['vk', 'gl'], (type(exc).__name__, h.calls))
    check('E1 auto: 用户层已写 opengl', user_api == 'opengl', user_api)


def t_double_fault_one_dialog(tmp):
    """双后端都不可用 -> 一个弹窗 + 两条原因 + SystemExit(1)，不重复前缀。"""
    print('=== C. 双后端都不可用 ===')
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError('[VK] 模拟: 无 Vulkan 设备'),
              gl_raises=GLVersionError('[GL] GLFW 窗口 需要 OpenGL 4.3 core 及以上'))
    try:
        out, exc, ret = _capture(lambda: run_player.run_backend('vulkan', 'x.json'))
    finally:
        h.restore()
    check('C1 双错 -> SystemExit(1)',
          isinstance(exc, SystemExit) and getattr(exc, 'code', None) == 1,
          (type(exc).__name__, getattr(exc, 'code', None)))
    check('C1 只弹一次窗（P3③）', len(h.dialogs) == 1, len(h.dialogs))
    text = h.dialogs[0][1] if h.dialogs else ''
    check('C1 弹窗含两条原因', '两条后端都不可用' in text and '[VK]' in text and '[GL]' in text,
          text[:160])
    check('C1 无重复前缀 [VK] [VK]', '[VK] [VK]' not in text and '[GL] [GL]' not in text, '')


def t_gl_only_visible_failure(tmp):
    """P1: 只走 GL 且 GL<4.3（上次回退后的第二次启动）-> 弹窗 + 非 0 退出。"""
    print('=== D. 仅 GL 路径失败必须可见 ===')
    h = _Harness(tmp)
    h.install(gl_raises=GLVersionError('[GL] GLFW 窗口 需要 OpenGL 4.3 core 及以上'))
    try:
        out, exc, ret = _capture(lambda: run_player.run_backend('opengl', 'x.json'))
    finally:
        h.restore()
    check('D1 仅 GL 失败 -> SystemExit(1)',
          isinstance(exc, SystemExit) and getattr(exc, 'code', None) == 1,
          (type(exc).__name__, getattr(exc, 'code', None)))
    check('D1 弹窗可见且说明原因',
          len(h.dialogs) == 1 and 'OpenGL 不可用' in h.dialogs[0][0],
          h.dialogs[0][0] if h.dialogs else '')
    check('D1 弹窗正文含 GL 诊断且不重复前缀',
          h.dialogs and 'OpenGL 4.3' in h.dialogs[0][1]
          and '[GL] [GL]' not in h.dialogs[0][1], '')

def t_loop_failure_not_swallowed(tmp):
    """渲染循环内失败 (VkRunError): 不回退、不改配置、不弹窗。"""
    print('=== F. 运行期失败 ===')
    for tag, api, kw in (('auto', 'auto', {}),
                         ('显式 vulkan', 'vulkan', {'explicit': True}),
                         ('设置 vulkan', 'vulkan', {})):
        h = _Harness(tmp)
        h.install(vk=run_player.VkRunError('渲染循环内 device lost'))
        try:
            out, exc, ret = _capture(lambda: run_player.run_backend(api, 'x.json', **kw))
        finally:
            h.restore()
        check('%s: VkRunError 原样上传（不回退/不弹窗）' % tag,
              isinstance(exc, run_player.VkRunError) and h.calls == ['vk']
              and not h.dialogs,
              (type(exc).__name__, h.calls, len(h.dialogs)))


def t_game_player_safe_layer(tmp):
    """发布链: VK 初始化失败 -> 同进程 GL 并回报实际后端; 意外异常仍兜底。"""
    print('=== G. 发布链 _run_backend_safe ===')
    import game_player
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError('adapter 为空'))
    try:
        out, exc, ret = _capture(lambda: game_player._run_backend_safe('vulkan', 'x.json'))
    finally:
        h.restore()
    check('G1 VK 失败 -> 同进程 GL 且回报 opengl',
          exc is None and ret == 'opengl' and h.calls == ['vk', 'gl'],
          (type(exc).__name__, ret, h.calls))
    h = _Harness(tmp)
    h.install(vk=run_player.VkRunError('loop 内异常'))
    try:
        out, exc, ret = _capture(lambda: game_player._run_backend_safe('vulkan', 'x.json'))
    finally:
        h.restore()
    check('G2 VkRunError -> 上传（不回退）',
          isinstance(exc, run_player.VkRunError) and h.calls == ['vk'],
          (type(exc).__name__, h.calls))
    h = _Harness(tmp)
    h.install(vk=RuntimeError('别的意外失败'))
    try:
        out, exc, ret = _capture(lambda: game_player._run_backend_safe('vulkan', 'x.json'))
    finally:
        h.restore()
    check('G3 其它意外异常 -> 仍兜底 GL（最后一道网）',
          exc is None and ret == 'opengl' and h.calls == ['vk', 'gl'],
          (type(exc).__name__, ret, h.calls))


def t_diag_fields():
    """P2-1: wgpu 0.32 / 0.33 两套字段名都要能读出；缺失写 n/a 不写「未知」。"""
    print('=== H. VK 诊断字段（wgpu 0.32/0.33）===')
    old = {'device': 'D1', 'driver': 'DR', 'driver_info': '1.2',
           'backend': 'vulkan', 'device_type': 'discrete'}
    t1 = G.vk_diag_text(old)
    check('H1 0.32 字段全读出', 'D1' in t1 and 'DR' in t1 and 'discrete' in t1, '')
    new = {'description': 'D2', 'backend_type': 'vulkan', 'adapter_type': 'integrated'}
    t2 = G.vk_diag_text(new)
    check('H2 0.33 字段全读出', 'D2' in t2 and 'integrated' in t2, '')
    check('H2 缺失字段写 n/a（不是「未知」）',
          'n/a' in t2 and '未知' not in t2, t2.replace(chr(10), ' | ')[:120])
    check('H3 0.32 文本也不含「未知」', '未知' not in t1, '')

    class _InfoObj:
        description = 'D3'
        backend_type = 'vulkan'
        adapter_type = 'cpu'

    class _Adapter:
        info = _InfoObj()

    d = G.adapter_info_dict(_Adapter())
    check('H4 对象式 AdapterInfo 也能归一', d.get('description') == 'D3', d)


def t_vk_canvas_closed(tmp):
    """P2-2: 建窗后初始化失败（设备创建失败 / 无适配器）必须关闭窗口。"""
    print('=== I. VK 初始化失败关闭残留空窗 ===')
    import vk_player

    sentinel = {}

    class _FakeCanvas:
        def __init__(self, **kw):
            self.closed = False
            sentinel["canvas"] = self

        def set_update_mode(self, mode):
            self.mode = mode

        def get_wgpu_context(self):
            return None

        def close(self):
            self.closed = True

    class _FakeAdapter:
        info = {'device': 'fakeGPU'}

        def request_device_sync(self):
            raise RuntimeError('device 创建失败')

    class _GpuFail:
        def request_adapter_sync(self, **kw):
            return _FakeAdapter()

    class _GpuNone:
        def request_adapter_sync(self, **kw):
            return None

    class _FakeWgpuFail:
        gpu = _GpuFail()

    class _FakeWgpuNone:
        gpu = _GpuNone()

    scene = os.path.join(tmp, 'mini.json')
    with open(scene, 'w', encoding='utf-8') as f:
        json.dump({'version': 10, 'objects': [], 'lights': [],
                   'materials': [], 'cameras': [], 'active_camera': None}, f)

    for tag, fake_wgpu in (('设备创建失败', _FakeWgpuFail),
                           ('无可用适配器', _FakeWgpuNone)):
        sentinel.clear()
        saved = (vk_player.GlfwRenderCanvas, vk_player.wgpu)
        vk_player.GlfwRenderCanvas = _FakeCanvas
        vk_player.wgpu = fake_wgpu
        err = None
        try:
            vk_player.run_vk(scene, frames_n=1)
        except BaseException as e:
            err = e
        finally:
            vk_player.GlfwRenderCanvas, vk_player.wgpu = saved
        cv = sentinel.get('canvas')
        check('I-%s: 抛 VkInitError' % tag,
              isinstance(err, run_player.VkInitError), type(err).__name__)
        check('I-%s: 已建的 VK 窗口被关闭（不留可见空窗）' % tag,
              cv is not None and getattr(cv, 'closed', False),
              None if cv is None else cv.closed)


def t_engine_settings_untouched(tmp):
    """Q2: 回退只写游戏设置.json（用户层），引擎层 设置.json 字节不变。"""
    print('=== J. 只写用户层 ===')
    h = _Harness(tmp)
    with open(h.path, 'w', encoding='utf-8') as f:
        json.dump({'render_api': 'vulkan', 'backend': 'vulkan'}, f)
    before = h.engine_bytes()
    h.install(vk=run_player.VkInitError('adapter 为空'))
    try:
        out, exc, ret = _capture(lambda: run_player.run_backend('vulkan', 'x.json'))
        user = h.user_api()
    finally:
        h.restore()
    check('J1 用户层写成 opengl', user == 'opengl', user)
    check('J2 引擎层字节完全不变', h.engine_bytes() == before, len(before))
    check('J3 引擎层 render_api 仍为 vulkan',
          json.loads(h.engine_bytes().decode('utf-8')).get('render_api') == 'vulkan', '')


def main():
    cases = (t_default_path_in_process_fallback,
             t_explicit_vulkan_keeps_config,
             t_auto_falls_back_and_persists,
             t_double_fault_one_dialog,
             t_gl_only_visible_failure,
             t_loop_failure_not_swallowed,
             t_game_player_safe_layer,
             t_engine_settings_untouched)
    for fn in cases:
        with tempfile.TemporaryDirectory() as tmp:
            fn(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_diag_fields()
        t_vk_canvas_closed(tmp)
    print('=' * 60)
    if _fails:
        print('失败:', _fails)
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())

