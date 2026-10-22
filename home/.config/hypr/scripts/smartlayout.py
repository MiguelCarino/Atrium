#!/usr/bin/env python3
"""Smart window layout: learn where you put each app, and put it there when
it opens (smartlayout.service, Settings > Window layout).

    smartlayout.py run                  the service: follow Hyprland's event socket
    smartlayout.py status [--json]      the settings, what was learned, the pairings
    smartlayout.py set mode off|learn|on   off: nothing; learn: watch only (as shipped);
                                        on: watch, and place apps when they open
    smartlayout.py set evidence N       how many times (2..20) before a placement is used
    smartlayout.py set follow on|off    a placed window takes you to its workspace
    smartlayout.py lock CLASS [KEY]     always use KEY (default: the best one) for CLASS
    smartlayout.py unlock CLASS
    smartlayout.py forget CLASS|all     drop what was learned (all: the pairings too)
    smartlayout.py forget-pair A B
    smartlayout.py arrange              the focused workspace "as usual": the app you
                                        usually pair with one here is brought over, and
                                        the two go on their usual sides

What counts as a placement (describe()): the workspace, tiled or floating,
and the side -- for a tiled window left / right / top / bottom / full of
its screen's usable area, for a floating one the third of the screen its
middle is in (top-left ... bottom-right, center) plus its size and position
as fractions of the screen. The KEY is "workspace|tile|side" or
"workspace|float|side" ("3|tile|left"). The screen is noted for the page
but is not part of the key: the workspace rules in lua/ decide which
screen a workspace lives on.

How it learns (Tracker): every window is refreshed from `clients` on each
event that can move it and every POLL_S (floating moves and resizes send no
event). A placement counts once it has stayed MIN_STAY_S unchanged, and each
window has ONE vote: when it settles somewhere else, its vote moves there.
So an app you always drag to workspace 5 gets its votes on 5, not on the
workspace it opened on. Pairings: two settled tiled windows of different
apps that are alone on a workspace, side by side, count once per pair of
windows. Which window voted for what is kept in $XDG_RUNTIME_DIR/
smartlayout-votes.json (for this Hyprland instance only), so restarting the
service -- or the event socket dropping -- does not give the windows that
are already open a second vote.

How it places (mode "on"): when an app's FIRST window opens (a second
terminal opens where you are), the placement with at least `evidence`
votes and a confidence (its votes over all of the app's votes plus the times
you undid it) of MIN_CONF or more -- or the locked one -- is applied with one
`hyprctl eval` (Lua dispatches, as sessions.py's place_lua(): this config
takes no classic dispatches). Floating windows get their size and position;
tiled ones their workspace, then their side (a swap) once they have mapped.
Never while a session or a closed window is being restored (sessions.py and
closed-windows.py place those themselves).

Never fighting you: moving a window this placed within FIGHT_S of the
placement is a vote AGAINST that placement (`against`), which lowers its
confidence; the window is then left alone. What this script itself
dispatches in the OWN_S after each placement is not counted either way.

Left out, never learned or placed: dialogs and pickers, scratchpads, the
bar's panels, Steam and games (sessions.py's TRANSIENT_* / GAME_RE), small
floating popups, fullscreen windows, and private windows -- KeePassXC,
private / incognito browser windows and the apps made private in Settings >
Privacy (privacy.conf activity_exclude). Only window classes and places are
kept, never titles.

Where things are: $XDG_STATE_HOME/hypr/smartlayout.json -- {"settings",
"apps": {class: {"placements": {KEY: {count, against, monitor, size, rel,
last}}, "locked": KEY|null}}, "pairs": {"a\\tb": {count, sides, last}}} --
read-modify-written under a lock by the service and the commands alike.
Logs: journalctl --user -t smartlayout.
"""
import fcntl
import json
import os
import re
import select
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desklog  # noqa: E402
import privacy_settings  # noqa: E402  (the private apps)
import sessions  # noqa: E402  (hypr_json, hypr_eval, lua_str, TRANSIENT_*, GAME_RE)

HOME = os.path.expanduser("~")
STORE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                     "hypr", "smartlayout.json")
DEFAULTS = {"mode": "learn", "evidence": 3, "follow": "on"}
MODES = ("off", "learn", "on")
EVIDENCE_RANGE = (2, 20)
MIN_STAY_S = 30         # a placement counts once it has stayed this long
FIGHT_S = 60            # moved this soon after being placed: a vote against
OWN_S = 2.5             # what we dispatch ourselves in this time is not the user
POLL_S = 5
SIDE_FIX_S = 0.5        # a placed tiled window gets its side this long after
MIN_CONF = 0.6
MAX_PLACES = 8          # placements kept per app (the least used go)
MAX_APPS = 200
POPUP = (220, 120)
DEFAULT_FLOAT = ([0.5, 0.6], [0.25, 0.2])     # a locked floating place never seen: size, position
PRIVATE_CLASS = re.compile(r"keepassxc", re.I)                       # activity-log.py's
PRIVATE_TITLE = re.compile(r"private browsing|incognito|inprivate", re.I)
SIDE_WORDS = {"left": "left side", "right": "right side", "top": "top half", "bottom": "bottom half",
              "full": "the whole screen", "center": "middle"}
DIRECTION = {"left": "l", "right": "r", "top": "u", "bottom": "d"}
OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
VOTES = os.path.join(RUNTIME, "smartlayout-votes.json")
REFRESH_ON = {"openwindow", "closewindow", "movewindowv2", "changefloatingmode", "fullscreen",
              "moveworkspacev2", "activewindowv2"}
KEY_RE = re.compile(r"^[^|\s]{1,40}\|(tile|float)\|[a-z-]{3,14}$")


def log(text, level="info"):
    desklog.log("smartlayout", text, level)


# -- the store -------------------------------------------------------------------------
def empty():
    return {"settings": dict(DEFAULTS), "apps": {}, "pairs": {}}


def read_store(path=None):
    try:
        with open(path or STORE) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return empty()
    if not isinstance(data, dict):
        return empty()
    out = empty()
    out["settings"].update({k: v for k, v in (data.get("settings") or {}).items() if k in DEFAULTS})
    out["apps"] = data.get("apps") if isinstance(data.get("apps"), dict) else {}
    out["pairs"] = data.get("pairs") if isinstance(data.get("pairs"), dict) else {}
    return out


def write_store(data, path=None):
    path = path or STORE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".smartlayout-")
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)


class Store:
    """The file, locked for each read-modify-write (the service and the
    commands both write it)."""

    def __init__(self, path=None):
        self.path = path or STORE

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.lock = open(self.path + ".lock", "w")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.data = read_store(self.path)
        return self.data

    def __exit__(self, exc, *_):
        try:
            if exc is None:
                write_store(self.data, self.path)
        finally:
            self.lock.close()


def settings_of(data):
    s = dict(DEFAULTS)
    s.update(data.get("settings") or {})
    if s["mode"] not in MODES:
        s["mode"] = DEFAULTS["mode"]
    try:
        s["evidence"] = max(EVIDENCE_RANGE[0], min(EVIDENCE_RANGE[1], int(s["evidence"])))
    except (TypeError, ValueError):
        s["evidence"] = DEFAULTS["evidence"]
    return s


# -- what a placement is ------------------------------------------------------------------
def usable(mon):
    """(x, y, w, h) of a monitor's logical area minus the bar's reserved edges."""
    scale = mon.get("scale") or 1
    w, h = mon["width"] / scale, mon["height"] / scale
    if (mon.get("transform") or 0) % 2:
        w, h = h, w
    left, top, right, bottom = (list(mon.get("reserved") or []) + [0, 0, 0, 0])[:4]
    return mon["x"] + left, mon["y"] + top, max(1.0, w - left - right), max(1.0, h - top - bottom)


def monitor_of(client, monitors):
    mid = client.get("monitor")
    return next((m for m in monitors if m.get("id") == mid), None)


def side_of(client, mon):
    """Where a window sits on its screen (the docstring's sides)."""
    ax, ay, aw, ah = usable(mon)
    (x, y), (w, h) = client.get("at") or (0, 0), client.get("size") or (0, 0)
    cx, cy = (x + w / 2 - ax) / aw, (y + h / 2 - ay) / ah
    fw, fh = w / aw, h / ah
    if client.get("floating"):
        col = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "center"
        rowv = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else "middle"
        return "center" if (col, rowv) == ("center", "middle") else f"{rowv}-{col}"
    if fw >= 0.8 and fh >= 0.8:
        return "full"
    if fw >= 0.8:
        return "top" if cy < 0.5 else "bottom"
    return "left" if cx < 0.5 else "right"


def private(client, exclude=()):
    cls, title = client.get("class") or "", client.get("title") or ""
    return bool(PRIVATE_CLASS.search(cls) or PRIVATE_TITLE.search(title) or cls.lower() in exclude)


def learnable(client, exclude=()):
    """Why a window is left out (the docstring's list), or None when it counts."""
    cls, title = client.get("class") or "", client.get("title") or ""
    ws = (client.get("workspace") or {}).get("name") or ""
    if not cls or not client.get("mapped", True) or client.get("hidden"):
        return "not a window yet"
    if sessions.TRANSIENT_CLASS.match(cls) or sessions.TRANSIENT_TITLE.match(title):
        return "a dialog or picker"
    if ws.startswith("special") or not ws:
        return "a scratchpad"
    if sessions.GAME_RE.match(cls):
        return "Steam / a game"
    if private(client, exclude):
        return "private"
    if client.get("fullscreen"):
        return "fullscreen"
    w, h = client.get("size") or (0, 0)
    if client.get("floating") and (w < POPUP[0] or h < POPUP[1]):
        return "a popup"
    return None


def describe(client, monitors):
    """The placement of a window ({key, workspace, floating, side, monitor,
    size, rel}), or None when it has no screen."""
    mon = monitor_of(client, monitors)
    if mon is None:
        return None
    ws = (client.get("workspace") or {}).get("name") or ""
    if "|" in ws:
        return None
    floating = bool(client.get("floating"))
    side = side_of(client, mon)
    ax, ay, aw, ah = usable(mon)
    (x, y), (w, h) = client.get("at") or (0, 0), client.get("size") or (0, 0)
    return {"key": f"{ws}|{'float' if floating else 'tile'}|{side}", "workspace": ws, "floating": floating,
            "side": side, "monitor": mon.get("name") or "",
            "size": [round(w / aw, 3), round(h / ah, 3)], "rel": [round((x - ax) / aw, 3), round((y - ay) / ah, 3)]}


def split_key(key):
    ws, kind, side = (key.rsplit("|", 2) + ["", ""])[:3] if key.count("|") >= 2 else (key, "tile", "")
    return ws, kind == "float", side


def undone(placed, before, after):
    """Is a window going from `before` to `after` the user undoing a
    placement on `placed`? Only once it had got there: the workspace and
    tiled / floating as placed (the side may still be on its way), and then
    either of those changes, or the side changes away from the placed one."""
    pw, pf, ps = split_key(placed)
    bw, bf, bs = split_key(before)
    aw, af, as_ = split_key(after)
    if (bw, bf) != (pw, pf):
        return False
    return (aw, af) != (pw, pf) or (bs == ps and as_ != ps)


def place_words(key, place=None):
    """"workspace 3 · left side", "workspace 5 · floating, top-right, 40 × 50 %"."""
    ws, floating, side = split_key(key)
    where = f"workspace {ws}" if re.fullmatch(r"-?\d+", ws) else f"workspace “{ws}”"
    mon = (place or {}).get("monitor")
    where += f" ({mon})" if mon else ""
    if not floating:
        return f"{where} · {SIDE_WORDS.get(side, side)}"
    size = (place or {}).get("size")
    dims = f", {round(size[0] * 100)} × {round(size[1] * 100)} %" if size else ""
    return f"{where} · floating, {side}{dims}"


# -- votes (pure, on the store's dict) ------------------------------------------------------
def app_entry(data, cls):
    return data["apps"].setdefault(cls, {"placements": {}, "locked": None})


def _mean(old, new, n):
    if not old or len(old) != len(new):
        return list(new)
    return [round(o + (v - o) / n, 3) for o, v in zip(old, new)]


def vote(data, cls, desc, old_key=None, now=None):
    """The window's one vote moves from old_key (if any) to desc's placement."""
    now = now if now is not None else time.time()
    app = app_entry(data, cls)
    places = app["placements"]
    if old_key and old_key in places:
        places[old_key]["count"] = max(0, places[old_key].get("count", 0) - 1)
    p = places.setdefault(desc["key"], {"count": 0, "against": 0})
    p["count"] = p.get("count", 0) + 1
    p["monitor"] = desc.get("monitor") or p.get("monitor", "")
    if desc.get("floating"):
        p["size"] = _mean(p.get("size"), desc["size"], p["count"])
        p["rel"] = _mean(p.get("rel"), desc["rel"], p["count"])
    p["last"] = int(now)
    app["last"] = int(now)
    prune(data, cls)


def vote_against(data, cls, key, now=None):
    app = data["apps"].get(cls)
    if not app or key not in app["placements"]:
        return
    p = app["placements"][key]
    p["against"] = p.get("against", 0) + 1
    p["last_against"] = int(now if now is not None else time.time())


def prune(data, cls):
    """At most MAX_PLACES per app (the least voted go, never the locked one),
    nothing left at zero, at most MAX_APPS apps (the least recent go)."""
    app = data["apps"].get(cls)
    if app:
        places = app["placements"]
        for key in [k for k, p in places.items() if p.get("count", 0) <= 0 and p.get("against", 0) <= 0
                    and k != app.get("locked")]:
            del places[key]
        ranked = sorted(places, key=lambda k: (k == app.get("locked"), places[k].get("count", 0),
                                               places[k].get("last", 0)), reverse=True)
        for key in ranked[MAX_PLACES:]:
            del places[key]
    if len(data["apps"]) > MAX_APPS:
        for old in sorted(data["apps"], key=lambda c: data["apps"][c].get("last", 0))[:len(data["apps"]) - MAX_APPS]:
            del data["apps"][old]


def confidence(app, key):
    places = app.get("placements") or {}
    total = sum(p.get("count", 0) for p in places.values())
    p = places.get(key) or {}
    denom = total + p.get("against", 0)
    return p.get("count", 0) / denom if denom else 0.0


def ranked(app):
    """The app's placements, best first: [(key, place, confidence)]."""
    places = app.get("placements") or {}
    return sorted(((k, p, confidence(app, k)) for k, p in places.items()),
                  key=lambda t: (t[2], t[1].get("count", 0)), reverse=True)


def decision(app, evidence):
    """(key, place, why) to apply when the app opens, or None."""
    if not app:
        return None
    locked = app.get("locked")
    if locked:
        return locked, (app.get("placements") or {}).get(locked, {}), "locked"
    for key, p, conf in ranked(app)[:1]:
        if p.get("count", 0) >= evidence and conf >= MIN_CONF:
            return key, p, f"{p['count']} times, {round(conf * 100)} %"
    return None


def pair_key(a, b):
    return "\t".join(sorted((a, b)))


def vote_pair(data, a, side_a, b, side_b, now=None):
    pair = data["pairs"].setdefault(pair_key(a, b), {"count": 0, "sides": {}})
    pair["count"] += 1
    pair["sides"] = {a: side_a, b: side_b}
    pair["last"] = int(now if now is not None else time.time())
    if len(data["pairs"]) > MAX_APPS:
        for old in sorted(data["pairs"], key=lambda k: data["pairs"][k].get("last", 0))[:len(data["pairs"]) - MAX_APPS]:
            del data["pairs"][old]


# -- the Lua that places a window -------------------------------------------------------
def place_lua(address, key, place, monitors, current=None, follow=False):
    """One `hyprctl eval` that puts a window on KEY's workspace, floating or
    tiled, and for floating its size and position on the workspace's screen."""
    current = current or {}
    ws, floating, _side = split_key(key)
    t = sessions.lua_str("address:" + address)
    lua = [f"local w = hl.get_window({t})", "if not w then return end"]
    if ws != (current.get("workspace") or {}).get("name"):
        sel = ws if re.fullmatch(r"-?\d+", ws) else "name:" + ws
        lua.append(f"hl.dispatch(hl.dsp.window.move({{ workspace = {sessions.lua_str(sel)}, "
                   f"follow = {'true' if follow else 'false'}, window = {t} }}))")
    if floating:
        if not current.get("floating"):
            lua.append(f'hl.dispatch(hl.dsp.window.float({{ action = "enable", window = {t} }}))')
        mon = next((m for m in monitors if m.get("name") == place.get("monitor")), None) \
            or monitor_of(current, monitors)
        size, rel = place.get("size") or DEFAULT_FLOAT[0], place.get("rel") or DEFAULT_FLOAT[1]
        if mon and size and rel:
            ax, ay, aw, ah = usable(mon)
            w, h = max(POPUP[0], int(size[0] * aw)), max(POPUP[1], int(size[1] * ah))
            w, h = min(w, int(aw)), min(h, int(ah))
            x = ax + max(0, min(int(rel[0] * aw), int(aw) - w))
            y = ay + max(0, min(int(rel[1] * ah), int(ah) - h))
            lua.append(f"hl.dispatch(hl.dsp.window.resize({{ x = {w}, y = {h}, window = {t} }}))")
            lua.append(f"hl.dispatch(hl.dsp.window.move({{ x = {int(x)}, y = {int(y)}, window = {t} }}))")
    elif current.get("floating"):
        lua.append(f'hl.dispatch(hl.dsp.window.float({{ action = "disable", window = {t} }}))')
    return "\n".join(lua)


def swap_lua(address, side, refocus=None):
    """Swap a tiled window toward `side` (focus it, swap, focus back)."""
    t = sessions.lua_str("address:" + address)
    lua = [f"hl.dispatch(hl.dsp.focus({{ window = {t} }}))",
           f'hl.dispatch(hl.dsp.window.swap({{ direction = "{DIRECTION[side]}" }}))']
    if refocus and refocus != address:
        lua.append(f"hl.dispatch(hl.dsp.focus({{ window = {sessions.lua_str('address:' + refocus)} }}))")
    return "\n".join(lua)


def restoring():
    """True while sessions.py restores or closed-windows.py reopens (they
    place their own windows)."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        argv = sessions.cmdline(pid)
        text = " ".join(argv[:4])
        if ("sessions.py" in text and ("restore" in argv or "where-was-i" in argv)) or \
                ("closed-windows.py" in text and "reopen" in argv):
            return True
    return False


def panel(client):
    argv = sessions.cmdline(client.get("pid") or 0)
    return any("/.config/waybar/scripts/" in a for a in argv[:3])


# -- the service ------------------------------------------------------------------------
class Tracker:
    """The open windows, what each is voting for, what this placed."""

    def __init__(self, clock=time.monotonic, wall=time.time, store=None, dispatch=None, exclude=None):
        self.clock, self.wall = clock, wall
        self.store = store or Store
        self.dispatch = dispatch or sessions.hypr_eval
        self.exclude = exclude or (lambda: privacy_settings.excluded(privacy_settings.load()))
        self.windows = {}       # address -> {cls, desc, since, voted, placed, placed_at, own_until}
        self.counted_pairs = set()
        self.later = []         # (when, address, side): a placed window's side fix
        self.settings = dict(DEFAULTS)
        self.settings_mtime = None
        self.skipped = {}       # address -> reason (panels are checked once)
        self.last_refresh = -1e9
        self.dirty = False
        self.prior = {}         # address -> [cls, key]: votes cast before a restart / reconnect
        self.votes_file = None  # (path, instance) where serve() keeps them

    def keep_votes(self):
        """The windows' votes into votes_file (serve() only)."""
        if not self.votes_file:
            return
        path, instance = self.votes_file
        votes = {a: [w["cls"], w["voted"]] for a, w in self.windows.items() if w["voted"]}
        try:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".smartlayout-votes-")
            with os.fdopen(fd, "w") as handle:
                json.dump({"instance": instance, "votes": votes}, handle)
            os.replace(tmp, path)
        except OSError:
            pass

    def load_settings(self):
        try:
            mtime = os.stat(STORE).st_mtime_ns
        except OSError:
            mtime = None
        if mtime != self.settings_mtime:
            self.settings_mtime = mtime
            self.settings = settings_of(read_store())
        return self.settings

    def refresh(self, clients=None, monitors=None):
        now = self.clock()
        self.last_refresh, self.dirty = now, False
        clients = clients if clients is not None else sessions.hypr_json("clients")
        monitors = monitors if monitors is not None else sessions.hypr_json("monitors")
        if clients is None or monitors is None:
            return
        if self.load_settings()["mode"] == "off":
            self.windows.clear()
            return
        exclude = self.exclude()
        seen, votes, fights = set(), [], []
        for c in clients:
            addr = c.get("address")
            why = learnable(c, exclude)
            if why is None and addr not in self.windows and addr not in self.skipped and panel(c):
                self.skipped[addr] = "a bar panel"
            if why or addr in self.skipped:
                continue
            desc = describe(c, monitors)
            if desc is None:
                continue
            seen.add(addr)
            w = self.windows.get(addr)
            if w is None:
                cls, voted = self.prior.pop(addr, (None, None))
                self.windows[addr] = {"cls": c["class"], "desc": desc, "since": now,
                                      "voted": voted if cls == c["class"] else None,
                                      "placed": None, "placed_at": None, "own_until": 0}
                continue
            if desc["key"] != w["desc"]["key"]:
                if w["placed"] and now >= w["own_until"] and now - w["placed_at"] <= FIGHT_S \
                        and undone(w["placed"], w["desc"]["key"], desc["key"]):
                    fights.append((w["cls"], w["placed"]))
                    w["placed"] = None          # undone once: left alone after that
                w["desc"], w["since"] = desc, now
            else:
                w["desc"] = desc                # same place, maybe a new size
            if now - w["since"] >= MIN_STAY_S and w["voted"] != desc["key"] and now >= w["own_until"]:
                votes.append((w["cls"], desc, w["voted"]))
                w["voted"] = desc["key"]
        for addr in set(self.windows) - seen:
            del self.windows[addr]
        self.skipped = {a: r for a, r in self.skipped.items() if any(c.get("address") == a for c in clients)}
        pairs = self.pairs_now(now)
        if votes or fights or pairs:
            with self.store() as data:
                for cls, desc, old in votes:
                    vote(data, cls, desc, old, self.wall())
                for cls, key in fights:
                    vote_against(data, cls, key, self.wall())
                    log(f"{cls}: moved right after being placed on {key}: counted against it")
                for a, sa, b, sb in pairs:
                    vote_pair(data, a, sa, b, sb, self.wall())
            self.settings_mtime = None
        if votes:
            self.keep_votes()

    def pairs_now(self, now):
        """New side-by-side pairs: two settled tiled windows of two apps,
        alone on a workspace."""
        by_ws = {}
        for addr, w in self.windows.items():
            if not w["desc"]["floating"]:
                by_ws.setdefault(w["desc"]["workspace"], []).append((addr, w))
        found = []
        for wins in by_ws.values():
            if len(wins) != 2:
                continue
            (a1, w1), (a2, w2) = wins
            s1, s2 = w1["desc"]["side"], w2["desc"]["side"]
            if w1["cls"] == w2["cls"] or OPPOSITE.get(s1) != s2:
                continue
            if min(now - w1["since"], now - w2["since"]) < MIN_STAY_S:
                continue
            ident = frozenset((a1, a2))
            if ident in self.counted_pairs:
                continue
            self.counted_pairs.add(ident)
            found.append((w1["cls"], s1, w2["cls"], s2))
        live = set(self.windows)
        self.counted_pairs = {p for p in self.counted_pairs if p <= live}
        return found

    def opened(self, address, cls, clients=None, monitors=None, busy=restoring):
        """An openwindow event: place the app's first window where it goes."""
        self.refresh(clients, monitors)
        if self.settings["mode"] != "on" or address not in self.windows:
            return None
        if any(w["cls"] == cls for a, w in self.windows.items() if a != address):
            return None             # not the app's first window
        data = read_store()
        found = decision(data["apps"].get(cls), self.settings["evidence"])
        if not found:
            return None
        key, place, why = found
        w = self.windows[address]
        if w["desc"]["key"] == key and not split_key(key)[1]:
            return None             # already there
        if busy():
            return None
        clients = clients if clients is not None else sessions.hypr_json("clients") or []
        monitors = monitors if monitors is not None else sessions.hypr_json("monitors") or []
        current = next((c for c in clients if c.get("address") == address), {})
        follow = self.settings["follow"] == "on" and current.get("focusHistoryID") == 0
        self.dispatch(place_lua(address, key, place, monitors, current, follow))
        now = self.clock()
        w.update(placed=key, placed_at=now, own_until=now + OWN_S)
        side = split_key(key)[2]
        if not split_key(key)[1] and side in DIRECTION and follow:
            self.later.append((now + SIDE_FIX_S, address, side))
        log(f"{cls}: placed on {key} ({why})")
        return key

    def tick(self, clients=None, monitors=None):
        """Due side fixes, and the periodic refresh."""
        now = self.clock()
        due = [x for x in self.later if x[0] <= now]
        self.later = [x for x in self.later if x[0] > now]
        if due:
            clients = clients if clients is not None else sessions.hypr_json("clients") or []
            monitors = monitors if monitors is not None else sessions.hypr_json("monitors") or []
            for _when, addr, side in due:
                c = next((c for c in clients if c.get("address") == addr), None)
                mon = c and monitor_of(c, monitors)
                if c and mon and not c.get("floating") and side_of(c, mon) == OPPOSITE[side]:
                    self.dispatch(swap_lua(addr, side))
                    if addr in self.windows:
                        self.windows[addr]["own_until"] = self.clock() + OWN_S
        if now - self.last_refresh >= POLL_S:
            self.refresh(clients, monitors)

    def wait(self):
        now = self.clock()
        nxt = min([t for t, _a, _s in self.later] + [self.last_refresh + POLL_S])
        return max(0.05, nxt - now)


def handle(tracker, line):
    name, _, rest = line.partition(">>")
    if name == "openwindow":
        parts = rest.split(",", 3)
        if len(parts) >= 3:
            tracker.opened("0x" + parts[0].removeprefix("0x"), parts[2])
            return
    if name in REFRESH_ON:
        tracker.dirty = True


def load_votes(path, instance):
    """{address: [cls, key]} from an earlier run on this Hyprland instance."""
    try:
        with open(path) as handle:
            data = json.load(handle)
        if data.get("instance") == instance and isinstance(data.get("votes"), dict):
            return {a: v for a, v in data["votes"].items() if isinstance(v, list) and len(v) == 2}
    except (OSError, ValueError, AttributeError):
        pass
    return {}


def serve():
    tracker = Tracker()
    log("watching window placements")
    while True:
        path = sessions.hypr_dir()
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(os.path.join(path, ".socket2.sock") if path else "")
        except OSError:
            sock.close()
            time.sleep(2)
            continue
        instance = os.path.basename(path)
        same = tracker.votes_file and tracker.votes_file[1] == instance     # a dropped socket, not a new Hyprland
        tracker.prior = {a: [w["cls"], w["voted"]] for a, w in tracker.windows.items() if w["voted"]} \
            if same else load_votes(VOTES, instance)
        tracker.votes_file = (VOTES, instance)
        tracker.windows.clear()
        tracker.refresh()
        tracker.prior = {}
        tracker.keep_votes()            # only the windows still open
        buf = b""
        with sock:
            while True:
                wait = tracker.wait()
                if tracker.dirty:
                    wait = min(wait, max(0.05, 0.5 - (tracker.clock() - tracker.last_refresh)))
                ready, _, _ = select.select([sock], [], [], wait)
                if ready:
                    try:
                        chunk = sock.recv(65536)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break           # Hyprland restarted: reconnect
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        handle(tracker, line.decode("utf-8", "replace"))
                if tracker.dirty and tracker.clock() - tracker.last_refresh >= 0.5:
                    tracker.refresh()
                tracker.tick()


# -- arrange as usual ------------------------------------------------------------------------
def arrange_plan(clients, monitors, data, evidence, exclude=()):
    """What `arrange` does on the focused workspace: [(lua, words)] for the
    first round (bring the partner over), and the pair's sides for the
    second -- or ([], None, why)."""
    focused = next((c for c in clients if c.get("focusHistoryID") == 0), None)
    mon = next((m for m in monitors if m.get("focused")), None)
    ws = ((mon or {}).get("activeWorkspace") or {}).get("name") or \
        ((focused or {}).get("workspace") or {}).get("name")
    if not ws:
        return [], None, "no focused workspace"
    good = [c for c in clients if learnable(c, exclude) is None]
    here = [c for c in good if (c.get("workspace") or {}).get("name") == ws and not c.get("floating")]
    classes = {c["class"] for c in here}
    pairs = sorted(((k, p) for k, p in (data.get("pairs") or {}).items() if p.get("count", 0) >= evidence),
                   key=lambda kp: kp[1]["count"], reverse=True)
    for key, pair in pairs:
        a, b = key.split("\t")
        if not ({a, b} & classes) or a == b:
            continue
        steps = []
        for cls in (a, b):
            if cls in classes:
                continue
            other = next((c for c in sorted(good, key=lambda c: c.get("focusHistoryID", 99))
                          if c["class"] == cls), None)
            if other is None:
                break
            sel = ws if re.fullmatch(r"-?\d+", ws) else "name:" + ws
            t = sessions.lua_str("address:" + other["address"])
            lua = []
            if other.get("floating"):
                lua.append(f'hl.dispatch(hl.dsp.window.float({{ action = "disable", window = {t} }}))')
            lua.append(f"hl.dispatch(hl.dsp.window.move({{ workspace = {sessions.lua_str(sel)}, "
                       f"follow = false, window = {t} }}))")
            steps.append(("\n".join(lua), f"brought {cls} over"))
        else:
            return steps, (a, b, pair.get("sides") or {}), None
    if not here:
        return [], None, "no tiled windows on this workspace"
    return [], None, "nothing learned yet about these apps side by side"


def sides_fix(clients, monitors, ws, pair, focused=None):
    """The swap that puts a pair on its usual sides, or None when it is."""
    a, b, sides = pair
    wins = [c for c in clients if (c.get("workspace") or {}).get("name") == ws and not c.get("floating")]
    ca = next((c for c in sorted(wins, key=lambda c: c.get("focusHistoryID", 99)) if c["class"] == a), None)
    want = sides.get(a)
    if ca is None or want not in DIRECTION:
        return None
    mon = monitor_of(ca, monitors)
    if mon is None or side_of(ca, mon) == want:
        return None
    return swap_lua(ca["address"], want, focused)


def arrange(notify=True, sleep=time.sleep):
    data = read_store()
    s = settings_of(data)
    clients, monitors = sessions.hypr_json("clients") or [], sessions.hypr_json("monitors") or []
    exclude = privacy_settings.excluded(privacy_settings.load())
    steps, pair, why = arrange_plan(clients, monitors, data, s["evidence"], exclude)
    if pair is None:
        if notify:
            note("Nothing to arrange", why)
        return 1
    focused = next((c.get("address") for c in clients if c.get("focusHistoryID") == 0), None)
    ws = next(((m.get("activeWorkspace") or {}).get("name") for m in monitors if m.get("focused")), None)
    for lua, _words in steps:
        sessions.hypr_eval(lua)
    if steps:
        sleep(0.4)
        clients = sessions.hypr_json("clients") or []
    fix = sides_fix(clients, monitors, ws, pair, focused)
    if fix:
        sessions.hypr_eval(fix)
    words = [w for _l, w in steps] + (["swapped sides"] if fix else [])
    if notify:
        note("Arranged as usual", f"{pair[0]} and {pair[1]}" + (": " + ", ".join(words) if words else
                                                                ": already as usual"))
    return 0


def note(summary, body=""):
    try:
        subprocess.run(["notify-send", "-a", "Smart layout", "-i", "view-grid", "-u", "low", summary, body],
                       timeout=5, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass


# -- the commands -------------------------------------------------------------------------
def status():
    data = read_store()
    s = settings_of(data)
    apps = []
    for cls, app in data["apps"].items():
        places = [{"key": k, "words": place_words(k, p), "count": p.get("count", 0),
                   "against": p.get("against", 0), "confidence": round(conf, 3)}
                  for k, p, conf in ranked(app)]
        if not places:
            continue
        found = decision(app, s["evidence"])
        apps.append({"class": cls, "locked": app.get("locked"), "places": places, "last": app.get("last", 0),
                     "applies": found[0] if found else None, "why": found[2] if found else None})
    apps.sort(key=lambda a: (a["applies"] is None, -a["places"][0]["count"], a["class"].lower()))
    pairs = [{"a": k.split("\t")[0], "b": k.split("\t")[1], "count": p.get("count", 0),
              "sides": p.get("sides") or {}, "ready": p.get("count", 0) >= s["evidence"]}
             for k, p in data["pairs"].items()]
    pairs.sort(key=lambda p: -p["count"])
    return {"settings": s, "apps": apps, "pairs": pairs, "min_stay_s": MIN_STAY_S, "min_conf": MIN_CONF,
            "store": STORE}


def human(data):
    s = data["settings"]
    lines = [f"mode {s['mode']}, evidence {s['evidence']}, follow {s['follow']}"]
    for a in data["apps"]:
        best = a["places"][0]
        mark = "LOCK" if a["locked"] else "use " if a["applies"] else "    "
        lines.append(f"{mark} {a['class']:<32} {best['words']}  ({best['count']}x, "
                     f"{round(best['confidence'] * 100)} %, {best['against']} against)")
    for p in data["pairs"]:
        lines.append(f"pair {p['a']} + {p['b']}: {p['count']}x {p['sides']}")
    return "\n".join(lines)


def main(argv):
    cmd, args = (argv[0] if argv else "status"), argv[1:]
    if cmd == "run":
        serve()
    elif cmd == "status":
        data = status()
        print(json.dumps(data) if "--json" in args else human(data))
    elif cmd == "set" and len(args) == 2:
        key, value = args
        if key == "mode" and value in MODES or key == "follow" and value in ("on", "off"):
            pass
        elif key == "evidence" and value.isdigit() and EVIDENCE_RANGE[0] <= int(value) <= EVIDENCE_RANGE[1]:
            value = int(value)
        else:
            return "smartlayout: set mode off|learn|on, evidence 2..20, follow on|off"
        with Store() as data:
            data["settings"][key] = value
    elif cmd in ("lock", "unlock", "forget") and args:
        cls = args[0]
        with Store() as data:
            if cmd == "forget" and cls == "all":
                data["apps"], data["pairs"] = {}, {}
                return 0
            app = data["apps"].get(cls)
            if cmd == "forget":
                data["apps"].pop(cls, None)
                for k in [k for k in data["pairs"] if cls in k.split("\t")]:
                    del data["pairs"][k]
            elif cmd == "unlock":
                if app:
                    app["locked"] = None
            else:
                key = args[1] if len(args) > 1 else (ranked(app)[0][0] if app and ranked(app) else None)
                if not key or not KEY_RE.match(key):
                    return "smartlayout: lock CLASS [WORKSPACE|tile|SIDE or WORKSPACE|float|SIDE]"
                app = app_entry(data, cls)
                app["placements"].setdefault(key, {"count": 0, "against": 0})
                app["locked"] = key
    elif cmd == "forget-pair" and len(args) == 2:
        with Store() as data:
            data["pairs"].pop(pair_key(*args), None)
    elif cmd == "arrange":
        return arrange()
    else:
        print(__doc__.split("\n\n")[1])
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
