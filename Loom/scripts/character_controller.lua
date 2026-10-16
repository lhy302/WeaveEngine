-- character_controller.lua: Loom 纯 Lua 第三人称角色全功能控制器 (M5)
-- 机制: WASD 平面移动矢量合成 + 旋转朝向对齐 + 驱动相机跟随目标
local move_speed = 5.0
local rot_speed = 180.0
local camera_height = 2.2

function on_start()
end

function update(dt)
    local right = (loom.get_action("向右") and 1 or 0) - (loom.get_action("向左") and 1 or 0)
    local fwd = (loom.get_action("向前") and 1 or 0) - (loom.get_action("向后") and 1 or 0)
    
    if right ~= 0 or fwd ~= 0 then
        local len = math.sqrt(right * right + fwd * fwd)
        if len > 0.0001 then
            right = right / len
            fwd = fwd / len
        end
        
        local step = move_speed * dt
        loom.move(right * step, 0.0, fwd * step)
        
        -- 根据输入移动方向旋转角色朝向
        if right > 0 then
            loom.rotate(0.0, rot_speed * dt, 0.0)
        elseif right < 0 then
            loom.rotate(0.0, -rot_speed * dt, 0.0)
        end
    end
    
    -- 同步相机跟随锚点
    local px, py, pz = loom.get_position()
    loom.set_camera_target(px, py + camera_height, pz)
end
