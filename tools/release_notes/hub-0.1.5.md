# LoomHub 0.1.5（正式版）

LoomHub 是 Loom 引擎的版本管理器（安装/切换引擎解释器、增量更新、按版本启停）。本版只修一个会直接影响安装行为的缺陷，其余为测试门自证修复。

## 一、本版实质改动

### 1）Program Files 判定的 fail-open 修复（Q-B7-29-1）

- **现象**：安装在 `C:\Program Files` 下时，Hub 有时**不加** `/ALLUSERS`、也**不触发** UAC 提权，装到一半权限失败或装到错误的用户上下文。
- **根因**：`hub_update.is_program_files()` 只读 `ProgramFiles` 系环境变量，然后直接 `abspath` 比较。环境变量缺失（精简环境、服务上下文、某些安装器子进程）时，它静默返回 False —— 典型的 fail-open。
- **修法**（`LoomHub/hub_update.py`）：
  - 三个环境变量都认：`ProgramFiles` / `ProgramFiles(x86)` / `ProgramW6432`；**缺失时用 `SystemDrive` 下的标准目录兜底**（不再 fail-open）；
  - 统一规范化后再比较：引号、首尾空白、正斜杠、尾部分隔符、大小写、`%VAR%` 未展开、8.3 短名（`C:\PROGRA~1` → 长名）；
  - 前缀匹配带路径分隔符边界，`C:\Program FilesX` 不会被误判成 Program Files。
- 影响面：装到 Program Files 时 **`/ALLUSERS` 与 UAC 提权行为恢复正确**；用户目录/便携目录安装行为不变。

### 2）测试「假绿」门封堵（同批，保证上面这条真能被门测到）

- 旧行为：测试里非守护 Timer 调 `os._exit(0)` 会绕过 `atexit` 与 `sys.exit`，于是测试打印了 FAIL 却以退出码 0 收场（假绿）。
- 现在：门带 FAIL 监视 + `_exit(1)` 双保险，注入失败时**确实非零退出**（`test_hub_update` 扩到 106 条，含「注入 FAIL 后进程退出码非零」「子进程 stdout 确有 FAIL 行」两条自检）。

## 二、兼容性

- Hub 版本 `0.1.5` 是正式版（非 prerelease），0.1.4 → 0.1.5 **直接覆盖安装**即可。
- 引擎侧配套版本：`0.1.0.beta7`（引擎 Release 与本版同日发布）。
- 本版不改 Hub 的数据格式、引擎解释器登记方式、增量更新拼装逻辑。

## 三、本次交付包

| 产物 | 字节 | 显示大小 | sha256 |
|---|---|---|---|
| `LoomHub-0.1.5-Setup.exe` | 25668225 | 24.48 MB | `516516fc9c3eaac80fafc36ab33fdf566338e6722e2ed106d879e32902ca3de6` |

- 打包：PyInstaller 出 `LoomHub.exe` 6.48 MB（版本资源 `ProductVersion/FileVersion = 0.1.5`）+ Inno Setup 出安装包 24.48 MB。
- 版本真源：`LoomHub/版本.json` = `0.1.5`（打包器与发布器共用这一处，不另设字面值）。

## 四、发布记录

- tag：`hub-v0.1.5`；Release 标记：正式版（`prerelease=False`）。
- 发布门：`tools/release_github.py hub` 默认先跑全套回归（`Loom/tests/run_all.py`，本版 179 个文件），非零即中止且零远端写操作。

## 五、安装安全提示（通用）

在 Program Files 安装时，安全软件会提示「修改配置」与「写入 DLL」，属正常安装行为，请允许。
原因：在关键目录写入疑似系统 DLL 是**几乎所有安全软件**都可能拦的操作，不只某一家。