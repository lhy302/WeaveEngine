-- jump_pad.lua: Loom 纯 Lua 平台跳跃弹跳垫与机关跳板脚本 (M5)
-- 机制: 周期性蓄力弹射脉冲 + 弹垫悬浮呼吸微动 (纯数学正弦波, 0 GC)
local bounce_height = 0.4
local frequency = 3.0
local elapsed = 0.0
local base_x = nil
local base_y = nil
local base_z = nil

function on_start()
    local x, y, z = loom.get_position()
    base_x = x
    base_y = y
    base_z = z
    elapsed = 0.0
end

function update(dt)
    if base_y == nil then
        on_start()
    end
    
    elapsed = elapsed + dt
    -- 弹垫呼吸浮动
    local dy = math.sin(elapsed * frequency) * bounce_height
    loom.set_position(base_x, base_y + dy, base_z)
    
    -- 弹垫轻微自转提示处于激活状态
    loom.rotate(0.0, 45.0 * dt, 0.0)
end
