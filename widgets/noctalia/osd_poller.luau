--!nonstrict
-- Assistant-mode OSD watcher.
--
-- Reads $XDG_RUNTIME_DIR/utter/osd.json (written atomically by the
-- utter voice/PTT emitter) and drives the `osd` overlay panel:
--   * on the first non-idle sample -> open the panel;
--   * publish each sample to shared state so the panel re-renders the live
--     level meter and text in place;
--   * on `final` -> colour by `activated` and hold ~1.2s, then close.
-- Polls at 50ms while active, 500ms when idle. No shelling out.

local STATE_KEY = "utter_osd"
local PANEL_ID = "utter/utter:osd"

local FINAL_HOLD_MS = 1200
local FAST_MS = 50
local IDLE_MS = 500

local open = false
local lastRaw = nil
local sinceFinal = 0
local lastSnap = { state = "idle", mode = "assistant", level = 0, text = "" }

local function trim(s)
	return tostring(s or ""):match("^%s*(.-)%s*$")
end

local function nowMs()
	if type(noctalia.nowMs) == "function" then
		local ms = noctalia.nowMs()
		if type(ms) == "number" and ms > 0 then
			return ms
		end
	end
	return math.floor(os.time() * 1000)
end

local function osdPath()
	local p = trim(noctalia.getConfig("osd_path"))
	if p ~= "" then
		return p
	end
	local runtimeDir = ""
	if type(noctalia.getenv) == "function" then
		runtimeDir = tostring(noctalia.getenv("XDG_RUNTIME_DIR") or "")
	end
	if runtimeDir == "" then
		local uid = ""
		if type(noctalia.getenv) == "function" then
			uid = tostring(noctalia.getenv("UID") or "")
		end
		if uid == "" then
			return ""
		end
		runtimeDir = "/run/user/" .. uid
	end
	return runtimeDir .. "/utter/osd.json"
end

local function readText(path)
	if type(noctalia.readFile) ~= "function" then
		return nil
	end
	local ok, content, err = pcall(noctalia.readFile, path)
	if not ok then
		return nil
	end
	if type(content) == "string" then
		return content
	end
	if content == true and type(err) == "string" then
		return err
	end
	return nil
end

local function publish(s)
	lastSnap = s
	noctalia.state.set(STATE_KEY, s)
end

local function openPanel()
	if open then
		return
	end
	open = true
	local enc = noctalia.json.encode(lastSnap or { state = "listening", mode = "assistant" })
	noctalia.runAsync({ "noctalia", "msg", "panel-open", PANEL_ID, enc }, function(_) end)
end

local function closePanel()
	if not open then
		return
	end
	open = false
	noctalia.runAsync({ "noctalia", "msg", "panel-close", PANEL_ID }, function(_) end)
end

local function apply(sample)
	local st = tostring(sample.state or "idle")
	if st == "listening" then
		sinceFinal = 0
		publish(sample)
		openPanel()
	elseif st == "loading" then
		-- Models are coming up after wake / cold start: keep the panel open
		-- (idle would otherwise close it) until the emitter clears it.
		sinceFinal = 0
		publish(sample)
		openPanel()
	elseif st == "final" then
		sinceFinal = nowMs()
		publish(sample)
		openPanel()
	else
		-- idle / unknown: keep a `final` visible for the hold window.
		if sinceFinal > 0 and (nowMs() - sinceFinal) < FINAL_HOLD_MS then
			return
		end
		sinceFinal = 0
		publish({ state = "idle", mode = "assistant", level = 0, text = "" })
		closePanel()
	end
end

local function poll()
	if noctalia.getConfig("osd_enabled") == false then
		sinceFinal = 0
		closePanel()
		noctalia.setUpdateInterval(IDLE_MS)
		return
	end

	local raw = readText(osdPath()) or ""
	if raw ~= lastRaw then
		lastRaw = raw
		if raw ~= "" then
			local ok, decoded = pcall(noctalia.json.decode, raw)
			if ok and type(decoded) == "table"
				and (decoded.mode == nil or decoded.mode == "assistant" or decoded.mode == "dictation") then
				apply(decoded)
			end
		else
			apply({ state = "idle" })
		end
	end

	-- Expire a final sample even when the file stops changing.
	if sinceFinal > 0 and (nowMs() - sinceFinal) >= FINAL_HOLD_MS then
		sinceFinal = 0
		publish({ state = "idle", mode = "assistant", level = 0, text = "" })
		closePanel()
	end

	local active = open or sinceFinal > 0
	noctalia.setUpdateInterval(active and FAST_MS or IDLE_MS)
end

noctalia.setUpdateInterval(IDLE_MS)
poll()

function update()
	poll()
end

function onConfigChanged()
	lastRaw = nil
	noctalia.setUpdateInterval(IDLE_MS)
	poll()
end

function onIpc(event, payload)
	-- Allow an emitter to push immediately instead of waiting for the tick.
	if event == "show" or event == "update" then
		local ok, decoded = pcall(noctalia.json.decode, tostring(payload or ""))
		if ok and type(decoded) == "table"
			and (decoded.mode == nil or decoded.mode == "assistant") then
			lastRaw = nil
			apply(decoded)
			noctalia.setUpdateInterval(FAST_MS)
		end
	elseif event == "hide" then
		sinceFinal = 0
		publish({ state = "idle", mode = "assistant", level = 0, text = "" })
		closePanel()
	end
end
