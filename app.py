#!/usr/bin/env python3
import datetime
import fcntl
import os
import sys
import tempfile
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Notify, Pango  # noqa: E402

import db  # noqa: E402
from dashboard import DashboardWindow  # noqa: E402

WIDGET_W = 300
WIDGET_H = 260
MARGIN = 24
CORNER_RADIUS = 22
TINT_TOP = "rgba(16, 16, 16, 0.60)"
TINT_BOTTOM = "rgba(16, 16, 16, 0.60)"
BORDER_COLOR = "rgba(235, 219, 178, 0.14)"

BACKDROP_DIR = Path(tempfile.gettempdir()) / "desktop-calendar-widget"


def grab_blurred_backdrop(x, y, w, h, passes=3, downscale=8):
    root = Gdk.get_default_root_window()
    try:
        pixbuf = Gdk.pixbuf_get_from_window(root, x, y, w, h)
    except Exception:
        pixbuf = None
    if pixbuf is None:
        return None
    small_w = max(1, w // downscale)
    small_h = max(1, h // downscale)
    blurred = pixbuf
    for _ in range(passes):
        blurred = blurred.scale_simple(small_w, small_h, GdkPixbuf.InterpType.BILINEAR)
        blurred = blurred.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
    return blurred


class DesktopWidget(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.manager_window = None
        self._backdrop_toggle = False
        BACKDROP_DIR.mkdir(parents=True, exist_ok=True)

        self.set_default_size(WIDGET_W, WIDGET_H)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.set_accept_focus(True)
        self.stick()

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        monitor_geo = monitor.get_geometry()
        self.pos_x = monitor_geo.x + monitor_geo.width - WIDGET_W - MARGIN
        self.pos_y = monitor_geo.y + MARGIN + 36  # clear the top panel
        self.move(self.pos_x, self.pos_y)

        self.get_style_context().add_class("cal-widget-window")

        overlay = Gtk.Overlay()
        self.add(overlay)

        self.panel = Gtk.EventBox()
        self.panel.set_visible_window(True)
        self.panel.get_style_context().add_class("cal-widget-panel")
        self.panel.connect("button-press-event", self.on_click)
        overlay.add(self.panel)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_border_width(18)
        self.panel.add(content)

        self.date_label = Gtk.Label(xalign=0)
        self.date_label.get_style_context().add_class("cal-widget-date")
        content.pack_start(self.date_label, False, False, 0)

        sep = Gtk.Separator()
        content.pack_start(sep, False, False, 4)

        self.events_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.pack_start(self.events_box, True, True, 0)

        add_btn = Gtk.Button(label="+")
        add_btn.set_halign(Gtk.Align.END)
        add_btn.set_valign(Gtk.Align.START)
        add_btn.set_margin_top(10)
        add_btn.set_margin_end(10)
        add_btn.get_style_context().add_class("cal-widget-add")
        add_btn.connect("clicked", self.on_add_clicked)
        overlay.add_overlay(add_btn)

        self._base_css()
        self.connect("realize", lambda w: self.refresh_backdrop())

        self.refresh_content()
        GLib.timeout_add_seconds(60, self._tick)
        GLib.timeout_add_seconds(300, self._backdrop_tick)

    def _base_css(self):
        css = b"""
        .cal-widget-window { background-color: transparent; }
        .cal-widget-date { color: #ebdbb2; font-size: 16px; font-weight: bold; }
        .cal-widget-event { color: #d5c4a1; font-size: 12px; }
        .cal-widget-task-header { color: #fabd2f; font-size: 11px; font-weight: bold; }
        .cal-widget-add {
            background: rgba(235, 219, 178, 0.14);
            color: #ebdbb2;
            border-radius: 14px;
            min-width: 26px;
            min-height: 26px;
            padding: 0;
            border: none;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def refresh_backdrop(self):
        backdrop = grab_blurred_backdrop(self.pos_x, self.pos_y, WIDGET_W, WIDGET_H)
        if backdrop is None:
            panel_css = f"""
            .cal-widget-panel {{
                background-image: linear-gradient({TINT_TOP}, {TINT_BOTTOM});
                border-radius: {CORNER_RADIUS}px;
                border: 1px solid {BORDER_COLOR};
            }}
            """.encode()
        else:
            # Ping-pong filenames so GTK's image loader can't serve a stale cache.
            self._backdrop_toggle = not self._backdrop_toggle
            path = BACKDROP_DIR / f"backdrop-{int(self._backdrop_toggle)}.png"
            backdrop.savev(str(path), "png", [], [])
            panel_css = f"""
            .cal-widget-panel {{
                background-image: linear-gradient({TINT_TOP}, {TINT_BOTTOM}),
                    url("file://{path}");
                background-size: cover;
                border-radius: {CORNER_RADIUS}px;
                border: 1px solid {BORDER_COLOR};
            }}
            """.encode()

        provider = Gtk.CssProvider()
        provider.load_from_data(panel_css)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
        )

    def _backdrop_tick(self):
        self.refresh_backdrop()
        return True

    def refresh_content(self):
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        self.date_label.set_text(now.strftime("%A, %d %B"))

        for child in self.events_box.get_children():
            self.events_box.remove(child)

        events = db.get_upcoming_events(today_str, now.strftime("%H:%M"), limit=4)
        if not events:
            lbl = Gtk.Label(label="No upcoming events", xalign=0)
            lbl.get_style_context().add_class("cal-widget-event")
            self.events_box.pack_start(lbl, False, False, 0)
        for ev in events:
            when = "Today" if ev["date"] == today_str else ev["date"]
            time_part = f" {ev['time']}" if ev["time"] else ""
            lbl = Gtk.Label(label=f"{when}{time_part} · {ev['title']}", xalign=0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.get_style_context().add_class("cal-widget-event")
            self.events_box.pack_start(lbl, False, False, 0)

        tasks = db.get_due_or_overdue_tasks(today_str, limit=3)
        if tasks:
            sep = Gtk.Separator()
            self.events_box.pack_start(sep, False, False, 4)
            header = Gtk.Label(label=f"{len(tasks)} task(s) due", xalign=0)
            header.get_style_context().add_class("cal-widget-task-header")
            self.events_box.pack_start(header, False, False, 0)
            for task in tasks:
                marker = "⚠" if task["due_date"] < today_str else "•"
                lbl = Gtk.Label(label=f"{marker} {task['title']}", xalign=0)
                lbl.set_ellipsize(Pango.EllipsizeMode.END)
                lbl.get_style_context().add_class("cal-widget-event")
                self.events_box.pack_start(lbl, False, False, 0)

        self.events_box.show_all()

    def _tick(self):
        self.refresh_content()
        return True

    def on_click(self, widget, event):
        self.open_manager()
        return True

    def on_add_clicked(self, button):
        self.open_manager()
        if self.manager_window:
            self.manager_window.on_add_event(None)

    def open_manager(self):
        if self.manager_window is None or not self.manager_window.get_visible():
            self.manager_window = DashboardWindow(on_change=self.refresh_content)
            self.manager_window.connect("destroy", self._on_manager_closed)
            self.manager_window.show_all()
        else:
            self.manager_window.present()

    def _on_manager_closed(self, window):
        self.manager_window = None
        self.refresh_content()


def check_reminders():
    now = datetime.datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    for ev in db.get_pending_reminders(today_str, now.strftime("%Y-%m-%d %H:%M")):
        try:
            ev_time = datetime.datetime.strptime(
                f"{ev['date']} {ev['time']}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            continue
        remind_at = ev_time - datetime.timedelta(minutes=ev["reminder_minutes"] or 0)
        if remind_at <= now <= ev_time:
            notification = Notify.Notification.new(
                f"Upcoming: {ev['title']}",
                f"At {ev['time']}" + (f" — {ev['description']}" if ev["description"] else ""),
                "x-office-calendar",
            )
            notification.show()
            db.mark_notified(ev["id"])
    return True


def acquire_single_instance_lock():
    """Refuse to start a second copy (e.g. autostart racing a manual launch
    after login). Holds the lock file handle for the process lifetime."""
    lock_path = Path(tempfile.gettempdir()) / "desktop-calendar-widget.lock"
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another instance is already running, exiting.", file=sys.stderr)
        sys.exit(0)
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file  # keep a reference so the lock isn't released by GC


def main():
    _lock = acquire_single_instance_lock()  # noqa: F841
    Notify.init("Desktop Calendar Widget")
    widget = DesktopWidget()
    widget.show_all()
    widget.set_keep_below(True)

    GLib.timeout_add_seconds(60, check_reminders)
    check_reminders()

    Gtk.main()


if __name__ == "__main__":
    main()
