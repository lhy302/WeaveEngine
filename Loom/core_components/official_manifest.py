# -*- coding: utf-8 -*-
"""official_manifest.py — 官方件出厂哈希基准 (编译进 exe, 外部改不动).

本文件由 tests/_tmp/gen_official_manifest.py 从 core_components/registry.json
自动生成 (build_all.bat 在 refresh_registry_sha.py 之后调用). 请勿手改.

作用: 与 registry.json (磁盘, 可改) 职责分离 ——
  · registry.json  = 花名册 (有哪些组件/装哪/启用否; 允许改, 装配灵活性来源)
  · 本文件          = 出厂基准 (官方件应有的 SHA256; 编译进 exe 外部改不动)
在 module_registry.assemble() 起始处校验: 官方件实际 SHA256 与基准不符 = 报警拒载.

LOOM_DEV=1 时跳过校验 (开发期天天重编, SHA 一直在变).
"""
# 生成时间: 2026-10-16T14:14:04
OFFICIAL_MANIFEST = {
    'module_ref': {
        "path": 'core_components/module_ref.dll',
        "sha256": '3cf5fc9cfc1cabe97306ed308035b358fe9a11e5d43ea6f578a2c5262734b793',
    },
    'ckernels': {
        "path": 'ckernels/loom_kernels.dll',
        "sha256": 'df810fc5652ee238d020c448b2c6e06dce745a2b59acb2542f37a26d1d45d37b',
    },
    'pipeline': {
        "path": 'core_components/pipeline/pipeline.dll',
        "sha256": '051b12d6aa4a6e1e3f5338999a282fde9110e3c3c7ed0c5e9d3a587319d8f30e',
    },
    'script': {
        "path": 'core_components/script/script.dll',
        "sha256": 'd445c97e9ac641fc2bc7432016a6d55790809d6240bf39825c952fa40a7ef32f',
    },
    'physics': {
        "path": 'core_components/physics/physics.dll',
        "sha256": '124eba34fc985ed1ef80b7d4cee3e2451189066bacd9c5c8dd25e9be1cbd39ba',
    },
}
