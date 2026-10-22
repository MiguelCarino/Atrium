#!/usr/bin/env python3
"""Render each desktop theme's sounds: ~/.config/themes/<name>/sounds/
notify.wav (a notification arrives), switch.wav (the theme comes on) and
alarm.wav (a timer / alarm ringing: timers.py loops it), plus the one sound
that is the same in every theme on purpose -- ~/.config/hypr/sounds/
quake-alarm.wav, the earthquake alert (quake-alert.py loops it).
Synthesised here from sine / square / triangle tones, so every sound is our
own -- none is sampled from the operating systems the themes look like.

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
}


def soft_bell(f, dur, decay=4.0):
    """bell() without its glassy high partials: the fundamental and a quiet
    octave -- round, not piercing."""
    return sine(f, dur, decay, 0.01) + 0.25 * sine(f * 2, dur, decay * 1.8, 0.01)


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


def write(path, x, peak=PEAK):
    x = lowpass(x)
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
            write(path, make())
            print(path)
    if not names:
        x = quake_alarm()
        write(QUAKE_SOUND, x, peak=0.6)     # an emergency: louder than the chimes
        print(QUAKE_SOUND)


if __name__ == "__main__":
    main(sys.argv[1:])
