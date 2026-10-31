#!/usr/bin/env python3
"""The toolbox card's Battery row (custom/keybinds#battery in config-toolbox:
the name gives it the plain row's look in every theme, as the Microphone row's
does; config-toolbox says why). Shown in the card while the top bar is off
(bar-settings.py toolbox-config-path, hypr/scripts/dock.py TOP BAR OFF); hidden
otherwise, though Settings > Bar & toolbox can show it for good. On a machine
without a battery it prints no text, and waybar hides the row.

    battery_row.py      one JSON line, then exit (the config runs it every 30 s)

The row: the battery glyph (the taskbar's, dock.py BATTERY_GLYPHS, with the
bolt while charging), the charge and the time ("Battery" only without one): "2h 15m left"
running down, "full in 40m" charging, "plugged in" on the cable held short
of full, the charge alone when full. Short, as the row shares a line of the
card's grid.
Class "charging", "full", "warning" (25 %) or "critical" (12 %) as the bar's
battery pill. Click: Settings > Power & lock.

The time comes from UPower (`upower -i`), which averages the draw over the
last minutes; sysfs (energy / power, or charge / current) is the fallback,
whose instant draw jumps with every burst of load.
"""
import json
import os
import re
import subprocess
import sys

POWER_SUPPLY = "/sys/class/power_supply"
GLYPHS = ("", "", "", "", "")   # Font Awesome empty .. full
BOLT = ""
# "battery" is a Font Awesome icon name: in a theme whose font stack reaches
# Font Awesome first its ligature drew the word as the icon (mic_row.py WORD).
WORD = "‌".join("Battery")


def duration(hours):
    """Hours -> "2h 15m" / "40m" (short: the row shares its line in the
    card's grid); None for nothing usable."""
    if hours is None or hours <= 0 or hours > 48:
        return None
    mins = int(round(hours * 60))
    h, m = divmod(mins, 60)
    return f"{h}h {m:02d}m" if h else f"{max(1, m)}m"


def from_upower(text):
    """`upower -i <battery>` -> {"pct", "state", "hours"} or None (no
    battery, not present)."""
    fields = {}
    for line in (text or "").splitlines():
        m = re.match(r"\s*([a-z][a-z -]*?):\s+(.*\S)\s*$", line)
        if m:
            fields.setdefault(m.group(1), m.group(2))
    if fields.get("present") == "no" or "percentage" not in fields:
        return None
    try:
        pct = round(float(fields["percentage"].rstrip("%").replace(",", ".")))
    except ValueError:
        return None
    state = fields.get("state", "unknown")
    hours = None
    m = re.match(r"([0-9.,]+)\s+(\w+)", fields.get("time to empty" if state == "discharging" else "time to full", ""))
    if m:
        value = float(m.group(1).replace(",", "."))
        unit = m.group(2)
        hours = value / 60 if unit.startswith("minute") else value / 3600 if unit.startswith("second") else value
    return {"pct": pct, "state": state, "hours": hours}


def from_sysfs(root=POWER_SUPPLY):
    """The first BAT* under root, as from_upower; None without one."""
    try:
        names = sorted(n for n in os.listdir(root) if n.startswith("BAT"))
    except OSError:
        return None

    def num(d, key):
        try:
            with open(os.path.join(d, key)) as fh:
                return float(fh.read().strip())
        except (OSError, ValueError):
            return None
    for name in names:
        d = os.path.join(root, name)
        pct = num(d, "capacity")
        if pct is None:
            continue
        try:
            with open(os.path.join(d, "status")) as fh:
                status = fh.read().strip()
        except OSError:
            status = ""
        state = {"Charging": "charging", "Discharging": "discharging", "Full": "fully-charged",
                 "Not charging": "pending-charge"}.get(status, "unknown")
        now, full, rate = num(d, "energy_now"), num(d, "energy_full"), num(d, "power_now")
        if now is None:
            now, full, rate = num(d, "charge_now"), num(d, "charge_full"), num(d, "current_now")
        hours = None
        if now is not None and rate:
            rate = abs(rate)
            if state == "discharging":
                hours = now / rate
            elif state == "charging" and full:
                hours = max(0.0, full - now) / rate
        return {"pct": int(pct), "state": state, "hours": hours}
    return None


def row(got):
    """from_upower / from_sysfs -> the row's JSON (a dict); no text without
    a battery."""
    if got is None:
        return {"text": "", "tooltip": "", "class": "none"}
    pct = max(0, min(100, got["pct"]))
    state = got["state"]
    glyph = GLYPHS[min(4, (pct + 12) // 25)]
    left = duration(got["hours"])
    if state == "charging":
        glyph = f"{BOLT} {glyph}"
        when, cls = (f"full in {left}" if left else "charging"), "charging"
    elif state == "discharging":
        when = f"{left} left" if left else "on battery"
        cls = "critical" if pct <= 12 else "warning" if pct <= 25 else "on"
    elif state == "fully-charged" or pct >= 99:
        when, cls = None, "full"
    else:
        when, cls = "plugged in", "full"
    tip = f"Battery {pct}% · {when or 'full'}\nclick: Power & lock settings"
    # With a time the glyph says "battery" alone: the word made the row wider
    # than its column in the card's grid.
    text = f"{glyph}   {pct}% · {when}" if when else f"{glyph}   {WORD} {pct}%"
    return {"text": text, "tooltip": tip, "class": cls}


def probe():
    got = None
    try:
        devices = subprocess.run(["upower", "-e"], capture_output=True, text=True, timeout=3).stdout.split()
        bat = next((d for d in devices if "/battery_BAT" in d), None) or \
            next((d for d in devices if "battery" in d.rsplit("/", 1)[-1]), None)
        if bat:
            got = from_upower(subprocess.run(["upower", "-i", bat], capture_output=True, text=True,
                                             timeout=3).stdout)
    except (OSError, subprocess.SubprocessError):
        got = None
    if got is None or (got["hours"] is None and got["state"] in ("charging", "discharging")):
        got = from_sysfs() or got
    return json.dumps(row(got))


def main():
    try:
        print(probe())
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
