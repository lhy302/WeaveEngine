# -*- coding: utf-8 -*-
"""loom_scene_query.py — 场景查询 / Layer·Tag 接口（**后端无关**，两端同一份）。

2026-11-17（S2-2 门面收敛 / JVM 模型）：这 11 个方法原来长在 `GLEngine` 上，
但它们**只碰 `self.models` 与 `layer_tag` 模块，不含任何 GPU 依赖** ——
放在 GL 侧等于让 VK 脚本调不到（VK 下 `AttributeError`），属于「受后端影响」。
搬进内核后两端共享同一份实现。

归属判据（可审计）：**方法体里不出现 moderngl / wgpu / 着色器 / VAO / 纹理 / 帧循环**。
不满足这条的（例如 `add_model` 要上传 VBO）留在后端侧，等 S2-2 的「数据/GPU 拆分」再处理。

依赖宿主提供：
  self.models（GameObject 列表）—— 两端都有（GLEngine 与 SceneDriver 都在 __init__ 建）
"""


class SceneQueryMixin:

    # ================ Layer / Tag 接口 (2026-10-18, 契约 §4) ================
    # 纯数据操作层: 校验与存储全部代理 layer_tag 模块; 撤销快照由调用方
    # (GUI commit_model / EAI _commit) 负责 —— 基座层不依赖编辑器概念.
    def tag_exists(self, tag):
        """标签是否已注册 (不区分大小写)."""
        import kernels.layer_tag as layer_tag
        return layer_tag.tag_exists(tag)

    def layer_name(self, layer_id):
        """层编号 -> 层名 (未命名/越界返回空串)."""
        import kernels.layer_tag as layer_tag
        return layer_tag.layer_name(layer_id)

    def layer_id(self, name):
        """层名 -> 层编号 (找不到返回 -1)."""
        import kernels.layer_tag as layer_tag
        return layer_tag.layer_id(name)

    def register_tag(self, tag):
        """注册新标签 (幂等); 已存在返回 False, 非法抛 ValueError."""
        import kernels.layer_tag as layer_tag
        return layer_tag.register_tag(tag)

    # ---- 2026-10-18 阶段1档序8 对象查找（用户拍板 1=C 双 API / 2=A 物体列表）----
    def find_by_tag(self, tag):
        """查找所有指定标签的物体 (不区分大小写)."""
        low = str(tag).lower()
        return [m for m in self.models
                if getattr(m, 'tag', '').lower() == low]

    def find_by_name(self, name):
        """按物体名查找首个匹配（Unity GameObject.Find 语义）。

        返回: GameObject 或 None（找不到）
        场景: 名字唯一（如 Player）时直接用；重名时只返回第一个。
        """
        if not isinstance(name, str) or not name:
            return None
        for m in self.models:
            if getattr(m, 'name', '') == name:
                return m
        return None

    def find_all_by_name(self, name):
        """按物体名查找所有匹配（与 find_by_tag 返回列表一致）。

        返回: list[GameObject]（可能空列表）
        场景: 重名物体（如 5 个 Enemy）批量操作。
        """
        if not isinstance(name, str) or not name:
            return []
        return [m for m in self.models if getattr(m, 'name', '') == name]

    def find_by_script(self, script_id):
        """查找挂有指定脚本的物体（按 script_id 匹配，物体去重）。

        返回: list[GameObject]（可能空列表；一个物体即使挂多个相同脚本也只返回一次）
        场景: 按"行为"批量操作（所有 enemy_ai 敌人统一暂停/重置）。
        """
        if not isinstance(script_id, str) or not script_id:
            return []
        out = []
        for m in self.models:
            for sc in getattr(m, 'scripts', ()):
                if getattr(sc, 'script_id', None) == script_id:
                    out.append(m)
                    break   # 同物体只返回一次
        return out

    def send_message_to_name(self, model_name, method_name, *args, **kwargs):
        """2026-10-18 阶段1档序6 SendMessage: 按物体名字调用脚本方法。

        语义对齐 Unity GameObject.SendMessage：找到首个同名物体（Unity 场景内
        名字唯一的假设），在其所有脚本上调用 method_name 方法。异常隔离由
        GameObject.send_message 负责（打印不崩帧，坏脚本标记）。

        返回: 成功调用的脚本数（int）。未找到物体返回 0。
        """
        if not isinstance(model_name, str) or not model_name:
            return 0
        for m in self.models:
            if getattr(m, 'name', '') == model_name:
                return m.send_message(method_name, *args, **kwargs)
        return 0

    def set_object_layer(self, obj, layer_id):
        """设置物体层; 越界抛 ValueError (校验在 GameObject.layer setter)."""
        obj.layer = layer_id

    def set_object_tag(self, obj, tag):
        """设置物体标签; 未注册抛 TagNotRegisteredError (校验在 GameObject.tag setter)."""
        obj.tag = tag
