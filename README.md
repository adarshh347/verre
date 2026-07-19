# verre

*French for glass.*

An OS-level UI/UX revamp of the Linux desktop — rethinking the shell, widgets, and visual language as one coherent system.

## Current pieces

**Calendar widget** — glass-blur desktop calendar. Manage events and your timeline locally, no Google Calendar required.

- `app.py` — main widget app
- `dashboard.py` — dashboard UI
- `db.py` — local event storage (SQLite)
- `github_integration.py` — GitHub activity integration

Autostarts via `~/.config/autostart/desktop-calendar-widget.desktop`.

## Roadmap

Deeper shell-level revamp: unified theming, compositor effects, and a consistent glass design language across the desktop.
