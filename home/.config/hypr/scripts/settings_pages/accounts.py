"""Settings page: you (name, picture, password), how the login screen starts,
online accounts; what this computer lets in from the network and how it is
protected (firewall, SSH server, KDE Connect, Secure Boot, SELinux, disk
encryption, problem reporting); and the printers.

Everything goes through ~/.config/hypr/scripts/accounts.py, which reads it
all fresh from where the system keeps it (`accounts.py status`) and does the
few changes your own account may make without root: the picture and the full
name (AccountsService allows both for yourself), your default printer and
your own print jobs (CUPS). The rest -- automatic login, the firewall, the
SSH server, automatic crash reports, a paused printer -- belongs to root, so
those buttons copy the exact command (`accounts.py copy ...`) for you to
paste into a terminal; nothing here runs sudo, and the page redraws from
what the system says once it has happened. "Change password" opens `passwd`
in your terminal, where it asks for the old password and the new one itself.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

PAGE = {"id": "accounts", "title": "Users, sharing & printers", "icon": "", "group": "System", "order": 40,
        "keywords": ["user", "usuario", "account", "cuenta", "name", "picture", "avatar", "password",
                     "contraseña", "login screen", "automatic login", "autologin", "online accounts",
                     "sharing", "security", "firewall", "ssh", "remote login", "kde connect", "secure boot",
                     "selinux", "encryption", "luks", "crash reports", "abrt", "printer", "impresora",
                     "print jobs", "cups", "default printer"]}

ACCOUNTS = os.path.join(HYPR, "accounts.py")
SETTINGS = os.path.join(HYPR, "settings.py")
USER, LOGIN, CLOUD, KEY, SHIELD, SSH, PHONE_ICON, CHIP, LOCK, DISK, BUG, PRINTER, JOB = (
    "", "", "", "", "", "", "", "", "", "",
    "", "", "")
# Root steps that can cut you off if pasted without thinking: said under
# the "Copied" line so the clipboard never holds one of them unexplained.
CAREFUL = {
    ("firewall-close", "dhcpv6-client"): "without it this computer gets no IPv6 address from the router",
    ("firewall-close", "ssh"): "an SSH session from another computer is cut off at once",
    ("firewall-zone", "block"): "no new connection from the network gets in: KDE Connect, sharing and SSH stop",
    ("firewall-zone", "drop"): "no new connection from the network gets in: KDE Connect, sharing and SSH stop",
}
# What each firewalld zone means, for the zone chips' explanation.
ZONES = {
    "FedoraWorkstation": "Fedora's desktop default: everything from port 1025 up is open (so games, KDE Connect "
                         "and local sharing just work), the system ports below only for the services listed",
    "FedoraServer": "only the services listed get in",
    "public": "an untrusted network (a café): only the services listed get in",
    "home": "a home network: the services listed, plus local discovery",
    "work": "a work network: the services listed",
    "internal": "a trusted internal network",
    "trusted": "everything gets in -- only for a network you fully control",
    "block": "nothing gets in; answers with a refusal",
    "drop": "nothing gets in, not even an answer",
    "external": "for a router doing NAT",
    "dmz": "for a computer exposed on purpose: only the services listed",
}


def short_home(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path and path.startswith(home) else path


def user_sub(u):
    """The line under your name: login, account type, password age, groups."""
    bits = [f"login {u['login']}", "administrator (can use sudo)" if u["admin"] else "standard account"]
    if u.get("password_changed"):
        bits.append(f"password last changed {u['password_changed']}")
    extra = [g for g in u.get("groups", []) if g not in (u["login"], "wheel")]
    if extra:
        bits.append("also in " + ", ".join(extra))
    return "  ·  ".join(bits)


def picture_sub(u):
    if not u.get("picture"):
        where = "no picture yet"
    elif u.get("accounts_icon") and u.get("face"):
        where = "shown on the login screen (AccountsService) and kept in ~/.face for apps that read it"
    elif u.get("accounts_icon"):
        where = "shown on the login screen (AccountsService); ~/.face is not set, a change writes both"
    else:
        where = "~/.face only; the login screen has none"
    return where + ("  ·  the one you had before is kept: Undo puts it back" if u.get("undo") else "")


def autologin_sub(lg):
    """How the computer starts: the login screen, or straight to the desktop."""
    dm = lg.get("dm") or "no login screen service"
    if not lg.get("kind"):
        return f"login screen: {dm}, which this page does not know how to read"
    if not lg.get("readable"):
        return f"login screen: {dm}  ·  its config ({lg.get('config')}) is not readable without root"
    if lg.get("autologin"):
        who = "you" if lg.get("mine") else lg["autologin"]
        return (f"ON: at boot {dm} logs {who} straight in, no password  ·  anyone at the keyboard gets the "
                "desktop, and the keyring (saved Wi-Fi and browser passwords) stays locked until you type the "
                f"password once  ·  set in {lg['config']}")
    return f"off: {dm} asks for your password at every start  ·  set in {lg['config']}"


def firewall_sub(fw):
    if not fw.get("installed"):
        return "firewalld is not installed: nothing filters what comes in from the network"
    if not fw.get("running"):
        return ("NOT running: every port a program opens can be reached from the network"
                + ("  ·  it is set to start at boot" if fw.get("enabled") else "  ·  and it does not start at boot"))
    bits = [f"on  ·  zone {fw.get('zone')}" + (f" for {', '.join(fw['interfaces'])}" if fw.get("interfaces") else "")]
    if fw.get("zone") in ZONES:
        bits.append(ZONES[fw["zone"]])
    if fw.get("ports"):
        bits.append("open ports: " + ", ".join(fw["ports"]))
    return "  ·  ".join(bits)


def ssh_sub(ssh, fw):
    if not ssh.get("installed"):
        return "the SSH server is not installed (sudo dnf install openssh-server)"
    state = "ON: you can log in to this computer from another one" if ssh["active"] else \
        "off: nobody can log in to this computer over the network"
    bits = [state, "starts at boot" if ssh["enabled"] else "does not start at boot"]
    if not fw.get("running"):
        if ssh["active"]:
            bits.append("no firewall is running, so it can be reached from the network")
    elif ssh["active"] and "ssh" not in (fw.get("services") or []):
        bits.append("the firewall does not let it in, though")
    elif not ssh["active"] and "ssh" in (fw.get("services") or []):
        bits.append("the firewall's ssh opening is unused while it is off")
    return "  ·  ".join(bits)


def kdeconnect_let_in(fw):
    """Whether the firewall lets KDE Connect (ports 1714-1764) in: no
    firewall running, its service listed, or a zone that opens 1025 and up
    (FedoraWorkstation)."""
    if not fw.get("running"):
        return True
    return "kdeconnect" in (fw.get("services") or []) or \
        all(f"1025-65535/{proto}" in (fw.get("ports") or []) for proto in ("tcp", "udp"))


def phone_sub(phones, installed, fw=None):
    if not installed:
        return "KDE Connect is not installed"
    if phones is None:
        return "KDE Connect is not running"
    if not phones:
        return "running, no phone paired  ·  it talks on ports 1714-1764, which " + (
            "the firewall lets in" if kdeconnect_let_in(fw or {}) else
            "the firewall shuts out: click kdeconnect under \"Let in\" above")
    names = ", ".join(f"{p['name']} ({'here' if p['reachable'] else 'away'})" for p in phones)
    return f"paired: {names}  ·  it can share files, the clipboard and notifications"


def disks_sub(disks):
    if not disks:
        return "no disks found"
    locked = [d["mount"] for d in disks if d["encrypted"]]
    plain = [d["mount"] for d in disks if not d["encrypted"]]
    if not plain:
        return "every disk is encrypted (LUKS): a stolen disk cannot be read without the password"
    text = f"not encrypted: {', '.join(plain)}"
    if locked:
        text += f"  ·  encrypted (LUKS): {', '.join(locked)}"
    return text + ("  ·  anyone with the disk in hand can read it. Encrypting means reinstalling (or a careful "
                   "offline conversion): it is chosen in the installer")


def selinux_sub(sec):
    mode, conf = sec.get("selinux"), sec.get("selinux_config")
    if not mode:
        return "SELinux is not available"
    text = {"Enforcing": "enforcing: each service is held to what it is meant to touch",
            "Permissive": "PERMISSIVE: rule breaks are only logged, not stopped",
            "Disabled": "DISABLED"}.get(mode, mode)
    if conf and conf.lower() != mode.lower():
        text += f"  ·  set to {conf} from the next boot"
    return text


def secure_boot_sub(sb):
    if sb is None:
        return "unknown: this computer did not start through UEFI"
    if sb:
        return "on: the firmware only starts a signed boot loader and kernel"
    return ("off: the firmware starts any boot loader. The NVIDIA driver is an unsigned kernel module, which "
            "Secure Boot would refuse until it is signed (a key enrolled with mokutil) -- turn it on in the "
            "firmware settings only after that")


def abrt_sub(ab):
    if not ab.get("installed"):
        return "ABRT is not installed: crashes are only in the journal (coredumpctl list)"
    bits = [f"{ab['problems']} crash report{'s' if ab['problems'] != 1 else ''} kept" if ab["problems"]
            else "no crash reports kept",
            "collecting" if ab["running"] else "NOT collecting (abrtd is stopped)",
            "sent to Fedora automatically" if ab["auto"] else "nothing is sent unless you report one yourself"]
    return "  ·  ".join(bits)


def printer_sub(p, default):
    state = {"idle": "ready", "printing": "printing",
             "disabled": "PAUSED"}.get(p["state"], p["state"])
    bits = [state + (f" since {p['since']}" if p["state"] == "disabled" and p.get("since") else "")]
    if p.get("reason"):
        bits.append(p["reason"])
    if p.get("connection"):
        bits.append({"usb": "USB", "ipp": "network (IPP)", "ipps": "network (IPP)", "dnssd": "network",
                     "socket": "network", "lpd": "network (LPD)", "implicitclass": "found on the network"}
                    .get(p["connection"], p["connection"]))
    if p.get("location"):
        bits.append(p["location"])
    if p["name"] == default:
        bits.append("default")
    if p["state"] == "disabled":
        bits.append("CUPS pauses a printer that was unplugged or off when something was sent; once it is back, "
                    "Resume copies the command that takes it back into use")
    return "  ·  ".join(bits)


def cli(*args, timeout=30):
    """accounts.py ARGS: (worked, its one line) -- stdout, or stderr when it
    failed, so the page can show why a click did nothing."""
    try:
        r = subprocess.run([ACCOUNTS, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"accounts.py did not run: {exc}"
    lines = (r.stdout.strip() if r.returncode == 0 else r.stderr.strip() or r.stdout.strip()).splitlines()
    return r.returncode == 0, (lines[-1] if lines else "")


def small(text):
    lab = dp.label(text, "ctl-sub")
    lab.set_line_wrap(True)
    lab.set_max_width_chars(90)
    return lab


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data = None
        # The last action's answer (what was copied, what failed), on top.
        self.msg = small("")
        self.msg.set_selectable(True)
        self.msg.set_no_show_all(True)
        w.pack_start(self.msg, False, False, 0)

        w.pack_start(heading("YOU"), False, False, 0)
        top = Gtk.Box(spacing=14)
        self.picture = Gtk.Image()
        self.picture.set_size_request(72, 72)
        self.picture.set_valign(Gtk.Align.START)
        top.pack_start(self.picture, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.name_title = dp.label("…", "ctl-title")
        right.pack_start(self.name_title, False, False, 0)
        self.user_sub = small("checking…")
        right.pack_start(self.user_sub, False, False, 0)
        self.picture_sub = small("")
        right.pack_start(self.picture_sub, False, False, 0)
        top.pack_start(right, True, True, 0)
        w.pack_start(top, False, False, 0)
        self.undo_link = link("Undo picture", lambda: self.do("avatar", "--undo"))
        w.pack_start(links_row(link("Change picture…", self.pick_picture), self.undo_link,
                               link("Change password…", lambda: self.do("password"))), False, False, 0)
        self.name_entry = Gtk.Entry()
        self.name_entry.set_width_chars(28)
        self.name_entry.connect("activate", lambda _e: self.save_name())
        box = Gtk.Box(spacing=6)
        box.pack_start(self.name_entry, False, False, 0)
        box.pack_start(link("Save", self.save_name), False, False, 0)
        grid, self.name_sub = row(USER, "Full name", "shown on the login screen, the lock screen and in apps "
                                  "that ask who you are (git keeps its own: git config user.name)", box)
        w.pack_start(grid, False, False, 0)
        grid, self.pw_sub = row(KEY, "Password", "Change password opens passwd in your terminal: it asks for the "
                                "current password, then the new one twice. The same password unlocks the screen, "
                                "sudo and the keyring (the keyring follows only when changed this way while "
                                "logged in)")
        w.pack_start(grid, False, False, 0)
        self.auto_link = link("Copy the command", lambda: self.copy(self.auto_what))
        grid, self.auto_sub = row(LOGIN, "Automatic login", "", self.auto_link)
        self.auto_what = "autologin-on"
        w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("ONLINE ACCOUNTS"), False, False, 0)
        grid, self.online_sub = row(CLOUD, "Online accounts", "", link("Open Online Accounts…",
                                                                         lambda: self.do("online")))
        w.pack_start(grid, False, False, 0)
        self.online_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.online_list, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SHARING AND SECURITY"), False, False, 0)
        self.fw_link = link("Copy: turn it off", lambda: self.copy(self.fw_what))
        self.fw_what = "firewall-off"
        grid, self.fw_sub = row(SHIELD, "Firewall", "", self.fw_link)
        w.pack_start(grid, False, False, 0)
        self.services_label = small("")
        w.pack_start(self.services_label, False, False, 0)
        self.services = self.make_chips(lambda s: self.copy("firewall-close", s))
        w.pack_start(self.services.widget, False, False, 0)
        self.offer_label = small("Let in (copies the command):")
        w.pack_start(self.offer_label, False, False, 0)
        self.offer = self.make_chips(lambda s: self.copy("firewall-open", s))
        w.pack_start(self.offer.widget, False, False, 0)
        self.zone_label = small("Default zone (copies the command):")
        w.pack_start(self.zone_label, False, False, 0)
        self.zones = self.make_chips(lambda z: self.copy("firewall-zone", z))
        w.pack_start(self.zones.widget, False, False, 0)
        self.ssh_link = link("Copy: turn it on", lambda: self.copy(self.ssh_what))
        self.ssh_what = "ssh-on"
        grid, self.ssh_sub = row(SSH, "SSH server", "", self.ssh_link)
        w.pack_start(grid, False, False, 0)
        grid, self.phone_sub = row(PHONE_ICON, "KDE Connect", "", link("Open Devices", lambda: spawn(SETTINGS,
                                                                                                    "devices")))
        w.pack_start(grid, False, False, 0)
        grid, self.sb_sub = row(CHIP, "Secure Boot", "")
        w.pack_start(grid, False, False, 0)
        grid, self.se_sub = row(LOCK, "SELinux", "")
        w.pack_start(grid, False, False, 0)
        grid, self.disk_sub = row(DISK, "Disk encryption", "")
        w.pack_start(grid, False, False, 0)
        self.abrt_open = link("Open crash reports", lambda: spawn("gnome-abrt"))
        self.abrt_link = link("Copy: send automatically", lambda: self.copy(self.abrt_what))
        self.abrt_what = "abrt-autoreport-on"
        grid, self.abrt_sub = row(BUG, "Problem reporting (ABRT)", "")
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(self.abrt_open, self.abrt_link), False, False, 0)
        w.pack_start(small("Every change marked \"Copy\" needs root: the command goes to the clipboard -- paste it "
                           "into a terminal and type your password. This page shows the result on its next look "
                           "(Check again)."), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("PRINTERS"), False, False, 0)
        self.printers = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.printers, False, False, 0)
        self.jobs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.jobs, False, False, 0)
        self.gnome_printers = link("Add a printer…", lambda: self.do("printers"))
        w.pack_start(links_row(link("Open the CUPS page", lambda: self.do("cups")), self.gnome_printers,
                               link("Check again", self.refresh)), False, False, 0)
        w.pack_start(small("Adding a printer: most network and USB printers made in the last ten years print "
                           "without any setup (driverless IPP) and show up above on their own. For an older one, "
                           "Add a printer opens GNOME's printer settings; the CUPS page (Administration > Add "
                           "Printer) does the same in the browser and asks for your login and password."),
                     False, False, 0)
        self.updating = False

    @staticmethod
    def make_chips(on_pick):
        chips = Chips(on_pick)
        chips.widget.set_max_children_per_line(7)
        chips.widget.set_halign(Gtk.Align.START)
        plain_set = chips.set

        def set_items(items, active):
            plain_set(items, active)
            chips.widget.set_min_children_per_line(max(1, min(len(items), 7)))
        chips.set = set_items
        return chips

    # -- actions ---------------------------------------------------------------------
    def say(self, text):
        self.msg.set_text(text)
        self.msg.set_visible(bool(text))

    def do(self, *args):
        """accounts.py ARGS in the background, its line on top, then redraw."""
        background(lambda: cli(*args), lambda res: (self.say(("" if res[0] else "!  ") + res[1]), self.refresh()))

    def copy(self, what, arg=None):
        def done(res):
            ok, text = res
            if ok:
                warn = CAREFUL.get((what, arg), "")
                self.say("Copied " + text.removeprefix("copied: ") + "\n-- paste it into a terminal; it asks "
                         "for your password there." + (f"\nCareful: {warn}" if warn else ""))
            else:
                self.say("!  " + text)
        background(lambda: cli("copy", what, *([arg] if arg else [])), done)

    def save_name(self):
        name = self.name_entry.get_text().strip()
        if self.data and name == self.data["user"]["real_name"]:
            self.say("That is already your name.")
            return
        self.do("realname", name)

    def pick_picture(self):
        dialog = Gtk.FileChooserDialog(title="Choose a picture", transient_for=self.widget.get_toplevel(),
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Use this picture", Gtk.ResponseType.ACCEPT)
        filt = Gtk.FileFilter()
        filt.set_name("Pictures")
        filt.add_pixbuf_formats()
        dialog.add_filter(filt)
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        if pictures:
            dialog.set_current_folder(pictures)
        preview = Gtk.Image()
        dialog.set_preview_widget(preview)

        def update_preview(_d):
            path = dialog.get_preview_filename()
            try:
                preview.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 160, 160, True))
                dialog.set_preview_widget_active(True)
            except (GLib.Error, TypeError):
                dialog.set_preview_widget_active(False)
        dialog.connect("update-preview", update_preview)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            path = dialog.get_filename()
            self.say("Setting the picture…")
            self.do("avatar", path)
        dialog.destroy()

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        if self.data is None:
            self.user_sub.set_text("checking…")
        background(lambda: (run_json(ACCOUNTS, "status", timeout=30), run_json(PHONE, "list", "--json")), self.show)

    def show(self, result):
        data, phones = result
        if not data:
            self.user_sub.set_text("accounts.py did not answer (run `accounts.py status` in a terminal to see why)")
            return
        self.data = data
        u = data["user"]
        self.name_title.set_text(u["real_name"] or u["login"])
        self.user_sub.set_text(user_sub(u))
        self.picture_sub.set_text(picture_sub(u))
        self.show_picture(u.get("picture"))
        if not self.name_entry.has_focus():
            self.name_entry.set_text(u["real_name"] or "")
        if not u.get("accountsservice"):
            self.name_sub.set_text("AccountsService did not answer, so the name cannot be changed from here")

        lg = data["login"]
        self.auto_sub.set_text(autologin_sub(lg))
        self.auto_what = "autologin-off" if lg.get("autologin") else "autologin-on"
        self.auto_link.set_label("Copy: turn it off" if lg.get("autologin") else "Copy: turn it on")
        self.auto_link.set_visible(bool(lg.get("kind")) and lg.get("readable", False))

        on = data["online"]
        clear(self.online_list)
        if not on["daemon"]:
            self.online_sub.set_text("gnome-online-accounts is not running: no accounts are shared with apps")
        elif not on["accounts"]:
            self.online_sub.set_text("none  ·  an account added here (Google, Microsoft, Nextcloud...) shows its "
                                     "mail, calendar, contacts and files in the GNOME apps and in Files")
        else:
            self.online_sub.set_text(f"{len(on['accounts'])} account{'s' if len(on['accounts']) != 1 else ''}, "
                                     "shared with the GNOME apps (Calendar, Contacts, Files)")
            for a in on["accounts"]:
                self.online_list.pack_start(small(f"    {a['provider']}" + (f"  ·  {a['identity']}"
                                                                           if a["identity"] else "")),
                                            False, False, 0)
        if not on["panel"]:
            self.online_sub.set_text(self.online_sub.get_text() + "  ·  adding one needs GNOME Settings: "
                                     "sudo dnf install gnome-control-center")

        fw = data["firewall"]
        self.fw_sub.set_text(firewall_sub(fw))
        running = fw.get("installed") and fw.get("running")
        self.fw_what = "firewall-off" if running else "firewall-on"
        self.fw_link.set_label("Copy: turn it off" if running else "Copy: turn it on")
        self.fw_link.set_visible(bool(fw.get("installed")))
        services = fw.get("services") or []
        self.services_label.set_text(("Services let in -- click one to copy the command that shuts it out:"
                                      if services else "No services are let in by name.") if running else "")
        self.services.set([(s, f"{s}  ✕") for s in services], None)
        self.offer.set([(s, s) for s in fw.get("offer", []) if s not in services], None)
        self.zones.set([(z, z) for z in fw.get("zones", []) if z in ZONES or z == fw.get("zone")], fw.get("zone"))

        ssh = data["ssh"]
        self.ssh_sub.set_text(ssh_sub(ssh, fw))
        self.ssh_what = "ssh-off" if ssh.get("active") or ssh.get("enabled") else "ssh-on"
        self.ssh_link.set_label("Copy: turn it off" if self.ssh_what == "ssh-off" else "Copy: turn it on")
        self.ssh_link.set_visible(bool(ssh.get("installed")))
        self.phone_sub.set_text(phone_sub(phones, data["kdeconnect"]["installed"], fw))

        sec = data["security"]
        self.sb_sub.set_text(secure_boot_sub(sec["secure_boot"]))
        self.se_sub.set_text(selinux_sub(sec))
        self.disk_sub.set_text(disks_sub(sec["disks"]))
        ab = data["abrt"]
        self.abrt_sub.set_text(abrt_sub(ab))
        self.abrt_what = "abrt-autoreport-off" if ab.get("auto") else "abrt-autoreport-on"
        self.abrt_link.set_label("Copy: stop sending automatically" if ab.get("auto")
                                 else "Copy: send automatically")

        self.show_printers(data["printing"])
        self.widget.show_all()
        self.msg.set_visible(bool(self.msg.get_text()))
        self.undo_link.set_visible(bool(u.get("undo")))
        self.auto_link.set_visible(bool(lg.get("kind")) and lg.get("readable", False))
        self.fw_link.set_visible(bool(fw.get("installed")))
        for widget in (self.services_label, self.services.widget, self.offer_label, self.offer.widget,
                       self.zone_label, self.zones.widget):
            widget.set_visible(bool(running))
        self.ssh_link.set_visible(bool(ssh.get("installed")))
        self.abrt_open.set_visible(bool(ab.get("viewer")))
        self.abrt_link.set_visible(bool(ab.get("installed")))
        self.gnome_printers.set_visible(bool(data["printing"].get("panel")))

    def show_picture(self, path):
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 72, 72, True) if path else None
        except GLib.Error:
            pix = None
        if pix:
            self.picture.set_from_pixbuf(pix)
        else:
            self.picture.set_from_icon_name("avatar-default-symbolic", Gtk.IconSize.DIALOG)
            self.picture.set_pixel_size(64)

    def show_printers(self, pr):
        clear(self.printers)
        clear(self.jobs)
        if not pr.get("installed"):
            self.printers.pack_start(small("CUPS is not installed: sudo dnf install cups && sudo systemctl enable "
                                           "--now cups"), False, False, 0)
            return
        if not pr["running"]:
            self.printers.pack_start(small("The printing service (CUPS) is not running; it starts by itself when "
                                           "something prints. To start it now: sudo systemctl start cups"),
                                     False, False, 0)
        if not pr["printers"]:
            self.printers.pack_start(small("No printers set up."), False, False, 0)
        for p in pr["printers"]:
            links = []
            if p["state"] == "disabled":
                links.append(link("Copy: resume", lambda n=p["name"]: self.copy("printer-resume", n)))
            if p["name"] != pr["default"]:
                links.append(link("Make default", lambda n=p["name"]: self.do("default-printer", n)))
            title = p["description"] if p.get("description") and p["description"] != p["name"] else p["name"]
            grid, _ = row(PRINTER, title, printer_sub(p, pr["default"]), links_row(*links) if links else None)
            self.printers.pack_start(grid, False, False, 0)
        if pr["jobs"]:
            self.jobs.pack_start(small(f"Waiting to print ({len(pr['jobs'])}):"), False, False, 0)
            me = self.data["user"]["login"] if self.data else None
            for j in pr["jobs"]:
                size = f"{j['size'] // 1024} KB" if j.get("size") else ""
                sub = "  ·  ".join(filter(None, [j["printer"], j["user"], size, j["when"]]))
                grid, _ = row(JOB, j["id"], sub, link("Cancel", lambda i=j["id"]: self.do("cancel-job", i))
                              if j["user"] == me else None)
                self.jobs.pack_start(grid, False, False, 0)
        else:
            self.jobs.pack_start(small("Nothing waiting to print."), False, False, 0)
