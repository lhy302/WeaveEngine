# LoomHub 0.1.3（内测）

> 注：本文是**下一次发包**（0.1.3）的发布说明草案。开发期代码版本号仍是上一个已发布版本，发包时才跳。

> 本轮**不发布**：只备好版本号/安装器/发布说明，禁止建 tag、建 Release、上传资产。

## 重点

### 1. 远程模式默认关闭（H1，性能）
以前 LoomHub 无条件给引擎注入 `LOOM_REMOTE_MODE=1`（离屏 GL 渲染 + QImage 回读兜底）。
同一场景同一引擎的现场 A/B：

| 模式 | FPS | TPS | GPU |
|---|---|---|---|
| 直连（默认） | 55 / 59 / 61 | 23.7 | 34% |
| remote-mode | 38 / 38 / 41 | 18.9 | 31% |

现在改为设置项 `remote_mode`（`off|auto|on`，**默认 off**），设置面板底部有可见开关与说明
「离屏回读兜底，会明显降低帧率」。`on` 留给确实白屏的机器；`auto` 预留给引擎侧自动降级（beta5 E2）。
两条启动路径（GUI 双击打开项目 / EAI 命令 launch_engine）共用同一实现，不再各自为政。

### 2. 自更新（H2）
- 检查：后台线程、延迟约 10s、24h 最多一次；筛 `hub-v*`；失败静默
- 下载：`LoomHub-<ver>-Setup.exe` → `%LOCALAPPDATA%\Loom\hub\updates\`；校验 size，有 `digest` 则校验 sha256；非 https 拒绝
- 安装：写 `updates\apply_update.cmd`（等当前 PID 退出 → `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS /SP-`），`runas` 弹一次 UAC
- 提交后 Hub **主动退出**（暂时关闭）；安装器静默模式不跑 postinstall；updater **不**再拉起 LoomHub
- 任一环节失败写 `updates\update.log`，下次启动提示

### 3. 台账重识别
启动时按各安装目录里的 `解释器.json` 重新识别引擎（引擎被原地替换成编译版后不再显示旧版本号）。

### 4. 配置目录
Hub 的设置与解释器/项目台账统一落 `%LOCALAPPDATA%\Loom\hub\`（程序目录只读也能保存），
首次运行自动迁移旧文件，旧文件保留不动。

## 安装
下载 `LoomHub-0.1.3-Setup.exe`，双击安装；卸载时可选择是否一并删除用户配置（默认保留）。
