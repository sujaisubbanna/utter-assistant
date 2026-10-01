#!/usr/bin/env python3
"""Compositor detection, backend selection and the KWin (KDE Plasma) backend.

Runs on any Linux box without a live KWin: it exercises the pure parts
(detection rules, the config override, argv / D-Bus call construction, the
niri -> KWin action table, the unsupported-capability path, GVariant / qdbus /
dbus-send reply parsing, the KWin script templates) and the dispatch points in
the shared modules. The only live piece is the stdlib D-Bus receiver, which is
exercised against the local session bus when one exists (skipped otherwise).
It never runs a compositor command: every action is dry-run.

Usage::

    python3 tests/platform/test_compositor_detection.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ok = True
_skipped = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}{(' -> ' + extra) if extra and not cond else ''}")


def skip(name: str, why: str) -> None:
    global _skipped
    _skipped += 1
    print(f"-- skip {name}: {why}")


class env:
    """Temporarily replace the process environment (os.environ) wholesale."""

    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self.saved = dict(os.environ)
        for k in ("XDG_CURRENT_DESKTOP", "KDE_FULL_SESSION", "KDE_SESSION_VERSION", "DESKTOP_SESSION",
                  "XDG_SESSION_DESKTOP", "XDG_SESSION_TYPE", "NIRI_SOCKET", "UTTER_COMPOSITOR",
                  "UTTER_DRY_RUN", "UTTER_DBUS_TOOL", "UTTER_PLATFORM"):
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in self.values.items() if v is not None})
        compositor.reset_cache()
        kwin.reset_cache()
        clipboard.reset_cache()
        return self

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self.saved)
        compositor.reset_cache()
        kwin.reset_cache()
        clipboard.reset_cache()


from utter.context import clipboard, compositor, desktop  # noqa: E402
from utter.context.backends import dbus, fallback, kwin  # noqa: E402
from utter.context.backends import niri as niri_backend  # noqa: E402

# --------------------------------------------------------------------------- #
# 1. detection rules (pure, env mapping in / Detection out)
# --------------------------------------------------------------------------- #
d = compositor.detect({"XDG_CURRENT_DESKTOP": "KDE", "KDE_FULL_SESSION": "true", "XDG_SESSION_TYPE": "wayland",
                       "KDE_SESSION_VERSION": "6"})
check("detect: XDG_CURRENT_DESKTOP=KDE -> kwin", d.compositor == "kwin", d.compositor)
check("detect: plasma version + session type recorded", d.plasma_version == "6" and d.session_type == "wayland")
check("detect: evidence names the variable", any("XDG_CURRENT_DESKTOP" in e for e in d.evidence), str(d.evidence))
check("detect: KDE_FULL_SESSION alone -> kwin",
      compositor.detect({"KDE_FULL_SESSION": "true"}).compositor == "kwin")
check("detect: KDE_SESSION_VERSION alone -> kwin",
      compositor.detect({"KDE_SESSION_VERSION": "5"}).compositor == "kwin")
check("detect: DESKTOP_SESSION=plasmawayland -> kwin",
      compositor.detect({"DESKTOP_SESSION": "plasmawayland"}).compositor == "kwin")
check("detect: XDG_SESSION_DESKTOP=plasma -> kwin",
      compositor.detect({"XDG_SESSION_DESKTOP": "plasma"}).compositor == "kwin")
check("detect: colon list 'KDE:ubuntu' -> kwin",
      compositor.detect({"XDG_CURRENT_DESKTOP": "KDE:ubuntu"}).compositor == "kwin")
check("detect: lowercase kde -> kwin", compositor.detect({"XDG_CURRENT_DESKTOP": "kde"}).compositor == "kwin")
check("detect: XDG_CURRENT_DESKTOP=niri -> niri", compositor.detect({"XDG_CURRENT_DESKTOP": "niri"}).compositor == "niri")
check("detect: NIRI_SOCKET alone -> niri", compositor.detect({"NIRI_SOCKET": "/run/x.sock"}).compositor == "niri")
check("detect: XDG_SESSION_DESKTOP=niri -> niri", compositor.detect({"XDG_SESSION_DESKTOP": "niri"}).compositor == "niri")
check("detect: XDG_CURRENT_DESKTOP wins over a stale NIRI_SOCKET",
      compositor.detect({"XDG_CURRENT_DESKTOP": "KDE", "NIRI_SOCKET": "/run/stale.sock"}).compositor == "kwin")
check("detect: GNOME -> unknown", compositor.detect({"XDG_CURRENT_DESKTOP": "GNOME"}).compositor == "unknown")
check("detect: empty env -> unknown with evidence", compositor.detect({}).compositor == "unknown"
      and compositor.detect({}).evidence)

# --------------------------------------------------------------------------- #
# 2. backend selection: auto / explicit override / env override / unknown name
# --------------------------------------------------------------------------- #
plasma_env = {"XDG_CURRENT_DESKTOP": "KDE", "KDE_FULL_SESSION": "true"}
niri_env = {"XDG_CURRENT_DESKTOP": "niri", "NIRI_SOCKET": "/run/niri.sock"}
r = compositor.resolve("auto", plasma_env)
check("resolve: auto + Plasma env -> kwin", r.active == "kwin" and r.requested == "auto", r.reason)
r = compositor.resolve("auto", niri_env)
check("resolve: auto + niri env -> niri", r.active == "niri", r.reason)
r = compositor.resolve("kwin", niri_env)
check("resolve: explicit kwin overrides a niri session", r.active == "kwin" and "override" in r.reason)
r = compositor.resolve("niri", plasma_env)
check("resolve: explicit niri overrides a Plasma session", r.active == "niri" and "override" in r.reason)
check("resolve: alias 'plasma' -> kwin", compositor.resolve("plasma", {}).active == "kwin")
r = compositor.resolve("sway", {"XDG_CURRENT_DESKTOP": "sway"})
check("resolve: unknown name + unknown env -> unknown (no crash)", r.active == "unknown" and "fell back" in r.reason)
r = compositor.resolve("auto", {"XDG_CURRENT_DESKTOP": "GNOME"})
check("resolve: auto + GNOME -> unknown, reason explains", r.active == "unknown" and "no supported" in r.reason)
check("resolve: UTTER_COMPOSITOR env override wins", compositor.resolve(None, {**niri_env, "UTTER_COMPOSITOR": "kwin"}).active == "kwin")
check("backend_for: niri/kwin/unknown modules", backend_for_names := (
    compositor.backend_for("niri").NAME, compositor.backend_for("kwin").NAME, compositor.backend_for("x").NAME
) == ("niri", "kwin", "unknown"), str(backend_for_names))

# config: [general] compositor default + override via a temp config file
from utter.config import Config, load_config  # noqa: E402

check("config: [general] compositor defaults to auto", Config().general.compositor == "auto")
check("config: [kwin] defaults", Config().kwin.screenshot == "auto" and Config().kwin.clipboard == "auto"
      and Config().kwin.use_kdotool and Config().kwin.pointer_abs_factor == 1.0)
with tempfile.TemporaryDirectory() as td:
    cfg_path = Path(td) / "config.toml"
    cfg_path.write_text('[general]\ncompositor = "kwin"\n[kwin]\nscreenshot = "spectacle"\nuse_kdotool = false\n')
    cfg = load_config(cfg_path)
    check("config: [general] compositor override parsed", cfg.general.compositor == "kwin")
    check("config: [kwin] keys parsed", cfg.kwin.screenshot == "spectacle" and cfg.kwin.use_kdotool is False)
    check("config: Linux defaults untouched", cfg.stt.backend == "faster_whisper" and cfg.ptt.dictation_key == "KEY_F13")

# the config value is what `configured()` returns when no env override is present
with env(XDG_CONFIG_HOME=tempfile.mkdtemp()):
    cfgdir = Path(os.environ["XDG_CONFIG_HOME"]) / "utter"
    cfgdir.mkdir(parents=True)
    (cfgdir / "config.toml").write_text('[general]\ncompositor = "kwin"\n')
    compositor.reset_cache()
    check("configured(): reads [general] compositor from the config file", compositor.configured() == "kwin")
    check("resolve(): config override selects kwin even in a niri env",
          compositor.resolve(None, {"XDG_CURRENT_DESKTOP": "niri"}).active == "kwin")

# --------------------------------------------------------------------------- #
# 3. provider dispatch: niri stays the niri module; Plasma -> kwin module
# --------------------------------------------------------------------------- #
with env(XDG_CURRENT_DESKTOP="niri", NIRI_SOCKET="/run/niri.sock"):
    check("desktop.provider(): niri session -> utter.context.niri (unchanged)",
          desktop.provider().__name__ == "utter.context.niri")
    check("compositor.active(): niri backend wraps the same functions",
          compositor.active().focused_window is desktop.provider().focused_window)
with env(**plasma_env):
    check("desktop.provider(): Plasma session -> kwin backend", desktop.provider().__name__ == "utter.context.backends.kwin")
    check("desktop.backend(): kwin", desktop.backend().NAME == "kwin")
with env(UTTER_COMPOSITOR="kwin", XDG_CURRENT_DESKTOP="niri"):
    check("desktop.provider(): UTTER_COMPOSITOR=kwin forces kwin in a niri session",
          desktop.provider().NAME == "kwin")
with env(XDG_CURRENT_DESKTOP="GNOME"):
    check("desktop.provider(): unknown -> fallback module", desktop.provider().NAME == "unknown")
    check("fallback: list_windows empty, focused None", desktop.list_windows() == [] and desktop.focused_window() is None)
    check("fallback: focus_window False", desktop.focus_window(1) is False)
    out = fallback.close_window(3)
    check("fallback: close_window -> structured unsupported", out.unsupported and not out.ok and out.backend == "unknown")
    out = fallback.run_action("focus-column-left")
    check("fallback: run_action -> structured unsupported", out.unsupported and "compositor not recognised" in out.detail)

# --------------------------------------------------------------------------- #
# 4. niri backend: argv identical to the old executor path; dry-run
# --------------------------------------------------------------------------- #
check("niri: action_argv == old `niri msg action <cmd> <args>`",
      niri_backend.action_argv("focus-workspace", [3]) == ["niri", "msg", "action", "focus-workspace", "3"])
check("niri: capabilities all true", all(niri_backend.capabilities().values()))
with env(UTTER_DRY_RUN="1"):
    out = niri_backend.run_action("close-window")
    check("niri: dry-run run_action records argv", out.ok and out.argv == [["niri", "msg", "action", "close-window"]])
    out = niri_backend.move_window_to_workspace(2, window_id=7)
    check("niri: move_window_to_workspace argv", out.argv == [["niri", "msg", "action", "move-window-to-workspace", "--window-id", "7", "2"]])
    out = niri_backend.maximize_window(5)
    check("niri: maximize focuses then maximize-column", out.argv == [
        ["niri", "msg", "action", "focus-window", "--id", "5"], ["niri", "msg", "action", "maximize-column"]])
    check("niri: switch_workspace", niri_backend.switch_workspace(4).argv == [["niri", "msg", "action", "focus-workspace", "4"]])
    check("niri: close by id", niri_backend.close_window(9).argv == [["niri", "msg", "action", "close-window", "--id", "9"]])

# the executor's niri handler still produces the same command on niri
from utter.executor import Executor  # noqa: E402
from utter.types import Action, ActionResult, Step  # noqa: E402

with env(XDG_CURRENT_DESKTOP="niri", UTTER_DRY_RUN="1"):
    ex = Executor(lambda with_a11y=False: None, None)
    res = ex._do_niri(Step(Action.NIRI, {"command": "focus-column-left", "args": []}))
    check("executor: _do_niri on niri -> ok, not unsupported, same detail prefix",
          res.ok and not res.unsupported and res.detail.startswith("niri focus-column-left"), res.detail)
check("ActionResult: unsupported flag defaults False (back-compat positional ctor)",
      ActionResult(True, Action.NIRI, __import__("utter.types", fromlist=["Tier"]).Tier.APP, "d", 1.0).unsupported is False)

# --------------------------------------------------------------------------- #
# 5. D-Bus argv construction for every CLI tool
# --------------------------------------------------------------------------- #
c = kwin.call_set_current_desktop(2)
check("dbus: gdbus argv", c.argv("gdbus") == ["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path",
                                              "/KWin", "--method", "org.kde.KWin.setCurrentDesktop", "2"])
check("dbus: qdbus6 argv", c.argv("qdbus6") == ["qdbus6", "org.kde.KWin", "/KWin", "org.kde.KWin.setCurrentDesktop", "2"])
check("dbus: dbus-send argv", c.argv("dbus-send") == ["dbus-send", "--session", "--print-reply", "--dest=org.kde.KWin",
                                                      "/KWin", "org.kde.KWin.setCurrentDesktop", "int32:2"])
s = kwin.call_shortcut("Window Close")
check("dbus: kglobalaccel invokeShortcut (gdbus quotes the string)",
      s.argv("gdbus")[-2:] == ["org.kde.kglobalaccel.Component.invokeShortcut", "'Window Close'"]
      and s.argv("gdbus")[4] == "org.kde.kglobalaccel" and s.argv("gdbus")[6] == "/component/kwin")
check("dbus: kglobalaccel dbus-send string arg", s.argv("dbus-send")[-1] == "string:Window Close")
check("dbus: gvariant string escaping", dbus.gvariant_literal("it's a \\ test") == "'it\\'s a \\\\ test'")
check("dbus: gvariant dict of variants",
      dbus.gvariant_literal({"interactive": dbus.Variant(False), "handle_token": dbus.Variant("t")})
      == "{'interactive': <false>, 'handle_token': <'t'>}")
p = kwin.call_vdm_prop("current")
check("dbus: Properties.Get for VirtualDesktopManager",
      p.argv("gdbus")[-3:] == ["org.freedesktop.DBus.Properties.Get", "'org.kde.KWin.VirtualDesktopManager'", "'current'"])
check("dbus: loadScript args (path, pluginName)", kwin.call_load_script("/tmp/a.js", "utter-x").argv("qdbus6")
      == ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript", "/tmp/a.js", "utter-x"])
check("dbus: run script path Plasma 6 vs 5", kwin.call_run_script(7, True).path == "/Scripting/Script7"
      and kwin.call_run_script(7, False).path == "/7")
check("dbus: klipper getClipboardContents", kwin.call_klipper_get().argv("gdbus")[-1] == "org.kde.klipper.klipper.getClipboardContents")
check("dbus: portal Screenshot call is gdbus-only (containers)", kwin.call_portal_screenshot("tok").argv("gdbus")[-1]
      == "{'interactive': <false>, 'handle_token': <'tok'>}")
try:
    kwin.call_portal_screenshot("tok").argv("qdbus6")
    check("dbus: qdbus refuses container args", False)
except TypeError:
    check("dbus: qdbus refuses container args", True)
check("dbus: pick_tool honours UTTER_DBUS_TOOL", dbus.pick_tool({"UTTER_DBUS_TOOL": "qdbus6"}) == "qdbus6")
check("dbus: tool_kind", (dbus.tool_kind("/usr/bin/qdbus6"), dbus.tool_kind("dbus-send"), dbus.tool_kind("gdbus"))
      == ("qdbus", "dbus-send", "gdbus"))
check("dbus: no shell anywhere in argv", all(" " not in a or a.startswith("'") for a in c.argv("gdbus")))

# reply parsing
check("parse gdbus: ('x',) -> x", dbus.parse_gvariant("('x',)") == "x")
check("parse gdbus: (true,)", dbus.parse_gvariant("(true,)") is True)
check("parse gdbus: (uint32 3,)", dbus.parse_gvariant("(uint32 3,)") == 3)
check("parse gdbus: variant unwrap", dbus.parse_gvariant("(<'uuid-1'>,)") == "uuid-1")
check("parse gdbus: a(uss) desktops", dbus.parse_gvariant("(<[(uint32 0, 'a', 'Desktop 1'), (1, 'b', 'Two')]>,)")
      == [(0, "a", "Desktop 1"), (1, "b", "Two")])
check("parse gdbus: escapes", dbus.parse_gvariant("('it\\'s\\n',)") == "it's\n")
check("parse gdbus: @as []", dbus.parse_gvariant("(@as [],)") == [])
check("parse qdbus: scalar + lines", dbus.parse_qdbus("true\n") is True and dbus.parse_qdbus("a\nb\n") == ["a", "b"])
check("parse dbus-send: string + variant", dbus.parse_dbus_send('method return ...\n   string "hi"\n') == "hi"
      and dbus.parse_dbus_send('method return\n   variant       string "clip"\n') == "clip"
      and dbus.parse_dbus_send('method return\n   int32 2\n') == 2)

# --------------------------------------------------------------------------- #
# 6. niri action name -> KWin call mapping and the unsupported path (dry-run)
# --------------------------------------------------------------------------- #
check("map: close-window -> Window Close", kwin.shortcut_for("close-window").args == ("Window Close",))
check("map: focus-workspace 3 -> setCurrentDesktop(3)", kwin.shortcut_for("focus-workspace", [3]).method == "setCurrentDesktop"
      and kwin.shortcut_for("focus-workspace", [3]).args == (3,))
check("map: move-window-to-workspace 2 -> Window to Desktop 2",
      kwin.shortcut_for("move-window-to-workspace", [2]).args == ("Window to Desktop 2",))
check("map: focus-workspace without number -> None", kwin.shortcut_for("focus-workspace", []) is None)
check("map: screenshot-screen -> spectacle component", kwin.shortcut_for("screenshot-screen").path == "/component/org_kde_spectacle_desktop")
check("map: toggle-window-floating deliberately unsupported", kwin.shortcut_for("toggle-window-floating") is None)
check("map: quit never mapped", kwin.shortcut_for("quit") is None)
check("map: unknown action -> None", kwin.shortcut_for("no-such-action") is None)
check("map: every curated NIRI_MAP phrase resolves to a call or an explicit None", all(
    (cmd in kwin.ACTION_MAP) or kwin.shortcut_for(cmd, args) is None
    for cmd, args in __import__("utter.router.rules", fromlist=["NIRI_MAP"]).NIRI_MAP.values()))

with env(**plasma_env, UTTER_DRY_RUN="1", UTTER_DBUS_TOOL="gdbus"):
    out = kwin.run_action("close-window")
    check("kwin: run_action close-window -> kglobalaccel argv", out.ok and out.argv[0][4] == "org.kde.kglobalaccel"
          and out.argv[0][-1] == "'Window Close'", str(out.argv))
    out = kwin.run_action("focus-workspace", [3])
    check("kwin: run_action focus-workspace 3 -> setCurrentDesktop", out.ok and out.argv[0][-2:] == ["org.kde.KWin.setCurrentDesktop", "3"])
    out = kwin.run_action("toggle-window-floating")
    check("kwin: unsupported action -> Outcome(unsupported) not an exception",
          out.unsupported and not out.ok and out.backend == "kwin" and out.capability == "compositor_action"
          and "toggle-window-floating" in out.detail)
    out = kwin.run_action("focus-workspace", [])
    check("kwin: desktop action without number -> unsupported with reason", out.unsupported and "desktop number" in out.detail)
    check("kwin: switch_workspace(2)", kwin.switch_workspace(2).argv[0][-1] == "2")
    check("kwin: switch_workspace(0) -> error not crash", not kwin.switch_workspace(0).ok)
    check("kwin: close_window(None) -> Window Close", kwin.close_window().argv[0][-1] == "'Window Close'")
    check("kwin: minimize_window(None) -> Window Minimize", kwin.minimize_window().argv[0][-1] == "'Window Minimize'")
    check("kwin: maximize_window(None) -> Window Maximize", kwin.maximize_window().argv[0][-1] == "'Window Maximize'")
    check("kwin: move_window_to_workspace(4) -> Window to Desktop 4", kwin.move_window_to_workspace(4).argv[0][-1] == "'Window to Desktop 4'")
    check("kwin: unknown int id -> error outcome", not kwin.close_window(424242).ok and not kwin.close_window(424242).unsupported)
    check("kwin: focus_window_on_workspace == activation", kwin.focus_window_on_workspace(424242) is False)
    # executor dispatch under a simulated Plasma session
    ex = Executor(lambda with_a11y=False: None, None)
    res = ex._do_niri(Step(Action.NIRI, {"command": "close-window", "args": []}))
    check("executor: _do_niri on kwin -> D-Bus, ok", res.ok and not res.unsupported and "invokeShortcut" in res.detail, res.detail)
    res = ex._do_niri(Step(Action.NIRI, {"command": "consume-window-into-column", "args": []}))
    check("executor: _do_niri unsupported -> ActionResult(ok=False, unsupported=True)", not res.ok and res.unsupported, res.detail)
    plan = kwin.plan()
    check("kwin: plan() lists D-Bus argv for every capability", {"switch_workspace", "close (focused)", "screenshot", "clipboard"} <= set(plan))
    probe = compositor.probe()
    check("probe: Plasma env -> active kwin with evidence", probe["active"] == "kwin" and probe["detected"]["compositor"] == "kwin"
          and probe["detected"]["evidence"])
    text = compositor.format_probe(probe)
    check("probe: human format mentions backend + plan", "active:     kwin" in text and "plan (argv" in text)

# no D-Bus tool at all -> every action is a structured unsupported result
with env(**plasma_env, UTTER_DBUS_TOOL="", PATH="/nonexistent"):
    kwin.reset_cache()
    check("kwin without tools: available() False", kwin.available() is False)
    caps = kwin.capabilities()
    check("kwin without tools: capabilities all False", not any(caps.values()), str(caps))
    check("kwin without tools: run_action unsupported", kwin.run_action("close-window").unsupported)
    check("kwin without tools: switch_workspace unsupported", kwin.switch_workspace(1).unsupported)
    check("kwin without tools: close_window unsupported", kwin.close_window().unsupported)
    check("kwin without tools: list_windows [] (no crash)", kwin.list_windows() == [])
    try:
        kwin.screenshot(str(Path(tempfile.mkdtemp()) / "x.png"))
        check("kwin without tools: screenshot raises CompositorUnsupported", False)
    except compositor.CompositorUnsupported as exc:
        check("kwin without tools: screenshot raises CompositorUnsupported", exc.capability == "screenshot"
              and exc.outcome().unsupported)

# --------------------------------------------------------------------------- #
# 7. KWin window ids, script templates, JSON payload parsing, kdotool argv
# --------------------------------------------------------------------------- #
a = kwin.window_int("{11111111-2222-3333-4444-555555555555}")
b = kwin.window_int("{11111111-2222-3333-4444-555555555555}")
c2 = kwin.window_int("{aaaa}")
check("ids: uuid -> stable int, distinct uuids distinct ints", a == b and a != c2 and kwin.window_uuid(a).startswith("{1111"))
check("ids: unknown int -> None", kwin.window_uuid(10**9) is None)
js = kwin.query_script("org.utter.kwin.p1")
check("script: query uses workspace.windowList (6) and clientList (5)", "workspace.windowList" in js and "workspace.clientList" in js)
check("script: query reports via callDBus to our bus name",
      'callDBus("org.utter.kwin.p1", "/", "org.utter.kwin", "result"' in js)
js = kwin.action_script('{abc}', "activate")
check("script: activate sets activeWindow / activeClient", "workspace.activeWindow = w" in js and "workspace.activeClient = w" in js
      and 'var target = "{abc}"' in js)
js = kwin.action_script('{abc}', "move_to_desktop", 3)
check("script: move_to_desktop uses desktops[n-1] (6) and .desktop (5)", "workspace.desktops[3 - 1]" in js and "w.desktop = 3" in js)
js = kwin.action_script('"quoted"', "close")
check("script: target is JSON-escaped", 'var target = "\\"quoted\\""' in js and "w.closeWindow();" in js)
wins = kwin.parse_windows_json(json.dumps({"windows": [
    {"id": "{u1}", "app_id": "org.kde.konsole", "title": "bash", "pid": 42, "workspace_id": 2, "is_focused": True},
    {"id": "{u2}", "app_id": "firefox", "title": "Mozilla", "pid": 43, "workspace_id": 1},
    {"bad": True}, "junk"]}))
check("payload: windows parsed, bad entries skipped", [w.app_id for w in wins] == ["org.kde.konsole", "firefox"]
      and wins[0].is_focused and wins[0].workspace_id == 2 and wins[1].pid == 43)
check("payload: ids mapped to ints", all(isinstance(w.id, int) for w in wins) and kwin.window_uuid(wins[0].id) == "{u1}")
check("payload: garbage -> []", kwin.parse_windows_json("not json") == [])
check("kdotool argv", kwin.kdotool_argv("windowactivate", "{u1}") == ["kdotool", "windowactivate", "{u1}"])
check("spectacle argv (background, no notify, fullscreen, output)", kwin.spectacle_argv("/tmp/s.png")
      == ["spectacle", "-b", "-n", "-f", "-o", "/tmp/s.png"])
with env(**plasma_env, UTTER_DBUS_TOOL="gdbus"):
    cfg_stub = SimpleNamespace(screenshot="spectacle", clipboard="auto", use_kdotool=True, use_scripts=True,
                               script_timeout_s=1.0, pointer_abs_factor=1.0)
    kwin._CFG = cfg_stub
    check("kwin: screenshot=spectacle without spectacle -> no method", kwin.screenshot_method() in (None, "spectacle"))
    kwin._CFG = SimpleNamespace(**{**vars(cfg_stub), "screenshot": "grim"})
    check("kwin: screenshot=grim honoured when grim exists", kwin.screenshot_method() == ("grim" if __import__("shutil").which("grim") else None))
    kwin.reset_cache()

# --------------------------------------------------------------------------- #
# 8. clipboard / keyboard / mouse / vision dispatch
# --------------------------------------------------------------------------- #
check("clipboard: kwin_order auto = klipper then wl-paste", clipboard.kwin_order("auto") == ("klipper", "wl-paste"))
check("clipboard: kwin_order wl-clipboard only", clipboard.kwin_order("wl-clipboard") == ("wl-paste",))
check("clipboard: linux default still wl-paste", clipboard.commands_for("linux")[0][0] == "wl-paste")
with env(**plasma_env, UTTER_DBUS_TOOL="gdbus"):
    calls: list = []
    orig_call = dbus.call
    dbus.call = lambda c, tool=None, timeout=0: calls.append(c) or dbus.Reply(True, "from klipper", c.argv("gdbus"), "")
    try:
        text = clipboard.get_clipboard()
    finally:
        dbus.call = orig_call
    check("clipboard: on kwin klipper is asked first", text == "from klipper" and calls and calls[0].dest == "org.kde.klipper")
    check("clipboard: working source remembered", clipboard._KWIN_WORKING == "klipper")
    clipboard.reset_cache()
    dbus.call = lambda c, tool=None, timeout=0: dbus.Reply(False, None, None, "no klipper")
    orig_run = clipboard._run_commands
    clipboard._run_commands = lambda commands: "from wl-paste"
    try:
        text = clipboard.get_clipboard()
    finally:
        dbus.call = orig_call
        clipboard._run_commands = orig_run
    check("clipboard: klipper missing -> wl-paste fallback, remembered", text == "from wl-paste" and clipboard._KWIN_WORKING == "wl-paste")

from utter.actions import keyboard, mouse  # noqa: E402

with env(XDG_CURRENT_DESKTOP="niri"):
    check("keyboard: niri does not prefer ydotool", keyboard.prefers_ydotool() is False)
    spawned: list = []
    orig = keyboard._run
    keyboard._run = lambda argv, env=None: spawned.append(argv) or SimpleNamespace(returncode=0, stderr="")
    keyboard.send_key("ctrl+t")
    keyboard._run = orig
    check("keyboard: niri still uses wtype first (unchanged)", spawned and spawned[0][0] == "wtype")
with env(**plasma_env):
    check("keyboard: kwin prefers ydotool", keyboard.prefers_ydotool() is True)
    spawned = []
    orig = keyboard._run
    keyboard._run = lambda argv, env=None: spawned.append(argv) or SimpleNamespace(returncode=0, stderr="")
    res = keyboard.send_key("ctrl+t")
    keyboard._run = orig
    check("keyboard: kwin sends the chord through ydotool first", spawned and spawned[0][:2] == ["ydotool", "key"] and res.ok, str(spawned))
    spawned = []
    orig = keyboard._run
    keyboard._run = lambda argv, env=None: spawned.append(argv) or SimpleNamespace(returncode=1 if argv[0] == "ydotool" else 0, stderr="no ydotoold")
    res = keyboard.send_key("ctrl+t")
    keyboard._run = orig
    check("keyboard: kwin falls back to wtype when ydotool fails", [a[0] for a in spawned] == ["ydotool", "wtype"] and res.ok)
    check("mouse: kwin abs factor from [kwin] pointer_abs_factor (1.0)", mouse._abs_factor() == 1.0)
with env(XDG_CURRENT_DESKTOP="niri"):
    check("mouse: niri keeps the measured default factor", mouse._abs_factor() == mouse._DEFAULT_ABS_FACTOR)

from utter.vision import screenshot as shot  # noqa: E402

with env(**plasma_env, UTTER_DBUS_TOOL="", PATH="/nonexistent"):
    kwin.reset_cache()
    try:
        shot.capture()
        check("vision: capture() on kwin without tools -> CompositorUnsupported", False)
    except compositor.CompositorUnsupported:
        check("vision: capture() on kwin without tools -> CompositorUnsupported", True)
    except Exception as exc:  # noqa: BLE001
        check("vision: capture() on kwin without tools -> CompositorUnsupported", False, repr(exc))
check("vision: capture_niri kept as the niri path", callable(shot.capture_niri))

# --------------------------------------------------------------------------- #
# 9. doctor report carries the compositor section (used by the settings app)
# --------------------------------------------------------------------------- #
from assistant import deps as deps_mod  # noqa: E402
from assistant import doctor  # noqa: E402

with env(**plasma_env, UTTER_DBUS_TOOL="gdbus"):
    sec = doctor.compositor_section()
    check("doctor: compositor section detected/active/capabilities", sec["detected"] == "kwin" and sec["active"] == "kwin"
          and set(compositor.CAPABILITIES) <= set(sec["capabilities"]))
    deps = deps_mod.probe_deps()
    check("doctor: kwin deps list dbus_cli/spectacle/kdotool, not wtype/grim",
          {"dbus_cli", "spectacle", "kdotool"} <= set(deps) and "grim" not in deps and "wtype" not in deps)
    check("doctor: human() mentions compositor", "compositor: detected kwin -> backend kwin" in doctor.human(
        {"runner": {}, "compositor": sec, "connected": False, "plugins": []}))
with env(XDG_CURRENT_DESKTOP="niri"):
    deps = deps_mod.probe_deps()
    check("doctor: niri deps unchanged (wtype, grim present)", {"wtype", "grim", "ydotool"} <= set(deps) and "spectacle" not in deps)

# --------------------------------------------------------------------------- #
# 10. live: the stdlib D-Bus receiver on the local session bus (skips without one)
# --------------------------------------------------------------------------- #
bus_path = dbus.session_bus_address()
gd = __import__("shutil").which("gdbus")
if bus_path and gd and os.path.exists(bus_path.lstrip("\0")):
    try:
        bus = dbus.LiteBus(timeout=5).connect()
        name = f"org.utter.kwin.test{os.getpid()}"
        owned = bus.request_name(name)
        check("litebus: Hello gives a unique name, RequestName succeeds", bus.unique.startswith(":") and owned)
        got: dict = {}
        t = threading.Thread(target=lambda: got.setdefault("args", bus.wait_for_call("result", timeout=5)))
        t.start()
        time.sleep(0.15)
        payload = json.dumps({"windows": [{"id": "{u}", "title": "it's \"ok\""}]})
        proc = subprocess.run([gd, "call", "--session", "--dest", name, "--object-path", "/", "--method",
                               "org.utter.kwin.result", dbus.gvariant_literal(payload)],
                              capture_output=True, text=True, timeout=10)
        t.join(timeout=6)
        check("litebus: gdbus call (as KWin's callDBus would) is received intact",
              proc.returncode == 0 and got.get("args") == [payload], f"{proc.stderr.strip()} {got}")
        bus.close()
    except (OSError, TimeoutError) as exc:
        skip("litebus live", str(exc))
else:
    skip("litebus live", "no session bus / gdbus here")

# header/body marshalling round-trip (pure)
msg = dbus.build_message(1, 7, [(1, "o", "/x"), (3, "s", "result"), (8, "g", "s")], dbus.marshal_body("s", ("héllo",)))
parsed, used = dbus.parse_message(msg)
check("litebus: build_message/parse_message round-trip", parsed is not None and used == len(msg) and parsed.member == "result"
      and parsed.args() == ["héllo"] and parsed.serial == 7)
check("litebus: partial buffer -> incomplete", dbus.parse_message(msg[:-3]) == (None, 0))
check("litebus: session bus address parsing", dbus.session_bus_address({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1/bus,guid=x"})
      == "/run/user/1/bus" and dbus.session_bus_address({"DBUS_SESSION_BUS_ADDRESS": "unix:abstract=/tmp/dbus-X"}) == "\0/tmp/dbus-X")

print()
print(f"{'ALL OK' if ok else 'FAILURES'} (skipped {_skipped})")
sys.exit(0 if ok else 1)
