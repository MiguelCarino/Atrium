#!/usr/bin/env python3
"""LLM chat: a chat window for language models -- local ones in LM Studio,
any OpenAI-compatible server, and (optionally) Claude through Claude Code --
with the desktop theme's mascot acting out what it is doing while it works
(LLM ♡ 萌え in moe, its first theme).

A plain GTK3 window (not layer-shell: it is a place to read, scroll and come
back to, so it tiles and takes focus like any app; app id "llm-chat").
The top is the mascot's stage -- the theme's ASCII animation (mascots.py:
moe's cat-eared girl, matrix's hacker, win95's paperclip, aero's glass orb,
cyberpunk's android) on the theme's dark card, a speech bubble over it --
the middle the conversation, the bottom a box to type the next message in
and a status line.

    llm-chat.py                           open it, the input box focused
    llm-chat.py PROMPT ...                open it and send PROMPT at once (the
                                          words joined by spaces; this is what
                                          the launcher's "?question" runs)
    llm-chat.py --image FILE ...          FILE attached to that first message
                                          (the launcher's "about the screen /
                                          clipboard"); may be given again
    llm-chat.py --cwd DIR ...             work in DIR: the tools' working
                                          directory (default: $HOME)
    llm-chat.py --resume SESSION_ID       continue that session (one of this
                                          window's, chat-…, or a Claude Code
                                          one when claude is installed); a
                                          PROMPT given too is its next message
    llm-chat.py --model NAME              that model: a local LM Studio
                                          model's alias or key, server:ID (the
                                          OpenAI-compatible server's), or --
                                          with Claude Code installed -- a
                                          Claude alias (fable, opus, sonnet,
                                          haiku), a full id or "default"
                                          (llm_models.py); an unknown NAME is
                                          said in the transcript and the
                                          default used
    llm-chat.py --render OUT.png          the window drawn off screen with a
                                          sample exchange and two permission
                                          cards, saved, exit (never mapped,
                                          runs nothing)

TWO BACKENDS, one window. Which one a message goes to follows the model:

    native   every local (LM Studio) and server model: this window's own
             engine, llm_chat_engine.py -- the OpenAI chat-completions API,
             streamed, with its own tools (read_file, list_dir, search,
             run_command, write_file, edit_file) and its own saved sessions
             ($XDG_STATE_HOME/hypr/llm-chat/sessions). No Claude involved,
             and none needed. Its docstring has the details: the
             endpoints, the tool loop, Folder access for reading, what each
             permission mode lets through, the session files.
    claude   the Claude models, ONLY when the `claude` CLI is installed
             (llm_models.claude_cli()): one headless Claude Code run per
             message (below). Without it no Claude model is offered, and
             nothing here asks for it.

Between two models of one backend a conversation goes on; between the two
backends it cannot (a native conversation is plain messages, a Claude one
lives in Claude Code's session files): a new one starts, and a note says so.

Keys:

    Enter                 send (a message typed while a reply is still being
                          written is queued and sent when it finishes)
    Shift+Enter, Ctrl+Enter
                          a new line in the message
    Up / Down             in an empty box (or one still holding a recalled
                          message, unedited): the messages sent before, as
                          in a shell -- Up only from the first line, Down
                          only from the last, so a multi-line one can still
                          be walked through
    Esc                   while running: stop (native: the stream cut, a
                          running command's process group ended, every open
                          question a no; Claude: SIGINT to claude's process
                          group, SIGTERM 2 s later, SIGKILL 2 s after that);
                          idle: close the window. Stop is not unload: a
                          local model stays loaded in LM Studio (holding the
                          card's memory until its idle TTL) -- Ctrl+M's
                          "Unload …" gives it back
    Alt+A / Alt+S / Alt+D the oldest open permission card: allow once /
                          allow for this session / deny (Tab reaches its
                          buttons and its note too; Enter in the note denies)
    Ctrl+P                the Permissions menu: Ask me / Auto / Accept edits
                          / Plan, this session's allow rules, notifications
    Ctrl+V                an image on the clipboard (a screenshot) is
                          attached to the next message, copied image files
                          too; other copied files are typed in as paths.
                          Files dropped on the conversation or the box work
                          the same. Each attachment is a pill over the box,
                          ✕ takes it off
    Ctrl+F                find in the conversation: Enter the match above,
                          Shift+Enter below, Esc closes
    Ctrl+O                recent sessions, any directory: this window's own
                          (the first message as the title) and, with Claude
                          Code installed, Claude Code's (its own title): a
                          pick draws that conversation again and the next
                          message goes on with it
    Ctrl+T                (a Claude model only) open the session in kitty
                          (`claude --resume ID` in the same directory), to go
                          on in Claude Code's own TUI
    Ctrl+N                a new session (forget the current one)
    Ctrl+M                the model picker (also the header's model button);
                          with a local model loaded, "Unload <model>" and
                          "Unload all local models" there
    Ctrl+J                the mascot menu: her mood now, and what she reacts
                          to (mascot_mood.py's settings)
    Ctrl+K                the mascot in a small card in a corner of the
                          conversation, or back on her stage; a click on the
                          card moves it to the next corner (both remembered
                          in $XDG_STATE_HOME/hypr/llm-chat.json)
    Ctrl+W, Ctrl+Q        close. Closing always ends a running reply and the
                          processes it started: each Claude run, and each
                          command the native engine runs, is its own process
                          group (start_new_session) and the group is killed.

THE NATIVE ENGINE in the window: a message is one llm_chat_engine.Run in a
thread; its events (reply text, reasoning, a tool call starting and its
result, a question for a permission card, usage, done) come to the GTK loop
through GLib.idle_add -- nothing blocks the window. The reply is rendered
live; reasoning (reasoning_content, or <think> … </think> written inline)
goes into a folded "thinking" row above it; each tool call is a chip
("⚙ run_command  make test") with its output folded under it. The
conversation is the engine's messages, kept here and written to the
session file after every answer; Ctrl+O lists those files, and a pick
draws the conversation again (the tool calls as chips) and goes on with
it. A model that takes no tools gets plain chat, and the status line says
"no tools". A picture goes as an image_url part; a model that cannot see
it fails with an error saying so, and that message is not kept. The status
line counts the context from the server's usage against llm.json's context
(a local model) -- a server model's size is not known.

HOW IT TALKS TO CLAUDE (a Claude model, Claude Code installed): one
headless run per message,

    claude -p --output-format stream-json --verbose --include-partial-messages
           --input-format stream-json --permission-prompt-tool stdio
           --permission-mode MODE [--resume SESSION_ID] [--model M]

(MODE: the Permissions pick, below)

in the --cwd directory, the message on stdin as one stream-json user message
(the words; with images, the images base64, scaled to 1568 px, then the
words) -- so a message that starts with "-" is never read as a flag. stdin
stays open for the run's permission answers and is closed at its result
(claude would wait for another message otherwise). stdout is JSON lines, read from a GLib watch
on the pipe -- never a blocking read in the GTK loop -- and buffered as bytes
until each newline, so a line split across reads or holding bad UTF-8 is
still whole when parsed. The events used:

    system/init           the session id, model, cwd, permission mode
    stream_event          content_block_start (a text, thinking or tool_use
                          block begins), content_block_delta text_delta (the
                          reply as it is written, rendered live)
    assistant             the finished blocks: text replaces what was
                          streamed for it; tool_use fills in its chip's
                          summary ("⚙ Bash  ls ~/.config")
    user                  tool_result: the chip turns done (or error) and
                          gets a folded excerpt of the output
    result                cost, duration, turns, is_error, permission
                          denials -- the run's end
    control_request       can_use_tool: a permission card (below); any
                          other subtype is answered with an error
    control_cancel_request  the question taken back: its card says so
    anything else         ignored; a line that is not JSON is skipped

The next message resumes the session (--resume, the id from init / result).
stderr is kept (the last 16 KB) and shown if the run fails. The status line
counts the context: the last reply's tokens (input, cached, output) against
the model's window from the result's modelUsage (200k until one says), and
the cost (Claude runs only).

PERMISSIONS (Ctrl+P, the header's shield button). A tool call that needs a
yes shows as a card in the conversation WHILE the reply waits -- from the
native engine (Run.answer) or from Claude Code's control protocol (the
Agent SDK's canUseTool; verified with Claude Code 2.1.306, the messages are
in the comment above can_use_tool()): the tool, a readable summary (the
command; the path; for an edit a -/+ line count and the changed lines; a
write's size and whether it replaces a file; a plan's first lines),
warnings (a path outside the working directory, one Folder access calls
secret or a system folder -- folder_access.refused, read only, its store
untouched -- and claude's own reason for asking), and

    Allow once            it runs (Claude: {"behavior": "allow",
                          "updatedInput": the input})
    Allow for this        the same, and a rule kept in this window until the
      session             conversation ends (Ctrl+N, another session,
                          closing): Claude Code's own suggestion when it made
                          one ("touch made.txt", "npm run:*"), else a file
                          tool in the file's folder, a command exactly,
                          another tool by name. For Claude it goes with the
                          answer as updatedPermissions, destination
                          "session" (never a settings file); a later request
                          it covers -- in this run or the next -- is allowed
                          at once, with a note. A "prefix:*" rule never
                          covers a command holding ; & | ` $( < > or a
                          newline.
    Deny                  the model reads "The user denied this in the chat
                          window[: the card's note]" as the tool's result and
                          goes on (Claude: {"behavior": "deny", "message"})

The buttons arm after 0.6 s (a key already on its way does not answer); the
card never takes the keyboard from the input box. While a card waits the
mascot is curious and her bubble asks; Esc still stops the run (every open
card then says it is no longer asked).

The modes, remembered in llm-chat.json ("permissions"); what they let
through for the native engine is llm_chat_engine.policy():

    Ask me        everything that changes something asks (native: every
                  write_file, edit_file, run_command; reads go, through
                  Folder access). The default for a new window
    Auto          native: a command on the read-only list (ls, cat, git
                  status…, one plain command, its paths readable) goes, the
                  rest asks. Claude: --permission-mode auto, its classifier
                  lets ordinary work through, what it is unsure of asks
    Accept edits  file edits go ahead (native: inside the working
                  directory); commands ask
    Plan          read-only: native offers only the reading tools and
                  refuses a write it is asked for anyway; Claude plans, and
                  leaving plan mode (ExitPlanMode, the plan on the card) asks

$LLM_CHAT_PERMISSION, if set, is the window's first mode instead (a key
above, or for Claude any --permission-mode). What a Claude run was refused
without asking -- Auto's classifier, a deny rule -- still shows at its end,
with a button that allows exactly that for one more run (--allowedTools: a
Bash command as it was, another tool by name) and asks claude to retry;
what you denied on a card is not offered again. Should a claude turn the
protocol's flags down (a run that ends without a result, its stderr naming
them), the window drops back to that after-the-fact way for the rest of its
life and says so.

Notifications, while the window is not focused (GTK is-active), through
notify-send -a "LLM chat" (one app name for every theme, so mako groups
them): a finished reply (its first line), a failed one, and a permission
waiting (critical). A click (mako's left click: the default action, "Open")
focuses this window: its address by our pid from `hyprctl clients -j`, then
the Lua dispatcher `hl.dsp.focus({ window = 'address:…' })` (this config has
no `dispatch focuswindow`). There are no Allow / Deny buttons on the
notification: mako here invokes only the default action, and a yes should
be given looking at the card. They are taken down when the window gets the
focus, and a permission's when its card is answered. Do Not Disturb (mako's
do-not-disturb mode): finished and failed replies are not sent at all; a
permission wait is (critical: mako's [mode=do-not-disturb urgency=critical]
shows it), since a reply stuck on a question waits forever. The toggle is
in the Permissions menu and Settings > AI & models, saved as llm-chat.json
"notify" (on unless set off) and read at each notification.

The model: --model, else $LLM_CHAT_MODEL, else the "default" of
~/.local/state/hypr/llm.json (llm_models.py) -- when that names a Claude
model and Claude Code is not installed, the first local model, and a note
says so. The header's model button lists them -- LM Studio's (from `lms ls`,
cached), the server's (its /models, asked in a thread when the menu opens,
when a server is set), and Claude's when claude is installed -- the current
one ticked; a pick is for the NEXT message. "Make default" writes the pick
to llm.json (the launcher's "?" uses it too). Before a local model's first
message LM Studio's server is started and the model loaded with llm.json's
context (llm_models.ensure_local, in a thread: the mascot's bubble says
"loading …", a message typed meanwhile is queued, Esc gives up). Whether a
local model is loaded right now, and how long until LM Studio unloads it
idle (its TTL), is in the status line and as ● / ○ on the model button:
looked up (local_loaded: `lms ps`, only when LM Studio is running -- /proc
says, it is never woken to ask) in a thread when the model menu opens, a
local model is picked, and after a local reply, and counted down from that
look in between (never `lms` per keystroke or per frame). The menu then
lists "Unload <model>" for each loaded one and "Unload all local models":
`llm-gpu.py unload KEY|--all` in a thread, the card's memory (nvidia-smi)
and RAM (MemAvailable) read before and after, what it freed said in the
status line. Not while a reply is going (or a model is being readied): a
note says to stop it first, with a "Stop and unload" button that stops the
reply and unloads when it has ended.
$LLM_CHAT_TRACE, if set, is a file that gets a line per mascot state
change ("epoch theme state tool"), for tests that screenshot a state.

The look follows the desktop theme (~/.config/themes/README): llm-chat.css
next to this file is the cyberpunk base, and imports the theme's override
(themes/<name>/llm-chat.css, copied by theme.py to
~/.config/waybar/generated/theme-llm-chat.css) and the wallpaper accent.
That folder is watched: when `theme.py set` (or apply, or a new accent)
rewrites those files, an open window reloads its stylesheet, its words
(Japanese only for a lang=ja theme), the colours of its reply markup (the
stylesheet's md-* names) and its mascot, without a restart. The mascot's
grid is sized from the
stage's allocation and the mono font's cell (Pango), and made again on resize.
A window 1100 px wide or more has the stage in a column on the right (45 % of
the width), the conversation and input box beside it; under 1000 px it goes
back on top.
It animates at 10 fps while something happens, slows to 2.5 fps after 10 s of
quiet and stops after two minutes, until the next key or run.
Her mood is mascot_mood.py's (for a mascot that draws moods): the window tells it
what happens -- each prompt and finished reply (word matching), tool errors
and successes, the result, a run past a minute -- and draws its View every
frame: the mood and scene go to the mascot, the topic (an event soon, the
weather, "go home") to the bubble, worded by the mascot's say(). The
surroundings are re-read on a thread every minute; a changed scene is drawn
even while the animation sleeps. The header's mascot menu (Ctrl+J) shows the
mood and scene now and switches the moods, random only, and each signal on or
off; a change is saved to mascot.json and read again at once.
"""

import argparse
import base64
import fcntl
import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CSS_FILE = os.path.join(HERE, "llm-chat.css")
APP_ID = "llm-chat"
# The generated files that restyle an open window (theme.py writes them on
# `set` / `apply`, theme-from-wallpaper.py the accent): watched, see
# Front.watch_theme.
GEN_DIR = os.path.expanduser("~/.config/waybar/generated")
WATCHED = ("theme-llm-chat.css", "accent.css", "lang")

try:
    import theme as desktop_theme       # ~/.config/hypr/scripts/theme.py: no GTK
except Exception as exc:
    print(f"llm-chat: theme.py unavailable ({exc}); cyberpunk look", file=sys.stderr)
    desktop_theme = None

# Words per theme. Japanese only when the theme says lang=ja (moe), English
# otherwise; the title is the theme's own.
TITLES = {
    "moe": "LLM ♡ 萌え",
    "cyberpunk": "LLM // NEON",
    "matrix": "llm@matrix:~",
    "win95": "LLM Chat Assistant",
    "aero": "LLM chat",
}
UI_EN = {"stop": "■ Stop", "send": "Send", "wait": "Queue", "stopping": "Stopping…",
         "done": "✓ done", "placeholder": "Ask {model}…  (Enter send · Shift+Enter newline)",
         "copy": "⧉ copy", "copied": "✓ copied", "retry": "Allow these and retry",
         "find": "Find in the conversation…",
         # the permission card (live permission requests) and its mascot line
         "perm_title": "The model wants to use {tool}",
         "perm_once": "Allow once", "perm_session": "Allow for this session",
         "perm_deny": "Deny", "perm_note": "a note for the model, sent with Deny (optional)",
         "perm_keys": "Alt+A allow once · Alt+S this session · Alt+D deny",
         "perm_sure_once": "Sure? Run it once", "perm_sure_session": "Sure? Run these all session",
         "perm_sure_hint": "This runs code on your computer: click again (or press the same key "
                           "again) to confirm",
         "perm_bubble": "May I? Waiting for you…",
         "perm_allowed": "✓ allowed once", "perm_allowed_session": "✓ allowed for this session: {rule}",
         "perm_denied": "✗ denied", "perm_auto": "✓ {rule} (allowed for this session)",
         "perm_gone": "— no longer asked (the reply ended or the model moved on)",
         # the desktop notifications, while the window is in the background
         "n_done": "The model answered", "n_failed": "LLM chat: the reply failed",
         "n_perm": "The model is waiting for your permission", "n_open": "Open",
         # unloading a local model (the model menu)
         "unload": "Unload {model}", "unload_all": "Unload all local models"}
UI_THEME = {
    "cyberpunk": {"send": "Send ▸", "wait": "Queue ▸",
                  "placeholder": "Jack in, choom… ask {model}  (Enter send · Shift+Enter newline)"},
    "matrix": {"stop": "■ kill", "send": "> send", "wait": "> queue", "done": "✓ exit 0",
               "placeholder": "> ask {model_lower}_   (Enter send · Shift+Enter newline)"},
    "win95": {"stop": "Stop", "send": "Send", "wait": "Queue", "done": "✓ Done",
              "placeholder": "Type your question for {model} here, and then click Send."},
    "aero": {"done": "✓ Done", "perm_bubble": "Waiting for your permission"},
}
UI_THEME["cyberpunk"]["perm_bubble"] = "Auth required, choom…"
UI_THEME["matrix"]["perm_bubble"] = "> awaiting authorization_"
UI_THEME["win95"]["perm_bubble"] = "It looks like the AI needs your permission."
UI_JA = {"stop": "■ 止める", "send": "送信 ♡", "wait": "待つ ♡", "stopping": "止めてる…",
         "done": "✿ できた",
         "placeholder": "ねえ、なにする？  Ask {model}…  (Enter send · Shift+Enter newline)",
         "copy": "⧉ コピー", "copied": "✓ コピーした", "retry": "許可してもう一回 ♡",
         "find": "さがす…",
         "perm_title": "{tool} を使ってもいい？",
         "perm_once": "今回だけ許可", "perm_session": "このセッション中は許可",
         "perm_deny": "だめ", "perm_note": "モデルへのひとこと（だめと一緒に送る・なくてもOK）",
         "perm_keys": "Alt+A 今回だけ · Alt+S このセッション · Alt+D だめ",
         "perm_sure_once": "ほんとに？ 一回だけ実行", "perm_sure_session": "ほんとに？ ずっと実行",
         "perm_sure_hint": "パソコンでコードを実行するよ：もう一回押して確認してね",
         "perm_bubble": "いい？ 待ってるね…",
         "perm_allowed": "✓ 今回だけ許可した", "perm_allowed_session": "✓ このセッション中は許可: {rule}",
         "perm_denied": "✗ だめって言った", "perm_auto": "✓ {rule}（このセッション中は許可）",
         "perm_gone": "— もう聞かれてない（実行が終わったか、先に進んだ）",
         "n_done": "モデルが答えたよ", "n_failed": "LLM chat: うまくいかなかった",
         "n_perm": "モデルが許可を待ってるよ", "n_open": "開く",
         "unload": "{model} をおろす", "unload_all": "ローカルモデルを全部おろす"}
# The face reply headings are drawn in, where the theme has one for it.
HEADING_FONT = {"moe": "Hachi Maru Pop", "aero": "Selawik", "win95": "W95FA"}

# A --permission-mode (or a Permissions key: ask, auto, acceptEdits, plan)
# that wins over the saved pick when the window opens; unset = the pick.
PERMISSION = os.environ.get("LLM_CHAT_PERMISSION", "").strip()
MODEL = os.environ.get("LLM_CHAT_MODEL", "").strip()
try:
    import llm_models           # the model registry and settings: no GTK
except Exception as exc:
    print(f"llm-chat: llm_models unavailable ({exc}); no model picker", file=sys.stderr)
    llm_models = None
# A file to append "time theme state tool" to on every mascot state change
# (for screenshots of a given state in tests); unset = nothing written.
TRACE = os.environ.get("LLM_CHAT_TRACE", "").strip()
try:
    import llm_chat_engine as engine    # the native backend: no GTK
except Exception as exc:
    print(f"llm-chat: llm_chat_engine unavailable ({exc}); only Claude models", file=sys.stderr)
    engine = None

FAST_MS = 100           # mascot frame interval while something happens
SLOW_MS = 400           # ... after QUIET_S of nothing
QUIET_S = 10
SLEEP_S = 120           # ... and no frames at all after this
DONE_TO_IDLE_S = 15     # "done" / "error" pose held this long, then "idle"
STDERR_KEEP = 16384
ART_MIN = (48, 14)      # the smallest grid a mascot draws whole; a stage
                        # smaller than that at the mono size scales her font down
ART_MAX = (160, 24)     # her natural size: a stage with room for more rows
                        # than these draws her font larger (to ART_SCALE_MAX)
ART_LIMIT = (480, 120)  # the grid itself always fills the stage edge to edge
                        # (the scenery is painted cell backgrounds, a smaller
                        # grid left it ending in a hard edge), up to this
CORNER_SHARE = 0.32     # the corner card (Ctrl+K): this share of the
CORNER_W = (320, 560)   # conversation's width, within these px, and 0.62
                        # times as tall (250 px at least)
CORNERS = ("top-right", "bottom-right", "bottom-left", "top-left")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
FRONT_STATE = os.path.join(STATE_DIR, "llm-chat.json")     # {"corner", "where", "permissions", "notify"}
# The window's settings before it was renamed: copied once into
# FRONT_STATE when that does not exist yet (the old file is left as it is).
OLD_STATE = os.path.join(STATE_DIR, "claude-front.json")
ART_SCALE_MIN, ART_SCALE_MAX = 0.6, 2.0
SIDE_AT = 1100          # a window this wide (px) puts the stage in a column on
STACK_AT = 1000         # the right, beside the conversation; narrower than
                        # STACK_AT puts it back on top (the gap: no flapping
                        # while a drag of the window's edge crosses one width)
SIDE_SHARE = 0.45       # the column's share of the width, 380 px at least
SIDE_MIN_W = 380

# The look of the markup llm-chat writes itself (reply headings,
# bullets, links, `code` spans): Front.apply_theme fills it from the theme --
# the colours from the stylesheet's md-* names (GTK lookup_color), the mono
# face from theme.conf font_mono. These are cyberpunk's, until then.
LOOK = {
    "theme": "cyberpunk", "lang": "en", "mono": "IBM Plex Mono", "heading": None,
    "accent": "#00f0ff", "dim": "#8fb4c4", "code_fg": "#ff6b96", "code_bg": "#141a26",
    "stage_fg": "#c8d3e6",
    "copy": UI_EN["copy"], "copied": UI_EN["copied"],     # the copy buttons' words
}

try:
    import mascots
except Exception as exc:  # absent or broken: the stage shows a kaomoji only
    print(f"llm-chat: mascots unavailable ({exc}); using a plain stand-in",
          file=sys.stderr)
    mascots = None
try:
    import mascot_mood          # her mood and scene: no GTK
except Exception as exc:
    print(f"llm-chat: mascot_mood unavailable ({exc}); no moods", file=sys.stderr)
    mascot_mood = None
MOOD_REFRESH_S = 60     # the surroundings (weather, calendar, ...) re-read this often
try:
    import folder_access        # Settings > Folder access: a permission card's warnings
except Exception:               # noqa: BLE001  (a hint only)
    folder_access = None


class _StandIn:
    """What the stage draws without moe_mascot.py: one centred face. Same
    interface (lines / markup / bubble), so nothing else has to know."""

    FACES = {"idle": "(｡•ᴗ•｡)", "thinking": "(・・?)", "tool": "(ง •̀_•́)ง",
             "writing": "φ(..)", "done": "(≧◡≦) ♡", "error": "(╥﹏╥)"}

    def __init__(self, cols=64, rows=18):
        self.cols, self.rows = cols, rows

    moods = False

    def lines(self, state, tick, tool=None, mood=None, scene=()):
        out = [" " * self.cols for _ in range(self.rows)]
        face = self.FACES.get(state, self.FACES["idle"])
        out[self.rows // 2] = face.center(self.cols)
        return out

    def markup(self, state, tick, tool=None, mood=None, scene=()):
        text = html.escape("\n".join(self.lines(state, tick, tool)), quote=False)
        return f'<span foreground="{LOOK["stage_fg"]}">{text}</span>'

    def bubble(self, state, tool=None, mood=None):
        return {"idle": "なにする？", "thinking": "うーん…", "tool": f"{tool or 'tool'} がんばる！",
                "writing": "かきかき…", "done": "できた！", "error": "あれれ…"}.get(state, "…")


def make_mascot(cols, rows, theme="moe"):
    if mascots is not None:
        try:
            return mascots.Mascot(cols, rows, theme=theme)
        except Exception as exc:
            print(f"llm-chat: Mascot({cols}, {rows}, {theme}) failed: {exc}", file=sys.stderr)
    return _StandIn(cols, rows)


def find_claude():
    """The claude CLI, or None: Claude models are offered only with it."""
    return llm_models.claude_cli() if llm_models is not None else None


def descendants(pid):
    """Every live process below `pid`, from /proc (ppid links). Claude runs
    its tools -- a Bash command, a background job -- in process groups of
    their own, so killing claude's group alone would orphan them if claude
    itself were killed before it could end them."""
    children = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as fh:
                stat = fh.read()
        except OSError:
            continue
        # comm may hold spaces and parens: the fields start after the last ")".
        fields = stat[stat.rfind(b")") + 2:].split()
        if len(fields) > 1:
            children.setdefault(int(fields[1]), []).append(int(entry))
    out, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), ()):
            out.append(child)
            todo.append(child)
    return out


def kill_pids(pids, sig=signal.SIGKILL):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def allow_rule(tool, data):
    """The --allowedTools rule for one refused call: a Bash command exactly
    as it was, any other tool by its name (for the one run it is given to)."""
    if tool == "Bash" and isinstance(data, dict) and data.get("command"):
        return f"Bash({data['command']})"
    return tool if tool and tool != "?" else None


# -- permissions: the stream-json control protocol ----------------------------
# Every run is started with --input-format stream-json --permission-prompt-tool
# stdio, so a tool call that would need a yes reaches this window as a line on
# stdout (verified against Claude Code 2.1.306):
#
#   {"type": "control_request", "request_id": "…", "request": {
#       "subtype": "can_use_tool", "tool_name": "Bash", "input": {…},
#       "permission_suggestions": [{"type": "addRules", "rules": [{"toolName":
#       "Bash", "ruleContent": "touch made.txt"}], "behavior": "allow",
#       "destination": "localSettings"}, …], "blocked_path": "…",
#       "decision_reason": "…", "tool_use_id": "toolu_…", …}}
#
# and is answered with a line on stdin -- the run waits until it is:
#
#   {"type": "control_response", "response": {"subtype": "success",
#       "request_id": "…", "response": {"behavior": "allow", "updatedInput":
#       {…}, "updatedPermissions": [...]}}}           (or)
#       "response": {"behavior": "deny", "message": "…"}
#
# A "control_cancel_request" {request_id} takes a question back (the turn
# was interrupted); any other control_request subtype is answered with an
# error response (this window registers no hooks or SDK MCP servers).

# The Permissions menu (Ctrl+P): key, label, the --permission-mode it runs, what it means.
PERM_MODES = (
    ("ask", "Ask me", "default",
     "every action that changes something waits for your yes, on a card in the conversation"),
    ("auto", "Auto", "auto",
     "read-only commands (ls, cat, git status…) go, the rest asks; with Claude, its classifier "
     "lets ordinary work through and asks about what it is unsure of"),
    ("acceptEdits", "Accept edits", "acceptEdits",
     "file edits go ahead (a local model's: inside the working directory); commands ask"),
    ("plan", "Plan (read-only)", "plan", "the model reads and plans only; it changes nothing"),
)
PERM_KEYS = tuple(k for k, *_ in PERM_MODES)
PERM_DEFAULT = "ask"        # verified: see the block above
DENY_MESSAGE = "The user denied this in the chat window."
FILE_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Glob", "Grep", "LS")
# A Bash command holding any of these is more than one command (or writes
# somewhere): a "prefix:*" session rule never covers it.
_SHELL_JOIN = re.compile(r"[;&|`\n<>]|\$\(")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def perm_cli_mode(key):
    """The --permission-mode a Permissions key runs with; anything else (a
    CLI mode named in $LLM_CHAT_PERMISSION) as it is."""
    for k, _label, cli, _what in PERM_MODES:
        if key == k:
            return cli
    return key or "auto"


def perm_label(key):
    return next((label for k, label, *_ in PERM_MODES if k == key), key)


def start_permission(env_value, saved):
    """The window's first Permissions key: $LLM_CHAT_PERMISSION, else
    the saved pick (llm-chat.json "permissions"), else PERM_DEFAULT.
    The CLI's own names for asking ("default", "manual") are "ask"."""
    env = (env_value or "").strip()
    if env:
        return "ask" if env in ("default", "manual") else env
    return saved if saved in PERM_KEYS else PERM_DEFAULT


def can_use_tool(ev):
    """A control_request line asking for a tool, made plain: {id, tool,
    display, input, suggestions, blocked, reason, tool_use_id, agent}; None
    for any other line."""
    if not isinstance(ev, dict) or ev.get("type") != "control_request":
        return None
    req = ev.get("request")
    if not isinstance(req, dict) or req.get("subtype") != "can_use_tool" or not ev.get("request_id"):
        return None
    data = req.get("input") if isinstance(req.get("input"), dict) else {}
    tool = str(req.get("tool_name") or "?")
    suggestions = [s for s in req.get("permission_suggestions") or [] if isinstance(s, dict)]
    reason = _ANSI.sub("", str(req.get("decision_reason") or "")).strip()
    return {"id": str(ev["request_id"]), "tool": tool,
            "display": str(req.get("display_name") or req.get("title") or tool),
            "input": data, "suggestions": suggestions,
            "blocked": req.get("blocked_path") or None, "reason": reason or None,
            "tool_use_id": req.get("tool_use_id"), "agent": req.get("agent_id")}


def control_response(request_id, response):
    return {"type": "control_response",
            "response": {"subtype": "success", "request_id": request_id, "response": response}}


def allow_response(request_id, data, updated=None):
    """Yes: the input as it was (updatedInput, as the Agent SDK sends it;
    the recorded test run allowed with it), and for "this session" the
    rule, so the rest of this run does not ask again."""
    answer = {"behavior": "allow", "updatedInput": data if isinstance(data, dict) else {}}
    if updated:
        answer["updatedPermissions"] = updated
    return control_response(request_id, answer)


def deny_message(note=""):
    """What the model reads as a denied tool's result: the note in it, when
    one was typed (both backends)."""
    note = (note or "").strip()
    return f"The user denied this in the chat window: {note}" if note else DENY_MESSAGE


def deny_response(request_id, note=""):
    """No: claude reads `message` as the tool's result and goes on (it may
    try something else, or ask)."""
    return control_response(request_id, {"behavior": "deny", "message": deny_message(note)})


def error_response(request_id, text):
    return {"type": "control_response",
            "response": {"subtype": "error", "request_id": request_id, "error": text}}


def tool_path(data):
    if not isinstance(data, dict):
        return ""
    return str(data.get("file_path") or data.get("notebook_path") or data.get("path") or "")


def _abs(path, cwd):
    path = os.path.expanduser(path)
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd or "/", path))


def _under(path, folder):
    folder = folder.rstrip(os.sep) or os.sep
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def session_rule(req):
    """(rule, updatedPermissions) for "Allow for this session". The rule is
    {"tool", "content"} -- content as in Claude Code's own rules:
    "touch made.txt" (that exact command), "npm run:*" (a prefix), a path
    pattern, "domain:host", "dir:/abs" (a folder, for the file tools), or
    None (any call of the tool). Taken from the CLI's own suggestion when it
    made one (its destination changed to "session": nothing is ever written
    to a settings file from here), else the narrowest: a file tool in the
    file's folder, a Bash command exactly, another tool by name."""
    tool, data = req["tool"], req["input"]
    for s in req["suggestions"]:
        if s.get("type") == "addRules" and s.get("behavior") == "allow":
            rules = [r for r in s.get("rules") or [] if isinstance(r, dict) and r.get("toolName")]
            if rules and rules[0]["toolName"] == tool:
                r = rules[0]
                content = r.get("ruleContent") or None
                wire = {"toolName": tool, **({"ruleContent": content} if content else {})}
                return ({"tool": tool, "content": content},
                        [{"type": "addRules", "rules": [wire], "behavior": "allow",
                          "destination": "session"}])
    if tool in FILE_TOOLS:
        for s in req["suggestions"]:
            dirs = [d for d in s.get("directories") or [] if isinstance(d, str) and d]
            if s.get("type") == "addDirectories" and dirs:
                return ({"tool": tool, "content": "dir:" + dirs[0]},
                        [{"type": "addDirectories", "directories": dirs[:1], "destination": "session"}])
    path = tool_path(data)
    if tool in FILE_TOOLS and path:
        # The file's folder (a Glob / Grep path is one already): narrower
        # than every call of the tool, wide enough to be worth remembering.
        target = os.path.normpath(os.path.expanduser(path))
        folder = target if tool in ("Glob", "Grep") or os.path.isdir(target) else os.path.dirname(target)
        if os.path.isabs(folder):
            return ({"tool": tool, "content": "dir:" + folder},
                    [{"type": "addRules", "rules": [{"toolName": tool, "ruleContent": "/" + folder + "/**"}],
                      "behavior": "allow", "destination": "session"}])
    if tool == "Bash" and data.get("command"):
        command = str(data["command"]).strip()
        return ({"tool": tool, "content": command},
                [{"type": "addRules", "rules": [{"toolName": tool, "ruleContent": command}],
                  "behavior": "allow", "destination": "session"}])
    return ({"tool": tool, "content": None},
            [{"type": "addRules", "rules": [{"toolName": tool}], "behavior": "allow",
              "destination": "session"}])


def rule_matches(rule, tool, data, cwd):
    """Does a session rule cover this call? Narrow on purpose: a doubt asks."""
    if not isinstance(rule, dict) or rule.get("tool") != tool:
        return False
    content = rule.get("content")
    if content is None:
        return True
    data = data if isinstance(data, dict) else {}
    if tool == "Bash":
        command = str(data.get("command") or "").strip()
        if content.endswith(":*"):
            prefix = content[:-2].strip()
            if not prefix or _SHELL_JOIN.search(command):
                return False
            return command == prefix or command.startswith(prefix + " ")
        return command == content.strip()
    if content.startswith("domain:"):
        from urllib.parse import urlparse
        try:
            host = (urlparse(str(data.get("url") or "")).hostname or "").lower()
        except ValueError:
            return False
        want = content[len("domain:"):].lower()
        return bool(host) and (host == want or host.endswith("." + want))
    path = tool_path(data)
    if not path:
        return False
    target = _abs(path, cwd)
    if content.startswith("dir:"):
        return _under(target, _abs(content[4:], cwd))
    # Claude Code's path rules: //abs, ~/home, /relative-to-the-project, or relative.
    if content.startswith("//"):
        pattern = content[1:]
    elif content.startswith("/"):
        pattern = os.path.join(cwd or "/", content[1:])
    else:
        pattern = _abs(content, cwd)
    if pattern.endswith("/**"):
        return _under(target, os.path.normpath(pattern[:-3]))
    import fnmatch
    return fnmatch.fnmatchcase(target, os.path.normpath(pattern))


def rule_text(rule):
    content = rule.get("content")
    tool = rule.get("label") or rule["tool"]        # a native tool by its own name
    if content is None:
        return f"{tool} (any)"
    if content.startswith("dir:"):
        return f"{tool} in {short_path(content[4:])}"
    return f"{tool}({one_line(content, 60)})"


def backend(model):
    """"claude" for a Claude model (the claude CLI runs it), "native" for
    every other (llm_chat_engine). No registry at all: Claude's default."""
    if model is None:
        return "claude" if engine is None or llm_models is None else "native"
    return "claude" if model.kind == "claude" else "native"


def _diff_lines(old, new, limit=10):
    import difflib
    rows = [r for r in difflib.unified_diff(str(old).splitlines(), str(new).splitlines(),
                                            lineterm="", n=0)
            if not r.startswith(("---", "+++", "@@"))]
    shown = [r if len(r) <= 160 else r[:159] + "…" for r in rows[:limit]]
    if len(rows) > limit:
        shown.append(f"… (+{len(rows) - limit} more changed lines)")
    return shown


def perm_details(req, cwd):
    """What a permission card says: (headline, [detail lines], [warnings]).
    The headline is the command / path / URL; the details a diff summary
    for an edit, the size of a write, the first lines of a plan; the
    warnings a path outside the working directory, one folder_access.py
    would never let the desktop's AI read, and why the model asks."""
    tool, data = req["tool"], req["input"]
    details, warn = [], []
    path = tool_path(data)
    if tool == "Bash":
        head = str(data.get("command") or "")
        if data.get("description"):
            details.append(str(data["description"]))
    elif tool == "Edit":
        head = short_path(path)
        old, new = data.get("old_string") or "", data.get("new_string") or ""
        details.append(f"−{len(str(old).splitlines())} +{len(str(new).splitlines())} lines"
                       + ("  (every match)" if data.get("replace_all") else ""))
        details += _diff_lines(old, new)
    elif tool == "MultiEdit":
        head = short_path(path)
        edits = [e for e in data.get("edits") or [] if isinstance(e, dict)]
        details.append(f"{len(edits)} edit{'s' if len(edits) != 1 else ''}")
        for e in edits[:3]:
            details += _diff_lines(e.get("old_string") or "", e.get("new_string") or "", 4)
    elif tool == "Write":
        head = short_path(path)
        text = str(data.get("content") or "")
        exists = bool(path) and os.path.exists(_abs(path, cwd))
        details.append(f"{len(text.splitlines())} lines, {len(text.encode())} bytes — "
                       + ("replaces the file" if exists else "a new file"))
        details += [one_line(r, 160) for r in text.splitlines()[:4]]
    elif tool == "ExitPlanMode":
        head = "leave plan mode and start on the plan"
        details += [r for r in str(data.get("plan") or "").splitlines() if r.strip()][:12]
    else:
        head = tool_summary(tool, data) or ""
        if not head and data:
            head = one_line(json.dumps(data, ensure_ascii=False), 200)
    if path and cwd and not _under(_abs(path, cwd), os.path.normpath(cwd)):
        warn.append(f"outside the working directory ({short_path(cwd)})")
    if path and folder_access is not None:
        try:
            why = folder_access.refused(_abs(path, cwd))
        except Exception:       # noqa: BLE001  (a hint only)
            why = None
        if why:
            warn.append(f"Folder access: {why}")
    if req.get("reason"):
        warn.append("why it asks: " + one_line(req["reason"], 200))
    if req.get("agent"):
        details.append("(from a subagent)")
    return head, details, warn


# -- notifications ----------------------------------------------------------------
NOTIFY_APP = "LLM chat"         # notify-send -a: one name for every theme (mako groups by it)


def notify_decision(event, focused, dnd, enabled):
    """The urgency of a desktop notification for `event` ("done", "failed",
    "permission"), or None for none: never while the window has the focus
    (it is in front of you) or with the toggle off; a permission wait is
    critical and goes through Do Not Disturb (mako's [mode=do-not-disturb
    urgency=critical] shows it: a run stuck on a question waits forever);
    a finished or failed run is not sent at all in Do Not Disturb (the
    conversation keeps it)."""
    if not enabled or focused:
        return None
    if event == "permission":
        return "critical"
    if dnd:
        return None
    return "normal"


def dnd_on():
    try:
        out = subprocess.run(["makoctl", "mode"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "do-not-disturb" in out.split()


def first_line(text, limit=140):
    """The first line of an answer worth reading in a notification: markup
    signs off, blank lines and fences skipped."""
    for row in str(text or "").splitlines():
        if row.strip().startswith(("```", "~~~")):
            continue
        row = re.sub(r"^\s*(#{1,6}\s+|[-*+]\s+|>\s?|\d+[.)]\s+)", "", row).replace("**", "").replace("`", "")
        if row.strip():
            return one_line(row, limit)
    return ""


# -- local models: loaded or not, and unloading -------------------------------------
LLM_GPU = os.path.join(HERE, "llm-gpu.py")


def unload_refusal(busy, name):
    """Why an unload must wait (None: it may go). A run -- or a model being
    readied -- may be using the card; stopping it is the user's call."""
    if busy:
        return (f"a run is going: stop it first (Esc) before unloading {name} -- "
                "or use Stop and unload below")
    return None


def mem_snapshot():
    """{"vram": bytes in use on the card or None, "ram": MemAvailable bytes or None}."""
    vram = None
    if llm_models is not None:
        try:
            card = llm_models._gpu_module().gpu()
            vram = card["used"] if card else None
        except Exception:       # noqa: BLE001
            vram = None
    ram = None
    try:
        with open("/proc/meminfo") as fh:
            for row in fh:
                if row.startswith("MemAvailable:"):
                    ram = int(row.split()[1]) * 1024
                    break
    except (OSError, ValueError, IndexError):
        pass
    return {"vram": vram, "ram": ram}


def freed_text(before, after):
    """"freed 9.8 GB of graphics memory, 1.2 GB of RAM" from two mem_snapshot()s."""
    bits = []
    if before.get("vram") is not None and after.get("vram") is not None:
        bits.append(f"{max(0, before['vram'] - after['vram']) / 2**30:.1f} GB of graphics memory")
    if before.get("ram") is not None and after.get("ram") is not None:
        bits.append(f"{max(0, after['ram'] - before['ram']) / 2**30:.1f} GB of RAM")
    return ("freed " + ", ".join(bits)) if bits else ""


def local_loaded():
    """{modelKey: {"ident": lms's identifier, "ttl": seconds before LM Studio
    unloads it idle or None}} for the models loaded now ({} when LM Studio is
    down: then lms is never woken to ask). Blocking (lms ps): a thread."""
    if llm_models is None:
        return {}
    gpu_mod = llm_models._gpu_module()
    if not gpu_mod.running():
        return {}
    now_ms = time.time() * 1000
    return {r["modelKey"]: {"ident": r.get("identifier") or r["modelKey"],
                            "ttl": gpu_mod.ttl_left(r, now_ms)}
            for r in gpu_mod.lms_ps()}


def ttl_text(secs):
    if secs is None:
        return "stays loaded"
    if secs >= 3600:
        return f"unloads after {secs / 3600:.1f} h idle"
    return f"unloads after {max(1, round(secs / 60))} min idle"


def short_path(path):
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def kilo(n):
    """42_317 -> "42k", 1_000_000 -> "1M"."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.3g}M"
    return f"{round(n / 1000)}k" if n >= 1000 else str(n)


def one_line(text, limit=96):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


# -- light markdown -> Pango markup -----------------------------------------
# Enough for what a model writes: headings, **bold**, *italic*, `code`, fenced
# code blocks (their own widget, mono on night plum), bullet / numbered / task
# lists, quotes, rules, links, tables (kept monospaced so their columns line
# up). Every line is checked with Pango.parse_markup and falls back to plain
# escaped text if the regexes paired markers badly (**a *b** c*): bad markup
# must never reach a label.

_FENCE = re.compile(r"^\s*(```+|~~~+)\s*([\w+#.-]*)")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITALIC = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])"
                     r"|(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
# A URL may hold one level of balanced parentheses (wiki/Foo_(bar)); the
# first unbalanced ")" ends it.
_LINK = re.compile(r"\[([^\]]+)\]\((https?://(?:[^()\s\"<>]|\([^()\s\"<>]*\))+)\)")
# A closing run of "#" is only one with a space before it: "## Using C#"
# keeps its "#".
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d+)([.)])\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE = re.compile(r"^\s*\|.*\|\s*$")
# Only the line under the header, and only with three dashes a cell: a data
# row of "-" placeholders ("| - | - |") is a row.
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_TABLE_BAR = re.compile(r"(?<!\\)\|")


_A_OPEN = re.compile(r'<a href="[^"]*">')


def _valid(markup):
    """Pango's parser does not know <a> (GtkLabel handles it before Pango
    sees the text), so links are checked as plain spans."""
    markup = _A_OPEN.sub("<span>", markup).replace("</a>", "</span>")
    try:
        Pango.parse_markup(markup, -1, "\0")
        return True
    except GLib.Error:
        return False


def _emphasis(text, level):
    out = html.escape(text, quote=False)
    if level >= 1:
        out = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", out)
    if level >= 2:
        out = _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", out)
        out = _STRIKE.sub(lambda m: f"<s>{m.group(1)}</s>", out)
    return out


def _inline_plain(text, level):
    """Links are cut out before the emphasis passes, as code spans are: run
    over a finished <a href="...">, the __ of .../__init__.py became <b> in
    the URL (which _valid cannot see, its _A_OPEN taking the whole tag). The
    emphasis runs on the link's text and on the text between links only."""
    parts, last = [], 0
    for m in _LINK.finditer(text):
        parts.append(_emphasis(text[last:m.start()], level))
        href = html.escape(m.group(2), quote=True)
        parts.append(f'<a href="{href}">{_emphasis(m.group(1), level)}</a>')
        last = m.end()
    parts.append(_emphasis(text[last:], level))
    return "".join(parts)


def inline(text):
    """Code spans first (nothing inside them is markdown), then links, bold,
    italic. If the markers interleave into crossing tags, try again with
    fewer kinds (no italic, then no bold), and at worst plain text."""
    for level in (2, 1, 0):
        parts, last = [], 0
        for m in _CODE_SPAN.finditer(text):
            parts.append(_inline_plain(text[last:m.start()], level))
            code = html.escape(m.group(2).strip() or m.group(2), quote=False)
            parts.append(f'<span font_family="{LOOK["mono"]}" foreground="{LOOK["code_fg"]}" '
                         f'background="{LOOK["code_bg"]}">\u2009{code}\u2009</span>')
            last = m.end()
        parts.append(_inline_plain(text[last:], level))
        out = "".join(parts)
        if _valid(out):
            return out
    return html.escape(text, quote=False)


_HEADING_SIZE = {1: "x-large", 2: "large", 3: "medium"}


def md_line(line):
    m = _HEADING.match(line)
    if m:
        level = len(m.group(1))
        size = _HEADING_SIZE.get(level, "medium")
        face = f'font_family="{LOOK["heading"]}" ' if LOOK["heading"] else 'weight="bold" '
        return (f'<span {face}size="{size}" '
                f'foreground="{LOOK["accent"]}">{inline(m.group(2))}</span>')
    if _RULE.match(line):
        # "─" is full width in the Mplus fonts (moe): 18 of them is ~36
        # cells, which still fits a narrow tile without wrapping; elsewhere
        # it is one cell, so twice as many.
        n = 18 if LOOK["lang"] == "ja" else 36
        return f'<span foreground="{LOOK["dim"]}">{"─" * n}</span>'
    m = _BULLET.match(line)
    if m:
        indent = "    " * (len(m.group(1).expandtabs(4)) // 2)
        body = m.group(2)
        task = _TASK.match(body)
        if task:
            box = "☑" if task.group(1) in "xX" else "☐"
            return f'{indent}<span foreground="{LOOK['accent']}">{box}</span> {inline(task.group(2))}'
        return f'{indent}<span foreground="{LOOK['accent']}">•</span> {inline(body)}'
    m = _NUMBER.match(line)
    if m:
        indent = "    " * (len(m.group(1).expandtabs(4)) // 2)
        return (f'{indent}<span foreground="{LOOK['accent']}"><b>{m.group(2)}{m.group(3)}</b></span> '
                f'{inline(m.group(4))}')
    m = _QUOTE.match(line)
    if m:
        return (f'<span foreground="{LOOK['dim']}"><span foreground="{LOOK['accent']}">▎</span>'
                f'<i>{inline(m.group(1))}</i></span>')
    return inline(line)


def _cells(row):
    """A table row's cells: split on the bars that are not escaped ("\\|" is
    a "|" in the cell, as in `a \\| b`), the outer bars dropped."""
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [c.strip().replace("\\|", "|") for c in _TABLE_BAR.split(row)]


def md_table(rows):
    """A pipe table as ("table", key, cells, header): cells a list of rows of
    inline markup, header whether the first row is one (it is when the line
    under it is the |---| rule; only that line is taken for the rule). The
    widget lays it out as a grid of labels, so the columns line up whatever
    the glyphs' widths -- padding with spaces could not: M PLUS 1 Code draws
    the symbols models like in tables (✓ ✗ → ● ★) about 1.7 cells wide,
    which no count of spaces matches. key is the cells joined, for the
    widget's "did anything change" test."""
    header = len(rows) > 1 and bool(_TABLE_SEP.match(rows[1]))
    body = [rows[0]] + rows[2:] if header else rows
    cells = [[inline(c) for c in _cells(row)] for row in body]
    ncol = max(len(r) for r in cells)
    for r in cells:
        r += [""] * (ncol - len(r))
    key = ("H" if header else "-") + "\n".join("\x1f".join(r) for r in cells)
    return ("table", key, cells, header)


def md_block(lines):
    """Prose lines to segments: a run of table rows is a table segment of
    its own -- drawn unwrapped in a sideways scroller, since a wrapped table
    row is no longer a row -- the rest one ("md", markup) per paragraph.
    One label per paragraph, not one for all the prose, is what keeps
    streaming cheap: set_text only re-marks the labels whose markup changed,
    which while a reply streams is the last one. A single label for a 40 KB
    answer was re-laid out whole on every delta (hundreds of ms each)."""
    out, prose, i = [], [], 0
    def flush():
        para = []
        for line in prose + [""]:
            if line.strip():
                para.append(line)
            elif para:
                out.append(("md", "\n".join(md_line(x) for x in para)))
                para = []
        del prose[:]
    while i < len(lines):
        if _TABLE.match(lines[i]):
            j = i
            while j < len(lines) and _TABLE.match(lines[j]):
                j += 1
            flush()
            out.append(md_table(lines[i:j]))
            i = j
        else:
            prose.append(lines[i])
            i += 1
    flush()
    return out


def markdown_segments(text):
    """[("md", markup) | ("table", key, cells, header) | ("code", lang,
    text)]. An unclosed fence (still streaming) runs to the end as code."""
    return _segments(text)[0]


def _segments(text):
    """markdown_segments, and whether the text ends inside an open fence."""
    segments, prose, code, lang, fence = [], [], None, "", None
    for line in text.split("\n"):
        if code is None:
            m = _FENCE.match(line)
            if m:
                if prose:
                    segments += md_block(prose)
                    prose = []
                code, lang, fence = [], m.group(2), m.group(1)[0]
            else:
                prose.append(line)
        else:
            stripped = line.strip()
            if stripped.startswith(fence * 3) and not stripped.strip(fence):
                segments.append(("code", lang, "\n".join(code)))
                code = None
            else:
                code.append(line)
    open_fence = code is not None
    if open_fence:
        segments.append(("code", lang, "\n".join(code)))
    if prose:
        segments += md_block(prose)
    # Blank lines around fences become empty segments: drop them.
    return [s for s in segments if s[0] == "code" or s[1].strip()], open_fence


# -- transcript widgets -----------------------------------------------------

def copy_button(get_text, tip):
    """A small flat "⧉ copy" that puts get_text() on the clipboard and says
    "✓ copied" for a moment. store() hands the text to the clipboard manager,
    so it is still there after the window closes."""
    button = Gtk.Button(label=LOOK["copy"])
    button.get_style_context().add_class("copy")
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.set_can_focus(False)         # Tab stays between the input and the header
    button.set_tooltip_text(tip)
    button.reset = None

    def back():
        button.reset = None
        button.set_label(LOOK["copy"])
        return False

    def clicked(_button):
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(get_text(), -1)
        clip.store()
        button.set_label(LOOK["copied"])
        if button.reset is not None:
            GLib.source_remove(button.reset)
        button.reset = GLib.timeout_add(1500, back)

    def destroyed(_button):
        if button.reset is not None:
            GLib.source_remove(button.reset)
            button.reset = None

    button.connect("clicked", clicked)
    button.connect("destroy", destroyed)
    return button


IMAGE_EDGE = 1568          # the longest side the API looks at; larger is scaled down
IMAGE_BYTES = 3_500_000    # a PNG above this goes as JPEG (the API's limit is ~5 MB base64)


def image_attachment(pixbuf, name):
    """{"name", "media", "data", "size"} for an image to send: scaled to
    IMAGE_EDGE, PNG, or JPEG on white if the PNG is too big (a photo)."""
    w, h = pixbuf.get_width(), pixbuf.get_height()
    scale = min(1.0, IMAGE_EDGE / max(w, h, 1))
    if scale < 1.0:
        w, h = max(1, round(w * scale)), max(1, round(h * scale))
        pixbuf = pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    media = "image/png"
    if ok and len(data) > IMAGE_BYTES:
        flat = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
        flat.fill(0xffffffff)
        pixbuf.composite(flat, 0, 0, w, h, 0, 0, 1, 1, GdkPixbuf.InterpType.NEAREST, 255)
        ok, data = flat.save_to_bufferv("jpeg", ["quality"], ["88"])
        media = "image/jpeg"
    if not ok:
        raise ValueError("the image could not be encoded")
    return {"name": name, "media": media, "data": bytes(data), "size": (w, h)}


def walk(widget):
    """widget and everything inside it, depth first, in display order."""
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from walk(child)


def text_label(classes=(), mono=False, wrap=True):
    label = Gtk.Label(xalign=0, yalign=0)
    label.set_selectable(True)
    label.set_can_focus(False)          # selectable, but Tab never lands on it
    if wrap:
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    for cls in classes:
        label.get_style_context().add_class(cls)
    if mono:
        label.get_style_context().add_class("mono")
    return label


class AssistantBlock(Gtk.Box):
    """One text block of a reply. set_text() re-renders, reusing the widgets
    of segments whose kind did not change, so streaming does not rebuild the
    box (or drop a selection) on every delta. A copy button at its foot takes
    the block's markdown as written.

    Parsing is incremental: the text up to its last blank line outside a
    code fence is final -- a blank line ends every paragraph and table, and
    nothing after it can reach back -- so its segments are kept (_head) and
    only the tail is parsed again. Streaming a 40 KB reply re-parsed all of
    it ~16 times a second; now each pass is the last paragraph or two."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.get_style_context().add_class("assistant")
        self.set_halign(Gtk.Align.FILL)
        self.text = ""
        self.kids = []          # [(kind, widget, label)]
        self._cut, self._head, self._head_text = 0, [], ""
        copy = copy_button(lambda: self.text, "Copy this reply (markdown)")
        copy.set_halign(Gtk.Align.END)
        self.pack_end(copy, False, False, 0)

    def rerender(self):
        """Every segment marked up again (new theme colours)."""
        self._cut, self._head, self._head_text = 0, [], ""
        self.set_text(self.text)

    def segments(self, text):
        if not text.startswith(self._head_text):
            self._cut, self._head, self._head_text = 0, [], ""   # replaced, not grown
        cut = text.rfind("\n\n")
        if cut > self._cut:
            more, open_fence = _segments(text[self._cut:cut])
            if not open_fence:
                self._head = self._head + more
                self._cut, self._head_text = cut, text[:cut]
        return self._head + markdown_segments(text[self._cut:])

    def set_text(self, text):
        self.text = text
        segments = self.segments(text) or [("md", "")]
        for i, seg in enumerate(segments):
            kind = seg[0]
            if i < len(self.kids) and self.kids[i][0] == kind:
                _, widget, label = self.kids[i]
            else:
                for _, old, _ in self.kids[i:]:
                    old.destroy()
                del self.kids[i:]
                widget, label = self._make(kind)
                self.kids.append((kind, widget, label))
            if kind == "md":
                if label.get_label() != seg[1]:
                    label.set_markup(seg[1])
            elif kind == "table":
                if label.key != seg[1]:
                    label.key = seg[1]
                    self._fill_table(label, seg[2], seg[3])
            else:
                lang, body = seg[1], seg[2]
                widget.lang.set_text(lang)
                widget.lang.set_visible(bool(lang))
                if label.get_text() != body:
                    label.set_text(body)
        for _, old, _ in self.kids[len(segments):]:
            old.destroy()
        del self.kids[len(segments):]

    @staticmethod
    def _fill_table(grid, cells, header):
        """Cells in the even columns, a bar in each odd one, the rule in row
        1 under a header. Rebuilt whole when the table changes: a table is
        a few dozen labels, and it changes only while its rows stream in."""
        for child in grid.get_children():
            child.destroy()
        ncol = len(cells[0]) if cells else 0
        nrows = len(cells) + (1 if header else 0)
        for r, row in enumerate(cells):
            y = r + 1 if header and r > 0 else r
            for c, markup in enumerate(row):
                label = text_label(("md", "cell"), wrap=False)
                if header and r == 0:
                    label.get_style_context().add_class("th")
                    markup = f"<b>{markup}</b>"
                label.set_markup(markup)
                grid.attach(label, 2 * c, y, 1, 1)
        for c in range(1, ncol):
            bar = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            grid.attach(bar, 2 * c - 1, 0, 1, nrows)
        if header and ncol:
            rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            grid.attach(rule, 0, 1, 2 * ncol - 1, 1)
        grid.show_all()

    def _make(self, kind):
        if kind == "md":
            label = text_label(("md",))
            label.connect("activate-link", _open_link)
            self.pack_start(label, False, False, 0)
            label.show()
            return label, label
        if kind == "table":
            # Unwrapped, in a scroller that only ever scrolls sideways (and
            # only shows a bar when the table is wider than the reply).
            grid = Gtk.Grid()
            grid.get_style_context().add_class("md-table")
            grid.set_halign(Gtk.Align.START)
            grid.key = None
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            scroller.set_propagate_natural_height(True)
            scroller.get_style_context().add_class("table-scroll")
            scroller.add(grid)
            self.pack_start(scroller, False, False, 0)
            scroller.show_all()
            return scroller, grid
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.get_style_context().add_class("codeblock")
        head = Gtk.Box(spacing=6)
        box.lang = Gtk.Label(xalign=0)
        box.lang.get_style_context().add_class("code-lang")
        head.pack_start(box.lang, True, True, 0)
        label = text_label(("code",), mono=True)
        head.pack_end(copy_button(label.get_text, "Copy this code"), False, False, 0)
        box.pack_start(head, False, False, 0)
        box.pack_start(label, False, False, 0)
        self.pack_start(box, False, False, 0)
        box.show_all()
        return box, label


def _open_link(_label, uri):
    try:
        Gtk.show_uri_on_window(None, uri, Gdk.CURRENT_TIME)
    except GLib.Error:
        subprocess.Popen(["xdg-open", uri], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


SPIN = "◐◓◑◒"


def tool_summary(name, data):
    """The one line after a tool's name: what it is working on."""
    if not isinstance(data, dict):
        return ""
    def path(key="file_path"):
        value = data.get(key) or data.get("path") or data.get("notebook_path") or ""
        return short_path(str(value))
    if name == "Bash":
        return data.get("command", "")
    if name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "LS"):
        return path()
    if name == "Grep":
        where = short_path(str(data.get("path", ""))) if data.get("path") else ""
        what = f"/{data['pattern']}/" if data.get("pattern") else ""
        what += ("  " if what and data.get("glob") else "") + str(data.get("glob") or "")
        return what + (f"  {where}" if where else "")
    if name == "Glob":
        where = short_path(str(data.get("path", ""))) if data.get("path") else ""
        return data.get("pattern", "") + (f"  {where}" if where else "")
    if name == "WebSearch":
        return data.get("query", "")
    if name == "WebFetch":
        return data.get("url", "")
    if name in ("Task", "Agent"):
        return data.get("description") or data.get("subagent_type") or ""
    if name == "TodoWrite":
        todos = data.get("todos") or []
        done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
        return f"{done}/{len(todos)} todos"
    if name == "Skill":
        return data.get("skill", "")
    for value in data.values():
        if isinstance(value, str) and value:
            return value
    return ""


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    out.append(str(part.get("text", "")))
                elif part.get("type") == "image":
                    out.append("[image]")
            elif isinstance(part, str):
                out.append(part)
        return "\n".join(out)
    return "" if content is None else str(content)


def excerpt(text, lines=14, width=220):
    rows = text.rstrip("\n").split("\n")
    shown = [r if len(r) <= width else r[:width - 1] + "…" for r in rows[:lines]]
    if len(rows) > lines:
        shown.append(f"… (+{len(rows) - lines} lines)")
    return "\n".join(shown)


class ToolChip(Gtk.Box):
    """⚙ Name  summary, as a pill; the output folded under it once it is in."""

    def __init__(self, name, nested=False, kind=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.name = name
        self.kind = kind or name    # the shape its input has (tool_summary's name)
        self.running = True
        self.set_halign(Gtk.Align.START)
        if nested:
            self.set_margin_start(28)
        pill = Gtk.Box(spacing=8)
        pill.set_halign(Gtk.Align.START)
        pill.get_style_context().add_class("toolchip")
        self.pill = pill
        self.icon = Gtk.Label(label=SPIN[0])
        self.icon.get_style_context().add_class("tool-icon")
        self.title = Gtk.Label(label=f"⚙ {name}")
        self.title.get_style_context().add_class("tool-name")
        self.summary = Gtk.Label(xalign=0)
        self.summary.get_style_context().add_class("tool-summary")
        self.summary.set_ellipsize(Pango.EllipsizeMode.END)
        self.summary.set_max_width_chars(84)
        self.summary.set_selectable(True)
        self.summary.set_can_focus(False)
        pill.pack_start(self.icon, False, False, 0)
        pill.pack_start(self.title, False, False, 0)
        pill.pack_start(self.summary, False, True, 0)
        self.pack_start(pill, False, False, 0)
        self.expander = None
        self.show_all()
        self.summary.hide()

    def set_input(self, data):
        text = one_line(tool_summary(self.kind, data), 140)
        self.summary.set_text(text)
        self.summary.set_tooltip_text(str(tool_summary(self.kind, data))[:2000] or None)
        self.summary.set_visible(bool(text))

    def spin(self, tick):
        if self.running:
            self.icon.set_text(SPIN[(tick // 2) % len(SPIN)])

    def finish(self, output, is_error):
        self.running = False
        ctx = self.pill.get_style_context()
        ctx.add_class("error" if is_error else "done")
        self.icon.set_text("✗" if is_error else "✓")
        text = excerpt(output) if output else ""
        if text.strip():
            n = output.count("\n") + 1
            self.expander = Gtk.Expander(label=f"{'error' if is_error else 'output'} · {n} line{'s' if n != 1 else ''}")
            self.expander.get_style_context().add_class("tool-output")
            body = text_label(("tool-excerpt",), mono=True)
            body.set_text(text)
            self.expander.add(body)
            self.expander.set_expanded(bool(is_error))
            self.pack_start(self.expander, False, False, 0)
            self.expander.show_all()


ARM_MS = 600            # a card's buttons wait this long before they take a click or key
# Allowing a card that runs code (CODE_TOOLS) takes two presses: the first
# turns the button into "Sure? ...", the second, at least CONFIRM_GAP_MS later
# (a double click is not two decisions) and within CONFIRM_MS, allows.
CODE_TOOLS = ("Bash", "run_command")
CONFIRM_GAP_MS = 400
CONFIRM_MS = 5000


class PermCard(Gtk.Box):
    """A permission request, inline in the conversation: the tool, what it
    would do (perm_details), and Allow once / Allow for this session / Deny,
    with a note for the model that goes with a Deny (Enter in it denies).
    Alt+A / Alt+S / Alt+D answer the oldest open card from anywhere in the
    window (Front.on_key). The buttons arm after ARM_MS, so a click or key
    already on its way when the card appears does not answer it; the card
    never takes the keyboard from the input box. A card that would run code
    (CODE_TOOLS) needs Allow pressed twice (see CONFIRM_MS); Deny never does."""

    def __init__(self, req, cwd, ui, on_answer):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.req, self.on_answer, self.done = req, on_answer, False
        self.ui = ui
        self.runs_code = req.get("tool") in CODE_TOOLS
        self.confirming = None      # (choice, when) after the first press of an Allow
        self.confirm_timer = None
        self.rule, self.updated = session_rule(req)
        if req.get("native"):
            self.rule["label"] = req["display"]     # "run_command(make test)", not Bash's name
        self.get_style_context().add_class("perm-card")
        self.set_halign(Gtk.Align.FILL)
        head, details, warn = perm_details(req, cwd)
        title = text_label(("perm-title",))
        title.set_text("🔒 " + ui["perm_title"].format(tool=req["display"]))
        self.pack_start(title, False, False, 0)
        if head:
            what = text_label(("perm-what",), mono=True)
            what.set_text(head if len(head) <= 2000 else head[:1999] + "…")
            self.pack_start(what, False, False, 0)
        if details:
            body = text_label(("perm-detail",), mono=req["tool"] in ("Edit", "MultiEdit", "Write"))
            body.set_text("\n".join(details))
            self.pack_start(body, False, False, 0)
        for text in warn:
            label = text_label(("perm-warn",))
            label.set_text("⚠ " + text)
            self.pack_start(label, False, False, 0)
        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        row = Gtk.Box(spacing=8)
        self.buttons = {}
        for key, text, cls in (("once", ui["perm_once"], "perm-allow"),
                               ("session", ui["perm_session"], "perm-session"),
                               ("deny", ui["perm_deny"], "perm-deny")):
            button = Gtk.Button(label=text)
            button.get_style_context().add_class(cls)
            button.set_sensitive(False)
            button.connect("clicked", lambda _b, k=key: self.answer(k))
            row.pack_start(button, False, False, 0)
            self.buttons[key] = button
        self.buttons["session"].set_tooltip_text(
            f"remember {rule_text(self.rule)} until this conversation ends (Ctrl+N, another "
            "session, or closing the window): nothing is written to a settings file")
        self.controls.pack_start(row, False, False, 0)
        self.note = Gtk.Entry()
        self.note.set_placeholder_text(ui["perm_note"])
        self.note.get_style_context().add_class("perm-note")
        self.note.connect("activate", lambda *_: self.answer("deny"))
        self.controls.pack_start(self.note, False, False, 0)
        keys = text_label(("perm-keys",))
        keys.set_text(ui["perm_keys"] + "  ·  " + rule_text(self.rule))
        self.controls.pack_start(keys, False, False, 0)
        self.sure = text_label(("perm-warn",))
        self.sure.set_text("⚠ " + ui["perm_sure_hint"])
        self.sure.set_no_show_all(True)
        self.controls.pack_start(self.sure, False, False, 0)
        self.pack_start(self.controls, False, False, 0)
        self.outcome = text_label(("perm-outcome",))
        self.outcome.set_no_show_all(True)
        self.pack_start(self.outcome, False, False, 0)
        self.armed = False
        GLib.timeout_add(ARM_MS, self.arm)

    def arm(self):
        if not self.done:
            self.armed = True
            for button in self.buttons.values():
                button.set_sensitive(True)
        return False

    def answer(self, choice):
        if self.done or not self.armed:
            return False
        if self.runs_code and choice in ("once", "session"):
            now = time.monotonic()
            if not self.confirming or self.confirming[0] != choice:
                self.ask_sure(choice, now)
                return True
            if (now - self.confirming[1]) * 1000 < CONFIRM_GAP_MS:
                return True         # the second half of a double click
        self.unsure()
        self.on_answer(self, choice, self.note.get_text())
        return True

    def ask_sure(self, choice, now):
        """First press of an Allow on a code card: that button asks "Sure?"."""
        self.unsure()
        self.confirming = (choice, now)
        button = self.buttons[choice]
        button.set_label(self.ui["perm_sure_" + choice])
        button.get_style_context().add_class("perm-sure")
        self.sure.show()
        self.confirm_timer = GLib.timeout_add(CONFIRM_MS, self.unsure)

    def unsure(self):
        """Back to the plain buttons (timed out, the other button, or answered)."""
        if self.confirm_timer:
            GLib.source_remove(self.confirm_timer)
        self.confirm_timer = None
        if self.confirming and not self.done:
            choice = self.confirming[0]
            self.buttons[choice].set_label(self.ui["perm_" + choice])
            self.buttons[choice].get_style_context().remove_class("perm-sure")
            self.sure.hide()
        self.confirming = None
        return False

    def settle(self, text, cls="answered"):
        """Answered (or taken back): the controls go, one line says what happened."""
        if self.done:
            return
        self.done = True
        self.controls.destroy()
        self.get_style_context().add_class(cls)
        self.outcome.set_text(text)
        self.outcome.show()


# -- the window -------------------------------------------------------------

class Front(Gtk.Window):

    def __init__(self, prompt, cwd, resume, choice=None, model_error=None, render=False, images=()):
        self.render = render        # drawn off screen (--render): never mapped, never notifies
        self.theme = current_theme()
        self.ui = ui_strings(self.theme)
        super().__init__(title=self.ui["title"])
        self.set_name("llm-chat")
        self.set_default_size(1000, 900)
        self.cwd = cwd
        native_resume = bool(resume) and engine is not None and engine.is_session_id(resume)
        self.session_id = None if native_resume else resume     # a Claude Code session
        self.model = ""             # what the last run's init said it ran
        self.choice = choice        # llm_models.Model for the next run (None: no --model)
        self.run_choice = None      # ... and the one the last run had
        # The backend (claude / native) the conversation lives on: a
        # --resume window's session is taken to be on the model it was given.
        self.session_kind = "native" if native_resume else backend(choice)
        # The native engine (llm_chat_engine): the conversation as OpenAI
        # messages, its session file's id, the Run going now, Folder
        # access's "once" answers for this conversation, the models that
        # turned tools down, and the server's model list (None: not asked).
        self.native = None
        self.chat = []
        self.chat_id = None
        self.typed = []             # this conversation's messages as typed (Folder access)
        self.access = self.new_access()
        self.no_tools = set()
        self.server_list = None
        self.server_busy = False
        self.server_error = None
        self.thinking = None        # the reasoning row text deltas go to
        self.usage_max = None
        self.preparing = None       # a local model being readied: its generation
        self.prep_gen = 0
        self.bubble_override = None
        self.fresh_said = False     # pick_model's note told of the new session
        # Permissions (Ctrl+P): the pick (a PERM_MODES key, or a CLI mode
        # from $LLM_CHAT_PERMISSION), and what the last run's init said
        # it ran as. live_prompts: runs ask over the control protocol; off
        # only if this claude turned the flags down (then: refusals at the
        # end of a run and the retry button, as before).
        self.perm = start_permission(PERMISSION, read_front_state().get("permissions"))
        self.mode = perm_cli_mode(self.perm)
        self.live_prompts = True
        self.perm_rules = []        # "Allow for this session": [{"tool", "content"}]
        self.cards = {}             # request_id -> PermCard, still waiting
        self.denied_ids = set()     # tool_use ids the user said no to (no retry offered)
        self.last_text = ""         # the last top-level reply (a notification's line)
        self.notes_out = {}         # key -> [notify-send Popen, mako id]
        # Local models: which are loaded (local_loaded(), refreshed in a
        # thread when the model menu opens and after a run), and an unload.
        self.loaded = {}
        self.loaded_at = None       # monotonic time of that look; None = never looked
        self.loaded_busy = False
        self.unloading = None       # the model word being unloaded
        self.unload_after_stop = None
        self.status_extra = None    # one line for the status (what an unload freed)
        self.cost = 0.0
        # The session's total as of the last result, to tell a run's own cost
        # from it; None while not known (a --resume window's first run: its
        # total holds the conversation before this window too).
        self.cost_prev = None if resume else 0.0
        self.proc = None
        self.pgids = []
        self.queue = []                 # [(text, images, its bubble)]
        self.allow_once = []            # --allowedTools rules for the next run only
        self.replaying = False
        self.ctx_used = None            # tokens in the context as of the last reply
        self.ctx_max = None             # the model's window (the result's modelUsage)
        self.history = []           # messages sent, oldest first (Up / Down)
        self.hist_pos = None        # the one the box shows, while browsing
        self.run_started = None
        self.last_elapsed = 0.0
        self.state = "idle"
        self.tool = None
        self.state_since = time.monotonic()
        self.last_activity = time.monotonic()
        self.t0 = time.monotonic()
        self.timer = None
        self.timer_ms = 0
        self.mascot = None
        self.grid = (0, 0, 1.0)  # mascot cols, rows, font scale
        self.cell = None
        self.scaled_cells = {}   # font scale -> cell measured at it
        self.chips = {}          # tool_use id -> ToolChip
        self.active_tools = {}   # tool_use id -> name, in start order
        self.streamed = {}       # message id -> [AssistantBlock] not yet confirmed
        self.live = None         # the AssistantBlock text deltas go to
        self.render_pending = set()
        self.render_source = None
        self.stick = True
        self.closing = False
        self.provider = None
        self.monitor = None
        self.theme_pending = None
        # Her mood (mascot_mood.Mood): fed the conversation's events, asked
        # for a View every frame; the surroundings re-read on a thread.
        self.moods = mascot_mood.Mood() if mascot_mood is not None else None
        self.mood_busy = False

        self._build()
        self.apply_theme(first=True)
        self.watch_theme()
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_delete)
        self.connect("notify::is-active", self.on_active)
        if not render:
            self.show_all()
        self.stop_btn.hide()
        self.stage_wrap.set_visible(not self.corner_btn.get_active())   # show_all showed it
        self.input.grab_focus()
        self.update_model_button()
        self.update_perm_button()
        self.update_status()
        self.wake()
        if model_error:
            self.error(model_error)
        if native_resume:
            self.open_native(resume)
        elif self.session_id:
            self.note(f"resuming session {self.session_id}")
        if llm_models is not None and llm_models.stale():
            self.refresh_models()
        if self.choice is not None and self.choice.local:
            self.refresh_loaded()
        if self.moods is not None:
            self.refresh_mood()
            GLib.timeout_add_seconds(MOOD_REFRESH_S, self.refresh_mood)
        if self.choice is not None and self.choice.kind == "server":
            self.refresh_server()
        for att in images:
            self.attachments.append(att)
        if images:
            self.show_attachments()
        if prompt or images:
            self.submit_text(prompt)

    def running(self):
        """A reply is being written (a claude run, or a native Run)."""
        return self.proc is not None or self.native is not None

    def new_access(self):
        """Folder access's answers for one conversation ("Allow once" lasts
        that long), or None without folder_access.py."""
        if folder_access is None:
            return None
        try:
            return folder_access.Session(engine.WHO if engine is not None else "chat")
        except Exception:       # noqa: BLE001  (an older folder_access without "chat")
            return None

    # ---- layout ------------------------------------------------------------

    def _build(self):
        header = Gtk.HeaderBar(title=self.ui["title"], subtitle=short_path(self.cwd))
        header.set_show_close_button(True)
        new_btn = Gtk.Button.new_from_icon_name("document-new-symbolic", Gtk.IconSize.BUTTON)
        new_btn.set_tooltip_text("New session (Ctrl+N)")
        new_btn.connect("clicked", lambda *_: self.new_session())
        header.pack_start(new_btn)
        # Recent sessions, any directory: a pick replays it here and goes on
        # with it. Styled as the model menu.
        self.sessions_btn = Gtk.MenuButton()
        self.sessions_btn.add(Gtk.Image.new_from_icon_name("document-open-recent-symbolic",
                                                           Gtk.IconSize.BUTTON))
        self.sessions_btn.set_tooltip_text("Recent sessions (Ctrl+O)")
        self.sessions_pop = Gtk.Popover()
        self.sessions_pop.set_name("model-menu")
        self.sessions_btn.set_popover(self.sessions_pop)
        self.sessions_btn.connect("toggled", lambda b: b.get_active() and self.fill_sessions_menu())
        header.pack_start(self.sessions_btn)
        self.stop_btn = Gtk.Button(label=self.ui["stop"])
        self.stop_btn.set_tooltip_text("Stop (Esc)")
        self.stop_btn.get_style_context().add_class("stop")
        self.stop_btn.connect("clicked", lambda *_: self.stop())
        header.pack_start(self.stop_btn)
        term_btn = Gtk.Button.new_from_icon_name("utilities-terminal-symbolic", Gtk.IconSize.BUTTON)
        term_btn.set_tooltip_text("Open in Claude Code's terminal UI (Ctrl+T)")
        term_btn.connect("clicked", lambda *_: self.open_terminal())
        term_btn.set_no_show_all(True)      # a Claude model only: update_model_button
        header.pack_end(term_btn)
        self.term_btn = term_btn
        # Permissions (Ctrl+P): the mode for this window's runs, the
        # session's allow rules, and the notifications toggle. Styled as
        # the model menu.
        self.perm_btn = Gtk.MenuButton()
        self.perm_btn.set_name("perm-button")
        self.perm_btn.set_tooltip_text("Permissions and notifications (Ctrl+P)")
        perm_box = Gtk.Box(spacing=4)
        perm_box.pack_start(Gtk.Image.new_from_icon_name("security-medium-symbolic", Gtk.IconSize.BUTTON),
                            False, False, 0)
        self.perm_label = Gtk.Label()
        perm_box.pack_start(self.perm_label, False, False, 0)
        self.perm_btn.add(perm_box)
        self.perm_pop = Gtk.Popover()
        self.perm_pop.set_name("model-menu")
        self.perm_btn.set_popover(self.perm_pop)
        self.perm_btn.connect("toggled", lambda b: b.get_active() and self.fill_perm_menu())
        header.pack_end(self.perm_btn)
        # The model picker: a popover (a child of this window, so the theme's
        # window#llm-chat rules reach it), rebuilt each time it opens.
        self.model_btn = Gtk.MenuButton()
        self.model_btn.set_name("model-button")
        self.model_btn.set_tooltip_text("Model for the next message (Ctrl+M)")
        self.model_label = Gtk.Label()
        self.model_btn.add(self.model_label)
        self.model_pop = Gtk.Popover()
        self.model_pop.set_name("model-menu")
        self.model_btn.set_popover(self.model_pop)
        self.model_btn.connect("toggled", self.on_model_toggled)
        self.model_btn.set_sensitive(llm_models is not None)
        header.pack_end(self.model_btn)
        # The mascot menu: her mood now and what she reacts to. Named like
        # the model menu, so it is styled like it (llm-chat.css).
        self.mascot_btn = Gtk.MenuButton()
        self.mascot_btn.add(Gtk.Image.new_from_icon_name("face-smile-symbolic", Gtk.IconSize.BUTTON))
        self.mascot_btn.set_tooltip_text("Mascot: mood and what she reacts to (Ctrl+J)")
        self.mascot_pop = Gtk.Popover()
        self.mascot_pop.set_name("model-menu")
        self.mascot_btn.set_popover(self.mascot_pop)
        self.mascot_btn.connect("toggled", lambda b: b.get_active() and self.fill_mascot_menu())
        self.mascot_btn.set_sensitive(mascot_mood is not None)
        header.pack_end(self.mascot_btn)
        # The mascot as a small card in a corner of the conversation, the
        # whole window left to the text (Ctrl+K); a click on the card moves
        # it to the next corner.
        self.corner_btn = Gtk.ToggleButton()
        self.corner_btn.add(Gtk.Image.new_from_icon_name("view-restore-symbolic", Gtk.IconSize.BUTTON))
        self.corner_btn.set_tooltip_text("Mascot in a corner (Ctrl+K) — click her to move her")
        header.pack_end(self.corner_btn)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.set_name("root")
        self.add(root)

        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.set_wide_handle(False)
        root.pack_start(paned, True, True, 0)

        # The stage: bubble above, art below, on the night card.
        stage = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        stage.set_name("stage")
        self.stage = stage
        self.bubble = Gtk.Label()
        self.bubble.set_name("bubble")
        self.bubble.set_halign(Gtk.Align.CENTER)
        self.bubble.set_ellipsize(Pango.EllipsizeMode.END)
        stage.pack_start(self.bubble, False, False, 0)
        self.art_scroll = Gtk.ScrolledWindow()
        self.art_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.EXTERNAL)
        self.art_scroll.set_name("art-scroll")
        self.art = Gtk.Label()
        self.art.set_name("art")
        self.art.set_halign(Gtk.Align.CENTER)
        self.art.set_valign(Gtk.Align.CENTER)
        self.art.set_justify(Gtk.Justification.LEFT)
        self.art_scroll.add(self.art)
        self.art_scroll.get_child().set_name("art-view")
        self.art_scroll.connect("size-allocate", self.on_stage_size)
        self.art.connect("style-updated", lambda *_: setattr(self, "cell", None))
        stage.pack_start(self.art_scroll, True, True, 0)
        stage_wrap = Gtk.Box()
        stage_wrap.set_name("stage-wrap")
        stage_wrap.pack_start(stage, True, True, 0)
        stage_wrap.set_size_request(-1, 150)
        self.stage_wrap, self.stage_floor = stage_wrap, 150
        paned.pack1(stage_wrap, resize=False, shrink=False)
        self.paned = paned
        self.side = False           # the stage in a column on the right
        self.paned_auto = True      # until the handle is dragged by hand
        self.paned_setting = False
        paned.connect("size-allocate", self.on_paned_size)
        paned.connect("notify::position", self.on_paned_moved)
        self.handle_held = False
        paned.connect("button-press-event", self.on_paned_button, True)
        paned.connect("button-release-event", self.on_paned_button, False)

        # The conversation.
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_name("transcript-scroll")
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.list.set_name("transcript")
        self.list.set_valign(Gtk.Align.END)
        self.scroll.add(self.list)
        adj = self.scroll.get_vadjustment()
        adj.connect("changed", self.on_adj_changed)
        adj.connect("value-changed", self.on_adj_value)
        # Ctrl+F: a search bar over the conversation (Enter: the match above,
        # Shift+Enter: below, Esc: close).
        self.search = Gtk.SearchBar()
        self.search.set_name("search")
        self.search.set_show_close_button(False)
        find_row = Gtk.Box(spacing=8)
        self.find_entry = Gtk.SearchEntry()
        self.find_entry.set_width_chars(30)
        self.find_entry.connect("search-changed", lambda *_: self.find_all())
        self.find_entry.connect("key-press-event", self.on_find_key)
        self.find_entry.connect("stop-search", lambda *_: self.close_search())
        self.find_count = Gtk.Label()
        self.find_count.set_name("find-count")
        find_row.pack_start(self.find_entry, False, False, 0)
        find_row.pack_start(self.find_count, False, False, 0)
        self.search.add(find_row)
        self.search.connect_entry(self.find_entry)
        self.matches, self.match_at, self.match_label = [], -1, None
        middle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        middle.pack_start(self.search, False, False, 0)
        middle.pack_start(self.scroll, True, True, 0)
        # The conversation and the input box below it: under the stage, or
        # beside it in a wide window (set_side).
        self.convo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        over = Gtk.Overlay()
        over.add(middle)
        self.corner = Gtk.EventBox()        # the corner card: the stage, moved in
        self.corner.set_name("corner")
        self.corner.set_no_show_all(True)
        for side in ("top", "bottom", "start", "end"):
            self.corner.set_property("margin-" + side, 14)
        self.corner.connect("button-press-event", lambda *_: self.move_corner() or True)
        over.add_overlay(self.corner)
        self.corner_w = 0
        over.connect("size-allocate", self.on_over_size)
        self.convo.pack_start(over, True, True, 0)
        paned.pack2(self.convo, resize=True, shrink=False)
        self.connect("size-allocate", self.on_window_size)
        saved = read_front_state()
        self.corner_where = saved.get("where") if saved.get("where") in CORNERS else CORNERS[0]
        self.corner_btn.set_active(bool(saved.get("corner")))
        self.set_corner(self.corner_btn.get_active(), save=False)
        self.corner_btn.connect("toggled", lambda b: self.set_corner(b.get_active()))
        # Files and images dropped anywhere on the conversation (or the
        # input box, below) are attached.
        self.scroll.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.scroll.drag_dest_add_uri_targets()
        self.scroll.drag_dest_add_image_targets()
        self.scroll.connect("drag-data-received", self.on_drop)

        # The input.
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bottom.set_name("bottom")
        # The images going with the next message (Ctrl+V of an image, or one
        # dropped): a pill each, ✕ to take it off. Hidden while empty.
        self.attachments = []
        self.attach_row = Gtk.Box(spacing=6)
        self.attach_row.set_no_show_all(True)
        bottom.pack_start(self.attach_row, False, False, 0)
        row = Gtk.Box(spacing=8)
        overlay = Gtk.Overlay()
        in_scroll = Gtk.ScrolledWindow()
        in_scroll.set_name("input-scroll")
        in_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        in_scroll.set_propagate_natural_height(True)
        in_scroll.set_min_content_height(24)
        in_scroll.set_max_content_height(160)
        self.input = Gtk.TextView()
        self.input.set_name("input")
        self.input.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input.set_accepts_tab(False)
        self.input.connect("key-press-event", self.on_input_key)
        targets = self.input.drag_dest_get_target_list() or Gtk.TargetList.new([])
        targets.add_uri_targets(0)
        targets.add_image_targets(0, False)
        self.input.drag_dest_set_target_list(targets)
        self.input.connect("drag-data-received", self.on_drop)
        self.input.get_buffer().connect("changed", self.on_input_changed)
        in_scroll.add(self.input)
        overlay.add(in_scroll)
        self.placeholder = Gtk.Label(label="", xalign=0)
        self.placeholder.set_name("placeholder")
        self.placeholder.set_ellipsize(Pango.EllipsizeMode.END)   # a narrow tile
        self.placeholder.set_halign(Gtk.Align.START)
        self.placeholder.set_valign(Gtk.Align.CENTER)
        overlay.add_overlay(self.placeholder)
        overlay.set_overlay_pass_through(self.placeholder, True)
        row.pack_start(overlay, True, True, 0)
        self.send_btn = Gtk.Button(label=self.ui["send"])
        self.send_btn.set_name("send")
        self.send_btn.set_valign(Gtk.Align.END)
        self.send_btn.connect("clicked", lambda *_: self.submit())
        row.pack_start(self.send_btn, False, False, 0)
        bottom.pack_start(row, False, False, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.set_name("status")
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_selectable(True)
        self.status.set_can_focus(False)
        bottom.pack_start(self.status, False, False, 0)
        self.convo.pack_start(bottom, False, False, 0)

    # ---- the theme ---------------------------------------------------------

    def apply_theme(self, first=False):
        """The desktop theme, (re)applied: the stylesheet (base + the theme's
        generated override, read again), the words, the markup colours and
        faces, and the mascot -- the theme's own, remade at the next size
        pass. Called at start and whenever a watched file changes."""
        self.theme = current_theme()
        conf = theme_conf(self.theme)
        self.ui = ui_strings(self.theme, conf)
        screen = Gdk.Screen.get_default()
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(CSS_FILE)
        except GLib.Error as exc:
            print(f"llm-chat: {CSS_FILE}: {exc}", file=sys.stderr)
            provider = None
        if provider is not None:
            if self.provider is not None:
                Gtk.StyleContext.remove_provider_for_screen(screen, self.provider)
            Gtk.StyleContext.add_provider_for_screen(screen, provider,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_USER)
            self.provider = provider
        mono = conf.get("font_mono") or "IBM Plex Mono"
        LOOK.update({
            "theme": self.theme,
            "lang": conf.get("lang") or "en",
            "mono": mono.split(",")[0].strip().strip('"\'') or "IBM Plex Mono",
            "heading": HEADING_FONT.get(self.theme),
            "accent": self.css_colour("md-accent", LOOK["accent"]),
            "dim": self.css_colour("md-dim", LOOK["dim"]),
            "code_fg": self.css_colour("md-code-fg", LOOK["code_fg"]),
            "code_bg": self.css_colour("md-code-bg", LOOK["code_bg"]),
            "stage_fg": self.css_colour("stage-fg", LOOK["stage_fg"]),
            "copy": self.ui["copy"], "copied": self.ui["copied"],
        })
        title = self.ui["title"]
        self.set_title(title)
        self.get_titlebar().set_title(title)
        self.stop_btn.set_label(self.ui["stop"])
        self.send_btn.set_label(self.ui["wait"] if self.running() else self.ui["send"])
        self.update_placeholder()
        self.find_entry.set_placeholder_text(self.ui["find"])
        if first:
            return
        # Another face is another cell: measure again, make the theme's
        # mascot at the size that gives, re-mark every reply in the new
        # colours.
        self.cell = None
        self.scaled_cells = {}
        self.grid = (0, 0, 1.0)
        self.mascot = None
        GLib.timeout_add(60, self._refit)
        for child in walk(self.list):
            if isinstance(child, AssistantBlock):
                child.rerender()
            elif isinstance(child, Gtk.Button) and child.get_style_context().has_class("copy") \
                    and child.reset is None:
                child.set_label(LOOK["copy"])
        self.wake()

    def _refit(self):
        self.cell = None
        self.scaled_cells = {}
        self.on_stage_size(self.art_scroll, self.art_scroll.get_allocation())
        return False

    def css_colour(self, name, fallback):
        """A named colour of the stylesheet as #rrggbb (fallback if the
        theme does not define it)."""
        ok, rgba = self.get_style_context().lookup_color(name)
        if not ok:
            return fallback
        return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255)))
                                       for c in (rgba.red, rgba.green, rgba.blue))

    def watch_theme(self):
        """A Gio monitor on waybar/generated/: theme.py replaces the files
        there atomically (a rename), so the directory sees every switch;
        a burst of events (set writes a dozen files) is folded into one
        restyle 250 ms after the last."""
        try:
            folder = Gio.File.new_for_path(GEN_DIR)
            self.monitor = folder.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error as exc:
            print(f"llm-chat: cannot watch {GEN_DIR}: {exc}", file=sys.stderr)
            return
        self.monitor.connect("changed", self.on_generated_changed)

    def on_generated_changed(self, _monitor, gfile, other, _event):
        names = {f.get_basename() for f in (gfile, other) if f is not None}
        if not names & set(WATCHED):
            return
        if self.theme_pending is not None:
            GLib.source_remove(self.theme_pending)
        self.theme_pending = GLib.timeout_add(250, self._theme_changed)

    def _theme_changed(self):
        self.theme_pending = None
        if not self.closing:
            self.apply_theme()
        return False

    # ---- the stage ---------------------------------------------------------

    def set_corner(self, on, save=True):
        """The stage (bubble and art) in its place above or beside the
        conversation, or in a card in a corner over it. The same widgets
        move: the grid is made again for the card's size."""
        here = self.stage.get_parent()
        want = self.corner if on else self.stage_wrap
        if here is not want:
            here.remove(self.stage)
            if on:
                self.corner.add(self.stage)
            else:
                self.stage_wrap.pack_start(self.stage, True, True, 0)
        self.stage_wrap.set_visible(not on)
        self.corner.set_visible(on)
        if on:
            self.stage.show_all()
            self.place_corner()
        if save:
            write_front_state(corner=on, where=self.corner_where)

    def on_over_size(self, _over, alloc):
        w = int(max(CORNER_W[0], min(CORNER_W[1], alloc.width * CORNER_SHARE)))
        w = min(w, max(200, alloc.width - 28))
        if abs(w - self.corner_w) >= 8:
            self.corner_w = w
            # 250 px tall at least: the bubble and ART_MIN's rows at the
            # smallest scale
            GLib.idle_add(lambda: self.corner.set_size_request(w, max(250, int(w * 0.62))) and False)

    def place_corner(self):
        v, h = self.corner_where.split("-")
        self.corner.set_halign(Gtk.Align.END if h == "right" else Gtk.Align.START)
        self.corner.set_valign(Gtk.Align.END if v == "bottom" else Gtk.Align.START)

    def move_corner(self):
        self.corner_where = CORNERS[(CORNERS.index(self.corner_where) + 1) % len(CORNERS)]
        self.place_corner()
        write_front_state(corner=True, where=self.corner_where)

    def on_window_size(self, _win, alloc):
        if not self.side and alloc.width >= SIDE_AT:
            GLib.idle_add(self.set_side, True)
        elif self.side and alloc.width < STACK_AT:
            GLib.idle_add(self.set_side, False)

    def set_side(self, side):
        """The stage on top of the conversation (stacked), or in a column on
        the right of it, the conversation and input box at full height on
        the left (side). The paned is turned and its two children swapped;
        a handle dragged by hand counts for the layout it was dragged in."""
        if side == self.side:
            return False
        self.side = side
        paned = self.paned
        for child in (self.stage_wrap, self.convo):
            paned.remove(child)
        if side:
            paned.set_orientation(Gtk.Orientation.HORIZONTAL)
            paned.pack1(self.convo, resize=True, shrink=False)
            paned.pack2(self.stage_wrap, resize=False, shrink=False)
            self.stage_wrap.get_style_context().add_class("side")
            self.stage_wrap.set_size_request(SIDE_MIN_W, -1)
        else:
            paned.set_orientation(Gtk.Orientation.VERTICAL)
            paned.pack1(self.stage_wrap, resize=False, shrink=False)
            paned.pack2(self.convo, resize=True, shrink=False)
            self.stage_wrap.get_style_context().remove_class("side")
            self.stage_wrap.set_size_request(-1, self.stage_floor)
        self.paned_auto = True
        paned.queue_resize()
        return False

    def on_paned_size(self, paned, alloc):
        """The stage's share of the height: 40 % of it, 150 px at least, so it
        grows and shrinks with the window (the art's font scales to fill it). A fixed
        330 left a short tile (a half-height split) a line of conversation;
        once the handle has been dragged, the hand's choice stands. Beside
        the conversation (side) it is SIDE_SHARE of the width instead."""
        if self.side:
            if self.paned_auto:
                want = alloc.width - max(SIDE_MIN_W, int(alloc.width * SIDE_SHARE))
                if paned.get_position() != want:
                    GLib.idle_add(self._set_paned, want)
            return
        # Never less than the art needs at its smallest scale: the bubble and
        # padding (what the stage holds besides the art) plus ART_MIN's rows.
        floor = 150
        if self.cell is not None and self.art_scroll.get_allocated_height() > 1:
            chrome = paned.get_position() - self.art_scroll.get_allocated_height()
            low = self.cell_at(ART_SCALE_MIN) or self.cell
            floor = max(floor, chrome + int(ART_MIN[1] * low[1]) + 6)
            if floor != self.stage_floor:
                self.stage_floor = floor
                self.stage_wrap.set_size_request(-1, floor)
        if not self.paned_auto:
            return
        want = max(floor, int(alloc.height * 0.4))
        if paned.get_position() != want:
            GLib.idle_add(self._set_paned, want)

    def _set_paned(self, want):
        self.paned_setting = True
        self.paned.set_position(want)
        self.paned_setting = False
        return False

    def on_paned_moved(self, *_):
        if not self.paned_setting and self.paned.get_property("position-set") \
                and self.get_mapped() and self.paned_auto and self.handle_held:
            self.paned_auto = False

    def on_paned_button(self, paned, event, held):
        """A button down on the handle itself: a drag by hand. Not any held
        button -- resizing the window with the mouse moves the position
        too (GTK clamps it), and that turned the automatic size off."""
        self.handle_held = held and event.window == paned.get_handle_window()
        return False

    def measure_cell(self, scale=1.0):
        layout = self.art.create_pango_layout("M" * 20 + "\n" + "M" * 20)
        if scale != 1.0:
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_scale_new(scale))
            layout.set_attributes(attrs)
        w, h = layout.get_pixel_size()
        if w <= 0 or h <= 0:
            return None
        return w / 20.0, h / 2.0

    def cell_at(self, scale):
        """The cell as drawn at `scale`, measured with the scale attribute
        itself and kept per scale. Pango snaps a scaled font to hinted
        metrics, so cell(1.0) * scale is not it: at 0.70 the 7 x 18 cell is
        5 x 13, not 4.9 x 12.6, and 14 rows are 182 px, not 176."""
        scale = round(scale, 2)
        if scale not in self.scaled_cells:
            self.scaled_cells[scale] = self.measure_cell(scale)
        return self.scaled_cells[scale]

    def on_stage_size(self, _widget, alloc):
        """The grid for this allocation, and the scale its font is drawn at.

        moe_mascot draws a figure of fixed size (21 x 11 cells) and is made
        for grids of ART_MIN to ART_MAX; below ART_MIN it hands back more
        rows than asked, which the stage would clip (her feet first). So a
        stage too small for ART_MIN at the theme's mono size draws the art
        smaller, and one with room for more than ART_MAX's rows draws it
        larger -- she grows with the panel instead of standing small in a
        field of stars. Either way the grid is as many cells as the stage
        holds (to ART_LIMIT), so the scene reaches every edge. The
        scale goes in steps of 1/20, so a drag of the pane does not remake
        the mascot on every pixel."""
        if self.cell is None:
            self.cell = self.measure_cell()
            if self.cell is None:
                return
        cw, lh = self.cell
        avail_w, avail_h = max(1.0, alloc.width - 8), max(1.0, alloc.height - 4)
        fit_c, fit_r = avail_w / cw, avail_h / lh
        (min_c, min_r), (max_c, max_r) = ART_MIN, ART_MAX
        scale = min(1.0, fit_c / min_c, fit_r / min_r)
        if scale >= 1.0:
            # Grown until the rows reach ART_MAX's, as long as the columns
            # stay ART_MIN's or more: a wide stage keeps her size and widens
            # the scenery, a tall one (the side column) draws her larger.
            scale = max(1.0, min(fit_r / max_r, fit_c / min_c, ART_SCALE_MAX))
        scale = round(max(ART_SCALE_MIN, int(scale * 20) / 20.0), 2)
        # The linear estimate picked the scale; the cell measured at it says
        # whether ART_MIN really fits, and a step down when it does not.
        while True:
            cell = self.cell_at(scale) or (cw * scale, lh * scale)
            if (min_c * cell[0] <= avail_w and min_r * cell[1] <= avail_h) \
                    or scale <= ART_SCALE_MIN:
                break
            scale = max(ART_SCALE_MIN, round(scale - 0.05, 2))
        cols = max(min_c, min(ART_LIMIT[0], int(avail_w / cell[0])))
        rows = max(min_r, min(ART_LIMIT[1], int(avail_h / cell[1])))
        if (cols, rows, scale) != self.grid:
            self.grid = (cols, rows, scale)
            GLib.idle_add(self._remake_mascot, cols, rows, scale)

    def _remake_mascot(self, cols, rows, scale):
        if (cols, rows, scale) == self.grid:
            attrs = Pango.AttrList()
            if scale != 1.0:
                attrs.insert(Pango.attr_scale_new(scale))
            self.art.set_attributes(attrs)
            self.mascot = make_mascot(cols, rows, self.theme)
            self.draw_frame()
        return False

    def tick(self):
        return int((time.monotonic() - self.t0) * 10)

    def draw_frame(self):
        if self.mascot is None:
            return
        tick = self.tick()
        state = self.state
        view = self.mood_view(state)
        mood, scene = (view.mood, view.scene) if view else (None, ())
        try:
            markup = self.mascot.markup(state, tick, self.tool, mood, scene)
            Pango.parse_markup(markup, -1, "\0")
            self.art.set_markup(markup)
        except Exception as exc:
            try:
                self.art.set_text("\n".join(self.mascot.lines(state, tick, self.tool, mood, scene)))
            except Exception:
                self.art.set_text(f"(mascot error: {exc})")
        try:
            text = self.bubble_override \
                or (self.mascot.say(view.line) if view and view.line else None) \
                or self.mascot.bubble(state, self.tool, mood)
        except Exception:
            text = ""
        if text and self.bubble.get_text() != text:
            self.bubble.set_text(text)
        self.bubble.set_visible(bool(text))
        # Only the running ones: a long session's finished chips are hundreds,
        # and this runs ten times a second.
        for tid in self.active_tools:
            chip = self.chips.get(tid)
            if chip is not None:
                chip.spin(tick)

    def mood_view(self, state):
        """The mood's View for this frame, or None: no mood module, or a
        mascot that does not draw moods."""
        if self.moods is None or not getattr(self.mascot, "moods", False):
            return None
        try:
            return self.moods.view(state)
        except Exception as exc:
            print(f"llm-chat: mood: {exc}", file=sys.stderr)
            return None

    def mood_event(self, event, **kw):
        if self.moods is not None and not self.replaying:
            try:
                self.moods.react(event, **kw)
            except Exception as exc:
                print(f"llm-chat: mood {event}: {exc}", file=sys.stderr)

    def refresh_mood(self):
        """Re-read the surroundings on a thread (the calendar is D-Bus, the
        game mode a subprocess); a changed scene is drawn even while the
        animation sleeps."""
        if self.closing:
            return False
        if self.mood_busy:
            return True
        self.mood_busy = True

        def work():
            try:
                changed = self.moods.refresh()
            except Exception as exc:
                print(f"llm-chat: mood refresh: {exc}", file=sys.stderr)
                changed = False
            GLib.idle_add(self._mood_refreshed, changed)

        import threading
        threading.Thread(target=work, daemon=True).start()
        return True

    def _mood_refreshed(self, changed):
        self.mood_busy = False
        if changed and not self.closing and self.get_mapped():
            self.draw_frame()
            if self.mascot_pop.get_visible():
                self.fill_mascot_menu()
        return False

    def set_state(self, state, tool=None):
        if state != self.state or tool != self.tool:
            self.state, self.tool = state, tool
            self.state_since = time.monotonic()
            if TRACE:
                try:
                    with open(TRACE, "a") as fh:
                        fh.write(f"{time.time():.2f} {self.theme} {state} {tool or '-'}\n")
                except OSError:
                    pass
        self.wake()

    def wake(self):
        """Something happened: back to full speed."""
        self.last_activity = time.monotonic()
        self._schedule(FAST_MS)

    def _schedule(self, ms):
        if self.timer is not None and self.timer_ms == ms:
            return
        if self.timer is not None:
            GLib.source_remove(self.timer)
        self.timer_ms = ms
        self.timer = GLib.timeout_add(ms, self.on_tick)

    def on_tick(self):
        now = time.monotonic()
        if self.state in ("done", "error") and now - self.state_since > DONE_TO_IDLE_S:
            self.state, self.tool, self.state_since = "idle", None, now
        if self.get_mapped():
            self.draw_frame()
        if self.running() and now - self.last_elapsed >= 1:
            self.last_elapsed = now
            self.update_status()
            self.mood_event("tick")
        quiet = now - self.last_activity
        if self.running() or quiet < QUIET_S:
            want = FAST_MS
        elif quiet < SLEEP_S:
            want = SLOW_MS
        else:
            self.timer = None
            return False
        if want != self.timer_ms:
            self.timer = None
            self._schedule(want)
            return False
        return True

    # ---- transcript --------------------------------------------------------

    def add_row(self, widget):
        self.list.pack_start(widget, False, False, 0)
        widget.show_all()
        return widget

    def user_bubble(self, text, queued=False):
        box = Gtk.Box()
        box.set_halign(Gtk.Align.END)
        label = text_label(("user",))
        label.set_max_width_chars(70)
        label.set_text(text)
        if queued:
            label.get_style_context().add_class("queued")
            label.set_tooltip_text("queued: sent when the current run finishes")
        box.pack_end(label, False, False, 0)
        self.add_row(box)
        return label

    def note(self, text, cls="note"):
        label = text_label((cls,))
        label.set_halign(Gtk.Align.CENTER if cls == "note" else Gtk.Align.FILL)
        label.set_xalign(0.5 if cls == "note" else 0)
        label.set_text(text)
        self.add_row(label)
        return label

    def error(self, text):
        self.note(text, "error-card")

    def on_adj_changed(self, adj):
        if self.stick:
            adj.set_value(adj.get_upper() - adj.get_page_size())

    def on_adj_value(self, adj):
        self.stick = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 40

    def schedule_render(self, block):
        self.render_pending.add(block)
        if self.render_source is None:
            self.render_source = GLib.timeout_add(60, self._render_now)

    def _render_now(self):
        self.render_source = None
        pending, self.render_pending = self.render_pending, set()
        for block in pending:
            block.set_text(block.text)
        return False

    # ---- input -------------------------------------------------------------

    def on_input_changed(self, buf):
        self.placeholder.set_visible(buf.get_char_count() == 0 and not self.attachments)
        self.wake()

    def on_input_key(self, _view, event):
        mods = event.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK)
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if mods:
                self.input.get_buffer().insert_at_cursor("\n")
            else:
                self.submit()
            return True
        if event.keyval in (Gdk.KEY_Up, Gdk.KEY_Down) and not mods \
                and not event.state & Gdk.ModifierType.MOD1_MASK:
            return self.recall(-1 if event.keyval == Gdk.KEY_Up else 1)
        if mods == Gdk.ModifierType.CONTROL_MASK and Gdk.keyval_to_lower(event.keyval) == Gdk.KEY_v:
            return self.paste()
        return False

    def recall(self, step):
        """Up / Down through the messages sent. Only from an empty box or
        one still showing a recalled message as it was (an edited one is
        the user's: the arrows move the cursor again), and only from its
        first line going up, its last going down. Past the newest: empty."""
        buf = self.input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        browsing = self.hist_pos is not None and text == self.history[self.hist_pos]
        if not self.history or not (browsing or (not text and step < 0)):
            return False
        line = buf.get_iter_at_mark(buf.get_insert()).get_line()
        if (step < 0 and line != 0) or (step > 0 and line != buf.get_line_count() - 1):
            return False
        pos = (self.hist_pos if browsing else len(self.history)) + step
        if pos < 0:
            return True                 # the oldest: stay on it
        if pos >= len(self.history):
            self.hist_pos = None
            buf.set_text("")
        else:
            self.hist_pos = pos
            buf.set_text(self.history[pos])
            buf.place_cursor(buf.get_end_iter() if step > 0 else buf.get_start_iter())
        return True

    def on_key(self, _win, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        key = Gdk.keyval_to_lower(event.keyval)
        self.wake()
        if event.keyval == Gdk.KEY_Escape and self.search.get_search_mode():
            self.close_search()
            return True
        if event.keyval == Gdk.KEY_Escape:
            if self.busy():
                self.stop()
            else:
                self.quit()
            return True
        if ctrl and key in (Gdk.KEY_w, Gdk.KEY_q):
            self.quit()
            return True
        alt = event.state & Gdk.ModifierType.MOD1_MASK
        if alt and not ctrl and key in (Gdk.KEY_a, Gdk.KEY_s, Gdk.KEY_d) and self.cards:
            # The oldest open permission card (they are answered in order).
            card = next(iter(self.cards.values()))
            card.answer({Gdk.KEY_a: "once", Gdk.KEY_s: "session", Gdk.KEY_d: "deny"}[key])
            return True
        if ctrl and key == Gdk.KEY_p:
            self.perm_btn.set_active(True)
            return True
        if ctrl and key == Gdk.KEY_t:
            self.open_terminal()
            return True
        if ctrl and key == Gdk.KEY_n:
            self.new_session()
            return True
        if ctrl and key == Gdk.KEY_m and self.model_btn.get_sensitive():
            self.model_btn.set_active(True)
            return True
        if ctrl and key == Gdk.KEY_j and self.mascot_btn.get_sensitive():
            self.mascot_btn.set_active(True)
            return True
        if ctrl and key == Gdk.KEY_k:
            self.corner_btn.set_active(not self.corner_btn.get_active())
            return True
        if ctrl and key == Gdk.KEY_o:
            self.sessions_btn.set_active(True)
            return True
        if ctrl and key == Gdk.KEY_f:
            self.open_search()
            return True
        return False

    def submit(self):
        buf = self.input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not text and not self.attachments:
            return
        buf.set_text("")
        self.submit_text(text)

    def submit_text(self, text):
        """`text` and the attachments waiting over the box, sent."""
        images, self.attachments = self.attachments, []
        self.show_attachments()
        self.send(text, images)

    def send(self, text, images=()):
        self.stick = True
        self.hist_pos = None
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        if text:
            self.typed.append(text)
        shown = "\n".join([text] * bool(text) + [f"🖼 {a['name']}" for a in images])
        if self.busy():
            self.queue.append((text, images, self.user_bubble(shown, queued=True)))
            return
        self.user_bubble(shown)
        self.start_run(text, images=images)

    # ---- attachments ---------------------------------------------------------

    def paste(self):
        """Ctrl+V: an image on the clipboard (a screenshot) is attached,
        copied files are attached (images) or their paths typed (anything
        else); plain text pastes as always."""
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        if clip.wait_is_image_available():
            pixbuf = clip.wait_for_image()
            if pixbuf is not None:
                self.attach(pixbuf, time.strftime("pasted %H:%M:%S"))
                return True
        if clip.wait_is_uris_available():
            uris = clip.wait_for_uris() or []
            if self.add_uris(uris):
                return True
        return False

    def on_drop(self, widget, ctx, _x, _y, data, _info, stamp):
        uris = data.get_uris() or []
        pixbuf = None if uris else data.get_pixbuf()
        if not uris and pixbuf is None:
            return                      # text: the input box inserts it itself
        if pixbuf is not None:
            self.attach(pixbuf, "dropped image")
        else:
            self.add_uris(uris)
        if widget is self.input:
            # The text view would otherwise insert the URIs as text.
            widget.stop_emission_by_name("drag-data-received")
            Gtk.drag_finish(ctx, True, False, stamp)
        self.input.grab_focus()

    def add_uris(self, uris):
        """Local files: images attached, the rest typed into the box as
        paths (the model reads them with its tools). False if none was a
        local file."""
        paths = []
        for uri in uris:
            try:
                paths.append(GLib.filename_from_uri(uri)[0])
            except GLib.Error:
                continue
        if not paths:
            return False
        typed = []
        for path in paths:
            info = GdkPixbuf.Pixbuf.get_file_info(path) if os.path.isfile(path) else (None, 0, 0)
            if info[0] is not None:
                try:
                    self.attach(GdkPixbuf.Pixbuf.new_from_file(path), os.path.basename(path))
                    continue
                except GLib.Error:
                    pass
            typed.append(f'"{path}"' if any(c.isspace() for c in path) else path)
        if typed:
            buf = self.input.get_buffer()
            buf.insert_at_cursor(" ".join(typed) + " ")
        return True

    def attach(self, pixbuf, name):
        try:
            att = image_attachment(pixbuf, name)
        except (GLib.Error, ValueError) as exc:
            self.error(f"could not attach {name}: {exc}")
            return
        self.attachments.append(att)
        self.show_attachments()
        self.input.grab_focus()

    def show_attachments(self):
        for child in self.attach_row.get_children():
            child.destroy()
        for att in self.attachments:
            pill = Gtk.Box(spacing=4)
            pill.get_style_context().add_class("toolchip")
            pill.get_style_context().add_class("attachment")
            label = Gtk.Label(label=f"🖼 {att['name']}  ·  {att['size'][0]}×{att['size'][1]}")
            label.get_style_context().add_class("tool-name")
            drop = Gtk.Button(label="✕")
            drop.get_style_context().add_class("copy")
            drop.set_relief(Gtk.ReliefStyle.NONE)
            drop.set_can_focus(False)
            drop.set_tooltip_text("Don't send this one")
            drop.connect("clicked", lambda _b, a=att: self.unattach(a))
            pill.pack_start(label, False, False, 0)
            pill.pack_start(drop, False, False, 0)
            self.attach_row.pack_start(pill, False, False, 0)
            pill.show_all()
        self.attach_row.set_visible(bool(self.attachments))
        self.on_input_changed(self.input.get_buffer())

    def unattach(self, att):
        self.attachments = [a for a in self.attachments if a is not att]
        self.show_attachments()
        self.input.grab_focus()

    # ---- the claude process (a Claude model, Claude Code installed) ---------------

    def argv(self, claude, images=False, allow=()):
        argv = [claude, "-p", "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--permission-mode", perm_cli_mode(self.perm)]
        if self.live_prompts:
            # Permission requests come to this window (control_request on
            # stdout, answered on stdin): see the docstring.
            argv += ["--input-format", "stream-json", "--permission-prompt-tool", "stdio"]
        elif images:
            argv += ["--input-format", "stream-json"]
        if self.session_id:
            argv += ["--resume", self.session_id]
        for rule in allow:
            argv += ["--allowedTools", rule]
        return argv + self.spec()[0]

    def spec(self):
        """(extra claude argv, env changes) for the chosen Claude model."""
        if llm_models is None or self.choice is None:
            return (["--model", MODEL] if MODEL else []), {}
        return llm_models.launch_spec(self.choice), {}

    def busy(self):
        return self.running() or self.preparing is not None

    def has_conversation(self):
        return bool(self.session_id) if self.session_kind == "claude" else bool(self.chat)

    def start_run(self, prompt, ready=False, images=()):
        choice = self.choice
        kind = backend(choice)
        if self.has_conversation() and kind != self.session_kind:
            # A Claude session cannot go on in the native engine, nor the
            # other way round (Claude Code's session files against plain
            # messages): a new one, said so -- unless the pick that caused
            # it said so already.
            if not self.fresh_said:
                self.note(f"new session: {choice.name if choice else 'this model'} is "
                          f"{'Claude' if kind == 'claude' else 'not Claude'}, the conversation so far "
                          f"stays where it was ({self.session_ref()}, Ctrl+O)")
            self.forget_conversation()
        self.fresh_said = False
        if not ready:
            self.mood_event("prompt", text=prompt)
        if kind == "native":
            if engine is None:
                self.error("llm_chat_engine.py is missing next to this script: only Claude models work")
                self.set_state("error")
                return
            if choice is None:
                self.error("no model to ask: LM Studio has no model (Ctrl+M: Find and download models…)"
                           + ("" if find_claude() else ", and Claude Code is not installed"))
                self.set_state("error")
                return
            if choice.local and not ready:
                self.prepare_local(prompt, choice, images)
                return
            self.start_native(prompt, images)
            return
        self.session_kind = kind
        self.run_choice = choice
        claude = find_claude()
        if claude is None:
            self.error("Claude Code is not installed (no `claude` on $PATH or in ~/.local/bin): pick a "
                       "local model (Ctrl+M)")
            self.set_state("error")
            return
        env = dict(os.environ)
        for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
            env.pop(key, None)      # a nested-session marker, if launched from claude
        allow, self.allow_once = self.allow_once, []
        try:
            proc = subprocess.Popen(self.argv(claude, bool(images), allow), cwd=self.cwd, env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True)
        except OSError as exc:
            self.error(f"could not start claude: {exc}")
            self.set_state("error")
            return
        self.proc = proc
        self.pgids.append(proc.pid)
        self.run_started = time.monotonic()
        self.out_buf = b""
        self.err_buf = b""
        self.got_result = False
        self.stopping = False
        self.live = None
        self.streamed = {}
        self.active_tools = {}
        self.last_text = ""
        self.status_extra = None
        if images or self.live_prompts:
            # One user message as stream-json: the images, then the words.
            content = [{"type": "image", "source": {"type": "base64", "media_type": a["media"],
                                                    "data": base64.b64encode(a["data"]).decode()}}
                       for a in images]
            if prompt:
                content.append({"type": "text", "text": prompt})
            if not images:
                content = prompt
            payload = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
        else:
            payload = prompt
        try:
            proc.stdin.write(payload.encode("utf-8", "replace"))
            proc.stdin.flush()
            if not self.live_prompts:
                proc.stdin.close()
        except (OSError, ValueError):
            pass
        for pipe in (proc.stdout, proc.stderr):
            fd = pipe.fileno()
            fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
        cond = GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR
        self.watches = [
            GLib.io_add_watch(proc.stdout.fileno(), GLib.PRIORITY_DEFAULT, cond, self.on_stdout, proc),
            GLib.io_add_watch(proc.stderr.fileno(), GLib.PRIORITY_DEFAULT, cond, self.on_stderr, proc),
        ]
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, proc.pid, self.on_exit, proc)
        self.stop_btn.show()
        self.send_btn.set_label(self.ui["wait"])
        self.set_state("thinking")
        self.update_status()

    @staticmethod
    def _read(fd):
        chunks = []
        while True:
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                return b"".join(chunks), False
            except OSError:
                return b"".join(chunks), True
            if not data:
                return b"".join(chunks), True
            chunks.append(data)

    def on_stdout(self, fd, _cond, proc):
        if proc is not self.proc:
            return False
        data, eof = self._read(fd)
        if data:
            self.out_buf += data
            *lines, self.out_buf = self.out_buf.split(b"\n")
            for line in lines:
                self.handle_line(line)
        return not eof

    def on_stderr(self, fd, _cond, proc):
        if proc is not self.proc:
            return False
        data, eof = self._read(fd)
        if data:
            self.err_buf = (self.err_buf + data)[-STDERR_KEEP:]
        return not eof

    def handle_line(self, raw):
        raw = raw.strip()
        if not raw:
            return
        try:
            event = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        try:
            self.handle_event(event)
        except Exception as exc:  # a surprise in one event must not end the run
            print(f"llm-chat: event {event.get('type')}: {exc!r}", file=sys.stderr)

    def handle_event(self, ev):
        kind = ev.get("type")
        if ev.get("session_id"):
            self.session_id = ev["session_id"]
        if kind == "system":
            if ev.get("subtype") == "init":
                self.model = ev.get("model") or self.model
                self.mode = ev.get("permissionMode") or self.mode
                if ev.get("cwd"):
                    self.cwd = ev["cwd"]
                    self.get_titlebar().set_subtitle(short_path(self.cwd))
                self.update_status()
            elif ev.get("subtype") == "status" and not self.active_tools:
                self.set_state("thinking")
        elif kind == "stream_event":
            self.handle_stream(ev.get("event") or {}, ev.get("parent_tool_use_id"))
        elif kind == "assistant":
            self.handle_assistant(ev.get("message") or {}, ev.get("parent_tool_use_id"))
        elif kind == "user":
            self.handle_user(ev.get("message") or {})
        elif kind == "result":
            self.handle_result(ev)
        elif kind == "control_request":
            self.handle_control(ev)
        elif kind == "control_cancel_request" and ev.get("request_id"):
            self.cancel_card(str(ev["request_id"]))

    def handle_stream(self, se, parent):
        t = se.get("type")
        if t == "message_start":
            self.msg_id = (se.get("message") or {}).get("id")
        elif t == "content_block_start":
            block = se.get("content_block") or {}
            bt = block.get("type")
            if bt == "text" and not parent:
                self.live = self.add_row(AssistantBlock())
                self.streamed.setdefault(getattr(self, "msg_id", None), []).append(self.live)
                self.set_state("writing")
            elif bt == "thinking":
                self.set_state("thinking")
            elif bt in ("tool_use", "server_tool_use", "mcp_tool_use") and block.get("id"):
                self.tool_started(block["id"], block.get("name") or "tool", None, parent)
        elif t == "content_block_delta":
            delta = se.get("delta") or {}
            if delta.get("type") == "text_delta" and self.live is not None and not parent:
                self.live.text += delta.get("text", "")
                self.schedule_render(self.live)
                if not self.active_tools:
                    self.set_state("writing")
                else:
                    self.wake()
            elif delta.get("type") == "thinking_delta":
                self.wake()
        elif t == "content_block_stop":
            self.live = None
        elif t == "message_stop" and not self.active_tools:
            self.set_state("thinking")

    def handle_assistant(self, msg, parent):
        mid = msg.get("id")
        usage = msg.get("usage")
        if not parent and isinstance(usage, dict):
            # What this request sent (fresh, cached, newly cached) plus what
            # it wrote: the context the next one starts from.
            used = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens", "output_tokens"))
            if used:
                self.ctx_used = used
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            bt = block.get("type")
            if bt == "text":
                text = block.get("text") or ""
                if parent:
                    continue
                pending = self.streamed.get(mid) or []
                if pending:
                    target = pending.pop(0)
                else:
                    if not text.strip():
                        continue
                    target = self.add_row(AssistantBlock())
                target.text = text
                self.render_pending.discard(target)
                target.set_text(text)
                self.last_text = text
                self.mood_event("reply", text=text)
            elif bt in ("tool_use", "server_tool_use", "mcp_tool_use") and block.get("id"):
                self.tool_started(block["id"], block.get("name") or "tool", block.get("input"), parent)

    def tool_started(self, tid, name, data, parent):
        chip = self.chips.get(tid)
        if chip is None:
            chip = self.add_row(ToolChip(name, nested=bool(parent)))
            self.chips[tid] = chip
            self.active_tools[tid] = name
        if data is not None:
            chip.set_input(data)
        if chip.running:
            self.set_state("tool", name)

    def handle_user(self, msg):
        content = msg.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tid = block.get("tool_use_id")
            chip = self.chips.get(tid)
            if chip is None or not chip.running:
                continue
            chip.finish(result_text(block.get("content")), bool(block.get("is_error")))
            self.active_tools.pop(tid, None)
            self.mood_event("tool_error" if block.get("is_error") else "tool_ok")
        if self.active_tools:
            last = list(self.active_tools.values())[-1]
            self.set_state("tool", last)
        else:
            self.set_state("thinking")

    def handle_result(self, ev):
        self.got_result = True
        self.close_stdin()          # the turn is over: claude may exit
        self.expire_cards()
        # total_cost_usd is the session's, not the run's: a --resume run
        # reports what the whole conversation has cost so far (checked
        # against the CLI: 0.0040, 0.0080, 0.0122 for three turns of ~0.004).
        # So it replaces the total, and the run's own cost is the step.
        cost = ev.get("total_cost_usd")
        run_cost = None
        local = self.run_choice is not None and self.run_choice.local
        if local:
            cost = None         # claude's price for tokens that cost nothing here
        if isinstance(cost, (int, float)):
            if self.cost_prev is not None and cost >= self.cost_prev:
                run_cost = cost - self.cost_prev
            self.cost = self.cost_prev = cost
        windows = [u.get("contextWindow") for u in (ev.get("modelUsage") or {}).values()
                   if isinstance(u, dict) and isinstance(u.get("contextWindow"), int)]
        if windows:
            self.ctx_max = max(windows)
        bad = bool(ev.get("is_error")) or (ev.get("subtype") not in (None, "success"))
        bits = []
        if ev.get("num_turns") is not None:
            n = ev["num_turns"]
            bits.append(f"{n} turn{'s' if n != 1 else ''}")
        if isinstance(ev.get("duration_ms"), (int, float)):
            bits.append(f"{ev['duration_ms'] / 1000:.1f} s")
        if local:
            bits.append(self.run_choice.name + " (local)")
        elif run_cost is not None:
            bits.append(f"${run_cost:.4f}")
        elif isinstance(cost, (int, float)):
            bits.append(f"${cost:.4f} in all")
        for chip in self.chips.values():
            if chip.running:
                chip.finish("", bad)
        self.active_tools = {}
        # What the user said no to on a card is no refusal to retry.
        denials = [d for d in ev.get("permission_denials") or []
                   if not (isinstance(d, dict) and d.get("tool_use_id") in self.denied_ids)]
        if denials:
            names, rules = [], []
            for d in denials:
                if isinstance(d, dict):
                    tool, data = d.get("tool_name") or "?", d.get("tool_input") or {}
                    names.append(one_line(f"{tool} {tool_summary(tool, data)}", 90))
                    rule = allow_rule(tool, data)
                    if rule and rule not in rules:
                        rules.append(rule)
            self.error(f"refused in {perm_label(self.perm)} mode ({len(denials)}):\n  " + "\n  ".join(names)
                       + "\nAllow them for one more run below, or Ctrl+T for the terminal.")
            if rules:
                self.retry_button(rules)
        secs = ev["duration_ms"] / 1000 if isinstance(ev.get("duration_ms"), (int, float)) else None
        self.mood_event("stopped" if self.stopping else "result_error" if bad else "result_ok",
                        duration=secs)
        if self.stopping:
            self.note("■ stopped · " + " · ".join(bits) if bits else "■ stopped")
            self.set_state("idle")
        elif bad:
            detail = ev.get("result") or ", ".join(ev.get("errors") or []) or ev.get("subtype") or "error"
            self.error(f"claude reported an error: {detail}")
            self.note("✗ " + " · ".join(bits) if bits else "✗")
            self.set_state("error")
            self.notify("failed", self.ui["n_failed"], one_line(str(detail), 160))
        else:
            self.note(self.ui["done"] + " · " + " · ".join(bits))
            self.set_state("done")
            self.notify("done", self.ui["n_done"],
                        first_line(self.last_text or ev.get("result") or "") or " · ".join(bits))
        self.update_status()

    def retry_button(self, rules):
        """Under a refusal: one click allows exactly what was refused
        (--allowedTools, for the next run only) and asks claude to retry."""
        button = Gtk.Button(label=self.ui["retry"])
        button.get_style_context().add_class("retry")
        button.set_halign(Gtk.Align.START)
        button.set_tooltip_text("Next run only: --allowedTools " + "  ".join(rules))

        code = any(rule.startswith(CODE_TOOLS) for rule in rules)
        sure = {"at": 0.0}

        def reset():
            sure["at"] = 0.0
            button.set_label(self.ui["retry"])
            button.get_style_context().remove_class("perm-sure")
            return False

        def clicked(_b):
            if self.busy():
                self.note("still running — retry once it is done")
                return
            now = time.monotonic()
            if code and not sure["at"]:     # runs code: a second press confirms (as on the cards)
                sure["at"] = now
                button.set_label(self.ui["perm_sure_once"])
                button.get_style_context().add_class("perm-sure")
                GLib.timeout_add(CONFIRM_MS, reset)
                return
            if code and (now - sure["at"]) * 1000 < CONFIRM_GAP_MS:
                return
            button.set_sensitive(False)
            self.allow_once = list(rules)
            self.send("Those actions were refused without asking me (the permission mode or a "
                      "rule, not my answer). I have allowed exactly them for this run: retry them.")

        button.connect("clicked", clicked)
        self.add_row(button)

    def on_exit(self, pid, status, proc):
        try:
            code = os.waitstatus_to_exitcode(status)
        except ValueError:
            code = status
        proc.returncode = code
        if proc is not self.proc:
            # Not the window's run (cannot happen while queued runs start
            # here, synchronously; kept so a stray one never leaks its pipes).
            for pipe in (proc.stdout, proc.stderr):
                try:
                    pipe.close()
                except OSError:
                    pass
            self.prune_pgids()
            return
        # Whatever is still in the pipes, then let go of them (a background
        # process claude left may hold them open: no waiting for EOF).
        for fd, handler in ((proc.stdout.fileno(), "out"), (proc.stderr.fileno(), "err")):
            data, _ = self._read(fd)
            if handler == "out":
                self.out_buf += data
            else:
                self.err_buf = (self.err_buf + data)[-STDERR_KEEP:]
        lines = self.out_buf.split(b"\n")
        self.out_buf = b""
        for line in lines:
            self.handle_line(line)
        context = GLib.MainContext.default()
        for watch in self.watches:
            if context.find_source_by_id(watch) is not None:
                GLib.source_remove(watch)
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        self._render_now()
        self.close_stdin(proc)
        self.expire_cards()
        self.proc = None
        self.prune_pgids()
        self.last_run = time.monotonic() - self.run_started
        self.stop_btn.hide()
        self.send_btn.set_label(self.ui["send"])
        if not self.got_result:
            err = self.err_buf.decode("utf-8", "replace").strip()
            if self.stopping:
                self.note("■ stopped")
                self.set_state("idle")
            else:
                self.mood_event("result_error")
                msg = f"claude exited with code {code} and no result."
                if err:
                    msg += "\n\n" + err[-4000:]
                self.error(msg)
                self.set_state("error")
                self.notify("failed", self.ui["n_failed"], first_line(err) or f"exit code {code}")
                if self.live_prompts and re.search(r"permission-prompt-tool|input-format|unknown option",
                                                   err, re.I):
                    # A claude without the control protocol: back to asking
                    # after the fact (refusals + retry) for this window.
                    self.live_prompts = False
                    self.note("this claude cannot ask for permission during a run: refusals show "
                              "at the end of a run, with a retry button. Send the message again.")
            for chip in self.chips.values():
                if chip.running:
                    chip.finish("", True)
        elif code not in (0, None) and self.err_buf.strip() and self.state != "error":
            self.error(self.err_buf.decode("utf-8", "replace").strip()[-4000:])
        self.after_run()

    def prune_pgids(self):
        """Forget the process groups that have emptied. Their numbers are free
        again, and one handed to a new group leader (a shell, an app started
        with setsid) would otherwise get kill_all's TERM and KILL."""
        live = []
        for pgid in self.pgids:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue        # reused already, by another user's group
            live.append(pgid)
        self.pgids = live

    def _signal(self, sig, proc):
        if proc.returncode is not None:
            return False
        # The last resort reaches the tools' own groups too: claude, killed
        # outright, cannot end them itself.
        kids = descendants(proc.pid) if sig == signal.SIGKILL else ()
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        kill_pids(kids, sig)
        return False

    def stop(self):
        if self.native is not None:
            # The stream cut, a running command's group ended, every open
            # question a no: the Run ends itself with done(stopped).
            self.stopping = True
            for *_, label in self.queue:
                label.get_style_context().add_class("dropped")
                label.set_tooltip_text("not sent: the reply was stopped")
            self.queue = []
            self.expire_cards()
            self.native.cancel()
            self.bubble.set_text(self.ui["stopping"])
            return
        if self.preparing is not None and self.proc is None:
            # lms load goes on to the end in its thread (it cannot be asked
            # to stop halfway); its answer is dropped.
            self.preparing = None
            self.bubble_override = None
            for *_, label in self.queue:
                label.get_style_context().add_class("dropped")
                label.set_tooltip_text("not sent: stopped while the model was loading")
            self.queue = []
            self.stop_btn.hide()
            self.send_btn.set_label(self.ui["send"])
            self.note("■ stopped before the model was ready (it may still finish loading)")
            self.set_state("idle")
            self.update_status()
            if self.unload_after_stop is not None:
                key, name = self.unload_after_stop
                self.unload_after_stop = None
                self.start_unload(key, name)
            return
        proc = self.proc
        if proc is None:
            return
        self.stopping = True
        for *_, label in self.queue:
            label.get_style_context().add_class("dropped")
            label.set_tooltip_text("not sent: the run was stopped")
        self.queue = []
        self.expire_cards()
        self._signal(signal.SIGINT, proc)
        GLib.timeout_add(2000, self._signal, signal.SIGTERM, proc)
        GLib.timeout_add(4000, self._signal, signal.SIGKILL, proc)
        self.bubble.set_text(self.ui["stopping"])

    def kill_all(self):
        """Every process group this window started, ended: TERM, a moment for
        claude to save its session, then KILL whatever is left -- claude's
        groups, and whatever its tools started in groups of their own and
        claude did not end on its way out."""
        kids = []
        if self.native is not None:
            self.native.cancel()        # its command's group is in self.pgids too
        if self.proc is not None and self.proc.returncode is None:
            kids = descendants(self.proc.pid)
        self.prune_pgids()
        alive = []
        for pgid in self.pgids:
            try:
                os.killpg(pgid, signal.SIGTERM)
                alive.append(pgid)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.monotonic() + 1.5
        while alive and time.monotonic() < deadline:
            if self.proc is not None:
                try:
                    if os.waitpid(self.proc.pid, os.WNOHANG)[0]:
                        self.proc.returncode = 0
                except ChildProcessError:
                    pass
            still = []
            for pgid in alive:
                try:
                    os.killpg(pgid, 0)
                    still.append(pgid)
                except (ProcessLookupError, PermissionError):
                    pass
            alive = still
            if alive:
                time.sleep(0.05)
        for pgid in alive:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        kill_pids(kids)

    # ---- the native engine (local and server models) --------------------------------

    def session_ref(self):
        if self.session_kind == "claude":
            return f"session {self.session_id[:8]}" if self.session_id else "no session"
        return self.chat_id or "not saved yet"

    def forget_conversation(self):
        """The current conversation let go of (not deleted): the next
        message starts a new one, on either backend."""
        self.session_id = None
        self.chat, self.chat_id = [], None
        self.cost_prev = 0.0
        self.ctx_used = None
        self.perm_rules = []
        self.denied_ids = set()
        self.typed = []
        self.access = self.new_access()

    def implied_folders(self):
        """The folders open to the native engine's reading tools without a
        Folder access prompt: the ones you typed in this conversation, and
        the working directory unless it is your home folder itself."""
        out = []
        home = os.path.realpath(os.path.expanduser("~"))
        if self.cwd and os.path.realpath(self.cwd) != home:
            out.append(self.cwd)
        if folder_access is not None:
            for text in self.typed:
                try:
                    out += folder_access.typed_folders(text)
                except Exception:       # noqa: BLE001
                    pass
        return out

    def start_native(self, prompt, images=()):
        choice = self.choice
        ep = engine.endpoint("server" if choice.kind == "server" else "local")
        if ep is None:
            self.error("no OpenAI-compatible server is set (Settings > AI & models, or "
                       "`llm_models.py set server_url URL`): pick a local model (Ctrl+M)")
            self.set_state("error")
            return
        if self.session_kind != "native":
            self.forget_conversation()
        self.session_kind = "native"
        if prompt and (not self.typed or self.typed[-1] != prompt):
            self.typed.append(prompt)       # a switch of backend forgot it with the rest
        self.run_choice = choice
        tools = choice.ident not in self.no_tools
        message = engine.user_message(prompt, [{"media": a["media"], "data": a["data"]} for a in images])
        run = engine.Run(ep, choice.ident, self.chat + [message],
                         lambda kind, data: GLib.idle_add(self.on_native, run_box[0], kind, data),
                         mode=self.perm if self.perm in PERM_KEYS else "ask", cwd=self.cwd, tools=tools,
                         session=self.access, implied=self.implied_folders(),
                         prompt=not self.render)
        run_box = [run]
        self.native = run
        self.run_started = time.monotonic()
        self.live = None
        self.thinking = None
        self.streamed = {}
        self.active_tools = {}
        self.last_text = ""
        self.status_extra = None
        self.stopping = False
        self.model = choice.ident
        self.usage_max = (llm_models.local_options()[0] if choice.local and llm_models is not None else None)
        self.stop_btn.show()
        self.send_btn.set_label(self.ui["wait"])
        self.set_state("thinking")
        self.update_model_button()
        self.update_status()
        run.start()

    def on_native(self, run, kind, data):
        """One event of a native Run, on the GTK loop (Run docstring)."""
        if run is not self.native or self.closing:
            if kind == "ask" and run is not None:
                run.answer(data["req"]["id"], False)    # nobody here to ask any more
            return False
        try:
            self.native_event(run, kind, data)
        except Exception as exc:    # a surprise in one event must not end the window
            print(f"llm-chat: native event {kind}: {exc!r}", file=sys.stderr)
        return False

    def native_event(self, run, kind, data):
        if kind == "start":
            self.live = None
            self.thinking = None
            if data["step"] and not self.active_tools:
                self.set_state("thinking")
        elif kind == "text":
            if self.live is None:
                self.live = self.add_row(AssistantBlock())
                self.thinking = None
            self.live.text += data["text"]
            self.schedule_render(self.live)
            self.set_state("writing") if not self.active_tools else self.wake()
        elif kind == "reasoning":
            if self.thinking is None:
                self.thinking = self.thinking_row()
            self.thinking.text += data["text"]
            self.thinking.update()
            self.set_state("thinking")
        elif kind == "tool":
            self.live = None
            self.thinking = None
            chip = self.add_row(ToolChip(data["name"], kind=data["canon"]))
            self.chips[data["id"]] = chip
            self.active_tools[data["id"]] = data["name"]
            chip.set_input(data["input"])
            self.set_state("tool", data["canon"])
        elif kind == "tool_done":
            chip = self.chips.get(data["id"])
            if chip is not None and chip.running:
                chip.finish(data["output"], data["is_error"])
            self.active_tools.pop(data["id"], None)
            self.mood_event("tool_error" if data["is_error"] else "tool_ok")
            if self.active_tools:
                self.set_state("tool", list(self.active_tools.values())[-1])
            else:
                self.set_state("thinking")
        elif kind == "ask":
            self.native_ask(run, data["req"])
        elif kind == "pgid":
            self.pgids.append(data["pgid"])
        elif kind == "no_tools":
            self.no_tools.add(run.model)
            self.note(f"{self.choice.name if self.choice else run.model} takes no tools here: plain chat, no "
                      f"files or commands ({one_line(data['why'], 120)})")
            self.update_status()
        elif kind == "usage":
            self.ctx_used = (data["prompt"] or 0) + (data["completion"] or 0) or self.ctx_used
            self.ctx_max = self.usage_max
            self.update_status()
        elif kind == "done":
            self.native_done(run, data)

    def thinking_row(self):
        """A folded "thinking" row (a model's reasoning), filled as it comes."""
        exp = Gtk.Expander(label="thinking…")
        exp.get_style_context().add_class("tool-output")
        exp.get_style_context().add_class("thinking")
        body = text_label(("tool-excerpt",))
        exp.add(body)
        exp.text = ""

        def update():
            n = exp.text.count("\n") + 1
            exp.set_label(f"thinking · {n} line{'s' if n != 1 else ''}")
            body.set_text(exp.text.strip()[-20000:])
        exp.update = update
        self.add_row(exp)
        return exp

    def native_ask(self, run, req):
        """A native tool call that needs a yes: a session rule answers it at
        once, else a card (the same PermCard as for Claude)."""
        for rule in self.perm_rules:
            if rule_matches(rule, req["tool"], req["input"], self.cwd):
                run.answer(req["id"], True)
                self.note(self.ui["perm_auto"].format(rule=rule_text(rule)))
                return
        self.show_card(req)

    def show_card(self, req):
        card = PermCard(req, self.cwd, self.ui, self.on_perm_answer)
        self.cards[req["id"]] = card
        self.stick = True
        self.add_row(card)
        self.bubble_override = self.ui["perm_bubble"]
        self.set_state("thinking")
        self.mood_event("permission")
        self.update_status()
        head = perm_details(req, self.cwd)[0]
        self.notify("permission", self.ui["n_perm"], one_line(f"{req['display']}: {head}", 160),
                    key="perm:" + req["id"])

    def native_done(self, run, data):
        self.native = None
        self._render_now()
        self.expire_cards()
        self.last_run = data["seconds"]
        self.stop_btn.hide()
        self.send_btn.set_label(self.ui["send"])
        for chip in self.chips.values():
            if chip.running:
                chip.finish("", True)
        self.active_tools = {}
        self.chat = list(data["messages"])
        if self.chat and not self.render:
            self.chat_id = self.chat_id or engine.new_session_id()
            try:
                engine.save_session(self.chat_id, self.chat, self.cwd, self.choice.name if self.choice else run.model)
            except OSError as exc:
                self.error(f"could not save the conversation: {exc}")
        steps = data["steps"]
        bits = [f"{steps} step{'s' if steps != 1 else ''}" if steps > 1 else "",
                f"{data['seconds']:.1f} s",
                (self.run_choice.name + (" (local)" if self.run_choice.local else "")) if self.run_choice else "",
                "" if data["tools"] else "no tools"]
        bits = [b for b in bits if b]
        if data["stopped"]:
            self.mood_event("stopped", duration=data["seconds"])
            self.note("■ stopped · " + " · ".join(bits))
            self.set_state("idle")
        elif data["error"]:
            self.mood_event("result_error", duration=data["seconds"])
            where = (self.run_choice.label if self.run_choice and self.run_choice.kind == "server"
                     else "LM Studio")
            self.error(f"{where}: {data['error']}")
            self.note("✗ " + " · ".join(bits))
            self.set_state("error")
            self.notify("failed", self.ui["n_failed"], first_line(data["error"]))
        else:
            reply = next((m.get("content") for m in reversed(self.chat)
                          if m.get("role") == "assistant" and m.get("content")), "") or ""
            self.last_text = reply
            self.mood_event("reply", text=reply)
            self.mood_event("result_ok", duration=data["seconds"])
            self.note(self.ui["done"] + " · " + " · ".join(bits))
            self.set_state("done")
            self.notify("done", self.ui["n_done"], first_line(reply) or " · ".join(bits))
        self.after_run()

    def after_run(self):
        """What follows any reply's end: an unload waiting for it, the
        loaded look, the status, the next queued message."""
        if self.unload_after_stop is not None and not self.closing:
            key, name = self.unload_after_stop
            self.unload_after_stop = None
            self.queue = []
            self.start_unload(key, name)
        elif self.run_choice is not None and self.run_choice.local:
            self.refresh_loaded()       # its idle timer started again
        self.update_status()
        # The queued message starts here and now, not from an idle callback:
        # key events outrank idle sources, so an Enter in that gap found no
        # run, started its own, and the idle one then took the run from it
        # -- a second one on the session, unwatched (and an Esc there closed
        # the window instead of stopping the run).
        if self.queue and not self.closing:
            text, images, label = self.queue.pop(0)
            label.get_style_context().remove_class("queued")
            label.set_tooltip_text(None)
            self.start_run(text, images=images)

    def open_native(self, sid_or_info):
        """A saved native conversation drawn again; the next message goes on
        with it (in its own directory, on its model when that is still
        there)."""
        try:
            data = engine.load_session(sid_or_info["path"] if isinstance(sid_or_info, dict) else sid_or_info)
        except (OSError, ValueError) as exc:
            self.error(f"could not open that conversation: {exc}")
            return
        self.clear()
        self.forget_conversation()
        self.session_kind = "native"
        self.chat = [m for m in data["messages"] if isinstance(m, dict)]
        self.chat_id = data.get("id")
        if data.get("cwd") and os.path.isdir(data["cwd"]):
            self.cwd = data["cwd"]
            self.get_titlebar().set_subtitle(short_path(self.cwd))
        model = llm_models.resolve(data["model"], prefix=False) if llm_models and data.get("model") else None
        if model is not None and backend(model) == "native" and model != self.choice:
            self.choice = model
            self.update_model_button()
        self.stick = True
        self.replay_native(self.chat)
        self.note(f"resuming {self.chat_id} · {one_line(data.get('title') or '', 60)}")
        self.set_state("idle")
        self.update_status()

    def replay_native(self, messages):
        shown = messages[-REPLAY_EVENTS:]
        if len(messages) > len(shown):
            self.note(f"… {len(messages) - len(shown)} earlier messages not shown")
        self.replaying = True
        try:
            for m in shown:
                role = m.get("role")
                if role == "user":
                    words = engine.message_words(m.get("content"))
                    if words:
                        self.user_bubble(words)
                elif role == "assistant":
                    text = re.sub(r"<think>.*?</think>", "", str(m.get("content") or ""), flags=re.S).strip()
                    if text:
                        block = self.add_row(AssistantBlock())
                        block.text = text
                        block.set_text(text)
                    for call in m.get("tool_calls") or []:
                        fn = call.get("function") or {}
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except ValueError:
                            args = {}
                        cname, cinput = engine.canon(fn.get("name") or "tool", args)
                        chip = self.add_row(ToolChip(fn.get("name") or "tool", kind=cname))
                        chip.set_input(cinput)
                        self.chips[call.get("id") or id(chip)] = chip
                elif role == "tool":
                    chip = self.chips.get(m.get("tool_call_id"))
                    if chip is not None and chip.running:
                        out = str(m.get("content") or "")
                        chip.finish(out, out.startswith(("The user denied", "stopped")))
        finally:
            self.replaying = False
        for chip in self.chips.values():
            if chip.running:
                chip.finish("", False)

    # ---- a server's models -------------------------------------------------------------

    def refresh_server(self):
        """The server's /models, in a thread (when a server is set)."""
        if self.server_busy or engine is None or self.closing:
            return
        ep = engine.endpoint("server")
        if ep is None:
            self.server_list = None
            return
        self.server_busy = True

        def work():
            try:
                found, why = engine.server_models(ep), None
            except engine.ServerError as exc:
                found, why = None, exc.message
            GLib.idle_add(self.server_listed, found, why)

        import threading
        threading.Thread(target=work, daemon=True).start()

    def server_listed(self, found, why):
        self.server_busy = False
        if self.closing:
            return False
        self.server_list = found if found is not None else []
        self.server_error = why
        if self.model_pop.get_visible():
            self.fill_model_menu(refresh=False)
        return False

    # ---- permissions (the control protocol) ----------------------------------

    def write_control(self, obj):
        """One line to the running claude's stdin (a control_response)."""
        proc = self.proc
        if proc is None or proc.stdin is None or proc.stdin.closed:
            return False
        try:
            proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def close_stdin(self, proc=None):
        """The run's input closed: claude ends once its turn is over (with
        stream-json input it would otherwise wait for another message)."""
        proc = proc or self.proc
        if proc is not None and proc.stdin is not None and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except OSError:
                pass

    def handle_control(self, ev):
        req = can_use_tool(ev)
        rid = ev.get("request_id")
        if req is None:
            if rid:
                sub = (ev.get("request") or {}).get("subtype") if isinstance(ev.get("request"), dict) else None
                self.write_control(error_response(rid, f"llm-chat does not handle {sub or 'this'}"))
            return
        if self.replaying:
            return
        for rule in self.perm_rules:
            if rule_matches(rule, req["tool"], req["input"], self.cwd):
                self.write_control(allow_response(req["id"], req["input"]))
                self.note(self.ui["perm_auto"].format(rule=rule_text(rule)))
                return
        self.show_card(req)

    def on_perm_answer(self, card, choice, note=""):
        req = card.req
        refocus = card.note.has_focus() or any(b.has_focus() for b in card.buttons.values())
        if self.cards.get(req["id"]) is not card or not self.running():
            card.settle(self.ui["perm_gone"], "expired")
            return
        native = self.native if req.get("native") else None
        if choice == "deny":
            ok = (native.answer(req["id"], False, note) if native is not None
                  else self.write_control(deny_response(req["id"], note)))
            if req.get("tool_use_id"):
                self.denied_ids.add(req["tool_use_id"])
            text = self.ui["perm_denied"] + (f": {one_line(note, 120)}" if note.strip() else "")
            cls = "denied"
            self.mood_event("permission_denied")
        elif choice == "session":
            if card.rule not in self.perm_rules:
                self.perm_rules.append(card.rule)
            ok = (native.answer(req["id"], True) if native is not None
                  else self.write_control(allow_response(req["id"], req["input"], card.updated)))
            text, cls = self.ui["perm_allowed_session"].format(rule=rule_text(card.rule)), "allowed"
            self.mood_event("permission_allowed")
        else:
            ok = (native.answer(req["id"], True) if native is not None
                  else self.write_control(allow_response(req["id"], req["input"])))
            text, cls = self.ui["perm_allowed"], "allowed"
            self.mood_event("permission_allowed")
        del self.cards[req["id"]]
        card.settle(text if ok else self.ui["perm_gone"], cls if ok else "expired")
        self.dismiss_note("perm:" + req["id"])
        if choice == "session":
            # Other open cards the new rule covers (parallel calls) go too.
            for other in list(self.cards.values()):
                if rule_matches(card.rule, other.req["tool"], other.req["input"], self.cwd):
                    self.on_perm_answer(other, "once")
        if not self.cards:
            self.bubble_override = None
            if self.active_tools:
                self.set_state("tool", list(self.active_tools.values())[-1])
        if refocus:
            self.input.grab_focus()     # the card's controls are gone: back to the box
        self.update_status()

    def cancel_card(self, rid):
        card = self.cards.pop(rid, None)
        if card is not None:
            card.settle(self.ui["perm_gone"], "expired")
            self.dismiss_note("perm:" + rid)
        if not self.cards:
            self.bubble_override = None

    def expire_cards(self):
        for rid in list(self.cards):
            self.cancel_card(rid)

    def set_perm(self, key):
        self.perm_pop.popdown()
        self.input.grab_focus()
        if key == self.perm:
            return
        self.perm = key
        self.mode = perm_cli_mode(key)
        write_front_state(permissions=key)
        self.note(f"permissions: {perm_label(key)}"
                  + (" — from the next message" if self.busy() else ""))
        self.update_perm_button()
        self.update_status()

    def update_perm_button(self):
        self.perm_label.set_text(perm_label(self.perm) + "  ▾")

    def fill_perm_menu(self):
        old = self.perm_pop.get_child()
        if old is not None:
            old.destroy()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_name("model-list")
        current = []

        def label(text, cls):
            lab = Gtk.Label(label=text, xalign=0)
            lab.get_style_context().add_class(cls)
            lab.set_line_wrap(True)
            lab.set_max_width_chars(48)
            box.pack_start(lab, False, False, 0)

        label("Permissions", "model-heading")
        for key, text, cli, what in PERM_MODES:
            button = Gtk.ModelButton(text=text + ("   ★" if key == PERM_DEFAULT else ""),
                                     role=Gtk.ButtonRole.RADIO)
            button.set_property("active", key == self.perm)
            button.set_tooltip_text(what + (f"  (Claude: --permission-mode {cli})" if find_claude() else ""))
            button.connect("clicked", lambda *_, k=key: self.set_perm(k))
            box.pack_start(button, False, False, 0)
            if key == self.perm:
                current.append(button)
        if self.perm not in PERM_KEYS:
            label(f"now: {self.perm} ($LLM_CHAT_PERMISSION; a local model asks as in Ask me)", "model-detail")
        if not self.live_prompts:
            label("this claude cannot ask during a run: refusals show at its end", "model-detail")
        box.pack_start(Gtk.Separator(), False, False, 4)
        label("Allowed for this session", "model-heading")
        if self.perm_rules:
            for rule in self.perm_rules:
                label("  " + rule_text(rule), "model-detail")
            forget = Gtk.ModelButton(text="Forget them")
            forget.connect("clicked", lambda *_: self.forget_rules())
            box.pack_start(forget, False, False, 0)
        else:
            label("  nothing yet (a card's “Allow for this session”)", "model-detail")
        box.pack_start(Gtk.Separator(), False, False, 4)
        on = notify_enabled()
        notify = Gtk.ModelButton(text="Notify me when the window is in the background",
                                 role=Gtk.ButtonRole.CHECK)
        notify.set_property("active", on)
        notify.set_tooltip_text("a finished or failed run, and a permission that waits (that one "
                                "even in Do Not Disturb); also in Settings > AI & models")
        notify.connect("clicked", lambda *_: self.set_notify(not on))
        box.pack_start(notify, False, False, 0)
        box.show_all()
        self.perm_pop.add(box)
        if current:
            GLib.idle_add(current[0].grab_focus)

    def forget_rules(self):
        self.perm_pop.popdown()
        n, self.perm_rules = len(self.perm_rules), []
        self.note(f"forgot {n} session rule{'s' if n != 1 else ''}: those ask again")

    def set_notify(self, on):
        write_front_state(notify=bool(on))
        self.note("notifications " + ("on: while the window is in the background" if on else "off"))
        GLib.idle_add(lambda: self.fill_perm_menu() and False)

    # ---- notifications --------------------------------------------------------

    def notify(self, event, summary, body="", key=None):
        """A desktop notification for `event`, if notify_decision says so
        (read here: focus now, the toggle, DND in the thread). A click on it
        brings this window to the front; it is taken down when the window
        gets the focus, or (a permission) when the card is answered."""
        focused = self.is_active()
        enabled = notify_enabled()
        if focused or not enabled or self.closing or self.render:
            return
        key = key or event

        def work():
            urgency = notify_decision(event, focused, dnd_on(), enabled)
            if urgency is None:
                return
            icon = {"permission": "dialog-password-symbolic", "failed": "dialog-error-symbolic"}.get(
                event, "emblem-default-symbolic")
            argv = ["notify-send", "-a", NOTIFY_APP, "-u", urgency, "-i", icon, "-p", "--wait",
                    "-A", f"default={self.ui['n_open']}", summary, body]
            try:
                proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        stdin=subprocess.DEVNULL, text=True)
            except OSError:
                return
            first = proc.stdout.readline().strip()
            GLib.idle_add(self._note_sent, key, proc, first)
            rest = proc.stdout.read().split()
            proc.wait()
            if "default" in rest:
                GLib.idle_add(self.focus_self)

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _note_sent(self, key, proc, nid):
        old = self.notes_out.pop(key, None)
        self.notes_out[key] = [proc, nid if nid.isdigit() else None]
        if old is not None:
            self._drop_note(old)
        if self.closing or (self.is_active() and key.startswith("perm:")) or \
                (key.startswith("perm:") and key[5:] not in self.cards):
            self.dismiss_note(key)       # answered or focused before it was up
        return False

    @staticmethod
    def _drop_note(entry):
        proc, nid = entry
        if nid:
            try:
                subprocess.Popen(["makoctl", "dismiss", "-n", nid], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except OSError:
                pass
        if proc.poll() is None:
            proc.terminate()

    def dismiss_note(self, key):
        entry = self.notes_out.pop(key, None)
        if entry is not None:
            self._drop_note(entry)

    def on_active(self, *_):
        if self.is_active():
            for key in list(self.notes_out):
                self.dismiss_note(key)

    def focus_self(self):
        """This window to the front (a click on its notification): its
        address from hyprctl by our pid, then the Lua dispatcher (this config
        has no `dispatch focuswindow`; launcher.py's focus_window)."""
        try:
            clients = json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True,
                                                text=True, timeout=2).stdout)
            addr = next((c["address"] for c in clients if c.get("pid") == os.getpid()), None)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            addr = None
        target = f"address:{addr}" if addr and re.fullmatch(r"0x[0-9a-fA-F]+", addr) else f"class:{APP_ID}"
        try:
            subprocess.Popen(["hyprctl", "dispatch", f"hl.dsp.focus({{ window = '{target}' }})"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.present()
        return False

    # ---- local models: loaded, unloading ----------------------------------------

    def refresh_loaded(self):
        """Which local models are loaded (lms ps, only when LM Studio is up),
        in a thread: when the model menu opens, after a local run, after an
        unload. Never per keystroke: the status reads the cached answer."""
        if self.loaded_busy or llm_models is None or self.closing:
            return
        self.loaded_busy = True

        def work():
            try:
                found = local_loaded()
            except Exception as exc:        # noqa: BLE001
                print(f"llm-chat: lms ps: {exc}", file=sys.stderr)
                found = None
            GLib.idle_add(self._loaded_now, found)

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _loaded_now(self, found):
        self.loaded_busy = False
        if self.closing:
            return False
        changed = found is not None and (self.loaded_at is None or set(found) != set(self.loaded))
        if found is not None:
            self.loaded, self.loaded_at = found, time.monotonic()
        self.update_model_button()
        self.update_status()
        if changed and self.model_pop.get_visible():
            self.fill_model_menu(refresh=False)     # only when it shows something new
        return False

    def local_state(self, model):
        """"loaded · unloads after 47 min idle" / "not loaded" for a local
        model, from the cached look (None before the first one)."""
        if model is None or not model.local or self.loaded_at is None:
            return None
        info = self.loaded.get(model.ident)
        if info is None:
            return "not loaded"
        ttl = info.get("ttl")
        if ttl is not None:
            ttl = max(0, ttl - int(time.monotonic() - self.loaded_at))
        return "loaded · " + ttl_text(ttl)

    def loaded_name(self, key):
        if llm_models is not None:
            for m in llm_models.local_models():
                if m.ident == key:
                    return m.name
        return key

    def request_unload(self, key):
        """The model menu's Unload (key: lms's model key, or "--all"). Not
        while a run is going: a note says so, with Stop and unload."""
        self.model_pop.popdown()
        name = "every local model" if key == "--all" else self.loaded_name(key)
        why = unload_refusal(self.busy(), name)
        if why:
            self.note(why)
            self.stop_unload_button(key, name)
            return False
        if self.unloading:
            self.note(f"still unloading {self.unloading}…")
            return False
        self.start_unload(key, name)
        return True

    def stop_unload_button(self, key, name):
        button = Gtk.Button(label=f"Stop and unload {name}")
        button.get_style_context().add_class("retry")
        button.set_halign(Gtk.Align.START)

        def clicked(_b):
            button.set_sensitive(False)
            if not self.busy():
                self.start_unload(key, name)
                return
            self.unload_after_stop = (key, name)
            self.stop()

        button.connect("clicked", clicked)
        self.add_row(button)

    def start_unload(self, key, name):
        self.unloading = name
        self.status_extra = f"unloading {name}…"
        self.update_status()

        def work():
            before = mem_snapshot()
            try:
                r = subprocess.run([sys.executable, LLM_GPU, "unload", key], capture_output=True,
                                   text=True, timeout=120)
                ok, out = r.returncode == 0, (r.stdout or r.stderr).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                ok, out = False, str(exc)
            after = mem_snapshot()
            for _ in range(10):         # the card's memory comes back as llama-server exits
                if not ok or before.get("vram") is None or after.get("vram") is None \
                        or after["vram"] < before["vram"] - 2**28:
                    break
                time.sleep(0.3)
                after = mem_snapshot()
            GLib.idle_add(self.unload_done, name, ok, out, freed_text(before, after))

        import threading
        threading.Thread(target=work, daemon=True).start()

    def unload_done(self, name, ok, out, freed):
        self.unloading = None
        if self.closing:
            return False
        if ok:
            self.status_extra = f"unloaded {name}" + (f" · {freed}" if freed else "")
            self.note(self.status_extra)
        else:
            self.status_extra = None
            self.error(f"could not unload {name}: {out.removeprefix('llm-gpu: ')}")
        self.refresh_loaded()
        self.update_status()
        return False

    # ---- models ---------------------------------------------------------------

    def prepare_local(self, prompt, choice, images=()):
        """LM Studio up and the model loaded (llm_models.ensure_local, in a
        thread), then the run. Messages sent meanwhile queue as during a
        run; Esc gives up (stop)."""
        self.prep_gen += 1
        gen = self.preparing = self.prep_gen
        self.stop_btn.show()
        self.send_btn.set_label(self.ui["wait"])
        self.set_state("thinking")
        self.prep_status(gen, f"waking LM Studio for {choice.name}…")

        def work():
            ok, why = llm_models.ensure_local(
                choice, lambda text: GLib.idle_add(self.prep_status, gen, text))
            GLib.idle_add(self.prepared, gen, prompt, ok, why, images)

        import threading
        threading.Thread(target=work, daemon=True).start()

    def prep_status(self, gen, text):
        if gen == self.preparing and not self.closing:
            self.bubble_override = text
            self.bubble.set_text(text)
            self.bubble.set_visible(True)
            self.status.set_text(text + "  ·  " + short_path(self.cwd))
            self.wake()
        return False

    def prepared(self, gen, prompt, ok, why, images=()):
        if gen != self.preparing or self.closing:
            return False
        self.preparing = None
        self.bubble_override = None
        if not ok:
            self.stop_btn.hide()
            self.send_btn.set_label(self.ui["send"])
            self.error(why)
            for *_, label in self.queue:
                label.get_style_context().add_class("dropped")
                label.set_tooltip_text("not sent: the local model could not be loaded")
            self.queue = []
            self.set_state("error")
            self.update_status()
            return False
        self.start_run(prompt, ready=True, images=images)
        return False

    def model_text(self):
        """The status line's model: the pick, what claude said it ran, or
        that the pick is for the next message."""
        if self.choice is None:
            return self.model or MODEL or "no model"
        name = self.choice.name + (" (local)" if self.choice.local else "")
        if backend(self.choice) == "native" and self.choice.ident in self.no_tools:
            name += " · no tools"
        if self.run_choice is not None and self.run_choice != self.choice:
            return f"{name} next  (ran {self.model or self.run_choice.name})"
        if self.model and self.model not in (self.choice.name, self.choice.ident):
            return f"{name} = {self.model}"
        return name

    def update_model_button(self):
        name = self.choice.name if self.choice is not None else (MODEL or "no model")
        if hasattr(self, "term_btn"):
            # Claude Code's own TUI: only for a Claude model, claude installed.
            self.term_btn.set_visible(backend(self.choice) == "claude" and find_claude() is not None)
        state = self.local_state(self.choice)
        # A local model: ● loaded now, ○ not (from the last look; none yet: no mark).
        mark = "" if state is None else ("  ●" if state.startswith("loaded") else "  ○")
        self.model_label.set_text(name + mark + "  ▾")
        self.model_btn.set_tooltip_text("Model for the next message (Ctrl+M)"
                                        + (f"\n{name}: {state}" if state else ""))
        self.update_placeholder()

    def update_placeholder(self):
        """"Ask gemma-4-e4b…": the input's hint names the model the next
        message goes to -- a local one by its short name (an LM Studio label
        can run to forty characters), a server's by its id, a Claude alias
        by its label, Claude Code's own default as plain "Claude"."""
        model = getattr(self, "choice", None)
        if model is None:
            shown = MODEL or "the model"
        elif model.kind == "claude" and model.name == "default":
            shown = "Claude"
        else:
            shown = model.label if model.kind in ("claude", "server") else model.name
        if hasattr(self, "placeholder"):
            self.placeholder.set_text(self.ui["placeholder"].format(
                model=shown, model_lower=shown.lower()))

    def on_model_toggled(self, button):
        if button.get_active():
            self.fill_model_menu()

    def fill_model_menu(self, refresh=True):
        if refresh:
            self.refresh_loaded()       # its answer fills the menu again
        old = self.model_pop.get_child()
        if old is not None:
            old.destroy()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_name("model-list")
        current = []            # the ticked entry: keyboard focus starts there
        models = llm_models.all_models()
        default = llm_models.chosen("default", models)

        def heading(text):
            label = Gtk.Label(label=text, xalign=0)
            label.get_style_context().add_class("model-heading")
            box.pack_start(label, False, False, 0)

        def entry(model):
            # A popover cannot grow past the window, so a long local label
            # ("GLM 4.7 Flash Uncen Hrt NEO CODE MAX Imat D AU") pushed the
            # list off its left edge in a narrow tile: cut, full one in the tooltip.
            label = model.label if len(model.label) <= 24 else model.label[:23] + "…"
            text = label if model.name == model.label.lower() else f"{model.name}  —  {label}"
            if default is not None and model == default:
                text += "   ★"
            if model.local and model.ident in self.loaded:
                text += "   ● loaded"
            button = Gtk.ModelButton(text=text, role=Gtk.ButtonRole.RADIO)
            button.set_property("active", self.choice is not None and model == self.choice)
            button.set_tooltip_text(" · ".join(t for t in (model.label, model.detail) if t) or None)
            button.connect("clicked", lambda *_: self.pick_model(model))
            box.pack_start(button, False, False, 0)
            if self.choice is not None and model == self.choice:
                current.append(button)

        def detail(text):
            label = Gtk.Label(label=text, xalign=0)
            label.get_style_context().add_class("model-detail")
            label.set_line_wrap(True)
            label.set_max_width_chars(48)
            box.pack_start(label, False, False, 0)

        locals_ = [m for m in models if m.local]
        heading("Local · LM Studio")
        if locals_:
            for m in locals_:
                entry(m)
        else:
            detail("none found (lms ls)")
        ep = engine.endpoint("server") if engine is not None else None
        if ep is not None:
            heading(f"Server · {ep['label']}")
            if self.server_list is None:
                detail("asking its /models…")
                self.refresh_server()
            elif not self.server_list:
                detail("no models" + (f": {one_line(self.server_error, 80)}"
                                      if getattr(self, "server_error", None) else ""))
            for ident in self.server_list or []:
                entry(llm_models.server_model(ident))
        claudes = [m for m in models if m.kind == "claude"]
        if claudes:
            heading("Claude · Claude Code")
            for m in claudes:
                entry(m)
        listed = models + [llm_models.server_model(i) for i in self.server_list or []]
        if self.choice is not None and self.choice not in listed:
            entry(self.choice)      # a full id given by --model
        if self.loaded:
            # Unloading gives the card's memory back; Esc only stops a reply.
            box.pack_start(Gtk.Separator(), False, False, 4)
            for key, info in self.loaded.items():
                name = self.loaded_name(key)
                unload = Gtk.ModelButton(text=self.ui["unload"].format(model=name))
                unload.set_tooltip_text(f"{key}: {ttl_text(info.get('ttl'))} -- llm-gpu.py unload")
                unload.connect("clicked", lambda *_, k=key: self.request_unload(k))
                box.pack_start(unload, False, False, 0)
            every = Gtk.ModelButton(text=self.ui["unload_all"])
            every.connect("clicked", lambda *_: self.request_unload("--all"))
            box.pack_start(every, False, False, 0)
        elif self.loaded_at is None and locals_:
            look = Gtk.Label(label="checking what is loaded…", xalign=0)
            look.get_style_context().add_class("model-detail")
            box.pack_start(look, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 4)
        name = self.choice.name if self.choice else "this"
        make = Gtk.ModelButton(text=("Keep Claude Code's own default"
                                     if name == "default" and backend(self.choice) == "claude"
                                     else f"Make {name} the default")
                               + ("   (already)" if self.choice == default else ""))
        make.set_sensitive(self.choice is not None and self.choice != default)
        make.connect("clicked", lambda *_: self.make_default())
        box.pack_start(make, False, False, 0)
        again = Gtk.ModelButton(text="Look for local models again")
        again.connect("clicked", lambda *_: self.refresh_models(say=True))
        box.pack_start(again, False, False, 0)
        find = Gtk.ModelButton(text="Find and download models…")
        find.set_tooltip_text("the launcher's ?get: GGUF models on Hugging Face, downloaded with lms get")
        find.connect("clicked", lambda *_: self.find_models())
        box.pack_start(find, False, False, 0)
        box.show_all()
        self.model_pop.add(box)
        if current:
            GLib.idle_add(current[0].grab_focus)

    def pick_model(self, model):
        # A radio ModelButton leaves its popover open (only a plain one
        # closes it): closed here, and the typing goes back to the box.
        self.model_pop.popdown()
        self.input.grab_focus()
        if model == self.choice:
            return
        before = self.choice
        self.choice = model
        self.update_model_button()
        if model.local:
            self.refresh_loaded()
        where = {"local": " (local, LM Studio)", "server": " (the OpenAI-compatible server)"}.get(model.kind, "")
        if not self.has_conversation():
            self.note(f"model: {model.name}{where}")
        elif backend(model) == self.session_kind:
            self.note(f"next message: {model.name}{where}, same conversation")
        else:
            self.fresh_said = True
            self.note(f"next message: {model.name} -- a new conversation ("
                      f"{'Claude cannot continue this one' if backend(model) == 'claude' else 'only Claude can continue a Claude Code session'})")
        self.update_status()
        return before

    def make_default(self):
        self.model_pop.popdown()
        try:
            llm_models.save_setting("default", self.choice.name)
        except OSError as exc:
            self.error(f"could not save {llm_models.SETTINGS}: {exc}")
            return
        extra = ("  ($LLM_CHAT_MODEL still overrides it here)" if MODEL else "")
        self.note(f"default model: {self.choice.name}, in {short_path(llm_models.SETTINGS)}{extra}")

    def find_models(self):
        """The launcher, "?get " typed: its model search and download. A
        new download shows up here the next time this list opens (the
        download refreshes the cache)."""
        self.model_pop.popdown()
        try:
            subprocess.Popen(["python3", os.path.join(HERE, "launcher.py"), "?get "],
                             start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.error(f"could not start the launcher: {exc}")

    def refresh_models(self, say=False):
        """lms ls again, in a thread (it may take seconds)."""
        def work():
            ok = llm_models.refresh()
            GLib.idle_add(self.models_refreshed, ok, say)
        import threading
        threading.Thread(target=work, daemon=True).start()

    def models_refreshed(self, ok, say):
        if self.closing:
            return False
        if say:
            n = len(llm_models.local_models())
            self.note(f"{n} local model{'s' if n != 1 else ''} in LM Studio" if ok
                      else "lms ls failed: is LM Studio installed?")
        if self.model_pop.get_visible():
            self.fill_model_menu(refresh=False)
        return False

    # ---- the mascot menu ------------------------------------------------------

    MASCOT_SIGNALS = (("talk", "the conversation"), ("weather", "the weather"),
                      ("time", "the time of day"), ("calendar", "the calendar and holidays"),
                      ("workhours", "work hours"), ("pc", "your PC: music, games, heat"),
                      ("chance", "chance: a random mood now and then"))

    def fill_mascot_menu(self, focus=None):
        old = self.mascot_pop.get_child()
        if old is not None:
            old.destroy()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_name("model-list")
        cur = mascot_mood.read_settings()
        on, rnd = cur["enabled"], cur["random_only"]
        buttons = {}

        def label(text, cls):
            lab = Gtk.Label(label=text, xalign=0)
            lab.get_style_context().add_class(cls)
            box.pack_start(lab, False, False, 0)

        def check(key, text, active, sensitive=True):
            button = Gtk.ModelButton(text=text, role=Gtk.ButtonRole.CHECK)
            button.set_property("active", active)
            button.set_sensitive(sensitive)
            button.connect("clicked", lambda *_: self.mascot_setting(key, not active))
            box.pack_start(button, False, False, 0)
            buttons[key] = button

        label("Mascot", "model-heading")
        if not getattr(self.mascot, "moods", False):
            label(f"the {self.theme} mascot draws no moods", "model-detail")
        elif not on:
            label("moods off: calm, no scenery", "model-detail")
        else:
            view = self.mood_view(self.state)
            if view is not None:
                scene = ", ".join(sorted(view.scene)) or "nothing around her"
                label(f"now: {view.mood}  ·  {scene}", "model-detail")
        check("enabled", "Moods", on)
        check("random_only", "Random moods only", rnd, on)
        box.pack_start(Gtk.Separator(), False, False, 4)
        label("She reacts to", "model-heading")
        for key, text in self.MASCOT_SIGNALS:
            check(key, text, cur["signals"][key] and (not rnd or key == "chance"),
                  on and (not rnd or key == "chance"))
        box.show_all()
        self.mascot_pop.add(box)
        if focus in buttons:
            GLib.idle_add(buttons[focus].grab_focus)

    def mascot_setting(self, key, value):
        """One switch flipped: saved, the surroundings read again with it,
        the menu rebuilt in place (a check ModelButton keeps it open)."""
        try:
            mascot_mood.save_settings(**{key: value})
        except (OSError, ValueError) as exc:
            self.error(f"could not save {short_path(mascot_mood.SETTINGS)}: {exc}")
            return
        if self.moods is not None:
            self.moods.signals = mascot_mood.load_settings()
            self.moods.enabled = mascot_mood.read_settings()["enabled"]
            self.refresh_mood()
        self.draw_frame()
        GLib.idle_add(lambda: self.fill_mascot_menu(focus=key) and False)

    # ---- recent sessions -------------------------------------------------------

    def fill_sessions_menu(self):
        old = self.sessions_pop.get_child()
        if old is not None:
            old.destroy()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_name("model-list")
        heading = Gtk.Label(label="Recent sessions", xalign=0)
        heading.get_style_context().add_class("model-heading")
        box.pack_start(heading, False, False, 0)
        found = recent_sessions()
        current = []
        for info in found:
            mine = info["id"] in (self.session_id, self.chat_id)
            text = (f"{one_line(info['title'], 54)}   ·   {ago(info['mtime'])}"
                    f"   ·   {one_line(short_path(info['cwd'] or '?'), 28)}")
            row = Gtk.Box(spacing=0)
            button = Gtk.ModelButton(text=text, role=Gtk.ButtonRole.RADIO)
            button.set_property("active", mine)
            button.set_tooltip_text(f"{info['title']}\n{info['cwd'] or '?'}\n"
                                    + (f"Claude Code session {info['id']}" if info["kind"] == "claude"
                                       else f"{info['id']} · {info.get('model') or '?'}"))
            button.connect("clicked", lambda _b, i=info: self.open_session(i))
            row.pack_start(button, True, True, 0)
            row.pack_start(self.delete_button(
                "Delete this session (its file, for good)",
                lambda i=info: self.delete_sessions([i])), False, False, 0)
            box.pack_start(row, False, False, 0)
            if mine:
                current.append(button)
        if not found:
            none = Gtk.Label(label="none yet", xalign=0)
            none.get_style_context().add_class("model-detail")
            box.pack_start(none, False, False, 0)
        else:
            box.pack_start(Gtk.Separator(), False, False, 0)
            row = Gtk.Box(spacing=0)
            row.pack_start(Gtk.Label(), True, True, 0)
            row.pack_start(self.delete_button(
                "Delete every saved conversation -- this window's, and Claude\n"
                "Code's in every folder with its prompt history when it is\n"
                "installed -- for good, no trash (memory and settings stay)",
                lambda: self.delete_sessions(None), label="🗑 delete all"), False, False, 0)
            box.pack_start(row, False, False, 0)
        box.show_all()
        self.sessions_pop.add(box)
        if current:
            GLib.idle_add(current[0].grab_focus)

    def delete_button(self, tip, action, label=None):
        """A small 🗑 that asks once: the first click turns it into
        "delete?", a second within 3 s does it."""
        button = Gtk.Button(label=label or "🗑")
        button.get_style_context().add_class("delete")
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(tip)
        armed = []

        def disarm():
            if armed:
                armed.clear()
                button.set_label(label or "🗑")
                button.get_style_context().remove_class("armed")
            return False

        def clicked(_b):
            if armed:
                armed.clear()
                action()
                return
            armed.append(True)
            button.set_label("delete? click again")
            button.get_style_context().add_class("armed")
            GLib.timeout_add(3000, disarm)
        button.connect("clicked", clicked)
        return button

    def delete_sessions(self, infos):
        """Saved sessions removed from disk at once -- the files, no trash,
        nothing written about it. None: every session in every folder,
        claude's prompt history and paste cache, and this window's ↑/↓
        history. A session still running here is left alone; the one open
        here, gone, leaves an empty window."""
        busy = (self.session_id if self.session_kind == "claude" else self.chat_id) if self.busy() else None
        if infos is None:
            gone = delete_all_sessions(keep=busy)
            self.history, self.hist_pos = [], None
        else:
            gone = [i["id"] for i in infos if i["id"] != busy and delete_session(i["path"])]
        if (self.session_id and self.session_id in gone) or (self.chat_id and self.chat_id in gone):
            self.clear()
            self.forget_conversation()
            self.cost = 0.0
            self.set_state("idle")
            self.update_status()
        if busy and (infos is None or any(i["id"] == busy for i in infos)):
            self.note("the running session was kept — Esc stops it first")
        self.fill_sessions_menu()

    def open_session(self, info):
        """Go on with a saved session: its conversation drawn again (the
        last REPLAY_EVENTS entries), the next message resumes it, in its
        own directory."""
        self.sessions_pop.popdown()
        self.input.grab_focus()
        if info["id"] in (self.session_id, self.chat_id):
            return
        if self.busy():
            self.note("still running — Esc stops it first")
            return
        if info["kind"] == "native":
            self.open_native(info)
            return
        self.clear()
        self.forget_conversation()
        self.session_id = info["id"]
        self.session_kind = "claude"
        self.cost, self.cost_prev = 0.0, None     # its total so far is not known here
        self.run_choice = None
        if info["cwd"] and os.path.isdir(info["cwd"]):
            self.cwd = info["cwd"]
            self.get_titlebar().set_subtitle(short_path(self.cwd))
        self.stick = True
        self.replay(info["path"])
        self.note(f"resuming session {self.session_id[:8]} · {one_line(info['title'], 60)}")
        self.set_state("idle")
        self.update_status()

    def replay(self, path):
        events = []
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"type":"user"' not in line and '"type":"assistant"' not in line:
                        continue        # most lines are bookkeeping: skip them unparsed
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("type") in ("user", "assistant") and not ev.get("isSidechain"):
                        events.append(ev)
        except OSError as exc:
            self.error(f"could not read {short_path(path)}: {exc}")
            return
        if len(events) > REPLAY_EVENTS:
            self.note(f"… {len(events) - REPLAY_EVENTS} earlier entries not shown")
            events = events[-REPLAY_EVENTS:]
        self.replaying = True
        try:
            for ev in events:
                msg = ev.get("message") or {}
                if ev["type"] == "assistant":
                    self.handle_assistant(msg, None)
                    continue
                if ev.get("isMeta"):
                    continue
                if ev.get("isCompactSummary"):
                    self.note("(earlier conversation compacted)")
                    continue
                said = user_words(msg.get("content"))
                if said:
                    self.user_bubble(said)
                self.handle_user(msg)
        except Exception as exc:     # an entry in a shape not seen before
            print(f"llm-chat: replay {path}: {exc!r}", file=sys.stderr)
        finally:
            self.replaying = False
        for chip in self.chips.values():
            if chip.running:
                chip.finish("", False)
        self.active_tools = {}

    # ---- search ----------------------------------------------------------------

    def open_search(self):
        self.search.set_search_mode(True)
        self.find_entry.grab_focus()
        self.find_all()

    def close_search(self):
        if self.match_label is not None:
            self.match_label.select_region(0, 0)
        self.matches, self.match_at, self.match_label = [], -1, None
        if self.search.get_search_mode():
            self.search.set_search_mode(False)
            self.input.grab_focus()

    def find_all(self):
        """Every visible transcript label holding the words (any case),
        top to bottom; the one nearest the bottom shown first."""
        query = self.find_entry.get_text().casefold()
        if self.match_label is not None:
            self.match_label.select_region(0, 0)
            self.match_label = None
        self.matches = []
        if query:
            for widget in walk(self.list):
                if isinstance(widget, Gtk.Label) and widget.get_selectable() and widget.get_mapped():
                    text = widget.get_text().casefold()
                    at = text.find(query)
                    while at >= 0:
                        self.matches.append((widget, at, at + len(query)))
                        at = text.find(query, at + 1)
        self.match_at = len(self.matches) - 1
        self.show_match()

    def on_find_key(self, _entry, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.matches:
            down = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
            self.match_at = (self.match_at + (1 if down else -1)) % len(self.matches)
            self.show_match()
            return True
        return False

    def show_match(self):
        if not self.matches:
            self.find_count.set_text("no match" if self.find_entry.get_text() else "")
            return
        label, start, end = self.matches[self.match_at]
        if self.match_label is not None and self.match_label is not label:
            self.match_label.select_region(0, 0)
        self.match_label = label
        label.select_region(start, end)
        self.find_count.set_text(f"{self.match_at + 1} / {len(self.matches)}")
        found = label.translate_coordinates(self.list, 0, 0)
        if found:
            adj = self.scroll.get_vadjustment()
            self.stick = False
            want = found[1] - adj.get_page_size() / 3
            adj.set_value(max(adj.get_lower(), min(want, adj.get_upper() - adj.get_page_size())))

    # ---- the rest ------------------------------------------------------------

    def new_session(self):
        if self.busy():
            self.note("still running — Esc stops it first")
            return
        self.clear()
        self.forget_conversation()
        self.cost = 0.0
        self.note("new session")
        self.set_state("idle")
        self.update_status()
        self.input.grab_focus()

    def clear(self):
        """An empty conversation: the transcript and what hangs off it."""
        self.close_search()
        self.chips, self.active_tools, self.streamed, self.live = {}, {}, {}, None
        self.thinking = None
        self.render_pending = set()
        self.ctx_used = None
        self.allow_once = []
        self.perm_rules = []        # "this session" ends with the conversation
        self.denied_ids = set()
        self.cards = {}
        for child in self.list.get_children():
            child.destroy()

    def open_terminal(self):
        """Ctrl+T: the Claude Code session in kitty, its own TUI -- for a
        Claude model with claude installed only; otherwise a note says so."""
        claude = find_claude()
        if claude is None or backend(self.choice) != "claude":
            self.note("Ctrl+T opens a Claude Code session in its own terminal UI: only for a Claude model"
                      + ("" if claude else " (and Claude Code is not installed)"))
            return
        argv = [claude, "--resume", self.session_id] if self.session_id else [claude]
        argv += self.spec()[0]
        if self.session_id and self.proc is not None:
            self.note("the run is still going: the terminal opens the session as it was saved")
        try:
            # A scope of its own (as the launcher starts this window): the
            # terminal outlives the window, and the window's cgroup.
            term = ["kitty", "--directory", self.cwd, "--title", "Claude Code ♡ " + short_path(self.cwd)] + argv
            if shutil.which("uwsm"):
                term = ["uwsm", "app", "--"] + term
            subprocess.Popen(term, cwd=self.cwd, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.error(f"could not open kitty: {exc}")

    def update_status(self):
        # Most telling first: a narrow window ellipsizes the tail (the
        # session id and the directory, both also in the header / tooltip),
        # never the cost in the middle.
        parts = [self.model_text()]
        if self.cards:
            first = next(iter(self.cards.values())).req
            parts.insert(0, f"🔒 waiting for you: {first['display']}"
                         + (f" (+{len(self.cards) - 1})" if len(self.cards) > 1 else ""))
        local = self.local_state(self.choice)
        if local:
            parts.append(local)
        if self.session_kind == "claude" and backend(self.choice) == "claude":
            parts.append(f"${self.cost:.4f}")       # Claude runs only: the rest cost nothing here
        if self.ctx_used:
            top = self.ctx_max or (200_000 if self.session_kind == "claude" else None)
            parts.append(f"ctx {kilo(self.ctx_used)}/{kilo(top)} ({100 * self.ctx_used // top}%)" if top
                         else f"ctx {kilo(self.ctx_used)}")
        if self.running() and self.run_started:
            parts.append(f"⏱ {int(time.monotonic() - self.run_started)} s")
        elif getattr(self, "last_run", None) is not None:
            parts.append(f"last {self.last_run:.1f} s")
        parts.append(f"perms {perm_label(self.perm)}"
                     + ("" if self.mode == perm_cli_mode(self.perm) else f" ({self.mode})"))
        if self.status_extra:
            parts.append(self.status_extra)
        sid = self.session_id if self.session_kind == "claude" else self.chat_id
        parts.append((f"session {sid[:8]}" if self.session_kind == "claude" else sid) if sid else "new session")
        parts.append(short_path(self.cwd))
        text = "  ·  ".join(parts)
        self.status.set_text(text)
        self.status.set_tooltip_text(text if sid is None else text + "\nsession " + sid)

    def on_delete(self, *_):
        self.quit()
        return True

    def quit(self):
        if self.closing:
            return
        self.closing = True
        for key in list(self.notes_out):
            if key.startswith("perm:"):
                self.dismiss_note(key)      # nobody left to answer it
            else:
                entry = self.notes_out.pop(key)
                if entry[0].poll() is None:
                    entry[0].terminate()    # the notification stays; its waiter goes
        self.kill_all()
        Gtk.main_quit()


PROJECTS = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"),
                        "projects")
SESSIONS_SHOWN = 15
REPLAY_EVENTS = 400         # a long session is drawn from its last this-many entries


def migrate_state():
    """The window's settings from before its rename (claude-front.json:
    corner, where, permissions, notify), copied once into llm-chat.json
    when that does not exist yet. The old file is left as it is."""
    if os.path.exists(FRONT_STATE) or not os.path.exists(OLD_STATE):
        return False
    try:
        with open(OLD_STATE) as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return False
        os.makedirs(os.path.dirname(FRONT_STATE), exist_ok=True)
        tmp = FRONT_STATE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({k: v for k, v in data.items() if k in ("corner", "where", "permissions", "notify")}, fh)
        os.replace(tmp, FRONT_STATE)
        return True
    except (OSError, ValueError):
        return False


def read_front_state():
    try:
        with open(FRONT_STATE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def notify_enabled():
    """The notifications toggle (llm-chat.json "notify", on unless set
    off), read each time: Settings > AI & models may change it meanwhile."""
    return read_front_state().get("notify", True) is not False


def write_front_state(**changes):
    data = read_front_state()
    data.update(changes)
    try:
        os.makedirs(os.path.dirname(FRONT_STATE), exist_ok=True)
        tmp = FRONT_STATE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, FRONT_STATE)
    except OSError:
        pass


_SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def delete_session(path):
    """One saved session gone. A native one: its file. A Claude Code one:
    <id>.jsonl, the <id>/ beside it (its subagents' and tool results'
    files) and its file-history and task folders. True if its file was
    there to remove."""
    if path.endswith(".json") and engine is not None:
        return engine.delete_session(path)
    sid = os.path.basename(path)[:-len(".jsonl")]
    if not _SESSION_ID.match(sid):
        return False
    try:
        os.remove(path)
        done = True
    except OSError:
        done = False
    home = os.path.dirname(PROJECTS)
    for folder in (path[:-len(".jsonl")], os.path.join(home, "file-history", sid),
                   os.path.join(home, "tasks", sid)):
        shutil.rmtree(folder, ignore_errors=True)
    return done


def delete_all_sessions(keep=None):
    """Every saved conversation: this window's own, and -- Claude Code
    installed -- every Claude Code session in every project folder (the
    memory/ folders stay), then claude's prompt history (history.jsonl) and
    paste cache. A project folder left empty goes too. keep: a session id
    spared. Returns the ids removed."""
    gone = []
    if engine is not None:
        for info in engine.list_sessions(limit=100000):
            if info["id"] != keep and engine.delete_session(info["path"]):
                gone.append(info["id"])
    if find_claude() is None:
        return gone
    try:
        projects = [p.path for p in os.scandir(PROJECTS) if p.is_dir()]
    except OSError:
        projects = []
    for proj in projects:
        try:
            entries = list(os.scandir(proj))
        except OSError:
            continue
        for entry in entries:
            sid = entry.name[:-len(".jsonl")] if entry.name.endswith(".jsonl") else entry.name
            if sid == keep or not _SESSION_ID.match(sid):
                continue
            if entry.name.endswith(".jsonl"):
                if delete_session(entry.path):
                    gone.append(sid)
            elif entry.is_dir() and not os.path.exists(entry.path + ".jsonl"):
                shutil.rmtree(entry.path, ignore_errors=True)    # a session's leftovers
        try:
            os.rmdir(proj)      # only if empty
        except OSError:
            pass
    home = os.path.dirname(PROJECTS)
    try:
        os.remove(os.path.join(home, "history.jsonl"))
    except OSError:
        pass
    shutil.rmtree(os.path.join(home, "paste-cache"), ignore_errors=True)
    return gone


def recent_sessions():
    """The newest saved conversations, any folder: [{"id", "path",
    "mtime", "cwd", "title", "kind"}], this window's own (kind "native")
    and, Claude Code installed, Claude Code's ("claude") together, newest
    first."""
    out = engine.list_sessions(SESSIONS_SHOWN) if engine is not None else []
    if find_claude() is not None:
        out += claude_sessions()
    out.sort(key=lambda i: i["mtime"], reverse=True)
    return out[:SESSIONS_SHOWN]


def claude_sessions():
    """Claude Code's newest saved sessions, any project: [{"id", "path",
    "mtime", "cwd", "title", "kind": "claude"}]. The title is claude's own
    (the last ai-title line, in the file's tail) or the first thing typed;
    a file with neither -- nothing was ever said in it -- is left out."""
    files = []
    try:
        for proj in os.scandir(PROJECTS):
            if proj.is_dir():
                for entry in os.scandir(proj.path):
                    if entry.name.endswith(".jsonl") and entry.is_file():
                        files.append((entry.stat().st_mtime, entry.path))
    except OSError:
        return []
    files.sort(reverse=True)
    out = []
    for mtime, path in files:
        info = session_info(path)
        if info is not None:
            info["mtime"] = mtime
            info["kind"] = "claude"
            out.append(info)
            if len(out) >= SESSIONS_SHOWN:
                break
    return out


def session_info(path):
    cwd = first = title = None
    try:
        with open(path, "rb") as fh:
            for n, raw in enumerate(fh):
                if n > 400 or (cwd and first):
                    break
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                cwd = cwd or ev.get("cwd")
                if not first and ev.get("type") == "user" and not ev.get("isMeta"):
                    first = user_words((ev.get("message") or {}).get("content"))
            fh.seek(max(0, os.path.getsize(path) - 65536))
            for raw in fh.read().split(b"\n"):
                if b'"ai-title"' in raw:
                    try:
                        title = json.loads(raw).get("aiTitle") or title
                    except ValueError:
                        pass
    except OSError:
        return None
    if not (title or first):
        return None
    return {"id": os.path.basename(path)[:-len(".jsonl")], "path": path,
            "cwd": cwd, "title": title or first}


def user_words(content):
    """What a person typed in a saved user entry: its text, an image as
    "🖼 image"; tool results and the harness's own tagged lines
    (<command-name>, <system-reminder>, ...) are not words."""
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, dict) and block.get("type") == "image":
                parts.append("🖼 image")
    else:
        return ""
    return "\n".join(p.strip() for p in parts if p.strip() and not p.lstrip().startswith("<"))


def ago(mtime):
    secs = max(0, time.time() - mtime)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if secs >= size:
            return f"{int(secs // size)} {unit}"
    return "now"


def current_theme():
    if desktop_theme is not None:
        try:
            return desktop_theme.current()
        except Exception as exc:
            print(f"llm-chat: theme.py current: {exc}", file=sys.stderr)
    return "cyberpunk"


def theme_conf(name):
    if desktop_theme is not None:
        try:
            return desktop_theme.load(name)
        except Exception as exc:
            print(f"llm-chat: theme.py load {name}: {exc}", file=sys.stderr)
    return {}


def ui_strings(name, conf=None):
    conf = theme_conf(name) if conf is None else conf
    ui = dict(UI_EN)
    ui.update(UI_THEME.get(name, {}))
    if conf.get("lang") == "ja":
        ui.update(UI_JA)
    ui["title"] = TITLES.get(name) or ("LLM chat · " + (conf.get("name") or name))
    return ui


def pick_start_model(name):
    """(Model or None, note or None) for the window's first model: --model,
    else $LLM_CHAT_MODEL, else llm.json's default -- which falls back to
    the first local model when it names a Claude one and Claude Code is
    not installed (the note says so)."""
    if llm_models is None:
        return None, (f"--model {name}: llm_models.py is missing, so the default is used"
                      if name else None)
    error = None
    if name:
        model = llm_models.resolve(name)
        if model is None and llm_models.stale():
            llm_models.refresh()        # a model downloaded since the last look
            model = llm_models.resolve(name)
        if model is not None:
            return model, None
        claude = ("fable, opus, sonnet, haiku, default, a full claude-… id, " if find_claude()
                  else "")
        error = (f"--model {name}: not a model I know -- {claude}server:<id>, or one of LM Studio's: "
                 + (", ".join(m.name for m in llm_models.local_models()) or "none found"))
    if MODEL:
        model = llm_models.resolve(MODEL, prefix=False)
        if model is not None:
            return model, error
        if find_claude():
            return llm_models.Model(MODEL, MODEL, "claude", MODEL, "$LLM_CHAT_MODEL"), error
        error = (error + "\n" if error else "") + f"$LLM_CHAT_MODEL={MODEL}: not a model I know"
    model, why = llm_models.chosen_note("default")
    if why:
        error = (error + "\n" if error else "") + why
    return model, error


def load_images(paths):
    """--image FILE...: attachments for the first message (an unreadable
    one is said and skipped)."""
    out, bad = [], []
    for path in paths or ():
        try:
            out.append(image_attachment(GdkPixbuf.Pixbuf.new_from_file(path), os.path.basename(path)))
        except (GLib.Error, ValueError) as exc:
            bad.append(f"--image {path}: {exc}")
    return out, bad


def render_main(out, cwd):
    """--render OUT.png: the window drawn off screen (never mapped, nothing
    run, no notification) with a short made-up exchange of the native
    engine -- a reasoning row, a reply, a read_file chip -- and two
    permission cards (a run_command and an edit_file with its diff), for a
    look at them in the current theme."""
    win = Front("", cwd, None, pick_start_model(None)[0], None, render=True)
    root, header = win.get_child(), win.get_titlebar()
    win.remove(root)
    win.set_titlebar(None)
    off = Gtk.OffscreenWindow()
    off.set_name("llm-chat")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.set_size_request(1000, 900)
    box.pack_start(header, False, False, 0)
    box.pack_start(root, True, True, 0)
    off.add(box)
    win.user_bubble("Make a file called made.txt here, then tidy the README's title.")
    think = win.thinking_row()
    think.text = "The user wants two things: a new file, and the README's heading fixed.\nRead it first."
    think.update()
    chip = win.add_row(ToolChip("read_file", kind="Read"))
    chip.set_input({"file_path": os.path.join(cwd, "README.md")})
    chip.finish("     1\t# my project\n     2\tnotes", False)
    reply = win.add_row(AssistantBlock())
    reply.text = "I'll create **made.txt** with `touch`, then fix the heading:"
    reply.set_text(reply.text)
    for req in ({"id": "render-cmd", "tool": "Bash", "display": "run_command",
                 "input": {"command": "touch made.txt", "description": "create an empty made.txt"}},
                {"id": "render-edit", "tool": "Edit", "display": "edit_file",
                 "input": {"file_path": os.path.join(cwd, "README.md"), "old_string": "# my project\nnotes",
                           "new_string": "# My Project\n\nNotes, tidied."}}):
        req.update(suggestions=[], blocked=None, reason=None, tool_use_id="call_render", agent=None, native=True)
        card = PermCard(req, win.cwd, win.ui, win.on_perm_answer)
        win.cards[req["id"]] = card
        win.add_row(card)
    win.perm_rules = [{"tool": "Bash", "content": "git status", "label": "run_command"}]
    win.update_status()
    off.show_all()
    win.stop_btn.hide()
    win.stage_wrap.set_visible(not win.corner_btn.get_active())
    win.update_model_button()

    def snap():
        pix = off.get_pixbuf()
        if pix:
            pix.savev(out, "png", [], [])
        win.closing = True
        Gtk.main_quit()
        return False
    GLib.timeout_add(1500, snap)
    Gtk.main()


def main():
    parser = argparse.ArgumentParser(prog="llm-chat.py",
                                     description="A chat window for language models, with a mascot.")
    parser.add_argument("prompt", nargs="*", help="sent at once if given")
    parser.add_argument("--cwd", default=os.path.expanduser("~"),
                        help="the working directory for the model's tools (default: $HOME)")
    parser.add_argument("--resume", metavar="SESSION_ID", help="continue this conversation")
    parser.add_argument("--model", metavar="NAME",
                        help="a local LM Studio model, server:ID, or a Claude model when Claude Code is "
                             "installed (default: llm.json's, or $LLM_CHAT_MODEL)")
    parser.add_argument("--image", metavar="FILE", action="append",
                        help="attach this picture to the first message (may be given again)")
    parser.add_argument("--render", metavar="OUT.png",
                        help="draw the window off screen with sample permission cards, save it, exit")
    args = parser.parse_args()
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    if not os.path.isdir(cwd):
        parser.error(f"--cwd {args.cwd}: not a directory")
    migrate_state()
    if args.render:
        GLib.set_prgname(APP_ID)
        render_main(os.path.abspath(args.render), cwd)
        return
    choice, model_error = pick_start_model(args.model)
    images, bad = load_images(args.image)
    if bad:
        model_error = "\n".join(([model_error] if model_error else []) + bad)

    GLib.set_prgname(APP_ID)
    GLib.set_application_name(ui_strings(current_theme())["title"])
    Gdk.set_program_class(APP_ID)
    win = Front(" ".join(args.prompt).strip(), cwd, args.resume, choice, model_error, images=images)

    def on_term(*_):
        win.quit()
        return False
    try:  # GLib's handlers, not signal.signal (see launcher.on_sigterm)
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        add = GLibUnix.signal_add
    except (ValueError, ImportError):
        add = GLib.unix_signal_add
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        add(GLib.PRIORITY_DEFAULT, sig, on_term)
    Gtk.main()


if __name__ == "__main__":
    main()
