"""The settings window: sidebar + content, search, runner polling."""
from __future__ import annotations

from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from . import backend as be  # noqa: E402
from . import config, widgets  # noqa: E402
from .pages import PAGE_CLASSES
from .pages.base import Page

_RUNNER_POLL_MS = 8000
_DEFAULT_SIZE = (900, 640)
_MIN_SIZE = (620, 480)


class NavRow(Gtk.ListBoxRow):
    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)
        icon = Gtk.Image.new_from_icon_name(page.icon)
        icon.set_pixel_size(16)
        label = Gtk.Label(label=page.title, xalign=0)
        label.set_hexpand(True)
        label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        box.append(icon)
        box.append(label)
        self.set_child(box)
        self.add_css_class("nav-row")
        self.set_tooltip_text(page.subtitle)
        self._search_text = f"{page.title} {page.subtitle} {page.keywords}".lower()

    def matches(self, query: str) -> bool:
        return query in self._search_text


class MainWindow(Adw.ApplicationWindow):
    __gsignals__ = {
        "runner-state-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }

    def __init__(self, app, backend: be.Backend):
        super().__init__(application=app)
        self.app = app
        self.backend = backend
        self.runner_connected: Optional[bool] = None

        self._pages: dict[str, Page] = {}
        self._rows: dict[str, NavRow] = {}
        self._order: list[str] = []
        self._current: Optional[str] = None
        self._runner_timer = 0
        self._anim = None

        self.set_title("utter Settings")
        self.set_default_size(*_DEFAULT_SIZE)
        self.set_size_request(*_MIN_SIZE)

        self._build_ui()
        self._install_actions()
        self._restore_state()

        if self._order:
            self.show_page(self._order[0])
        self._poll_runner()
        self._runner_timer = GLib.timeout_add(_RUNNER_POLL_MS, self._poll_tick)

    # -- construction ---------------------------------------------------- #
    def _build_ui(self) -> None:
        self._split = Adw.NavigationSplitView()
        self._split.set_min_sidebar_width(210)
        self._split.set_max_sidebar_width(260)
        self._split.set_sidebar(self._build_sidebar())
        self._split.set_content(self._build_content())

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._split)
        self.set_content(self._toast_overlay)

    def _build_sidebar(self) -> Adw.NavigationPage:
        page = Adw.NavigationPage(tag="sidebar", title="utter")

        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="utter", subtitle="Settings")
        header.set_title_widget(title)

        menu = Gio.Menu()
        menu.append("Refresh", "win.refresh")
        menu.append("Keyboard shortcuts", "win.shortcuts")
        menu.append("About utter", "app.about")
        menu.append("Quit", "app.quit")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_button)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search settings")
        self._search.set_margin_top(6)
        self._search.set_margin_bottom(6)
        self._search.set_margin_start(12)
        self._search.set_margin_end(12)
        self._search.connect("search-changed", self._on_search_changed)

        self._listbox = Gtk.ListBox()
        self._listbox.add_css_class("navigation-sidebar")
        self._listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._listbox.set_show_separators(False)
        self._listbox.connect("row-selected", self._on_row_selected)

        self._no_results = Gtk.ListBoxRow()
        no_results_label = Gtk.Label(label="No settings match your search")
        no_results_label.add_css_class("dim-label")
        no_results_label.set_margin_top(24)
        no_results_label.set_margin_bottom(24)
        self._no_results.set_child(no_results_label)
        self._no_results.set_activatable(False)
        self._no_results.set_selectable(False)
        self._no_results.set_visible(False)
        self._listbox.append(self._no_results)

        for cls in PAGE_CLASSES:
            instantiated = cls(self)
            nav = instantiated.build()
            self._pages[instantiated.id] = instantiated
            self._order.append(instantiated.id)
            row = NavRow(instantiated)
            self._rows[instantiated.id] = row
            self._listbox.append(row)

        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_child(self._listbox)
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_vexpand(True)

        status = self._build_status_strip()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self._search)
        box.append(list_scroll)
        box.append(status)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(box)
        page.set_child(toolbar)
        return page

    def _build_status_strip(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.add_css_class("status-strip")
        box.set_margin_top(8)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        self._status_dot = widgets.dot("busy")
        self._status_label = Gtk.Label(label="Checking runner…", xalign=0)
        self._status_label.add_css_class("caption")
        self._status_label.set_ellipsize(3)
        self._status_label.set_hexpand(True)
        box.append(self._status_dot)
        box.append(self._status_label)
        return box

    def _build_content(self) -> Adw.NavigationPage:
        self._content_nav = Adw.NavigationView()
        root = Adw.NavigationPage(tag="content", title="Settings")
        root.set_child(self._content_nav)
        return root

    # -- actions --------------------------------------------------------- #
    def _install_actions(self) -> None:
        actions = {
            "refresh": (self._on_refresh_action, None),
            "focus-search": (lambda *_: self._search.grab_focus(), None),
            "shortcuts": (lambda *_: self._show_shortcuts(), None),
            "show-page": (lambda _a, p: self.show_page(p.get_string()), GLib.VariantType.new("s")),
        }
        for name, (callback, param_type) in actions.items():
            action = Gio.SimpleAction.new(name, param_type)
            if param_type is None:
                action.connect("activate", lambda _a, _p, cb=callback: cb())
            else:
                action.connect("activate", lambda _a, p, cb=callback: cb(_a, p))
            self.add_action(action)

        self.app.set_accels_for_action("win.refresh", ["<Control>r"])
        self.app.set_accels_for_action("win.focus-search", ["<Control>f"])
        self.app.set_accels_for_action("win.shortcuts", ["<Control>question"])
        self.app.set_accels_for_action("app.quit", ["<Control>q"])

    def _on_refresh_action(self) -> None:
        page = self._pages.get(self._current or "")
        if page is not None:
            page.refresh()
            self.toast("Refreshed")

    def _show_shortcuts(self) -> None:
        dialog = Adw.Dialog()
        dialog.set_title("Keyboard shortcuts")
        dialog.set_content_width(420)
        dialog.set_content_height(360)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Keyboard shortcuts"))
        group = Adw.PreferencesGroup()
        for keys, description in (
            ("Ctrl+F", "Focus the settings search"),
            ("Ctrl+R", "Refresh the current page"),
            ("Ctrl+?", "Show this list"),
            ("Ctrl+Q", "Quit utter Settings"),
        ):
            row = Adw.ActionRow(title=description)
            row.add_suffix(widgets.badge(keys, "neutral"))
            group.add(row)
        prefs = Adw.PreferencesPage()
        prefs.add(group)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(prefs)
        dialog.set_child(toolbar)
        dialog.present(self)

    # -- navigation ------------------------------------------------------ #
    def show_page(self, page_id: str) -> None:
        page = self._pages.get(page_id)
        if page is None:
            return
        if self._current == page_id:
            self._split.set_show_content(True)
            return
        previous = self._pages.get(self._current or "")
        if previous is not None:
            previous.on_hide()
        self._current = page_id
        row = self._rows.get(page_id)
        if row is not None and self._listbox.get_selected_row() is not row:
            self._listbox.select_row(row)
        self._content_nav.replace([page.nav_page])
        self._split.set_show_content(True)
        self._fade_in(page.nav_page)
        page.on_show()
        self._save_state()

    def _on_row_selected(self, _listbox, row) -> None:
        if isinstance(row, NavRow):
            self.show_page(row.page.id)

    def _on_search_changed(self, entry) -> None:
        query = entry.get_text().strip().lower()
        visible = 0
        for page_id, row in self._rows.items():
            match = not query or row.matches(query)
            row.set_visible(match)
            if match:
                visible += 1
        self._no_results.set_visible(visible == 0)

    def _fade_in(self, widget) -> None:
        try:
            widget.set_opacity(0.0)
            target = Adw.PropertyAnimationTarget.new(widget, "opacity")
            self._anim = Adw.TimedAnimation.new(widget, 0.0, 1.0, 100, target)
            self._anim.play()
        except Exception:  # noqa: BLE001 - animation is a nicety
            widget.set_opacity(1.0)

    # -- runner status --------------------------------------------------- #
    def _poll_tick(self) -> bool:
        self._poll_runner()
        return True

    def _poll_runner(self) -> None:
        proc = self.backend.assistant("status", "--json", "--timeout", "3")
        self.backend.track(proc)
        self._status_poll = proc

        def done(rc: int, out: str, err: str) -> None:
            data = be.parse_json(out) or {}
            self._set_runner_connected(bool(data.get("connected")))

        proc.communicate(done)

    def _set_runner_connected(self, connected: bool) -> None:
        if connected == self.runner_connected:
            return
        self.runner_connected = connected
        self._status_dot.set_state("ok" if connected else "unknown")
        self._status_label.set_text(
            "Runner connected" if connected
            else "Runner not reachable — see Diagnostics"
        )
        self.emit("runner-state-changed", connected)

    def toast(self, text: str, timeout: int = 3) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=widgets.esc(text), timeout=timeout))

    # -- state ----------------------------------------------------------- #
    def _restore_state(self) -> None:
        state = config.load_gui_state()
        width = int(state.get("width") or _DEFAULT_SIZE[0])
        height = int(state.get("height") or _DEFAULT_SIZE[1])
        self.set_default_size(max(width, _MIN_SIZE[0]), max(height, _MIN_SIZE[1]))
        last = state.get("page")
        if last in self._pages:
            self._order = [last] + [p for p in self._order if p != last]
        self.connect("close-request", self._on_close_request)

    def _on_close_request(self, _win) -> bool:
        self._save_state()
        return False

    def _save_state(self) -> None:
        width, height = self.get_width(), self.get_height()
        if width <= 1 or height <= 1:
            fallback = self.get_default_size()
            width = width if width > 1 else fallback[0]
            height = height if height > 1 else fallback[1]
        config.save_gui_state({
            "width": width,
            "height": height,
            "page": self._current,
        })
