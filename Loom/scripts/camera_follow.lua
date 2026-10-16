-- camera_follow.lua: Loom 纯 Lua 相机跟随脚本 (M4)
local oy = 2.0
local oz = 0.0

function on_start()
end

function update(dt)
    local x, y, z = loom.get_position()
    loom.set_camera_target(x, y + oy, z + oz)
end
