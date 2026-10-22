"""contexts.py (project contexts), the automations it feeds (the "context"
action, the context-enter / -leave events), the launcher's project items and
the Settings page's helpers. Hermetic: contexts.json, the runtime state and
mako's fragment live in a scratch folder, Hyprland is a fake client list,
and nothing is launched -- spawn, run (makoctl, notify-send, pkill) and
hyprctl eval only record what they were asked."""
import json
import os
import tempfile
import unittest

import helpers

C = helpers.import_script("contexts.py")
A = helpers.import_script("automations.py")


def rec(kind, path="", key=None, note=None, app="App", cls="x"):
    launch = {"terminal": {"argv": ["kitty"], "cwd": path},
              "editor": {"desktop": "codium", "args": [path] if path else []},
              "files": {"desktop": "nautilus", "args": [path]}}.get(kind, {"desktop": "firefox"})
    r = {"kind": kind, "launch": launch, "key": key or f"{kind}|{cls}|{path}|", "app": app, "class": cls}
    if note:
        r["note"] = note
    return r


class Scratch(unittest.TestCase):
    """contexts.json, the state and the fragment in a scratch folder; the
    outside world stubbed on C (and on the sessions module it uses)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.repo = os.path.join(self.dir, "Projects", "Atlas")
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(os.path.join(self.dir, "Projects", "Notes", ".git"))
        self.saved = {k: getattr(C, k) for k in ("CONF", "STATE", "FRAGMENT", "PROJECTS", "run", "spawn", "live",
                                                "repos_module", "wait_windows", "automation_event")}
        self.saved_s = {k: getattr(C.sessions, k) for k in ("hypr_json", "hypr_eval", "STATE_DIR")}
        C.CONF = os.path.join(self.dir, "contexts.json")
        C.STATE = os.path.join(self.dir, "state.json")
        C.FRAGMENT = os.path.join(self.dir, "mako", "contexts")
        C.PROJECTS = os.path.join(self.dir, "Projects")
        C.sessions.STATE_DIR = os.path.join(self.dir, "sessions")
        self.ran, self.spawned, self.evals, self.events = [], [], [], []
        self.modes = ["default"]
        self.windows = []

        def run(*cmd, timeout=10):
            self.ran.append(list(cmd))

            class Out:
                returncode, stdout, stderr = 0, "", ""
            if cmd[:2] == ("makoctl", "mode"):
                if len(cmd) == 4:
                    (self.modes.append if cmd[2] == "-a" else self.modes.remove)(cmd[3])
                Out.stdout = " ".join(self.modes)
            if len(cmd) > 2 and cmd[1] == C.NOTIFY_SETTINGS:
                on = cmd[3] == "on"
                if on and "do-not-disturb" not in self.modes:
                    self.modes.append("do-not-disturb")
                if not on and "do-not-disturb" in self.modes:
                    self.modes.remove("do-not-disturb")
            return Out
        C.run = run
        C.spawn = lambda argv, cwd=None: self.spawned.append(argv) or True
        C.live = lambda clients=None, monitors=None: [(f"0x{i}", r) for i, r in enumerate(self.windows)]
        C.wait_windows = lambda before, count, **kw: True
        C.automation_event = lambda event, name: self.events.append((event, name))
        C.sessions.hypr_json = lambda what: [] if what in ("clients", "monitors") else None
        C.sessions.hypr_eval = lambda lua: self.evals.append(lua) or True

        class Repos:
            stopped = []

            @staticmethod
            def preview(path):
                return True, "http://localhost:8123/"

            @staticmethod
            def preview_stop(path):
                Repos.stopped.append(path)

            @staticmethod
            def site_dir(path):
                return path
        self.repos = Repos
        C.repos_module = lambda: Repos

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(C, k, v)
        for k, v in self.saved_s.items():
            setattr(C.sessions, k, v)

    def make(self, **kw):
        ctx = C.new("Atlas", self.repo)
        for key, value in kw.items():
            C.set_option("Atlas", key, value)
        return C.find(C.load()[0], "Atlas") if kw else ctx


class Definitions(Scratch):
    def test_no_file_is_no_contexts(self):
        # a new desktop: no contexts.json at all is not an error, just none yet
        if os.path.exists(C.CONF):
            os.remove(C.CONF)
        self.assertEqual(C.load(), ([], []))
        status = C.status()
        self.assertEqual((status["contexts"], status["problems"]), ([], []))
        self.assertEqual(status["repos"], ["~" + p[len(C.HOME):] if p.startswith(C.HOME) else p
                                           for p in C.free_repos([])])
        self.assertEqual(C.bar_json({})["text"], "")

    def test_tidy_fills_defaults_and_checks(self):
        ctx = C.tidy({"name": "Atlas", "repo": self.repo})
        self.assertEqual(ctx["focus"], "project")
        self.assertTrue(ctx["terminal"])
        self.assertEqual(ctx["allow"], [])
        for bad in ({"name": "leave", "repo": "/"}, {"name": "_x", "repo": "/"}, {"name": "a/b", "repo": "/"},
                    {"name": "R", "repo": "/", "focus": "loud"}, {"name": "R", "repo": "/", "terminal": "yes"},
                    {"name": "R", "repo": ""}, {"name": "R", "repo": "/", "allow": "kitty"}):
            with self.assertRaises(ValueError, msg=bad):
                C.tidy(bad)

    def test_load_skips_broken_and_doubles(self):
        with open(C.CONF, "w") as fh:
            json.dump({"contexts": [{"name": "Atlas", "repo": self.repo}, {"name": "atlas", "repo": "/"},
                                    {"name": "Bad", "repo": "/", "preview": "maybe"}]}, fh)
        good, bad = C.load()
        self.assertEqual([c["name"] for c in good], ["Atlas"])
        self.assertEqual(len(bad), 2)

    def test_new_set_delete(self):
        ctx = self.make()
        self.assertEqual(ctx["preview"], "start")     # it has a site (site_dir stub)
        with self.assertRaises(ValueError):
            C.new("atlas", self.repo)
        with self.assertRaises(ValueError):
            C.new("Nope", os.path.join(self.dir, "missing"))
        C.set_option("Atlas", "allow", "Automations, kitty")
        C.set_option("Atlas", "close_on_leave", "on")
        ctx = C.find(C.load()[0], "atlas")
        self.assertEqual(ctx["allow"], ["Automations", "kitty"])
        self.assertTrue(ctx["close_on_leave"])
        with self.assertRaises(ValueError):
            C.set_option("Atlas", "focus", "loud")
        with self.assertRaises(ValueError):
            C.set_option("Atlas", "colour", "red")
        C.delete("Atlas")
        self.assertEqual(C.load()[0], [])

    def test_free_repos(self):
        self.make()
        self.assertEqual([os.path.basename(p) for p in C.free_repos(C.load()[0])], ["Notes"])


class Planning(Scratch):
    def test_enter_plan(self):
        ctx = self.make()
        steps = C.plan_enter(ctx, {}, [], session_saved=True)
        self.assertEqual([s for s, _ in steps], ["terminal", "editor", "session", "preview", "focus", "announce"])
        # a terminal and an editor open in the repo already: not again; no session saved: no restore
        open_ = [rec("terminal", self.repo + "/src"), rec("editor", self.repo)]
        self.assertEqual([s for s, _ in C.plan_enter(ctx, {}, open_, False)], ["preview", "focus", "announce"])
        # a terminal elsewhere does not count
        self.assertIn("terminal", [s for s, _ in C.plan_enter(ctx, {}, [rec("terminal", self.repo + "-old")], False)])

    def test_enter_plan_switch_and_same(self):
        ctx = self.make(workspace="3")
        steps = C.plan_enter(ctx, {"name": "Notes"}, [], False)
        self.assertEqual(steps[:2], [("leave", "Notes"), ("workspace", "3")])
        same = C.plan_enter(ctx, {"name": "Atlas", "preview": self.repo}, [], False)
        self.assertEqual([s for s, _ in same], ["terminal", "editor"])

    def test_leave_plan(self):
        ctx = self.make()
        self.assertEqual(C.plan_leave(ctx, {"name": "Atlas"}), [("announce", "Atlas")])
        full = C.plan_leave(ctx, {"name": "Atlas", "preview": self.repo, "mode": C.MODE, "dnd": True}, save=True)
        self.assertEqual([s for s, _ in full], ["save", "preview-stop", "focus-off", "focus-off", "announce"])
        self.assertEqual(C.plan_leave(None, {"name": "Gone"}), [("announce", "Gone")])

    def test_project_windows(self):
        pairs = [("a", rec("terminal", self.repo)), ("b", rec("terminal", self.repo, note="was running make")),
                 ("c", rec("terminal", self.repo, key=f"term|kitty|{self.repo}|nvim")),
                 ("d", rec("editor", self.repo + "/index.html")), ("e", rec("browser")),
                 ("f", rec("files", "/tmp"))]
        self.assertEqual([a for a, _ in C.project_windows(pairs, self.repo)], ["a", "d"])


class Mako(unittest.TestCase):
    def test_fragment(self):
        ctx = C.tidy({"name": "My.App", "repo": "/", "allow": ['Thunder "bird"']})
        text = C.render_fragment(ctx)
        self.assertIn(f"[mode={C.MODE}]\ninvisible=1", text)
        self.assertIn(r'summary~="(My\\.App|my\\.app|MY\\.APP|My\\.app)"', text)
        self.assertIn('app-name="Thunder \\"bird\\""', text)
        self.assertIn(f"[mode={C.MODE} urgency=critical]\ninvisible=0", text)
        self.assertNotIn("[", C.render_fragment(None))

    def test_fragment_sections_balanced(self):
        text = C.render_fragment(C.tidy({"name": "Atlas", "repo": "/"}))
        for line in text.splitlines():
            if line.startswith("["):
                self.assertTrue(line.endswith("]"), line)
                self.assertTrue(line.startswith(f"[mode={C.MODE}"), line)


class Doing(Scratch):
    def test_enter_then_leave(self):
        self.make(workspace="3")
        code, _ = C.enter("atlas")
        self.assertEqual(code, 0)
        st = C.state()
        self.assertEqual((st["name"], st["preview"], st["mode"]), ("Atlas", self.repo, C.MODE))
        self.assertIn(C.MODE, self.modes)
        self.assertTrue(any('workspace = "3"' in e for e in self.evals))
        launched = [" ".join(a) for a in self.spawned]
        self.assertTrue(any("run terminal --dir " + self.repo in a for a in launched))
        self.assertTrue(any("run editor " + self.repo in a for a in launched))
        self.assertIn("summary~=", open(C.FRAGMENT).read())
        self.assertEqual(self.events, [("context-enter", "Atlas")])
        # again: nothing new is switched on, no event
        C.enter("Atlas")
        self.assertEqual(self.events, [("context-enter", "Atlas")])
        C.leave()
        self.assertEqual(C.state(), {})
        self.assertNotIn(C.MODE, self.modes)
        self.assertEqual(self.repos.stopped, [self.repo])
        self.assertNotIn("summary~=", open(C.FRAGMENT).read())
        self.assertEqual(self.events[-1], ("context-leave", "Atlas"))

    def test_dnd_left_alone_when_it_was_on(self):
        self.make(focus="dnd")
        self.modes.append("do-not-disturb")
        C.enter("Atlas")
        self.assertFalse(C.state().get("dnd"))
        C.leave()
        self.assertIn("do-not-disturb", self.modes)     # was on before: stays on
        self.modes.remove("do-not-disturb")
        C.enter("Atlas")
        self.assertTrue(C.state().get("dnd"))
        C.leave()
        self.assertNotIn("do-not-disturb", self.modes)

    def test_switching_leaves_the_other(self):
        self.make()
        C.new("Notes", os.path.join(self.dir, "Projects", "Notes"))
        C.enter("Atlas")
        C.enter("Notes")
        self.assertEqual(C.state()["name"], "Notes")
        self.assertIn(("context-leave", "Atlas"), self.events)
        self.assertEqual(self.modes.count(C.MODE), 1)

    def test_unknown(self):
        code, steps = C.enter("Nope")
        self.assertIn("no context", code)
        self.assertEqual(steps, [])

    def test_bar_and_picker(self):
        self.assertEqual(C.bar_json({})["text"], "")
        bar = C.bar_json({"name": "Atlas", "repo": "~/Projects/Atlas", "since": 0, "mode": C.MODE}, now=3900)
        self.assertIn("Atlas", bar["text"])
        self.assertIn("1 h 05 min", bar["tooltip"])
        self.make()
        contexts = C.load()[0]
        lines = C.pick_lines(contexts, {"name": "Atlas"})
        self.assertTrue(lines[0].startswith("leave"))
        self.assertEqual(C.picked(lines[0], contexts), ("leave", None))
        self.assertEqual(C.picked(lines[1], contexts), ("enter", "Atlas"))
        self.assertEqual(C.picked(lines[2], contexts), ("new", os.path.join(self.dir, "Projects", "Notes")))
        self.assertIsNone(C.picked("typed nonsense", contexts))


class Hardening(Scratch):
    """What the review found: a preview someone else started, picker names
    that look like the leave line, renaming the current one, a stale filter
    after a new login, two switches at once, a failed enter said aloud."""

    def test_preview_running_already_is_not_stopped(self):
        self.make()
        self.repos.previewing = staticmethod(lambda path: "http://localhost:8123/")
        try:
            C.enter("Atlas")
            self.assertNotIn("preview", C.state())
            C.leave()
            self.assertEqual(self.repos.stopped, [])
        finally:
            del self.repos.previewing

    def test_picker_names_like_leave_and_prefixes(self):
        for name in ("leave me", "a", "a  b"):
            C.new(name, self.repo)
        contexts = C.load()[0]
        lines = C.pick_lines(contexts, {})
        by_name = {C.picked(line, contexts) for line in lines if not line.startswith("+ ")}
        self.assertEqual(by_name, {("enter", "leave me"), ("enter", "a"), ("enter", "a  b")})
        self.assertEqual(C.picked(C.pick_lines(contexts, {"name": "a"})[0], contexts), ("leave", None))

    def test_rename_current_moves_state_and_layout(self):
        self.make()
        C.enter("Atlas")
        os.makedirs(C.sessions.STATE_DIR, exist_ok=True)
        with open(C.sessions.session_path("Atlas"), "w") as fh:
            json.dump({"windows": []}, fh)
        C.set_option("Atlas", "name", "Eye")
        self.assertEqual(C.state()["name"], "Eye")
        self.assertTrue(os.path.exists(C.sessions.session_path("Eye")))
        self.assertFalse(os.path.exists(C.sessions.session_path("Atlas")))

    def test_ensure_clears_a_stale_filter(self):
        ctx = self.make()
        C.write_fragment(C.render_fragment(ctx))
        self.assertEqual(C.command(["ensure"]), 0)
        with open(C.FRAGMENT) as fh:
            self.assertNotIn("summary~=", fh.read())

    def test_busy_waits_then_gives_up(self):
        saved = C.LOCK
        C.LOCK = os.path.join(self.dir, "lock")
        try:
            with C.busy():
                with self.assertRaises(TimeoutError):
                    with C.busy(timeout=0.3, sleep=lambda s: None):
                        pass
            with C.busy():      # free again
                pass
        finally:
            C.LOCK = saved

    def test_enter_failure_is_said(self):
        C.command(["enter", "Nope"])
        self.assertTrue(any(cmd[0] == "notify-send" and "Could not enter the project" in cmd for cmd in self.ran))


class Automations(unittest.TestCase):
    def test_rule_with_context(self):
        rule, problems = A.validate({"name": "Atlas focus", "when": {"event": "context-enter", "name": "Atlas"},
                                     "do": [{"action": "context", "value": "leave"}]})
        self.assertEqual(problems, [])
        self.assertTrue(A.matches(rule, "context-enter", {"name": "atlas"}))
        self.assertFalse(A.matches(rule, "context-enter", {"name": "Notes"}))
        self.assertFalse(A.matches(rule, "context-leave", {"name": "Atlas"}))
        anyone = A.validate({"name": "x", "when": {"event": "context-leave"}, "do": [{"action": "digest"}]})[0]
        self.assertTrue(A.matches(anyone, "context-leave", {"name": "Notes"}))
        argv, how = A.action_argv({"action": "context", "value": "leave"})
        self.assertEqual(argv[-2:], [os.path.join(A.HERE, "contexts.py"), "leave"])
        argv, _ = A.action_argv({"action": "context", "value": "Atlas"})
        self.assertEqual(argv[-2:], ["enter", "Atlas"])
        self.assertIn("project", A.describe(rule))

    def test_event_cli(self):
        sent, saved = [], A.poke
        A.poke = lambda msg: sent.append(msg) or True
        try:
            self.assertEqual(A.main(["event", "context-enter", "My", "App"]), 0)
            self.assertNotEqual(A.main(["event", "context-enter"]), 0)
        finally:
            A.poke = saved
        self.assertEqual(sent, ["event context-enter My App"])


class Launcher(Scratch):
    def test_items(self):
        L = helpers.import_script("launcher.py", "launcher")
        store = L.context_store
        saved = {k: getattr(store, k) for k in ("CONF", "STATE", "PROJECTS")}
        store.CONF, store.STATE, store.PROJECTS = C.CONF, C.STATE, C.PROJECTS
        try:
            self.make()
            self.assertEqual([i.name for i in L.project_items("project")], ["Project: Atlas"])
            self.assertEqual([i.name for i in L.project_items("ctx atl")], ["Project: Atlas"])
            self.assertEqual([i.name for i in L.project_items("proyecto notes")], ["New project: Notes"])
            self.assertEqual(L.project_items("atlas"), [])
            self.assertEqual(L.project_items("leave project"), [])
            C.write_state({"name": "Atlas", "repo": "~/Projects/Atlas", "since": 0})
            names = [i.name for i in L.project_items("project")]
            self.assertEqual(names[0], "Leave project Atlas")
            self.assertIn("you are in it", names[1])
            self.assertEqual([i.name for i in L.project_items("leave project")], ["Leave project Atlas"])
        finally:
            for k, v in saved.items():
                setattr(store, k, v)


class Page(unittest.TestCase):
    def test_helpers(self):
        from settings_pages import contexts as page
        c = {"repo": "~/Projects/Atlas", "session": True, "terminal": True, "editor": False, "preview": "start",
             "focus": "project", "layout": None, "exists": True}
        self.assertEqual(page.does_text(c), "its windows, terminal, preview  ·  only its notifications")
        self.assertIn("no layout saved yet", page.context_sub(c))
        self.assertIn("the folder is gone", page.context_sub(c | {"exists": False}))
        self.assertEqual(page.name_for("~/Projects/Signal-Lamp/"), "Signal-Lamp")
        self.assertEqual(page.name_for("/x/a+b"), "a-b")


if __name__ == "__main__":
    unittest.main()
