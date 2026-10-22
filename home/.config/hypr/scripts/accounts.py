#!/usr/bin/env python3
"""Users, sharing & printers: one command line for everything the Settings
page "Users, sharing & printers" shows and does, so the search bar, a key or
a terminal can do the same.

    accounts.py status                  JSON: you (login, real name, picture, account
                                        type), how the login screen starts (automatic
                                        login), online accounts, the firewall, the SSH
                                        server, Secure Boot / SELinux / disk encryption,
                                        problem reporting (ABRT), printers and print jobs
    accounts.py avatar FILE             make FILE your picture: a square 256 px PNG at
                                        ~/.face and, through AccountsService (allowed for
                                        your own account without root), the picture the
                                        login screen shows. The one it replaces is kept
    accounts.py avatar --undo           put back the picture you had before the changes
                                        made since the last undo
    accounts.py realname NAME           your full name, through AccountsService
    accounts.py password                open `passwd` in your terminal (it asks there)
    accounts.py online                  open the Online Accounts settings (GNOME's)
    accounts.py cups                    open the printing system's page, http://localhost:631
    accounts.py printers                open GNOME's printer settings (adding a printer)
    accounts.py default-printer NAME    your default printer (lpoptions, no root needed)
    accounts.py cancel-job ID           cancel one of your own print jobs
    accounts.py root WHAT [ARG]         print the root command for WHAT (below)
    accounts.py copy WHAT [ARG]         the same, copied to the clipboard

WHAT, for the things only root can change -- never run from here, printed or
copied so you can paste them into a terminal and type your password there:

    autologin-on | autologin-off        start the desktop at boot without the login screen
    firewall-on | firewall-off          the firewall service (firewalld)
    firewall-zone ZONE                  the default zone (how much the network is trusted)
    firewall-open SERVICE               let a service in (ssh, kdeconnect, samba...)
    firewall-close SERVICE              shut it out again
    ssh-on | ssh-off                    the SSH server (sshd): log in to this computer remotely
    abrt-autoreport-on | -off           send crash reports to Fedora without asking
    printer-resume PRINTER              take a paused printer back into use

Actions print one line saying what happened and exit 0, or print the reason on
stderr and exit 1 -- the Settings page shows that line under the row.

Nothing is kept here, except the picture a change replaced
($XDG_STATE_HOME/hypr/accounts/, for --undo). Everything else is read fresh
from where the system keeps it: /etc/passwd and AccountsService for you, the
login screen's own config (greetd / GDM / SDDM / LightDM), firewalld, systemd,
mokutil / the EFI variables, SELinux, lsblk, ABRT and CUPS.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HYPR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APPS = os.path.join(HYPR, "default-apps.py")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr", "accounts")
FACE = os.path.expanduser("~/.face")
ACCOUNTS = "org.freedesktop.Accounts"
CUPS_URL = "http://localhost:631"
SECURE_BOOT_VAR = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
# How the desktop starts when there is no login screen: what the login
# screen's own "Hyprland" entry runs (/usr/share/wayland-sessions).
SESSION_CMD = "/usr/bin/start-hyprland"
# The services the page offers to open, when firewalld knows them; any other
# works from the command line (accounts.py root firewall-open NAME).
COMMON_SERVICES = ["ssh", "kdeconnect", "samba", "mdns", "ipp", "http", "https", "syncthing",
                   "steam-streaming", "rdp", "vnc-server"]
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+-]{0,63}$")


def run(*cmd, timeout=10, env=None):
    """(exit code, stdout, stderr); 127 when the program is not there."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LANG="C", LC_ALL="C", **(env or {})))
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} is not installed"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def done(ok, message):
    print(message, file=sys.stdout if ok else sys.stderr)
    sys.exit(0 if ok else 1)


def read(path):
    try:
        with open(path, errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


# -- you ---------------------------------------------------------------------------------
def accounts_user(uid):
    """AccountsService's view of you ({} when it does not answer)."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        path = bus.call_sync(ACCOUNTS, "/org/freedesktop/Accounts", ACCOUNTS, "FindUserById",
                             GLib.Variant("(x)", (uid,)), None, 0, 3000).unpack()[0]
        props = bus.call_sync(ACCOUNTS, path, "org.freedesktop.DBus.Properties", "GetAll",
                              GLib.Variant("(s)", (ACCOUNTS + ".User",)), None, 0, 3000).unpack()[0]
        return dict(props, _path=path)
    except Exception:
        return {}


def call_user(method, signature, *args):
    """Call a method on your AccountsService user; "" or the error."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        path = accounts_user(os.getuid()).get("_path")
        if not path:
            return "AccountsService did not answer"
        bus.call_sync(ACCOUNTS, path, ACCOUNTS + ".User", method, GLib.Variant(signature, args),
                      None, Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 30000)
        return ""
    except Exception as exc:
        text = str(exc)
        return text.split(": ", 2)[-1] if text.startswith("g-dbus-error") or "GDBus" in text else text


def user_status():
    import grp
    import pwd
    me = pwd.getpwuid(os.getuid())
    groups = sorted({g.gr_name for g in grp.getgrall() if me.pw_name in g.gr_mem}
                    | {grp.getgrgid(me.pw_gid).gr_name})
    acc = accounts_user(me.pw_uid)
    icon = acc.get("IconFile") or ""
    picture = next((p for p in (icon, FACE) if p and os.access(p, os.R_OK)), "")
    return {"login": me.pw_name, "uid": me.pw_uid, "home": me.pw_dir, "shell": me.pw_shell,
            "real_name": acc.get("RealName") or me.pw_gecos.split(",")[0],
            "admin": acc.get("AccountType") == 1 if acc else "wheel" in groups,
            "groups": groups, "picture": picture, "accounts_icon": icon if os.path.exists(icon) else "",
            "face": os.path.exists(FACE), "accountsservice": bool(acc),
            "undo": os.path.exists(os.path.join(STATE, "changed")),
            "password_changed": password_changed(me.pw_name)}


def password_changed(login):
    """When the password was last changed (`passwd -S` works for yourself
    without root on Fedora: "you PS 2026-05-15 ..."), or None."""
    rc, out, _ = run("passwd", "-S", login, timeout=5)
    parts = out.split()
    return parts[2] if rc == 0 and len(parts) > 2 and re.match(r"\d{4}-\d\d-\d\d$", parts[2]) else None


def square_png(source, target, size=256):
    """Crop the middle square out of an image and scale it to size x size, as
    a PNG. Raises ValueError for something that is not an image."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
    try:
        pix = GdkPixbuf.Pixbuf.new_from_file(source)
    except GLib.Error as exc:
        raise ValueError(f"not a picture this computer can read ({exc.message})") from None
    pix = pix.apply_embedded_orientation() or pix
    side = min(pix.get_width(), pix.get_height())
    pix = pix.new_subpixbuf((pix.get_width() - side) // 2, (pix.get_height() - side) // 2, side, side)
    pix = pix.scale_simple(size, size, GdkPixbuf.InterpType.HYPER)
    pix.savev(target, "png", [], [])


def set_avatar(source):
    """~/.face and the AccountsService picture from SOURCE. What they were is
    copied to STATE first, so --undo can put it back: previous-icon /
    previous-face, missing when there was none, and a "changed" marker that
    says a change happened at all."""
    os.makedirs(STATE, exist_ok=True)
    new = os.path.join(STATE, "new-face.png")
    square_png(source, new)
    acc = accounts_user(os.getuid())
    icon = acc.get("IconFile") or ""
    marker = os.path.join(STATE, "changed")
    # Only the first change since the last undo keeps what was there: a
    # second change in a row must not replace your original picture with the
    # one you tried a minute ago (it would be gone for good).
    if not os.path.exists(marker):
        for src, name in ((icon, "previous-icon"), (FACE, "previous-face")):
            kept = os.path.join(STATE, name)
            if os.path.isfile(src):
                shutil.copyfile(src, kept)
            elif os.path.exists(kept):
                os.remove(kept)      # there was none: undo means "none" again
        open(marker, "w").close()
    put_face(new)
    if not acc:
        return "~/.face set; AccountsService did not answer, so the login screen keeps its old picture"
    err = call_user("SetIconFile", "(s)", FACE)
    if err:
        return f"~/.face set; the login screen's picture was not changed: {err}"
    return "picture set (~/.face and the login screen)"


def undo_avatar():
    icon_kept, face_kept, marker = (os.path.join(STATE, n) for n in ("previous-icon", "previous-face", "changed"))
    if not os.path.exists(marker):
        return False, "no earlier picture is kept"
    if os.path.exists(face_kept):
        put_face(face_kept)
    elif os.path.lexists(FACE):
        os.remove(FACE)              # there was no ~/.face before the change
    err = call_user("SetIconFile", "(s)", icon_kept if os.path.exists(icon_kept) else "")
    if err:
        return False, f"~/.face is back; the login screen's picture is not (try Undo again): {err}"
    for f in (icon_kept, face_kept, marker):
        if os.path.exists(f):
            os.remove(f)
    return True, "the earlier picture is back"


def put_face(source):
    """Copy SOURCE to ~/.face by renaming a finished copy over it: when
    ~/.face is a link to one of your photos, the link is replaced and the
    photo it pointed at is left alone (copying onto the link would have
    overwritten the photo)."""
    tmp = FACE + ".new"
    shutil.copyfile(source, tmp)
    os.replace(tmp, FACE)


def password_argv():
    """What "Change password" runs: passwd, in your terminal, held open after
    it finishes so you can read what it said."""
    return [DEFAULT_APPS, "run", "terminal", "--", "sh", "-c",
            "passwd; printf '\\nPress Enter to close.'; read _"]


# -- the login screen --------------------------------------------------------------------
def display_manager():
    """(name, kind, config file) of the login screen that starts at boot."""
    unit = os.path.basename(os.path.realpath("/etc/systemd/system/display-manager.service"))
    name = unit.removesuffix(".service") if unit.endswith(".service") else ""
    rc, out, _ = run("systemctl", "cat", "display-manager.service", timeout=5)
    exec_line = next((ln for ln in out.splitlines() if ln.startswith("ExecStart=")), "")
    if "greetd" in exec_line:
        m = re.search(r"--config\s+(\S+)", exec_line)
        return name or "greetd", "greetd", m.group(1) if m else "/etc/greetd/config.toml"
    for kind, conf in (("gdm", "/etc/gdm/custom.conf"), ("sddm", "/etc/sddm.conf"),
                       ("lightdm", "/etc/lightdm/lightdm.conf")):
        if kind in name or kind in exec_line:
            return name, kind, conf
    return name or None, None, None


def greetd_autologin(text):
    """The user greetd logs in at boot ([initial_session] user), or None."""
    section, user, command = None, None, None
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("["):
            section = line.strip("[] ")
        elif section == "initial_session" and "=" in line:
            key, value = (s.strip() for s in line.split("=", 1))
            value = value.strip("\"'")
            if key == "user":
                user = value
            elif key == "command":
                command = value
    return user if user and command else None


def ini_autologin(text, kind):
    """GDM / SDDM / LightDM: the automatic-login user, or None."""
    section, values = None, {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("["):
            section = line.strip("[] ")
        elif "=" in line:
            key, value = (s.strip() for s in line.split("=", 1))
            values[(section, key)] = value
    if kind == "gdm":
        on = values.get(("daemon", "AutomaticLoginEnable"), "").lower() in ("true", "1", "yes")
        return values.get(("daemon", "AutomaticLogin")) if on else None
    if kind == "sddm":
        return values.get(("Autologin", "User")) or None
    if kind == "lightdm":
        return values.get(("Seat:*", "autologin-user")) or None
    return None


def login_status(login):
    name, kind, conf = display_manager()
    text = read(conf) if conf else None
    user = None
    if text is not None:
        user = greetd_autologin(text) if kind == "greetd" else ini_autologin(text, kind)
    return {"dm": name, "kind": kind, "config": conf, "readable": text is not None,
            "autologin": user, "mine": user == login}


# -- online accounts ---------------------------------------------------------------------
def online_status():
    """The accounts gnome-online-accounts holds (provider and the name it
    shows), and whether its settings can be opened here."""
    rc, out, _ = run("gdbus", "call", "--session", "-d", "org.gnome.OnlineAccounts", "-o",
                     "/org/gnome/OnlineAccounts", "-m", "org.freedesktop.DBus.ObjectManager.GetManagedObjects",
                     timeout=5)
    accounts = []
    if rc == 0:
        for block in out.split("'org.gnome.OnlineAccounts.Account':")[1:]:
            prov = re.search(r"'ProviderName': <'([^']*)'>", block)
            ident = re.search(r"'PresentationIdentity': <'([^']*)'>", block)
            accounts.append({"provider": prov.group(1) if prov else "?", "identity": ident.group(1) if ident else ""})
    return {"daemon": rc == 0, "accounts": accounts, "panel": bool(shutil.which("gnome-control-center"))}


# -- sharing and security ----------------------------------------------------------------
def parse_list_all(text):
    """firewall-cmd --list-all -> {zone, services, ports, interfaces}."""
    out = {"zone": None, "services": [], "ports": [], "interfaces": []}
    lines = (text or "").splitlines()
    if lines:
        out["zone"] = lines[0].split(" (")[0].strip() or None
    for line in lines[1:]:
        key, _, value = line.strip().partition(":")
        if key in ("services", "ports", "interfaces"):
            out[key] = value.split()
    return out


def firewall_status():
    if not shutil.which("firewall-cmd"):
        return {"installed": False}
    with ThreadPoolExecutor(4) as pool:
        state = pool.submit(run, "firewall-cmd", "--state")
        listing = pool.submit(run, "firewall-cmd", "--list-all")
        zones = pool.submit(run, "firewall-cmd", "--get-zones")
        services = pool.submit(run, "firewall-cmd", "--get-services")
        enabled = pool.submit(run, "systemctl", "is-enabled", "firewalld")
    running = state.result()[0] == 0
    info = parse_list_all(listing.result()[1]) if running else {}
    known = set(services.result()[1].split())
    return {"installed": True, "running": running, "enabled": enabled.result()[1].strip() == "enabled",
            "zone": info.get("zone"), "services": info.get("services", []), "ports": info.get("ports", []),
            "interfaces": info.get("interfaces", []), "zones": zones.result()[1].split(),
            "offer": [s for s in COMMON_SERVICES if s in known]}


def unit_state(*units):
    """{unit: (active, enabled)} for each unit, one systemctl call each way."""
    rc, act, _ = run("systemctl", "is-active", *units, timeout=5)
    rc, en, _ = run("systemctl", "is-enabled", *units, timeout=5)
    act, en = act.split(), en.split()
    return {u: (act[i] if i < len(act) else "?", en[i] if i < len(en) else "?") for i, u in enumerate(units)}


def ssh_status():
    if not os.path.exists("/usr/sbin/sshd"):
        return {"installed": False}
    s = unit_state("sshd.service", "sshd.socket")
    return {"installed": True, "active": s["sshd.service"][0] == "active" or s["sshd.socket"][0] == "active",
            "enabled": s["sshd.service"][1] == "enabled" or s["sshd.socket"][1] == "enabled"}


def secure_boot():
    """True / False from the EFI variable (the last byte), None when the
    computer did not boot through UEFI or the variable is not readable."""
    try:
        with open(SECURE_BOOT_VAR, "rb") as handle:
            data = handle.read()
        return bool(data[-1]) if data else None
    except OSError:
        rc, out, _ = run("mokutil", "--sb-state", timeout=5)
        if "enabled" in out:
            return True
        return False if "disabled" in out else None


def encryption(tree):
    """[{mount, encrypted}] for the mounted filesystems that hold your data
    (/, /home and any other on a real disk), from `lsblk -J`: encrypted when
    a LUKS layer sits anywhere between it and the disk."""
    found = []

    def walk(dev, locked):
        locked = locked or dev.get("type") == "crypt" or dev.get("fstype") == "crypto_LUKS"
        for mount in dev.get("mountpoints") or []:
            if mount and mount.startswith("/") and not mount.startswith(("/boot", "/var/lib/snapd")):
                found.append({"mount": mount, "encrypted": locked})
        for child in dev.get("children") or []:
            walk(child, locked)

    for dev in (tree or {}).get("blockdevices", []):
        if dev.get("type") not in ("loop", "rom") and not str(dev.get("name", "")).startswith("zram"):
            walk(dev, False)
    seen, out = set(), []
    for f in sorted(found, key=lambda f: (f["mount"] != "/", f["mount"] != "/home", f["mount"])):
        if f["mount"] not in seen:
            seen.add(f["mount"])
            out.append(f)
    return out


def security_status():
    rc, mode, _ = run("getenforce", timeout=5)
    conf = read("/etc/selinux/config") or ""
    m = re.search(r"^SELINUX=(\w+)", conf, re.M)
    rc2, out, _ = run("lsblk", "-J", "-o", "NAME,TYPE,FSTYPE,MOUNTPOINTS", timeout=5)
    try:
        tree = json.loads(out) if rc2 == 0 else {}
    except ValueError:
        tree = {}
    return {"secure_boot": secure_boot(), "selinux": mode.strip() if rc == 0 else None,
            "selinux_config": m.group(1) if m else None, "disks": encryption(tree)}


def parse_problem_count(text):
    m = re.search(r"detected (\d+) problem", text or "")
    return int(m.group(1)) if m else 0


def abrt_status():
    if not shutil.which("abrt"):
        return {"installed": False}
    with ThreadPoolExecutor(3) as pool:
        count = pool.submit(run, "abrt", "status")
        auto = pool.submit(run, "abrt-auto-reporting")
        units = pool.submit(unit_state, "abrtd.service")
    return {"installed": True, "running": units.result()["abrtd.service"][0] == "active",
            "problems": parse_problem_count(count.result()[1]),
            "auto": auto.result()[1].strip().lower() == "enabled",
            "viewer": bool(shutil.which("gnome-abrt"))}


# -- printers ----------------------------------------------------------------------------
def parse_printers(text):
    """`lpstat -l -p` -> [{name, state, since, reason, description, location}]."""
    printers, cur = [], None
    for line in (text or "").splitlines():
        m = re.match(r"printer (\S+) (?:is )?(idle|disabled|now printing)", line)
        if m:
            since = re.match(r".* disabled since (.+?)\s*-?\s*$", line)
            cur = {"name": m.group(1), "state": "printing" if m.group(2) == "now printing" else m.group(2),
                   "since": since.group(1) if since else None, "reason": None,
                   "description": "", "location": ""}
            printers.append(cur)
            continue
        if cur is None or not line.startswith("\t"):
            continue
        body = line.strip()
        if body.startswith("Description:"):
            cur["description"] = body.split(":", 1)[1].strip()
        elif body.startswith("Location:"):
            cur["location"] = body.split(":", 1)[1].strip()
        elif cur["reason"] is None and ":" not in body and body:
            cur["reason"] = body
        elif cur["reason"] is None:
            cur["reason"] = ""          # past the reason line: none was given
    for p in printers:
        p["reason"] = p["reason"] or None
    return printers


def parse_jobs(text):
    """`lpstat -o` -> [{id, printer, user, size, when}]."""
    jobs = []
    for line in (text or "").splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and "-" in parts[0]:
            jobs.append({"id": parts[0], "printer": parts[0].rsplit("-", 1)[0], "user": parts[1],
                         "size": int(parts[2]) if parts[2].isdigit() else None,
                         "when": parts[3].strip() if len(parts) > 3 else ""})
    return jobs


def printer_status():
    if not shutil.which("lpstat"):
        return {"installed": False}
    with ThreadPoolExecutor(4) as pool:
        sched = pool.submit(run, "lpstat", "-r")
        plist = pool.submit(run, "lpstat", "-l", "-p")
        dflt = pool.submit(run, "lpstat", "-d")
        jobs = pool.submit(run, "lpstat", "-o")
        devices = pool.submit(run, "lpstat", "-v")
    running = "is running" in sched.result()[1]
    m = re.search(r"destination: (\S+)", dflt.result()[1])
    printers = parse_printers(plist.result()[1])
    uris = dict(re.findall(r"device for (\S+): (\S+)", devices.result()[1]))
    for p in printers:
        uri = uris.get(p["name"], "")
        p["connection"] = uri.split(":", 1)[0] if uri else None
    return {"installed": True, "running": running, "default": m.group(1) if m else None,
            "printers": printers, "jobs": parse_jobs(jobs.result()[1]),
            "panel": bool(shutil.which("gnome-control-center"))}


def status():
    with ThreadPoolExecutor(7) as pool:
        user = pool.submit(user_status)
        parts = {k: pool.submit(f) for k, f in (
            ("online", online_status), ("firewall", firewall_status), ("ssh", ssh_status),
            ("security", security_status), ("abrt", abrt_status), ("printing", printer_status))}
        me = user.result()
        result = {"user": me, "login": pool.submit(login_status, me["login"]).result()}
        result.update({k: f.result() for k, f in parts.items()})
    result["kdeconnect"] = {"installed": bool(shutil.which("kdeconnect-cli"))}
    return result


# -- root steps --------------------------------------------------------------------------
def root_command(what, arg=None, login=None, config=None, kind=None, session=SESSION_CMD):
    """The shell command (with sudo) that does WHAT. Raises ValueError for an
    unknown WHAT or a name that is not a plain name."""
    if arg is not None and not NAME_OK.match(arg):
        raise ValueError(f"not a name: {arg!r}")
    q = shlex.quote
    if what in ("firewall-zone", "firewall-open", "firewall-close", "printer-resume") and not arg:
        raise ValueError(f"{what} needs a name")
    if what == "autologin-on":
        if kind == "greetd":
            block = f"\\n[initial_session]\\ncommand = \"{session}\"\\nuser = \"{login}\"\\n"
            return (f"sudo cp -n {q(config)} {q(config)}.orig && "
                    f"sudo sed -i '/^\\[initial_session\\]/,/^\\[/{{/^\\[initial_session\\]/d;/^\\[/!d}}' {q(config)} && "
                    f"printf '{block}' | sudo tee -a {q(config)} >/dev/null")
        if kind == "gdm":
            return (f"sudo sed -i '/^AutomaticLogin/d; s/^\\[daemon\\]$/[daemon]\\nAutomaticLoginEnable=True\\n"
                    f"AutomaticLogin={login}/' {q(config)}")
        if kind == "sddm":
            return (f"printf '[Autologin]\\nUser={login}\\nSession=hyprland.desktop\\n' | "
                    "sudo tee /etc/sddm.conf.d/50-autologin.conf >/dev/null")
        if kind == "lightdm":
            return f"sudo sed -i 's/^#\\?autologin-user=.*/autologin-user={login}/' {q(config)}"
        raise ValueError("the login screen here is not one this knows how to set up")
    if what == "autologin-off":
        if kind == "greetd":
            return (f"sudo sed -i '/^\\[initial_session\\]/,/^\\[/{{/^\\[initial_session\\]/d;/^\\[/!d}}' {q(config)}")
        if kind == "gdm":
            return f"sudo sed -i 's/^AutomaticLoginEnable=.*/AutomaticLoginEnable=False/' {q(config)}"
        if kind == "sddm":
            return "sudo rm -f /etc/sddm.conf.d/50-autologin.conf"
        if kind == "lightdm":
            return f"sudo sed -i 's/^autologin-user=/#autologin-user=/' {q(config)}"
        raise ValueError("the login screen here is not one this knows how to set up")
    commands = {
        "firewall-on": "sudo systemctl enable --now firewalld",
        "firewall-off": "sudo systemctl disable --now firewalld",
        "firewall-zone": f"sudo firewall-cmd --set-default-zone={q(arg or '')}",
        "firewall-open": f"sudo firewall-cmd --permanent --add-service={q(arg or '')} && sudo firewall-cmd --reload",
        "firewall-close": f"sudo firewall-cmd --permanent --remove-service={q(arg or '')} && sudo firewall-cmd --reload",
        "ssh-on": "sudo systemctl enable --now sshd",
        "ssh-off": "sudo systemctl disable --now sshd sshd.socket",
        "abrt-autoreport-on": "sudo abrt-auto-reporting enabled",
        "abrt-autoreport-off": "sudo abrt-auto-reporting disabled",
        "printer-resume": f"sudo cupsenable {q(arg or '')} && sudo cupsaccept {q(arg or '')}",
    }
    if what not in commands:
        raise ValueError(f"no root step called {what!r} (see accounts.py --help)")
    return commands[what]


def root_for(what, arg=None):
    """root_command() with the login and the login screen filled in."""
    import pwd
    login = pwd.getpwuid(os.getuid()).pw_name
    _name, kind, config = display_manager() if what.startswith("autologin") else (None, None, None)
    return root_command(what, arg, login=login, config=config, kind=kind)


def gnome_panel(panel):
    """GNOME's settings app on one panel. It refuses to start outside GNOME,
    so it is told it is in one (only for itself)."""
    if not shutil.which("gnome-control-center"):
        return False, "GNOME Settings (gnome-control-center) is not installed"
    subprocess.Popen(["gnome-control-center", panel], env=dict(os.environ, XDG_CURRENT_DESKTOP="GNOME"),
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, f"opened GNOME Settings > {panel}"


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "status":
        print(json.dumps(status()))
    elif cmd == "avatar":
        if not rest:
            done(False, "avatar FILE | --undo")
        if rest[0] == "--undo":
            done(*undo_avatar())
        try:
            msg = set_avatar(os.path.expanduser(rest[0]))
        except (ValueError, OSError) as exc:
            done(False, str(exc))
        done("not changed" not in msg, msg)
    elif cmd == "realname":
        name = " ".join(rest).strip()
        if not name or len(name) > 128 or any(c in name for c in ":,\n"):
            done(False, "a name, without : , or line breaks")
        err = call_user("SetRealName", "(s)", name)
        done(not err, f"your name is now {name}" if not err else err)
    elif cmd == "password":
        subprocess.Popen(password_argv(), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        done(True, "passwd is open in the terminal")
    elif cmd == "online":
        done(*gnome_panel("online-accounts"))
    elif cmd == "printers":
        done(*gnome_panel("printers"))
    elif cmd == "cups":
        subprocess.Popen(["xdg-open", CUPS_URL], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        done(True, f"opened {CUPS_URL}")
    elif cmd == "default-printer":
        if not rest or not NAME_OK.match(rest[0]):
            done(False, "default-printer NAME")
        rc, _, err = run("lpoptions", "-d", rest[0])
        done(rc == 0, f"{rest[0]} is your default printer" if rc == 0 else err.strip() or "lpoptions failed")
    elif cmd == "cancel-job":
        if not rest or not NAME_OK.match(rest[0]):
            done(False, "cancel-job ID")
        rc, _, err = run("cancel", rest[0])
        done(rc == 0, f"cancelled {rest[0]}" if rc == 0 else err.strip() or "cancel failed")
    elif cmd in ("root", "copy"):
        if not rest:
            done(False, f"{cmd} WHAT [ARG]")
        try:
            text = root_for(rest[0], rest[1] if len(rest) > 1 else None)
        except ValueError as exc:
            done(False, str(exc))
        if cmd == "root":
            print(text)
            return
        try:
            # wl-copy stays behind to serve the clipboard; with this script's
            # stdout/stderr it would keep the Settings page's pipe open and the
            # click would hang until its timeout, so it gets none.
            subprocess.run(["wl-copy", "--", text], timeout=5, check=True, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            done(False, f"could not copy (wl-copy); the command: {text}")
        done(True, f"copied: {text}")
    else:
        done(False, f"unknown command {cmd!r} (accounts.py --help)")


if __name__ == "__main__":
    main(sys.argv[1:])
