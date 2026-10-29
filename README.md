# Atrium

A complete desktop on [Hyprland](https://hyprland.org) for Fedora: the bar,
the panels, notifications, a launcher, a Settings app for every part of it,
desktop themes that restyle everything at once, and a set of local, private
smart features (an assistant, voice typing, spoken replies, background tasks,
a nightly health checkup and more). Nothing leaves the machine unless you
turn on a feature that says it does.

Made for Fedora 44 or newer (Hyprland 0.56, Lua config).

## Requirements

| | Needed | Notes |
|---|---|---|
| System | Fedora 44 or newer, a user that may use `sudo` | rpmfusion (free + nonfree) is enabled by `install.sh` |
| Disk | about 6 GB | packages ~3 GB, the themes' wallpapers and sounds ~1 GB, the build tools; the optional smart extras 2-5 GB more; local models 2-20 GB each |
| RAM | 8 GB; 16 GB or more for local AI models | |
| Graphics | any card Hyprland runs on: NVIDIA, AMD or Intel | `install.sh` installs only what your card needs: the NVIDIA driver (`akmod-nvidia`) on NVIDIA, VA-API video encoding on AMD and Intel |
| Graphics memory | 2-5 GB free for small local models, 8 GB or more for the bigger ones | only for local AI; without a card of its own, models run on the CPU, slowly |
| Optional | a webcam (presence, gestures), a microphone (voice typing, voice commands), a phone with [KDE Connect](https://kdeconnect.kde.org) (phone handoff) | each feature stays off until you turn it on |

What works less well without some of it:

- **No graphics card of its own** (or the NVIDIA card on nouveau): screen
  recording and instant replay encode on the CPU (x264, 30 fps); the bar's GPU
  pill is hidden and Railguard does not watch graphics memory; local models
  and voice typing run on the CPU.
- **No [LM Studio](https://lmstudio.ai)**: the assistant, voice commands,
  asking about the screen and the written summaries (daily brief, journal)
  have no model to ask and say so. Everything else -- the desktop, themes,
  voice typing, spoken replies, the camera features, recording, Railguard --
  works without it.

## Install

```sh
git clone https://github.com/MiguelCarino/Atrium ~/Atrium
~/Atrium/install.sh            # asks before each optional step
~/Atrium/install.sh --dry-run  # only print the steps
```

It installs the packages, copies the desktop into `~/.config` (anything of
yours it would replace is copied to `~/.local/share/atrium/backup-<date>/`
first), asks where your projects live, builds the plugins, icons, wallpapers
and sounds, and turns on the services. Then log out and pick
**Hyprland (uwsm-managed)** at the login screen. The first login opens a
short welcome: pick a theme, check the screens and the microphone, turn the
smart features on or off (`~/.config/hypr/scripts/welcome.py` shows it again).

To undo it, `~/Atrium/uninstall.sh --dry-run` shows what it would put back:
it restores the backups above (each path from the oldest backup, the copy
made before Atrium first touched it), moves Atrium's files aside rather than
deleting them, and leaves the packages installed.

First steps after logging in:

| | |
|---|---|
| **SUPER+I** | Settings: every page, searchable |
| **SUPER+CTRL+I** | Settings > Smart desktop: every smart feature, and what may use your camera, microphone, screen and clipboard |
| **SUPER+F1** | every shortcut |
| `~/.config/hypr/scripts/monitors-capture.py` | once your screens are arranged (Settings > Displays): remembers them for this machine |

The smart features that hear, speak or see need models (2-5 GB):
`extras/setup-extras.sh` (install.sh offers it). The ones that use the camera
ship **off**. Local language models run in [LM Studio](https://lmstudio.ai);
pick them in Settings > AI & models, which shows which ones fit your card's
memory (any vendor) next to what is already on it.

## What is where

| Path | What |
|---|---|
| `home/.config/hypr/` | Hyprland (Lua config: `hyprland.lua` is the index, `lua/` one module per concern), hypridle, hyprlock, the scripts, the Settings app (`scripts/settings.py`, `scripts/settings_pages/`), the tests |
| `home/.config/waybar/` | the bar, its pills and panels |
| `home/.config/themes/` | desktop themes (`scripts/theme.py`) |
| `home/.config/{mako,wofi,uwsm,autostart,systemd/user,qt5ct,qt6ct}` | notifications, launcher, session, services, Qt colours |
| `packages/` | Fedora packages, repositories, the services install.sh enables |
| `system/` | the root-side pieces (cpu-power, railguard's SysRq keys) |
| `install.sh`, `uninstall.sh` | set it up; put back what it replaced |
| `extras/` | the smart features' models |

## Yours, not the desktop's

Some files belong to one person and are never in this repo; keep them in your
own dotfiles:

| File | What |
|---|---|
| `~/.config/hypr/lua/hosts/<hostname>.lua` | this machine's screens (`monitors-capture.py` writes it) |
| `~/.config/hypr/desktop.conf` | your folders: projects, dotfiles repo |
| `~/.config/hypr/contexts.json` | your project contexts |
| `~/.config/hypr/workhours.conf` | work hours, an optional feature that is off until you set it up (Settings > Timers & alarms): a bar badge with the time left in your working day, and a git hook that keeps work time and your own projects apart |
| `~/.config/hypr/region.conf`, `emergency.conf` | your weather place and where alerts are for (both start from your time zone's city) |
| `~/.config/hypr/folder-access.json` | the folders you let the AI features read |
| `~/Pictures/Wallpapers/` | your wallpapers |

## Tests

```sh
~/.config/hypr/tests/run.sh
```

## Maintainers

`./sync.sh` copies a running install back into the repo, leaving the
personal files above out and refusing to stage anything that still contains
your home path, your git name or email, or a word from `.personal-words`
(not committed). `./sync.sh --commit` also runs the tests, commits and pushes.

## Licence

Atrium is free software under the GNU General Public License, version 3 or
(at your option) any later version: see `LICENSE`.

Not covered by that licence, and kept under their own:

- the fonts in `home/.local/share/fonts/` (SIL Open Font License and others;
  each folder has its licence file next to the fonts)
- `home/.config/hypr/scripts/hyprview.patch`, a change to
  [hyprview](https://github.com/yz778/hyprview) (MIT)

The cube plugin, [hypr-cube](https://github.com/dmty/hypr-cube), is built
from its upstream source as it is: it has no licence yet, so Atrium's local
changes to it (per-monitor faces, floating windows in front of the cube, live
video on the faces, spinning straight to a workspace) are not published here.
