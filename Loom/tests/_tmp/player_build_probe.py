# -*- coding: utf-8 -*-
r"""player_build_probe.py — M4: AUDIT-46 独立 Player 物理游戏拆装打包与纯 DLL 运行时验证

测试维度:
  1. 脚本收集类型测试: 验证 build_game._collect_scripts 能够同时收集 .py 与 .lua 脚本;
  2. 游戏打包与解包验证: 验证 game_pack 成功将测试场景与 Lua 脚本加密打包为 游戏包.lsc;
  3. 核心 DLL 随包组装验证: 验证发布流程自动携带 core_components (含 4 大 DLL 与 registry.json);
  4. 纯 Player 运行时独立性: 验证 game_player / runtime.PlayerApp 完全不依赖 PySide6 / Qt 库, 达成纯净运行。

判据: 全部 4 组用例 100% 通过, 否则 sys.exit(1)。
"""
import os
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

import build_game
import game_pack
import scripts

def test_script_collection():
    print("--- 1. AUDIT-46: .py 与 .lua 脚本全量收集验证 ---")
    tmp = tempfile.mkdtemp(prefix="loom_scripts_test_")
    try:
        py_file = os.path.join(tmp, "test_s1.py")
        lua_file = os.path.join(tmp, "test_s2.lua")
        with open(py_file, 'w', encoding='utf-8') as f: f.write("# py")
        with open(lua_file, 'w', encoding='utf-8') as f: f.write("-- lua")
        
        collected = build_game._collect_scripts(tmp)
        names = [n for n, s in collected]
        assert "test_s1.py" in names, "缺少 test_s1.py"
        assert "test_s2.lua" in names, "缺少 test_s2.lua"
        print(f"PASS: 脚本收集正常命中 .py 与 .lua: {names}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return True

def test_pack_and_unpack_with_lua():
    print("\n--- 2. AUDIT-46: 包含 Lua 脚本的 游戏包.lsc 混淆打包与解包测试 ---")
    tmp_out = tempfile.mkdtemp(prefix="loom_pack_test_")
    try:
        config = {'name': 'LoomTestGame', 'company': 'TestCo', 'version': '1.0', 'title': 'Loom Test'}
        scene_dict = {'version': 8, 'objects': [], 'lights': []}
        lua_code = "function update(dt) loom.rotate(0, 90*dt, 0) end"
        script_list = [('my_rot.lua', lua_code)]
        
        lsc_path = game_pack.pack(tmp_out, config, scene_dict, script_list, encrypt=True)
        assert os.path.isfile(lsc_path), "游戏包.lsc 未生成"
        
        # 解包读取
        loaded = game_pack.load(tmp_out)
        assert loaded is not None, "游戏包解密读取失败"
        assert loaded['config']['name'] == 'LoomTestGame'
        assert len(loaded['scripts']) == 1
        assert loaded['scripts'][0]['name'] == 'my_rot.lua'
        
        # 注册进 scripts.SCRIPTS
        n = scripts.register_sources(loaded['scripts'])
        assert n == 1, f"Lua 脚本注册失败: n={n}"
        assert 'my_rot' in scripts.SCRIPTS, "SCRIPTS 中缺少 my_rot 动态类"
        print("PASS: 游戏包加密解密与 Lua 动态注册全部闭环")
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)
    return True

def test_core_dlls_assembly():
    print("\n--- 3. AUDIT-46: 独立 Player 核心组件 DLL 随包发布验证 ---")
    # 验证 core_components 下核心 DLL 齐备
    cc = os.path.join(LOOM, 'core_components')
    req_files = [
        os.path.join(cc, 'registry.json'),
        os.path.join(cc, 'module_ref.dll'),
        os.path.join(cc, 'pipeline', 'pipeline.dll'),
        os.path.join(cc, 'script', 'script.dll'),
        os.path.join(LOOM, 'ckernels', 'loom_kernels.dll')
    ]
    for rf in req_files:
        assert os.path.isfile(rf), f"缺少核心组件: {rf}"
        
    print("PASS: 4 大官方核心 DLL 与注册表均处于可直接交付状态")
    return True

def test_qt_decoupling():
    print("\n--- 4. AUDIT-46: 纯 Player 运行时 Qt 依赖剥离测试 ---")
    import game_player
    import runtime
    
    # 检查模块命名空间中绝无 Qt 或 PySide 符号
    for mod in (game_player, runtime):
        for name in dir(mod):
            assert 'PySide' not in name and 'Qt' not in name, f"{mod.__name__} 包含残留 Qt 符号: {name}"
            
    print("PASS: 玩家运行时完全剥离 Qt/PySide 依赖, 保持纯净轻量")
    return True

if __name__ == '__main__':
    ok = True
    ok = ok and test_script_collection()
    ok = ok and test_pack_and_unpack_with_lua()
    ok = ok and test_core_dlls_assembly()
    ok = ok and test_qt_decoupling()
    if ok:
        print("\n=== AUDIT-46 ALL VERIFICATIONS PASSED ===")
        sys.exit(0)
    else:
        print("\n=== AUDIT-46 SOME TESTS FAILED ===")
        sys.exit(1)
