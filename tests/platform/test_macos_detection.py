#!/usr/bin/env python3
"""Platform detection and macOS backend selection.

Runs on Linux without PyObjC: it exercises the pure parts (detection, config
defaults, the STT backend chain, key tables, chord parsing, the push-to-talk
edge detector, command builders) and the dispatch points in the shared
modules with the macOS backends stubbed out. It must never touch the desktop.

Usage::

    .venv-agent/bin/python tests/platform/test_macos_detection.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ok = True


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}{(' -> ' + extra) if extra and not cond else ''}")


def forced(value):
    """Context manager forcing UTTER_PLATFORM."""
    class _Ctx:
        def __enter__(self):
            self.prev = os.environ.get("UTTER_PLATFORM")
            if value is None:
                os.environ.pop("UTTER_PLATFORM", None)
            else:
                os.environ["UTTER_PLATFORM"] = value
            return self

        def __exit__(self, *exc):
            if self.prev is None:
                os.environ.pop("UTTER_PLATFORM", None)
            else:
                os.environ["UTTER_PLATFORM"] = self.prev
    return _Ctx()


# --------------------------------------------------------------------------- #
# 1. detection
# --------------------------------------------------------------------------- #
from utter import platform  # noqa: E402

with forced(None):
    native = platform.name()
    check("native name is linux here", native == "linux" if sys.platform.startswith("linux") else True, native)
    check("is_linux/is_macos are exclusive", platform.is_linux() != platform.is_macos())
with forced("darwin"):
    check("UTTER_PLATFORM=darwin forces macOS", platform.is_macos() and not platform.is_linux())
with forced("macos"):
    check("UTTER_PLATFORM=macos alias", platform.name() == "darwin")
with forced("linux"):
    check("UTTER_PLATFORM=linux forces Linux", platform.is_linux())
check("has_module(os) true", platform.has_module("os"))
check("has_module(nonexistent) false", not platform.has_module("utter_no_such_module_xyz"))

# --------------------------------------------------------------------------- #
# 2. config: [macos] section exists, Linux sections untouched
# --------------------------------------------------------------------------- #
from utter.config import Config, load_config  # noqa: E402

defaults = Config()
check("[macos] defaults: apple_speech -> whisper_cpp", defaults.macos.stt_backend == "apple_speech"
      and defaults.macos.stt_fallback == "whisper_cpp")
check("[macos] defaults: say / quartz", defaults.macos.tts_backend == "say"
      and defaults.macos.hotkey_backend == "quartz" and defaults.macos.injection == "quartz")
check("Linux [stt] default unchanged", defaults.stt.backend == "faster_whisper")
check("Linux [ptt] default unchanged", defaults.ptt.dictation_key == "KEY_F13"
      and defaults.ptt.assistant_key == "KEY_INSERT")
check("Linux [hotkey] default unchanged", defaults.hotkey.key == "KEY_RIGHTCTRL")

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "config.toml"
    p.write_text('[stt]\nbackend = "whisper_cpp"\n[macos]\nstt_backend = "vocamac"\ntts_voice = "Samantha"\n'
                 'dictation_key = "f13"\nunknown_key = 1\n')
    cfg = load_config(p)
    check("[macos] merges known keys", cfg.macos.stt_backend == "vocamac" and cfg.macos.tts_voice == "Samantha"
          and cfg.macos.dictation_key == "f13")
    check("[macos] ignores unknown keys", not hasattr(cfg.macos, "unknown_key"))
    check("[stt] still merges", cfg.stt.backend == "whisper_cpp")
    p.write_text('[stt]\nbackend = "whisper_cpp"\n')
    cfg = load_config(p)
    check("missing [macos] section -> defaults", cfg.macos == Config().macos)

repo_default = load_config(Path(__file__).resolve().parents[2] / "config.default.toml")
check("config.default.toml parses with [macos]", repo_default.macos.stt_backend == "apple_speech")

# --------------------------------------------------------------------------- #
# 3. STT backend chain
# --------------------------------------------------------------------------- #
from utter.voice import stt  # noqa: E402

stt_cfg = SimpleNamespace(backend="faster_whisper", model="x", device="cpu", compute_type="int8")
mac_cfg = Config().macos
none = lambda n: None  # noqa: E731

check("linux chain == [stt.backend]", stt.select_backends("linux", stt_cfg, mac_cfg) == ["faster_whisper"])
check("linux chain ignores [macos]", stt.select_backends("linux", stt_cfg, mac_cfg,
                                                          has_module=lambda n: True, which=none)
      == ["faster_whisper"])
check("darwin: apple first when Speech importable",
      stt.select_backends("darwin", stt_cfg, mac_cfg, has_module=lambda n: n in ("Speech", "Foundation"),
                          which=none) == ["apple_speech", "whisper_cpp"])
check("darwin: whisper first when only pywhispercpp present",
      stt.select_backends("darwin", stt_cfg, mac_cfg, has_module=lambda n: n == "pywhispercpp",
                          which=none) == ["whisper_cpp", "apple_speech"])
check("darwin: nothing importable keeps configured order",
      stt.select_backends("darwin", stt_cfg, mac_cfg, has_module=lambda n: False, which=none)
      == ["apple_speech", "whisper_cpp"])
check("darwin: fallback 'none' dropped",
      stt.select_backends("darwin", stt_cfg, SimpleNamespace(stt_backend="whisper_cpp", stt_fallback="none"),
                          has_module=lambda n: False, which=none) == ["whisper_cpp"])
check("darwin: duplicate collapsed",
      stt.select_backends("darwin", stt_cfg, SimpleNamespace(stt_backend="whisper_cpp", stt_fallback="whisper_cpp"),
                          has_module=lambda n: False, which=none) == ["whisper_cpp"])
check("darwin: vocamac counts as present when the app binary exists",
      stt.select_backends("darwin", stt_cfg, SimpleNamespace(stt_backend="apple_speech", stt_fallback="vocamac"),
                          has_module=lambda n: False, which=lambda n: "/usr/local/bin/VocaMac")
      == ["vocamac", "apple_speech"])

t = stt.Transcriber.for_platform(Config(), platform_name="linux")
check("Transcriber.for_platform(linux) == configured backend, no fallbacks",
      t.backend == "faster_whisper" and t.fallbacks == [])
t = stt.Transcriber.for_platform(Config(), platform_name="darwin")
check("Transcriber.for_platform(darwin) has a fallback", len(t.fallbacks) == 1
      and set([t.backend, *t.fallbacks]) == {"apple_speech", "whisper_cpp"})

# fallback chain: primary loader fails -> secondary loads
t = stt.Transcriber(stt_cfg, backend="apple_speech", fallbacks=["whisper_cpp"])
loaded = []


def _boom():
    raise RuntimeError("no permission")


t._load_apple_speech = _boom
t._load_whisper_cpp = lambda: loaded.append("whisper") or "fake-model"
t._ensure_loaded()
check("fallback chain: apple fails -> whisper_cpp active", t.backend == "whisper_cpp" and loaded == ["whisper"])

t = stt.Transcriber(stt_cfg, backend="apple_speech", fallbacks=[])
t._load_apple_speech = _boom
try:
    t._ensure_loaded()
    check("no fallbacks: error propagates", False)
except RuntimeError as exc:
    check("no fallbacks: error propagates", "no permission" in str(exc))

# --------------------------------------------------------------------------- #
# 4. TTS selection
# --------------------------------------------------------------------------- #
from utter.voice import tts  # noqa: E402
from utter.macos import tts as mac_tts  # noqa: E402

check("tts: linux -> none", tts.backend_for("linux", mac_cfg) == "none")
check("tts: darwin -> say", tts.backend_for("darwin", mac_cfg) == "say")
check("tts: darwin avspeech honoured", tts.backend_for("darwin", SimpleNamespace(tts_backend="AVSpeech")) == "avspeech")
with forced("linux"):
    check("tts.speak is a no-op on linux", tts.speak("hello", Config()) is False)
check("say argv: voice + rate", mac_tts.say_argv("hi there", "Samantha", 180)
      == ["say", "-v", "Samantha", "-r", "180", "--", "hi there"])
check("say argv: defaults", mac_tts.say_argv("-leading dash") == ["say", "--", "-leading dash"])
check("say: 'none' backend declines", mac_tts.speak("x", backend="none") is False)

# --------------------------------------------------------------------------- #
# 5. hotkeys: key names + edge detection
# --------------------------------------------------------------------------- #
from utter.macos import hotkey as mh  # noqa: E402

check("keycode right_option=61", mh.resolve_keycode("right_option") == 61)
check("keycode right_command=54", mh.resolve_keycode("Right-Command") == 54)
check("keycode f13=105", mh.resolve_keycode("F13") == 105)
check("keycode numeric passthrough", mh.resolve_keycode("63") == 63)
check("keycode evdev alias KEY_RIGHTALT", mh.resolve_keycode("KEY_RIGHTALT") == 61)
check("keycode evdev alias KEY_INSERT", mh.resolve_keycode("KEY_INSERT") == 114)
check("keycode evdev alias KEY_F13", mh.resolve_keycode("KEY_F13") == 105)
try:
    mh.resolve_keycode("KEY_NOPE")
    check("unknown key raises", False)
except ValueError:
    check("unknown key raises", True)

st = mh.PTTState(61)
alt = mh.MODIFIER_FLAG[61]
check("flags: press edge", st.feed("flags", 61, alt) == "press")
check("flags: held (no repeat)", st.feed("flags", 61, alt | mh.MODIFIER_FLAG[56]) is None)
check("flags: other key ignored", st.feed("flags", 54, mh.MODIFIER_FLAG[54]) is None)
check("flags: release edge", st.feed("flags", 61, 0) == "release")
check("flags: double release ignored", st.feed("flags", 61, 0) is None)
st = mh.PTTState(105)
check("keydown: press", st.feed(mh.EVENT_KEY_DOWN, 105, 0) == "press")
check("keydown: auto-repeat ignored", st.feed(mh.EVENT_KEY_DOWN, 105, 0) is None)
check("keyup: release", st.feed(mh.EVENT_KEY_UP, 105, 0) == "release")
check("flags on a non-modifier ignored", st.feed("flags", 105, 0xFFFF) is None)

# listen_many validates names before touching Quartz/pynput
try:
    mh.listen_many({})
    check("listen_many rejects empty", False)
except ValueError:
    check("listen_many rejects empty", True)
try:
    mh.listen_many({"KEY_NOPE": (lambda: None, lambda: None)})
    check("listen_many rejects unknown key", False)
except ValueError:
    check("listen_many rejects unknown key", True)

# --------------------------------------------------------------------------- #
# 6. injection: chord parsing + AppleScript builders
# --------------------------------------------------------------------------- #
from utter.macos import inject  # noqa: E402

flags, mods, code, key = inject.parse_chord("ctrl+shift+t")
check("chord ctrl+shift+t", code == inject.KEYCODES["t"] and mods == ["control down", "shift down"]
      and flags == (1 << 18) | (1 << 17))
flags, mods, code, key = inject.parse_chord("super+Return")
check("chord super -> command, Return -> 36", mods == ["command down"] and code == 36)
flags, mods, code, key = inject.parse_chord("Page_Down")
check("chord Page_Down", code == 121 and mods == [])
flags, mods, code, key = inject.parse_chord("cmd++")
check("chord cmd++ (plus key)", code == inject.KEYCODES["equal"])
for bad in ("", "hyper+a", "ctrl+nosuchkey"):
    try:
        inject.parse_chord(bad)
        check(f"bad chord {bad!r} raises", False)
    except ValueError:
        check(f"bad chord {bad!r} raises", True)
check("applescript key code", inject.applescript_key(["command down"], 17)
      == 'tell application "System Events" to key code 17 using {command down}')
check("applescript keystroke escapes quotes",
      inject.applescript_type('say "hi"\\') == 'tell application "System Events" to keystroke "say \\"hi\\"\\\\"')

# --------------------------------------------------------------------------- #
# 7. dispatch in the shared modules (macOS backends stubbed)
# --------------------------------------------------------------------------- #
from utter.actions import keyboard, launch, mouse  # noqa: E402
from utter.context import desktop  # noqa: E402
from utter.macos import pointer  # noqa: E402
from utter.types import Action, ActionResult, Tier  # noqa: E402

calls: list = []
inject.send_key = lambda chord, backend="quartz": calls.append(("key", chord, backend)) or ActionResult(True, Action.KEY, Tier.KEYBOARD, "stub")
inject.type_text = lambda text, backend="quartz": calls.append(("type", text, backend)) or ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD, "stub")
pointer.click_point = lambda x, y, button="left": calls.append(("click", x, y)) or ActionResult(True, Action.CLICK_POINT, Tier.KEYBOARD, "stub")
keyboard._macos_backend = lambda: "applescript"
with forced("darwin"):
    keyboard.send_key("cmd+t")
    keyboard.type_text("hello")
    mouse.click_point(10, 20)
    check("darwin: keyboard.send_key -> macos inject (configured backend)",
          ("key", "cmd+t", "applescript") in calls)
    check("darwin: keyboard.type_text -> macos inject", ("type", "hello", "applescript") in calls)
    check("darwin: mouse.click_point -> macos pointer", ("click", 10, 20) in calls)
    check("darwin: context provider is utter.macos.desktop", desktop.provider().__name__ == "utter.macos.desktop")
    check("darwin: url opener is `open`", launch._url_opener() == ["open"])
    check("darwin: bare app name -> open -a", launch._macos_app_argv("Safari") == ["open", "-a", "Safari"])
    check("darwin: bundle id -> open -b", launch._macos_app_argv("com.apple.Safari") == ["open", "-b", "com.apple.Safari"])
    check("darwin: absolute path spawns directly", launch._macos_app_argv(sys.executable) is None)
with forced("linux"):
    calls.clear()
    launch_spawned: list = []
    orig_run = keyboard._run
    keyboard._run = lambda argv, env=None: launch_spawned.append(argv) or SimpleNamespace(returncode=0, stderr="")
    keyboard.send_key("ctrl+t")
    keyboard._run = orig_run
    check("linux: keyboard.send_key still uses wtype", launch_spawned and launch_spawned[0][0] == "wtype"
          and not calls)
    check("linux: context provider is utter.context.niri", desktop.provider().__name__ == "utter.context.niri")
    check("linux: url opener is xdg-open", launch._url_opener() == ["xdg-open"])
    check("linux: no `open -a` rewriting", launch._macos_app_argv("Safari") is None)

# --------------------------------------------------------------------------- #
# 8. small command builders
# --------------------------------------------------------------------------- #
from utter.macos import notify, screenshot as mshot  # noqa: E402
from utter.context import clipboard  # noqa: E402

check("screencapture argv (display 0 -> -D 1)", mshot.screencapture_argv("/tmp/x.png", 0)
      == ["screencapture", "-x", "-t", "png", "-D", "1", "/tmp/x.png"])
check("screencapture argv (all)", mshot.screencapture_argv("/tmp/x.png")
      == ["screencapture", "-x", "-t", "png", "/tmp/x.png"])
check("notification applescript escapes", notify.applescript_notification('a "b"', "Utter", "s")
      == 'display notification "a \\"b\\"" with title "Utter" subtitle "s"')
check("clipboard: linux uses wl-paste", clipboard.commands_for("linux")[0][0] == "wl-paste")
check("clipboard: darwin uses pbpaste", clipboard.commands_for("darwin")[0][0] == "pbpaste")

# --------------------------------------------------------------------------- #
# 9. permissions (onboarding): table, deep links, Linux = unknown, state file, CLI
# --------------------------------------------------------------------------- #
import json  # noqa: E402
import subprocess  # noqa: E402

from utter.macos import permissions as perms  # noqa: E402

check("permissions: five in onboarding order", perms.PERMISSION_IDS
      == ["microphone", "speech_recognition", "input_monitoring", "accessibility", "screen_recording"])
check("permissions: deep link for input monitoring", perms.settings_url("input_monitoring")
      == "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")
check("permissions: deep link for accessibility", perms.settings_url("accessibility").endswith("?Privacy_Accessibility"))
try:
    perms.settings_url("nope")
    check("permissions: unknown id raises", False)
except KeyError:
    check("permissions: unknown id raises", True)
with forced("linux"):
    check("permissions: linux check -> unknown, no prompt", perms.check("accessibility") == perms.UNKNOWN
          and perms.request("microphone") == perms.UNKNOWN)
with tempfile.TemporaryDirectory() as tmp:
    os.environ["UTTER_PERMISSIONS_FILE"] = str(Path(tmp) / "perm.json")
    try:
        with forced("linux"):
            doc = perms.status_all(request=True)
        on_disk = json.loads((Path(tmp) / "perm.json").read_text())
        check("permissions: status_all writes the state file", on_disk["permissions"][0]["id"] == "microphone"
              and on_disk["all_granted"] is False and on_disk["platform"] == "linux")
        check("permissions: every item carries a settings_url", all(i["settings_url"].startswith("x-apple.")
                                                                      for i in doc["permissions"]))
        check("permissions: read_state round-trips", perms.read_state()["ts"] == on_disk["ts"])
        env = dict(os.environ, UTTER_PLATFORM="linux")
        proc = subprocess.run([sys.executable, "-m", "assistant", "macos-permissions", "--json"],
                              capture_output=True, text=True, env=env, cwd=str(Path(__file__).resolve().parents[2]))
        cli = json.loads(proc.stdout)
        check("CLI: assistant macos-permissions --json", proc.returncode == 1 and len(cli["permissions"]) == 5)
        proc = subprocess.run([sys.executable, "-m", "assistant", "macos-permissions", "--request", "bogus"],
                              capture_output=True, text=True, env=env, cwd=str(Path(__file__).resolve().parents[2]))
        check("CLI: unknown permission is rejected", proc.returncode == 2)
    finally:
        os.environ.pop("UTTER_PERMISSIONS_FILE", None)

# runner: darwin peer-cred helpers exist and fail closed on a bogus socket
from runner import socket as rsock  # noqa: E402

check("runner: darwin peer creds fail closed", rsock._peer_creds_darwin(object()) is None)
check("runner: linux peer-cred path still present", callable(rsock.SocketServer._peer_creds))

# --------------------------------------------------------------------------- #
# 10. hardened macOS features: audio chunking, STT fallback, AX raise, creds
# --------------------------------------------------------------------------- #
import struct  # noqa: E402
import numpy as np  # noqa: E402
from utter.macos import speech as mspeech  # noqa: E402
from utter.macos import desktop as mdesk  # noqa: E402

# 10.1 audio chunking for Apple speech (~1 min cap)
short_pcm = np.zeros(16000 * 10, dtype=np.float32)
short_chunks = mspeech.split_audio_chunks(short_pcm, sample_rate=16000, max_duration_s=50.0)
check("audio chunking: short audio returns 1 chunk", len(short_chunks) == 1 and len(short_chunks[0]) == len(short_pcm))

long_pcm = np.ones(16000 * 80, dtype=np.float32)
long_pcm[16000 * 35: 16000 * 36] = 0.0  # pause at 35s
long_chunks = mspeech.split_audio_chunks(long_pcm, sample_rate=16000, max_duration_s=50.0, min_duration_s=25.0)
check("audio chunking: 80s audio splits into chunks <= 50s",
      len(long_chunks) == 2 and all(len(c) <= 16000 * 50 for c in long_chunks))
check("audio chunking: total samples preserved", sum(len(c) for c in long_chunks) == len(long_pcm))

# 10.2 STT runtime fallback: apple_speech runtime failure falls back to whisper_cpp
t_rt = stt.Transcriber(stt_cfg, backend="apple_speech", fallbacks=["whisper_cpp"])
mock_apple = SimpleNamespace(transcribe=lambda audio, sr: (_ for _ in ()).throw(RuntimeError("Audio limit or permission revoked")))
t_rt._model = mock_apple
t_rt._load_whisper_cpp = lambda: SimpleNamespace(transcribe=lambda audio, **kw: [SimpleNamespace(text="hello fallback")])
res = t_rt.transcribe(np.zeros(16000, dtype=np.float32))
check("STT runtime fallback: apple_speech failure falls back to whisper_cpp",
      res == "hello fallback" and t_rt.backend == "whisper_cpp")

# 10.3 AX window raise (kAXRaiseAction)
mock_as = SimpleNamespace(
    AXUIElementCreateApplication=lambda pid: "mock_app",
    AXUIElementCopyAttributeValue=lambda elem, attr, val: (0, ["mock_win1", "mock_win2"]) if attr == "AXWindows" else (0, "target title"),
    _AXUIElementGetWindow=lambda win, val: (0, 101) if win == "mock_win1" else (0, 102),
    AXUIElementPerformAction=lambda win, action: 0 if win == "mock_win2" and action == "AXRaise" else 1,
    kAXWindowsAttribute="AXWindows",
    kAXTitleAttribute="AXTitle",
    kAXRaiseAction="AXRaise",
)
orig_as = sys.modules.get("ApplicationServices")
sys.modules["ApplicationServices"] = mock_as
try:
    check("ax_raise_window succeeds on matching window id", mdesk.ax_raise_window(1234, 102) is True)
    check("ax_raise_window returns False on nonexistent window id", mdesk.ax_raise_window(1234, 999) is False)
finally:
    if orig_as is None:
        sys.modules.pop("ApplicationServices", None)
    else:
        sys.modules["ApplicationServices"] = orig_as

# 10.4 Darwin peer creds unpacking + version check + pid check
class MockDarwinSock:
    def getsockopt(self, level, optname, buflen):
        if optname == rsock._LOCAL_PEERCRED:
            packed = struct.pack("IIh16I", 0, 501, 1, 20, *([0] * 15))
            return packed + b"\x00" * (128 - len(packed))
        if optname == rsock._LOCAL_PEERPID:
            return struct.pack("i", 4321)
        raise OSError("unknown opt")

mock_sock = MockDarwinSock()
creds = rsock._peer_creds_darwin(mock_sock)
check("runner: darwin peer creds extracts pid, uid, gid", creds == (4321, 501, 20))

class MockBadVersionSock(MockDarwinSock):
    def getsockopt(self, level, optname, buflen):
        if optname == rsock._LOCAL_PEERCRED:
            packed = struct.pack("IIh16I", 999, 501, 1, 20, *([0] * 15))
            return packed + b"\x00" * (128 - len(packed))
        return super().getsockopt(level, optname, buflen)

check("runner: darwin peer creds rejects bad struct version", rsock._peer_creds_darwin(MockBadVersionSock()) is None)

class MockBadPidSock(MockDarwinSock):
    def getsockopt(self, level, optname, buflen):
        if optname == rsock._LOCAL_PEERPID:
            return struct.pack("i", -1)
        return super().getsockopt(level, optname, buflen)

check("runner: darwin peer creds rejects invalid pid <= 0", rsock._peer_creds_darwin(MockBadPidSock()) is None)

import ctypes  # noqa: E402
class MockLibProc:
    def proc_pidpath(self, pid, buf, buflen):
        buf.value = b"/Applications/utter.app/Contents/MacOS/utter"
        return len(buf.value)

mock_libproc = MockLibProc()
orig_cdll = ctypes.CDLL
ctypes.CDLL = lambda name: mock_libproc
try:
    check("runner: _exe_darwin returns process executable path",
          rsock._exe_darwin(4321) == "/Applications/utter.app/Contents/MacOS/utter")
    check("runner: _exe_darwin rejects pid <= 0", rsock._exe_darwin(0) is None)
finally:
    ctypes.CDLL = orig_cdll

# 10.5 screencapture error handling & Retina points
orig_sp_run = subprocess.run
def _fail_screencapture(cmd, check=True, timeout=15):
    raise subprocess.CalledProcessError(1, cmd)

subprocess.run = _fail_screencapture
try:
    mshot._displays = lambda: [mdesk.Rect(0, 0, 1000, 800)]
    try:
        mshot.capture_output(0)
        check("screencapture failure raises", False)
    except RuntimeError as exc:
        check("screencapture failure mentions Screen Recording", "Screen Recording" in str(exc))
finally:
    subprocess.run = orig_sp_run
    mshot._displays = lambda: []

check("screenshot backing_scale_factor defaults to 1.0 without AppKit", mshot.backing_scale_factor() == 1.0)

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
