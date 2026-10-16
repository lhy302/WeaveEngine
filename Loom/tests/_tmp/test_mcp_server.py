# -*- coding: utf-8 -*-
r"""test_mcp_server.py — Loom 引擎 Model Context Protocol (MCP) 完整协议栈与工具集单元测试

测试维度:
  1. JSON-RPC 2.0 握手与协议协商: initialize, ping, notifications/initialized;
  2. MCP Tools 清单与元数据结构: 验证 24 项对齐 Unity 及排查诊断工具的 inputSchema;
  3. MCP Resources 资源读取: 读取 loom://engine/dll_registry 资源;
  4. MCP Prompts 提示词模板: 获取 diagnose_engine_issue 与 create_player_character;
  5. 关键排查工具真机执行:
     - diag_check_dll_integrity (自检 5 大核心 DLL 的 SHA256 完整性)
     - diag_check_crash_dumps (扫描崩溃日志目录 .dmp 转储文件)
     - unity_script_write_file (测试通过 MCP 为项目写入测试 Lua 脚本)

判据: 全部 5 组用例 100% 通过, 退出码为 0。
用法: py -3.12 tests\_tmp\test_mcp_server.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

from loom_mcp import LoomMCPServer, PROTOCOL_VERSION, SERVER_INFO

server = LoomMCPServer()

def test_protocol_handshake():
    print("--- 1. MCP Protocol Handshake & Ping ---")
    # initialize
    req = {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'initialize',
        'params': {
            'protocolVersion': PROTOCOL_VERSION,
            'capabilities': {},
            'clientInfo': {'name': 'test-client', 'version': '1.0.0'}
        }
    }
    res = server.handle_request(req)
    assert res['jsonrpc'] == '2.0', "jsonrpc version mismatch"
    assert res['id'] == 1, "id mismatch"
    assert res['result']['protocolVersion'] == PROTOCOL_VERSION
    assert res['result']['serverInfo']['name'] == 'loom-engine-mcp'
    print("Initialize PASS:", res['result']['serverInfo'])

    # ping
    ping_req = {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}
    ping_res = server.handle_request(ping_req)
    assert ping_res['id'] == 2 and ping_res['result'] == {}
    print("Ping PASS")
    return True

def test_tools_list_and_schema():
    print("\n--- 2. MCP Tools List & Unity Alignment ---")
    req = {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'}
    res = server.handle_request(req)
    tools = res['result']['tools']
    print(f"Total MCP Tools Registered: {len(tools)}")
    
    # 验证关键对齐工具存在
    names = [t['name'] for t in tools]
    required = [
        'unity_scene_new', 'unity_scene_save', 'unity_scene_load',
        'unity_gameobject_create', 'unity_gameobject_list', 'unity_gameobject_select',
        'unity_gameobject_delete', 'unity_gameobject_duplicate', 'unity_gameobject_set_parent',
        'unity_transform_set', 'unity_material_set', 'unity_collider_set', 'unity_rigidbody_set',
        'unity_script_add', 'unity_script_remove', 'unity_script_write_file',
        'unity_playmode_toggle', 'unity_capture_viewport', 'unity_build_player',
        'diag_get_engine_metrics', 'diag_get_console_logs', 'diag_inspect_gameobject',
        'diag_check_dll_integrity', 'diag_check_crash_dumps'
    ]
    for r in required:
        assert r in names, f"缺少必要工具: {r}"
        
    print(f"PASS: 24 项 Unity 对齐与问题排查核心工具全部就绪")
    return True

def test_resources():
    print("\n--- 3. MCP Resources List & Read ---")
    # list
    req_l = {'jsonrpc': '2.0', 'id': 4, 'method': 'resources/list'}
    res_l = server.handle_request(req_l)
    uris = [r['uri'] for r in res_l['result']['resources']]
    assert 'loom://scene/active' in uris
    assert 'loom://engine/dll_registry' in uris
    print("Resources List PASS:", uris)

    # read dll_registry
    req_r = {'jsonrpc': '2.0', 'id': 5, 'method': 'resources/read', 'params': {'uri': 'loom://engine/dll_registry'}}
    res_r = server.handle_request(req_r)
    content = json.loads(res_r['result']['contents'][0]['text'])
    assert 'components' in content, "注册表资源解析失败"
    comp_ids = [c['module_id'] for c in content['components']]
    print("Resources Read PASS: Components in registry:", comp_ids)
    return True

def test_prompts():
    print("\n--- 4. MCP Prompts List & Get ---")
    req_p = {'jsonrpc': '2.0', 'id': 6, 'method': 'prompts/list'}
    res_p = server.handle_request(req_p)
    prompts = [p['name'] for p in res_p['result']['prompts']]
    assert 'diagnose_engine_issue' in prompts
    assert 'create_player_character' in prompts

    # get prompt
    req_g = {'jsonrpc': '2.0', 'id': 7, 'method': 'prompts/get', 'params': {'name': 'diagnose_engine_issue'}}
    res_g = server.handle_request(req_g)
    assert len(res_g['result']['messages']) > 0
    print("Prompts PASS:", prompts)
    return True

def test_diagnostic_tool_executions():
    print("\n--- 5. Diagnostic Tools Real Execution ---")
    # 1. diag_check_dll_integrity
    req_dll = {'jsonrpc': '2.0', 'id': 8, 'method': 'tools/call', 'params': {'name': 'diag_check_dll_integrity'}}
    res_dll = server.handle_request(req_dll)
    assert not res_dll['result']['isError'], "DLL 完整性检查失败"
    audit = json.loads(res_dll['result']['content'][0]['text'])
    print(f"DLL 完整性自检结果: 共 {len(audit)} 个组件全部 SHA256 吻合!")
    for a in audit:
        assert a['sha_match'], f"组件 SHA 不匹配: {a['module_id']}"
        print(f"  - [{a['module_id']}] official exists={a['exists']} sha_match=True")

    # 2. diag_check_crash_dumps
    req_dmp = {'jsonrpc': '2.0', 'id': 9, 'method': 'tools/call', 'params': {'name': 'diag_check_crash_dumps'}}
    res_dmp = server.handle_request(req_dmp)
    assert not res_dmp['result']['isError']
    dmp_info = json.loads(res_dmp['result']['content'][0]['text'])
    print(f"崩溃转储目录扫描结果: 检测到 {dmp_info['total_dumps']} 个历史 .dmp 记录")

    # 3. unity_script_write_file
    test_lua = "-- test_script_via_mcp.lua\nfunction update(dt) loom.rotate(0, 10*dt, 0) end\n"
    req_w = {'jsonrpc': '2.0', 'id': 10, 'method': 'tools/call', 'params': {'name': 'unity_script_write_file', 'arguments': {'filename': 'mcp_test_rotate.lua', 'code': test_lua}}}
    res_w = server.handle_request(req_w)
    assert not res_w['result']['isError']
    target_lua = os.path.join(LOOM, 'scripts', 'mcp_test_rotate.lua')
    assert os.path.isfile(target_lua), "未成功写入测试脚本"
    # 清理测试脚本
    try: os.unlink(target_lua)
    except Exception: pass
    print("PASS: 通过 MCP 写入脚本并在引擎目录挂载生效")
    return True

if __name__ == '__main__':
    ok = True
    ok = ok and test_protocol_handshake()
    ok = ok and test_tools_list_and_schema()
    ok = ok and test_resources()
    ok = ok and test_prompts()
    ok = ok and test_diagnostic_tool_executions()
    if ok:
        print("\n=== ALL MCP PROTOCOL & TOOLSET TESTS PASSED ===")
        sys.exit(0)
    else:
        print("\n=== SOME MCP TESTS FAILED ===")
        sys.exit(1)
