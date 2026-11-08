# LoomHub 0.1.2 — 本版要点

- **设置与台账迁到用户目录**：`设置.json`、`interpreters.json`、`projects.json` 改存 `%LOCALAPPDATA%\Loom\hub\`，装到 `C:\Program Files\LoomHub` 也能正常保存；首次启动自动迁移旧文件（旧文件保留不动）
- **覆盖安装更干净**：安装器先清 `_internal/`，避免 PyInstaller 旧残留混进新版本（实测 0.1.1→0.1.2 曾残留旧台账）
- **卸载可选删配置**：卸载时询问是否同时删除用户配置，默认**保留**
- **打开项目仍自动启用 Agent 通道**（`--agent`），且改为由调用方显式添加，避免命令行出现两个 `--agent`