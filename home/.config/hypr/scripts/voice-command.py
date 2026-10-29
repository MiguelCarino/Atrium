#!/usr/bin/env python3
"""Voice commands: say what you want the desktop to do, in Spanish or
English -- "move Firefox to workspace 3", "pon la terminal y el navegador
lado a lado", "no molestar durante una hora", "timer 10 minutes for the
tea" -- and it is done, after it says what it understood.

    voice-command.py run FILE [--lang es|en] [--replace ID]
                            what voice.py's daemon runs after a command
                            recording: FILE holds the transcript (tmpfs, read
                            and deleted at once), ID the notification to
                            replace
    voice-command.py text "WORDS" [--lang es|en]
                            the same for typed words (no microphone)
    voice-command.py plan "WORDS" [--json]
                            only what it would do: understood, checked,
                            nothing run (Settings > Voice's "Show the plan")
    voice-command.py catalog [--json]   the actions it can do

THE KEY is voice.py's: `voice.py command` (start, again stop) or `voice.py
command-ptt start|stop` (hold to talk). The daemon records and transcribes
exactly as for dictation, then hands the words here in a transient unit
(systemd-run, SyslogIdentifier=voice-command), so the journal has every
command: journalctl --user -t voice-command.

FROM WORDS TO ACTIONS, in this order:

  1. fast_parse(): a handful of whole short sentences ("pause", "siguiente
     canción", "pantalla completa", "close this window", "workspace 3") are
     matched here, without a model -- instant, and still possible while the
     card is full.
  2. the local "quick" model (llm-worker.py's ready("quick") / ask(), a JSON
     schema as the response format) maps the sentence to ONE TO SIX actions
     from CATALOG -- nothing else exists for it. When the quick model would
     not fit on the card but the big "default" one is loaded already, that
     one answers instead (it is there; nothing is loaded or unloaded for
     it). Local only: no cloud model is ever asked; when no local model can
     run, the command is refused saying why.
  3. plan(): every action the model named is CHECKED here against the world
     as it is -- the theme exists, the session / project exists, the app is
     installed, the window is open, the folder exists and is not a secret
     one, the URL is http(s), the duration is sane -- and becomes a step:
     what to say, what to run (argv lists and fixed Lua, never a shell, never
     a command line the model wrote), and whether it needs a yes. What fails
     a check is refused with the reason. An action not in CATALOG -- the
     automations' "shell" and raw "open" are deliberately not in it -- is
     refused, whatever the model says.

ASKING FIRST. A notification always says what was heard and the plan. Safe
steps run at once, and when they can be taken back cheaply the bubble has an
Undo button for UNDO_S. These ask first (Confirm / Cancel, CONFIRM_S, no
answer is Cancel): closing anything but the focused window you can see,
moving or closing several windows, overwriting a saved session, the sound
profile, an app name that matches several apps, anything the model was not
sure of, a sentence of which part was refused -- and everything when
"confirm everything" is on (Settings > Voice).

REUSED, not copied: automations.py's action catalog, value checks and
executor (theme, dnd, gamemode, sound-output / -profile, nightlight, notify,
session, context, digest, brief, journal; launching an app is its "open" with
a desktop id this resolved -- never words); sessions.py's Lua helpers;
timers.py for timers, reminders and alarms; ask-desktop.py --notify for
"search my desktop" (Settings > Privacy decides what it may read);
default-apps.py for the browser / terminal / files / editor and for folders
and links; closed-windows.py reopen as the Undo of a close; playerctl and
wpctl for media and volume. Window ops are `hyprctl eval` with the Lua
dispatchers (hl.dsp.window.move / fullscreen / close, hl.dsp.focus), the
same guard as ALT+C for a close: only a window on a workspace you can see.
"Go to workspace N" does what ALT+N does (an empty one homed on another
screen is pulled to this one), and N is one of the workspaces with a rule
(1-6 here). The Undo of a close reopens only what closed-windows.py really
kept from it (not a dialog, a second window, one that asked "close?"), so it
never brings back some older window instead.

Privacy: the transcript is only ever in memory, the tmpfs hand-off file and
the journal line. Window titles go to nobody -- the model gets app classes
only, the journal app names only -- and a private window (privacy.conf's private apps, KeePassXC,
private-browsing titles) is named by its app, never its title, in the
notification and the journal.

Settings (voice.conf through voice.py set): commands on|off, command_confirm
on|off (everything asks), command_language auto|es|en (what Whisper is told
to hear; auto = it decides, and the replies follow what it heard).

ANSWERING BY VOICE (speak_back()): with Settings > Speech's "voice commands
answer by voice" on (tts.py's speak_commands, off as shipped) the outcome is
also said, in the command's language, by tts.py's local voice -- what will
be asked ("Do this? …"), done, refused or cancelled. tts.py keeps quiet in
gamemode, Do Not Disturb and the quiet hours; the bubble says it anyway.
"""
import datetime
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
HOME = os.path.expanduser("~")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desktop_conf  # noqa: E402
import desk_common  # noqa: E402  (hypr_request: hyprctl over the socket)

PROJECTS = desktop_conf.projects_dir()      # your projects folder (desktop.conf)
DND_UNIT = "voice-dnd-off"           # the transient timer that ends a "DND for an hour"

MAX_ACTIONS = 6                      # automations.py's MAX_ACTIONS too
MAX_WORDS = 400                      # characters of transcript the model gets
CONFIRM_S = 30                       # Confirm / Cancel waits this long, then cancels
UNDO_S = 12                          # the Undo button stays this long
MAX_MINUTES = 24 * 60
APP_DIRS = [os.path.join(HOME, ".local/share/applications"), "/usr/share/applications",
            "/usr/local/share/applications", "/var/lib/flatpak/exports/share/applications",
            os.path.join(HOME, ".local/share/flatpak/exports/share/applications")]
# desktop-index.py's NEVER: key stores and browser profiles are not opened by voice.
SECRET_DIRS = (".ssh", ".gnupg", ".password-store", ".local/share/keyrings", ".local/share/kwalletd",
               ".mozilla", ".librewolf", ".thunderbird", ".config/google-chrome", ".config/chromium",
               ".config/BraveSoftware", ".config/vivaldi", ".config/microsoft-edge", ".var/app",
               ".config/keepassxc", ".pki", ".aws", ".kube", ".docker")
HANDOFF_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "voice")
WORKSPACES = range(1, 7)             # lua/binds.lua's ALT+1..6 (rules.lua pins only those); hyprctl says better
PRIVATE_CLASS = re.compile(r"keepassxc|bitwarden|1password|org\.gnome\.seahorse", re.I)
PRIVATE_TITLE = re.compile(r"private browsing|incognito|inprivate|navegación privada|incógnito", re.I)

# Words for a default app (default-apps.py run ROLE), English and Spanish,
# folded (lower case, no accents).
ROLE_WORDS = {
    "browser": ("browser", "web browser", "navegador", "el navegador", "internet", "web"),
    "terminal": ("terminal", "the terminal", "la terminal", "consola", "console", "shell"),
    "files": ("files", "file manager", "archivos", "explorador", "explorador de archivos",
              "gestor de archivos", "nautilus"),
    "editor": ("editor", "text editor", "editor de texto", "the editor", "el editor"),
    "mail": ("mail", "email", "e-mail", "correo", "el correo"),
    "calendar": ("calendar", "calendario", "el calendario"),
    "music": ("music player", "reproductor de musica"),
}
# The window classes a role word also means when it names an OPEN window.
ROLE_CLASSES = {
    "browser": ("firefox", "chrom", "brave", "zen", "librewolf", "vivaldi", "epiphany", "opera"),
    "terminal": ("kitty", "foot", "alacritty", "wezterm", "ghostty", "cosmicterm", "ptyxis", "konsole",
                 "gnome-terminal"),
    "files": ("nautilus", "thunar", "dolphin", "nemo", "cosmicfiles", "pcmanfm"),
    "editor": ("code", "codium", "zed", "texteditor", "gedit", "kate", "sublime"),
    "mail": ("thunderbird", "geary", "evolution"),
}
FOLDERS = {      # spoken name -> (XDG user-dirs key, fallback under $HOME); PROJECTS = your projects folder
    "downloads": ("DOWNLOAD", "Downloads"), "descargas": ("DOWNLOAD", "Downloads"),
    "documents": ("DOCUMENTS", "Documents"), "documentos": ("DOCUMENTS", "Documents"),
    "pictures": ("PICTURES", "Pictures"), "images": ("PICTURES", "Pictures"), "imagenes": ("PICTURES", "Pictures"),
    "fotos": ("PICTURES", "Pictures"), "photos": ("PICTURES", "Pictures"),
    "music": ("MUSIC", "Music"), "musica": ("MUSIC", "Music"),
    "videos": ("VIDEOS", "Videos"), "desktop": ("DESKTOP", "Desktop"), "escritorio": ("DESKTOP", "Desktop"),
    "home": (None, ""), "inicio": (None, ""), "carpeta personal": (None, ""), "casa": (None, ""),
    "github": ("PROJECTS", ""), "repos": ("PROJECTS", ""), "repositorios": ("PROJECTS", ""),
    "projects": ("PROJECTS", ""), "proyectos": ("PROJECTS", ""),
    "screenshots": ("PICTURES", "Pictures/Screenshots"), "capturas": ("PICTURES", "Pictures/Screenshots"),
}
MEDIA = ("play", "pause", "play-pause", "next", "previous", "stop")
VOLUME = ("up", "down", "mute", "unmute")


# -- the catalog ----------------------------------------------------------------------
# name -> (arguments, from automations.py, English words, Spanish words).
# Arguments: value | text | app | app2 | workspace | minutes | time; a "?"
# suffix is optional. "auto" names the automations.py action that does it.
CATALOG = {
    "theme": ("value", "theme", "switch the theme to {value}", "cambiar el tema a {value}"),
    "dnd": ("value", "dnd", "turn Do Not Disturb {value}", "{value_es} No molestar"),
    "dnd-for": ("minutes", None, "Do Not Disturb for {dur}", "No molestar durante {dur}"),
    "gamemode": ("value", "gamemode", "turn gamemode {value}", "modo juego: {value_es}"),
    "nightlight": ("value", "nightlight", "night light {value}", "luz nocturna: {value_es}"),
    "sound-output": ("value", "sound-output", "play sound through {value}", "sonido por {value}"),
    "sound-profile": ("value", "sound-profile", "set the sound profile {value}", "perfil de sonido {value}"),
    "notify": ("text", "notify", "show a notification “{text}”", "mostrar un aviso «{text}»"),
    "digest": ("", "digest", "show what Do Not Disturb held back", "mostrar lo que No molestar retuvo"),
    "brief": ("", "brief", "show the daily brief", "mostrar el resumen del día"),
    "journal": ("", "journal", "write today's journal entry", "escribir la entrada del diario de hoy"),
    "session": ("value", "session", "restore the session “{value}”", "restaurar la sesión «{value}»"),
    "session-save": ("value", None, "save the open windows as the session “{value}”{extra}",
                     "guardar las ventanas abiertas como la sesión «{value}»{extra}"),
    "context": ("value", "context", "enter the project “{value}”", "entrar al proyecto «{value}»"),
    "launch": ("app", None, "open {label}", "abrir {label}"),
    "open-folder": ("text", None, "open the folder {label}", "abrir la carpeta {label}"),
    "open-url": ("text", None, "open {label}", "abrir {label}"),
    "move": ("app workspace", None, "move {win} to workspace {workspace}", "mover {win} al escritorio {workspace}"),
    "side-by-side": ("app app2", None, "put {win} and {win2} side by side", "poner {win} y {win2} lado a lado"),
    "fullscreen": ("app?", None, "fullscreen {win}", "pantalla completa: {win}"),
    "close": ("app?", None, "close {win}", "cerrar {win}"),
    "workspace": ("workspace", None, "go to workspace {workspace}", "ir al escritorio {workspace}"),
    "timer": ("minutes text?", None, "a {dur} timer{label}", "un temporizador de {dur}{label}"),
    "reminder": ("minutes? time? text", None, "remind me “{text}” {when}", "recordarme «{text}» {when}"),
    "alarm": ("time text?", None, "an alarm at {time}{label}", "una alarma a las {time}{label}"),
    "search": ("text", None, "search the desktop for “{text}”", "buscar en el escritorio «{text}»"),
    "media": ("value", None, "{value_words}", "{value_es}"),
    "volume": ("value", None, "{value_words}", "{value_es}"),
}
NEVER = {"shell": "running commands by voice is never allowed",
         "open": "apps are opened by name (launch), never by a command line"}
VALUE_ES = {"on": "activar", "off": "desactivar", "auto": "automática", "play": "reproducir", "pause": "pausar",
            "play-pause": "reproducir / pausar", "next": "siguiente pista", "previous": "pista anterior",
            "stop": "detener la música", "up": "subir el volumen", "down": "bajar el volumen",
            "mute": "silenciar el sonido", "unmute": "quitar el silencio"}
VALUE_EN = {"play": "play", "pause": "pause", "play-pause": "play / pause", "next": "next track",
            "previous": "previous track", "stop": "stop the music", "up": "volume up", "down": "volume down",
            "mute": "mute the sound", "unmute": "unmute the sound"}
WORDS = {   # the bubbles, by language
    "en": {"heard": "Heard", "thinking": "Understanding…", "refused": "Not done", "confirm": "Confirm",
           "cancel": "Cancel", "undo": "Undo", "done": "Done", "undone": "Undone", "cancelled": "Cancelled",
           "ask": "Do this?", "why_ask": "asks first", "failed": "Some of it failed", "off": "Voice commands are off",
           "off_body": "Settings > Voice turns them on.", "nothing": "Nothing to do"},
    "es": {"heard": "Entendido", "thinking": "Entendiendo…", "refused": "No se hizo", "confirm": "Confirmar",
           "cancel": "Cancelar", "undo": "Deshacer", "done": "Hecho", "undone": "Deshecho", "cancelled": "Cancelado",
           "ask": "¿Hago esto?", "why_ask": "pregunta antes", "failed": "Algo falló", "off": "Los comandos de voz están apagados",
           "off_body": "Ajustes > Voz los enciende.", "nothing": "Nada que hacer"},
}


def log(text):
    print(f"voice-command: {text}", file=sys.stderr, flush=True)


def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def automations():
    return _module("automations", "automations.py")


def fold(text):
    """Lower case, accents off, punctuation to spaces, one space between words."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w:./+-]+", " ", text).split()).strip(" .")


def settings():
    """voice.py's command settings (commands, command_confirm, command_language)."""
    try:
        values = _module("voice", "voice.py").read_settings()
    except Exception:       # voice.py broken must not make commands run unasked
        values = {}
    return {"commands": values.get("commands", "on"), "confirm": values.get("command_confirm", "off") == "on",
            "language": values.get("command_language", "auto")}


def guess_language(text):
    """"es" or "en" from the words alone (when Whisper did not say)."""
    words = set(fold(text).split())
    es = len(words & {"el", "la", "los", "las", "de", "al", "pon", "mueve", "abre", "cierra", "escritorio",
                      "ventana", "minutos", "hora", "por", "para", "que", "y", "una", "un", "molestar",
                      "siguiente", "sube", "baja", "recuerdame", "busca", "tema", "lado"})
    en = len(words & {"the", "to", "of", "and", "put", "move", "open", "close", "workspace", "window",
                      "minutes", "hour", "for", "a", "an", "do", "disturb", "next", "up", "down", "remind",
                      "search", "theme", "side"})
    return "es" if es > en else "en"


# -- the world (what is open, installed, saved) ----------------------------------------
def hypr_json(*what):
    """`hyprctl ARGS -j`, parsed; None when Hyprland does not answer. Over the
    request socket (desk_common.hypr_request): no process."""
    return desk_common.hypr_request(what, json=True, timeout=5)


def script_json(name, *args, timeout=15):
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, name), *args], capture_output=True,
                             text=True, timeout=timeout).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def private_classes():
    try:
        import privacy_settings
        return set(privacy_settings.excluded(privacy_settings.load()))
    except Exception:       # noqa: BLE001 - privacy.conf unreadable: nothing extra is private
        return set()


def desktop_entries(dirs=None):
    """[{"id", "names": [folded], "keywords": [folded], "label"}] of the apps a
    person would launch (Type=Application, not NoDisplay / Hidden)."""
    seen, out = set(), []
    for folder in dirs or APP_DIRS:
        try:
            files = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in files:
            if not name.endswith(".desktop") or name in seen:
                continue
            seen.add(name)
            entry = {}
            try:
                with open(os.path.join(folder, name), errors="replace") as handle:
                    group = None
                    for line in handle:
                        line = line.strip()
                        if line.startswith("["):
                            group = line
                            continue
                        if group == "[Desktop Entry]" and "=" in line:
                            key, _, value = line.partition("=")
                            entry.setdefault(key.strip(), value.strip())
            except OSError:
                continue
            if entry.get("Type") != "Application" or entry.get("NoDisplay") == "true" \
                    or entry.get("Hidden") == "true" or not entry.get("Name"):
                continue
            names = [entry[k] for k in ("Name", "Name[es]", "GenericName", "GenericName[es]") if entry.get(k)]
            keywords = ";".join(entry[k] for k in ("Keywords", "Keywords[es]") if entry.get(k)).split(";")
            out.append({"id": name, "label": entry["Name"], "names": [fold(n) for n in names],
                        "keywords": [fold(k) for k in keywords if k.strip()],
                        "stem": fold(name.removesuffix(".desktop").split(".")[-1])})
    return out


class World:
    """What the checks look at, read once per command. Tests hand in their
    own (every attribute is plain data)."""

    def __init__(self):
        self._cache = {}

    def _get(self, key, make):
        if key not in self._cache:
            self._cache[key] = make()
        return self._cache[key]

    def clients(self):
        return self._get("clients", lambda: [c for c in (hypr_json("clients") or [])
                                             if c.get("mapped", True) and c.get("address")])

    def active(self):
        return self._get("active", lambda: hypr_json("activewindow") or {})

    def monitors(self):
        return self._get("monitors", lambda: hypr_json("monitors") or [])

    def active_workspace(self):
        return self._get("activeworkspace", lambda: hypr_json("activeworkspace") or {})

    def themes(self):
        return self._get("themes", automations().theme_names)

    def current_theme(self):
        return self._get("theme", lambda: automations().run(sys.executable, os.path.join(HERE, "theme.py"),
                                                            "current").strip())

    def sessions(self):
        data = self._get("sessions", lambda: script_json("sessions.py", "list", "--json") or {})
        return [s.get("name") for s in data.get("sessions") or [] if isinstance(s, dict) and s.get("name")]

    def contexts(self):
        data = self._get("contexts", lambda: script_json("contexts.py", "list", "--json") or {})
        return [c.get("name") for c in data.get("contexts") or [] if isinstance(c, dict) and c.get("name")]

    def apps(self):
        return self._get("apps", desktop_entries)

    def private(self):
        return self._get("private", private_classes)

    def dnd(self):
        return automations().dnd_now()

    def sink(self):
        return automations().sink_now()[0]

    def timer_ids(self):
        data = script_json("timers.py", "list", "--json") or []
        return {t.get("id") for t in data if isinstance(t, dict)}

    def muted(self):
        out = automations().run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@", timeout=3)
        return "MUTED" in out

    def workspaces(self):
        """The numbered workspaces that have a home (workspace rules), else WORKSPACES."""
        def make():
            names = {str(r.get("workspaceString", "")) for r in hypr_json("workspacerules") or []
                     if isinstance(r, dict)}
            return sorted(int(n) for n in names if n.isdigit() and 1 <= int(n) <= 10) or list(WORKSPACES)
        return self._get("workspaces", make)

    def closed_stack(self):
        """closed-windows.py's stack, newest first ([] when it is not running)."""
        data = script_json("closed-windows.py", "list", "--json", timeout=5)
        return data if isinstance(data, list) else []


# -- checking one action ------------------------------------------------------------------
class Refused(ValueError):
    pass


def is_private(client, private=()):
    cls = (client.get("class") or client.get("initialClass") or "").lower()
    return bool(PRIVATE_CLASS.search(cls) or PRIVATE_TITLE.search(client.get("title") or "")
                or cls in private)


def window_label(client, private=(), titles=True):
    """"Firefox (“Claude — Mozilla…”)", or only the app for a private window
    (and for the journal: titles=False)."""
    cls = client.get("class") or client.get("initialClass") or "?"
    app = cls.split(".")[-1]
    app = app[:1].upper() + app[1:]
    title = (client.get("title") or "").strip()
    if not titles or not title or is_private(client, private):
        return app
    return f"{app} (“{title[:40]}{'…' if len(title) > 40 else ''}”)"


def match_windows(word, clients, private=()):
    """The open windows `word` names, best kind of match first: the class
    exactly, a role word ("browser", "navegador"), the class containing it,
    then the title containing it (never a private window's title)."""
    w = fold(word).removeprefix("the ").removeprefix("el ").removeprefix("la ")
    w = re.sub(r"\s+(window|ventana)$", "", w)
    if not w:
        return []
    squash = w.replace(" ", "").replace("-", "")
    role = next((r for r, words in ROLE_WORDS.items() if w in words), None)
    tiers = ([], [], [], [])
    for c in clients:
        classes = {fold(c.get("class") or ""), fold(c.get("initialClass") or "")} - {""}
        flat = {x.replace(" ", "").replace("-", "") for x in classes}
        short = {x.split(".")[-1] for x in flat}
        if squash in flat or squash in short:
            tiers[0].append(c)
        elif role and any(k in x for x in flat for k in ROLE_CLASSES.get(role, ())):
            tiers[1].append(c)
        elif len(squash) >= 3 and any(squash in x for x in flat):
            tiers[2].append(c)
        elif len(w) >= 3 and not is_private(c, private) and w in fold(c.get("title") or ""):
            tiers[3].append(c)
    return next((t for t in tiers if t), [])


def resolve_app(word, apps):
    """("role", ROLE, label) for a default app word, ("id", desktop id, label),
    or Refused. A tie between different apps is Refused too, naming them --
    the caller asks instead."""
    w = fold(word).removeprefix("the ").removeprefix("el ").removeprefix("la ")
    for role, words in ROLE_WORDS.items():
        if w in words:
            return "role", role, {"browser": "the browser", "terminal": "a terminal", "files": "the file manager",
                                  "editor": "the editor", "mail": "mail", "calendar": "the calendar",
                                  "music": "the music player"}[role], []
    if not w:
        raise Refused("no app named")
    scored = []
    for app in apps:
        score = 0
        if w in app["names"][:2]:
            score = 100
        elif w == app["stem"] or w.replace(" ", "") == app["stem"].replace(" ", ""):
            score = 90
        elif any(n.startswith(w + " ") or n.startswith(w) and len(w) >= 4 for n in app["names"][:2]):
            score = 60
        elif w in app["keywords"] or w in app["names"]:
            score = 50
        elif len(w) >= 4 and any(w in n for n in app["names"]):
            score = 30
        if score:
            scored.append((score, app))
    if not scored:
        raise Refused(f"no installed app is called “{word}”")
    scored.sort(key=lambda s: -s[0])
    best = scored[0][0]
    top = [a for s, a in scored if s == best]
    return "id", top[0]["id"], top[0]["label"], [a["label"] for a in top[1:4]]


def user_dir(key):
    """An XDG user dir from ~/.config/user-dirs.dirs, else None."""
    try:
        with open(os.path.join(HOME, ".config", "user-dirs.dirs")) as handle:
            for line in handle:
                m = re.match(rf'XDG_{key}_DIR="(.*)"', line.strip())
                if m:
                    return m[1].replace("$HOME", HOME)
    except OSError:
        pass
    return None


def looks_secret(path):
    real = os.path.realpath(path)
    return any(real == os.path.join(HOME, d) or real.startswith(os.path.join(HOME, d) + os.sep)
               for d in SECRET_DIRS)


def resolve_folder(words, github=None):
    """An existing folder for spoken words: a known folder ("downloads",
    "descargas", "repos" = your projects folder), a repo in your projects
    folder (`github`, PROJECTS by default) by name, or a path. Refused when
    there is none, or it is a secret one."""
    w = fold(words).removeprefix("my ").removeprefix("mis ").removeprefix("mi ")
    w = re.sub(r"^(the|la|el|las|los) ", "", w)
    w = re.sub(r"\s*(folder|carpeta|directory|directorio)\s*", " ", w).strip()
    w = re.sub(r"^(de|del|of) ", "", w).strip()
    github = github or PROJECTS
    path = None
    if w in FOLDERS:
        key, fallback = FOLDERS[w]
        path = github if key == "PROJECTS" else (user_dir(key) if key else None) or os.path.join(HOME, fallback)
    elif str(words).strip().startswith(("/", "~")):
        path = str(words).strip()
        path = os.path.join(HOME, path[2:]) if path.startswith("~/") else HOME if path == "~" else path
    else:
        try:
            repos = os.listdir(github)
        except OSError:
            repos = []
        squash = w.replace(" ", "").replace("-", "")
        hits = [r for r in repos if fold(r).replace(" ", "").replace("-", "") == squash] or \
               [r for r in repos if len(squash) >= 4 and squash in fold(r).replace("-", "").replace(" ", "")]
        if len(hits) > 1:
            raise Refused(f"“{words}” could be {', '.join(sorted(hits)[:4])}")
        if hits:
            path = os.path.join(github, hits[0])
    if not path or not os.path.isdir(path):
        raise Refused(f"no folder “{words}”")
    if looks_secret(path):
        raise Refused("that folder holds secrets: not opened by voice")
    return os.path.normpath(path)


URL = re.compile(r"(?:https?://)?((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(:\d{1,5})?(/[^\s<>\"']*)?$", re.I)


def check_url(text):
    text = str(text).strip()
    if re.match(r"[a-z][a-z0-9+.-]*:", text, re.I) and not re.match(r"https?://", text, re.I):
        raise Refused("only web links (http / https) are opened")
    text = re.sub(r"\s+(dot|punto)\s+", ".", text.strip(), flags=re.I).replace(" ", "")
    m = URL.match(text)
    if not m:
        raise Refused(f"“{text}” is not a web address")
    return "https://" + text.split("://", 1)[-1] if not re.match(r"https?://", text, re.I) else text


def check_minutes(value, lo=0.05, hi=MAX_MINUTES):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise Refused("needs a duration") from None
    if not lo <= n <= hi:
        raise Refused("the duration is out of range")
    return n


def check_time(value):
    m = re.fullmatch(r"\s*([01]?\d|2[0-3])[:.h]([0-5]\d)\s*", str(value or ""))
    if not m:
        raise Refused("needs a time as HH:MM")
    return f"{int(m[1]):02d}:{m[2]}"


def check_workspace(value, allowed=WORKSPACES):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise Refused("needs a workspace number") from None
    if n not in allowed:
        raise Refused(f"the workspaces are {min(allowed)} to {max(allowed)}")
    return n


def summon_lua(n):
    """lua/binds.lua's ALT+n: an empty workspace homed on another screen is
    pulled to the focused one, else plain focus (goes where it is)."""
    return (f"local id = {int(n)}; local mon = hl.get_active_monitor(); local target; "
            "for _, w in ipairs(hl.get_workspaces()) do if w.id == id then target = w break end end; "
            "if mon and target and target.monitor and target.monitor.name ~= mon.name and target.is_empty then "
            "hl.dispatch(hl.dsp.workspace.move({ workspace = id, monitor = mon.name })) end; "
            "hl.dispatch(hl.dsp.focus({ workspace = id }))")


def clean_label(text, limit=80):
    """A label / message for timers.py: words only. Its "then ..." parser
    (which can run a "!command") never sees a "then" from here."""
    text = re.sub(r"[^\w\s,.'¿?¡!-]", " ", str(text or ""))
    text = text.replace("!", " ")
    text = re.sub(r"\b(then|and then|luego|y luego|despues|después)\b", " ", text, flags=re.I)
    return " ".join(text.split())[:limit]


def dur_text(minutes, lang="en"):
    secs = int(round(minutes * 60))
    h, rest = divmod(secs, 3600)
    m, s = divmod(rest, 60)
    parts = ([f"{h} h"] if h else []) + ([f"{m} min"] if m else []) + ([f"{s} s"] if s else [])
    return " ".join(parts) or "0 s"


def hms(minutes):
    """A duration as H:MM:SS for timers.py: its parse_duration ends there, so
    a label that starts with "5 minutes" is never added to the time."""
    h, rest = divmod(int(round(minutes * 60)), 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}"


def lua_target(address):
    """The Lua selector for a window address -- only ever 0x and hex digits
    (anything else selects nothing)."""
    address = str(address)
    return '"address:' + (address if re.fullmatch(r"0x[0-9a-f]{1,16}", address) else "none") + '"'


def ws_of(client):
    return (client.get("workspace") or {}).get("name") or str((client.get("workspace") or {}).get("id", ""))


def py(script, *args):
    return [sys.executable, os.path.join(HERE, script), *args]


def scope(argv):
    return automations().scope(argv)


def unit(argv):
    return automations().unit(argv)


def check_step(act, world, lang="en"):
    """One action from the model -> a step: {"action", "say", "confirm" (why
    it asks, "" when it does not), "ops", "undo" (how to take it back, or
    None), ...}. Refused with the reason when it does not check out."""
    if not isinstance(act, dict):
        raise Refused("not an action")
    name = act.get("action")
    if not isinstance(name, str):
        raise Refused("not an action")
    if name in NEVER:
        raise Refused(NEVER[name])
    if name not in CATALOG:
        raise Refused(f"“{name}” is not something voice commands can do")
    spec, auto_name, en, es = CATALOG[name]
    words = {"value": "", "value_es": "", "value_words": "", "text": "", "label": "", "win": "", "win2": "",
             "workspace": "", "dur": "", "time": "", "when": "", "extra": ""}
    step = {"action": name, "confirm": "", "ops": [], "undo": None}
    plain = {}                  # win / win2 without titles: what the journal gets
    needs = [a for a in spec.split() if not a.endswith("?")]
    for arg in needs:
        if act.get(arg) in (None, "") and not (name == "reminder"):
            raise Refused(f"{name} needs “{arg}”")
    private = world.private()

    if auto_name:                                   # automations.py checks and does it
        kind = automations().ACTIONS[auto_name][0]
        value = act.get("text") if spec == "text" else act.get("value")
        if kind is None:
            value = None
        if kind == "theme":
            value = match_name(value, world.themes(), "theme")
        elif kind == "name" and name == "session":
            value = match_name(value, world.sessions(), "saved session")
        elif kind == "name" and name == "context":
            v = fold(value or "")
            value = "leave" if v in ("leave", "salir", "none", "ninguno") else \
                match_name(value, world.contexts(), "project context")
        elif kind in ("on-off", "on-off-auto") and isinstance(value, str):
            value = {"encender": "on", "activar": "on", "apagar": "off", "desactivar": "off",
                     "true": "on", "false": "off"}.get(fold(value), fold(value))
        try:
            value = automations().check_value(kind, value)
        except ValueError as err:
            raise Refused(f"{name}: the value {err}") from None
        step["ops"] = [("auto", {"action": auto_name} | ({"value": value} if value is not None else {}))]
        words.update(value=value or "", text=value or "", value_es=VALUE_ES.get(value or "", value or ""))
        if name == "context" and value == "leave":
            en, es = "leave the project", "salir del proyecto"
        if name == "sound-profile":
            step["confirm"] = "changes the sound card's profile"
        if name in ("theme", "dnd", "gamemode", "sound-output"):
            step["undo"] = name
        step["value"] = value

    elif name == "dnd-for":
        minutes = check_minutes(act.get("minutes"), 1)
        secs = int(round(minutes * 60))
        step["ops"] = [("argv", ["systemctl", "--user", "stop", f"{DND_UNIT}.timer"]),
                       ("auto", {"action": "dnd", "value": "on"}),
                       ("argv", ["systemd-run", "--user", "--quiet", "--collect", f"--unit={DND_UNIT}",
                                 f"--on-active={secs}s", "--", *py("notify-settings.py", "dnd", "off")])]
        step["undo"] = "dnd-for"
        words["dur"] = dur_text(minutes, lang)

    elif name == "session-save":
        value = str(act.get("value") or "").strip()
        if not re.fullmatch(r"\w[\w .-]{0,63}", value):
            raise Refused("a session name is letters, digits, space . _ - (starting with a letter or digit)")
        if any(fold(s) == fold(value) for s in world.sessions()):
            value = next(s for s in world.sessions() if fold(s) == fold(value))
            step["confirm"] = "replaces the session saved under that name"
            words["extra"] = " (replaces it)" if lang == "en" else " (la reemplaza)"
        step["ops"] = [("argv", py("sessions.py", "save", value))]
        words["value"] = value

    elif name == "launch":
        kind, target, label, others = resolve_app(act.get("app"), world.apps())
        if kind == "role":
            step["ops"] = [("detach", scope(py("default-apps.py", "run", target)))]
        else:
            step["ops"] = [("auto", {"action": "open", "value": target})]
        if others:
            step["confirm"] = f"“{act.get('app')}” could also be {', '.join(others)}"
        words["label"] = label

    elif name == "open-folder":
        path = resolve_folder(act.get("text"))
        step["ops"] = [("detach", scope(py("default-apps.py", "run", "files", path)))]
        words["label"] = path.replace(HOME, "~", 1)

    elif name == "open-url":
        url = check_url(act.get("text"))
        step["ops"] = [("detach", scope(py("default-apps.py", "run", "browser", url)))]
        words["label"] = url

    elif name in ("move", "side-by-side", "fullscreen", "close"):
        clients = world.clients()
        active = world.active() or {}
        if act.get("app"):
            wins = match_windows(act["app"], clients, private)
            if not wins:
                raise Refused(f"no open window is “{act['app']}”")
        else:
            if not active.get("address"):
                raise Refused("no window has the focus")
            wins = [active]
        words["win"] = window_label(wins[0], private) + (f" (+{len(wins) - 1})" if len(wins) > 1 else "")
        plain["win"] = window_label(wins[0], titles=False) + (f" (+{len(wins) - 1})" if len(wins) > 1 else "")
        step["windows"] = [{"address": c["address"], "workspace": ws_of(c), "floating": bool(c.get("floating")),
                            "fullscreen": c.get("fullscreen") or 0} for c in wins]
        if name == "move":
            n = check_workspace(act.get("workspace"), workspaces_of(world))
            words["workspace"] = n
            step["ops"] = [("lua", f'hl.dispatch(hl.dsp.window.move({{ workspace = "{n}", follow = false, '
                                   f'window = {lua_target(c["address"])} }}))') for c in wins]
            if len(wins) > 1:
                step["confirm"] = f"moves {len(wins)} windows"
            step["undo"] = "move"
        elif name == "side-by-side":
            if len(wins) > 1:
                wins = wins[:1]
                step["windows"] = step["windows"][:1]
                words["win"] = window_label(wins[0], private)
                plain["win"] = window_label(wins[0], titles=False)
            others = [c for c in match_windows(act.get("app2") or "", clients, private)
                      if c["address"] != wins[0]["address"]]
            if not others:
                raise Refused(f"no other open window is “{act.get('app2')}”")
            b = others[0]
            words["win2"] = window_label(b, private)
            plain["win2"] = window_label(b, titles=False)
            if len(others) > 1:
                step["confirm"] = f"“{act.get('app2')}” matches {len(others)} windows; the first one is used"
            step["windows"].append({"address": b["address"], "workspace": ws_of(b),
                                    "floating": bool(b.get("floating")), "fullscreen": b.get("fullscreen") or 0})
            here = ws_of(wins[0])
            ops = []
            for c in (wins[0], b):
                t = lua_target(c["address"])
                if c.get("fullscreen"):
                    ops.append(f"hl.dispatch(hl.dsp.window.fullscreen({{ window = {t} }}))")
                if c.get("floating"):
                    ops.append(f'hl.dispatch(hl.dsp.window.float({{ action = "disable", window = {t} }}))')
            if ws_of(b) != here:
                ops.append(f'hl.dispatch(hl.dsp.window.move({{ workspace = "{lua_esc(here)}", follow = false, '
                           f'window = {lua_target(b["address"])} }}))')
            ops.append(f'hl.dispatch(hl.dsp.focus({{ window = {lua_target(wins[0]["address"])} }}))')
            step["ops"] = [("lua", op) for op in ops]
            step["undo"] = "move"
        elif name == "fullscreen":
            if len(wins) > 1:
                wins = wins[:1]
                step["windows"] = step["windows"][:1]
                words["win"] = window_label(wins[0], private)
                plain["win"] = window_label(wins[0], titles=False)
            t = lua_target(wins[0]["address"])
            step["ops"] = [("lua", f"hl.dispatch(hl.dsp.focus({{ window = {t} }}))"),
                           ("lua", f"hl.dispatch(hl.dsp.window.fullscreen({{ window = {t} }}))")]
            step["undo"] = "fullscreen"
        else:                                           # close
            shown = shown_workspaces(world)
            focused = len(wins) == 1 and wins[0].get("address") == active.get("address")
            if focused and ws_of(wins[0]) not in shown:
                raise Refused("the focus is on a workspace you cannot see: nothing closed")
            if not focused:
                step["confirm"] = (f"closes {len(wins)} windows" if len(wins) > 1
                                   else "closes a window that does not have the focus")
            step["ops"] = [("lua", f"hl.dispatch(hl.dsp.window.close({{ window = {lua_target(c['address'])} }}))")
                           for c in wins]
            step["undo"] = "close"

    elif name == "workspace":
        n = check_workspace(act.get("workspace"), workspaces_of(world))
        words["workspace"] = n
        step["ops"] = [("lua", summon_lua(n))]
        step["from"] = (world.active_workspace() or {}).get("id")
        step["undo"] = "workspace" if step["from"] else None

    elif name == "timer":
        minutes = check_minutes(act.get("minutes"))
        label = clean_label(act.get("text"))
        step["ops"] = [("argv", py("timers.py", "timer", hms(minutes), *label.split()))]
        step["undo"] = "timer"
        words.update(dur=dur_text(minutes, lang), label=f" “{label}”" if label else "")

    elif name == "reminder":
        text = clean_label(act.get("text"), 160)
        if not text:
            raise Refused("a reminder needs what to remind")
        if act.get("minutes") not in (None, "", 0):
            minutes = check_minutes(act.get("minutes"))
            step["ops"] = [("argv", py("timers.py", "remind", "in", hms(minutes), *text.split()))]
            words["when"] = (f"in {dur_text(minutes)}" if lang == "en" else f"en {dur_text(minutes)}")
        elif act.get("time"):
            at = check_time(act.get("time"))
            step["ops"] = [("argv", py("timers.py", "remind", "at", at, *text.split()))]
            words["when"] = (f"at {at}" if lang == "en" else f"a las {at}")
        else:
            raise Refused("a reminder needs when: minutes or a time")
        step["undo"] = "timer"
        words["text"] = text

    elif name == "alarm":
        at = check_time(act.get("time"))
        label = clean_label(act.get("text"))
        step["ops"] = [("argv", py("timers.py", "alarm", at, *label.split()))]
        step["undo"] = "timer"
        words.update(time=at, label=f" “{label}”" if label else "")

    elif name == "search":
        text = " ".join(str(act.get("text") or "").split())[:300]
        if not text:
            raise Refused("search for what?")
        step["ops"] = [("argv", unit(py("ask-desktop.py", "--notify", text)))]
        words["text"] = text

    elif name == "media":
        value = fold(act.get("value") or "").replace(" ", "-")
        value = {"resume": "play", "toggle": "play-pause", "skip": "next", "prev": "previous",
                 "back": "previous"}.get(value, value)
        if value not in MEDIA:
            raise Refused(f"media is one of: {', '.join(MEDIA)}")
        step["ops"] = [("argv", ["playerctl", value])]
        step["value"] = value
        words.update(value_words=VALUE_EN[value], value_es=VALUE_ES[value].capitalize())

    elif name == "volume":
        value = fold(act.get("value") or "")
        if value not in VOLUME:
            raise Refused(f"volume is one of: {', '.join(VOLUME)}")
        sink = "@DEFAULT_AUDIO_SINK@"
        step["ops"] = [("argv", {"up": ["wpctl", "set-volume", "-l", "1.0", sink, "5%+"],
                                 "down": ["wpctl", "set-volume", sink, "5%-"],
                                 "mute": ["wpctl", "set-mute", sink, "1"],
                                 "unmute": ["wpctl", "set-mute", sink, "0"]}[value])]
        step["value"] = value
        step["undo"] = "volume" if value in ("mute", "unmute") else None
        words.update(value_words=VALUE_EN[value], value_es=VALUE_ES[value].capitalize())

    template = es if lang == "es" else en
    step["say"] = template.format(**words).strip()
    step["say"] = step["say"][:1].upper() + step["say"][1:]
    step["log"] = template.format(**(words | plain)).strip()
    return step


def lua_esc(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def workspaces_of(world):
    """The workspace numbers a command may name (tests' worlds may not say)."""
    get = getattr(world, "workspaces", None)
    try:
        return (get() if get else None) or WORKSPACES
    except Exception:       # noqa: BLE001 - hyprctl unreadable: the bound six
        return WORKSPACES


def shown_workspaces(world):
    """The workspace names the screens show now (and their open special ones)."""
    shown = set()
    for m in world.monitors():
        for key in ("activeWorkspace", "specialWorkspace"):
            name = (m.get(key) or {}).get("name")
            if name:
                shown.add(name)
    return shown


def match_name(value, names, what):
    """`value` as one of `names` -- exactly, ignoring case and accents, or the
    one that starts with it. Refused otherwise."""
    if not isinstance(value, str) or not value.strip():
        raise Refused(f"which {what}?")
    v = fold(value)
    for n in names:
        if fold(n) == v:
            return n
    hits = [n for n in names if fold(n).startswith(v) or v in fold(n) and len(v) >= 3]
    if len(hits) == 1:
        return hits[0]
    if not names:
        raise Refused(f"there is no {what} yet")
    raise Refused(f"no {what} “{value}” ({', '.join(names[:6])})")


def plan(actions, world, lang="en", sure=True, confirm_all=False):
    """(steps, refused): the actions checked, in order. A step that has to
    ask says why in step["confirm"]."""
    steps, refused = [], []
    for act in (actions or [])[:MAX_ACTIONS]:
        try:
            steps.append(check_step(act, world, lang))
        except Refused as err:
            refused.append(f"{(act or {}).get('action', '?') if isinstance(act, dict) else '?'}: {err}")
    if len(actions or []) > MAX_ACTIONS:
        refused.append(f"only the first {MAX_ACTIONS} actions are done")
    for step in steps:
        if confirm_all and not step["confirm"]:
            step["confirm"] = "confirm everything is on"
        elif not sure and not step["confirm"]:
            step["confirm"] = "not sure that is what you meant"
        elif refused and not step["confirm"]:
            step["confirm"] = "part of what you said was not understood"
    return steps, refused


# -- words -> actions --------------------------------------------------------------------
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "uno": 1, "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
                "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
FAST = [   # whole sentences, folded: no model needed
    (r"(?:pause|pausa|pausar|pausa la musica|pause the music|pause music)", {"action": "media", "value": "pause"}),
    (r"(?:play|resume|play music|play the music|reproducir|reproduce|continua|continuar|reanudar|"
     r"pon la musica|reproduce la musica)", {"action": "media", "value": "play"}),
    (r"(?:next|next song|next track|skip|siguiente|siguiente cancion|siguiente pista|la siguiente)",
     {"action": "media", "value": "next"}),
    (r"(?:previous|previous song|previous track|anterior|cancion anterior|pista anterior|la anterior)",
     {"action": "media", "value": "previous"}),
    (r"(?:stop the music|stop music|deten la musica|para la musica|detener la musica)",
     {"action": "media", "value": "stop"}),
    (r"(?:volume up|louder|turn it up|sube el volumen|subir el volumen|mas volumen|sube volumen)",
     {"action": "volume", "value": "up"}),
    (r"(?:volume down|quieter|turn it down|baja el volumen|bajar el volumen|menos volumen|baja volumen)",
     {"action": "volume", "value": "down"}),
    (r"(?:mute|mute the sound|silencio|silenciar|silencia|silencia el sonido)", {"action": "volume", "value": "mute"}),
    (r"(?:unmute|quita el silencio|quitar el silencio)", {"action": "volume", "value": "unmute"}),
    (r"(?:fullscreen|full screen|go fullscreen|pantalla completa|ponla en pantalla completa)", {"action": "fullscreen"}),
    (r"(?:close (?:this |the )?window|cierra (?:esta |la )?ventana|cerrar (?:esta |la )?ventana)", {"action": "close"}),
    (r"(?:(?:turn on |activa |activar |enciende )?(?:do not disturb|don t disturb|dont disturb|no molestar)(?: on)?)",
     {"action": "dnd", "value": "on"}),
    (r"(?:(?:turn off |desactiva |desactivar |apaga |quita )(?:do not disturb|don t disturb|dont disturb|no molestar)|"
     r"(?:do not disturb|don t disturb|dont disturb|no molestar) off)", {"action": "dnd", "value": "off"}),
]
FAST_WS = re.compile(r"(?:go to |switch to |ir al |ve al |vete al |cambia al )?(?:workspace|escritorio) "
                     r"(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")")


def fast_parse(text):
    """The actions for a short sentence everyone says the same way, or None
    (the model decides)."""
    t = fold(text).rstrip(".!?¡¿ ")
    t = re.sub(r"^(?:please |por favor |hey |oye )|(?: please| por favor)$", "", t).strip()
    for pattern, act in FAST:
        if re.fullmatch(pattern, t):
            return [dict(act)]
    m = FAST_WS.fullmatch(t)
    if m:
        n = m[1]
        return [{"action": "workspace", "workspace": int(n) if n.isdigit() else NUMBER_WORDS[n]}]
    return None


SYSTEM = ("You turn one spoken desktop command (Spanish or English, transcribed by speech recognition, so it may "
          "have small errors) into a list of actions, as JSON. Use ONLY the actions listed; never invent "
          "others, never write commands or code. If the request cannot be done with them, or is not a "
          "command, answer {\"actions\": [], \"sure\": false, \"error\": \"short reason\"}.")
SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {"type": "array", "maxItems": MAX_ACTIONS, "items": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(CATALOG) + ["unknown"]},
                "value": {"type": "string"}, "text": {"type": "string"}, "app": {"type": "string"},
                "app2": {"type": "string"}, "workspace": {"type": "integer"}, "minutes": {"type": "number"},
                "time": {"type": "string"},
            },
            "required": ["action"]}},
        "sure": {"type": "boolean"},
        "error": {"type": "string"},
    },
    "required": ["actions", "sure"],
}
ARG_HELP = {
    "theme": "value = one of THEMES", "dnd": "value = on|off", "dnd-for": "minutes = how long (\"for an hour\" = 60)",
    "gamemode": "value = on|off", "nightlight": "value = on|off|auto",
    "sound-output": "value = a word of the output's name (headphones, hdmi, speakers)",
    "sound-profile": "value = \"CARD PROFILE\"", "notify": "text = the message",
    "digest": "no arguments: the notifications Do Not Disturb held back", "brief": "no arguments: the daily brief",
    "journal": "no arguments: today's journal entry", "session": "value = one of SESSIONS (restore it)",
    "session-save": "value = a name (save the open windows as a session)",
    "context": "value = one of PROJECTS, or \"leave\"",
    "launch": "app = the app's name as spoken, or browser|terminal|files|editor|mail|calendar",
    "open-folder": "text = the folder: downloads, documents, pictures, music, videos, desktop, home, a repo name, or a path",
    "open-url": "text = the web address", "move": "app = which window (app name), workspace = number",
    "side-by-side": "app, app2 = the two windows", "fullscreen": "app = which window (leave out: the focused one)",
    "close": "app = which window (leave out: the focused one)", "workspace": "workspace = number (go there)",
    "timer": "minutes (seconds / 60), text = label (optional)",
    "reminder": "text = what to remind, and minutes (\"in 20 minutes\") OR time HH:MM 24 h (\"at 5 pm\" = 17:00)",
    "alarm": "time = HH:MM 24 h, text = label (optional)", "search": "text = what to look for in my files / activity",
    "media": "value = play|pause|play-pause|next|previous|stop", "volume": "value = up|down|mute|unmute",
}
EXAMPLES = [
    ("move firefox to workspace 3", {"actions": [{"action": "move", "app": "firefox", "workspace": 3}], "sure": True}),
    ("pon la terminal y el navegador lado a lado",
     {"actions": [{"action": "side-by-side", "app": "terminal", "app2": "browser"}], "sure": True}),
    ("no molestar durante una hora", {"actions": [{"action": "dnd-for", "minutes": 60}], "sure": True}),
    ("timer de 10 minutos para el té", {"actions": [{"action": "timer", "minutes": 10, "text": "té"}], "sure": True}),
    ("open my downloads and pause the music",
     {"actions": [{"action": "open-folder", "text": "downloads"}, {"action": "media", "value": "pause"}], "sure": True}),
    ("delete all my files", {"actions": [], "sure": False, "error": "deleting files is not something I can do"}),
]


def model_prompt(text, world):
    try:
        classes = sorted({(c.get("class") or "").split(".")[-1].lower() for c in world.clients()} - {""})
    except Exception:       # noqa: BLE001 - the prompt goes without the open apps
        classes = []
    actions = "\n".join(f"  {name}: {ARG_HELP[name]}" for name in CATALOG)
    examples = "\n".join(f"  \"{said}\" -> {json.dumps(out, ensure_ascii=False)}" for said, out in EXAMPLES)
    return (f"Actions (\"actions\": [{{\"action\": NAME, ...arguments}}], at most {MAX_ACTIONS}, in the order "
            f"said):\n{actions}\n\n"
            f"THEMES: {', '.join(world.themes()) or 'none'}\n"
            f"SESSIONS: {', '.join(world.sessions()) or 'none'}\n"
            f"PROJECTS: {', '.join(world.contexts()) or 'none'}\n"
            f"Open apps now: {', '.join(classes[:30]) or 'none'}\n"
            f"Time now: {datetime.datetime.now():%H:%M}\n\n"
            "Rules: a spoken window/app name goes in app as said (\"Firefox\", \"terminal\", \"Chrome\"); "
            "\"navegador\" is browser, \"archivos\" is files; \"escritorio N\" means workspace N; an hour is "
            "60 minutes; \"sure\" is false when you had to guess.\n"
            f"Examples:\n{examples}\n\nCommand: {text[:MAX_WORDS]}")


def loaded_default():
    """The "default" local model when LM Studio has it loaded already, else
    None -- asked only when the quick one would not fit next to it."""
    try:
        lm = _module("llm_models", "llm_models.py")
        model = lm.chosen("default")
        if model is None or not model.local:
            return None
        loaded = lm._json_out(lm._lms("ps", "--json", timeout=10).stdout) or []
        if any(isinstance(m, dict) and m.get("modelKey") == model.ident for m in loaded):
            return model
    except Exception:       # noqa: BLE001 - LM Studio not there: no fallback
        pass
    return None


def model_ask():
    """(ask(prompt) -> text, model name) or (None, why). Local only."""
    worker = _module("llm_worker", "llm-worker.py")
    model, why = worker.ready("quick")
    if model is None and "would not fit" in (why or ""):
        model = loaded_default()
    if model is None:
        return None, (why or "no local model").removesuffix(": do the job yourself")

    def ask(prompt):
        return worker.ask(model, prompt, system=SYSTEM, extra={
            "temperature": 0, "max_tokens": 600,
            "response_format": {"type": "json_schema", "json_schema": {"name": "command", "schema": SCHEMA}}})
    return ask, model.name


def understand(text, world, ask=None):
    """{"actions", "sure", "error", "how"} for the transcript: the fast
    sentences, else the model (`ask`: tests hand in a stub)."""
    fast = fast_parse(text)
    if fast:
        return {"actions": fast, "sure": True, "error": "", "how": "fast"}
    how = "model"
    if ask is None:
        ask, name = model_ask()
        if ask is None:
            return {"actions": [], "sure": False, "error": f"the local model cannot run now: {name}", "how": "none"}
        how = name
    try:
        answer = ask(model_prompt(text, world))
    except Exception as err:        # noqa: BLE001 - the server, the network, a timeout
        return {"actions": [], "sure": False, "error": f"the local model did not answer ({err})", "how": how}
    return parse_answer(answer) | {"how": how}


def parse_answer(answer):
    m = re.search(r"\{.*\}", answer or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {"actions": [], "sure": False, "error": "the model's answer was not a list of actions"}
    actions = data.get("actions")
    if not isinstance(actions, list):
        actions = []
    actions = [a for a in actions if isinstance(a, dict) and a.get("action") != "unknown"]
    error = str(data.get("error") or "").strip()
    return {"actions": actions, "sure": data.get("sure") is not False, "error": error[:200]}


# -- doing ---------------------------------------------------------------------------------
def hypr_eval(lua):
    try:
        out = subprocess.run(["hyprctl", "eval", lua], capture_output=True, text=True, timeout=5)
        return out.returncode == 0 and not out.stdout.lstrip().lower().startswith("error")
    except (OSError, subprocess.SubprocessError):
        return False


def run_op(op):
    """One op; "" when it went, else the problem."""
    kind, what = op
    if kind == "auto":
        problems = automations().do_actions({"id": "voice-command", "do": [what]}, event="voice")
        return "; ".join(problems)
    if kind == "lua":
        return "" if hypr_eval(what) else "Hyprland refused it"
    try:
        if kind == "detach":
            subprocess.Popen(what, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ""
        done = subprocess.run(what, capture_output=True, text=True, timeout=60)
        if done.returncode:
            tail = (done.stderr or done.stdout).strip().splitlines()
            return f"exit {done.returncode}" + (f" ({tail[-1][:120]})" if tail else "")
        return ""
    except subprocess.TimeoutExpired:
        return "took too long"
    except OSError as err:
        return str(err)


def before(step, world):
    """What the Undo needs, read just before the step runs."""
    kind = step.get("undo")
    if kind == "theme":
        return world.current_theme()
    if kind in ("dnd", "dnd-for"):
        return world.dnd()
    if kind == "sound-output":
        return world.sink()
    if kind == "timer":
        return world.timer_ids()
    if kind == "volume":
        return world.muted()
    if kind == "close":
        return closed_stack(world)
    return None


def closed_stack(world):
    get = getattr(world, "closed_stack", None)
    return get() if get else []


def newly_closed(was, world, wait_s=1.5):
    """How many windows closed-windows.py put on its stack since `was` (its
    newest-first list before the close). It leaves out dialogs, second
    windows of an app, windows open < 3 s -- and an app may ask "close?" --
    so this is what a reopen would really bring back; waits for it a moment."""
    new = []
    for _ in range(int(wait_s / 0.3) + 1):
        now = closed_stack(world)
        new = now if not was else now[:next((i for i, item in enumerate(now) if item == was[0]), len(now))]
        if new:
            break
        time.sleep(0.3)
    return len(new)


def undo_ops(step, was, world):
    """The ops that take a done step back, [] when there is nothing cheap."""
    kind = step.get("undo")
    if kind == "theme" and was:
        return [("auto", {"action": "theme", "value": was})]
    if kind == "dnd":
        return [("auto", {"action": "dnd", "value": "on" if was else "off"})]
    if kind == "dnd-for":
        return [("argv", ["systemctl", "--user", "stop", f"{DND_UNIT}.timer"]),
                ("auto", {"action": "dnd", "value": "on" if was else "off"})]
    if kind == "gamemode":
        return [("auto", {"action": "gamemode", "value": "off" if step.get("value") == "on" else "on"})]
    if kind == "sound-output" and was:
        return [("argv", py("sound-settings.py", "default", was))]
    if kind == "move":
        ops = []
        for w in step.get("windows") or []:
            t = lua_target(w["address"])
            ops.append(("lua", f'hl.dispatch(hl.dsp.window.move({{ workspace = "{lua_esc(w["workspace"])}", '
                               f'follow = false, window = {t} }}))'))
            if w.get("floating"):
                ops.append(("lua", f'hl.dispatch(hl.dsp.window.float({{ action = "enable", window = {t} }}))'))
        return ops
    if kind == "fullscreen":
        return [("lua", f"hl.dispatch(hl.dsp.window.fullscreen({{ window = {lua_target(w['address'])} }}))")
                for w in step.get("windows") or []]
    if kind == "close":     # only what closed-windows.py really kept: never an older window
        count = min(newly_closed(was, world), len(step.get("windows") or []))
        return [("argv", py("closed-windows.py", "reopen")) for _ in range(count)]
    if kind == "workspace" and step.get("from"):
        return [("lua", f"hl.dispatch(hl.dsp.focus({{ workspace = {int(step['from'])} }}))")]
    if kind == "timer" and was is not None:
        new = sorted(world.timer_ids() - set(was))
        return [("argv", py("timers.py", "cancel", tid)) for tid in new if tid]
    if kind == "volume":
        return [("argv", ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if was else "0"])]
    return []


def execute(steps, world):
    """Run the steps in order. (problems, undo ops) -- the undo in reverse
    order, so taking it back unwinds."""
    problems, undo = [], []
    for step in steps:
        was = before(step, world)
        failed = [p for p in (run_op(op) for op in step["ops"]) if p]
        if failed:
            problems.append(f"{step['say']}: {failed[0]}")
            log(f"failed: {step['action']}: {failed[0]}")
            continue
        log(f"done: {step['action']}: {step.get('log', step['say'])}")
        if step.get("undo"):
            undo = undo_ops(step, was, world) + undo
    return problems, undo


# -- telling (notifications) -------------------------------------------------------------
class Notifier:
    """notify-send, one bubble replaced in place. buttons() waits for a
    click (or the timeout) and says which."""

    def __init__(self, replace=None):
        self.id = replace

    def _argv(self, title, body, timeout, urgency="normal"):
        argv = [NOTIFY, "-a", "Voice commands", "-i", "audio-input-microphone", "-u", urgency,
                "-t", str(timeout), "-p", "-h", "string:x-canonical-private-synchronous:voice"]
        if self.id:
            argv += ["-r", str(self.id)]
        return argv

    def tell(self, title, body="", timeout=5000, urgency="normal"):
        try:
            out = subprocess.run(self._argv(title, body, timeout, urgency) + [title, body],
                                 capture_output=True, text=True, timeout=10).stdout
            self.id = out.strip().splitlines()[0] if out.strip() else self.id
        except (OSError, subprocess.SubprocessError, IndexError):
            pass

    def buttons(self, title, body, buttons, timeout):
        """The key of the button clicked, or None (closed, timed out)."""
        argv = self._argv(title, body, timeout * 1000, "critical" if "confirm" in dict(buttons) else "normal")
        for key, label in buttons:
            argv += ["-A", f"{key}={label}"]
        try:
            out = subprocess.run(argv + ["--wait", title, body], capture_output=True, text=True,
                                 timeout=timeout + 5).stdout.split()
        except (OSError, subprocess.SubprocessError):
            return None
        if out and out[0].isdigit():
            self.id = out[0]
        keys = {k for k, _ in buttons}
        return next((w for w in reversed(out) if w in keys), None)


def speak_back(lang, line):
    """The outcome said aloud (ANSWERING BY VOICE); tts.py decides whether."""
    try:
        return bool(_module("tts", "tts.py").speak(line, lang=lang, feature="commands"))
    except Exception as err:    # noqa: BLE001 -- no voice costs the command nothing
        log(f"no spoken reply: {type(err).__name__}")
        return False


def summary_lines(steps, refused, lang):
    lines = [f"• {s['say']}" + (f"  ({s['confirm']})" if s["confirm"] else "") for s in steps]
    lines += [f"✗ {r}" for r in refused]
    return "\n".join(lines)


def handle(text, lang=None, world=None, notifier=None, ask=None, conf=None):
    """The whole command: understand, check, tell, ask when it has to, do,
    offer Undo. Returns what happened, for the log and the tests."""
    conf = conf or settings()
    world = world or World()
    notifier = notifier or Notifier()
    text = " ".join(str(text or "").split())
    lang = lang if lang in ("es", "en") else (conf["language"] if conf["language"] in ("es", "en")
                                               else guess_language(text))
    w = WORDS[lang]
    if conf["commands"] != "on":
        notifier.tell(w["off"], w["off_body"])
        return {"result": "off"}
    if not text:
        notifier.tell(w["nothing"], "")
        return {"result": "empty"}
    notifier.tell(f"{w['heard']}: “{text[:120]}”", w["thinking"], timeout=0)
    got = understand(text, world, ask)
    steps, refused = plan(got["actions"], world, lang, got["sure"], conf["confirm"])
    if got["error"]:
        refused.insert(0, got["error"])
    log(f"heard {text!r} ({lang}, {got['how']}) -> " +
        (json.dumps([{"action": s["action"], "say": s.get("log", s["say"]), "confirm": s["confirm"]} for s in steps],
                    ensure_ascii=False) if steps else "nothing") +
        (f"; refused: {'; '.join(refused)}" if refused else ""))
    title = f"{w['heard']}: “{text[:120]}”"
    if not steps:
        notifier.tell(title, f"{w['refused']}: " + ("; ".join(refused) or w["nothing"]), timeout=7000,
                      urgency="normal")
        speak_back(lang, f"{w['refused']}: " + ("; ".join(refused) or w["nothing"]))
        return {"result": "refused", "refused": refused, "how": got["how"]}
    body = summary_lines(steps, refused, lang)
    if any(s["confirm"] for s in steps):
        speak_back(lang, f"{w['ask']} " + "; ".join(s["say"] for s in steps))
        pick = notifier.buttons(f"{title}  —  {w['ask']}", body,
                                [("confirm", w["confirm"]), ("cancel", w["cancel"])], CONFIRM_S)
        if pick != "confirm":
            log("cancelled" if pick == "cancel" else "not confirmed in time")
            notifier.tell(title, w["cancelled"], timeout=2000)
            speak_back(lang, w["cancelled"])
            return {"result": "cancelled", "steps": steps, "refused": refused, "how": got["how"]}
    problems, undo = execute(steps, world)
    done = f"{w['done'] if not problems else w['failed']}\n{body}"
    if problems:
        done += "\n" + "\n".join(f"✗ {p}" for p in problems)
    speak_back(lang, f"{w['done'] if not problems else w['failed']}: " + "; ".join(s["say"] for s in steps))
    if undo and not problems:
        pick = notifier.buttons(title, done, [("undo", w["undo"])], UNDO_S)
        if pick == "undo":
            failed = [p for p in (run_op(op) for op in undo) if p]
            log("undone" + (f" (problems: {'; '.join(failed)})" if failed else ""))
            notifier.tell(title, w["undone"] + ("" if not failed else f": {failed[0]}"), timeout=2500)
            return {"result": "undone", "steps": steps, "refused": refused, "how": got["how"]}
    else:
        notifier.tell(title, done, timeout=6000 if not problems else 9000,
                      urgency="critical" if problems else "normal")
    return {"result": "failed" if problems else "done", "steps": steps, "refused": refused,
            "problems": problems, "how": got["how"]}


# -- the command line -----------------------------------------------------------------------
def read_handoff(path):
    """The transcript voice.py left in tmpfs, deleted as soon as it is read.
    Only voice.py's own hand-off files: `run` never reads (or deletes) any
    other file it is pointed at."""
    real = os.path.realpath(path)
    if os.path.dirname(real) != os.path.realpath(HANDOFF_DIR) or \
            not re.fullmatch(r"command-\d+\.txt", os.path.basename(real)):
        log(f"not a hand-off file, left alone: {path}")
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read(4000)
    except OSError:
        return ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return text


def option(rest, flag):
    if flag in rest:
        i = rest.index(flag)
        if i + 1 < len(rest):
            value = rest[i + 1]
            del rest[i:i + 2]
            return value
    return None


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], list(argv[1:])
    as_json = "--json" in rest
    rest = [r for r in rest if r != "--json"]
    lang = option(rest, "--lang")
    replace = option(rest, "--replace")
    if cmd in ("run", "text") and rest:
        notifier = Notifier(replace)
        try:
            result = handle(read_handoff(rest[0]) if cmd == "run" else " ".join(rest), lang, notifier=notifier)
        except Exception as err:    # noqa: BLE001 - never leave "Understanding…" up for good
            log(f"crashed: {type(err).__name__}: {err}")
            notifier.tell("Voice command failed", f"{type(err).__name__}: {err}"[:200], timeout=6000,
                          urgency="critical")
            raise
        if cmd == "text":
            print(result["result"])
    elif cmd == "plan" and rest:
        text = " ".join(rest)
        conf = settings()
        lang = lang or (conf["language"] if conf["language"] in ("es", "en") else guess_language(text))
        world = World()
        got = understand(text, world)
        steps, refused = plan(got["actions"], world, lang, got["sure"], conf["confirm"])
        if got["error"]:
            refused.insert(0, got["error"])
        if as_json:
            print(json.dumps({"how": got["how"], "actions": got["actions"], "refused": refused,
                              "steps": [{"action": s["action"], "say": s["say"], "confirm": s["confirm"],
                                         "ops": [[k, v if isinstance(v, (str, dict)) else shlex.join(v)]
                                                 for k, v in s["ops"]]} for s in steps]}, ensure_ascii=False))
        else:
            print(f"understood by: {got['how']}")
            print(summary_lines(steps, refused, lang) or "nothing")
    elif cmd == "catalog":
        if as_json:
            print(json.dumps({name: {"args": spec, "en": en, "es": es} for name, (spec, _a, en, es)
                              in CATALOG.items()}, ensure_ascii=False))
        else:
            for name in CATALOG:
                print(f"{name:14} {ARG_HELP[name]}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
