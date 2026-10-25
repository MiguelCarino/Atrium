#!/usr/bin/env python3
"""Render each desktop theme's sounds: ~/.config/themes/<name>/sounds/
notify.wav (a notification arrives), switch.wav (the theme comes on) and
alarm.wav (a timer / alarm ringing: timers.py loops it), plus the one sound
that is the same in every theme on purpose -- ~/.config/hypr/sounds/
quake-alarm.wav, the earthquake alert (quake-alert.py loops it).
Synthesised here from sine / square / triangle tones (and, for lofi, a
small FM electric piano with synthetic tape wobble and vinyl crackle), so
every sound is our own -- none is sampled from the operating systems the
themes look like, or from any record. luna's are bright XP-era chimes in
the same spirit, written here as new phrases (a fifth, a rolled F major
chord, a four-note loop), not a transcription of any Windows sound.
orbit's are Quindar-style tones -- the pure 2525 / 2475 Hz beeps that keyed
radio links on and off in the 1960s, a generic technique, not a recording --
plus a soft two-tone caution chime. seasons' are a kalimba (thumb piano):
a sine tine with one quiet inharmonic 'tink' at 5.4x that fades fast and a
3 ms attack -- wood and metal, outdoorsy, soft. One set serves all four
seasons (theme-sound.sh and timers.py read themes/seasons/sounds/ directly).
Its notes come from D major pentatonic, all at or below B4 (71), and the
pairs are told apart from moe (67/72), lofi (64/71), luna (65/72) and aero
(64/68): notify is D4 -> A4 (62/69).

    make-theme-sounds.py            render every theme that has a recipe
    make-theme-sounds.py <name>...  only these

theme-sound.sh plays them (mako's on-notify, theme.py set).
"""
import os
import sys
import wave

import numpy as np

RATE = 44100
THEMES = os.path.expanduser("~/.config/themes")
PEAK = 0.22                 # about -13 dBFS: a desktop chime, quieter than speech


def t(seconds):
    return np.arange(int(RATE * seconds)) / RATE


def env(n, attack=0.005, decay=6.0):
    """Fast attack, exponential decay; `decay` per second."""
    x = np.arange(n) / RATE
    return np.minimum(1, x / attack) * np.exp(-decay * x)


def sine(f, dur, decay=6.0, attack=0.005):
    x = t(dur)
    return np.sin(2 * np.pi * f * x) * env(len(x), attack, decay)


def bell(f, dur, decay=4.0):
    """A sine with a few inharmonic partials: glassy."""
    out = sum(a * sine(f * r, dur, decay * d) for r, a, d in
              ((1, 1, 1), (2.76, 0.35, 1.6), (5.4, 0.12, 2.4), (8.93, 0.05, 3)))
    return out


def square(f, dur, decay=8.0, duty=0.5):
    x = t(dur)
    return np.where((x * f) % 1 < duty, 1.0, -1.0) * env(len(x), 0.002, decay) * 0.35


def triangle(f, dur, decay=7.0):
    x = t(dur)
    return (2 * np.abs(2 * ((x * f) % 1) - 1) - 1) * env(len(x), 0.003, decay)


def sweep(f0, f1, dur, decay=5.0, wave_fn=np.sin):
    x = t(dur)
    f = f0 * (f1 / f0) ** (x / dur)
    phase = 2 * np.pi * np.cumsum(f) / RATE
    return wave_fn(phase) * env(len(x), 0.003, decay)


def seq(*parts):
    """(start seconds, samples) pairs mixed onto one track."""
    end = max(int(s * RATE) + len(p) for s, p in parts)
    out = np.zeros(end)
    for s, p in parts:
        i = int(s * RATE)
        out[i:i + len(p)] += p
    return out


def echo(x, delay=0.11, gain=0.3, times=3):
    out = np.concatenate([x, np.zeros(int(delay * RATE * times))])
    for k in range(1, times + 1):
        i = int(delay * RATE * k)
        out[i:i + len(x)] += x * gain ** k
    return out


def crush(x, bits=6):
    q = 2 ** (bits - 1)
    return np.round(x * q) / q


def note(n):
    """MIDI note -> Hz."""
    return 440 * 2 ** ((n - 69) / 12)


# Kept low and soft on purpose: every note is at or below C5 (523 Hz), the
# tones are sines and triangles (no square waves, no bit-crushing -- both are
# made of high harmonics), attacks are gentle, and write() rolls everything
# off above ~2 kHz. A notification should be noticed, not felt in the teeth.
RECIPES = {
    # neon synth: a slow low glide, then a soft triangle note
    "cyberpunk": {
        "notify": lambda: seq((0, 0.6 * sweep(196, 262, 0.18, 9)),
                              (0.12, triangle(note(57), 0.45, 6))),
        "switch": lambda: echo(seq(*[(i * 0.1, 0.8 * triangle(note(n), 0.6, 5))
                                     for i, n in enumerate((45, 52, 57, 64))]), 0.16, 0.3),
        "alarm": lambda: seq(*[(i * 0.22, 0.9 * triangle(note(n), 0.3, 5)) for i, n in enumerate((57, 64, 57, 64))]),
    },
    # digital rain: two muted drops, falling
    "matrix": {
        "notify": lambda: seq(*[(i * 0.09, sine(note(n), 0.3, 12, 0.008)) for i, n in enumerate((64, 57))]),
        "switch": lambda: echo(seq(*[(i * 0.07, sine(note(n), 0.25, 11, 0.008))
                                     for i, n in enumerate((67, 64, 60, 57, 52))]), 0.12, 0.3),
        "alarm": lambda: seq(*[(i * 0.2, sine(note(n), 0.28, 6, 0.01)) for i, n in enumerate((64, 60, 64, 60))]),
    },
    # glass: a soft low bell and its third
    "aero": {
        "notify": lambda: echo(seq((0, soft_bell(note(64), 1.0, 4)), (0.12, 0.7 * soft_bell(note(68), 1.0, 4))),
                               0.16, 0.2),
        "switch": lambda: echo(seq(*[(i * 0.12, (0.9 - i * 0.12) * soft_bell(note(n), 1.3, 3))
                                     for i, n in enumerate((57, 61, 64, 69))]), 0.18, 0.25),
        "alarm": lambda: seq(*[(i * 0.3, soft_bell(note(n), 0.6, 4)) for i, n in enumerate((64, 69, 64, 69))]),
    },
    # beige box: one warm "dong", and a slow low chord to start up
    "win95": {
        "notify": lambda: soft_bell(note(60), 0.8, 5),
        "switch": lambda: seq(*[(i * 0.16, 0.6 * (sine(note(n), 1.6, 1.8, 0.04) + 0.2 * sine(note(n) * 2, 1.6, 3, 0.04)))
                                for i, n in enumerate((48, 55, 60, 64))]),
        "alarm": lambda: seq(*[(i * 0.3, soft_bell(note(n), 0.5, 5)) for i, n in enumerate((60, 60, 67, 60))]),
    },
    # kirakira, grown down: two soft triangle notes a fourth apart
    "moe": {
        "notify": lambda: seq(*[(i * 0.08, 0.8 * triangle(note(n), 0.4, 7)) for i, n in enumerate((67, 72))]),
        "switch": lambda: echo(seq(*[(i * 0.08, 0.7 * triangle(note(n), 0.5, 6))
                                     for i, n in enumerate((60, 64, 67, 72))]), 0.14, 0.25),
        "alarm": lambda: seq(*[(i * 0.2, 0.8 * triangle(note(n), 0.3, 6)) for i, n in enumerate((67, 72, 67, 72))]),
    },
    # a warm Rhodes in a dusty room: soft electric piano, a little tape wobble,
    # vinyl crackle. notify: E4 then B4. switch: a rolled Fmaj9. alarm: Dm9
    # then G13, with both ends quiet so timers.py loops it without a seam.
    # Every note is at or below B4 (71); the FM bark is a fast-fading partial.
    "lofi": {
        "notify": lambda: seq((0, wobble(seq((0, 0.9 * rhodes(note(64), 1.3, 3.0)),
                                              (0.11, 0.7 * rhodes(note(71), 1.2, 3.2))))),
                              (0, crackle(1.45, seed=3))),
        "switch": lambda: seq((0, wobble(echo(seq(*[(i * 0.075, (0.75 - i * 0.08) * rhodes(note(n), 2.0, 1.8))
                                                    for i, n in enumerate((53, 57, 60, 64, 67))]), 0.23, 0.22, 2))),
                              (0, crackle(2.6, seed=5))),
        "alarm": lambda: seq((0, wobble(seq((0, strum((50, 57, 62, 65, 69), 1.0, bark=1.4)),
                                             (0.9, strum((55, 59, 64, 69), 1.0, bark=1.4))))),
                             (0, crackle(1.95, rate=5, seed=7))),
    },
    # bright XP-era chime, our own: a bell rising a fifth (F4 -> C5; moe's
    # pair is 67/72 and lofi's 64/71, so this one is told apart by ear); a
    # low F pad under a rolled F major arpeggio for the theme coming on; a
    # four-note chime (C5 G4 A4 C5) that starts and ends on the same note,
    # so timers.py loops it clean. Every note at or below C5 (72).
    "luna": {
        "notify": lambda: echo(seq((0, 0.9 * bell(note(65), 0.9, 4.5)),
                                   (0.11, 0.8 * bell(note(72), 1.1, 4.0))), 0.14, 0.18),
        "switch": lambda: echo(seq((0, 0.35 * sum(sine(note(n), 2.4, 1.2, 0.25) for n in (41, 48, 53, 57))),
                                   *[(0.08 + i * 0.11, (0.8 - i * 0.08) * bell(note(n), 1.6, 2.8))
                                     for i, n in enumerate((53, 60, 65, 69, 72))]), 0.2, 0.22, 2),
        "alarm": lambda: seq(*[(i * 0.25, 0.9 * bell(note(n), 0.45, 6)) for i, n in enumerate((72, 67, 69, 72))]),
    },
    # mission control's radio: Quindar-style tones. notify: one 250 ms beep
    # at 2525 Hz (the "intro" tone). switch: the intro, a breath, then the
    # 2475 Hz "outro" -- the pair that opened and closed a transmission.
    # alarm: a two-tone caution chime, G5 -> C5 (784 / 523 Hz), twice, quiet
    # at both ends so timers.py loops it clean. These are the only theme
    # sounds above C5, so they get their own rules (THEME_WRITE below): a
    # 5 kHz low-pass instead of 2 kHz (which would take a 2.5 kHz tone down
    # by ~8 dB and dull it to a whistle), pure sines with 25 ms raised-cosine
    # edges (no click, nothing above the tone itself), and a lower peak --
    # the ear is most sensitive around 2.5 kHz, so the beeps sit at about
    # -19 dBFS against the other themes' -13.
    "orbit": {
        "notify": lambda: quindar(2525, 0.25),
        "switch": lambda: seq((0, quindar(2525, 0.25)), (0.55, quindar(2475, 0.25))),
        "alarm": lambda: seq(*[(i * 0.42, 0.9 * soft_bell(note(n), 0.5, 5.5))
                               for i, n in enumerate((79, 72, 79, 72))]),
    },
    # a kalimba under a tree: notify D4 then A4 (62, 69) with a short echo;
    # switch a rising D-major pentatonic roll D4 E4 F#4 A4 B4, each softer,
    # like a wind chime; alarm A4 F#4 A4 D4, its first note softer and its
    # last let ring out, so timers.py loops it without a seam. Every note at
    # or below B4 (71): write()'s defaults hold, no THEME_WRITE entry.
    "seasons": {
        "notify": lambda: echo(seq((0, 0.9 * kalimba(note(62), 0.9)),
                                   (0.12, 0.8 * kalimba(note(69), 1.0))), 0.14, 0.18),
        "switch": lambda: echo(seq(*[(i * 0.09, (0.85 - i * 0.1) * kalimba(note(n), 1.2, 2.8))
                                     for i, n in enumerate((62, 64, 66, 69, 71))]), 0.2, 0.22, 2),
        "alarm": lambda: seq(*[(i * 0.25, a * kalimba(note(n), 0.5, 4.5))
                               for i, (n, a) in enumerate(((69, 0.6), (66, 0.9), (69, 0.9), (62, 0.8)))]),
    },
}

# Per-theme overrides for write(): the low-pass cutoff (Hz) and the peak.
# Every other theme keeps write()'s defaults (2 kHz, PEAK), so their files
# render exactly as before.
THEME_WRITE = {
    "orbit": {"cutoff": 5000.0, "peak": 0.11},
}


def quindar(f, dur=0.25, edge=0.025):
    """A Quindar-style tone: a steady pure sine with raised-cosine fade-in
    and fade-out (edge seconds each), so it starts and stops soft."""
    x = t(dur)
    shape = np.ones(len(x))
    k = int(edge * RATE)
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, k))
    shape[:k] = ramp
    shape[-k:] = ramp[::-1]
    return np.sin(2 * np.pi * f * x) * shape


def soft_bell(f, dur, decay=4.0):
    """bell() without its glassy high partials: the fundamental and a quiet
    octave -- round, not piercing."""
    return sine(f, dur, decay, 0.01) + 0.25 * sine(f * 2, dur, decay * 1.8, 0.01)


def kalimba(f, dur, decay=3.2):
    """A thumb piano: the tine's fundamental, a quiet inharmonic overtone at
    5.4x that fades fast (the metallic 'tink', mostly under write()'s 2 kHz
    low-pass), and a 3 ms attack -- woody, not a bell."""
    return sine(f, dur, decay, 0.003) + 0.16 * sine(f * 5.4, dur, decay * 3.5, 0.002)


# -- lofi: a Rhodes in a dusty room ---------------------------------------------
# The lambdas in RECIPES look these up when they are CALLED, so they can live
# down here beside soft_bell().
def rhodes(f, dur, decay=2.6, bark=1.1):
    """Electric piano: 1:1 FM 'tine bark' that fades fast, quiet 2nd harmonic,
    8 ms attack, 4.2 Hz tremolo."""
    x = t(dur)
    tone = np.sin(2 * np.pi * f * x + bark * np.exp(-9 * x) * np.sin(2 * np.pi * f * x))
    tone += 0.18 * np.sin(4 * np.pi * f * x) * np.exp(-6 * x)
    return tone * env(len(x), 0.008, decay) * (1 + 0.10 * np.sin(2 * np.pi * 4.2 * x))


def wobble(x, rate=0.6, depth=0.0025, flutter=0.0006):
    """Tape wow (0.6 Hz, ~4 cents) and flutter (7.5 Hz): time-warp resample."""
    n = np.arange(len(x))
    s = n / RATE
    warp = n + RATE * (depth / (2 * np.pi * rate)) * np.sin(2 * np.pi * rate * s) \
             + RATE * (flutter / (2 * np.pi * 7.5)) * np.sin(2 * np.pi * 7.5 * s)
    return np.interp(warp, n, x, right=0.0)


def crackle(dur, rate=7.0, gain=0.035, seed=1):
    """Vinyl: sparse decaying ticks plus a whisper of smoothed hiss. Seeded,
    so a render is the same every time."""
    rng = np.random.default_rng(seed)
    n = int(RATE * dur)
    out = np.zeros(n)
    for i in rng.integers(0, n, int(rate * dur)):
        k = np.arange(min(90, n - i))
        out[i:i + len(k)] += rng.uniform(0.3, 1) * rng.choice((-1, 1)) * np.exp(-k / 12)
    hiss = np.convolve(rng.standard_normal(n), np.ones(8) / 8, "same")
    return gain * (out + 0.15 * hiss)


def strum(notes, dur, gap=0.03, decay=2.4, bark=1.1):
    """A chord rolled upwards, each note a little later and a little softer."""
    return seq(*[(i * gap, (0.8 - 0.06 * i) * rhodes(note(m), dur, decay, bark)) for i, m in enumerate(notes)])


def lowpass(x, cutoff=2000.0):
    """One-pole low-pass, twice (12 dB/octave): takes the edge off."""
    a = np.exp(-2 * np.pi * cutoff / RATE)
    for _ in range(2):
        y = np.empty_like(x)
        acc = 0.0
        for i, v in enumerate(x):
            acc = (1 - a) * v + a * acc
            y[i] = acc
        x = y
    return x


def write(path, x, peak=PEAK, cutoff=2000.0):
    x = lowpass(x, cutoff)
    x = x / max(1e-9, np.abs(x).max()) * peak
    fade = min(len(x), int(0.02 * RATE))
    x[-fade:] *= np.linspace(1, 0, fade)            # no click at the end
    data = (x * 32767).astype("<i2")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(data.tobytes())


QUAKE_SOUND = os.path.expanduser("~/.config/hypr/sounds/quake-alarm.wav")


def quake_alarm():
    """Meant to cut through, not to hurt: a low two-tone (A4 / D5, 440 and
    587 Hz) pulse with a strong rhythm, like a siren an octave down, rounded
    by the low-pass. Distinct from every theme sound, so it is never taken
    for a timer. One second; quake-alert.py loops it."""
    tone = lambda f, d: (sine(f, d, 1.5, 0.02) + 0.35 * triangle(f, d, 1.5)) * np.hanning(int(RATE * d))
    return seq((0, tone(440, 0.45)), (0.5, tone(587, 0.45)))


def main(names):
    for name in names or sorted(RECIPES):
        if name not in RECIPES:
            sys.exit(f"make-theme-sounds: no recipe for {name!r} ({', '.join(RECIPES)})")
        if not os.path.isdir(os.path.join(THEMES, name)):
            continue
        for event, make in RECIPES[name].items():
            path = os.path.join(THEMES, name, "sounds", f"{event}.wav")
            write(path, make(), **THEME_WRITE.get(name, {}))
            print(path)
    if not names:
        x = quake_alarm()
        write(QUAKE_SOUND, x, peak=0.6)     # an emergency: louder than the chimes
        print(QUAKE_SOUND)


if __name__ == "__main__":
    main(sys.argv[1:])
