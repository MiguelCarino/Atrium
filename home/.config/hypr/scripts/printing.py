#!/usr/bin/env python3
"""Printing: a toast for every print job, and the queue on the bar.

    printing.py daemon          watch CUPS (printing.service): a toast when a
                                job is sent ("Printing ..."), replaced by
                                "Printed" / "Cancelled" / "Failed" when it
                                ends; a toast when a printer needs a hand (out
                                of paper, jammed, ink low, not answering). It
                                keeps the queue in $XDG_RUNTIME_DIR/printing.json
                                for the bar and signals it on change
                                (bar_signals.py "printing")
    printing.py bar             waybar JSON for custom/printing: a printer and
                                the number of jobs, only while any are
                                queued (yellow when one is held, red when one
                                is stopped or its printer needs a hand);
                                empty (hidden) otherwise
    printing.py list [--json]   the queue: id, state, printer, name
    printing.py cancel <id>|all
    printing.py hold <id> | release <id>
    printing.py settings        the printers' settings (GNOME Settings >
                                Printers, else CUPS's own page)

CUPS tells the daemon about every change on the system bus (a dbus://
subscription, renewed before its lease runs out); a slow poll backs that up,
so a missed signal or a restarted cupsd only delays a toast. Toasts are for
this user's jobs; other users' jobs still show in the queue. A printer's
trouble is toasted when it starts, not again until it clears.
"""
import json
import os
import subprocess
import sys
import threading

NOTIFY = os.path.expanduser("~/.config/hypr/scripts/notify")  # notify-send with the theme's mascot (mascot_notify.py)
STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "printing.json")
PANEL = os.path.expanduser("~/.config/waybar/scripts/panel.py")
GROUP = 2               # more jobs than this ending at once: one toast for them all
LEASE = 900             # s, the dbus:// subscription; renewed at half
POLL_BUSY, POLL_IDLE = 3, 60   # s between checks with / without jobs queued
EVENTS = ["job-created", "job-completed", "job-state-changed", "job-progress",
          "printer-state-changed", "printer-stopped", "printer-added", "printer-deleted"]

# IPP job-state
PENDING, HELD, PROCESSING, STOPPED, CANCELED, ABORTED, COMPLETED = 3, 4, 5, 6, 7, 8, 9
ACTIVE = (PENDING, HELD, PROCESSING, STOPPED)
JOB_STATE = {PENDING: "queued", HELD: "on hold", PROCESSING: "printing", STOPPED: "stopped",
             CANCELED: "cancelled", ABORTED: "failed", COMPLETED: "printed"}
PRINTER_STATE = {3: "idle", 4: "printing", 5: "stopped"}
JOB_ATTRS = ["job-id", "job-name", "job-state", "job-state-reasons", "job-printer-uri",
             "job-originating-user-name", "job-impressions-completed", "job-media-sheets-completed",
             "job-k-octets", "time-at-creation", "time-at-completed", "job-printer-state-message"]

# printer-state-reasons worth a toast (the -report/-warning/-error suffix is
# dropped first). "none", "paused" (a stopped queue says so itself),
# "cups-*" bookkeeping and the rest are not.
TROUBLE = {
    "media-empty": "Out of paper", "media-needed": "Out of paper", "media-low": "Paper is low",
    "media-jam": "Paper jam", "cover-open": "A cover is open", "door-open": "A door is open",
    "marker-supply-empty": "Out of ink", "marker-supply-low": "Ink is low",
    "toner-empty": "Out of toner", "toner-low": "Toner is low",
    "marker-waste-full": "The waste ink pad is full", "marker-waste-almost-full": "The waste ink pad is nearly full",
    "offline": "The printer is not answering", "connecting-to-device": "The printer is not answering",
    "output-area-full": "The output tray is full", "input-tray-missing": "A paper tray is missing",
    "other": "The printer reports a problem",
}


def reason_key(reason):
    for suffix in ("-report", "-warning", "-error"):
        if reason.endswith(suffix):
            return reason[: -len(suffix)]
    return reason


def troubles(reasons):
    """printer-state-reasons -> [(key, words)] worth telling the user about."""
    out = []
    for reason in reasons or ():
        key = reason_key(reason)
        if key in TROUBLE and all(k != key for k, _ in out):
            out.append((key, TROUBLE[key]))
    return out


def severe(reasons):
    """An -error reason (or one we know stops printing) -- the bar goes red."""
    return any(r.endswith("-error") or reason_key(r) in ("media-empty", "media-needed", "media-jam", "cover-open",
                                                         "door-open", "marker-supply-empty", "toner-empty")
               for r in reasons or ())


def printer_of(uri):
    return (uri or "").rstrip("/").rsplit("/", 1)[-1]


def pages_text(n):
    return f"{n} page" + ("" if n == 1 else "s") if n else ""


# -- reading CUPS ----------------------------------------------------------------
def connect():
    import cups      # here, not at the top: `bar` reads the state file and never needs it
    return cups.Connection()


def job_row(jid, attrs, me):
    reasons = attrs.get("job-state-reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    pages = attrs.get("job-impressions-completed") or attrs.get("job-media-sheets-completed") or 0
    return {"id": jid, "name": attrs.get("job-name") or "", "state": attrs.get("job-state", PENDING),
            "reasons": [r for r in reasons if r != "none"], "printer": printer_of(attrs.get("job-printer-uri")),
            "user": attrs.get("job-originating-user-name") or "", "pages": pages,
            "kb": attrs.get("job-k-octets") or 0, "created": attrs.get("time-at-creation") or 0,
            "completed": attrs.get("time-at-completed") or 0,
            "mine": (attrs.get("job-originating-user-name") or me) == me}


def jobs_of(conn, which, **kw):
    """{id: row}. CUPS hides a job's name and owner (JobPrivateValues) unless
    the request is for the asker's own jobs, so everyone's jobs are listed
    first (ids, states) and this user's laid over them with their names;
    the rest are someone else's."""
    me = os.environ.get("USER") or ""
    rows = {}
    for mine in (False, True):
        for jid, a in conn.getJobs(which_jobs=which, my_jobs=mine, requested_attributes=JOB_ATTRS, **kw).items():
            row = job_row(jid, a, me)
            row["mine"] = mine
            if not mine:
                row["user"] = row["user"] or "another user"
            rows[jid] = row
    return rows


def snapshot(conn=None):
    """{printers: {name: {...}}, jobs: [{...}] (queued, oldest first)}, or
    {"error": ...} when CUPS cannot be reached."""
    me = os.environ.get("USER") or ""
    try:
        conn = conn or connect()
        printers = {}
        for name, a in conn.getPrinters().items():
            reasons = [r for r in (a.get("printer-state-reasons") or []) if r != "none"]
            printers[name] = {"state": a.get("printer-state", 3), "reasons": reasons,
                              "message": a.get("printer-state-message") or "",
                              "accepting": bool(a.get("printer-is-accepting-jobs", True)),
                              "info": a.get("printer-info") or name}
        rows = jobs_of(conn, "not-completed")
        default = conn.getDefault()
    except Exception as exc:          # cups.IPPError, RuntimeError (no cupsd), ImportError
        return {"error": str(exc) or exc.__class__.__name__, "printers": {}, "jobs": []}
    return {"printers": printers, "jobs": sorted(rows.values(), key=lambda r: r["id"]), "default": default}


def finished(conn, ids):
    """The final state of jobs of mine that just left the queue: {id: row},
    or None for one CUPS no longer keeps (PreserveJobHistory off)."""
    if not ids:
        return {}
    try:
        done = jobs_of(conn, "completed", first_job_id=min(ids))
    except Exception:
        done = {}
    return {jid: done.get(jid) for jid in ids}


def history(limit=8, conn=None):
    """This user's last finished jobs, newest first (for the panel)."""
    me = os.environ.get("USER") or ""
    try:
        conn = conn or connect()
        jobs = conn.getJobs(which_jobs="completed", my_jobs=True, requested_attributes=JOB_ATTRS)
    except Exception:
        return []
    rows = sorted((job_row(j, a, me) for j, a in jobs.items()), key=lambda r: -r["id"])
    return rows[:limit]


# -- what changed ----------------------------------------------------------------
def changes(prev, cur, gone):
    """What to toast between two snapshots: [(kind, job_or_printer, extra)].

    kind: "sent" (a new job of mine; one sent on hold is just "held"), "held", "stopped", "ended" (job left the
    queue; extra = its final row, or None when CUPS no longer has it),
    "trouble" (a printer reason that was not there before; extra = words),
    "cleared" (a stopped printer is idle again)."""
    out = []
    before = {j["id"]: j for j in prev.get("jobs", [])}
    now = {j["id"]: j for j in cur.get("jobs", [])}
    for jid, job in now.items():
        if not job["mine"]:
            continue
        old = before.get(jid)
        if old is None and job["state"] not in (HELD, STOPPED):
            out.append(("sent", job, None))
        if job["state"] == HELD and (old is None or old["state"] != HELD):
            out.append(("held", job, None))
        if job["state"] == STOPPED and (old is None or old["state"] != STOPPED):
            out.append(("stopped", job, None))
    for jid, old in before.items():
        if jid not in now and old["mine"]:
            out.append(("ended", old, gone.get(jid)))
    for name, p in cur.get("printers", {}).items():
        was = prev.get("printers", {}).get(name)
        if was is None:
            continue             # a printer that just appeared (or the first look): nothing to compare
        had = {k for k, _ in troubles(was["reasons"])}
        for key, words in troubles(p["reasons"]):
            if key not in had:
                out.append(("trouble", dict(p, name=name), words))
        if was["state"] == 5 and p["state"] != 5:
            out.append(("cleared", dict(p, name=name), None))
    return out


def summary(ended):
    """One toast for several jobs that ended at once (Cancel all, a queue
    flushed): (title, body, urgency, actions)."""
    counts = {}
    for _job, final in ended:
        word = JOB_STATE.get((final or {}).get("state"), "done")
        counts[word] = counts.get(word, 0) + 1
    title = f"{len(ended)} print jobs ended"
    if len(counts) == 1:
        title = f"{next(iter(counts)).capitalize()} {len(ended)} print jobs"
    body = " · ".join(f"{n} {w}" for w, n in counts.items())
    return (title, body, "critical" if "failed" in counts else "low", [])


def toast_for(kind, item, extra):
    """(title, body, urgency, actions) for one change."""
    name = f"“{item['name']}”" if item.get("name") else "Your document"
    where = item.get("printer") or ""
    if kind == "sent":
        return (f"Printing {name}", where, "low", [("queue", "Show queue"), ("cancel", "Cancel")])
    if kind == "held":
        return (f"On hold: {name}", f"{where} · release it from the queue", "normal",
                [("queue", "Show queue"), ("cancel", "Cancel")])
    if kind == "stopped":
        return (f"Stopped: {name}", " · ".join(filter(None, [where] + item.get("reasons", []))), "critical",
                [("queue", "Show queue")])
    if kind == "ended":
        final = extra or {}
        state = final.get("state")
        pages = pages_text(final.get("pages"))
        if state == COMPLETED:
            return (f"Printed {name}", " · ".join(filter(None, [where, pages])), "low", [])
        if state == CANCELED:
            return (f"Cancelled {name}", where, "low", [])
        if state == ABORTED:
            why = ", ".join(final.get("reasons") or []) or "the printer gave up on it"
            return (f"Printing failed: {name}", f"{where} · {why}", "critical", [("queue", "Show queue")])
        return (f"Done: {name}", where, "low", [])     # purged before we could ask
    if kind == "trouble":
        body = item.get("message") or item.get("info") or item["name"]
        return (f"{item['name']}: {extra}", body, "critical" if severe(item["reasons"]) else "normal",
                [("queue", "Show queue")])
    if kind == "cleared":
        return (f"{item['name']} is printing again", "", "low", [])
    return (name, where, "low", [])


# -- the bar ---------------------------------------------------------------------
def bar_json(state):
    jobs = state.get("jobs", [])
    printers = state.get("printers", {})
    bad = [n for n, p in printers.items() if p["state"] == 5 or severe(p["reasons"])]
    stuck = [j for j in jobs if j["state"] in (STOPPED, HELD)]
    if not jobs:          # a printer's trouble alone is a toast, not a pill
        return {"text": "", "class": "none"}
    lines = []
    for j in jobs:
        bits = [JOB_STATE.get(j["state"], "?"), j["printer"]]
        if j["pages"]:
            bits.append(pages_text(j["pages"]))
        lines.append(f"{j['name'] or 'job ' + str(j['id'])}  —  " + " · ".join(bits))
    for n in bad:
        p = printers[n]
        words = ", ".join(w for _, w in troubles(p["reasons"])) or p["message"] or PRINTER_STATE.get(p["state"], "")
        lines.append(f"⚠ {n}: {words}")
    cls = "error" if bad or any(j["state"] == STOPPED for j in jobs) else ("held" if stuck else "printing")
    text = "" + (f" {len(jobs)}" if jobs else "")
    # The tooltip text stays (`bar` from a shell reads it), but custom/printing
    # has "tooltip": false -- its click opens the queue panel, which would sit
    # under it -- so it carries no click hints.
    return {"text": text, "tooltip": "\n".join(lines), "class": cls}


def read_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_state(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE)


def poke_bar():
    """Redraw custom/printing (bar_signals "printing"): the module is pushed
    from here, its interval only a long safety net."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import bar_signals
        bar_signals.poke("printing")
    except Exception:       # no bar: nothing to redraw
        pass


# -- the daemon ------------------------------------------------------------------
class Daemon:
    def __init__(self):
        from gi.repository import Gio, GLib
        self.GLib = GLib
        self.conn = None
        self.sub = None
        self.state = {"printers": {}, "jobs": []}
        self.first = True
        self.toasts = {}        # job id -> notification id, so "Printed" replaces "Printing"
        self.pending = 0
        self.lock = threading.Lock()
        # kept on self: a connection only a local holds is dropped, and its
        # subscriptions with it
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.bus.signal_subscribe(None, "org.cups.cupsd.Notifier", None, "/org/cups/cupsd/Notifier", None,
                             Gio.DBusSignalFlags.NONE, lambda *a: self.soon(), None)
        self.subscribe()
        GLib.timeout_add_seconds(LEASE // 2, self.renew)
        self.refresh()
        self.tick()

    def connection(self):
        if self.conn is None:
            self.conn = connect()
        return self.conn

    def subscribe(self):
        try:
            self.sub = self.connection().createSubscription(
                "/", events=EVENTS, recipient_uri="dbus://", lease_duration=LEASE)
        except Exception:
            self.conn, self.sub = None, None          # cupsd not up yet: the poll keeps trying

    def renew(self):
        try:
            if self.sub is None:
                raise RuntimeError
            self.connection().renewSubscription(self.sub, lease_duration=LEASE)
        except Exception:
            self.conn = None
            self.subscribe()
        return True

    def soon(self):
        # CUPS sends a burst (created, state, progress...): one look after it
        if not self.pending:
            self.pending = self.GLib.timeout_add(250, self.refresh)

    def tick(self):
        self.refresh()
        busy = bool(self.state.get("jobs"))
        self.GLib.timeout_add_seconds(POLL_BUSY if busy else POLL_IDLE, self.tick)
        return False

    def refresh(self):
        self.pending = 0
        try:
            conn = self.connection()
        except Exception:
            conn = None
        cur = snapshot(conn) if conn else {"error": "cupsd unreachable", "printers": {}, "jobs": []}
        if cur.get("error"):
            self.conn = None
            if self.sub is None:
                self.subscribe()
            return False
        if self.sub is None:
            self.subscribe()
        prev = self.state
        if not self.first:
            now_ids = {j["id"] for j in cur["jobs"]}
            gone = finished(conn, [j["id"] for j in prev.get("jobs", []) if j["id"] not in now_ids and j["mine"]])
            found = changes(prev, cur, gone)
            ended = [(item, extra) for kind, item, extra in found if kind == "ended"]
            for kind, item, extra in found:
                if kind != "ended" or len(ended) <= GROUP:
                    self.toast(kind, item, extra)
            if len(ended) > GROUP:
                self.toast("summary", None, ended)
        self.first = False
        cur["pid"] = os.getpid()
        self.state = cur
        if json.dumps(cur, sort_keys=True) != json.dumps(read_state() or {}, sort_keys=True):
            write_state(cur)
            poke_bar()
        return False

    def toast(self, kind, item, extra):
        if kind == "summary":
            title, body, urgency, actions = summary(extra)
            with self.lock:
                for job, _final in extra:
                    self.toasts.pop(job["id"], None)
            threading.Thread(target=self.send, args=(None, kind, title, body, urgency, actions), daemon=True).start()
            return
        title, body, urgency, actions = toast_for(kind, item, extra)
        jid = item.get("id") if kind in ("sent", "held", "stopped", "ended") else None
        threading.Thread(target=self.send, args=(jid, kind, title, body, urgency, actions), daemon=True).start()

    def send(self, jid, kind, title, body, urgency, actions):
        cmd = [NOTIFY, "-a", "Printing", "-i", "printer", "-u", urgency, "-p"]
        with self.lock:
            replace = self.toasts.get(jid) if jid is not None else None
        if replace:
            cmd += ["-r", str(replace)]
        if actions:
            cmd += ["--wait"] + [f"--action={k}={v}" for k, v in actions]
        cmd += [title, body]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            return
        first = proc.stdout.readline().strip()
        if jid is not None and first.isdigit():
            with self.lock:
                if kind == "ended":
                    self.toasts.pop(jid, None)
                else:
                    self.toasts[jid] = int(first)
        if not actions:
            proc.wait()
            return
        try:
            picked = proc.communicate(timeout=900)[0].strip()
        except subprocess.TimeoutExpired:
            proc.kill()
            return
        if picked == "queue":
            subprocess.Popen([PANEL, "toggle", "printing", "--at", "bar-right"], start_new_session=True)
        elif picked == "cancel" and jid is not None:
            cancel(str(jid))


# -- commands --------------------------------------------------------------------
def job_id(text):
    """12, or lp's "Printer-12"."""
    return int(str(text).rsplit("-", 1)[-1])


def cancel(which):
    conn = connect()
    if which == "all":
        for jid, a in conn.getJobs(which_jobs="not-completed", my_jobs=True).items():
            conn.cancelJob(jid)
    else:
        conn.cancelJob(job_id(which))


def hold(jid, release=False):
    conn = connect()
    if release:
        conn.releaseJob(job_id(jid))
    else:
        conn.setJobHoldUntil(job_id(jid), "indefinite")


def open_settings():
    import shutil
    if shutil.which("gnome-control-center"):
        cmd = ["env", "XDG_CURRENT_DESKTOP=GNOME", "gnome-control-center", "printers"]   # as accounts.py
    elif shutil.which("system-config-printer"):
        cmd = ["system-config-printer"]
    else:
        cmd = ["xdg-open", "http://localhost:631/printers/"]
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def daemon_alive(state):
    """The state file is the daemon's while its pid lives; without it the
    bar looks at CUPS directly."""
    pid = (state or {}).get("pid")
    return bool(pid) and os.path.exists(f"/proc/{pid}")


def main(argv):
    cmd = argv[0] if argv else "list"
    if cmd == "daemon":
        from gi.repository import GLib
        Daemon()
        GLib.MainLoop().run()
    elif cmd == "bar":
        state = read_state()
        if not daemon_alive(state):
            state = snapshot()
        print(json.dumps(bar_json(state)))
    elif cmd == "list":
        state = snapshot()
        if "--json" in argv:
            print(json.dumps(state))
        elif state.get("error"):
            sys.exit(f"printing: {state['error']}")
        else:
            for j in state["jobs"]:
                print(f"{j['id']}\t{JOB_STATE.get(j['state'], '?')}\t{j['printer']}\t{j['name']}")
    elif cmd in ("cancel", "hold", "release") and len(argv) > 1:
        try:
            cancel(argv[1]) if cmd == "cancel" else hold(argv[1], release=cmd == "release")
        except Exception as exc:      # cups.IPPError: finished already, not yours, no such job
            sys.exit(f"printing: {cmd} {argv[1]}: {exc.args[-1] if exc.args else exc}")
    elif cmd == "settings":
        open_settings()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
