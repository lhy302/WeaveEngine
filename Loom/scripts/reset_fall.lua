-- reset_fall.lua: Loom 纯 Lua 跌出世界自愈重置脚本 (M5 纯 Lua 改造)
-- 机制: 监测 y 坐标是否低于阈值, 跌出世界时瞬移回出生点, 彻底剥离 Python 反射
local threshold_y = -30.0
local spawn_x = 0.0
local spawn_y = 1.0
local spawn_z = 0.0
local initialized = false

function on_start()
    spawn_x, spawn_y, spawn_z = loom.get_position()
    initialized = true
end

function update(dt)
    if not initialized then
        on_start()
    end
    
    local x, y, z = loom.get_position()
    if y < threshold_y then
        loom.set_position(spawn_x, spawn_y, spawn_z)
        loom.set_rotation(0.0, 0.0, 0.0)
    end
end
