【普通插件 · 投放说明】(2026-08-27 分级重设计)
====================================================================
目录结构 (放进即装, 删掉即卸):
  plugins/editor/   只注入编辑器层的普通插件 (开发者工具; 不会进游戏)
  plugins/player/   只注入播放器层的普通插件 (游戏运行要用的; 封装成游戏
                    时会被 build_game 打包带走)

每个插件 = 一个目录:
  plugins/player/<目录名>/
      plugin.json   {"id", "name", "version", "entry", 可选 "min_engine","deps"}
                    id 用反向域名风格 (如 com.dsh.my_tool), 防重名
      entry.py      def register(api): ...   (必需)
      其它文件      插件资源 (用 api.read_asset('文件名') 只读访问)

目录即声明: 放 editor/ = 只影响编辑器; 放 player/ = 进游戏层。

【权限 = 受限执行环境 (2026-08-27; 2026-08-28 渗透实测后收口)】
  - 与引擎不同权! 普通插件运行在受限环境:
      无 文件读写 (资源走 api.read_asset, 限自己目录只读)
      无 网络 / 子进程 / ctypes / 线程 / 动态代码 (exec/eval)
      无 系统模块 (os/sys/subprocess/socket/shutil/...); 允许白名单:
      math re collections itertools functools dataclasses typing random
      copy json (2026-08-28: scripts/engine/matlib 已移出 —— 命名空间真实
      含 os/sys/np, import 即直取系统面; 引擎能力一律走 api.*)
      + 入口源码 AST 门禁 (.__globals__/.__subclasses__/.__builtins__/
      .__dict__ 等元编程黑面属性与 vars/globals/getattr 检索器调用直接拒载)
  - 目的: 防误用/防低级恶意 (投放式安装; 谁都能往这目录放文件)
  - 诚实边界: **门禁档, 不是安全沙箱**。2026-08-28 渗透靶场
    (_attack_range_普通插件释毒实验) 13 个向量 (直写 9 + 混淆 4, 含异常
    回溯框架面) 全部被拦 (可复跑 attack_range.py), 但 AST/受限环境挡的是
    "书写形态", 刻意深层混淆在理论上仍可构造绕道 —— 解释器内无真沙箱。
    受限制的是"伸手抓系统", 不限"用引擎 API 做事"。
  - 想替换引擎核心部件? -> 那是核心插件: 放 core_plugins\<类别>\<插件>\
    (全权 + 人工信任闸 + 重启生效, 见 core_plugins\README.txt)

【危险权利清单 (受限挡板)】
  禁止: 任意文件读写 / 网络 / 子进程 / 原生接口(ctypes/注册表) /
        动态代码(exec/eval) / 线程与进程 / 直接改引擎私有内部兜底
  允许: 注册游戏脚本(检查器可挂) / 注册编辑器按钮(工具栏「插件」菜单) /
        只读自己的资源 / 引擎数学工具 / 查询输入动作 / 场景只读数据

【1\ 信任边界】此目录内的插件 = 任意代码执行 (受限环境, 但可被元编程
绕过, 见上)。只放入你信任的插件 (含 plugin.json + entry.py)。
任何能向此目录投放文件的人 = 获得本机代码执行能力。

【2\ 生效方式】放进后: 重启 Loom 或设置面板「重新扫描」; [加载]/[卸载]
每个插件单独控制 (卸载=会话禁用, 忘删目录则重启恢复); 改插件代码后
须「卸载→再加载」或重启 (Python 只 import 一次)。

【3\ 插件 API (register 钩子可用)】
  api.register_script(类)           注册游戏脚本 (脚本下拉可挂)
  api.register_editor_button(文字, 回调)  编辑器「插件」菜单按钮 (跨层界面补充)
  api.read_asset('文件')            读自己插件目录内文本 (只读)
  其余扩展点 (menu/panel/importer/shader...) L2+ 开放, 先记待办。

【4\ 测试与文档】[新增功能台账]《未测试功能测试方向指南.txt》2026-08-27 条;
详细设计见《Loom插件系统分级方案.txt》。
