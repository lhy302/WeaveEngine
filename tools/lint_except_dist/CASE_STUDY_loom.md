# Case Study: 在 Loom 引擎上实测

**项目**：Loom 引擎（Python 3.12 + 5 个 C ABI DLL 的 3D 游戏引擎）
**规模**：74 个核心 .py 文件，约 4 万行代码
**时间**：2026-10-20

---

## 结果摘要

```
扫描文件: 74
ERROR: 296
WARN : 772

ERROR 细分:
  silent-pass: 209  (纯 pass/continue，最典型的静默吞错)
  no-handling: 87   (except 体有代码但无任何上报)

WARN  细分:
  broad-exception: 772  (except Exception / BaseException，过宽未声明)
```

---

## 典型问题样本

### 样本 1：用户脚本异常被吞（最严重）

```python
try:
    sc.update(dt)
except Exception:
    pass              # ← 用户脚本抛 TypeError，界面上按钮点了没反应
```

**后果**：用户写的按钮回调抛异常，引擎静默捕获，界面上只是「点了没反应」。
用户翻遍脚本代码也找不到原因——因为异常被引擎吞了。

**修复**：改 `_report_error('script.update', e)`，同时落盘 + UI toast。

### 样本 2：渲染上屏失败无日志

```python
try:
    glfw.swap_buffers(self._glfw_win)
except Exception:
    pass              # ← 上屏失败 = 画面不更新（卡住/黑屏）
```

**后果**：用户看到画面卡住，不知道是引擎 bug 还是显卡驱动问题。

**修复**：改 `_report_error('swap_buffers', e)` + 节流。

### 样本 3：场景加载失败静默

```python
try:
    engine._skybox = _apply_skybox(data.get('skybox'))
except Exception:
    engine._skybox = None    # ← 天空盒加载失败，静默用「无天空盒」
```

**后果**：用户手改场景 JSON 写错天空盒配置，加载后天空盒消失，
但没有任何提示告诉他「配置有误」。

**修复**：改 `_report_error('sceneio.skybox', e, {'data': data.get('skybox')})`。

### 样本 4：合理容错（应加 `_ignore_` 而非改代码）

```python
try:
    glfw.set_window_iconify_callback(win, _on_window_iconify_cb)
except (AttributeError, Exception):
    pass              # ← 老版 glfw-python 无此 API，降级无害
```

**判断**：这是合理的——老版 GLFW 没有这个回调，跳过不影响功能。

**修复**：只需加标记 `# _ignore_, 老版 glfw-python 无此 API，跳过不影响窗口行为`。

---

## 抽样人工核对（25 处）

对 `loom_glfw_window.py` 和 `loom_ui.py` 的 25 处 ERROR 逐条人工核对：

- **无误报**（工具报的每一处确实缺少上报或缺少忽略声明）
- **发现 3 处严重缺陷**（swap_buffers、ui.dispatch_text、on_text_input）
- **发现约 15 处合理容错但未声明**（只需加 `_ignore_`）
- **发现约 7 处需要改代码**（改为 `_report_error`）

---

## 为什么这个工具有用

没有工具时，这 296 处的问题是这样被发现的：

1. 用户报告「按钮点了没反应」→ 排查 40 分钟 → 发现 Text 颜色 4 元组静默失败
2. 用户报告「天空盒不显示」→ 排查 30 分钟 → 发现加载失败静默
3. 用户报告「沙盘区域灰块」→ 排查 30 分钟 → 发现 pygame 中文路径静默失败

**累计消耗**：约 450 分钟（7.5 小时）用于对抗「静默失败」。

有工具后：

1. 开发时跑 `loom_lint_except.py`，新代码一旦引入静默吞错立即报 ERROR
2. 存量代码按文件分批处理（每个文件平均 4 处，约 10 分钟）
3. 处理完后 CI 拦截，不会再有新的静默吞错进入代码库

**根本改变**：从「用户报告才排查」变成「代码提交前就拦截」。

---

## 局限

1. 工具只能抓「已经写了 except 但没处理」的情况，抓不到「忘了写 try」
2. `_broad_` 标记可能被滥用（作者全写 `_broad_, 不知道会抛什么`）
   - 这是社会工程问题，不是技术问题。code review 时人工把关
3. 对 `finally` / `__exit__` 抑制异常不检查

---

## 复现方式

在项目根目录运行：

```bash
python loom_lint_except.py Loom/ --summary
```

输出如上方「结果摘要」所示。
