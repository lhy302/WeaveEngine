# loom_lint_except — Python 异常处理契约检查

**一句话**：让每个 `except` 分支显式声明"我处理了"或"我故意忽略"，模拟 Rust 的强制错误处理。

> **新手请先看 [如何使用.md](如何使用.md)** —— 面向没用过的人，从"它解决什么问题"讲起，含完整示例。  
> 本 README 偏技术说明（设计理念、判定规则、反馈方式清单）。

---

## 它解决什么问题

```python
try:
    data = json.loads(text)
except Exception:
    pass          # ← 静默吞错：出错了没人知道
```

Python 没有类型系统强制你处理错误。`except: pass` 是开发者的默认惰性选择，
结果是：功能没生效、数据丢了、脚本炸了，但**没有任何地方告诉你**。

Rust 用 `Result<T, E>` + `?` 强制每个错误被处理。本工具用**静态分析**模拟同样的约束：

**每个 `except` 分支必须二选一**：
1. **上报**：`raise` / `print` / 日志 / UI 提示 / `return {'error': ...}`
2. **显式忽略**：`# _ignore_, <为什么可以忽略>`

都没有 → `ERROR`（模拟 Rust 编译错误）。

---

## 30 秒上手（零门槛）

**Windows 用户，不想装 Python**：把 `loom-lint-except.exe` 复制到你的项目目录，双击。

**Windows 用户，有 Python**：双击目录里的 `try_it.bat`，看效果。

**命令行 / macOS / Linux**：

```bash
# 1. 解压后进入目录
cd loom-lint-except-0.1.0

# 2. 一键试用（自动扫描当前目录；空目录则演示 examples/）
python try_it.py

# 3. 想扫你自己的项目？把 `try_it.py` + `loom_lint_except.py` 复制到项目根目录，再运行
```

**输出说明**：

- `ERROR`：静默吞错，必须修（except 体没 raise、没日志、没返回错误、也没 `_ignore_` 标记）
- `WARN`：有标记但缺理由 / 过宽异常类型（`except Exception`）未声明 `_broad_`
- 退出码：`0` 通过，`1` 有 ERROR，`2` 有 WARN（配 `--warn-as-error`）

**想直接看完整报告**：

```bash
python loom_lint_except.py 你的项目路径/
```

---

## 标记协议

```python
# 方案 1：上报（E1-E12 任意一种）
try:
    load_config()
except FileNotFoundError as e:
    print('配置缺失，用默认值: %r' % e)   # ← E2 已上报

# 方案 2：显式忽略（必须写理由）
try:
    ctx.viewport = (0, 0, w, h)
except Exception:
    pass  # _ignore_, GL 上下文未就绪时设置视口无效，下一帧会重试

# 方案 3：宽异常兜底（需额外声明）
try:
    user_script.update(dt)
except Exception as e:  # _broad_, 用户脚本可能抛任意异常，必须兜住防止整个引擎崩溃
    report_error('script.update', e)
```

**规则**（0.1.1 更新，与 BUG-06 修复对齐）：
| 有上报 | `_ignore_` 带理由 | 宽异常 | 有 `_broad_` | 结果 |
|---|---|---|---|---|
| 是 | — | 否 | — | PASS |
| 是 | — | 是 | 有 | PASS |
| 是 | — | 是 | 无 | WARN（宽异常未声明）|
| 否 | 是 | 否 / 是 | — | PASS（`_ignore_` 完全豁免）|
| 否 | 无理由 | 否 / 是 | — | WARN（标记缺理由）|
| 否 | 无 | 否 | — | ERROR |
| 否 | 无 | 是 | — | ERROR（宽异常提示合并进 message，不额外报 WARN）|

> **注**：`except Exception: pass  # _ignore_, <理由>` → 完全 PASS（0 ERROR / 0 WARN）。
> 因为用户已用 `_ignore_` 显式声明「忽略」，再要求 `_broad_` 是重复约束。

---

## 异常反馈方式清单（判定基准）

| 编号 | 方式 | 场景 |
|---|---|---|
| E1 | `raise` | 不可恢复、需上层决策 |
| E2 | `print(...)` | 开发期诊断 |
| E3 | `print(..., file=sys.stderr)` | 与正常输出区分 |
| E4 | `logging.*` | 结构化日志 |
| E5 | `warnings.warn` | 弃用/不推荐路径 |
| E6 | `traceback.print_exc()` | 未知异常兜底 |
| E7 | `_report_error(...)` | 引擎统一通道 |
| E8 | UI toast / 状态栏 | 用户可见交互错误 |
| E9 | 写日志文件 | 无控制台环境 |
| E10 | `return {'error': ...}` | 调用方判断（EAI/MCP）|
| E11 | `crash_reporter` | 崩溃转储 |
| E12 | `assert` / 硬错 | 编程错误（契约级）|
| E13 | `# _ignore_, <理由>` | 显式忽略（本工具标记）|

E1–E12 = 已处理；E13 = 显式忽略；都没有 = 静默吞错。

---

## 为什么这套范式能推广到其他语言

核心逻辑三层，与语言无关：

1. **"上报"白名单**：该语言里所有"把错误告知外部"的 API
   - Rust: `eprintln!` / `log::error!` / `panic!`
   - Go: `log.Fatal` / `fmt.Fprintf(os.Stderr, ...)`
   - JS/TS: `console.error` / `logger.error` / `throw`
   - Java: `logger.error` / `throw new XxxException`
2. **"显式忽略"标记**：固定的注释协议（`# _ignore_,` / `// _ignore_,` / `/* _ignore_, */`）
3. **静态分析**：AST + tokenize（Rust: syn，JS: babel，Java: javac API）

换语言只需要换这三样。**本质是把"作者心里的意图"变成"代码里可检查的声明"** ——
这正是 Rust 类型系统做的事，只是我们用注释 + linter 来模拟。

---

## 完整用法

```bash
# 基本用法
python loom_lint_except.py                   # 检查当前目录
python loom_lint_except.py src/ lib/         # 检查指定目录
python loom_lint_except.py --summary         # 只看统计
python loom_lint_except.py --json            # JSON 输出（CI 用）

# 严格模式
python loom_lint_except.py --warn-as-error   # WARN 也当 ERROR（退出码 2）
python loom_lint_except.py --strict-return   # return None 也算未处理
python loom_lint_except.py --no-broad        # 关闭"过宽异常"检查
```

### 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 全部通过 |
| `1` | 有 ERROR |
| `2` | 有 WARN 且加了 `--warn-as-error` |

### 自检与回归（改工具后必须跑）

```bash
python selftest.py          # 工具自身 + 5 个示例自检
python regression_bugs.py   # 审计报告 6 BUG + 2 观察项回归（0.1.1 新增）
```

两个脚本退出码 0 = 全部通过。`regression_bugs.py` 每个用例的注释写明「修复前行为 → 修复后行为」，可对照源码逻辑链审计。

---

## 期望你反馈什么

我在引擎代码上实测了这套规则，想请你帮忙在**你自己的 Python 项目**上试用，告诉我：

### 1. 误报（不该报但报了）
- 哪一行？
- 你用了什么上报方式没被识别？（贴代码，我加白名单）

### 2. 漏报（该报但没报）
- 哪一行？
- 你见过什么"静默吞错"的写法本工具抓不到？

### 3. 标记协议是否好用
- `# _ignore_, <理由>` 的语法是否自然？
- 一行里同时写 `_ignore_` 和 `_broad_` 会不会太长？

### 4. 其他语言推广
- 你在 Go / JS / Rust / Java 里遇到过类似问题吗？
- 如果这套范式移植到你的主语言，你希望标记长什么样？

---

## 目录结构

```
loom-lint-except/
├── loom_lint_except.py     # 工具本体（单文件，零依赖）
├── README.md               # 本文件
├── examples/               # 示例：每个文件演示一类问题
│   ├── 01_silent_pass.py
│   ├── 02_wrong_marker.py
│   ├── 03_good_reporting.py
│   ├── 04_broad_exception.py
│   └── 05_real_world.py
└── selftest.py             # 自检：工具检查自己 + 示例应当报出预期数量
```

---

## 已知限制

1. **只检查 `except` 语句**，不检查"忘了写 try"的情况
2. **不检查 `finally` / `else` 分支**（这两个分支不处理错误，只做清理）
3. **不检查 `with` 语句的 `__exit__` 抑制异常**（`__exit__` 返回 True 会吞掉异常，本工具目前不管）
4. **不看函数返回类型的错误约定**（如 Go 的 `(T, error)` 返回模式）
5. **宽异常检查可关闭**（`--no-broad`），因为某些项目风格偏好 `except Exception`

---

## 许可

MIT
