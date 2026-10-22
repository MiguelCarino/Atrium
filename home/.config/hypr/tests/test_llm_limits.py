"""llm-limits.py (LM Studio's RAM / CPU limits, lmstudio.service): the
settings checked, the drop-in written, a load the RAM limit ended told
apart (fake cgroup files), and a daemon running outside the unit found
(a fake /proc)."""
import json
import os
import tempfile
import unittest
from unittest import mock

import helpers

gpu = helpers.import_script("llm-gpu.py")
llm_models = gpu.llm_models
limits = llm_models._limits_module()
# Never the real unit: an ensure_local reached by any test does the old way.
limits.UNIT_FILE = os.path.join(helpers.SCRATCH, "systemd", "lmstudio.service")
limits.DROPIN = os.path.join(helpers.SCRATCH, "systemd", "lmstudio.service.d", "limits.conf")

MACH = {"ram_gb": 31.2, "cpus": 24}
UNIT_CG = "/user.slice/user-1000.slice/user@1000.service/app.slice/lmstudio.service"
SCOPE_CG = "/user.slice/user-1000.slice/user@1000.service/app.slice/app-graphical.slice/app-x-python3-1.scope"


class Validation(unittest.TestCase):
    def test_ram(self):
        self.assertEqual(limits.validate("ram_limit_gb", "16", MACH), 16)
        self.assertEqual(limits.validate("ram_limit_gb", "15.5", MACH), 15.5)
        self.assertEqual(limits.validate("ram_limit_gb", "12.3", MACH), 12.5)     # half-GB steps
        self.assertEqual(limits.validate("ram_limit_gb", "0", MACH), 0)
        self.assertEqual(limits.validate("ram_limit_gb", "off", MACH), 0)
        for bad in ("1", "64", "lots", "-4"):
            with self.assertRaises(ValueError):
                limits.validate("ram_limit_gb", bad, MACH)

    def test_cpu(self):
        self.assertEqual(limits.validate("cpu_limit_pct", "50", MACH), 50)
        self.assertEqual(limits.validate("cpu_limit_pct", "75%", MACH), 75)
        self.assertEqual(limits.validate("cpu_limit_pct", "0", MACH), 0)
        for bad in ("2", "101", "half"):
            with self.assertRaises(ValueError):
                limits.validate("cpu_limit_pct", bad, MACH)

    def test_low_priority_and_unknown(self):
        self.assertIs(limits.validate("llm_low_priority", "on", MACH), True)
        self.assertIs(limits.validate("llm_low_priority", False, MACH), False)
        with self.assertRaises(ValueError):
            limits.validate("llm_low_priority", "maybe", MACH)
        with self.assertRaises(ValueError):
            limits.validate("ram", "16", MACH)

    def test_defaults_fill_unset_and_broken(self):
        self.assertEqual(limits.defaults(MACH), {"ram_limit_gb": 16, "cpu_limit_pct": 50, "llm_low_priority": True})
        got = limits.limits({"ram_limit_gb": 0, "cpu_limit_pct": "nonsense"}, MACH)
        self.assertEqual(got, {"ram_limit_gb": 0, "cpu_limit_pct": 50, "llm_low_priority": True})

    def test_set_option_saves_through_llm_models(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "llm.json")
            with open(path, "w") as handle:
                json.dump({"default": "glm-4.7-flash", "context": 65536}, handle)
            with mock.patch.object(llm_models, "SETTINGS", path), \
                    mock.patch.object(limits, "machine", lambda: MACH), \
                    mock.patch.object(limits, "apply", lambda: []) as _apply:
                llm_models.set_option("ram_limit_gb", "20")
                llm_models.set_option("llm_low_priority", "off")
                with self.assertRaises(ValueError):
                    llm_models.set_option("cpu_limit_pct", "400")
            with open(path) as handle:
                data = json.load(handle)
        self.assertEqual(data, {"default": "glm-4.7-flash", "context": 65536, "ram_limit_gb": 20,
                                "llm_low_priority": False})


class DropIn(unittest.TestCase):
    def test_limits(self):
        text = limits.render_dropin({"ram_limit_gb": 16, "cpu_limit_pct": 50, "llm_low_priority": True}, 24)
        body = text.split("[Service]\n", 1)[1]
        self.assertEqual(body, "MemoryMax=16G\nMemorySwapMax=0\nCPUQuota=1200%\nCPUWeight=20\nIOWeight=20\n"
                               "Nice=10\n")
        self.assertTrue(text.startswith("# Written by"))

    def test_no_limits(self):
        body = limits.render_dropin({"ram_limit_gb": 0, "cpu_limit_pct": 0, "llm_low_priority": False},
                                    24).split("[Service]\n", 1)[1]
        self.assertEqual(body, "MemoryMax=infinity\nMemorySwapMax=0\nCPUQuota=\nCPUWeight=100\nIOWeight=100\n"
                               "Nice=0\n")

    def test_half_gb(self):
        props = dict(limits.properties({"ram_limit_gb": 15.5, "cpu_limit_pct": 25, "llm_low_priority": True}, 8))
        self.assertEqual((props["MemoryMax"], props["CPUQuota"]), ("15872M", "200%"))

    def test_written_once(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "lmstudio.service.d", "limits.conf")
            lim = limits.defaults(MACH)
            with mock.patch.object(limits, "DROPIN", path), \
                    mock.patch.object(limits, "_systemctl") as ctl:
                self.assertTrue(limits.write_dropin(lim, MACH))
                self.assertFalse(limits.write_dropin(lim, MACH))
            self.assertEqual(ctl.call_count, 1)      # daemon-reload only when it changed
            with open(path) as handle:
                self.assertIn("MemoryMax=16G", handle.read())


class OomReason(unittest.TestCase):
    def cgroup(self, d, kills):
        with open(os.path.join(d, "memory.events"), "w") as handle:
            handle.write(f"low 0\nhigh 0\nmax 12\noom 1\noom_kill {kills}\noom_group_kill 0\n")

    def test_kill_counted(self):
        with tempfile.TemporaryDirectory() as d:
            self.cgroup(d, 2)
            before = limits.oom_kills(d)
            self.cgroup(d, 3)
            after = limits.oom_kills(d)
        self.assertEqual((before, after), (2, 3))
        why = limits.oom_reason(before, after, "glm-4.7-flash", 16)
        self.assertIn("RAM limit of 16 GB", why)
        self.assertIn("Settings > AI & models", why)

    def test_no_kill_no_reason(self):
        self.assertEqual(limits.oom_reason(2, 2, "glm", 16), "")
        self.assertEqual(limits.oom_reason(None, 3, "glm", 16), "")
        self.assertIsNone(limits.oom_kills("/nonexistent/cgroup"))

    def test_ensure_local_says_so(self):
        """A failed `lms load` after the unit's oom_kill went up: the RAM
        limit is the reason given, not lms's own last line."""
        model = llm_models.Model("glm", "GLM", "local", "glm-key")
        kills = iter([0, 1])

        class Proc:
            stdout = mock.Mock(read1=mock.Mock(side_effect=[b"loading 40%", b"error: crashed", b""]))

            def wait(self, timeout=None):
                return 1

        def lms(*args, timeout=30):
            out = {("server", "status", "--json"): '{"running": true}', ("ps", "--json"): "[]"}
            return mock.Mock(returncode=0, stdout=out.get(args, ""), stderr="")

        answer = mock.Mock(read=lambda: b'{"data": []}')
        with mock.patch.object(llm_models, "_lms", lms), \
                mock.patch.object(llm_models, "_make_room", lambda *a: None), \
                mock.patch.object(llm_models.os, "access", lambda *a: True), \
                mock.patch("urllib.request.urlopen", lambda *a, **k: answer), \
                mock.patch.object(llm_models.subprocess, "Popen", lambda *a, **k: Proc()), \
                mock.patch.object(limits, "ensure_daemon", lambda status: ""), \
                mock.patch.object(limits, "oom_kills", lambda cg=None: next(kills)), \
                mock.patch.object(limits, "limits", lambda *a, **k: {"ram_limit_gb": 16}):
            ok, why = llm_models.ensure_local(model)
        self.assertFalse(ok)
        self.assertIn("hit LM Studio's RAM limit of 16 GB", why)


class Placement(unittest.TestCase):
    def fake_proc(self, d, rows):
        for pid, comm, group in rows:
            os.makedirs(os.path.join(d, str(pid)))
            with open(os.path.join(d, str(pid), "comm"), "w") as handle:
                handle.write(comm + "\n")
            with open(os.path.join(d, str(pid), "cgroup"), "w") as handle:
                handle.write(f"0::{group}\n")
        os.makedirs(os.path.join(d, "self"))

    def where(self, rows):
        with tempfile.TemporaryDirectory() as d:
            self.fake_proc(d, rows)
            procs = limits.lm_procs(d)
        return limits.placement(procs), procs

    def test_outside(self):
        where, procs = self.where([(10, "llmster", SCOPE_CG), (11, "llama-server", SCOPE_CG), (12, "bash", UNIT_CG)])
        self.assertEqual(where, "outside")
        self.assertEqual(sorted(p["pid"] for p in procs), [10, 11])

    def test_inside(self):
        where, _ = self.where([(10, "llmster", UNIT_CG), (11, "llama-server", UNIT_CG)])
        self.assertEqual(where, "inside")

    def test_none_and_the_app(self):
        self.assertEqual(self.where([(11, "llama-server", SCOPE_CG)])[0], "none")
        self.assertEqual(self.where([(10, "lm-studio", SCOPE_CG)])[0], "outside")

    def test_ensure_daemon_reports_outside_without_stopping_it(self):
        procs = [{"pid": 10, "comm": "llmster", "cgroup": SCOPE_CG}]
        said = []
        with mock.patch.object(limits, "unit_installed", lambda: True), \
                mock.patch.object(limits, "lm_procs", lambda proc=None: procs), \
                mock.patch.object(limits, "_systemctl") as ctl:
            note = limits.ensure_daemon(said.append)
        self.assertIn("outside the limits", note)
        self.assertEqual(said, [note])
        ctl.assert_not_called()

    def test_no_unit_is_the_old_way(self):
        with mock.patch.object(limits, "unit_installed", lambda: False), \
                mock.patch.object(limits, "_systemctl") as ctl:
            self.assertEqual(limits.ensure_daemon(), "")
        ctl.assert_not_called()


class Newest(unittest.TestCase):
    def test_newest_version(self):
        with tempfile.TemporaryDirectory() as d:
            for v in ("0.0.9-3", "0.0.20-1", "0.0.20-10"):
                os.makedirs(os.path.join(d, v))
                exe = os.path.join(d, v, "llmster")
                with open(exe, "w") as handle:
                    handle.write("")
                os.chmod(exe, 0o755)
            os.makedirs(os.path.join(d, "0.1.0"))       # no binary: half an update
            self.assertEqual(limits.newest_llmster(d), os.path.join(d, "0.0.20-10", "llmster"))


if __name__ == "__main__":
    unittest.main()
