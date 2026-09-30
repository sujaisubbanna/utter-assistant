--!nonstrict
-- Assistant-mode OSD panel: a persistent, non-interactive overlay that appears
-- while push-to-talk is active and auto-dismisses. Opened live by
-- osd_poller.luau from $XDG_RUNTIME_DIR/utter/osd.json, and updated
-- in-place via shared state. Also accepts an IPC push for immediacy:
--   noctalia msg plugin utter/utter:osd focused show '<json>'
--
-- Look: the Utter mark, the live transcript, and a waveform of rounded bars
-- (the mark's round-capped stems) in the brand yellow. Final state tints the
-- bars green (a command ran) or red (nothing matched).

local PANEL_ID = "utter/utter:osd"
local STATE_KEY = "utter_osd"

local YELLOW = "#f7c948"   -- assistant: your words become an action
local BLUE = "#8cc8ff"     -- dictation: your words are typed
local INK = "#ececec"
local MUTED = "#9c9c9c"
local OK = "#4cc38a"
local ERROR = "#f2777a"

local BARS = 17
local BAR_W = 3
local BAR_GAP = 3
local WAVE_H = 30
local MIN_H = 3
local TAIL_CHARS = 22
local TEXT_W = 214   -- panel 420 − mark 26 − gaps 24 − wave 99 − padding

local isOpen = false
local snap = nil
local history = {}
for i = 1, BARS do
	history[i] = 0
end

local function decode(value)
	if type(value) == "table" then
		return value
	end
	if type(value) == "string" and value ~= "" then
		local ok, decoded = pcall(noctalia.json.decode, value)
		if ok and type(decoded) == "table" then
			return decoded
		end
	end
	return nil
end

local function clamp01(v)
	v = tonumber(v) or 0
	if v < 0 then
		return 0
	elseif v > 1 then
		return 1
	end
	return v
end

-- New samples enter at the centre and ripple outwards, so the wave reads as a
-- voice coming *out of* the mark rather than a scrolling chart.
local function pushLevel(level)
	local mid = math.floor(BARS / 2) + 1
	for i = 1, mid - 1 do
		history[i] = history[i + 1]
	end
	for i = BARS, mid + 1, -1 do
		history[i] = history[i - 1]
	end
	history[mid] = clamp01(level)
end

local function wave(color, flat)
	local bars = {}
	for i = 1, BARS do
		local lv = flat and 0.18 or history[i]
		-- soft envelope: taller in the middle, like the mark's centre of mass
		local centre = 1 - math.abs((i - (BARS + 1) / 2) / ((BARS + 1) / 2)) * 0.45
		local h = math.floor(MIN_H + (WAVE_H - MIN_H) * math.min(1, lv * 1.35) * centre + 0.5)
		if h < MIN_H then
			h = MIN_H
		end
		table.insert(bars, ui.box({
			width = BAR_W,
			height = h,
			radius = 2,
			fill = color,
		}))
	end
	return ui.row({ gap = BAR_GAP, align = "center", minHeight = WAVE_H }, bars)
end

local function view(s)
	if type(s) ~= "table" then
		s = { state = "listening", level = 0, text = "" }
	end
	local st = tostring(s.state or "listening")
	local text = tostring(s.text or "")
	local dictation = s.mode == "dictation"
	local accent = dictation and BLUE or YELLOW

	local color, status, title, glyph
	if st == "final" then
		local activated = s.activated == true
		color = activated and OK or ERROR
		if dictation then
			status = activated and "Typed" or "Couldn't type that"
		else
			status = activated and "Done" or "Didn't catch that"
		end
		title = text ~= "" and text or status
		glyph = activated and "check" or "x"
	elseif st == "idle" then
		color = MUTED
		status = "Ready"
		title = "Hold to talk"
	else
		color = accent
		if dictation then
			status = "Dictation · typing"
			title = text ~= "" and text or "Dictating…"
			glyph = "keyboard"
		else
			status = "Assistant · listening"
			title = text ~= "" and text or "Listening…"
		end
		pushLevel(s.level)
		-- While speaking, the newest words matter most: keep the tail visible.
		if #title > TAIL_CHARS then
			local tail = string.sub(title, -(TAIL_CHARS - 1))
			-- start the tail on a word boundary when one is close by
			local cut = string.find(tail, " ", 1, true)
			if cut and cut < 8 then
				tail = string.sub(tail, cut + 1)
			end
			title = "…" .. tail
		end
	end

	local statusColor = (st == "final" or dictation) and color or MUTED
	local statusRow = { ui.label({ text = status, color = statusColor, fontSize = 11, maxLines = 1 }) }
	if glyph then
		table.insert(statusRow, 1, ui.glyph({ name = glyph, size = 12, color = color }))
	end

	return ui.row({ gap = 12, align = "center", paddingH = 4 }, {
		ui.image({ path = "assets/utter-mark.png", width = 26, height = 26, fit = "contain" }),
		-- Fixed-width text column: long transcripts truncate before the waveform.
		ui.column({ gap = 2, flexGrow = 1, minWidth = TEXT_W, maxWidth = TEXT_W }, {
			ui.label({ text = title, color = INK, fontWeight = "bold", fontSize = 14, maxLines = 1, maxWidth = TEXT_W }),
			ui.row({ gap = 4, align = "center", maxWidth = TEXT_W }, statusRow),
		}),
		wave(color, st ~= "listening"),
	})
end

local function render(s)
	snap = s
	if isOpen and type(s) == "table" then
		panel.render(view(s))
	end
end

noctalia.state.watch(STATE_KEY, function(v)
	if type(v) == "table" then
		render(v)
	end
end)

function onOpen(context)
	isOpen = true
	for i = 1, BARS do
		history[i] = 0
	end
	local s = decode(context)
	if type(s) ~= "table" then
		s = noctalia.state.get(STATE_KEY)
	end
	render(s or { state = "listening", level = 0, text = "" })
end

function onClose()
	isOpen = false
end

function onIpc(event, payload)
	if event ~= "show" and event ~= "update" then
		return
	end
	local s = decode(payload)
	if type(s) ~= "table" then
		return
	end
	noctalia.state.set(STATE_KEY, s)
	render(s)
	if not isOpen then
		isOpen = true
		local enc = noctalia.json.encode(s)
		noctalia.runAsync({ "noctalia", "msg", "panel-open", PANEL_ID, enc }, function(_) end)
	end
end
