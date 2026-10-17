# -*- coding: utf-8 -*-
"""M33 运行时 UI: RuntimeUI 文字/按钮/进度条 命令逻辑 + 按钮点击检测."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

eng = E.GLEngine.__new__(E.GLEngine)   # 桩: 只测命令逻辑, 不画 GPU
eng.mouse_pos = (0, 0)
eng.pressed = set()
ui = E.RuntimeUI(eng)

# ---- 文字 ----
ui.text("分数: 10", 10, 20)
check("ui.text 追加 text 命令", ui.cmds[0][0] == 'text' and ui.cmds[0][1] == '分数: 10',
      str(ui.cmds[0]))

# ---- 按钮点击检测 ----
eng.mouse_pos = (110, 115); eng.pressed = {1}     # 鼠标在按钮内 + 本帧按下左键
clk = ui.button("go", (100, 110, 80, 30), "开始")
check("ui.button 命中矩形+按下 -> 点击", clk is True)
eng.pressed = set()
clk2 = ui.button("go2", (200, 110, 80, 30), "跳过")
check("ui.button 未命中 -> 不点击", clk2 is False)
eng.pressed = {1}; eng.mouse_pos = (10, 10)
clk3 = ui.button("go3", (100, 110, 80, 30), "跳过")
check("ui.button 按下但不在矩形 -> 不点击", clk3 is False)

# ---- 进度条 frac clamp ----
ui.bar((10, 10, 100, 10), 1.5)
check("ui.bar frac clamp 到 1", ui.cmds[-1][2] == 1.0, str(ui.cmds[-1][2]))
ui.bar((10, 10, 100, 10), -0.2)
check("ui.bar frac clamp 到 0", ui.cmds[-1][2] == 0.0, str(ui.cmds[-1][2]))

# ---- clear ----
ui.clear()
check("ui.clear 清空命令", ui.cmds == [])

# ---- 脚本可访问 engine.ui (真实 __init__ 才有, 桩验证属性存在性由集成测) ----
check("RuntimeUI 可实例化", isinstance(E.RuntimeUI(eng), E.RuntimeUI))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
