--!nonstrict
-- Persistent on-screen attention panel. Rendered as a floating overlay-layer
-- panel so it stays visible even when the bar is auto-hidden. Opened by the
-- poller on a transition into trouble and closed on recovery.

local COLOR_ERROR = "#ef4444"
local COLOR_ATTENTION = "#facc15"

local function decodeContext(context)
	if type(context) == "table" then
		return context
	end
	if type(context) == "string" and context ~= "" then
		local ok, decoded = pcall(noctalia.json.decode, context)
		if ok and type(decoded) == "table" then
			return decoded
		end
	end
	return nil
end

local function render(snap)
	local st = (type(snap) == "table" and snap.state) or "attention"
	local color = (st == "error") and COLOR_ERROR or COLOR_ATTENTION
	local glyphName = (st == "error") and "alert-circle" or "alert-triangle"

	local title = "Utter needs attention"
	local detail = ""

	if type(snap) == "table" then
		if snap.connected == false then
			title = "Utter runner unreachable"
			detail = tostring(snap.error or snap.reason or "the runner socket is unavailable")
		elseif type(snap.problems) == "table" and #snap.problems > 0 then
			title = "Utter plugin problem"
			detail = table.concat(snap.problems, ", ")
		else
			detail = tostring(snap.reason or "the assistant needs a human")
		end
	end

	local rows = {
		ui.row({ gap = 10, align = "center" }, {
			ui.glyph({ name = glyphName, size = 20, color = color }),
			ui.label({
				text = title,
				color = color,
				fontWeight = "bold",
				flexGrow = 1,
				maxLines = 2,
			}),
		}),
	}
	if detail ~= "" then
		table.insert(rows, ui.label({
			text = detail,
			color = "on_surface_variant",
			fontSize = 12,
			maxLines = 3,
		}))
	end
	table.insert(rows, ui.label({
		text = "Closes automatically on recovery.",
		color = "on_surface_variant",
		fontSize = 11,
	}))

	panel.render(ui.column({ gap = 8, align = "stretch" }, rows))
end

function onOpen(context)
	render(decodeContext(context))
end
