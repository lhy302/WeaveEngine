# -*- coding: utf-8 -*-
"""gamepack_probe.py — 游戏包发布链路单测 (2026-08-22)
覆盖: 打包/解包 round-trip; register_sources 注入脚本 (get_script 命中);
缺包启动报错 (game_pack.load -> None); 端到端: 跳台试炼场景 -> build_game.py
(模拟 runtime 目录) -> 游戏包 -> PlayerApp(源码) 8s 无崩溃.
运行: py -3.12 tests\_tmp\gamepack_probe.py"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LOOM_DIR)

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        FAILS.append(name)


import game_pack
import sceneio

TMP = tempfile.mkdtemp(prefix='gamepack_')

# ========== 1. 打包/解包 round-trip ==========
cfg = {'name': '测试游戏', 'company': '测试公司', 'version': '1.0',
       'title': '测试游戏窗口'}
scene_mock = {'version': 99, 'models': [{'name': 'A'}]}
scripts = [('reset_fall.py', "from scripts import Script, register\n@register"
            "\nclass X(Script):\n    script_id='x'\n    def update(self, dt): pass\n")]
p = game_pack.pack(TMP, cfg, scene_mock, scripts)
check("游戏包已生成", os.path.isfile(p), p)
with open(p, 'r', encoding='utf-8') as f:
    head = f.read(30)
check("游戏包内容为混淆 (LOOMSC1, 无明文)", head.startswith('LOOMSC1'), head)
with open(p, 'r', encoding='utf-8') as f:
    txt = f.read()
check("包内无明文脚本源码/场景 (防窥)", 'reset_fall' not in txt and '测试游戏' not in txt
      and '"models"' not in txt)

gm = game_pack.load(TMP)
check("解包 round-trip: fmt 校验", gm is not None and gm['fmt'] == 'loom-pack-1')
check("解包 round-trip: config 保真", gm['config'] == cfg, gm['config'])
check("解包 round-trip: scene 保真", gm['scene'] == scene_mock)
check("解包 round-trip: scripts 保真", gm['scripts'] ==
      [{'name': 'reset_fall.py', 'source': scripts[0][1]}])

# ========== 2. 缺包 = None (加载器报错语义) ==========
empty = os.path.join(TMP, '空的')
os.makedirs(empty, exist_ok=True)
check("缺包 load -> None", game_pack.load(empty) is None)

# ========== 3. register_sources 注入生效 ==========
from scripts import register_sources, get_script
n = register_sources(gm['scripts'])
check("register_sources 加载数 = 1", n == 1)
check("注入后 get_script('x') 命中", get_script('x') is not None)
check("注入脚本是 Script 子类 (params/on_start 可用)",
      getattr(get_script('x'), 'name', None) is not None)

# ========== 4. 端到端: build_game.py -> 发布夹 -> 源码玩家 8s ==========
demo_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(HERE))), '演示游戏')
scene_json = os.path.join(demo_dir, '跳台试炼场景.json')   # LOOMSC 加密的源场景? 明文? -> 生成脚本是 encrypt=True
# 构建器输入要求明文场景 (开发者文件) —— 生成一份明文副本 (encrypt=False)
plain = os.path.join(TMP, '跳台试炼_明文.json')
data = sceneio.load_scene_data(scene_json)
sceneio.save_scene_data(plain, data, encrypt=False)
print("  [diag] 明文场景存在=%s load=%s" % (
    os.path.isfile(plain),
    type(sceneio.load_scene_data(plain)).__name__))
# 玩家运行时: 模拟 dist 目录 (放一个真正的 "运行时" — 用源码目录模拟太慢;
# 构建器 --runtime 只要求目录; 端到端玩家用源码 game_player.py 直跑)
fake_runtime = os.path.join(TMP, 'runtime')
os.makedirs(fake_runtime, exist_ok=True)
out_dir = os.path.join(TMP, '发布夹')
r = subprocess.run([sys.executable, os.path.join(LOOM_DIR, 'build_game.py'),
                    '--name', '跳台试炼', '--company', 'DSH实验室',
                    '--scene', plain, '--game-scripts',
                    os.path.join(LOOM_DIR, 'scripts'),
                    '--output', out_dir, '--runtime', fake_runtime],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', cwd=LOOM_DIR, timeout=120)
log = r.stdout + r.stderr
print("  [info] build_game rc=%d" % r.returncode)
if r.returncode:
    print("  [info] build_game 输出: " + " | ".join(log.strip().splitlines()[-4:]))
ok = r.returncode == 0 and os.path.isfile(os.path.join(out_dir, '游戏包.lsc'))
check("build_game 构建成功 (含 游戏包.lsc)", ok)
if ok:
    gm2 = game_pack.load(out_dir)
    check("发布夹内游戏包解包成功", gm2 is not None)
    check("发布夹包内含 reset_fall 脚本 (game_scripts 收集)",
          any(s['name'] == 'reset_fall.py' for s in gm2['scripts']))
    with open(os.path.join(out_dir, '游戏包.lsc'), 'r', encoding='utf-8') as f:
        check("发布夹游戏包无明文 (reset_fall 源码未泄漏)",
              '跌出重置' not in f.read())

print("总结果:", "ALL PASS ✅" if not FAILS else "FAIL ❌ " + str(FAILS))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if FAILS else 0)
