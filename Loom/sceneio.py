# -*- coding: utf-8 -*-
"""sceneio.py — 场景/Prefab 序列化（**薄门面**：只 re-export，不含任何实现）。

目录重构 B2 批（Q-B7-38-1，2026-11-21）：本文件 2220 行按域拆进了 scene/ 包 ——
  scene/contract.py   场景契约（版本号 / gate / migrate / prepare；原 loom_scene_contract.py）
  scene/entities.py   场景实体状态类（LightState / CameraState；原 loom_scene_entities.py）
  scene/query.py      SceneQueryMixin（原 loom_scene_query.py）
  scene/identity.py   ★ guid 唯一真源（new_guid / derived_guid，Q-B7-49-1 P2 新建）
  scene/asset.py      资产身份层（asset_context / 资产问题 / 失效引用保留 / generate_guid）
  scene/object.py     对象 <-> dict（发射/装配/父链校验 + Canvas UI 段）
  scene/camera.py     相机投影归一 + 摄像机实体
  scene/light.py      光源
  scene/sky.py        天空盒
  scene/material.py   材质资产
  scene/resource.py   独立资产文件（材质/网格）
  scene/prefab.py     Prefab
  scene/io.py         场景装配（scene_to_dict / scene_from_dict）+ 存盘/读盘 + 混淆编码

**外部引用零改动**：旧调用面（外部 71 个文件、365 处 sceneio.* 引用 / from sceneio
import）全部靠本门面的同名 re-export 养活 —— 旧名一个不许断（test_scene_contract
F 组与 test_sceneio 全量钉住）。各域函数体与拆分前逐字一致（生成器校验）。

两个兼容别名照旧（唯一真源在契约模块，本文件不写数字）：
  SCENE_VERSION         = scene.contract.CURRENT_VERSION
  check_engine_version  = scene.contract.gate
sceneio.prepare 保留原函数体（把"迁移"那一步绑定到 sceneio.migrate 符号上，
tests/test_scene_load_parity.py ③-migrate 按 sceneio.migrate 符号观察）。
"""
from core.primitives import Point3D
from scene.contract import (CURRENT_VERSION, ENGINE_VERSION, SceneVersionError,
                            gate, migrate, parse_version, version_lt,
                            prepare as _contract_prepare)
from scene.identity import derived_guid, new_guid
from scene.asset import (ASSET_ERROR_LIMIT, _TEXTURE_IMPORT_KEYS, _clear_slot_ref,
                         _cubemap_ref_dict, _keep_slot_ref, _texture_ref_dict,
                         _warn_dup_guid, asset_context, asset_error_count,
                         asset_errors, asset_issue_notice, asset_refs_kept,
                         clear_asset_slot, generate_guid, record_asset_error,
                         reset_asset_errors)
from scene.object import (SceneCycleError, _apply_object, _apply_ui,
                          _apply_ui_element, _emit_object, _emit_subtree,
                          _emit_ui, _emit_ui_element, _f1, _f3, _link_by_map,
                          _link_parents, _link_ui_targets, _make_mesh,
                          _validate_model_graph, _validate_object_graph)
from scene.camera import (FOV_DEFAULT_DEG, FOV_MAX_DEG, FOV_MIN_DEG,
                          ORTHO_SIZE_DEFAULT, ORTHO_SIZE_MIN, _FALSE_WORDS,
                          _TRUE_WORDS, _apply_cameras, _b_strict,
                          _emit_camera, _emit_camera_skybox,
                          _keep_cam_skybox_ref, _link_camera_parents,
                          norm_fov_deg, norm_ortho_size)
from scene.light import _apply_lights, _emit_light
from scene.sky import (DEFAULT_SKYBOX_COLOR, DEFAULT_SKYBOX_NAME, _apply_skybox,
                       _apply_skybox_or_default, _emit_skybox,
                       _emit_skybox_checked, _inside_scene_dir,
                       _scene_skybox_from_data, default_skybox,
                       skybox_from_dict, parse_color)
from scene.material import (_apply_material_env,
                            _apply_material_texture, _apply_materials,
                            _drop_orphan_default_materials, _emit_material,
                            _emit_material_refs, _is_default_material,
                            _resolve_scene_rel)
from scene.resource import (ASSET_VERSION, load_material_asset, load_mesh_asset,
                            material_to_dict, save_material_asset,
                            save_mesh_asset)
from scene.prefab import (PREFAB_VERSION, instantiate_prefab, load_prefab,
                          prefab_to_dict, save_prefab)
from scene.io import (_ENC_MAGIC, _XOR_KEY, decode_blob, encode_blob,
                      load_scene_data, save_json_atomic, save_scene_data,
                      scene_from_dict, scene_to_dict)

SCENE_VERSION = CURRENT_VERSION   # 兼容别名（唯一真源在契约模块，本文件不再写数字）
check_engine_version = gate       # 兼容别名（旧调用点/既有测试按这个名字用）


def __getattr__(name):
    # sceneio._CUR_BASE_DIR 历史 读/写 点（scene_driver VK 装配）改指唯一真源
    # scene/material.py（B2 拆分：模块全局写无法经 re-export 转发，读经 PEP 562 惰性转发，
    # 写方 scene_driver:752 已改为直写 scene.material —— 这里只为**任何残余读点**兜底）。
    if name == '_CUR_BASE_DIR':
        from scene import material as _material
        return _material._CUR_BASE_DIR
    raise AttributeError(name)


def prepare(data):
    """**场景打开的唯一入口**：先过版本闸门（任何状态变更之前），再做数据迁移。

    契约模块的 prepare() 是唯一实现；这里只把"迁移"这一步绑定到**本模块的 migrate
    符号**上 —— 于是 `sceneio.migrate` 仍然是真正被调用的实现（历史调用点、monkeypatch
    探针、tests/test_scene_load_parity.py ③-migrate 都按这个符号观察），语义只有一份。

    所有打开场景的路径都必须经过它：编辑器 _load_scene / GL 播放器 _load_scene_data /
    VK 播放器 load_from_data / 打包游戏（PlayerApp / run_vk）/ 游戏包（同前两条）/
    EAI+Hub 的 scene_load 命令。
    """
    return _contract_prepare(data, migrate_fn=migrate)
