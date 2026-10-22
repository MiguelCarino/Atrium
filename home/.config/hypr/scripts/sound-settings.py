#!/usr/bin/env python3
"""Sound settings: outputs, inputs, per-application volume, profiles, and the
over-amplification switch. The backend of the Settings app's Sound page, and
usable from a terminal or the search bar the same way.

    sound-settings.py status [--json]             everything below, as text or JSON
    sound-settings.py default <device>            play / record through this device
    sound-settings.py volume <device> <percent>   set its volume (balance kept, capped
                                                  at the limit, see `boost`)
    sound-settings.py mute <device> on|off|toggle
    sound-settings.py balance <output> <-100..100>  left (-) / right (+); 0 is centred
    sound-settings.py port <device> <port>        headphones / speakers on one card
    sound-settings.py app volume <index> <percent>  one application's stream
    sound-settings.py app mute <index> on|off|toggle
    sound-settings.py app move <index> <output>   play that application elsewhere
    sound-settings.py profile <card> <profile>    e.g. a Bluetooth headset's A2DP / HFP
    sound-settings.py boost on|off|status         over-amplification: volumes up to 150 %
    sound-settings.py limit                       1.0 or 1.5 -- what osd.py passes to
                                                  `wpctl set-volume -l` for the keys
    sound-settings.py meter <source> [seconds]    print the input's level (0-100), ten
                                                  lines a second; records nothing

<device> is a sink or source name (pactl's, "alsa_output.usb-..."), or its
index. Run `status` to see them.

Everything goes through pactl (pipewire-pulse), whose `-f json` output carries
every property, rather than wpctl status, which is a tree drawn for humans.
WirePlumber remembers what pactl changes -- the default devices
(~/.local/state/wireplumber/default-nodes), each device's volume and mute,
each application's volume (restore-stream), card profiles -- so every change
here survives a Hyprland reload and a re-login without this script keeping
any of it. (Except `app move`: WirePlumber's restore-stream keeps an
application's volume and mute but, as configured here, not its output, so a
moved application goes back to the default output the next time it plays.) The one thing it does keep is the over-amplification switch, in
$XDG_STATE_HOME/hypr/sound.json, because that is not a PipeWire setting at
all: it is how far the sliders and the volume keys are allowed to go.

Over-amplification. Past 100 % PipeWire is adding software gain on top of the
device's own maximum: louder, but quiet recordings and laptop-grade speakers
are the only things it helps, and loud ones clip. Off (the default), the
sliders stop at 100 % and osd.py's volume keys use `wpctl -l 1.0`, as before;
on, both go to 150 % (`-l 1.5`). Turning it back off brings anything above
100 % down to 100 %, so nothing is left louder than the sliders can show.

Balance is the louder channel's volume plus how much quieter the other one
is, pactl's own model (pa_cvolume_get_balance): -100 is left only, +100 right
only. Changing the volume here keeps the balance -- every channel is set in
one `pactl set-sink-volume <name> L% R%` call. (A plain `wpctl set-volume`,
which the volume keys use, sets all channels alike and so centres it again;
that is wpctl's behaviour, not something this script can change.)

The level meter reads the input through parec at 16 kHz mono and prints the
peak of each 100 ms block in dB, mapped -60 dB..0 dB to 0..100. Nothing is
written anywhere; the stream is named "Sound settings level meter" so the
"apps using the microphone" list can leave it out.

speech-dispatcher (the screen reader's voice server) keeps a stream open per
voice even when silent; while its PipeWire node is idle it is left out of the
application list (`idle_speech` in the JSON names them) and comes back the
moment it speaks.
"""
import array
import json
import math
import os
import re
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
STATE = os.path.join(STATE_DIR, "sound.json")
THEME_SOUND = os.path.join(HERE, "theme-sound.sh")
METER_NAME = "Sound settings level meter"
NORMAL_LIMIT, BOOST_LIMIT = 1.0, 1.5
FULL = 65536                    # pactl's 100 % (PA_VOLUME_NORM)
METER_RATE, METER_BLOCK_S, METER_FLOOR_DB = 16000, 0.1, -60.0

try:                            # the audio panel's "USB · HDMI" connection hint
    sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
    from audio_panel import kind_of
except Exception:               # noqa: BLE001 -- without the panel there is just no hint
    def kind_of(_name, _desc):
        return ""


# -- the switch this script keeps ------------------------------------------------------
def read_state():
    try:
        with open(STATE) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(data):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = f"{STATE}.tmp.{os.getpid()}"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(tmp, STATE)


def limit():
    """How far volumes may go, as wpctl's -l takes it: 1.0, or 1.5 with
    over-amplification on."""
    return BOOST_LIMIT if read_state().get("boost") else NORMAL_LIMIT


# -- pure helpers (tests/test_settings_sound.py) ----------------------------------------
def percent_of(value):
    """pactl's raw volume (65536 = 100 %) as a whole percent."""
    return round(value * 100 / FULL)


def volume_of(channels):
    """The device's volume: its loudest channel, as pavucontrol shows it.
    channels is pactl's {"front-left": {"value": 36047, ...}, ...}."""
    values = [c.get("value", 0) for c in (channels or {}).values()]
    return percent_of(max(values)) if values else 0


def balance_of(channels):
    """-100..100 from pactl's per-channel volumes, the same formula as
    pa_cvolume_get_balance: how much quieter the weaker side is, signed
    toward the louder one. Channels named neither left nor right (centre,
    LFE, mono) do not count; a mono device is always 0."""
    left = [c.get("value", 0) for n, c in (channels or {}).items() if "left" in n]
    right = [c.get("value", 0) for n, c in (channels or {}).items() if "right" in n]
    if not left or not right:
        return 0
    lv, rv = sum(left) / len(left), sum(right) / len(right)
    if lv == rv:
        return 0
    return round(100 * (rv - lv) / rv) if rv > lv else -round(100 * (lv - rv) / lv)


def channel_volumes(names, volume, balance):
    """The per-channel percents for `pactl set-*-volume`, in names' order:
    the louder side at `volume`, the other scaled down by |balance| %.
    Channels that are neither left nor right stay at `volume`."""
    balance = max(-100, min(100, balance))
    left = volume * (1 - max(balance, 0) / 100)
    right = volume * (1 + min(balance, 0) / 100)
    return [round(left if "left" in n else right if "right" in n else volume, 2) for n in names]


def clamp(percent, cap):
    """A requested percent, kept within 0 .. cap * 100."""
    return max(0, min(round(cap * 100), int(percent)))


def level_percent(samples, floor_db=METER_FLOOR_DB):
    """0..100 for one block of signed 16-bit samples: the peak in dBFS,
    floor_db..0 mapped linearly, the way mixers draw a meter (a linear
    scale would sit at the bottom for anything but shouting)."""
    peak = max((abs(s) for s in samples), default=0)
    if peak <= 0:
        return 0
    db = 20 * math.log10(min(peak, 32768) / 32768)
    return max(0, min(100, round(100 * (db - floor_db) / -floor_db)))


def short_name(props, fallback):
    """node.nick ("USB Audio CODEC") first, like the audio panel, then the
    description."""
    return props.get("node.nick") or props.get("device.description") or fallback


def app_name(props):
    """What a stream should be called: the application's own name, then its
    binary, then PipeWire's node name."""
    return (props.get("application.name") or props.get("application.process.binary")
            or props.get("node.name") or "Unknown application")


def is_bluetooth(name):
    return name.startswith(("bluez_", "bluez5"))


def profile_label(name, desc):
    """Bluetooth profiles in words: A2DP is the high-quality one with no
    microphone, HFP / HSP the headset mode that has a mic and sounds like a
    phone call. Other profiles keep their own description."""
    lowered = name.lower()
    if lowered.startswith("a2dp"):
        codec = re.search(r"codec ([^),]+)", desc)       # "High Fidelity Playback (A2DP Sink, codec AAC)"
        return "High quality (A2DP)" + (f" · {codec.group(1)}" if codec else "")
    if lowered.startswith(("headset", "hfp", "hsp")):
        return "Headset with microphone (HFP)"
    if lowered == "off":
        return "Off"
    return desc or name


def unplugged(dev):
    """A device whose active port says nothing is plugged into that jack;
    WirePlumber will not make it the default (see audio_panel.list_devices)."""
    ports = {p.get("name"): p for p in dev.get("ports") or []}
    port = ports.get(dev.get("active_port"))
    return bool(port) and port.get("availability") == "not available"


def device_entry(dev, default_name):
    props = dev.get("properties") or {}
    name = dev.get("name", "")
    desc = dev.get("description") or name
    channels = dev.get("volume") or {}
    return {
        "index": dev.get("index"),
        "name": name,
        "label": short_name(props, desc),
        "desc": desc,
        "kind": "unplugged" if unplugged(dev) else kind_of(name, desc),
        "volume": volume_of(channels),
        "balance": balance_of(channels),
        "channels": list(channels),
        "mute": bool(dev.get("mute")),
        "default": name == default_name,
        "available": not unplugged(dev),
        "card": props.get("device.name", ""),
        "bluetooth": is_bluetooth(name),
        "port": dev.get("active_port") or "",
        "ports": [{"name": p.get("name"), "desc": p.get("description") or p.get("name"),
                   "available": p.get("availability") != "not available"} for p in dev.get("ports") or []],
    }


def is_idle_speech(props, idle_nodes):
    """speech-dispatcher (the screen reader's voice server) keeps one stream
    per voice open for as long as it runs, silent nearly all the time; while
    its PipeWire node is idle it is not "an application playing" and the
    Applications list leaves it out. It shows up the moment it speaks."""
    name = app_name(props)
    return name.startswith("speech-dispatcher") and str(props.get("object.id", "")) in idle_nodes


def build_status(sinks, sources, inputs, outputs, cards, defaults, state, theme_sounds, idle_nodes=()):
    """The `status --json` document, from pactl's JSON lists (pure, so the
    tests can feed it canned data). idle_nodes: PipeWire ids of the streams
    whose node is idle (only asked for the speech-dispatcher ones)."""
    def label_dupes(devices):
        names = [d["label"] for d in devices]
        for d in devices:
            if names.count(d["label"]) > 1:
                d["label"] = d["desc"]
        devices.sort(key=lambda d: (d["label"].lower(), d["index"]))
        return devices

    out_list = label_dupes([device_entry(s, defaults.get("sink")) for s in sinks or []])
    # Monitors are every output's "what is playing" tap: recordable, but not
    # a microphone, so they are not offered as one (see audio_panel).
    in_list = label_dupes([device_entry(s, defaults.get("source")) for s in sources or []
                           if not s.get("name", "").endswith(".monitor")
                           and (s.get("properties") or {}).get("device.class") != "monitor"])
    by_index = {s["index"]: s for s in out_list}
    apps, quiet = [], []
    for item in inputs or []:
        props = item.get("properties") or {}
        if is_idle_speech(props, idle_nodes):
            quiet.append(app_name(props))
            continue
        sink = by_index.get(item.get("sink"))
        apps.append({
            "index": item.get("index"),
            "name": app_name(props),
            "media": props.get("media.name", ""),
            "icon": props.get("application.icon_name", ""),
            "sink": sink["name"] if sink else "",
            "sink_label": sink["label"] if sink else "",
            "volume": volume_of(item.get("volume")),
            "channels": list(item.get("volume") or {}),
            "mute": bool(item.get("mute")),
            "paused": bool(item.get("corked")),
        })
    apps.sort(key=lambda a: (a["name"].lower(), a["index"]))
    recording = sorted({app_name(o.get("properties") or {}) for o in outputs or []
                        if (o.get("properties") or {}).get("application.name") != METER_NAME
                        # pavucontrol's and the panels' own peak meters
                        and not (o.get("properties") or {}).get("stream.monitor")
                        and (o.get("properties") or {}).get("media.name") != "Peak detect"})
    card_list = []
    for card in cards or []:
        profiles = [{"name": key, "label": profile_label(key, p.get("description", "")),
                     "available": bool(p.get("available", True)), "priority": p.get("priority", 0)}
                    for key, p in (card.get("profiles") or {}).items()]
        props = card.get("properties") or {}
        card_list.append({
            "name": card.get("name", ""),
            "label": props.get("device.description") or props.get("device.nick") or card.get("name", ""),
            "bluetooth": is_bluetooth(card.get("name", "")),
            "active": card.get("active_profile", ""),
            "profiles": profiles,
        })
    card_list.sort(key=lambda c: (not c["bluetooth"], c["label"].lower()))
    boost = bool(state.get("boost"))
    return {"boost": boost, "limit": BOOST_LIMIT if boost else NORMAL_LIMIT,
            "theme_sounds": theme_sounds, "sinks": out_list, "sources": in_list,
            "apps": apps, "idle_speech": sorted(quiet), "recording": recording, "cards": card_list}


# -- talking to pactl ------------------------------------------------------------------
# pactl translates `pactl info`'s "Default Sink:" labels and, in some
# versions, prints the JSON's decimals with the locale's comma ("0,000000",
# which is not JSON); the C locale keeps both parseable whatever LANG is.
PACTL_ENV = {**os.environ, "LC_ALL": "C"}


def pactl(*args, timeout=5):
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout,
                              env=PACTL_ENV)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def pactl_json(*what):
    try:
        data = json.loads(pactl("-f", "json", "list", *what).stdout or "[]")
        return data if isinstance(data, list) else []
    except ValueError:
        return []


def defaults():
    info = pactl("info").stdout
    found = {}
    for line in info.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "Default Sink":
            found["sink"] = value.strip()
        elif key.strip() == "Default Source":
            found["source"] = value.strip()
    return found


def theme_sounds():
    try:
        return subprocess.run([THEME_SOUND, "status"], capture_output=True, text=True,
                              timeout=3).stdout.strip() or "on"
    except (OSError, subprocess.SubprocessError):
        return "on"


def idle_nodes(inputs):
    """The PipeWire ids, among the speech-dispatcher streams, whose node is
    idle right now (`pw-cli info <id>` says state: "idle"). pactl has no
    such field (a silent open stream is not "corked"), and only these few
    are asked, so the page's poll stays cheap."""
    found = set()
    for item in inputs or []:
        props = item.get("properties") or {}
        node = str(props.get("object.id", ""))
        if not node or not app_name(props).startswith("speech-dispatcher"):
            continue
        try:
            info = subprocess.run(["pw-cli", "info", node], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if re.search(r'state: "(idle|suspended)"', info):
            found.add(node)
    return found


def status():
    inputs = pactl_json("sink-inputs")
    return build_status(pactl_json("sinks"), pactl_json("sources"), inputs,
                        pactl_json("source-outputs"), pactl_json("cards"), defaults(), read_state(),
                        theme_sounds(), idle_nodes(inputs))


def find_device(ref):
    """("sink"|"source", pactl's entry) for a name or index, else exits."""
    for kind in ("sink", "source"):
        for dev in pactl_json(kind + "s"):
            if ref in (dev.get("name"), str(dev.get("index"))):
                return kind, dev
    sys.exit(f"sound-settings: no output or input called {ref!r} (see `status`)")


def check(result):
    if result.returncode != 0:
        sys.exit(f"sound-settings: {(result.stderr or result.stdout).strip() or 'pactl failed'}")


def set_volume(ref, percent, cap=None):
    kind, dev = find_device(ref)
    channels = dev.get("volume") or {}
    names = list(channels) or ["mono"]
    level = clamp(percent, limit() if cap is None else cap)
    per = channel_volumes(names, level, balance_of(channels))
    check(pactl(f"set-{kind}-volume", dev["name"], *[f"{v}%" for v in per]))


def set_balance(ref, balance):
    kind, dev = find_device(ref)
    channels = dev.get("volume") or {}
    per = channel_volumes(list(channels), volume_of(channels), int(balance))
    check(pactl(f"set-{kind}-volume", dev["name"], *[f"{v}%" for v in per]))


def flag(value):
    return {"on": "1", "off": "0", "toggle": "toggle", "1": "1", "0": "0"}.get(value) or sys.exit(
        "sound-settings: on, off or toggle")


def set_boost(on):
    state = read_state()
    state["boost"] = bool(on)
    write_state(state)
    if not on:                  # nothing left louder than the sliders can show
        for kind in ("sink", "source"):
            for dev in pactl_json(kind + "s"):
                if volume_of(dev.get("volume")) > 100 and not dev.get("name", "").endswith(".monitor"):
                    set_volume(dev["name"], 100, NORMAL_LIMIT)
        for item in pactl_json("sink-inputs"):
            if volume_of(item.get("volume")) > 100:
                pactl("set-sink-input-volume", str(item["index"]), "100%")


def meter(source, seconds):
    """Print the level ten times a second for `seconds` (0: until killed)."""
    block = int(METER_RATE * METER_BLOCK_S) * 2
    try:
        proc = subprocess.Popen(["parec", "-d", source, "--raw", "--format=s16le", "--channels=1",
                                 f"--rate={METER_RATE}", "--latency-msec=50", f"--client-name={METER_NAME}",
                                 f"--stream-name={METER_NAME}",
                                 f"--property=application.name={METER_NAME}"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        sys.exit(f"sound-settings: {exc}")
    # The page stops the meter with SIGTERM: leave through `finally`, so
    # parec goes too instead of waiting for its next write to fail.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    blocks = 0
    try:
        while not seconds or blocks < seconds / METER_BLOCK_S:
            data = proc.stdout.read(block)
            if not data:
                break
            samples = array.array("h")
            samples.frombytes(data[:len(data) - len(data) % 2])
            if sys.byteorder == "big":
                samples.byteswap()
            print(level_percent(samples), flush=True)
            blocks += 1
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        proc.kill()
        proc.wait()


def print_text(data):
    for title, key in (("Outputs", "sinks"), ("Inputs", "sources")):
        print(f"{title}:")
        for d in data[key]:
            mark = "*" if d["default"] else " "
            extra = f"  balance {d['balance']:+d}" if d["balance"] else ""
            print(f" {mark} {d['label']:<28} {d['volume']:>3} %{' muted' if d['mute'] else ''}{extra}"
                  f"  [{d['name']}]")
    print("Applications:")
    for a in data["apps"]:
        print(f"   {a['name']:<28} {a['volume']:>3} %{' muted' if a['mute'] else ''}  on {a['sink_label']}"
              f"  [{a['index']}]")
    if data.get("idle_speech"):
        print(f"   (not listed: {len(data['idle_speech'])} idle speech-dispatcher voice(s))")
    if data["recording"]:
        print("Using the microphone: " + ", ".join(data["recording"]))
    print(f"Over-amplification: {'on (150 %)' if data['boost'] else 'off (100 %)'}  ·  "
          f"theme sounds: {data['theme_sounds']}")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]
    if cmd == "status":
        data = status()
        print(json.dumps(data, indent=1)) if "--json" in rest else print_text(data)
    elif cmd == "limit":
        print(limit())
    elif cmd == "default" and len(rest) == 1:
        kind, dev = find_device(rest[0])
        check(pactl(f"set-default-{kind}", dev["name"]))
    elif cmd == "volume" and len(rest) == 2:
        set_volume(rest[0], int(float(rest[1].rstrip("%"))))
    elif cmd == "mute" and len(rest) == 2:
        kind, dev = find_device(rest[0])
        check(pactl(f"set-{kind}-mute", dev["name"], flag(rest[1])))
    elif cmd == "balance" and len(rest) == 2:
        set_balance(rest[0], int(float(rest[1])))
    elif cmd == "port" and len(rest) == 2:
        kind, dev = find_device(rest[0])
        check(pactl(f"set-{kind}-port", dev["name"], rest[1]))
    elif cmd == "app" and len(rest) == 3 and rest[0] in ("volume", "mute", "move"):
        what, index, value = rest
        if what == "volume":
            check(pactl("set-sink-input-volume", index, f"{clamp(float(value.rstrip('%')), limit())}%"))
        elif what == "mute":
            check(pactl("set-sink-input-mute", index, flag(value)))
        else:
            _kind, dev = find_device(value)
            check(pactl("move-sink-input", index, dev["name"]))
    elif cmd == "profile" and len(rest) == 2:
        check(pactl("set-card-profile", rest[0], rest[1]))
    elif cmd == "boost" and len(rest) == 1 and rest[0] in ("on", "off", "status"):
        if rest[0] == "status":
            print("on" if read_state().get("boost") else "off")
        else:
            set_boost(rest[0] == "on")
    elif cmd == "meter" and 1 <= len(rest) <= 2:
        meter(rest[0], float(rest[1]) if len(rest) == 2 else 0)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except ValueError:          # "volume <device> loud": a usage error, not a traceback
        sys.exit("sound-settings: percents, balance and seconds are numbers (see --help)")
