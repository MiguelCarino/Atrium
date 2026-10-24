"""Settings page: USB drives and the phone. The game profiles live on the
Screenshots & recording page, next to gamemode; this page only points there.

Phone handoff (phone.py's open / file / watch): what goes each way, the
watcher service, and the one switch it has -- sign-in codes from the phone's
notifications, privacy.conf phone_codes (`phone.py codes on|off`), off as
shipped.

Ask from the phone (phone-ask.py): its own section, settings_pages/_phone_ask.py."""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402

from . import _phone_ask  # noqa: E402  (the "Ask from the phone" section)

PAGE = {"id": "devices", "title": "Devices", "icon": "\uf287", "group": "Hardware", "order": 90,
        "keywords": ["usb", "usb drives", "external drive", "eject", "automount", "phone", "kde connect",
                     "android", "find my phone", "handoff", "send to phone", "open on phone", "2fa",
                     "sign-in code", "verification code", "photos from phone", "ask from the phone",
                     "run command", "remote question", "preguntar desde el telefono"]}


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        w.pack_start(heading("USB DRIVES"), False, False, 0)
        self.drives = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.drives, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("PHONE"), False, False, 0)
        self.phone = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.phone, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("PHONE HANDOFF"), False, False, 0)
        self.handoff = dp.label("", "ctl-sub")
        self.handoff.set_line_wrap(True)
        self.handoff.set_max_width_chars(80)
        w.pack_start(self.handoff, False, False, 0)
        self.codes = Gtk.Switch()
        self.codes_busy = False
        self.codes.connect("state-set", self.flip_codes)
        grid, _ = row("", "Offer sign-in codes from the phone",
                      "2FA codes in phone notifications, one click to copy (kept 60 s)", self.codes)
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open this page on the phone", lambda: spawn(PHONE, "open")),
                               link("Send a file", lambda: spawn(PHONE, "file")),
                               link("Send copied files", lambda: spawn(PHONE, "file", "--copied"))),
                     False, False, 0)
        # The fixes (commands) for what show_handoff found missing; hidden when nothing is.
        self.handoff_fix = dp.label("", "ctl-sub")
        self.handoff_fix.set_line_wrap(True)
        self.handoff_fix.set_selectable(True)
        self.handoff_fold = details(self.handoff_fix, label="How to fix")
        self.handoff_fold.set_no_show_all(True)
        w.pack_start(self.handoff_fold, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        self.ask = _phone_ask.Section()     # asking the desktop from the phone (phone-ask.py)
        w.pack_start(self.ask.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("GAMES"), False, False, 0)
        grid, _ = row("\uf11b", "Game profiles and game mode",
                      "per-game setup and what game mode turns off",
                      link("Open Screenshots & recording", lambda: spawn(os.path.join(HYPR, "settings.py"), "capture")))
        w.pack_start(grid, False, False, 0)

    def refresh(self):
        for box in (self.drives, self.phone):
            if not box.get_children():
                box.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)
                box.show_all()
        background(lambda: (run_json(AUTOMOUNT, "list", "--json") or [],
                            run_json(PHONE, "list", "--json"),
                            run(PHONE, "bar"),
                            run_json(AUTOMOUNT, "get", "--json") or {}), self.show)
        background(lambda: run_json(PHONE, "status", "--json"), self.show_handoff)
        self.ask.refresh()

    # -- phone handoff ----------------------------------------------------------------------
    def flip_codes(self, _switch, on):
        if self.codes_busy:
            return True
        background(lambda: run(PHONE, "codes", "on" if on else "off"), lambda _r: self.refresh())
        return True

    def show_handoff(self, st):
        st = st or {}
        self.codes_busy = True
        try:
            self.codes.set_active(bool(st.get("codes")))
            self.codes.set_state(bool(st.get("codes")))
        finally:
            self.codes_busy = False
        fixes = []
        if not st.get("kdeconnect"):
            text = "KDE Connect is not running: nothing goes either way."
        else:
            text = ("Pages, files and the clipboard go to the phone; its shared text and links land on the "
                    "clipboard, photos in ~/Pictures/Phone.")
            if not st.get("watcher"):
                text += "\nLinks and photos from the phone are not being picked up."
                fixes.append("systemctl --user enable --now phone-handoff")
            if not st.get("picker"):
                text += "\nNo file picker installed."
                fixes.append("sudo dnf install zenity")
            plugins = st.get("plugins") or {}
            off = [k for k in ("share", "notifications") if k in plugins and not plugins[k]]
            if off:
                text += f"\nOff in the phone's KDE Connect plugins: {', '.join(off)}."
        self.handoff.set_text(text)
        self.handoff_fix.set_text("\n".join(fixes))
        self.handoff_fold.set_no_show_all(not fixes)
        self.widget.show_all()
        self.handoff_fold.set_visible(bool(fixes))

    def show(self, data):
        drives, phones, phone_bar, auto = data
        clear(self.drives)
        if not drives:
            # Worded from what automount.py really does now (Settings >
            # Storage switches both): mounted, opened in Files, or neither.
            if auto.get("mount", True) and auto.get("open", True):
                what = "mounted and opened in Files when plugged in"
            elif auto.get("mount", True):
                what = "mounted when plugged in"
            else:
                what = "not mounted by themselves (Storage page)"
            lab = dp.label("None plugged in  ·  drives are " + what, "ctl-sub")
            lab.set_line_wrap(True)
            self.drives.pack_start(lab, False, False, 0)
        for d in drives:
            grid, _ = row("", d["label"], d["mount"], link("Eject", lambda m=d["mount"]: background(
                # In the background: an eject waits for the drive to finish
                # writing, seconds the window would otherwise sit frozen for.
                lambda: run(AUTOMOUNT, "eject", m, timeout=120), lambda _r: self.refresh())))
            self.drives.pack_start(grid, False, False, 0)
            self.drives.pack_start(links_row(link("Open", lambda m=d["mount"]: spawn("nautilus", m))), False, False, 0)
        clear(self.phone)
        if phones is None:
            sub = "KDE Connect is not running: finish the setup on the System page."
            self.phone.pack_start(dp.label(sub, "ctl-sub"), False, False, 0)
        elif not phones:
            msg = "No phone paired: pair this computer from KDE Connect on the phone (same network)."
            lab = dp.label(msg, "ctl-sub")
            lab.set_line_wrap(True)
            self.phone.pack_start(lab, False, False, 0)
            self.phone.pack_start(dp.label(f"This computer: {self.my_ip()} (to add it by IP)", "ctl-title"),
                                  False, False, 0)
        else:
            try:
                bar = json.loads(phone_bar or "{}")
            except ValueError:
                bar = {}
            for p in phones:
                sub = ("reachable" if p["reachable"] else "away") + (
                    f"  ·  {bar.get('tooltip', '').splitlines()[0]}" if p["reachable"] and bar.get("tooltip") else "")
                grid, _ = row("", p["name"], sub)
                self.phone.pack_start(grid, False, False, 0)
            self.phone.pack_start(links_row(link("Ring it", lambda: spawn(PHONE, "ring")),
                                            link("Send the clipboard", lambda: spawn(PHONE, "clip")),
                                            link("Ping", lambda: spawn(PHONE, "ping"))), False, False, 0)
        self.widget.show_all()

    @staticmethod
    def my_ip():
        out = run("ip", "-4", "-o", "route", "get", "1.1.1.1")
        parts = out.split()
        return parts[parts.index("src") + 1] if "src" in parts else "?"


