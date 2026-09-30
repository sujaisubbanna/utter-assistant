--!nonstrict
-- Utter assistant status poller.
--
-- Polls `python -m assistant status --json` (the runner.status passthrough:
-- `{connected, plugins:[{id,kind,epoch,status}]}`) and publishes a normalized
-- snapshot to shared state. Raises the persistent attention overlay panel when
-- the runner is unreachable or a plugin is not healthy, and closes it on
-- recovery. Transitions only: the panel is not reopened on every poll.
--
-- The interpreter and repo root are resolved from the plugin settings, with an
-- install-time default substituted by scripts/install-noctalia-widget.sh.

local STATUS_KEY = "utter_status"
local COMMAND_KEY = "utter_cmd"
local PANEL_ID = "utter/utter:attention"

-- Installer may replace this token with the absolute checkout path.
local INSTALL_REPO = "__UTTER_REPO__"

local busy = false
local prevState = ""
local panelOpen = false
local lastCtx = ""

-- Transient plugin states are "still coming up", not "needs a human".
local TRANSIENT = { starting = true, created = true, initializing = true }
-- Statuses that should colour the widget/panel as a hard error.
local HARD_ERROR = { error = true, failed = true, crashed = true, unhealthy = true }

local function trim(s)
	return tostring(s or ""):match("^%s*(.-)%s*$")
end

local function repoRoot()
	local r = trim(noctalia.getConfig("repo_root"))
	if r ~= "" then
		return r
	end
	local isToken = INSTALL_REPO == "" or INSTALL_REPO:find("__UTTER", 1, true) ~= nil
	if not isToken then
		return INSTALL_REPO
	end
	if type(noctalia.getenv) == "function" then
		local e = noctalia.getenv("UTTER_REPO")
		if type(e) == "string" and trim(e) ~= "" then
			return trim(e)
		end
	end
	return INSTALL_REPO
end

local function fileExists(path)
	if type(noctalia.commandExists) == "function" and noctalia.commandExists(path) then
		return true
	end
	if type(noctalia.readFile) == "function" then
		local ok = pcall(noctalia.readFile, path)
		if ok then
			return true
		end
	end
	return false
end

local function pythonCmd()
	local p = trim(noctalia.getConfig("python_cmd"))
	if p ~= "" then
		return p
	end
	local root = repoRoot()
	local candidates = {
		root .. "/.venv-agent/bin/python",
		root .. "/.venv/bin/python",
	}
	for _, c in ipairs(candidates) do
		if fileExists(c) then
			return c
		end
	end
	return "python3"
end

local function backendArgv()
	-- argv form: `env PYTHONPATH=<repo> <python> -m assistant status --json`
	-- (PYTHONPATH lets `-m assistant` resolve without relying on cwd).
	return {
		"env",
		"PYTHONPATH=" .. repoRoot(),
		pythonCmd(),
		"-m",
		"assistant",
		"status",
		"--json",
	}
end

local function refreshMs()
	local s = tonumber(noctalia.getConfig("refresh_seconds")) or 2
	s = math.max(1, math.min(30, math.floor(s)))
	return s * 1000
end

local function panelShow(ctx)
	local enc = noctalia.json.encode(ctx)
	if panelOpen and enc == lastCtx then
		return
	end
	panelOpen = true
	lastCtx = enc
	noctalia.runAsync({ "noctalia", "msg", "panel-open", PANEL_ID, enc }, function(_) end)
end

local function panelHide()
	if not panelOpen then
		return
	end
	panelOpen = false
	lastCtx = ""
	noctalia.runAsync({ "noctalia", "msg", "panel-close", PANEL_ID }, function(_) end)
end

-- Normalize a runAsync result into the snapshot consumed by the widget/panel.
local function normalize(result)
	local snap = {
		connected = false,
		state = "error",
		reason = "runner unreachable",
		error = "",
		plugins = {},
		problems = {},
		ok = false,
	}

	local code = (type(result) == "table" and tonumber(result.exitCode)) or 1
	local raw = (type(result) == "table" and tostring(result.stdout or "")) or ""
	local decoded = nil
	if raw ~= "" then
		local ok, d = pcall(noctalia.json.decode, raw)
		if ok and type(d) == "table" then
			decoded = d
		end
	end

	local connected = code == 0 and type(decoded) == "table" and type(decoded.plugins) == "table"
	if connected then
		local plugins = decoded.plugins
		local problems = {}
		local working = 0
		local hardError = false
		for _, p in ipairs(plugins) do
			local st = tostring(p.status or "")
			if st == "ok" or st == "" then
				-- healthy (empty status treated as ok)
			elseif TRANSIENT[st] == true then
				working = working + 1
			else
				if HARD_ERROR[st] == true then
					hardError = true
				end
				table.insert(problems, string.format("%s (%s)", tostring(p.id or "?"), st))
			end
		end
		snap.connected = true
		snap.plugins = plugins
		snap.problems = problems
		if #problems > 0 then
			snap.state = hardError and "error" or "attention"
			snap.reason = "plugin needs attention"
		elseif working > 0 then
			snap.state = "working"
			snap.reason = "assistant starting"
			snap.ok = true
		else
			snap.state = "idle"
			snap.reason = "all plugins healthy"
			snap.ok = true
		end
	else
		-- Disconnected or unexpected output.
		if type(decoded) == "table" and type(decoded.error) == "string" and decoded.error ~= "" then
			snap.error = decoded.error
		elseif type(result) == "table" and tostring(result.stderr or "") ~= "" then
			snap.error = trim(tostring(result.stderr))
		end
		if snap.error == "" then
			snap.error = "the runner socket is unavailable"
		end
	end

	if type(noctalia.nowMs) == "function" then
		local ms = noctalia.nowMs()
		if type(ms) == "number" and ms > 0 then
			snap.updated_at = math.floor(ms / 1000)
		end
	end
	return snap
end

local function poll()
	if busy then
		return
	end
	busy = true
	local started = noctalia.runAsync(backendArgv(), function(result)
		busy = false
		local snap = normalize(result)
		if (not snap.connected) or (#snap.problems > 0) then
			panelShow(snap)
		else
			panelHide()
		end
		if snap.state ~= prevState then
			noctalia.log(string.format(
				"utter: state -> %s (connected=%s, plugins=%d, problems=%d)",
				snap.state, tostring(snap.connected), #snap.plugins, #snap.problems))
			prevState = snap.state
		end
		noctalia.state.set(STATUS_KEY, snap)
	end, 8000)
	if not started then
		busy = false
		local snap = normalize(nil)
		panelShow(snap)
		noctalia.state.set(STATUS_KEY, snap)
	end
end

noctalia.state.watch(COMMAND_KEY, function(v)
	if type(v) == "table" and (v.action == "refresh") then
		poll()
	end
end)

noctalia.setUpdateInterval(refreshMs())
poll()

function update()
	poll()
end

function onConfigChanged()
	noctalia.setUpdateInterval(refreshMs())
	poll()
end

function onIpc(event, _)
	if event == "refresh" then
		poll()
	end
end
