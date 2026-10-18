# -*- coding: utf-8 -*-
# loom_mcp.py — Loom 引擎 Model Context Protocol (MCP) 标准协议服务 (2026-10-02)
#
# 协议标准: Anthropic Model Context Protocol (MCP) JSON-RPC 2.0 (stdio)
# 作用:
#   1. 提供大模型全自动控制 Loom 3D 游戏引擎的标准化协议通道 (Claude Desktop / Cursor / DSH)
#   2. 对齐 Unity 工作流 (SceneManager, GameObject, Component, Material, Scripting, BuildPipeline)
#   3. 提供全维度问题排查与诊断能力 (FPS/TPS metrics, console logs, DLL 校验, 崩溃 dump 探测, 视口截图)

import base64
import glob
import json
import os
import sys
import threading
import time
import urllib.request
PROTOCOL_VERSION = '2024-11-05'
SERVER_INFO = {'name': 'loom-engine-mcp', 'version': '1.0.0'}
class LoomEngineClient:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self._cached_info = None
    def get_info(self):
        p = os.path.join(self.base_dir, '.agent_port.json')
        if not os.path.exists(p):
            parent = os.path.dirname(self.base_dir)
            cand = os.path.join(parent, 'Loom(编译版)', 'Loom', '.agent_port.json')
            if os.path.exists(cand): p = cand
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f: return json.load(f)
            except Exception: pass
        return None
    def is_alive(self):
        info = self.get_info()
        if not info: return False
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{info["port"]}/status', headers={'X-Agent-Token': info['token']})
            with urllib.request.urlopen(req, timeout=1.5) as r:
                return r.status == 200
        except Exception: return False
    def call(self, cmd, args=None, timeout=30.0):
        info = self.get_info()
        if not info:
            return {'ok': False, 'error': 'Loom 引擎未启动 (未找到 .agent_port.json)。请先启动 Loom.py --agent 或打开编辑器。'}
        body = json.dumps({'cmd': cmd, 'args': args or {}}).encode('utf-8')
        req = urllib.request.Request(f'http://127.0.0.1:{info["port"]}/cmd', data=body, method='POST', headers={'X-Agent-Token': info['token'], 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e: return {'ok': False, 'error': f'连接引擎失败: {e}'}
    def get_logs(self, after=0):
        info = self.get_info()
        if not info: return {'ok': False, 'error': '引擎未运行'}
        req = urllib.request.Request(f'http://127.0.0.1:{info["port"]}/logs?after={after}', headers={'X-Agent-Token': info['token']})
        try:
            with urllib.request.urlopen(req, timeout=5.0) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e: return {'ok': False, 'error': str(e)}
TOOLS_DEF = [
    {'name': 'unity_scene_new', 'description': '创建一个全新的空白场景 (对齐 Unity SceneManager.CreateScene)', 'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'unity_scene_save', 'description': '保存当前场景到指定 json 文件 (对齐 Unity EditorSceneManager.SaveScene)', 'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string', 'description': '场景相对或绝对文件路径'}}, 'required': ['path']}},
    {'name': 'unity_scene_load', 'description': '加载并打开指定 json 场景文件 (对齐 Unity EditorSceneManager.OpenScene)', 'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string', 'description': '场景相对或绝对文件路径'}}, 'required': ['path']}},
    {'name': 'unity_gameobject_create', 'description': '在场景中实例化一个新游戏对象 (对齐 Unity GameObject.CreatePrimitive / Instantiate)', 'inputSchema': {'type': 'object', 'properties': {'primitive': {'type': 'string', 'enum': ['cube', 'sphere', 'plane', 'none'], 'description': '几何基元类型'}, 'name': {'type': 'string', 'description': '物体名称'}, 'position': {'type': 'array', 'items': {'type': 'number'}, 'description': '三维坐标 [x, y, z]'}, 'rotation': {'type': 'array', 'items': {'type': 'number'}, 'description': '欧拉角 [rx, ry, rz]'}, 'scale': {'type': 'array', 'items': {'type': 'number'}, 'description': '缩放 [sx, sy, sz]'}}}},
    {'name': 'unity_gameobject_list', 'description': '获取场景内所有 GameObject 层次结构清单 (对齐 Unity Hierarchy 树)', 'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'unity_gameobject_select', 'description': '在编辑器中选中指定 GameObject (对齐 Unity Selection.activeGameObject)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称或 GUID'}}, 'required': ['name_or_id']}},
    {'name': 'unity_gameobject_delete', 'description': '删除销毁指定 GameObject (对齐 Unity Object.Destroy)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称或 GUID'}}, 'required': ['name_or_id']}},
    {'name': 'unity_gameobject_duplicate', 'description': '克隆复制当前选中或指定的 GameObject (对齐 Unity Instantiate 副本)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称或 GUID'}}}},
    {'name': 'unity_gameobject_set_parent', 'description': '设置父子层级挂载关系 (对齐 Unity Transform.SetParent)', 'inputSchema': {'type': 'object', 'properties': {'child': {'type': 'string', 'description': '子物体名称'}, 'parent': {'type': 'string', 'description': '父物体名称 (为空表示解除父子关系)'}, 'keep_world': {'type': 'boolean', 'description': '是否保持世界坐标不变'}}, 'required': ['child']}},
    {'name': 'unity_transform_set', 'description': '修改 GameObject 的空间变换属性 (对齐 Unity Transform 组件)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'position': {'type': 'array', 'items': {'type': 'number'}, 'description': '世界位置 [x, y, z]'}, 'rotation': {'type': 'array', 'items': {'type': 'number'}, 'description': '欧拉角弧度 [rx, ry, rz]'}, 'scale': {'type': 'array', 'items': {'type': 'number'}, 'description': '缩放 [sx, sy, sz]'}}, 'required': ['name_or_id']}},
    {'name': 'unity_material_set', 'description': '创建或绑定材质颜色与饱和度 (对齐 Unity Material / MeshRenderer)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'color': {'type': 'string', 'description': '十六进制颜色码如 #FF5555'}, 'saturation': {'type': 'number', 'description': '饱和度 (0=灰度, 1=原始, >1=增艳)'}, 'normal_mode': {'type': 'string', 'enum': ['flat', 'vertex'], 'description': '法线模式'}}, 'required': ['name_or_id']}},
    {'name': 'unity_lod_set', 'description': '设置 LOD (对齐 Unity LODGroup): 按屏幕占比切换网格精度', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'screen': {'type': 'number', 'description': '屏幕占比阈值 0-1 (低于则降级; 默认 0.1)'}, 'bias': {'type': 'number', 'description': 'LOD 偏移 (大=更高质量; 对齐 Unity lodBias)'}, 'on': {'type': 'boolean', 'description': '是否启用 LOD (false=关闭)'}}, 'required': ['name_or_id']}},
    {'name': 'unity_env_set', 'description': '设置材质环境反射贴图 (对齐 Unity Reflection Probe / Cubemap)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'paths': {'type': 'array', 'items': {'type': 'string'}, 'description': '6 面图片路径 [+X,-X,+Y,-Y,+Z,-Z] (相对引擎目录或绝对)'}, 'color': {'type': 'string', 'description': '纯色环境 (hex 如 #8080FF; 与 paths 二选一)'}}, 'required': ['name_or_id']}},
    {'name': 'unity_pbr_set', 'description': '设置材质 PBR 参数 (对齐 Unity Standard Shader: Metallic/Smoothness)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'metallic': {'type': 'number', 'description': '金属度 0-1 (对齐 Unity Metallic)'}, 'roughness': {'type': 'number', 'description': '粗糙度 0-1'}, 'smoothness': {'type': 'number', 'description': '光滑度 0-1 (Unity 风格, =1-roughness)'}, 'on': {'type': 'boolean', 'description': '是否启用 PBR 渲染 (给参数则自动启用)'}}, 'required': ['name_or_id']}},
    {'name': 'unity_texture_set', 'description': '设置物体材质的颜色贴图 (albedo; 对齐 Unity Material.mainTexture + Texture Import Settings)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'path': {'type': 'string', 'description': '图片文件路径 (相对引擎目录或绝对; 空字符串=清除贴图)'}, 'wrap': {'type': 'string', 'enum': ['repeat', 'clamp'], 'description': '寻址模式 (对齐 Unity Wrap Mode)'}, 'filter_mode': {'type': 'string', 'enum': ['point', 'bilinear', 'trilinear'], 'description': '过滤模式 (对齐 Unity Filter Mode)'}, 'aniso': {'type': 'number', 'description': '各向异性过滤级别 (1-16, 对齐 Unity Aniso Level)'}, 'max_size': {'type': 'integer', 'description': '最大尺寸上限 (等比缩放, 0=不限; 对齐 Unity Max Size)'}, 'compression': {'type': 'string', 'enum': ['none', 'rgb24', 'rgb565', 'rgba4444', 'rgb5a1'], 'description': '显存格式 (对齐 Unity Compression): none=RGBA8, rgb565/rgba4444/rgb5a1=16bpp省50%'}}, 'required': ['name_or_id']}},
    {'name': 'unity_collider_set', 'description': '配置碰撞体组件 (对齐 Unity BoxCollider / SphereCollider)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'shape': {'type': 'string', 'enum': ['box', 'sphere', 'none'], 'description': '碰撞体形状'}, 'enabled': {'type': 'boolean', 'description': '是否启用碰撞体'}}, 'required': ['name_or_id']}},
    {'name': 'unity_rigidbody_set', 'description': '配置刚体物理动力学参数 (对齐 Unity Rigidbody); 有任一精细参数则 action=set 应用', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'action': {'type': 'string', 'enum': ['add', 'remove', 'gravity', 'set'], 'description': 'add/remove/gravity/set (缺省: 有精细参数=set, 否则 add)'}, 'mass': {'type': 'number', 'description': '质量 (kg)'}, 'use_gravity': {'type': 'boolean', 'description': '是否受重力'}, 'is_kinematic': {'type': 'boolean', 'description': '是否为运动学物体'}, 'friction': {'type': 'number', 'description': '摩擦系数'}, 'restitution': {'type': 'number', 'description': '弹性恢复系数'}, 'velocity': {'type': 'array', 'items': {'type': 'number'}, 'description': '初速度 [vx, vy, vz] (m/s)'}}, 'required': ['name_or_id']}},
    {'name': 'unity_physics_simulate', 'description': '确定性推进 N 个逻辑帧并返回步长参数 (物理对拍; 需已 play, 建议 paused=true)', 'inputSchema': {'type': 'object', 'properties': {'frames': {'type': 'integer', 'description': '推进的逻辑帧数'}}, 'required': ['frames']}},
    {'name': 'unity_script_add', 'description': '为物体添加逻辑脚本组件 (对齐 Unity GameObject.AddComponent<Script>)', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'script_id': {'type': 'string', 'description': '脚本标识符 (如 rotate, wasd_move 或自定义 lua 脚本)'}, 'script_vars': {'type': 'object', 'description': '脚本自定义参数字典'}}, 'required': ['name_or_id', 'script_id']}},
    {'name': 'unity_script_remove', 'description': '移除物体上的脚本组件', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称'}, 'index': {'type': 'integer', 'description': '脚本序号'}}, 'required': ['name_or_id']}},
    {'name': 'unity_script_write_file', 'description': '在项目 scripts/ 目录下编写或更新纯 Lua 5.4 / Python 玩法脚本', 'inputSchema': {'type': 'object', 'properties': {'filename': {'type': 'string', 'description': '文件名 (如 player.lua 或 enemy.lua)'}, 'code': {'type': 'string', 'description': '完整的脚本代码'}}, 'required': ['filename', 'code']}},
    {'name': 'unity_playmode_toggle', 'description': '切换编辑器播放模式与编辑模式 (对齐 Unity EditorApplication.isPlaying = true/false)', 'inputSchema': {'type': 'object', 'properties': {'on': {'type': 'boolean', 'description': 'true 为开始播放, false 为停止播放'}, 'paused': {'type': 'boolean', 'description': '进入播放即冻结逻辑帧 (物理对拍用)'}}}},
    {'name': 'unity_capture_viewport', 'description': '截取当前编辑器视口渲染画面 (供多模态模型视觉检查画面对齐/缺陷排查)', 'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string', 'description': '可选保存图片文件路径'}}}},
    {'name': 'unity_build_player', 'description': '一键将游戏项目构建打包为独立的纯 Player 免安装发布夹 (对齐 Unity BuildPipeline.BuildPlayer)', 'inputSchema': {'type': 'object', 'properties': {'game_name': {'type': 'string', 'description': '发布游戏名称'}, 'scene_path': {'type': 'string', 'description': '启动场景文件路径'}, 'output_dir': {'type': 'string', 'description': '发布目标目录'}}}},
    {'name': 'diag_get_engine_metrics', 'description': '【问题排查】获取引擎实时帧率、逻辑时钟TPS、各阶段耗时毫秒、DrawCall批次与活动物理刚体数', 'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'diag_get_console_logs', 'description': '【问题排查】拉取引擎内部环形控制台日志流与错误排查记录', 'inputSchema': {'type': 'object', 'properties': {'after_seq': {'type': 'integer', 'description': '从该日志序号之后拉取增量 (0 为拉取最新)'}}}},
    {'name': 'diag_inspect_gameobject', 'description': '【问题排查】深度透视检查指定 GameObject 的所有组件、世界矩阵、碰撞盒与运行态变量', 'inputSchema': {'type': 'object', 'properties': {'name_or_id': {'type': 'string', 'description': '物体名称或 ID'}}, 'required': ['name_or_id']}},
    {'name': 'diag_check_dll_integrity', 'description': '【问题排查】全量自检 5 大官方 C ABI 动态库 (ckernels, pipeline, script, physics, module_ref) 的 SHA256 钉扎完整性与导出接口', 'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'diag_check_crash_dumps', 'description': '【问题排查】扫描崩溃日志目录下的 Windows MiniDump (.dmp) 崩溃转储文件与异常堆栈', 'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'loom_set_layer', 'description': '设置 GameObject 的 Layer (0~31; 对齐 Unity GameObject.layer)', 'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string', 'description': '物体名称 (缺省=当前选中)'}, 'layer': {'type': 'integer', 'description': '层编号 0~31'}}, 'required': ['layer']}},
    {'name': 'loom_set_tag', 'description': '设置 GameObject 的 Tag (对齐 Unity GameObject.tag; 未注册自动注册)', 'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string', 'description': '物体名称 (缺省=当前选中)'}, 'tag': {'type': 'string', 'description': '标签名 (字母/数字/下划线/中文)'}}, 'required': ['tag']}},
    {'name': 'loom_get_layer_tag', 'description': '查询 GameObject 的 Layer/Tag (对齐 Unity layer + tag)', 'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string', 'description': '物体名称 (缺省=当前选中)'}}}},
    {'name': 'loom_audio_3d_set', 'description': '设置音频 3D 参数 (对齐 Unity AudioSource 的 spatialBlend/minDistance/maxDistance/rolloffMode)', 'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string', 'description': '物体名称 (缺省=当前选中)'}, 'category': {'type': 'string', 'enum': ['music', 'sfx', 'voice'], 'description': '音频类别: music=强制2D(背景音乐), sfx/voice=走3D'}, 'min_distance': {'type': 'number', 'description': '最小距离 (内不再衰减)'}, 'max_distance': {'type': 'number', 'description': '最大距离 (外完全听不见)'}, 'rolloff': {'type': 'number', 'description': '衰减曲线强度'}}}},
    {'name': 'loom_audio_3d_get', 'description': '查询音频 3D 参数', 'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string', 'description': '物体名称 (缺省=当前选中)'}}}},
    # 2026-10-18 阶段5: UI 编辑工具（与 EAI ui_* 命令对接）
    {'name': 'loom_ui_list', 'description': '列出所有 UI Canvas 与元素树（CanvasUI 契约 §8）',
     'inputSchema': {'type': 'object', 'properties': {
         'canvas': {'type': 'integer', 'description': '指定 Canvas 序号（缺省=全部）'}}}},
    {'name': 'loom_ui_add', 'description': '添加 UI 元素：11 种类型 (panel/text/image/button/slider/toggle/progress_bar/scroll_view/input_field/dropdown/grid_layout)',
     'inputSchema': {'type': 'object', 'properties': {
         'type': {'type': 'string', 'description': '元素类型'},
         'name': {'type': 'string', 'description': '元素名（缺省自动生成 {type}_{n}）'},
         'parent': {'type': 'string', 'description': '父元素名（缺省=Canvas root）'},
         'canvas': {'type': 'integer', 'description': 'Canvas 序号（缺省=0）'},
         'rect': {'type': 'array', 'description': '[x,y,w,h] 像素'},
         'anchor': {'type': 'array', 'description': '[ax,ay] 锚点 0~1'},
         'pivot': {'type': 'array', 'description': '[px,py] 轴心 0~1'},
         'visible': {'type': 'boolean'},
         'enabled': {'type': 'boolean'},
         'z_order': {'type': 'integer'},
     }, 'required': ['type']}},
    {'name': 'loom_ui_set', 'description': '修改 UI 元素字段（含 type-specific 字段）',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string', 'description': '元素名'},
         'canvas': {'type': 'integer', 'description': 'Canvas 序号（缺省=0）'},
     }, 'required': ['name']}},
    {'name': 'loom_ui_remove', 'description': '删除 UI 元素',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string', 'description': '元素名'},
         'canvas': {'type': 'integer', 'description': 'Canvas 序号（缺省=0）'},
     }, 'required': ['name']}},
    {'name': 'loom_ui_canvas_add', 'description': '添加 UI Canvas',
     'inputSchema': {'type': 'object', 'properties': {
         'type': {'type': 'string', 'description': 'screen 或 world（缺省 screen）'},
         'width': {'type': 'integer'}, 'height': {'type': 'integer'},
         'z_order': {'type': 'integer'},
     }}},
    {'name': 'loom_ui_reparent', 'description': '移动 UI 元素到另一个父元素（检查循环依赖）',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string', 'description': '元素名'},
         'new_parent': {'type': 'string', 'description': '新父元素名（缺省=Canvas root）'},
         'canvas': {'type': 'integer', 'description': 'Canvas 序号（缺省=0）'},
         'index': {'type': 'integer', 'description': '在新父元素下的插入位置（缺省=末尾）'},
     }, 'required': ['name']}},
    {'name': 'loom_ui_move_child', 'description': '同一父元素内调整 UI 元素顺序',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string', 'description': '元素名'},
         'to_index': {'type': 'integer', 'description': '目标位置（同级列表中的索引，0 起）'},
         'canvas': {'type': 'integer', 'description': 'Canvas 序号（缺省=0）'},
     }, 'required': ['name', 'to_index']}},
    # 2026-10-18 Raycast（物理 Culverin + 几何 AABB 兜底）
    {'name': 'loom_raycast', 'description': '射线检测（最近命中）：从 (ox,oy,oz) 沿 (dx,dy,dz) 射向，返回 hit 或 null',
     'inputSchema': {'type': 'object', 'properties': {
         'ox': {'type': 'number'}, 'oy': {'type': 'number'}, 'oz': {'type': 'number'},
         'dx': {'type': 'number'}, 'dy': {'type': 'number'}, 'dz': {'type': 'number'},
         'max_dist': {'type': 'number', 'description': '最大距离，缺省 1000'},
         'backend': {'type': 'string', 'description': 'auto|physics|geometry，缺省 auto'},
         'layer_mask': {'type': 'integer', 'description': '位掩码过滤（bit i 表示 layer i；缺省=不限；0=全不匹配）'},
     }, 'required': ['ox', 'oy', 'oz', 'dx', 'dy', 'dz']}},
    {'name': 'loom_raycast_all', 'description': '射线检测（全部命中）：返回 hits 列表按距离升序',
     'inputSchema': {'type': 'object', 'properties': {
         'ox': {'type': 'number'}, 'oy': {'type': 'number'}, 'oz': {'type': 'number'},
         'dx': {'type': 'number'}, 'dy': {'type': 'number'}, 'dz': {'type': 'number'},
         'max_dist': {'type': 'number'},
         'backend': {'type': 'string'},
         'layer_mask': {'type': 'integer', 'description': '位掩码过滤（bit i 表示 layer i）'},
     }, 'required': ['ox', 'oy', 'oz', 'dx', 'dy', 'dz']}},
    {'name': 'loom_raycast_screen', 'description': '屏幕坐标反投影射线（等价鼠标点选）',
     'inputSchema': {'type': 'object', 'properties': {
         'px': {'type': 'number', 'description': '屏幕 x 像素'},
         'py': {'type': 'number', 'description': '屏幕 y 像素'},
         'max_dist': {'type': 'number'},
         'backend': {'type': 'string'},
         'layer_mask': {'type': 'integer', 'description': '位掩码过滤（bit i 表示 layer i）'},
     }, 'required': ['px', 'py']}},
]

RESOURCES_DEF = [
    {'uri': 'loom://scene/active', 'name': 'Active Scene Hierarchy', 'description': '当前激活场景的完整物体树与组件属性', 'mimeType': 'application/json'},
    {'uri': 'loom://engine/metrics', 'name': 'Engine Performance Metrics', 'description': '实时性能度量指标 (FPS, TPS, Profiler Stage Times, DrawCalls)', 'mimeType': 'application/json'},
    {'uri': 'loom://engine/logs', 'name': 'Engine Console Logs', 'description': '引擎控制台最近 200 行输出日志', 'mimeType': 'text/plain'},
    {'uri': 'loom://engine/dll_registry', 'name': 'DLL Module Registry', 'description': '5 大官方核心 C ABI 动态库装配与 SHA256 钉扎状态', 'mimeType': 'application/json'}
]

PROMPTS_DEF = [
    {'name': 'diagnose_engine_issue', 'description': '自动排查引擎运行时的帧率异常、物理穿模或脚本崩溃问题', 'arguments': []},
    {'name': 'create_player_character', 'description': '在场景中自动生成并配置一个支持 WASD 移动与第三人称相机跟随的玩家角色', 'arguments': []}
]
class LoomMCPServer:
    def __init__(self, client=None):
        self.client = client or LoomEngineClient()
    def handle_request(self, req):
        method = req.get('method')
        req_id = req.get('id')
        params = req.get('params') or {}
        if method == 'initialize':
            return {'jsonrpc': '2.0', 'id': req_id, 'result': {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {'tools': {}, 'resources': {}, 'prompts': {}}, 'serverInfo': SERVER_INFO}}
        elif method == 'notifications/initialized': return None
        elif method == 'ping': return {'jsonrpc': '2.0', 'id': req_id, 'result': {}}
        elif method == 'tools/list': return {'jsonrpc': '2.0', 'id': req_id, 'result': {'tools': TOOLS_DEF}}
        elif method == 'tools/call':
            name = params.get('name')
            args = params.get('arguments') or {}
            res = self.dispatch_tool(name, args)
            return {'jsonrpc': '2.0', 'id': req_id, 'result': res}
        elif method == 'resources/list': return {'jsonrpc': '2.0', 'id': req_id, 'result': {'resources': RESOURCES_DEF}}
        elif method == 'resources/read':
            uri = params.get('uri')
            res = self.dispatch_resource(uri)
            return {'jsonrpc': '2.0', 'id': req_id, 'result': res}
        elif method == 'prompts/list': return {'jsonrpc': '2.0', 'id': req_id, 'result': {'prompts': PROMPTS_DEF}}
        elif method == 'prompts/get':
            p_name = params.get('name')
            res = self.dispatch_prompt(p_name)
            return {'jsonrpc': '2.0', 'id': req_id, 'result': res}
        else:
            return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': -32601, 'message': f'Method not found: {method}'}}

    def _mk(self, text):
        return {'content': [{'type': 'text', 'text': text}], 'isError': False}

    def _err(self, text):
        return {'content': [{'type': 'text', 'text': text}], 'isError': True}

    def _wrap(self, r):
        return {'content': [{'type': 'text', 'text': json.dumps(r, ensure_ascii=False, indent=2)}],
                'isError': not r.get('ok', False)}

    def _merge(self, *rs):
        text = '\n'.join(json.dumps(r, ensure_ascii=False) for r in rs)
        ok = all(r.get('ok', False) for r in rs)
        return {'content': [{'type': 'text', 'text': text}], 'isError': not ok}

    def _find_last_model(self):
        """object_add 之后查最后一个模型名 (用于 rename / set_transform 目标定位)."""
        ol = self.client.call('object_list')
        if not ol.get('ok'):
            return None
        models = (ol.get('result') or {}).get('models') or []
        return models[-1]['name'] if models else None

    def dispatch_tool(self, name, args):
        import math
        c = self.client

        # ---- 场景管理 ----
        if name == 'unity_scene_new':
            return self._wrap(c.call('scene_new'))
        if name == 'unity_scene_save':
            return self._wrap(c.call('scene_save', {'path': args.get('path')}))
        if name == 'unity_scene_load':
            return self._wrap(c.call('scene_load', {'path': args.get('path')}))

        # ---- GameObject 实体 ----
        if name == 'unity_gameobject_create':
            prim = args.get('primitive', 'cube') or 'cube'
            r0 = c.call('object_add', {'type': prim})
            if not r0.get('ok'):
                return self._wrap(r0)
            results = [r0]
            new_name = self._find_last_model()
            if args.get('name') and new_name:
                r1 = c.call('object_rename', {'name': new_name, 'new': args['name']})
                results.append(r1)
                new_name = args['name']
            # 位置/旋转/缩放: set_transform（引擎用 x,y,z / rx,ry,rz 度 / sx,sy,sz）
            tf = {}
            if 'position' in args and args['position']:
                p = list(args['position'])
                tf.update({'x': p[0], 'y': p[1], 'z': p[2]})
            if 'rotation' in args and args['rotation']:
                rr = list(args['rotation'])   # 弧度 -> 度
                tf.update({'rx': math.degrees(float(rr[0])),
                           'ry': math.degrees(float(rr[1])),
                           'rz': math.degrees(float(rr[2]))})
            if 'scale' in args and args['scale']:
                sc = list(args['scale'])
                tf.update({'sx': sc[0], 'sy': sc[1], 'sz': sc[2]})
            if tf:
                tf['name'] = new_name or ''
                r2 = c.call('set_transform', tf)
                results.append(r2)
            return self._merge(*results)

        if name == 'unity_gameobject_list':
            return self._wrap(c.call('object_list'))

        if name == 'unity_gameobject_select':
            return self._wrap(c.call('object_select', {'name': args.get('name_or_id')}))

        if name == 'unity_gameobject_delete':
            tgt = args.get('name_or_id')
            if tgt:
                rs = c.call('object_select', {'name': tgt})
                if not rs.get('ok'):
                    return self._wrap(rs)
            return self._wrap(c.call('object_delete'))

        if name == 'unity_gameobject_duplicate':
            tgt = args.get('name_or_id')
            if tgt:
                rs = c.call('object_select', {'name': tgt})
                if not rs.get('ok'):
                    return self._wrap(rs)
            return self._wrap(c.call('object_duplicate'))

        if name == 'unity_gameobject_set_parent':
            return self._wrap(c.call('reparent', {
                'child': args.get('child'),
                'parent': args.get('parent') or '',
                'keep_world': args.get('keep_world', True),
            }))

        # ---- 组件属性 ----
        if name == 'unity_transform_set':
            tf = {}
            if args.get('name_or_id'):
                tf['name'] = args['name_or_id']
            if 'position' in args and args['position']:
                p = list(args['position'])
                tf.update({'x': p[0], 'y': p[1], 'z': p[2]})
            if 'rotation' in args and args['rotation']:
                rr = list(args['rotation'])
                tf.update({'rx': math.degrees(float(rr[0])),
                           'ry': math.degrees(float(rr[1])),
                           'rz': math.degrees(float(rr[2]))})
            if 'scale' in args and args['scale']:
                sc = list(args['scale'])
                tf.update({'sx': sc[0], 'sy': sc[1], 'sz': sc[2]})
            return self._wrap(c.call('set_transform', tf))

        if name == 'unity_material_set':
            tgt = args.get('name_or_id')
            rs = []
            if 'color' in args:
                rs.append(c.call('set_color', {'name': tgt, 'color': args['color']}))
            if 'saturation' in args:
                rs.append(c.call('set_saturation', {'name': tgt, 'value': args['saturation']}))
            if 'normal_mode' in args:
                rs.append(c.call('set_normal_mode', {'name': tgt, 'mode': args['normal_mode']}))
            if not rs:
                return self._err('至少给 color/saturation/normal_mode 之一')
            return self._merge(*rs)

        if name == 'unity_lod_set':
            payload = {'name': args.get('name_or_id')}
            for k in ('screen', 'bias', 'on'):
                if k in args:
                    payload[k] = args[k]
            return self._wrap(c.call('set_lod', payload))

        if name == 'unity_env_set':
            payload = {'name': args.get('name_or_id')}
            for k in ('paths', 'color'):
                if k in args:
                    payload[k] = args[k]
            return self._wrap(c.call('set_env', payload))

        if name == 'unity_pbr_set':
            payload = {'name': args.get('name_or_id')}
            for k in ('metallic', 'roughness', 'smoothness', 'on'):
                if k in args:
                    payload[k] = args[k]
            return self._wrap(c.call('set_pbr', payload))

        if name == 'unity_texture_set':
            payload = {'name': args.get('name_or_id'),
                       'path': args.get('path', '')}
            for k in ('wrap', 'filter_mode', 'aniso', 'max_size', 'compression'):
                if k in args:
                    payload[k] = args[k]
            return self._wrap(c.call('set_texture', payload))

        if name == 'unity_collider_set':
            payload = {'name': args.get('name_or_id')}
            if 'enabled' in args:
                payload['on'] = args['enabled']
            return self._wrap(c.call('collider', payload))

        if name == 'unity_rigidbody_set':
            # 参数透传 (2026-10-13): 有任一精细参数 -> action=set; 否则 add。
            # 旧实现只传 name/action, 丢弃 mass/gravity/friction/velocity。
            fine = [k for k in ('mass', 'use_gravity', 'is_kinematic',
                                'friction', 'restitution', 'velocity')
                    if k in args]
            act = args.get('action')
            if act is None:
                act = 'set' if fine else 'add'
            payload = {'name': args.get('name_or_id'), 'action': act}
            for k in fine:
                payload[k] = args[k]
            return self._wrap(c.call('rigidbody', payload))

        if name == 'unity_physics_simulate':
            # 确定性推进 N 个逻辑帧 (物理对拍; 需已 play on, 建议 paused=true)
            return self._wrap(c.call('physics_simulate', {
                'frames': args.get('frames', 1)}))

        # ---- 脚本玩法 ----
        if name == 'unity_script_add':
            return self._wrap(c.call('script_add', {
                'target': args.get('name_or_id'),
                'sid': args.get('script_id'),
            }))
        if name == 'unity_script_remove':
            return self._wrap(c.call('script_remove', {
                'name': args.get('name_or_id'),
                'index': args.get('index', 0),
            }))
        if name == 'unity_script_write_file':
            fname = (args.get('filename') or '').strip()
            code_str = args.get('code', '')
            if not (fname.endswith('.lua') or fname.endswith('.py')):
                return self._err('文件名必须以 .lua 或 .py 结尾')
            scripts_dir = os.path.join(c.base_dir, 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            full_path = os.path.join(scripts_dir, fname)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(code_str)
            return self._mk('脚本写入成功: %s (%d bytes)' % (full_path, len(code_str)))

        # ---- 3D 音频 (2026-10-18) ----
        if name == 'loom_audio_3d_set':
            payload = {}
            if args.get('name'):
                payload['name'] = args['name']
            for k in ('category', 'min_distance', 'max_distance', 'rolloff'):
                if k in args:
                    payload[k] = args[k]
            return self._wrap(c.call('set_audio_3d', payload))

        if name == 'loom_audio_3d_get':
            payload = {}
            if args.get('name'):
                payload['name'] = args['name']
            return self._wrap(c.call('get_audio_3d', payload))

        # ---- Layer / Tag (2026-10-18) ----
        if name == 'loom_set_layer':
            payload = {'layer': args.get('layer')}
            if args.get('name'):
                payload['name'] = args['name']
            return self._wrap(c.call('set_layer', payload))

        if name == 'loom_set_tag':
            payload = {'tag': args.get('tag')}
            if args.get('name'):
                payload['name'] = args['name']
            return self._wrap(c.call('set_tag', payload))

        if name == 'loom_get_layer_tag':
            payload = {}
            if args.get('name'):
                payload['name'] = args['name']
            return self._wrap(c.call('get_layer_tag', payload))

        # ---- UI 编辑 (2026-10-18 阶段5) ----
        if name == 'loom_ui_list':
            payload = {}
            if 'canvas' in args:
                payload['canvas'] = args['canvas']
            return self._wrap(c.call('ui_list', payload))

        if name == 'loom_ui_add':
            # 直接透传 args（含 type / name / parent / canvas / rect 等）
            return self._wrap(c.call('ui_add', dict(args)))

        if name == 'loom_ui_set':
            return self._wrap(c.call('ui_set', dict(args)))

        if name == 'loom_ui_remove':
            return self._wrap(c.call('ui_remove', dict(args)))

        if name == 'loom_ui_canvas_add':
            return self._wrap(c.call('ui_canvas_add', dict(args)))

        if name == 'loom_ui_reparent':
            return self._wrap(c.call('ui_reparent', dict(args)))

        if name == 'loom_ui_move_child':
            return self._wrap(c.call('ui_move_child', dict(args)))

        # ---- Raycast (2026-10-18) ----
        if name == 'loom_raycast':
            return self._wrap(c.call('raycast', dict(args)))
        if name == 'loom_raycast_all':
            return self._wrap(c.call('raycast_all', dict(args)))
        if name == 'loom_raycast_screen':
            return self._wrap(c.call('raycast_screen', dict(args)))

        # ---- 测试视口 ----
        if name == 'unity_playmode_toggle':
            payload = {'on': args.get('on', True)}
            if 'paused' in args:
                payload['paused'] = args['paused']
            return self._wrap(c.call('play', payload))
        if name == 'unity_capture_viewport':
            return self._wrap(c.call('screenshot', {'file': args.get('path', '')}))

        # ---- 发布 ----
        if name == 'unity_build_player':
            import subprocess
            out_dir = args.get('output_dir') or os.path.join(
                c.base_dir, '发布', args.get('game_name', 'MyGame'))
            cmd = [sys.executable, os.path.join(c.base_dir, 'build_game.py'),
                   '--name', args.get('game_name', 'MyGame'),
                   '--output', out_dir, '--force']
            if 'scene_path' in args:
                cmd += ['--scene', args['scene_path']]
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=c.base_dir)
            return {'content': [{'type': 'text',
                                 'text': p.stdout + ('\n' + p.stderr if p.stderr else '')}],
                    'isError': p.returncode != 0}

        # ---- 问题排查 ----
        if name == 'diag_get_engine_metrics':
            return self._wrap(c.call('engine_metrics'))
        if name == 'diag_get_console_logs':
            return self._wrap(c.get_logs(args.get('after_seq', 0)))
        if name == 'diag_inspect_gameobject':
            return self._wrap(c.call('inspect', {'name': args.get('name_or_id')}))
        if name == 'diag_check_dll_integrity':
            reg_path = os.path.join(c.base_dir, 'core_components', 'registry.json')
            if not os.path.exists(reg_path):
                return self._err('未找到注册表文件: %s' % reg_path)
            with open(reg_path, 'r', encoding='utf-8') as f:
                reg = json.load(f)
            import hashlib
            audit = []
            for comp in reg.get('components', []):
                p = os.path.join(c.base_dir, comp['path'])
                exists = os.path.exists(p)
                sha_match = False
                actual_sha = ''
                if exists:
                    with open(p, 'rb') as fh:
                        actual_sha = hashlib.sha256(fh.read()).hexdigest()
                    sha_match = (actual_sha == comp.get('sha256', ''))
                audit.append({'module_id': comp['module_id'], 'path': comp['path'],
                              'exists': exists, 'sha_match': sha_match,
                              'actual_sha': actual_sha,
                              'expected_sha': comp.get('sha256', ''),
                              'provides': comp.get('provides', [])})
            return {'content': [{'type': 'text', 'text': json.dumps(audit, ensure_ascii=False, indent=2)}],
                    'isError': not all(a['sha_match'] for a in audit)}
        if name == 'diag_check_crash_dumps':
            crash_dir = os.path.join(c.base_dir, '崩溃日志')
            dumps = glob.glob(os.path.join(crash_dir, '*.dmp'))
            dumps_info = [{'file': os.path.basename(d),
                           'size': os.path.getsize(d),
                           'mtime': time.strftime('%Y-%m-%d %H:%M:%S',
                                                  time.localtime(os.path.getmtime(d)))}
                          for d in dumps]
            return {'content': [{'type': 'text',
                                 'text': json.dumps({'total_dumps': len(dumps_info),
                                                     'dumps': dumps_info},
                                                    ensure_ascii=False, indent=2)}],
                    'isError': False}

        return self._err('未知工具: %s' % name)

    def dispatch_resource(self, uri):
        c = self.client
        if uri == 'loom://scene/active':
            r = c.call('object_list')
            return {'contents': [{'uri': uri, 'mimeType': 'application/json', 'text': json.dumps(r, ensure_ascii=False, indent=2)}]}
        elif uri == 'loom://engine/metrics':
            r = c.call('engine_metrics')
            return {'contents': [{'uri': uri, 'mimeType': 'application/json', 'text': json.dumps(r, ensure_ascii=False, indent=2)}]}
        elif uri == 'loom://engine/logs':
            r = c.get_logs(0)
            lines = [f'[{row[1]}] {row[2]}' for row in r.get('lines', [])]
            return {'contents': [{'uri': uri, 'mimeType': 'text/plain', 'text': '\n'.join(lines)}]}
        elif uri == 'loom://engine/dll_registry':
            reg_path = os.path.join(c.base_dir, 'core_components', 'registry.json')
            text = open(reg_path, 'r', encoding='utf-8').read() if os.path.exists(reg_path) else '{}'
            return {'contents': [{'uri': uri, 'mimeType': 'application/json', 'text': text}]}
        return {'contents': [{'uri': uri, 'mimeType': 'text/plain', 'text': f'Resource not found: {uri}'}]}

    def dispatch_prompt(self, name):
        if name == 'diagnose_engine_issue':
            return {'description': '排查引擎当前运行时的性能掉帧或报错问题', 'messages': [{'role': 'user', 'content': {'type': 'text', 'text': '请调用 diag_get_engine_metrics 与 diag_get_console_logs，检查当前 FPS/TPS 与控制台最新报错，输出排查结论并给出修复方案。'}}]}
        elif name == 'create_player_character':
            return {'description': '创建一个完整的第三人称玩家角色', 'messages': [{'role': 'user', 'content': {'type': 'text', 'text': '请在场景中心创建一个胶囊体/立方体角色“Player”，赋予刚体与碰撞体，并挂载 scripts/wasd_move.lua 与 scripts/camera_follow.lua 实现第三人称操控。'}}]}
        return {'description': '未知 Prompt', 'messages': []}
def run_stdio_server():
    server = LoomMCPServer()
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        res = server.handle_request(req)
        if res is not None:
            sys.stdout.write(json.dumps(res, ensure_ascii=False) + '\n')
            sys.stdout.flush()

if __name__ == '__main__':
    run_stdio_server()

