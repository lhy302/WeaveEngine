# WeaveEngine

> **把创意织成可玩的梦。**
>
> Weave（编织）+ Engine（引擎），呼应前身代号 **Loom**（织布机）——
> 一台把灵感经纬交织成游戏的织梦机。

Loom 引擎是一个 **Python 基座 + C ABI DLL 核心组件** 的 3D 游戏引擎编辑器。
目标：**小游戏 / 原型 / 教学**——开箱即用，编辑器友好，核心性能段 C 化。

---

## ✨ 特性

### 架构
- **5 大官方 C ABI DLL**（SHA256 钉扎）：
  - `ckernels` — AABB 归约 / SAP 碰撞对筛选 / collide_pairs 一体内核
  - `pipeline` — 光源 VP / 世界矩阵 / 姿态插值直出 / 材质桶打包 / 深度 DP
  - `script`  — C 原生批量自转/平移 + 嵌入式官方 **Lua 5.4.6**
  - `physics` — 重力 / 库仑阻尼 / 残速死带 / 多子步 C 闭环
  - `module_ref` — 契约脚手架与自愈参考靶
- **主循环彻底解耦**：逻辑推进（Fixed TPS）与渲染线程独立，调度精度稳定 1ms
- **13 个 mixin** 重构的 engine.py（Shadow / Physics / Render / Lighting / …）

### 渲染
- PBR 材质 / 法线贴图 / mipmap / LOD / cubemap / 纹理压缩
- 视锥剔除（实测剔 79%）、实例化批绘制、阴影 VP 静态缓存
- 可切换：PBR 全局开关、视锥剔除开关（排错后门，手动改 `设置.json`）

### 脚本
- 内嵌 Lua 5.4.6（C 侧高速执行，非 Python 反射）
- 官方示例：rotate / wasd_move / camera_follow / character_controller / door_trigger / jump_pad / patrol_ai / reset_fall
- 生命周期钩子：`on_enable` / `on_disable` / `on_destroy` / `on_collision_start/end/stay`

### 编辑器
- **LoomHub** 启动器（独立项目，本项目含其源码）
- 层级面板 / 属性检查器 / 视口 / 工具栏 / 状态栏
- 场景序列化（`sceneio.py`）、撤销系统（`undo.py`）、游戏打包（`build_game.py`）

### 自动化 / MCP
- **MCP 协议服务**（`loom_mcp.py`）：24 项 Unity 对齐工具 + 4 大 Resources
- **EAI 命令服务器**（`agent_commands.py`）：本地 HTTP + Token 鉴权

---

## 🚀 快速上手

### 环境
- Python 3.12
- Windows 10/11 x64（引擎当前以 Windows 为主）
- 推荐已编译的 5 个官方 DLL 放在 `Loom/core_components/`

### 安装依赖
```bash
py -3.12 -m pip install -r requirements.txt
```

### 从源码启动
```bash
cd Loom
py -3.12 Loom.py
```

### 通过 LoomHub 启动（多项目托管）
```bash
cd LoomHub
py -3.12 LoomHub.py
```

### 用 MCP 大模型驱动
```bash
cd Loom
py -3.12 Loom.py --agent
# 然后在 Claude Desktop / Cursor 里接入 loom_mcp.py
```

---

## 📁 仓库结构

```
.
├── Loom/                  ← 引擎主体（编辑器 + 运行时 + 核心组件桥接）
│   ├── core_components/   ← 5 大 C ABI DLL 源码 + 契约头 + registry.json
│   ├── ckernels/          ← 数值内核 C 源码 + 构建脚本
│   ├── ui/                ← PySide6 编辑器面板
│   ├── scripts/           ← 官方 Lua 示例脚本
│   ├── tests/             ← 单测 + 逐位对拍探针（永久固化）
│   └── 保存/压力测试/       ← 8 个压力场景（基准）
├── LoomHub/               ← 启动器（Hub 源码）
├── AI工作排查笔记/          ← 开发过程记录（脱敏公开，欢迎指教）
├── 代码架构.txt            ← 分层 / 数据模型 / 渲染管线 / 踩坑清单
├── 开发进度与Unity对照.txt   ← 与 Unity 逐项对照
├── 使用操作指南.txt
├── 未测试功能测试方向指南.txt
└── 现代游戏引擎设计.txt
```

---

## 🗺 路线图

- [x] 5 大 C ABI DLL 闭环 + SHA256 钉扎
- [x] 逻辑帧/渲染帧分离 + 常驻物理线程
- [x] 逃生门退役（B1~B7b：ckernels / pipeline / script / physics / SAP / 帧调度 / 渲染特性）
- [x] 脚本生命周期钩子（C1）
- [x] 内嵌哈希基准 + 启动自检（A1）
- [ ] 启动自检模块（A2）/ 开发模式开关（A3）
- [ ] 脚本执行顺序 / 通信 / 触发器 / 协程（C2~C7）
- [ ] 粒子 / 后处理 / 天空盒 / 骨骼动画 / 3D 音频 / 寻路（D 线）
- [ ] LoomHub 分发体系：自动更新 + 引擎一键安装 + 傻瓜式安装包
- [ ] 彻底移除绑死模式架构 / 平台质量分级预设系统
- [ ] GitHub Actions 自动构建 LoomHub 安装包 + 发布 Release

---

## 🤝 贡献

本项目**当前处于开发中**，欢迎任何形式的反馈：

- **设计讨论**：`docs/design/` 下是我们的白盒蓝图，欢迎在 Issues 里指教
- **开发过程**：`AI工作排查笔记/` + `docs/audit/` 摊开了我们从零到现在的完整思考过程
- **问题反馈**：请附上场景文件 / 复现步骤 / 系统信息

> 我们**诚挚欢迎**：架构批评、设计质疑、性能建议、命名讨论——任何能让我们把这台织布机做得更好的意见。

---

## 📜 许可

[MIT License](LICENSE)

---

## 💬 关于名字

**Loom**（织布机）→ **Weave**（编织）→ 把创意织成梦。
引擎的每一个设计决策，都是为了让"想做一个游戏"这件事，
变得像"拿起一块布"一样简单。

如果这个项目对你有启发，或者你觉得它还能更好，欢迎让我们知道。
