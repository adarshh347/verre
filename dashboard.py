"""The full 'open' view: calendar + day panel (events/tasks/progress) and a
projects registry with GitHub issue creation. Kept in plain GTK3 (matching
the desktop overlay widget) since libadwaita requires GTK4, which cannot be
loaded in the same process as GTK3.
"""
import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Gio, Pango  # noqa: E402

import db  # noqa: E402
import github_integration as ghi  # noqa: E402

CSS = b"""
.dash-window { background-color: #1d2021; }
.dash-sidebar { background-color: #282828; border: none; }
.dash-sidebar row { padding: 10px 14px; color: #d5c4a1; }
.dash-sidebar row:selected { background-color: #3c3836; color: #fe8019; }
.dash-heading { color: #ebdbb2; font-size: 18px; font-weight: bold; }
.dash-subheading { color: #ebdbb2; font-size: 13px; font-weight: bold; }
.dash-muted { color: #a89984; font-size: 12px; }
.card-list { background-color: transparent; }
.card-list row {
    background-color: #282828;
    border-radius: 10px;
    margin: 3px 0;
    padding: 8px;
    border: 1px solid rgba(235, 219, 178, 0.06);
}
.card-list row:hover { background-color: #32302f; }
.pill {
    border-radius: 999px;
    padding: 1px 9px;
    font-size: 11px;
    color: #1d2021;
}
.accent-btn {
    background-color: #fe8019;
    color: #1d2021;
    border-radius: 8px;
    font-weight: bold;
    border: none;
    padding: 4px 10px;
}
.ghost-btn {
    background-color: rgba(235, 219, 178, 0.08);
    color: #ebdbb2;
    border-radius: 8px;
    border: none;
    padding: 4px 10px;
}
"""


def apply_css(screen):
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def colored_pill(text, hex_color):
    label = Gtk.Label(label=text)
    label.get_style_context().add_class("pill")
    css = f"label {{ background-color: {hex_color}; }}".encode()
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    label.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    return label


# --------------------------------------------------------------- dialogs

class EventDialog(Gtk.Dialog):
    def __init__(self, parent, date_str, event_row=None):
        title = "Edit Event" if event_row else "Add Event"
        super().__init__(title=title, transient_for=parent, flags=Gtk.DialogFlags.MODAL)
        self.set_default_size(360, 320)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
        )
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.add(grid)

        grid.attach(Gtk.Label(label="Title", xalign=0), 0, 0, 1, 1)
        self.title_entry = Gtk.Entry()
        grid.attach(self.title_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Date (YYYY-MM-DD)", xalign=0), 0, 1, 1, 1)
        self.date_entry = Gtk.Entry()
        self.date_entry.set_text(date_str)
        grid.attach(self.date_entry, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Time (HH:MM, optional)", xalign=0), 0, 2, 1, 1)
        self.time_entry = Gtk.Entry()
        grid.attach(self.time_entry, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="Reminder (minutes before)", xalign=0), 0, 3, 1, 1)
        self.reminder_spin = Gtk.SpinButton.new_with_range(0, 1440, 5)
        self.reminder_spin.set_value(10)
        grid.attach(self.reminder_spin, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label="Description", xalign=0, valign=Gtk.Align.START), 0, 4, 1, 1)
        self.desc_view = Gtk.TextView()
        self.desc_view.set_wrap_mode(Gtk.WrapMode.WORD)
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 90)
        scroll.add(self.desc_view)
        grid.attach(scroll, 1, 4, 1, 1)

        if event_row:
            self.title_entry.set_text(event_row["title"])
            self.date_entry.set_text(event_row["date"])
            self.time_entry.set_text(event_row["time"] or "")
            self.reminder_spin.set_value(event_row["reminder_minutes"] or 0)
            self.desc_view.get_buffer().set_text(event_row["description"] or "")

        self.show_all()

    def get_values(self):
        buf = self.desc_view.get_buffer()
        description = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        return {
            "title": self.title_entry.get_text().strip(),
            "date": self.date_entry.get_text().strip(),
            "time": self.time_entry.get_text().strip() or None,
            "description": description,
            "reminder_minutes": int(self.reminder_spin.get_value()),
        }


class TaskDialog(Gtk.Dialog):
    def __init__(self, parent, date_str, projects, task_row=None):
        title = "Edit Task" if task_row else "Add Task"
        super().__init__(title=title, transient_for=parent, flags=Gtk.DialogFlags.MODAL)
        self.set_default_size(380, 340)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
        )
        self.projects = list(projects)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.add(grid)

        grid.attach(Gtk.Label(label="Title", xalign=0), 0, 0, 1, 1)
        self.title_entry = Gtk.Entry()
        grid.attach(self.title_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Project", xalign=0), 0, 1, 1, 1)
        self.project_combo = Gtk.ComboBoxText()
        self.project_combo.append_text("— None —")
        for proj in self.projects:
            self.project_combo.append_text(proj["name"])
        self.project_combo.set_active(0)
        grid.attach(self.project_combo, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Due date (YYYY-MM-DD)", xalign=0), 0, 2, 1, 1)
        self.due_entry = Gtk.Entry()
        self.due_entry.set_text(date_str)
        grid.attach(self.due_entry, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="Status", xalign=0), 0, 3, 1, 1)
        self.status_combo = Gtk.ComboBoxText()
        for status in ("todo", "in_progress", "done"):
            self.status_combo.append_text(status)
        self.status_combo.set_active(0)
        grid.attach(self.status_combo, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label="Description", xalign=0, valign=Gtk.Align.START), 0, 4, 1, 1)
        self.desc_view = Gtk.TextView()
        self.desc_view.set_wrap_mode(Gtk.WrapMode.WORD)
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 80)
        scroll.add(self.desc_view)
        grid.attach(scroll, 1, 4, 1, 1)

        if task_row:
            self.title_entry.set_text(task_row["title"])
            self.due_entry.set_text(task_row["due_date"] or "")
            self.desc_view.get_buffer().set_text(task_row["description"] or "")
            statuses = ["todo", "in_progress", "done"]
            self.status_combo.set_active(statuses.index(task_row["status"]))
            if task_row["project_id"]:
                for i, proj in enumerate(self.projects):
                    if proj["id"] == task_row["project_id"]:
                        self.project_combo.set_active(i + 1)
                        break

        self.show_all()

    def get_values(self):
        buf = self.desc_view.get_buffer()
        description = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        idx = self.project_combo.get_active()
        project_id = None if idx <= 0 else self.projects[idx - 1]["id"]
        statuses = ["todo", "in_progress", "done"]
        return {
            "title": self.title_entry.get_text().strip(),
            "project_id": project_id,
            "due_date": self.due_entry.get_text().strip() or None,
            "status": statuses[self.status_combo.get_active()],
            "description": description,
        }


class ProjectDialog(Gtk.Dialog):
    def __init__(self, parent, project_row=None):
        title = "Edit Project" if project_row else "Add Project"
        super().__init__(title=title, transient_for=parent, flags=Gtk.DialogFlags.MODAL)
        self.set_default_size(420, 280)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
        )
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.add(grid)

        grid.attach(Gtk.Label(label="Name", xalign=0), 0, 0, 1, 1)
        self.name_entry = Gtk.Entry()
        grid.attach(self.name_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Local path", xalign=0), 0, 1, 1, 1)
        path_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.path_entry = Gtk.Entry()
        self.path_entry.set_hexpand(True)
        browse_btn = Gtk.Button(label="Browse…")
        browse_btn.connect("clicked", self.on_browse)
        path_box.pack_start(self.path_entry, True, True, 0)
        path_box.pack_start(browse_btn, False, False, 0)
        grid.attach(path_box, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="GitHub owner", xalign=0), 0, 2, 1, 1)
        self.owner_entry = Gtk.Entry()
        grid.attach(self.owner_entry, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="GitHub repo", xalign=0), 0, 3, 1, 1)
        self.repo_entry = Gtk.Entry()
        grid.attach(self.repo_entry, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label="Color", xalign=0), 0, 4, 1, 1)
        self.color_btn = Gtk.ColorButton()
        rgba = Gdk.RGBA()
        rgba.parse((project_row["color"] if project_row else "#b8bb26"))
        self.color_btn.set_rgba(rgba)
        grid.attach(self.color_btn, 1, 4, 1, 1)

        detect_btn = Gtk.Button(label="Auto-detect GitHub repo from path")
        detect_btn.connect("clicked", self.on_detect)
        grid.attach(detect_btn, 1, 5, 1, 1)

        if project_row:
            self.name_entry.set_text(project_row["name"])
            self.path_entry.set_text(project_row["local_path"] or "")
            self.owner_entry.set_text(project_row["repo_owner"] or "")
            self.repo_entry.set_text(project_row["repo_name"] or "")

        self.show_all()

    def on_browse(self, button):
        dialog = Gtk.FileChooserDialog(
            title="Select project folder",
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK,
        )
        if dialog.run() == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            self.path_entry.set_text(path)
            if not self.name_entry.get_text().strip():
                self.name_entry.set_text(path.rstrip("/").split("/")[-1])
            self.on_detect(None)
        dialog.destroy()

    def on_detect(self, button):
        owner, repo = ghi.detect_repo_from_path(self.path_entry.get_text().strip())
        if owner and repo:
            self.owner_entry.set_text(owner)
            self.repo_entry.set_text(repo)

    def get_values(self):
        rgba = self.color_btn.get_rgba()
        hex_color = "#{:02x}{:02x}{:02x}".format(
            int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255)
        )
        return {
            "name": self.name_entry.get_text().strip(),
            "local_path": self.path_entry.get_text().strip(),
            "repo_owner": self.owner_entry.get_text().strip(),
            "repo_name": self.repo_entry.get_text().strip(),
            "color": hex_color,
        }


# ----------------------------------------------------------- main window

class DashboardWindow(Gtk.Window):
    def __init__(self, on_change):
        super().__init__(title="Engineering Dashboard")
        self.on_change = on_change
        self.set_default_size(820, 640)
        self.set_position(Gtk.WindowPosition.CENTER)
        apply_css(self.get_screen())
        self.get_style_context().add_class("dash-window")

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(root)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        sidebar.get_style_context().add_class("dash-sidebar")
        root.pack_start(sidebar, False, False, 0)
        root.pack_start(self.stack, True, True, 0)

        self.stack.add_titled(self._build_calendar_page(), "calendar", "Calendar")
        self.stack.add_titled(self._build_projects_page(), "projects", "Projects")

        self.refresh_marks()
        self.refresh_day_panel()
        self.refresh_projects_list()

    # -------------------------------------------------------- calendar page

    def _build_calendar_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        page.set_border_width(14)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.calendar = Gtk.Calendar()
        self.calendar.connect("day-selected", lambda c: self.refresh_day_panel())
        self.calendar.connect("month-changed", lambda c: self.refresh_marks())
        left.pack_start(self.calendar, False, False, 0)
        page.pack_start(left, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right.set_border_width(0)
        right.set_margin_start(18)

        self.day_heading = Gtk.Label(xalign=0)
        self.day_heading.get_style_context().add_class("dash-heading")
        right.pack_start(self.day_heading, False, False, 0)

        quick_add = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, handler in (
            ("+ Event", self.on_add_event),
            ("+ Task", self.on_add_task),
        ):
            btn = Gtk.Button(label=label)
            btn.get_style_context().add_class("ghost-btn")
            btn.connect("clicked", handler)
            quick_add.pack_start(btn, False, False, 0)
        right.pack_start(quick_add, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        sections = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        sections.set_margin_top(6)
        scroll.add(sections)
        right.pack_start(scroll, True, True, 0)

        self.events_list = self._make_section(sections, "Events")
        self.tasks_list = self._make_section(sections, "Tasks")
        self.progress_list = self._make_section(sections, "Progress")

        note_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.progress_project_combo = Gtk.ComboBoxText()
        self.note_entry = Gtk.Entry()
        self.note_entry.set_placeholder_text("What did you get done today…")
        self.note_entry.set_hexpand(True)
        log_btn = Gtk.Button(label="Log")
        log_btn.get_style_context().add_class("accent-btn")
        log_btn.connect("clicked", self.on_log_progress)
        note_row.pack_start(self.progress_project_combo, False, False, 0)
        note_row.pack_start(self.note_entry, True, True, 0)
        note_row.pack_start(log_btn, False, False, 0)
        sections.pack_start(note_row, False, False, 0)

        page.pack_start(right, True, True, 0)
        return page

    def _make_section(self, parent_box, title):
        heading = Gtk.Label(label=title, xalign=0)
        heading.get_style_context().add_class("dash-subheading")
        parent_box.pack_start(heading, False, False, 0)
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.get_style_context().add_class("card-list")
        parent_box.pack_start(listbox, False, False, 0)
        return listbox

    # -------------------------------------------------------- projects page

    def _build_projects_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_border_width(18)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        heading = Gtk.Label(label="Projects", xalign=0)
        heading.get_style_context().add_class("dash-heading")
        header.pack_start(heading, True, True, 0)
        add_btn = Gtk.Button(label="+ Add Project")
        add_btn.get_style_context().add_class("accent-btn")
        add_btn.connect("clicked", self.on_add_project)
        header.pack_end(add_btn, False, False, 0)
        page.pack_start(header, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.projects_list = Gtk.ListBox()
        self.projects_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.projects_list.get_style_context().add_class("card-list")
        scroll.add(self.projects_list)
        page.pack_start(scroll, True, True, 0)
        return page

    def refresh_projects_list(self):
        for child in self.projects_list.get_children():
            self.projects_list.remove(child)
        projects = db.get_projects()
        if not projects:
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label="No projects yet — add one to link tasks to GitHub issues.", xalign=0))
            self.projects_list.add(row)
        for proj in projects:
            self.projects_list.add(self._build_project_row(proj))
        self.projects_list.show_all()

        self.progress_project_combo.remove_all()
        self._progress_projects = list(projects)
        self.progress_project_combo.append_text("— No project —")
        for proj in projects:
            self.progress_project_combo.append_text(proj["name"])
        self.progress_project_combo.set_active(0)

    def _build_project_row(self, proj):
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hbox.set_border_width(4)

        swatch = Gtk.DrawingArea()
        swatch.set_size_request(14, 14)
        color = proj["color"] or "#b8bb26"
        swatch.connect("draw", self._draw_swatch, color)
        hbox.pack_start(swatch, False, False, 0)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        name_lbl = Gtk.Label(label=proj["name"], xalign=0)
        name_lbl.get_style_context().add_class("dash-subheading")
        info.pack_start(name_lbl, False, False, 0)
        repo_txt = (
            f"{proj['repo_owner']}/{proj['repo_name']}" if proj["repo_owner"] else "no GitHub repo linked"
        )
        detail_lbl = Gtk.Label(label=f"{proj['local_path'] or '—'}  ·  {repo_txt}", xalign=0)
        detail_lbl.get_style_context().add_class("dash-muted")
        detail_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        info.pack_start(detail_lbl, False, False, 0)
        hbox.pack_start(info, True, True, 0)

        edit_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        edit_btn.connect("clicked", lambda b, p=proj: self.on_edit_project(p))
        hbox.pack_start(edit_btn, False, False, 0)

        del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        del_btn.connect("clicked", lambda b, p=proj: self.on_delete_project(p))
        hbox.pack_start(del_btn, False, False, 0)

        row.add(hbox)
        return row

    def _draw_swatch(self, widget, cr, hex_color):
        rgba = Gdk.RGBA()
        rgba.parse(hex_color)
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1.0)
        cr.arc(7, 7, 6, 0, 2 * 3.14159265)
        cr.fill()
        return False

    def on_add_project(self, button):
        dialog = ProjectDialog(self)
        if dialog.run() == Gtk.ResponseType.OK:
            values = dialog.get_values()
            if values["name"]:
                db.add_project(**values)
                self.refresh_projects_list()
                self.refresh_day_panel()
                self.on_change()
        dialog.destroy()

    def on_edit_project(self, proj):
        dialog = ProjectDialog(self, project_row=proj)
        if dialog.run() == Gtk.ResponseType.OK:
            values = dialog.get_values()
            if values["name"]:
                db.update_project(proj["id"], **values)
                self.refresh_projects_list()
                self.refresh_day_panel()
                self.on_change()
        dialog.destroy()

    def on_delete_project(self, proj):
        confirm = Gtk.MessageDialog(
            transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO, text=f"Delete project '{proj['name']}'?",
        )
        confirm.format_secondary_text("Linked tasks will be kept but unlinked.")
        response = confirm.run()
        confirm.destroy()
        if response == Gtk.ResponseType.YES:
            db.delete_project(proj["id"])
            self.refresh_projects_list()
            self.refresh_day_panel()
            self.on_change()

    # ------------------------------------------------------- calendar logic

    def selected_date_str(self):
        y, m, d = self.calendar.get_date()
        return f"{y:04d}-{m + 1:02d}-{d:02d}"

    def refresh_marks(self):
        self.calendar.clear_marks()
        y, m, _ = self.calendar.get_date()
        start = f"{y:04d}-{m + 1:02d}-01"
        end = f"{y + 1:04d}-01-01" if m == 11 else f"{y:04d}-{m + 2:02d}-01"
        marked = (
            db.get_dates_with_events(start, end)
            | db.get_dates_with_tasks(start, end)
            | db.get_dates_with_progress(start, end)
        )
        for date_str in marked:
            try:
                self.calendar.mark_day(int(date_str.split("-")[2]))
            except (ValueError, IndexError):
                pass

    def refresh_day_panel(self):
        date_str = self.selected_date_str()
        self.day_heading.set_text(date_str)

        self._fill_list(
            self.events_list, db.get_events_for_date(date_str),
            self._build_event_row, "No events",
        )
        self._fill_list(
            self.tasks_list, db.get_tasks_for_date(date_str),
            self._build_task_row, "No tasks due",
        )
        self._fill_list(
            self.progress_list, db.get_progress_for_date(date_str),
            self._build_progress_row, "No progress logged",
        )

    def _fill_list(self, listbox, rows, builder, empty_text):
        for child in listbox.get_children():
            listbox.remove(child)
        if not rows:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=empty_text, xalign=0)
            lbl.get_style_context().add_class("dash-muted")
            row.add(lbl)
            listbox.add(row)
        for item in rows:
            listbox.add(builder(item))
        listbox.show_all()

    def _build_event_row(self, ev):
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        time_str = f"{ev['time']}  " if ev["time"] else ""
        label = Gtk.Label(label=f"{time_str}{ev['title']}", xalign=0)
        hbox.pack_start(label, True, True, 0)
        edit_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        edit_btn.connect("clicked", lambda b, e=ev: self.on_edit_event(e))
        hbox.pack_start(edit_btn, False, False, 0)
        del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        del_btn.connect("clicked", lambda b, e=ev: self.on_delete_event(e))
        hbox.pack_start(del_btn, False, False, 0)
        row.add(hbox)
        return row

    def _build_task_row(self, task):
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        check = Gtk.CheckButton()
        check.set_active(task["status"] == "done")
        check.connect("toggled", lambda b, t=task: self.on_toggle_task(t, b.get_active()))
        hbox.pack_start(check, False, False, 0)

        label = Gtk.Label(label=task["title"], xalign=0)
        if task["status"] == "done":
            label.set_markup(f"<s>{GLib.markup_escape_text(task['title'])}</s>")
        hbox.pack_start(label, True, True, 0)

        project = db.get_project(task["project_id"]) if task["project_id"] else None
        if project:
            hbox.pack_start(colored_pill(project["name"], project["color"]), False, False, 0)

        if task["github_issue_number"]:
            link_btn = Gtk.Button(label=f"#{task['github_issue_number']}")
            link_btn.get_style_context().add_class("ghost-btn")
            link_btn.connect(
                "clicked",
                lambda b, url=task["github_issue_url"]: Gio.AppInfo.launch_default_for_uri(url, None),
            )
            hbox.pack_start(link_btn, False, False, 0)
        elif project and project["repo_owner"] and project["repo_name"]:
            issue_btn = Gtk.Button(label="Create Issue")
            issue_btn.get_style_context().add_class("ghost-btn")
            issue_btn.connect("clicked", lambda b, t=task, p=project: self.on_create_issue(t, p))
            hbox.pack_start(issue_btn, False, False, 0)

        edit_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        edit_btn.connect("clicked", lambda b, t=task: self.on_edit_task(t))
        hbox.pack_start(edit_btn, False, False, 0)
        del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        del_btn.connect("clicked", lambda b, t=task: self.on_delete_task(t))
        hbox.pack_start(del_btn, False, False, 0)

        row.add(hbox)
        return row

    def _build_progress_row(self, note):
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if note["project_name"]:
            hbox.pack_start(colored_pill(note["project_name"], note["project_color"]), False, False, 0)
        label = Gtk.Label(label=note["note"], xalign=0)
        label.set_line_wrap(True)
        hbox.pack_start(label, True, True, 0)
        del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        del_btn.connect("clicked", lambda b, n=note: self.on_delete_progress(n))
        hbox.pack_start(del_btn, False, False, 0)
        row.add(hbox)
        return row

    # ------------------------------------------------------------- actions

    def on_add_event(self, button):
        dialog = EventDialog(self, self.selected_date_str())
        if dialog.run() == Gtk.ResponseType.OK:
            values = dialog.get_values()
            if values["title"] and values["date"]:
                db.add_event(**values)
                self.refresh_marks()
                self.refresh_day_panel()
                self.on_change()
        dialog.destroy()

    def on_edit_event(self, ev):
        dialog = EventDialog(self, ev["date"], event_row=ev)
        if dialog.run() == Gtk.ResponseType.OK:
            values = dialog.get_values()
            if values["title"] and values["date"]:
                db.update_event(ev["id"], **values)
                self.refresh_marks()
                self.refresh_day_panel()
                self.on_change()
        dialog.destroy()

    def on_delete_event(self, ev):
        db.delete_event(ev["id"])
        self.refresh_marks()
        self.refresh_day_panel()
        self.on_change()

    def on_add_task(self, button):
        dialog = TaskDialog(self, self.selected_date_str(), db.get_projects())
        if dialog.run() == Gtk.ResponseType.OK:
            values = dialog.get_values()
            if values["title"]:
                db.add_task(**values)
                self.refresh_marks()
                self.refresh_day_panel()
                self.on_change()
        dialog.destroy()

    def on_edit_task(self, task):
        dialog = TaskDialog(self, task["due_date"] or self.selected_date_str(), db.get_projects(), task_row=task)
        if dialog.run() == Gtk.ResponseType.OK:
            values = dialog.get_values()
            if values["title"]:
                db.update_task(task["id"], **values)
                self.refresh_marks()
                self.refresh_day_panel()
                self.on_change()
        dialog.destroy()

    def on_delete_task(self, task):
        db.delete_task(task["id"])
        self.refresh_marks()
        self.refresh_day_panel()
        self.on_change()

    def on_toggle_task(self, task, is_done):
        db.set_task_status(task["id"], "done" if is_done else "todo")
        self.refresh_day_panel()
        self.on_change()

    def on_create_issue(self, task, project):
        try:
            number, url = ghi.create_issue(
                project["repo_owner"], project["repo_name"], task["title"], task["description"]
            )
        except ghi.GithubError as exc:
            error = Gtk.MessageDialog(
                transient_for=self, flags=0, message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK, text="Couldn't create GitHub issue",
            )
            error.format_secondary_text(str(exc))
            error.run()
            error.destroy()
            return
        db.set_task_github_issue(task["id"], number, url)
        self.refresh_day_panel()
        self.on_change()

    def on_log_progress(self, button):
        note = self.note_entry.get_text().strip()
        if not note:
            return
        idx = self.progress_project_combo.get_active()
        project_id = None if idx <= 0 else self._progress_projects[idx - 1]["id"]
        db.add_progress_note(project_id, self.selected_date_str(), note)
        self.note_entry.set_text("")
        self.refresh_marks()
        self.refresh_day_panel()
        self.on_change()

    def on_delete_progress(self, note):
        db.delete_progress_note(note["id"])
        self.refresh_marks()
        self.refresh_day_panel()
        self.on_change()
