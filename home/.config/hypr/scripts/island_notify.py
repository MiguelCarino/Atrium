#!/usr/bin/env python3
"""Notifications in the dynamic island: the pure half (no GTK, no D-Bus;
tests/test_island_notify.py). island.py's daemon owns the window, the bus
monitor and makoctl; everything it decides about a notification is here.

    island.py ──(D-Bus monitor: Notify + its reply, NotificationClosed)──> queue
              ──(pick: what shows now, what goes to the history)──> render
              ──(makoctl invoke / dismiss -n ID)──> mako

Mako stays the notification server (it owns org.freedesktop.Notifications,
numbers them, keeps the history, runs actions); its "island" mode
(mako/island: invisible=1, default-timeout=0) only stops its popups. So the
island has to answer two questions mako would have answered on screen:

  * would mako have SHOWN it? -- mako_visible() reads the invisible= lines
    of mako's own config (config, its includes: sections, contexts,
    settings) and applies them for the current modes minus "island". Do Not
    Disturb (and its urgent break-through switch), a project-focus filter or
    any later [mode=...] rule therefore hold notifications back exactly as
    they did; a held one is never drawn and goes to the history when its
    time is up, like mako's invisible ones.
  * for how long? -- duration(): Settings > Notifications' timeouts per
    urgency (notifications.json), an app's own expire timeout unless "ignore
    app timeouts" is on; None (critical by default) stays until dismissed.

The queue shows one notification at a time, critical first, then oldest
first. While others wait, each normal one gets at most QUEUE_STEP_S, and a
critical one that has had STICKY_HOLD_S steps aside (parked) for them and
comes back afterwards. Hovering freezes the clock. A flood never stacks up
more than QUEUE_MAX waiting: the oldest waiting ones go straight to the
history (the bell's panel lists them).

Items are dicts:
    id        mako's notification id (dedupe key: a replaces_id update and
              the startup `makoctl list -j` merge into the same item)
    app, summary, body (plain text), urgency "low|normal|critical",
    actions   [(key, label)] in the sender's order ("default" included)
    icon      a file path or an icon name (image-path beats app_icon), ""
    data      True when the sender gave raw image-data (island.py keeps the
              picture by id)
    expire    the sender's expire_timeout in ms (-1: the server's default)
    category, desktop_entry  the sender's hints of those names (mako rules)
    seq       arrival order;  visible  mako_visible() (again on a mode change)
    dur       seconds, or None (sticky);  shown_at  monotonic, or None
    parked    a sticky one that stepped aside;  arrived  monotonic
"""
import html
import os
import re

QUEUE_STEP_S = 4.0            # the most a normal one shows while others wait
STICKY_HOLD_S = 8.0           # a critical one's turn before it lets others by
AFTER_HOVER_S = 2.0           # left after the pointer leaves it
MIN_S = 1.5                   # nobody reads anything faster
QUEUE_MAX = 8                 # waiting (not counting the one that shows)
URGENCIES = ("low", "normal", "critical")
DEFAULT_TIMEOUTS = {"low": 3, "normal": 5, "critical": 0}      # notify-settings.py's
RAILGUARD_APP = "Railguard"
RAILGUARD_TWIN_S = 30.0       # a Railguard alert and its notification: one event
MAX_INCLUDE_DEPTH = 6
TAG = re.compile(r"<[^>]*>")


# -- reading a notification -------------------------------------------------------------------
def urgency_name(value):
    """The spec's urgency byte (0/1/2), mako's JSON (null / "low" ...) or a
    notify-send word as one of URGENCIES; anything else is normal."""
    if isinstance(value, bool):
        return "normal"
    if isinstance(value, int):
        return URGENCIES[value] if 0 <= value < 3 else "normal"
    word = str(value or "").strip().lower()
    return word if word in URGENCIES else "normal"


def plain_text(markup):
    """mako's markup=1 body as plain text: tags out, entities decoded, runs
    of blank space folded (newlines kept, at most one empty line)."""
    text = TAG.sub("", str(markup or "").replace("<br>", "\n").replace("<br/>", "\n"))
    text = html.unescape(text).replace("\r", "")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    out = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def pair_actions(flat):
    """The spec's flat [key, label, key, label ...] as [(key, label)];
    an odd trailing key is dropped."""
    flat = [str(x) for x in (flat or [])]
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)]


def from_notify(nid, app, icon, summary, body, actions, hints, expire):
    """An item from a Notify call (hints: a plain dict, image-data already
    reduced to True by the caller)."""
    hints = hints or {}
    image = hints.get("image-path") or hints.get("image_path") or ""
    return {"id": int(nid), "app": str(app or ""), "summary": plain_text(summary),
            "body": plain_text(body), "urgency": urgency_name(hints.get("urgency")),
            "actions": pair_actions(actions), "icon": str(image or icon or ""),
            "data": bool(hints.get("image-data") or hints.get("image_data") or hints.get("icon_data")),
            "category": str(hints.get("category") or ""),
            "desktop_entry": str(hints.get("desktop-entry") or ""),
            "expire": int(expire if isinstance(expire, int) else -1)}


def from_mako(entry):
    """An item from one `makoctl list -j` entry (no expire timeout or
    picture there: what was on screen before the island started)."""
    actions = entry.get("actions") or {}
    return {"id": int(entry.get("id") or 0), "app": str(entry.get("app_name") or ""),
            "summary": plain_text(entry.get("summary")), "body": plain_text(entry.get("body")),
            "urgency": urgency_name(entry.get("urgency")),
            "actions": [(str(k), str(v)) for k, v in actions.items()] if isinstance(actions, dict) else [],
            "icon": str(entry.get("app_icon") or ""), "data": False,
            "category": str(entry.get("category") or ""),
            "desktop_entry": str(entry.get("desktop_entry") or ""), "expire": -1}


def buttons(item, limit=3):
    """The action buttons: every action but "default" (clicking the card
    runs that one), at most `limit`, labels cut short."""
    out = []
    for key, label in item.get("actions") or []:
        if key == "default" or not label:
            continue
        out.append((key, label if len(label) <= 18 else label[:17] + "…"))
    return out[:limit]


# -- how long ---------------------------------------------------------------------------------
def timeouts(conf):
    """notifications.json's {urgency: seconds} (0 = until dismissed) and
    its ignore_app_timeouts, with the defaults for anything missing."""
    conf = conf if isinstance(conf, dict) else {}
    out = {}
    for u in URGENCIES:
        v = conf.get(f"timeout_{u}", DEFAULT_TIMEOUTS[u])
        out[u] = v if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 \
            else DEFAULT_TIMEOUTS[u]
    return out, bool(conf.get("ignore_app_timeouts"))


def duration(item, conf):
    """Seconds it shows, or None: until dismissed."""
    per, ignore_app = timeouts(conf)
    expire = item.get("expire", -1)
    if not ignore_app and isinstance(expire, int) and expire >= 0:
        return None if expire == 0 else max(MIN_S, expire / 1000)
    secs = per[item.get("urgency") or "normal"]
    return None if not secs else max(MIN_S, float(secs))


# -- would mako have shown it ------------------------------------------------------------------
def unquote(value):
    """A mako criteria value: "quoted, with \\" and \\\\" or bare."""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    return value


def criteria_tokens(text):
    """`mode=x summary~="a b"` -> ["mode=x", 'summary~="a b"'] (quotes kept)."""
    out, cur, quoted, i = [], "", False, 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and quoted and i + 1 < len(text):
            cur += text[i:i + 2]
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
        if ch.isspace() and not quoted:
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    if cur:
        out.append(cur)
    return out


def parse_criteria(text):
    """[(field, op, value)] for one section header; op is "=" or "~"; a
    bare word (grouped, hidden ...) is (word, "=", "true")."""
    out = []
    for tok in criteria_tokens(text):
        m = re.match(r"^([a-z-]+)(~?=)(.*)$", tok)
        if m:
            out.append((m.group(1), "~" if m.group(2) == "~=" else "=", unquote(m.group(3))))
        else:
            out.append((tok, "=", "true"))
    return out


def mako_rules(path, depth=0):
    """The invisible= lines of a mako config and everything it includes,
    in reading order: [(criteria text ("" global), "1"|"0")]. A missing or
    unreadable file is nothing (mako itself would refuse it, so it is not
    the config mako runs with anyway)."""
    rules = []
    if depth > MAX_INCLUDE_DEPTH:
        return rules
    try:
        with open(os.path.expanduser(path)) as fh:
            lines = fh.read().splitlines()
    except OSError:
        return rules
    section = ""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "include" and section == "":
            rules += mako_rules(value, depth + 1)
            section = ""          # back in this file's global scope
        elif key == "invisible":
            rules.append((section, "1" if value.lower() in ("1", "true", "yes") else "0"))
    return rules


def matches(criteria, item, modes):
    """Whether one parsed section header applies to `item` with `modes`
    active. A criterion it cannot judge (one mako added later) does not
    match, so an unknown rule never hides anything by mistake."""
    fields = {"app-name": item.get("app"), "app-icon": item.get("icon"),
              "summary": item.get("summary"), "body": item.get("body"),
              "urgency": item.get("urgency"), "category": item.get("category"),
              "desktop-entry": item.get("desktop_entry")}
    for field, op, value in criteria:
        if field == "mode":
            if value not in modes:
                return False
        elif field in ("output", "anchor"):
            continue              # where it would pop up: the island is one place
        elif field in ("grouped", "hidden"):
            if value.lower() in ("true", "1", "yes"):
                return False      # the island never groups or hides
        elif field == "actionable":
            if bool(item.get("actions")) != (value.lower() in ("true", "1", "yes")):
                return False
        elif field == "expiring":
            if (item.get("dur") is not None) != (value.lower() in ("true", "1", "yes")):
                return False
        elif field in fields:
            have = str(fields[field] or "")
            if op == "~":
                try:
                    if not re.search(value, have):
                        return False
                except re.error:
                    return False
            elif have != value:
                return False
        else:
            return False
    return True


def mako_visible(item, modes, rules):
    """Would mako (without the island's mode) have drawn it? rules is
    mako_rules(); later matching sections win, like mako's own reading."""
    modes = set(modes or ()) - {"island"}
    invisible = False
    for header, value in rules:
        crit = parse_criteria(header) if header else []
        if any(f == "mode" and v == "island" for f, _o, v in crit):
            continue
        if matches(crit, item, modes):
            invisible = value == "1"
    return not invisible


# -- the queue --------------------------------------------------------------------------------
def upsert(queue, item, now, seq):
    """Add `item`, or update the one with its id in place (a replaces_id
    notification: the new words, its clock started again when it shows).
    Returns True when it is new."""
    for old in queue:
        if old["id"] == item["id"]:
            keep = {k: old[k] for k in ("seq", "arrived") if k in old}
            showing = old.get("shown_at") is not None
            old.clear()
            old.update(item, **keep)
            old["shown_at"] = now if showing else None
            old["parked"] = False
            return False
    queue.append(dict(item, seq=seq, arrived=now, shown_at=None, parked=False))
    return True


def remove(queue, nid):
    """Drop the item with this id (closed by mako, the app or the user);
    True when there was one."""
    for i, it in enumerate(queue):
        if it["id"] == nid:
            del queue[i]
            return True
    return False


def order(queue):
    """The visible ones in showing order: unparked before parked, critical
    before the rest, then oldest first."""
    vis = [it for it in queue if it.get("visible", True)]
    return sorted(vis, key=lambda it: (bool(it.get("parked")), it.get("urgency") != "critical",
                                       it.get("seq", 0)))


def pick(queue, now, hovering=False):
    """What shows now. Expires (in place) what is done: returns (current
    item or None, [ids done -- to dismiss into mako's history], the
    monotonic time to look again or None)."""
    done = []
    wake = []
    # held back (Do Not Disturb ...): never drawn, gone when their time is up
    for it in [it for it in queue if not it.get("visible", True)]:
        if it.get("dur") is None:
            continue
        end = it["arrived"] + it["dur"]
        if end <= now:
            done.append(it["id"])
            queue.remove(it)
        else:
            wake.append(end)
    while True:
        line = order(queue)
        if not line:
            return None, done, (min(wake) if wake else None)
        cur = line[0]
        waiting = line[1:]
        # A flood: the oldest waiting ones go to the history unseen.
        extra = [it for it in waiting if it.get("dur") is not None]
        while len(waiting) > QUEUE_MAX and extra:
            gone = min(extra, key=lambda it: it.get("seq", 0))
            extra.remove(gone)
            waiting.remove(gone)
            queue.remove(gone)
            done.append(gone["id"])
        if cur.get("shown_at") is None:
            cur["shown_at"] = now
        if hovering:
            return cur, done, (min(wake) if wake else None)
        shown_for = now - cur["shown_at"]
        if cur.get("dur") is None:
            # sticky: stays, but lets the waiting by after its turn
            # (a parked one is current only when nothing unparked waits:
            # order() puts those first)
            if any(not it.get("parked") for it in waiting):
                if shown_for >= STICKY_HOLD_S:
                    cur["parked"], cur["shown_at"] = True, None
                    continue
                wake.append(cur["shown_at"] + STICKY_HOLD_S)
            return cur, done, (min(wake) if wake else None)
        limit = min(cur["dur"], QUEUE_STEP_S) if waiting else cur["dur"]
        if shown_for >= limit - 0.01:
            queue.remove(cur)
            done.append(cur["id"])
            continue
        wake.append(cur["shown_at"] + limit)
        return cur, done, min(wake)


def after_hover(item, now, waiting=False):
    """The pointer left: AFTER_HOVER_S more (none for a sticky one) --
    counted against the shorter turn it gets while others wait."""
    if item.get("dur") is not None:
        limit = min(item["dur"], QUEUE_STEP_S) if waiting else item["dur"]
        item["shown_at"] = now - max(0.0, limit - AFTER_HOVER_S)


def revisit(queue, modes, rules):
    """The modes changed (Do Not Disturb on or off, a project-focus
    filter, a reload): each item's mako_visible() again, as mako re-reads
    its own rules then. One that goes back starts its turn over when it
    shows again. True when anything changed."""
    changed = False
    for it in queue:
        vis = mako_visible(it, modes, rules)
        if vis != it.get("visible", True):
            it["visible"], it["shown_at"], it["parked"] = vis, None, False
            changed = True
    return changed


def waiting_count(queue, current):
    """How many visible ones wait behind the current one (the "+N")."""
    return max(0, len(order(queue)) - (1 if current is not None else 0))


# -- dedupe -----------------------------------------------------------------------------------
def railguard_twin(queue, title, now, window=RAILGUARD_TWIN_S):
    """Railguard sends an alert to the island AND a notification (critical,
    app "Railguard", the same title as its summary). The queued twin of
    `title`, or None."""
    for it in queue:
        if it.get("app") == RAILGUARD_APP and it.get("summary") == plain_text(title) \
                and now - it.get("arrived", now) <= window:
            return it
    return None


def is_railguard_twin(item, alert, now, window=RAILGUARD_TWIN_S):
    """Whether a new notification is the twin of the Railguard alert the
    island shows (alert: its activity dict with "title" and "at")."""
    return bool(alert) and item.get("app") == RAILGUARD_APP \
        and item.get("summary") == plain_text(alert.get("title")) \
        and now - alert.get("at", now) <= window
