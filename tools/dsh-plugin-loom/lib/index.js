import { defineTool } from "@deepseek-ai/dsh-tools";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";

const name = "loom-tools";
const inject = ["tools"];

const STATUS_FILE =
  "D:\\my-project\\Loom(py源代码)\\未测试功能测试方向指南.txt";
const LOOM_DIR = "D:\\my-project\\Loom(py源代码)\\Loom";

function apply(ctx) {
  ctx.tools.register(
    defineTool({
      name: "loom_tally_status",
      description:
        "读取未测试功能测试方向指南.txt,输出所有需要复测的条目。标记格式为【a,b】:a=人工实测状态(0=未实测,1=已实测),b=代码改动(1=代码有改动需要复测)。只要 b=1 就需要复测,即标记为【0,1】或【1,1】的条目。每条输出'标题 + 标记'。",
      parameters: {},
      output: {
        schema: { type: "string" },
        render: (_args, value) => [{ type: "text", text: String(value) }],
      },
      async execute() {
        let raw;
        try {
          raw = await readFile(STATUS_FILE, "utf-8");
        } catch (err) {
          return `错误:无法读取状态文件: ${err.message}`;
        }
        if (raw.charCodeAt(0) === 0xfeff) {
          raw = raw.slice(1);
        }
        const lines = raw.split(/\r?\n/);
        const matches = [];
        let lastTitle = null;
        for (const line of lines) {
          const t = line.trim();
          if (/^[AHPXR]\d+/.test(t)) {
            lastTitle = t;
          }
          if (/^【\d\s*,\s*1】$/.test(t) && lastTitle) {
            matches.push(`${lastTitle} ${t}`);
          }
        }
        if (matches.length === 0) {
          return "没有b=1的条目";
        }
        return matches.join("\n");
      },
    })
  );

  ctx.tools.register(
    defineTool({
      name: "loom_test_file",
      description:
        "在 Loom 目录下执行 py -3.12 tests/<file_name>,返回退出码与输出的最后 40 行。",
      parameters: {
        file_name: {
          type: "string",
          required: true,
          description: "测试文件名(仅允许字母、数字、下划线、点)。",
        },
      },
      output: {
        schema: { type: "string" },
        render: (_args, value) => [{ type: "text", text: String(value) }],
      },
      async execute(args) {
        const file_name = args?.file_name;
        if (typeof file_name !== "string") {
          return "错误:参数 file_name 必须为字符串。";
        }
        if (!/^[A-Za-z0-9_\.]+$/.test(file_name)) {
          return "错误:file_name 含非法字符(仅允许字母数字下划线点,禁止路径分隔符与 ..)。";
        }
        return new Promise((resolve) => {
          execFile(
            "py",
            ["-3.12", `tests/${file_name}`],
            {
              cwd: LOOM_DIR,
              timeout: 300000,
              env: { ...process.env, PYTHONIOENCODING: "utf-8" },
            },
            (error, stdout, stderr) => {
              const code = error ? error.code ?? 1 : 0;
              const combined = `${stdout ?? ""}\n${stderr ?? ""}`.trimEnd();
              const lines = combined.split(/\r?\n/);
              const tail = lines.slice(-40).join("\n");
              return resolve(
                `退出码: ${code}\n输出最后 40 行:\n${tail || "(无输出)"}`
              );
            }
          );
        });
      },
    })
  );
}

export { name, inject, apply };
