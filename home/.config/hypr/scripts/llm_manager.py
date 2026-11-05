#!/usr/bin/env python3
"""The LLM chat window's model manager: the local models on this PC, and
new ones found on Hugging Face and downloaded -- one window, two pages.

    On this PC     every model folder in ~/.lmstudio/models (llm_hub.on_disk):
                   its models (lms ls), size, quantization, whether it is
                   loaded now and which role it has (★ the chat's default).
                   Use (the chat's next message goes to it), Make default,
                   Unload (a loaded one), Delete (asks in the row first;
                   refused while it is loaded or downloading). A folder with
                   no model lms can load -- a download that never finished,
                   a lone vision projector -- says so and can be deleted.
    Download       a search of Hugging Face's GGUF repos (llm_hub.hf_search:
                   most downloaded first, LM Studio's own quantizations
                   raised), each with its default variant's size and how it
                   fits this machine; Download takes that variant, Variants
                   lists them all (llm_hub.variants) to pick another.

Downloads run as `llm_models.py get` processes of their own (spawn_get, in
a systemd scope), so closing this window -- or the chat -- does not stop
them; their progress comes back through their status files
(llm_models.downloads(), read once a second while one is going) and shows
over both pages with a Cancel button (llm_models.cancel: lms stops and
removes the partial file). The usual notification still says when one ends.

Everything that blocks (the search, the disk walk, lms ls, lms ps, unload,
delete) runs in a thread; the window only draws what came back.

    llm_manager.py            the window on its own (Settings, a keybind)
    llm_manager.py --download  ... on the Download page
    llm_manager.py --render OUT.png [--query WORDS] [--width PX]
                              drawn off screen and saved (a look at the
                              theme; the query is searched first)

From the chat (llm-chat.py: Ctrl+Shift+M, or "Manage models…" in the model
menu) it is a transient of the chat window, and Use / Make default /
Unload go through the chat (its notes, its model button, its refusal to
unload under a running reply).
"""

import os
import re
import subprocess
import sys
import threading
import urllib.parse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

import llm_hub  # noqa: E402  (no GTK)
import llm_models  # noqa: E402  (no GTK)

HERE = os.path.dirname(os.path.abspath(__file__))
CSS_FILE = os.path.join(HERE, "llm-chat.css")
LLM_GPU = os.path.join(HERE, "llm-gpu.py")
POLL_MS = 1000              # downloads' status files, while one is going
SEARCH_DELAY = 450          # ms after the last key before Hugging Face is asked


def gb(n):
    return llm_hub.gb(n) if n else "?"


def label(text="", classes=(), xalign=0.0, wrap=False, markup=False, ellipsize=False):
    widget = Gtk.Label(xalign=xalign)
    if markup:
        widget.set_markup(text)
    else:
        widget.set_text(text)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    for cls in classes:
        widget.get_style_context().add_class(cls)
    return widget


def button(text, callback, classes=(), tip=None):
    widget = Gtk.Button(label=text)
    for cls in classes:
        widget.get_style_context().add_class(cls)
    if tip:
        widget.set_tooltip_text(tip)
    widget.connect("clicked", lambda *_: callback())
    return widget


def reveal(box):
    """Show a box kept out of show_all (no_show_all) and everything in it."""
    for child in box.get_children():
        child.show_all()
    box.show()


def in_thread(work, done):
    """work() in a thread, done(result) on the GTK loop (an exception is the result)."""
    def run():
        try:
            out = work()
        except Exception as exc:  # noqa: BLE001 -- shown in the window, never raised there
            out = exc
        GLib.idle_add(lambda: done(out) and False)
    threading.Thread(target=run, daemon=True).start()


def loaded_keys():
    """{modelKey} loaded in LM Studio now; {} when it is down (never woken to
    ask). Blocking (lms ps): a thread."""
    try:
        gpu_mod = llm_models._gpu_module()
        if not gpu_mod.running():
            return set()
        return {r["modelKey"] for r in gpu_mod.lms_ps()}
    except Exception:  # noqa: BLE001 -- no answer is "none loaded"
        return set()


def short_name(repo):
    author, _, name = repo.partition("/")
    return (re.sub(r"[-_.]?gguf$", "", name, flags=re.I) or name), author


class ModelManager(Gtk.Window):
    def __init__(self, host=None, page="installed"):
        super().__init__(title="Models")
        self.host = host            # the chat's Front, or None on its own
        self.set_name("llm-models")
        self.set_default_size(720, 640)
        if host is not None:
            self.set_transient_for(host)
            self.set_destroy_with_parent(True)
        self.disk = None            # llm_hub.on_disk() as last read
        self.loaded = set()
        self.query = ""
        self.search_timer = 0
        self.poll_id = 0
        self.dl_rows = {}           # repo -> (row, bar, text, button)
        self.seen_states = {}       # repo -> state at the last poll: a change to "done" refreshes the disk
        self.open_variants = set()  # repos whose variant list is shown
        self.closed = False
        self._build(page)
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", self.on_destroy)
        self.refresh_disk()
        self.poll_downloads()

    # -- layout ----------------------------------------------------------------
    def _build(self, page):
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=self.stack)
        header.set_custom_title(switcher)
        self.free_label = label("", ("dim",))
        header.pack_end(self.free_label)
        self.set_titlebar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.dl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.dl_box.set_name("downloads")
        self.dl_box.set_no_show_all(True)
        outer.pack_start(self.dl_box, False, False, 0)
        outer.pack_start(self.stack, True, True, 0)
        self.add(outer)

        # On this PC
        page_disk = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.disk_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.disk_list.set_name("model-rows")
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.add(self.disk_list)
        page_disk.pack_start(scroll, True, True, 0)
        foot = Gtk.Box(spacing=8)
        foot.set_name("manager-foot")
        self.disk_note = label("", ("dim",), ellipsize=True)
        foot.pack_start(self.disk_note, True, True, 0)
        foot.pack_end(button("Look again", lambda: self.refresh_disk(rescan=True),
                             tip="lms ls again: a model added or removed by hand"), False, False, 0)
        page_disk.pack_end(foot, False, False, 0)
        self.stack.add_titled(page_disk, "installed", "On this PC")

        # Download
        page_dl = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        bar = Gtk.Box(spacing=8)
        bar.set_name("search-bar")
        self.search = Gtk.SearchEntry(placeholder_text="Search Hugging Face: qwen coder, gemma, llama 8b…")
        self.search.connect("search-changed", self.on_search_changed)
        self.search.connect("activate", lambda *_: self.start_search(now=True))
        bar.pack_start(self.search, True, True, 0)
        page_dl.pack_start(bar, False, False, 0)
        self.result_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.result_list.set_name("model-rows")
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.add(self.result_list)
        page_dl.pack_start(scroll, True, True, 0)
        self.stack.add_titled(page_dl, "download", "Download")
        self.show_hint("Type a model's name. GGUF models on Hugging Face, most downloaded first; "
                       "LM Studio downloads them into ~/.lmstudio/models. Only the words you search "
                       "and the repos you open are sent.")
        header.show_all()
        outer.show_all()        # not the window: present() maps it (and --render never does)
        self.stack.set_visible_child_name(page)
        if page == "download":
            self.search.grab_focus()

    def card(self, parent):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("model-card")
        parent.pack_start(box, False, False, 0)
        return box

    def clear(self, box):
        for child in box.get_children():
            child.destroy()

    def show_page(self, name):
        self.stack.set_visible_child_name(name)
        if name == "download":
            self.search.grab_focus()

    def on_key(self, _win, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        key = Gdk.keyval_to_lower(event.keyval)
        if event.keyval == Gdk.KEY_Escape:
            if self.search.has_focus() and self.search.get_text():
                self.search.set_text("")
            else:
                self.destroy()
            return True
        if ctrl and key in (Gdk.KEY_w, Gdk.KEY_q):
            self.destroy()
            return True
        if ctrl and key == Gdk.KEY_f:
            self.show_page("download")
            return True
        if ctrl and key == Gdk.KEY_1:
            self.show_page("installed")
            return True
        if ctrl and key == Gdk.KEY_2:
            self.show_page("download")
            return True
        return False

    def on_destroy(self, *_):
        self.closed = True
        for source in (self.poll_id, self.search_timer):
            if source:
                GLib.source_remove(source)
        self.poll_id = self.search_timer = 0
        if self.host is not None and hasattr(self.host, "manager_closed"):
            self.host.manager_closed()

    # -- On this PC --------------------------------------------------------------
    def refresh_disk(self, rescan=False):
        """The folders and what is loaded, in a thread; lms ls first when
        asked, or when the cache no longer matches the folders."""
        self.disk_note.set_text("looking…")

        def work():
            if rescan or llm_models.stale():
                llm_models.refresh()
            return llm_hub.on_disk(), loaded_keys(), llm_hub.disk_free()
        in_thread(work, self.disk_read)

    def disk_read(self, out):
        if self.closed:
            return
        if isinstance(out, Exception):
            self.disk_note.set_text(f"could not read the model folders: {out}")
            return
        self.disk, self.loaded, free = out
        self.free_label.set_text(f"{gb(free)} free" if free != float("inf") else "")
        self.draw_disk()
        if self.host is not None and hasattr(self.host, "models_changed"):
            self.host.models_changed()

    def draw_disk(self):
        self.clear(self.disk_list)
        disk = self.disk or []
        if not disk:
            self.show_text(self.disk_list, "No models yet. Find one on the Download page (Ctrl+2).")
        default = llm_models.chosen("default")
        roles = {}
        for role in llm_models.ROLES:
            model = llm_models.chosen(role)
            if model is not None and model.local:
                roles.setdefault(model.ident, []).append(role)
        current = getattr(self.host, "choice", None)
        for entry in disk:
            self.disk_card(entry, default, roles, current)
        total = sum(e["size"] for e in disk)
        models = sum(len(e["models"]) for e in disk)
        self.disk_note.set_text(f"{models} model{'s' if models != 1 else ''} in {len(disk)} folder"
                                f"{'s' if len(disk) != 1 else ''} · {gb(total)} · ~/.lmstudio/models")
        self.disk_list.show_all()

    def disk_card(self, entry, default, roles, current):
        box = self.card(self.disk_list)
        top = Gtk.Box(spacing=8)
        box.pack_start(top, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top.pack_start(text, True, True, 0)
        models = entry["models"]
        name, author = short_name(entry["folder"])
        if models:
            title = "  ·  ".join(m.name for m in models)
        else:
            title = name
        marks = []
        for m in models:
            if m.ident in self.loaded:
                marks.append("● loaded")
            if default is not None and m == default:
                marks.append("★ default")
            for role in roles.get(m.ident, []):
                if role != "default":
                    marks.append(f"{role} model")
            if current is not None and m == current:
                marks.append("in use here")
        head = Gtk.Box(spacing=8)
        head.pack_start(label(title, ("model-name",), ellipsize=True), False, True, 0)
        if marks:
            head.pack_start(label("   ".join(marks), ("model-mark",)), False, False, 0)
        text.pack_start(head, False, False, 0)
        if models:
            detail = "  ·  ".join(dict.fromkeys(m.detail for m in models if m.detail))
            text.pack_start(label(f"{models[0].label}  ·  {detail}" if len(models) == 1 else detail,
                                  ("dim",), ellipsize=True), False, False, 0)
        else:
            why = ("an unfinished download" if entry["partial"]
                   else "no model LM Studio can load here (a vision projector left alone?)")
            text.pack_start(label(f"{gb(entry['size'])}  ·  {why}", ("warn",), wrap=True), False, False, 0)
        where = label(f"{entry['folder']}  ·  {gb(entry['size'])} on disk", ("dim", "small"), ellipsize=True)
        where.set_tooltip_text("\n".join(entry["files"][:20]))
        text.pack_start(where, False, False, 0)

        actions = Gtk.Box(spacing=6)
        actions.set_halign(Gtk.Align.END)
        box.pack_start(actions, False, False, 0)
        for m in models:
            suffix = f" {m.name}" if len(models) > 1 else ""
            if self.host is not None:
                use = button("Use" + suffix, lambda m=m: self.use(m),
                             tip="the chat's next message goes to it")
                use.set_sensitive(current is None or m != current)
                actions.pack_start(use, False, False, 0)
            make = button("Make default" + suffix, lambda m=m: self.make_default(m),
                          tip="the chat's and the launcher's ? model (llm.json)")
            make.set_sensitive(default is None or m != default)
            actions.pack_start(make, False, False, 0)
            if m.ident in self.loaded:
                actions.pack_start(button("Unload" + suffix, lambda m=m: self.unload(m),
                                          tip="give its memory back to the card and the RAM"),
                                   False, False, 0)
        delete = button("Delete…", lambda: self.ask_delete(entry, actions), ("destructive",),
                        tip=f"remove {entry['folder']} from the disk")
        actions.pack_start(delete, False, False, 0)

    def ask_delete(self, entry, actions):
        """The row's buttons become the question: no dialog over the window."""
        self.clear(actions)
        busy = [m.name for m in entry["models"] if m.ident in self.loaded]
        if busy:
            actions.pack_start(label(f"{', '.join(busy)} is loaded: unload it first", ("warn",)),
                               False, False, 0)
            actions.pack_start(button("OK", self.draw_disk), False, False, 0)
            actions.show_all()
            return
        actions.pack_start(label(f"Delete {gb(entry['size'])} for good?", ("warn",)), False, False, 0)
        keep = button("Keep it", self.draw_disk)
        actions.pack_start(keep, False, False, 0)
        actions.pack_start(button("Delete", lambda: self.delete(entry, actions), ("destructive",)),
                           False, False, 0)
        actions.show_all()
        keep.grab_focus()

    def delete(self, entry, actions):
        self.clear(actions)
        actions.pack_start(label("deleting…", ("dim",)), False, False, 0)
        actions.show_all()
        folder, loaded = entry["folder"], set(self.loaded)

        def done(out):
            if isinstance(out, Exception):
                self.disk_note.set_text(f"not deleted: {out}")
                self.draw_disk()
                return
            self.say(f"deleted {folder}: {gb(out)} freed")
            self.refresh_disk()
        in_thread(lambda: llm_hub.remove(folder, loaded), done)

    def use(self, model):
        if self.host is not None:
            self.host.pick_model(model)
            self.draw_disk()

    def make_default(self, model):
        try:
            llm_models.save_setting("default", model.name)
        except OSError as exc:
            self.disk_note.set_text(f"could not save {llm_models.SETTINGS}: {exc}")
            return
        self.say(f"default model: {model.name}")
        self.draw_disk()

    def unload(self, model):
        if self.host is not None and hasattr(self.host, "request_unload"):
            self.host.request_unload(model.ident)       # the chat's notes, and its refusal mid-reply
            GLib.timeout_add(2500, lambda: self.refresh_disk() and False)
            return
        self.disk_note.set_text(f"unloading {model.name}…")

        def work():
            subprocess.run([sys.executable, LLM_GPU, "unload", model.ident], capture_output=True,
                           timeout=120)
        in_thread(work, lambda _out: self.refresh_disk())

    def say(self, text):
        """A line in the chat's conversation when there is one, else the footer."""
        if self.host is not None and hasattr(self.host, "note"):
            self.host.note(text)
        self.disk_note.set_text(text)

    # -- Download: the search ----------------------------------------------------
    def show_text(self, box, text, classes=("dim",)):
        box.pack_start(label(text, classes, wrap=True), False, False, 12)
        box.show_all()

    def show_hint(self, text, classes=("dim",)):
        self.clear(self.result_list)
        self.show_text(self.result_list, text, classes)

    def on_search_changed(self, entry):
        if self.search_timer:
            GLib.source_remove(self.search_timer)
        self.search_timer = GLib.timeout_add(SEARCH_DELAY, self.start_search)

    def start_search(self, now=False):
        self.search_timer = 0
        query = self.search.get_text().strip()
        if len(query) < 2:
            return False
        if query == self.query and not now:
            return False
        self.query = query
        cached = llm_hub.HF_CACHE.get(query)
        if cached is not None:
            self.draw_results(query)
            return False
        self.show_hint(f"Searching Hugging Face for “{query}”…")

        def work():
            llm_hub.hf_search(query, lambda: GLib.idle_add(self.draw_results, query))
        threading.Thread(target=work, daemon=True).start()
        return False

    def draw_results(self, query):
        if query != self.query or self.closed:
            return False
        entry = llm_hub.HF_CACHE.get(query)
        if entry is None:
            return False
        if entry["error"]:
            self.show_hint(f"Hugging Face did not answer: {entry['error']}", ("warn",))
            return False
        if not entry["rows"]:
            self.show_hint(f"No GGUF models for “{query}”.")
            return False
        self.clear(self.result_list)
        have = llm_models.installed_repos()
        models = llm_models.local_models()
        free = llm_hub.disk_free()
        for row in entry["rows"]:
            installed = (llm_models.model_for_repo(row["id"], models) or True) \
                if row["id"].lower() in have else None
            self.result_card(row, installed, free)
        self.result_list.show_all()
        return False

    def result_card(self, row, installed, free):
        repo, variant = row["id"], row["variant"]
        size = row["size"] or row["guess"]
        box = self.card(self.result_list)
        name, author = short_name(repo)
        head = Gtk.Box(spacing=8)
        head.pack_start(label(name, ("model-name",), ellipsize=True), False, True, 0)
        head.pack_start(label(author, ("dim",)), False, False, 0)
        marks = []
        if row["pick"]:
            marks.append("LM Studio's own")
        if installed is not None:
            marks.append(f"✓ on this PC as {installed.name}" if installed is not True else "✓ on this PC")
        if marks:
            head.pack_start(label("   ".join(marks), ("model-mark",)), False, False, 0)
        box.pack_start(head, False, False, 0)
        bits = []
        if variant:
            bits.append(f"{variant} {('' if row['size'] else '~') + gb(size)}" if size else variant)
            if size:
                bits.append(llm_hub.fit(size))
        else:
            bits.append("no known variant: LM Studio picks the file")
        if row["params"]:
            bits.append(f"{row['params'] / 1e9:.1f}".rstrip("0").rstrip(".") + "B"
                        + (f" ({row['moe']} active)" if row["moe"] else ""))
        bits.append(f"{llm_hub.count(row['downloads'])} downloads · {llm_hub.count(row['likes'])} likes")
        box.pack_start(label("  ·  ".join(bits), ("dim",), wrap=True), False, False, 0)
        low = bool(size) and free < size + llm_hub.DISK_SPARE
        if low:
            box.pack_start(label(f"only {gb(free)} free on disk", ("warn",)), False, False, 0)

        actions = Gtk.Box(spacing=6)
        actions.set_halign(Gtk.Align.END)
        box.pack_start(actions, False, False, 0)
        going = llm_models.downloading(repo)
        get = button("Downloading…" if going else (f"Download {variant}" if variant else "Download"),
                     lambda: self.download(repo, variant), ("suggested",))
        get.set_sensitive(not going)
        more = Gtk.ToggleButton(label="Variants ▾")
        page = button("Hugging Face ↗", lambda: self.open_url(f"https://huggingface.co/{repo}"),
                      tip="its page, in the browser")
        actions.pack_start(page, False, False, 0)
        actions.pack_start(more, False, False, 0)
        actions.pack_start(get, False, False, 0)
        sub = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sub.get_style_context().add_class("variants")
        sub.set_no_show_all(True)
        box.pack_start(sub, False, False, 0)
        more.connect("toggled", lambda b: self.toggle_variants(b, repo, sub))
        if repo in self.open_variants:
            more.set_active(True)

    def toggle_variants(self, toggle, repo, sub):
        if not toggle.get_active():
            self.open_variants.discard(repo)
            sub.hide()
            return
        self.open_variants.add(repo)
        self.clear(sub)
        sub.pack_start(label("asking for its files…", ("dim",)), False, False, 0)
        reveal(sub)

        def done(out):
            if self.closed or sub.get_parent() is None:     # the results drawn again meanwhile
                return
            self.clear(sub)
            if isinstance(out, Exception):
                sub.pack_start(label(f"Hugging Face did not answer: {out}", ("warn",), wrap=True),
                               False, False, 0)
            elif not out:
                sub.pack_start(label("no GGUF variant found in its files", ("dim",)), False, False, 0)
            free = llm_hub.disk_free()
            for v in out if isinstance(out, list) else []:
                line = Gtk.Box(spacing=8)
                text = f"{v['variant']}   {gb(v['size'])}   {v['fit']}" + ("   · the default" if v["best"] else "")
                if free < v["size"] + llm_hub.DISK_SPARE:
                    text += f"   · only {gb(free)} free"
                line.pack_start(label(text, ("variant",)), True, True, 0)
                line.pack_end(button("Download", lambda v=v: self.download(repo, v["variant"])),
                              False, False, 0)
                sub.pack_start(line, False, False, 0)
            reveal(sub)
        in_thread(lambda: llm_hub.variants(repo), done)

    def open_url(self, url):
        try:
            subprocess.Popen(["xdg-open", url], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    # -- downloads ------------------------------------------------------------------
    def download(self, repo, variant):
        if not llm_models.spawn_get(repo, variant or ""):
            self.say(f"{repo} is being downloaded already")
        self.poll_downloads()
        if self.query:
            GLib.timeout_add(300, lambda: self.draw_results(self.query) and False)

    def poll_downloads(self):
        """Draw the downloads' status files; again in POLL_MS while one is going."""
        self.poll_id = 0
        items = llm_models.downloads()
        going = False
        repos = set()
        for d in items:
            repo, state = d["repo"], d.get("state")
            repos.add(repo)
            going = going or state in ("running", "starting")
            if self.seen_states.get(repo) in ("running", "starting") and state == "done":
                self.refresh_disk()
                if self.query:
                    self.draw_results(self.query)
            self.seen_states[repo] = state
            self.draw_download(d)
        for repo in list(self.dl_rows):
            if repo not in repos:
                self.dl_rows.pop(repo)[0].destroy()
        self.dl_box.set_visible(bool(self.dl_rows))
        if going and not self.closed:
            self.poll_id = GLib.timeout_add(POLL_MS, self.poll_downloads)
        return False

    def draw_download(self, d):
        repo, state = d["repo"], d.get("state")
        if repo not in self.dl_rows:
            row = Gtk.Box(spacing=10)
            row.get_style_context().add_class("download")
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title = label("", ("model-name",), ellipsize=True)
            bar = Gtk.ProgressBar()
            text = label("", ("dim", "small"), ellipsize=True)
            text_box.pack_start(title, False, False, 0)
            text_box.pack_start(bar, False, False, 0)
            text_box.pack_start(text, False, False, 0)
            row.pack_start(text_box, True, True, 0)
            act = Gtk.Button()
            act.set_valign(Gtk.Align.CENTER)
            act.connect("clicked", lambda *_: self.download_action(repo))
            row.pack_end(act, False, False, 0)
            self.dl_box.pack_start(row, False, False, 0)
            row.show_all()
            row.title = title
            self.dl_rows[repo] = (row, bar, text, act)
        row, bar, text, act = self.dl_rows[repo]
        name, _author = short_name(repo)
        row.title.set_text(f"{name} {d.get('variant') or ''}".strip())
        bar.set_fraction(max(0.0, min(1.0, (d.get("pct") or 0) / 100)))
        if state in ("running", "starting"):
            if d.get("total"):
                line = f"{d.get('pct') or 0:.0f} %  ·  {d.get('done')} of {d.get('total')}  ·  " \
                       f"{d.get('speed')}  ·  {d.get('eta')} left"
            else:
                line = d.get("message") or "starting…"
            if d.get("message") == "cancelling…":
                line = "cancelling…"
            act.set_label("Cancel")
        else:
            line = {"done": f"downloaded{' as ' + d['model'] if d.get('model') else ''}"
                            + (" (it was already here)" if d.get("message") == "already downloaded" else ""),
                    "cancelled": "cancelled -- the partial file was removed"}.get(
                        state, f"failed: {d.get('message') or '?'}")
            act.set_label("✕")
            act.set_tooltip_text("take it off this list")
        text.set_text(line)
        for cls in ("done", "failed"):
            row.get_style_context().remove_class(cls)
        if state in ("done", "failed"):
            row.get_style_context().add_class(state)

    def download_action(self, repo):
        if llm_models.downloading(repo):
            if llm_models.cancel(repo):
                self.dl_rows[repo][2].set_text("cancelling…")
            return
        llm_models.forget_download(repo)
        self.seen_states.pop(repo, None)
        self.poll_downloads()


def load_css():
    """On its own: the chat's stylesheet (the theme's palette and the
    manager's rules are in it)."""
    provider = Gtk.CssProvider()
    try:
        provider.load_from_path(CSS_FILE)
    except GLib.Error as exc:
        print(f"llm_manager: {CSS_FILE}: {exc}", file=sys.stderr)
        return
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                             Gtk.STYLE_PROVIDER_PRIORITY_USER)


def render_main(out, page, query, width):
    """--render OUT.png: the window drawn off screen (never mapped), on
    `page`, after `query` was searched (Download), for a look in the
    current theme. Nothing is downloaded or deleted."""
    win = ModelManager(page=page)
    root, header = win.get_child(), win.get_titlebar()
    win.remove(root)
    win.set_titlebar(None)
    off = Gtk.OffscreenWindow()
    off.set_name("llm-models")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.set_size_request(width, 760)
    box.pack_start(header, False, False, 0)
    box.pack_start(root, True, True, 0)
    off.add(box)
    off.show_all()
    if query:
        win.search.set_text(query)
        win.start_search(now=True)

    def snap():
        pix = off.get_pixbuf()
        if pix:
            pix.savev(out, "png", [], [])
        win.closed = True
        Gtk.main_quit()
        return False
    GLib.timeout_add(9000 if query else 2500, snap)
    Gtk.main()


def main():
    args = sys.argv[1:]
    page = "download" if "--download" in args else "installed"
    GLib.set_prgname("llm-models")
    load_css()
    if "--render" in args:
        i = args.index("--render")
        query = args[args.index("--query") + 1] if "--query" in args else ""
        width = int(args[args.index("--width") + 1]) if "--width" in args else 720
        render_main(args[i + 1], "download" if query else page, query, width)
        return
    win = ModelManager(page=page)
    win.connect("destroy", Gtk.main_quit)
    win.present()
    Gtk.main()


if __name__ == "__main__":
    main()
