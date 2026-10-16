-- wasd_move.lua: Loom 纯 Lua WASD 移动脚本 (M4)
local speed = 3.0

function on_start()
end

function update(dt)
    local dx = (loom.get_action("向右") and 1 or 0) - (loom.get_action("向左") and 1 or 0)
    local dz = (loom.get_action("向前") and 1 or 0) - (loom.get_action("向后") and 1 or 0)
    if dx ~= 0 or dz ~= 0 then
        local s = speed * dt
        loom.move(dx * s, 0.0, dz * s)
    end
end
