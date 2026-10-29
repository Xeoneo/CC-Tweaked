-- CC:Tweaked Mining Turtle - safe, TELEMETRY-ONLY client.
-- Does not issue movement, mining, or update commands.
local config = dofile("fleet_config.lua")
assert(type(config.url)=="string" and config.url:sub(1,6)=="wss://", "Set a wss:// URL in fleet_config.lua")
assert(type(config.key)=="string" and #config.key>=24, "Set your FLEET_KEY in fleet_config.lua")
assert(turtle, "Run this on a Mining Turtle")
assert(http and http.websocket, "HTTP/WebSockets disabled in CC:Tweaked server config")

local function status()
  local slots=0
  for i=1,16 do if turtle.getItemCount(i)>0 then slots=slots+1 end end
  local x,y,z = gps.locate(2, false)
  local pos = nil
  if x then pos = {x=math.floor(x+0.5),y=math.floor(y+0.5),z=math.floor(z+0.5)} end
  return {type="status", fuel=turtle.getFuelLevel(), slots=slots, pos=pos}
end

print("Safe Fleet cloud telemetry | Computer ID "..os.getComputerID())
while true do
  local ws,why = http.websocket(config.url, {["X-Fleet-Key"]=config.key})
  if ws then
    print("Connected to cloud")
    local ok,err=pcall(function()
      ws.send(textutils.serializeJSON({type="hello",id=os.getComputerID(),label=os.getComputerLabel() or ""}))
      while true do
        ws.send(textutils.serializeJSON(status()))
        local reply, reason=ws.receive(10)
        if reply==nil and reason~="Timed out" then error(tostring(reason or "Disconnected")) end
        -- Remote commands are intentionally ignored in this stage.
      end
    end)
    pcall(ws.close)
    if not ok then print("Socket reset: "..tostring(err)) end
  else
    print("Connect failed: "..tostring(why))
  end
  sleep(5)
end
