-- patrol_ai.lua: Loom 纯 Lua 敌人与守卫巡逻 AI 脚本 (M5)
-- 机制: 沿配置轴 (默认 X 轴) 往返匀速巡逻, 到达端点平滑原地调头, 全流程纯 C 虚拟机推进
local speed = 2.5
local patrol_range = 8.0
local direction = 1.0
local origin_x = nil
local origin_y = nil
local origin_z = nil

function on_start()
    local x, y, z = loom.get_position()
    origin_x = x
    origin_y = y
    origin_z = z
end

function update(dt)
    if origin_x == nil then
        on_start()
    end
    
    local x, y, z = loom.get_position()
    local dx = direction * speed * dt
    local next_x = x + dx
    
    -- 边界反弹与掉头检测
    if (next_x - origin_x) > patrol_range then
        next_x = origin_x + patrol_range
        direction = -1.0
        loom.rotate(0.0, 180.0, 0.0)
    elseif (next_x - origin_x) < -patrol_range then
        next_x = origin_x - patrol_range
        direction = 1.0
        loom.rotate(0.0, 180.0, 0.0)
    end
    
    loom.set_position(next_x, y, z)
end
