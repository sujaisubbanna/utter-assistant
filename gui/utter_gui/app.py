"""Application object: CSS, actions, and the single settings window."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, __version__  # noqa: E402
from .backend import Backend  # noqa: E402
from .theme import ThemeManager  # noqa: E402
from .window import MainWindow  # noqa: E402


class UtterApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.backend: Optional[Backend] = None
        self.window: Optional[MainWindow] = None
        self.theme: Optional[ThemeManager] = None

    # -- lifecycle ------------------------------------------------------- #
    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._load_css()
        # Deterministic matugen palette; no-op when the file is absent.
        self.theme = ThemeManager()
        # Follow the system light/dark preference.
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)
        self._install_actions()

    def do_activate(self) -> None:
        if self.window is None:
            self.backend = Backend()
            self.window = MainWindow(self, self.backend)
        self.window.present()

    # -- styling --------------------------------------------------------- #
    def _load_css(self) -> None:
        css_path = Path(__file__).with_name("style.css")
        if not css_path.exists():
            return
        provider = Gtk.CssProvider()
        provider.load_from_path(str(css_path))
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    # -- actions --------------------------------------------------------- #
    def _install_actions(self) -> None:
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_a: self.quit())
        self.add_action(quit_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", lambda *_a: self._show_about())
        self.add_action(about_action)

    def _show_about(self) -> None:
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon="preferences-system-symbolic",
            version=__version__,
            developer_name="utter",
            comments=(
                "Settings for the utter voice→desktop assistant.\n"
                "This window is a client: it configures the assistant and asks the "
                "runner to do the work."
            ),
            license_type=Gtk.License.MIT_X11,
        )
        try:
            dialog.add_credit_section("Backend", ["assistant CLI · runner socket"])
        except (AttributeError, TypeError):
            pass
        dialog.present(self.window)


def main(argv: Optional[list[str]] = None) -> int:
    app = UtterApplication()
    args = list(argv) if argv is not None else list(sys.argv)
    if not args or not args[0]:
        args = [APP_NAME]
    return int(app.run(args))


if __name__ == "__main__":
    raise SystemExit(main())
