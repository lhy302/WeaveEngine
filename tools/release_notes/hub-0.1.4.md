# LoomHub 0.1.4（内测 · 草稿）

## 一、安装根可自由选、持久化

- 安装解释器时可选**任意安装根**（默认 `C:\Program Files\Loom`）；选择写入 `hub_settings.install_root` 持久化，
  下次启动沿用。
- 安装失败给 **权限归类**：`PermissionError / winerror 5` → 明确提示"需要管理员，或点【改安装根】切到用户目录"，
  不再是一句笼统的"安装失败"。

## 二、扫描覆盖用户目录

- 启动扫描**合并所有安装根**（Program Files + 用户目录 + 当前根），去重后登记；
  用户级安装（非管理员）同样能被自动发现。

## 三、安全与可审计

- 安装根写入前做可写性检测（`root_writable`），不可写自动回落到用户目录并提示；
- 版本号仍以 `LoomHub/版本.json` 为唯一真源，安装器 `MyAppVersion` 与之一致。

## 四、LoomHub.exe 版本资源（P3）

- 产物 exe 现在带 `ProductVersion/FileVersion`（PyInstaller `--version-file`），
  属性页可查；构建后断言资源存在，缺则打包失败。

## 五、本次交付数字（2026-11-13 重打）

| 产物 | 字节 | 显示大小 | sha256 |
|---|---|---|---|
| `LoomHub-0.1.4-Setup.exe` | 25 539 782 | 24.36 MB | `960f0e4023dbb19a5d72cef75f5129ec51c0fffca44214669e98a5dcae5a35be` |

- 安装包内 `LoomHub.exe` = **6.36 MB**（6 671 167 B），构建期断言 `ProductVersion/FileVersion = 0.1.4` 通过；
  Inno Setup 7 编译成功（`Successful compile (17.781 sec)`）。
- 与引擎同批同 HEAD 产出：本 Hub 配套引擎 `0.1.0.beta6`，引擎 `git_head=2e69b38110b8a42f156a1094928e440477ac407e`
  （compiled `132.78 MB` / source `342.10 MB`，数字见 `engine-0.1.0.beta6.md` §七）。
  Hub 自身是 PyInstaller/Inno 产物、不含引擎源码，故**没有**独立的 `git_head` 字段，版本真源仍是 `LoomHub/版本.json`。
- 本文**不含**像素门 MAE：MAE 是引擎渲染语义指标，记在 `engine-0.1.0.beta6.md` §五
  （23 场景三向最大 6.6e-5，UI 1.10e-4）。

## 六、发布命令（**未执行**，等人类裁决后统一跑）

```bat
set LOOM_HUB_VERSION=0.1.4
py -3.13 tools/package_hub.py
py -3.13 tools/release_github.py hub
```

## 七、安装安全提示（通用，不只某一家安全软件）

在 Program Files 安装时，安全软件会提示「修改配置」与「写入 DLL」，属正常安装行为，请允许。

原因：在关键目录写入疑似系统 DLL 是**几乎所有安全软件**都可能拦的操作，不只某一家。

LoomHub 装引擎时的默认安装根改为**跟随 Hub 自身安装位置**推荐，避免在用户级安装时
却把运行库写进系统程序目录；用户仍可在安装对话框里自选（系统目录 / 用户目录 / 手输 / 浏览）。
