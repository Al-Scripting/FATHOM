-- FATHOM telemetry mod (UE4SS Lua). Writes telemetry.json twice a second for the Python side.
-- Only calls proven safe on this build are used: FindFirstOf, FindAllOf, IsValid, GetClass():GetFName(),
-- K2_GetActorLocation, GetVelocity, GetControlRotation, one verified property on the HUD view model, and pcall'd
-- UFunction calls. Every attempt to scan objects or read properties by name from Lua crashed this build
-- (2026-09-07, five dumps). Use UE4SS's own "Dump Objects & Properties" for exploration.

local OUT = "S:/Master/FATHOM/telemetry.json"
local PERIOD_MS = 500
local SEA_LEVEL_Z = 0 -- measured 2026-09-07: pawn Z at the surface was -1.9 cm, so no offset needed
-- Oxygen: the HUD view model mirrors UWESurvivalAttributeSet.Oxygen on the pawn and is unique to the player.
local O2_CLASS, O2_PROP = "SN2PlayerOxygenViewModel", "CurrentValue"
local HOME_CLASSES = { "BP_Lifepod_C", "BP_StaticLifepod_C", "BP_StaticLifepod_Surface_C", "BP_BaseHatch_C",
    "BP_Tadpole_C" }
local AIR_CLASSES = { "BP_OxygenPlant_C", "BP_OxygenTank_Medium_C", "BP_OxygenGenerator_Carryable_C",
    "BP_OxygenReplenishBox_C", "BP_Tadpole_C" }
local DAY_CLASS = "DaySequenceActor" -- Unreal's day sequence plugin; GetTimeOfDay() returns game hours
-- Hostiles are found by class-name pattern among live pawns, so predators whose exact class is not yet known
-- are still tracked. Names from the Subnautica 2 wiki's creature roster (docs/pda_register.md).
local LEVIATHAN = { "Leviathan", "Shiver", "GreatJaw", "CoralCrab", "Collector" }
local PREDATOR = { "Marrowbreach", "Sandspear", "Epicurean", "Foureye", "Hycean", "Cerathecan", "Bullethead",
    "Needler", "Nibbler", "Sitaray", "Scourge", "Waxmoon", "VepsDefender", "Defendervep", "Hammerhead" }
local PLACID = { "DeepWing", "Deepwing" } -- the Deepwing Brooder is the Reefback of this game
local EXCLUDE = { "Nest", "Egg", "Spawn", "Zone", "Manager", "Prototype", "Shake", "Sound", "Fragment",
    "PlayerStart", "Chassis", "Tadpole", "Trigger", "Component", "Anim", "Default__", "Corpse", "Dead" }
local KNOWN_LEVIATHANS = { "BP_CollectorLeviathan_C", "BP_VoidLeviathanChild_C" } -- in case they are not Pawns

local function log(s) print("[FATHOM] " .. tostring(s) .. "\n") end

local function player()
    local pc = FindFirstOf("PlayerController")
    if not pc or not pc:IsValid() then return nil end
    local ok, pawn = pcall(function() return pc.Pawn end)
    if ok and pawn and pawn:IsValid() then return pawn end
end

local function dist(a, b)
    local dx, dy, dz = a.X - b.X, a.Y - b.Y, a.Z - b.Z
    return math.sqrt(dx * dx + dy * dy + dz * dz) / 100 -- UE cm -> m
end

local function has_any(s, words)
    for _, w in ipairs(words) do
        if s:find(w, 1, true) then return true end
    end
    return false
end

local tier_cache = {}
local function tier(cn)
    local t = tier_cache[cn]
    if t ~= nil then return t or nil end
    local result = false
    if not has_any(cn, EXCLUDE) and not has_any(cn, PLACID) then
        if has_any(cn, LEVIATHAN) then result = "leviathan" elseif has_any(cn, PREDATOR) then result = "predator" end
    end
    tier_cache[cn] = result
    if result then log("tracking " .. cn .. " as " .. result) end
    return result or nil
end

-- No actor caching across ticks: a cached actor freed by garbage collection is a dangling pointer and crashed
-- the game. FindAllOf goes through UE4SS's class index and is cheap enough per tick.
local function nearest(classes, loc)
    local best, name, where
    for _, cls in ipairs(classes) do
        for _, o in ipairs(FindAllOf(cls) or {}) do
            local ok, l = pcall(function() return o:IsValid() and o:K2_GetActorLocation() end)
            if ok and l then
                local d = dist(l, loc)
                if not best or d < best then best, name, where = d, cls, l end
            end
        end
    end
    return best, name, where
end

-- Every live pawn whose class name marks it hostile, nearest per tier.
local function hostiles(pawn, loc)
    local best = { leviathan = {}, predator = {} }
    local me = pawn:GetAddress()
    local function consider(o, forced)
        local ok = pcall(function()
            if not o:IsValid() or o:GetAddress() == me then return end
            local cn = o:GetClass():GetFName():ToString()
            local tr = forced or tier(cn)
            if not tr then return end
            local l = o:K2_GetActorLocation()
            local d = dist(l, loc)
            local b = best[tr]
            if not b.dist or d < b.dist then b.dist, b.name, b.where = d, cn, l end
        end)
        return ok
    end
    for _, o in ipairs(FindAllOf("Pawn") or {}) do consider(o) end
    for _, cls in ipairs(KNOWN_LEVIATHANS) do
        for _, o in ipairs(FindAllOf(cls) or {}) do consider(o, "leviathan") end
    end
    return best.leviathan, best.predator
end

-- Where a hostile is relative to the diver, in words: "below, behind you". Only ever spoken at contact.
local function relation(pc, loc, vel, where)
    local dz = (where.Z - loc.Z) / 100
    local vert = dz > 5 and "above" or dz < -5 and "below" or nil
    local fx, fy
    local ok, rot = pcall(function() return pc:GetControlRotation() end)
    if ok and rot and rot.Yaw then
        local yaw = math.rad(rot.Yaw)
        fx, fy = math.cos(yaw), math.sin(yaw)
    elseif math.sqrt(vel.X ^ 2 + vel.Y ^ 2) > 50 then
        local n = math.sqrt(vel.X ^ 2 + vel.Y ^ 2)
        fx, fy = vel.X / n, vel.Y / n
    end
    local horiz
    if fx then
        local dx, dy = where.X - loc.X, where.Y - loc.Y
        local n = math.sqrt(dx * dx + dy * dy)
        if n > 100 then
            local dot = (dx * fx + dy * fy) / n
            horiz = dot > 0.5 and "ahead" or dot < -0.5 and "behind you" or "beside you"
        end
    end
    if vert and horiz then return vert .. ", " .. horiz end
    return vert or horiz
end

local function number_of(obj, prop)
    local ok, v = pcall(function() return obj[prop] end)
    if not ok or v == nil then return nil end
    if type(v) == "number" then return v end
    local ok2, cv = pcall(function() return v.CurrentValue end) -- FGameplayAttributeData
    if ok2 and type(cv) == "number" then return cv end
end

local function read_o2()
    local src = FindFirstOf(O2_CLASS) -- looked up every tick on purpose: the HUD object is rebuilt on respawn
    if src and src:IsValid() then return number_of(src, O2_PROP) end
end

local day_warned = false
local function time_of_day()
    local day = FindFirstOf(DAY_CLASS)
    if not day or not day:IsValid() then return nil end
    local ok, v = pcall(function() return day:GetTimeOfDay() end)
    if ok and type(v) == "number" then return v end
    if not day_warned then day_warned = true; log("time of day unavailable: " .. tostring(v)) end
end

local function j(v)
    if v == nil then return "null" end
    if type(v) == "string" then return '"' .. v .. '"' end
    return string.format("%.2f", v)
end

local function write(t)
    local f = io.open(OUT .. ".tmp", "w")
    if not f then return end
    f:write(string.format(
        '{"t":%d,"depth":%s,"o2":%s,"speed":%s,"threat_dist":%s,"threat":%s,"predator_dist":%s,"predator":%s,' ..
        '"threat_rel":%s,"dist_home":%s,"air_dist":%s,"time_of_day":%s,"x":%s,"y":%s}',
        os.time(), j(t.depth), j(t.o2), j(t.speed), j(t.threat_dist), j(t.threat), j(t.predator_dist),
        j(t.predator), j(t.threat_rel), j(t.dist_home), j(t.air_dist), j(t.time_of_day), j(t.x), j(t.y)))
    f:close()
    os.remove(OUT)
    os.rename(OUT .. ".tmp", OUT)
end

local function frame()
    local pc = FindFirstOf("PlayerController")
    local pawn = player()
    if not pawn then return end
    local loc = pawn:K2_GetActorLocation()
    local vel = pawn:GetVelocity()
    local speed = math.sqrt(vel.X ^ 2 + vel.Y ^ 2 + vel.Z ^ 2) / 100
    local lev, pred = hostiles(pawn, loc)
    local rel
    local close = lev.dist and (not pred.dist or lev.dist <= pred.dist) and lev or pred
    if close.dist and close.dist < 120 then
        local ok, r = pcall(relation, pc, loc, vel, close.where)
        if ok then rel = r end
    end
    local hd = nearest(HOME_CLASSES, loc)
    local ad = nearest(AIR_CLASSES, loc)
    write({ depth = (SEA_LEVEL_Z - loc.Z) / 100, o2 = read_o2(), speed = speed, threat_dist = lev.dist,
        threat = lev.name, predator_dist = pred.dist, predator = pred.name, threat_rel = rel, dist_home = hd,
        air_dist = ad, time_of_day = time_of_day(), x = loc.X / 100, y = loc.Y / 100 })
end

local busy = false
LoopAsync(PERIOD_MS, function()
    if busy then return false end -- the game thread has not run the previous frame yet
    busy = true
    ExecuteInGameThread(function()
        local ok, err = pcall(frame)
        if not ok then log(err) end
        busy = false
    end)
    return false
end)

log("loaded, writing " .. OUT .. " every " .. PERIOD_MS .. " ms")
