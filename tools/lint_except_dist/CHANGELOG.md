# Changelog

所有值得注意的变更都会记录在此文件。
格式参考 [Keep a Changelog](https://keepachangelog.com/)，遵循语义化版本。

## [0.1.1] — 2026-10-20

### 修复（外部审计报告 6 个 BUG + 2 个观察项）

**漏报类（最危险：该报的没报）**

- **BUG-01** `SENTINEL_KEYS` 含 `'ok'` / `'success'`：`except: return {'ok': True}`（出错却返回成功）被误判为已上报。
  修复：只认错误语义 key（`error` / `err` / `errors` / `failed`）。
- **BUG-02** `ast.Assign` 中含 `error` 子串的字符串被当上报：`except: msg = "error: ..."`（局部变量，没人读）被误判为已上报。
  修复：只认容器元素赋值（`out[k] = ...`），不认裸变量赋值（`msg = ...`）；同时收紧 `ERROR_STRING_HINTS`（去掉裸 `'error'`，改为 `'error:'`）。
- **BUG-04** 白名单过宽：`check` / `ensure` / `require` / `notify` 及裸前缀 `print(` / `log(` 导致误判。
  修复：移除上述条目；日志前缀细化为具体级别（`logger.error` / `logger.warning` / `logger.critical` / `logger.exception`），不认 `debug` / `info`。

**可用性**

- **BUG-03** CLI `iter_py_files` 只排除 `__pycache__`，不排除 `venv` / `.venv` / `node_modules`：首次使用扫描被第三方库淹没。
  修复：新增模块级 `EXCLUDE_DIRS`（与 `try_it.py` / `lint_exe_entry.py` 对齐）。

**噪音 / 文档一致性**

- **BUG-05** 静默吞错 + 宽异常在同一行报两条（ERROR + WARN）：用户修完 ERROR 后仍看到 WARN，误以为没修好。
  修复：宽异常提示合并进 ERROR 的 message，同一行只报一条。
- **BUG-06** 注释承诺「有 `_ignore_` 时宽异常降低为静默」，代码未实现，且与 README 判定表第 2 行冲突。
  修复：判定 3 增加 `ignore_reason is None` 条件——有 `_ignore_` 带理由时完全豁免（包括宽异常检查）。

**观察项**

- **OBS-01** `return True` 与 `return False` 不对称：`except: return True` 把失败包装成「成功」，与 `False` 同等危险。
  修复：`True` 也加入 `is_silent_default_literal`。
- **OBS-02** 白名单含死条目 `'sys'`；`stderr.write` 未被识别。
  修复：移除 `'sys'`；新增 `'stderr.write'` / `'stdout.write'`。

### 验证

- `regression_bugs.py`：6 个 BUG + 1 个观察项的回归测试（全部 PASS）
- `selftest.py`：原有 10 项 + 工具自检（全部 PASS）

### 设计说明

修复原则：**能从源码逻辑链证明「这个行为与文档承诺冲突」的才改**。
每一条修复都附带：源码证据 → 逻辑链 → 最小复现 → 预期（文档依据）→ 实际 → 验证命令。
详见 `regression_bugs.py` 的注释。

## [0.1.0] — 2026-10-20

### 首发

- 静态检查每个 `except` 分支是否显式表达了「已处理」或「故意忽略」意图
- 三档结果：`ERROR`（静默吞错）/ `WARN`（标记不完整 / 宽异常未声明）/ `PASS`
- 支持 13 种异常反馈方式识别（raise / print / 日志 / UI / return error 等）
- 支持两种显式标记：`# _ignore_, <理由>` / `# _broad_, <理由>`
- 一行可同时写两个标记（如 `# _ignore_, a  # _broad_, b`）
- `--json` / `--summary` / `--strict-return` / `--no-broad` / `--warn-as-error` 选项
- `selftest.py`：工具自检 + 5 个示例验证（全部通过）

### 设计决策

- **为什么 `return None` 算 ERROR**：从 Rust 视角看，`except: return None` 丢失了所有错误信息，
  调用方无法区分「真的没有数据」和「出错了」。这正是本工具要抓的静默失败。
  `return {"error": ...}` 或 `return some_var` 才算已处理。
- **为什么宽异常要额外声明 `_broad_`**：`except Exception` 是 Python 里最常见的「一把梭」写法，
  但 Rust 的 `match` 强制穷尽所有错误类型。我们用 `_broad_, <理由>` 让作者显式承认
  「这里必须宽兜底」——比如用户回调、插件执行。
- **为什么标记用注释而不是装饰器**：注释不改变运行时行为，零侵入；装饰器需要改函数签名，
  对已有代码改造量太大。代价是注释不参与编译，需要 linter 保障。

### 真实项目验证

在 Loom 引擎（74 个文件 / 约 4 万行 Python）上实测：
- 296 处 `except` 缺少显式声明（原代码没有任何 `_ignore_` / `_broad_` 标记）
- 工具自身 0 ERROR / 0 WARN（自检闭环通过）
- 抽样 25 处人工核对，**零误报**

### 已知限制

- 只检查 `except` 语句，不检查「忘了写 try」
- 不检查 `with` 的 `__exit__` 抑制异常
- 不检查函数返回类型的错误约定（Go 的 `(T, error)` 风格）
- 宽异常检查可关闭（`--no-broad`），因为部分项目风格偏好宽 `except`

### 计划

- [ ] 支持 `finally` 分支的「清理失败」检查
- [ ] 支持自定义上报白名单（配置文件）
- [ ] 移植到 Go / JS（同一套规则，换 AST 解析器）
