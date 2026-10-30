#!/usr/bin/env python3
"""Disk pill, and the lsblk reading disk_panel.py shares.

    disk.py      one line of waybar JSON

Replaces waybar's built-in disk module, which follows exactly one path: with
it the pill sat at a calm 28% for / while /mnt/Andromeda was 98% full. The
text still shows / (the number you want at a glance), but the pill's state is
the fullest filesystem on any disk:

    warning   any filesystem at 85% or more   yellow pill, "⚠ 98%" appended
    critical  any filesystem at 95% or more   red pill

The appended number is that worst filesystem's, so a yellow pill reading 28%
is never a mystery; the panel (left click) says which one it is.

On a narrow screen (barfit.py: a laptop's) the text is a meter instead, /
in 25% segments, class "meters"; the warning and critical fills still say
when some other filesystem is the full one.

Kept free of gi: waybar runs this every minute, the panel imports it.
"""

import json
import subprocess
import sys

WARNING, CRITICAL = 85, 95
COLUMNS = ("NAME,PATH,MODEL,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINTS,"
           "FSSIZE,FSUSED,TRAN,RM")
GLYPH = "⽥"            # ⽥, what the pill has always shown
ALERT = ""            # Font Awesome triangle-exclamation


def human(size):
    """Decimal units, as drive makers and lsblk label them: a "4TB" SSD reads
    4.1 T here, not 3.7 T."""
    size = float(size or 0)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if size < 1000 or unit == "P":
            return f"{size:.0f} {unit}" if unit in "BKM" else f"{size:.1f} {unit}"
        size /= 1000
    return ""


def read_disks():
    """[(disk, [filesystem, ...])], or None if lsblk failed. A filesystem is
    the disk itself or any descendant with an fstype, so partitions, LVM
    volumes and bare-disk filesystems all count. zram (compressed swap in RAM)
    is not a disk and is left out."""
    try:
        out = subprocess.run(["lsblk", "-J", "-b", "-o", COLUMNS],
                             capture_output=True, text=True, timeout=5).stdout
        devices = json.loads(out)["blockdevices"]
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        return None

    def filesystems(node):
        found = []
        if node.get("fstype") and node["fstype"] != "LVM2_member":
            found.append(node)
        for child in node.get("children", []):
            found += filesystems(child)
        return found

    return [(disk, filesystems(disk)) for disk in devices
            if disk.get("type") == "disk" and not disk["name"].startswith("zram")]


def mountpoints(fs):
    return sorted(m for m in (fs.get("mountpoints") or []) if m)


def percent(fs):
    """Used share of a mounted filesystem, or None (swap, unmounted: lsblk
    only reports usage for filesystems that are mounted)."""
    size, used = fs.get("fssize"), fs.get("fsused")
    if not size or used is None:
        return None
    return 100 * int(used) / int(size)


def pill(narrow=False):
    disks = read_disks()
    if disks is None:
        return {"text": f"? {GLYPH}", "class": "unavailable"}

    root, worst, worst_at = None, -1.0, ""
    for _disk, filesystems in disks:
        for fs in filesystems:
            used = percent(fs)
            if used is None:
                continue
            mounts = mountpoints(fs)
            if "/" in mounts:
                root = used
            if used > worst:
                worst, worst_at = used, ", ".join(mounts)

    text = f"{root:.0f}% {GLYPH}" if root is not None else GLYPH
    state = ("critical" if worst >= CRITICAL else
             "warning" if worst >= WARNING else "")
    if state:
        text += f"  {ALERT} {worst:.0f}%"
    if narrow:
        import barfit
        return {"text": barfit.vbars([root or 0]), "class": [c for c in (state, "meters") if c],
                "alt": worst_at, "percentage": round(worst)}
    # alt carries the culprit for anyone scripting against the bar; there is
    # no tooltip (it would cover the panel).
    return {"text": text, "class": state, "alt": worst_at,
            "percentage": round(worst)}


def main():
    try:
        import barfit
        narrow = barfit.narrow()
    except Exception:       # noqa: BLE001 - the usual pill
        narrow = False
    print(json.dumps(pill(narrow)), flush=True)


if __name__ == "__main__":
    sys.exit(main())
