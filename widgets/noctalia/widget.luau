--!nonstrict
-- Compact bar widget: glyph + label coloured by assistant state.
--   idle      -> dim
--   working   -> accent (starting/listening)
--   attention -> yellow (a plugin is degraded)
--   error     -> red (runner unreachable, or a plugin failed)
-- Left-click opens/focuses utter-gui; right-click forces a refresh.

local GUI_CMD = "utter-gui"

local COLOR_IDLE = "#525252"
local COLOR_ACCENT = "#38bdf8"
local COLOR_ATTENTION = "#facc15"
local COLOR_ERROR = "#ef4444"

local snap = noctalia.state.get("utter_status")
	or { connected = false, state = "idle", plugins = {}, problems = {} }

local function stateColor(st)
	if st == "working" then
		return COLOR_ACCENT
	end
	if st == "attention" then
		return COLOR_ATTENTION
	end
	if st == "error" then
		return COLOR_ERROR
	end
	return COLOR_IDLE
end

local function glyphFor(st)
	if st == "working" then
		return "microphone"
	end
	if st == "attention" then
		return "alert-triangle"
	end
	if st == "error" then
		return "alert-circle"
	end
	return "robot"
end

local function tooltipFor(s)
	local tips = {}
	if type(s) ~= "table" then
		return { { key = "Utter", value = "no status yet" } }
	end
	if s.connected then
		table.insert(tips, { key = "Runner", value = "connected" })
		local plugins = s.plugins or {}
		if #plugins == 0 then
			table.insert(tips, { key = "Plugins", value = "none registered" })
		end
		for _, p in ipairs(plugins) do
			table.insert(tips, {
				key = tostring(p.id or "?"),
				value = tostring(p.status or "?"),
			})
		end
		if type(s.problems) == "table" and #s.problems > 0 then
			table.insert(tips, { key = "Problems", value = table.concat(s.problems, ", ") })
		end
	else
		table.insert(tips, { key = "Runner", value = "unreachable" })
		if type(s.error) == "string" and s.error ~= "" then
			table.insert(tips, { key = "Error", value = s.error })
		end
	end
	return tips
end

local function render()
	local st = snap.state or "idle"
	local color = stateColor(st)
	local bold = (st == "attention" or st == "error")

	barWidget.render(ui.row({ gap = 6, align = "center" }, {
		ui.glyph({ name = glyphFor(st), size = 14, color = color }),
		ui.label({
			text = "Utter",
			color = color,
			fontWeight = bold and "bold" or "normal",
		}),
	}))
	barWidget.setTooltip(tooltipFor(snap))
end

noctalia.state.watch("utter_status", function(v)
	if type(v) == "table" then
		snap = v
		render()
	end
end)

noctalia.setUpdateInterval(2000)
render()

function update()
	render()
end

function onClick()
	-- Focus/open the native settings window; fall back to the Noctalia plugin
	-- settings if utter-gui is not installed yet.
	if type(noctalia.commandExists) ~= "function" or noctalia.commandExists(GUI_CMD) then
		noctalia.runAsync({ GUI_CMD }, function(_) end)
	else
		noctalia.runAsync({ "noctalia", "msg", "settings-open-plugin", "utter/utter" }, function(_) end)
	end
end

function onRightClick()
	noctalia.state.set("utter_cmd", { action = "refresh", nonce = math.random() })
end
