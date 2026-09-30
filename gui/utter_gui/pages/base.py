"""Base class for settings pages: header, banner, toasts and lifecycle."""
from __future__ import annotations

from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import widgets  # noqa: E402


class Page:
    id: str = "page"
    title: str = "Page"
    subtitle: str = ""
    icon: str = "preferences-system-symbolic"
    keywords: str = ""
    needs_runner: bool = False

    def __init__(self, window) -> None:
        self.window = window
        self.app = window.app
        self.backend = window.backend
        self._procs: list = []
        self.page: Adw.PreferencesPage = Adw.PreferencesPage()
        self._built = False

    # -- chrome ---------------------------------------------------------- #
    def build(self) -> Adw.NavigationPage:
        self.nav_page = Adw.NavigationPage(tag=self.id, title=self.title)

        self.header = Adw.HeaderBar()
        self.header.set_title_widget(widgets.header_title(self.title, self.subtitle))

        self.banner = Adw.Banner(revealed=False)
        self.banner.connect("button-clicked", self._on_banner_button)

        self.body = self.build_body()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self.banner)
        if self.body is not None:
            content.append(self.body)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(content)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(self.header)
        toolbar.set_content(self.toast_overlay)
        self.nav_page.set_child(toolbar)

        self.window.connect("runner-state-changed", self._on_runner_state_changed)
        self._runner_connected = self.window.runner_connected
        self._apply_runner_state(self._runner_connected)
        self._built = True
        return self.nav_page

    def build_body(self) -> Optional[Gtk.Widget]:
        """Return the page's main widget (a preferences page by default)."""
        return self.page

    def add_group(self, group: Adw.PreferencesGroup) -> Adw.PreferencesGroup:
        self.page.add(group)
        return group

    # -- helpers --------------------------------------------------------- #
    def toast(self, text: str, timeout: int = 3) -> None:
        if self._built:
            self.toast_overlay.add_toast(Adw.Toast(title=widgets.esc(text), timeout=timeout))
        else:  # not shown yet — queue via window
            self.window.toast(text, timeout)

    def track(self, proc) -> None:
        self._procs.append(proc)

    def cancel_all(self) -> None:
        for proc in self._procs:
            try:
                proc.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._procs.clear()

    # -- lifecycle ------------------------------------------------------- #
    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    # -- runner availability -------------------------------------------- #
    @property
    def runner_connected(self) -> bool:
        return getattr(self, "_runner_connected", False)

    def _apply_runner_state(self, connected: bool) -> None:
        if not self.needs_runner:
            self.banner.set_revealed(False)
            return
        self.banner.set_revealed(not connected)
        if not connected:
            self.banner.set_title("Runner not reachable — start utter-runner to use these settings")
            self.banner.set_button_label("Diagnostics")
        self.on_runner_state(connected)

    def _on_runner_state_changed(self, _win, connected: bool) -> None:
        self._runner_connected = connected
        if self._built:
            self._apply_runner_state(connected)

    def on_runner_state(self, connected: bool) -> None:
        pass

    def _on_banner_button(self, _banner) -> None:
        self.window.show_page("diagnostics")
