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
                      "When a phone notification (an SMS, an app) carries a 2FA code, a notification offers it: "
                      "click to copy. On the clipboard for 60 s, never in its history, never logged. Reads the "
                      "phone's notifications on this computer only.", self.codes)
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open this page on the phone", lambda: spawn(PHONE, "open")),
                               link("Send a file", lambda: spawn(PHONE, "file")),
                               link("Send copied files", lambda: spawn(PHONE, "file", "--copied"))),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)
        self.ask = _phone_ask.Section()     # asking the desktop from the phone (phone-ask.py)
        w.pack_start(self.ask.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("GAMES"), False, False, 0)
        grid, _ = row("\uf11b", "Game profiles and game mode",
                      "what each game sets up when it starts, and what game mode turns off -- on the "
                      "Screenshots & recording page",
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
        if not st.get("kdeconnect"):
            text = "KDE Connect is not running: nothing goes either way."
        else:
            text = ("To the phone: the page in your browser (opens in the phone's browser), files (a picker, or "
                    "the ones copied in Files), the clipboard. From the phone: shared text lands on the clipboard "
                    "(KDE Connect does that itself), shared links on the clipboard too (KDE Connect also opens "
                    "them), photos and videos in ~/Pictures/Phone.")
            if not st.get("watcher"):
                text += ("\nThe watcher (phone-handoff.service) is not running: links and photos from the phone "
                         "are left as KDE Connect leaves them. systemctl --user enable --now phone-handoff")
            if not st.get("picker"):
                text += "\nNo file picker: sudo dnf install zenity"
            plugins = st.get("plugins") or {}
            off = [k for k in ("share", "notifications") if k in plugins and not plugins[k]]
            if off:
                text += f"\nOff in the phone's KDE Connect plugins: {', '.join(off)}."
        self.handoff.set_text(text)
        self.widget.show_all()

    def show(self, data):
        drives, phones, phone_bar, auto = data
        clear(self.drives)
        if not drives:
            # Worded from what automount.py really does now (Settings >
            # Storage switches both): mounted, opened in Files, or neither.
            if auto.get("mount", True) and auto.get("open", True):
                what = "A USB drive is mounted and opens in Files by itself when you plug it in."
            elif auto.get("mount", True):
                what = "A USB drive is mounted by itself when you plug it in (opening it in Files is off)."
            else:
                what = "Plugged-in drives are not mounted by themselves (switched off on the Storage page)."
            lab = dp.label("None plugged in. " + what, "ctl-sub")
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
            sub = ("KDE Connect is not running. If setup-root.sh has not finished, run it (System page), "
                   "then open KDE Connect on the phone.")
            self.phone.pack_start(dp.label(sub, "ctl-sub"), False, False, 0)
        elif not phones:
            msg = ("No phone paired. Open KDE Connect on the phone (same network), allow it to find local "
                   "devices, pick this computer and pair; accept the request here. If it does not show this "
                   "computer, add it by IP address in the phone app.")
            lab = dp.label(msg, "ctl-sub")
            lab.set_line_wrap(True)
            self.phone.pack_start(lab, False, False, 0)
            self.phone.pack_start(dp.label(f"This computer: {self.my_ip()}", "ctl-title"), False, False, 0)
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


