-- rotate.lua: Loom 纯 Lua 自转脚本 (M4)
local sx = 0.0
local sy = 90.0
local sz = 0.0

function on_start()
end

function update(dt)
    loom.rotate(sx * dt, sy * dt, sz * dt)
end
