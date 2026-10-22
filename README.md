# Atrium

A complete desktop on [Hyprland](https://hyprland.org) for Fedora: the bar,
the panels, notifications, a launcher, a Settings app for every part of it,
desktop themes that restyle everything at once, and a set of local, private
smart features (an assistant, voice typing, spoken replies, background tasks,
a nightly health checkup and more). Nothing leaves the machine unless you
turn on a feature that says it does.

Made for Fedora 44 or newer (Hyprland 0.56, Lua config).

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
**Hyprland (uwsm-managed)** at the login screen.

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
pick them in Settings > AI & models.

## What is where

| Path | What |
|---|---|
| `home/.config/hypr/` | Hyprland (Lua config: `hyprland.lua` is the index, `lua/` one module per concern), hypridle, hyprlock, the scripts, the Settings app (`scripts/settings.py`, `scripts/settings_pages/`), the tests |
| `home/.config/waybar/` | the bar, its pills and panels |
| `home/.config/themes/` | desktop themes (`scripts/theme.py`) |
| `home/.config/{mako,wofi,uwsm,autostart,systemd/user,qt5ct,qt6ct}` | notifications, launcher, session, services, Qt colours |
| `packages/` | Fedora packages, repositories, the services install.sh enables |
| `system/` | the root-side pieces (cpu-power) |
| `extras/` | the smart features' models |

## Yours, not the desktop's

Some files belong to one person and are never in this repo; keep them in your
own dotfiles:

| File | What |
|---|---|
| `~/.config/hypr/lua/hosts/<hostname>.lua` | this machine's screens (`monitors-capture.py` writes it) |
| `~/.config/hypr/desktop.conf` | your folders: projects, dotfiles repo |
| `~/.config/hypr/contexts.json` | your project contexts |
| `~/.config/hypr/workhours.conf` | your work hours, if you use them |
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
