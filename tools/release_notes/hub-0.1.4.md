# LoomHub 0.1.4

配套引擎：**Loom 0.1.0.beta6**（`git_head=3946f8f`）。本版为 Hub 的正式发布（引擎侧为 prerelease）。

## 一、引擎默认安装根：跟随 LoomHub 自身位置推荐（本版核心改动）

装引擎时的**默认安装根不再写死** `C:\Program Files\Loom`，而是按 LoomHub 自身安装位置推荐：

| LoomHub 装在哪 | 判定 | 推荐引擎安装根 |
|---|---|---|
| `C:\Program Files\LoomHub`（管理员安装） | system | `C:\Program Files\Loom` |
| `%LOCALAPPDATA%\Programs\LoomHub`（用户安装） | user | `%LOCALAPPDATA%\Programs\Loom` |
| 其它位置（例如解压在 D 盘） | portable | `%LOCALAPPDATA%\Programs\Loom` |

- 逻辑：Hub 能在 Program Files 说明这次安装拿到了管理员权限，那引擎装 Program Files 是一致的；Hub 在用户目录说明没提权，就别逼用户提权。
- 推荐位置不可写时自动退回另一个（装得下去优先于口味）。

## 二、安装根仍可自由选，且白名单不放松

- 安装对话框里可以**手输路径 / 浏览选择**，另有两个快捷按钮：`系统目录` / `用户目录`；
- 白名单仍是 `Program Files\Loom` / `%LOCALAPPDATA%` / `%USERPROFILE%` 之下，域外路径直接拒绝；
- 安装失败给**权限归类**：`PermissionError / winerror 5` → 明确提示「需要管理员，或点【改安装根】切到用户目录」。

## 三、安装对话框与主窗口的 GUI 修复

- **长路径不再撑坏布局**：目录类文本改为**定长显示 + 中间省略（middle ellipsis）**，鼠标悬停用浮窗（overflow tooltip）显示完整路径，**点击可复制**；主窗口「默认安装根」与安装对话框的路径提示都走这条规则；
- **按钮不再被挤掉**：安装对话框加高（640×620，minsize 640×560），按钮栏改为**钉底**（先于内容 pack）；
- 提示文案里的路径先省略再拼接，避免多折几行把按钮顶出可视区。

## 四、扫描覆盖用户目录

- 启动扫描合并所有安装根（Program Files + 用户目录 + 当前根），去重后登记；用户级安装（非管理员）同样能被自动发现。

## 五、安全与可审计

- 安装根写入前做可写性检测（`root_writable`），不可写自动回落并提示；
- 版本号仍以 `LoomHub/版本.json` 为唯一真源，安装器 `MyAppVersion` 与之一致；
- 产物 exe 带 `ProductVersion/FileVersion`（PyInstaller `--version-file`），构建后断言资源存在，缺则打包失败。

## 六、安装安全提示（通用，不只某一家安全软件）

在 Program Files 安装时，安全软件会提示「修改配置」与「写入 DLL」，属正常安装行为，请允许。

原因：在关键目录写入疑似系统 DLL 是**几乎所有安全软件**都可能拦的操作，不只某一家。
（实测即使装到 `%LOCALAPPDATA%\Programs`，部分安全软件仍会提示——那属于「向程序目录写 DLL」这一通用判定，无法通过换路径消除。）

## 七、本次交付数字（2026-11-13）

| 产物 | 字节 | 显示大小 | sha256 |
|---|---|---|---|
| `LoomHub-0.1.4-Setup.exe` | 25 546 396 | 24.36 MB | `e84399bb03d0446f55a9abf83b435add5a64609e709a434f27a57540d6899436` |

- 安装包内 `LoomHub.exe` = 6 671 167 B，构建期断言 `ProductVersion/FileVersion = 0.1.4` 通过；Inno Setup 7 编译成功。
- Hub 是 PyInstaller/Inno 产物、不含引擎源码，故**没有**独立 `git_head`；版本真源是 `LoomHub/版本.json`。
- 配套引擎包：compiled `145 284 153` B / sha256 `ed2b3531…`，source `358 725 022` B / sha256 `605012b8…`，引擎 `git_head=3946f8f`，26 场景像素门与 136 测试全绿（详见 `engine-0.1.0.beta6.md`）。

## 八、发布记录

- tag：`hub-v0.1.4`（与 `engine-v0.1.0.beta6` 同指 `74f8535`）
- Release：<https://github.com/lhy302/WeaveEngine/releases/tag/hub-v0.1.4>
- 发布门：`tools/release_github.py hub` 默认先跑全套 `run_all`（136 个），非零即中止且零远端写操作（本次 EXIT=0）。
