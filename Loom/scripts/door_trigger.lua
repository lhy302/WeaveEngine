-- door_trigger.lua: Loom 纯 Lua 机关门与升降电梯脚本 (M5)
-- 机制: 在 min_height 与 max_height 之间往复平滑升降, 两端具备停留缓冲时钟
local move_speed = 2.0
local min_offset = 0.0
local max_offset = 4.5
local wait_duration = 1.2

local base_x = nil
local base_y = nil
local base_z = nil
local current_offset = 0.0
local state = 1 -- 1: 向上移动, 2: 顶部等待, 3: 向下移动, 4: 底部等待
local wait_timer = 0.0

function on_start()
    local x, y, z = loom.get_position()
    base_x = x
    base_y = y
    base_z = z
    current_offset = 0.0
    state = 1
    wait_timer = 0.0
end

function update(dt)
    if base_y == nil then
        on_start()
    end
    
    if state == 1 then
        current_offset = current_offset + move_speed * dt
        if current_offset >= max_offset then
            current_offset = max_offset
            state = 2
            wait_timer = wait_duration
        end
    elseif state == 2 then
        wait_timer = wait_timer - dt
        if wait_timer <= 0.0 then
            state = 3
        end
    elseif state == 3 then
        current_offset = current_offset - move_speed * dt
        if current_offset <= min_offset then
            current_offset = min_offset
            state = 4
            wait_timer = wait_duration
        end
    elseif state == 4 then
        wait_timer = wait_timer - dt
        if wait_timer <= 0.0 then
            state = 1
        end
    end
    
    loom.set_position(base_x, base_y + current_offset, base_z)
end
