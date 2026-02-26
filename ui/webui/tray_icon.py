#!/usr/bin/env python3
"""Frank Web UI — System tray icon with 'WEB' label.

Creates a green tray icon that opens http://localhost:8099 in the browser.
"""
import os
import signal
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

try:
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
except ImportError:
    pass

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3


WEB_URL = "http://127.0.0.1:8099"
ICON_SIZE = 22


def _create_icon() -> str:
    """Create a small green 'WEB' icon as PNG and return path."""
    try:
        import cairo
    except ImportError:
        # Fallback: use a simple text file icon
        icon_path = Path(tempfile.gettempdir()) / "frank_web_icon.svg"
        icon_path.write_text(
            '<?xml version="1.0"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">'
            '<rect width="22" height="22" rx="3" fill="#0a0a0a" stroke="#00FF41" stroke-width="1"/>'
            '<text x="11" y="15" text-anchor="middle" fill="#00FF41" '
            'font-family="monospace" font-size="7" font-weight="bold">WEB</text>'
            '</svg>'
        )
        return str(icon_path)

    icon_path = Path(tempfile.gettempdir()) / "frank_web_icon.png"
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, ICON_SIZE, ICON_SIZE)
    ctx = cairo.Context(surface)

    # Background
    ctx.set_source_rgb(0.04, 0.04, 0.04)
    ctx.rectangle(0, 0, ICON_SIZE, ICON_SIZE)
    ctx.fill()

    # Border
    ctx.set_source_rgb(0, 1.0, 0.25)
    ctx.set_line_width(1)
    ctx.rectangle(0.5, 0.5, ICON_SIZE - 1, ICON_SIZE - 1)
    ctx.stroke()

    # Text "WEB"
    ctx.set_source_rgb(0, 1.0, 0.25)
    ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(7)
    extents = ctx.text_extents("WEB")
    x = (ICON_SIZE - extents.width) / 2 - extents.x_bearing
    y = (ICON_SIZE - extents.height) / 2 - extents.y_bearing
    ctx.move_to(x, y)
    ctx.show_text("WEB")

    surface.write_to_png(str(icon_path))
    return str(icon_path)


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())

    icon_path = _create_icon()

    indicator = AyatanaAppIndicator3.Indicator.new(
        "frank-webui",
        icon_path,
        AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)

    # Menu
    menu = Gtk.Menu()

    item_open = Gtk.MenuItem(label="Open Web UI")
    item_open.connect("activate", lambda _: webbrowser.open(WEB_URL))
    menu.append(item_open)

    menu.append(Gtk.SeparatorMenuItem())

    item_quit = Gtk.MenuItem(label="Quit")
    item_quit.connect("activate", lambda _: Gtk.main_quit())
    menu.append(item_quit)

    menu.show_all()
    indicator.set_menu(menu)

    Gtk.main()


if __name__ == "__main__":
    main()
