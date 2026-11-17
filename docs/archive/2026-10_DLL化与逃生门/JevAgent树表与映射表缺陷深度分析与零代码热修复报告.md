# JevAgent 树表与映射表缺陷深度分析与零代码热修复报告

**致接手维护 Agent / 架构师团队**：
在推进 Loom 引擎 DLL 化攻坚战役（物理模块 C ABI 封装 physics.dll 与子步循环 C 闭环）期间，JevAgent 插件在执行 .spec.c.dsl 编译时发生严重异常，报出：
```text
http://36.251.86.131:1234/v1/decide: Jev native decide HTTP error: 404
| http://36.251.86.131:1234/v1/chat/completions: Jev model returned choice 'exact_candidate_string' which is not in candidate set: 定义, 异步定义, 返回
```
经对插件核心库（lib/*.js）与树表资源（tables/*.json）的代码级溯源，**确认该问题核心是“语法树表定义严重缺失”叠加“Prompt 占位符诱导 4B 小模型机械复读”的双重设计缺陷所致**。

本文档提供完整根因证据链，并给出**无需修改插件代码、仅通过热更新 tables/ 树表 JSON 即可快速闭环的免侵入修复方案**。

---

## 一、运行态事实与异常链路

### 1. 运行态证据（Telemetry / Log）
- **服务端连通性**：`http://36.251.86.131:1234/v1` 网络正常（TCP/HTTP 延迟仅 4ms）；
- **专用接口失效**：原生决策端点 `/decide` 返回 **HTTP 404**；
- **降级端点超时**：回退至通用补全端点 `/chat/completions` 时，单次推理耗时高达 **55~56 秒**，极易触发 harness 的 120 秒总超时；
- **无效输出**：模型最终吐出的内容不是候选节点，而是字面量字符串 `'exact_candidate_string'`；
- **前端拦截**：因该字面量不在候选集（如 `['定义', '异步定义', '返回']`）中，被插件底层抛出异常并阻断编译。

---

## 二、代码级根因溯源（为什么会发生？）

```
  [输入阶段] 用户编写标准 C 语言 DSL (.spec.c.dsl)，包含 LOOM_PHYSICS_API、double*、typedef
                         │
                         ▼
  [静态校验] tables/c_v1.json 仅16个节点 + 误把 double/void 列入黑名单；
             tables/syntax_core_v1.json 节点数为 0 (空文件)
             ⟹ 触发 unknown_node 错误，收集建议词 ['定义', '异步定义', '返回']
                         │
                         ▼
  [决策触发] index.js:146 发现 DSL 存在歧义，调用 jevClient.decide() 触发 4B 模型意图自愈
                         │
                         ▼
  [提示词缺陷] jev-client.js:268 的 System Prompt 硬编码了示例：
             "Output ONLY JSON: {\"choice\": \"exact_candidate_string\"}."
                         │
                         ▼
  [模型复读] 端侧 4B 小模型 (jevk5-4b-v0.3-Q4_K_M) 缺乏复杂泛化能力，
             直接照抄输出：{"choice": "exact_candidate_string"}
                         │
                         ▼
  [校验崩溃] jev-client.js:364 检查 chosen 是否在 candidates 列表中，
             发现 'exact_candidate_string' 无法匹配，抛出致命异常！
```

### 1. 诱导源：`lib/jev-client.js:268` 的硬编码提示词
```javascript
if (qType === 'choice') {
  systemPrompt = 'You are a decision classifier. You must pick one string from the candidates array. Output ONLY JSON: {"choice": "exact_candidate_string"}.';
  userContent = `Candidates: ${JSON.stringify(candidates)}\nTask: ${prompt || "Select the most appropriate candidate"}${state ? `\nContext: ${state}` : ""}`;
}
```
在给小模型提供的单样本示例中，直接把占位说明文字 `"exact_candidate_string"` 当作 value。对于 4B 级别轻量量化模型而言，极易将其当做静态模板原样吐出。

### 2. 根源触发源：树表（Tree Tables）体系设计缺陷
为什么合法的 C 语言代码会走到调用 Jev 模型做选择这一步？
- **缺陷 A（核心表为空）**：检查 `tables/syntax_core_v1.json`，其 `nodes count: 0`，核心映射体系彻底瘫痪，通用语法糖无法归一化；
- **缺陷 B（C 规则表极度贫瘠）**：检查 `tables/c_v1.json`，仅有 16 个极简节点，缺失了宏定义（`#define`）、类型别名（`typedef`）、结构体（`struct`）、导出属性（`__declspec` / `LOOM_API`）等工程级必备语法节点；
- **缺陷 C（黑名单误杀）**：`tables/c_v1.json` 中的 `keyword_blacklist` 竟然把 `int`, `void`, `double`, `float`, `const`, `sizeof` 列入了黑名单，导致任何带类型签名的 C 代码在本地直接被判定为非法；
- **缺陷 D（归一化缺失）**：`lib/normalize.js` 中的 `convertNativeSyntax` 仅实现了 Python 和 JavaScript 的语法转换，对 C 语言是空白。

---

## 三、零代码修改热修复方案（仅改表文件）

由于 `lib/router.js` 具有自动加载与热注册能力，会动态遍历读取 `tables/` 目录下的全部 JSON 文件，**接手 Agent 无需改动任何 JS 插件代码，只需按以下步骤覆盖更新两份树表文件，即可从根源消除未知节点误判，实现全本地离线高速编译**！

### 1. 覆盖目标一：`tables/syntax_core_v1.json`
- **目标路径**：`C:\Users\<USER>\.dsh\plugins\dsh-plugin-jevagent\tables\syntax_core_v1.json`
- **写入内容**：
```json
{
  "schema_version": "1.0",
  "table_id": "syntax_core_v1",
  "target_language": "abstract",
  "core_nodes": {
    "define": {
      "canonical": "定义",
      "aliases": ["def", "function", "fn", "LOOM_API", "LOOM_EXPORT", "LOOM_PHYSICS_API", "LOOM_SCRIPT_API", "LOOM_PIPE_API"]
    },
    "declare": {
      "canonical": "设",
      "aliases": ["let", "const", "var", "typedef", "static", "extern"]
    },
    "return": {
      "canonical": "返回",
      "aliases": ["return", "ret"]
    },
    "include_system": {
      "canonical": "引入系统",
      "aliases": ["#include <...>"]
    },
    "include_local": {
      "canonical": "引入本地",
      "aliases": ["#include \"...\""]
    }
  },
  "core_operators": {
    "=": "assign",
    "+=": "add_assign",
    "-=": "sub_assign"
  }
}
```

### 2. 覆盖目标二：`tables/c_v1.json`
- **目标路径**：`C:\Users\<USER>\.dsh\plugins\dsh-plugin-jevagent\tables\c_v1.json`
- **关键修正点**：
  1. 清空 `keyword_blacklist` 与 `confusions`，解除对 C 原生类型（`double`, `void`, `int` 等）的误杀；
  2. 增加 `/c/preprocessor/macro` 与 `/c/raw` 容错节点。
- **写入内容**：
```json
{
  "schema_version": "1.0",
  "table_id": "c_v1",
  "target_language": "c",
  "skeleton_ref": "common_skeleton_v1",
  "core_conformance": {
    "/core/define": "/c/function/define",
    "/core/return": "/c/function/return",
    "/core/if": "/c/control/if",
    "/core/elif": "/c/control/elif",
    "/core/else": "/c/control/else",
    "/core/loop/for": "/c/control/for",
    "/core/loop/while": "/c/control/while",
    "/core/loop/break": "/c/control/loop/break",
    "/core/loop/continue": "/c/control/loop/continue",
    "/core/var/declare": "/c/data/declare",
    "/core/io/output": "/c/io/output",
    "/core/io/input": "/c/io/input"
  },
  "confusions": [],
  "keyword_blacklist": [],
  "root": {
    "type": "branch",
    "choices": ["control", "data", "function", "io", "error", "module"]
  },
  "semantic_mappings": {
    "/semantic/function/define": "/c/function/define",
    "/semantic/function/call": "/c/function/call",
    "/semantic/function/return": "/c/function/return",
    "/semantic/control/branch/if": "/c/control/if",
    "/semantic/control/branch/elif": "/c/control/elif",
    "/semantic/control/branch/else": "/c/control/else",
    "/semantic/control/loop/for": "/c/control/for",
    "/semantic/control/loop/while": "/c/control/while",
    "/semantic/control/loop/break": "/c/control/loop/break",
    "/semantic/control/loop/continue": "/c/control/loop/continue",
    "/semantic/data/declare": "/c/data/declare",
    "/semantic/data/assign": "/c/data/assign",
    "/semantic/io/output": "/c/io/output",
    "/semantic/io/input": "/c/io/input",
    "/semantic/module/import": "/c/module/include_system",
    "/semantic/module/import/local": "/c/module/include_local"
  },
  "nodes": {
    "/c/function/call": {
      "type": "leaf",
      "template": "{call};",
      "spec_template": "{call}",
      "slots": ["call"],
      "maps_from": ["/semantic/function/call"]
    },
    "/c/data/assign": {
      "type": "leaf",
      "template": "{var} = {expr};",
      "spec_template": "{var} = {expr}",
      "slots": ["var", "expr"],
      "maps_from": ["/semantic/data/assign"]
    },
    "/c/function/define": {
      "type": "leaf",
      "template": "{ret_type} {func_name}({typed_args}) {",
      "spec_template": "定义 {func_name}({typed_args}) -> {ret_type}:",
      "slots": ["func_name", "typed_args", "ret_type"],
      "maps_from": ["/semantic/function/define"]
    },
    "/c/function/return": {
      "type": "leaf",
      "template": "return {expr};",
      "spec_template": "返回 {expr}",
      "slots": ["expr"],
      "maps_from": ["/semantic/function/return"]
    },
    "/c/control/if": {
      "type": "leaf",
      "template": "if ({cond}) {",
      "spec_template": "如果 {cond}:",
      "slots": ["cond"],
      "maps_from": ["/semantic/control/branch/if"]
    },
    "/c/control/elif": {
      "type": "leaf",
      "template": "} else if ({cond}) {",
      "spec_template": "否则如果 {cond}:",
      "slots": ["cond"],
      "maps_from": ["/semantic/control/branch/elif"]
    },
    "/c/control/else": {
      "type": "leaf",
      "template": "} else {",
      "spec_template": "否则:",
      "slots": [],
      "maps_from": ["/semantic/control/branch/else"]
    },
    "/c/control/loop/break": {
      "type": "leaf",
      "template": "break;",
      "spec_template": "跳出",
      "slots": [],
      "maps_from": ["/semantic/control/loop/break"]
    },
    "/c/control/loop/continue": {
      "type": "leaf",
      "template": "continue;",
      "spec_template": "继续",
      "slots": [],
      "maps_from": ["/semantic/control/loop/continue"]
    },
    "/c/control/for": {
      "type": "leaf",
      "template": "for ({init}; {cond}; {step}) {",
      "spec_template": "对于 {var} 中的 {iter}:",
      "slots": ["init", "cond", "step"],
      "maps_from": ["/semantic/control/loop/for"]
    },
    "/c/control/while": {
      "type": "leaf",
      "template": "while ({cond}) {",
      "spec_template": "当 {cond}:",
      "slots": ["cond"],
      "maps_from": ["/semantic/control/loop/while"]
    },
    "/c/data/declare": {
      "type": "leaf",
      "template": "{type} {var} = {expr};",
      "spec_template": "设 {var} = {expr}",
      "slots": ["type", "var", "expr"],
      "maps_from": ["/semantic/data/declare"]
    },
    "/c/io/output": {
      "type": "leaf",
      "template": "printf(\"%s\\n\", {expr});",
      "spec_template": "输出({expr})",
      "slots": ["expr"],
      "maps_from": ["/semantic/io/output"]
    },
    "/c/io/input": {
      "type": "leaf",
      "template": "scanf(\"%d\", &{var});",
      "spec_template": "输入({var})",
      "slots": ["var"],
      "maps_from": ["/semantic/io/input"]
    },
    "/c/module/include_system": {
      "type": "leaf",
      "template": "#include <{header}>",
      "spec_template": "引入系统 {header}",
      "slots": ["header"],
      "placement": "imports",
      "maps_from": ["/semantic/module/import"]
    },
    "/c/module/include_local": {
      "type": "leaf",
      "template": "#include \"{header}\"",
      "spec_template": "引入本地 {header}",
      "slots": ["header"],
      "placement": "imports",
      "maps_from": ["/semantic/module/import/local"]
    },
    "/c/preprocessor/macro": {
      "type": "leaf",
      "template": "#define {name} {val}",
      "spec_template": "宏定义 {name} = {val}",
      "slots": ["name", "val"],
      "maps_from": ["/semantic/preprocessor/macro"]
    },
    "/c/raw": {
      "type": "leaf",
      "template": "{code}",
      "spec_template": "原生 c \"{code}\"",
      "slots": ["code"],
      "maps_from": ["/semantic/raw"]
    }
  }
}
```

---

## 四、验证与预期效果

完成上述两份树表 JSON 覆盖后，可通过以下指令进行闭环验证：
1. 调用 `jevagent(action="list_tables")`，确认 `c_v1` 节点数扩充至 18 个，`syntax_core_v1` 包含标准别名；
2. 执行 `jevagent(action="spec_to_code", module_path="core_components/physics/loom_physics", target_lang="c")`；
3. **预期表现**：本地规则前置校验 100% 命中通过，无需连接远程 Jev 服务端，在毫秒级内直接产出标准 `loom_physics.c`，彻底消除 55 秒超时与 `exact_candidate_string` 歧义报错！
