"""macOS (Darwin) backends for utter.

Every module here is imported lazily and only when :func:`utter.platform.is_macos`
is true. The package itself imports cleanly on Linux so tests can exercise the
pure parts (key tables, chord parsing, event state machines, backend
selection) without PyObjC.

Modules:
    speech      Apple ``Speech.framework`` STT (``SFSpeechRecognizer`` via PyObjC)
    tts         ``say`` / ``AVSpeechSynthesizer`` text-to-speech
    hotkey      push-to-talk via Quartz ``CGEventTap`` (or ``pynput``)
    inject      key chords + typed text via Quartz ``CGEventPost`` / AppleScript
    pointer     mouse clicks and scrolling via Quartz events
    desktop     focused app/window, window list, monitors (NSWorkspace + AX)
    screenshot  ``screencapture`` + ``NSScreen`` geometry
    clipboard   ``pbpaste`` / ``pbcopy``
    notify      ``osascript display notification`` / ``terminal-notifier``

Required Python packages (``pip install 'utter[macos]'``): ``pyobjc-framework-Cocoa``,
``pyobjc-framework-Quartz``, ``pyobjc-framework-Speech``,
``pyobjc-framework-AVFoundation``, ``pyobjc-framework-ApplicationServices``.

Permissions (System Settings -> Privacy & Security): Microphone, Speech
Recognition, Accessibility (typing + AX window titles), Input Monitoring (the
event tap) and Screen Recording (``screencapture``).
"""
from __future__ import annotations

__all__ = [
    "speech", "tts", "hotkey", "inject", "pointer", "desktop",
    "screenshot", "clipboard", "notify",
]
