# -*- coding: utf-8 -*-
"""scene/identity.py — ★ guid 唯一真源（Q-B7-49-1 P2，2026-11-21 人类裁决 ①+③）。

裁决 ①：new_guid() 保持 uuid4().hex —— **新增对象/资产**的身份由它生成。
裁决 ②（本文件）：迁移期 v1 物体缺 id 时**不用 uuid4**，用 derived_guid()
  **确定性派生** —— 同输入同输出，两次迁移 / 两端（GL/VK）加载 / 跨机读盘
  逐值相等（门：tests/test_scene_contract.py G1）。保存场景后固化为永久身份。
裁决 ③：迁移新分配了 id 就打印一行「请保存场景以固化」提示（只打印一行，
  不打断加载、不弹窗；幂等重迁移不打印）。

收敛纪律（门：tests/test_scene_contract.py G3）：全仓生产代码里
uuid.uuid4 / uuid4().hex 只允许出现在本文件（唯一实现）；旧 8 处散落点
（sceneio.generate_guid / loom_assets.new_guid / 契约 migrate / loom_model_data /
scene.entities 两处构造默认值 / loom_material / loom_texture / loom_cubemap）
全部改为调 new_guid()。两个非对象 guid 的随机身份（agent_commands 截图临时
文件名、hostenv/userpaths 工程 project_id）同格式（uuid4().hex），一并收敛。

依赖：只 import hashlib / uuid —— 本模块必须保持零引擎/零 numpy/零 GPU，
契约模块（scene.contract）与实体模块（scene.entities）都要 import 它。
"""
import hashlib
import uuid


def new_guid():
    """新对象/资产 guid（32 hex，uuid4）。**全仓唯一实现** —— 旧 8 处散落点已全部收敛到这里。"""
    return uuid.uuid4().hex


def derived_guid(*parts):
    """迁移期**确定性派生** guid（32 hex）：同输入同输出，不用 uuid4。

    输入按位置传入任意可 str() 的派生因子（迁移方约定：
    derived_guid('scene-v1', 物体序号, 物体内容 JSON) —— 契约模块 migrate 的 v1
    分支是唯一调用方）。实现 = SHA-256('\x00'.join(parts)) 截 32 hex：
      · 同一份 v1 场景无论迁移几次 / 在哪个后端 / 哪台机器，派生值逐位相同；
      · 序号参与派生，内容相同的两个物体也不会撞同一 id；
      · 派生值只用于**迁移补 id**这一次性场合，写盘后即固化为永久身份（I4）。
    """
    payload = '\x00'.join(str(p) for p in parts)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]
