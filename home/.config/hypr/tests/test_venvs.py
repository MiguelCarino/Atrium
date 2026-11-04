"""venvs.py: which venvs a Python upgrade left stale, the login notification
(once per Python version), and a rebuild that puts the old venv back when the
new one fails. Hermetic: venvs are fake folders in the scratch dir and no
venv, pip or notify ever runs."""
import os
import shutil
import tempfile
import types
import unittest

import helpers

venvs = helpers.import_script("venvs.py", "venvs")


def fake_venv(root, name, version):
    venv = venvs.venv_dir(name, root)
    os.makedirs(os.path.join(venv, "bin"))
    open(os.path.join(venv, "bin", "python"), "w").close()
    with open(os.path.join(venv, "pyvenv.cfg"), "w") as f:
        f.write(f"home = /usr/bin\ninclude-system-site-packages = true\nversion = {version}\n")
    return venv


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.now = venvs.this_python()
        self.old = "3.1" if self.now != "3.1" else "3.0"


class State(Base):
    def test_missing_ok_stale(self):
        fake_venv(self.root, "tts", self.now + ".2")
        fake_venv(self.root, "voice", self.old + ".8")
        self.assertEqual(venvs.state("tts", self.root), ("ok", self.now))
        self.assertEqual(venvs.state("voice", self.root), ("stale", self.old))
        self.assertEqual(venvs.state("presence", self.root), ("missing", None))
        self.assertEqual(venvs.stale_names(self.root), ["voice"])

    def test_cuda_only_with_the_nvidia_driver(self):
        self.assertTrue(set(venvs.CUDA) <= set(venvs.packages("voice", nvidia=True)))
        self.assertFalse(set(venvs.CUDA) & set(venvs.packages("voice", nvidia=False)))
        self.assertFalse(set(venvs.CUDA) & set(venvs.packages("tts", nvidia=True)))


class Check(Base):
    def test_notifies_once_per_python(self):
        fake_venv(self.root, "tts", self.old + ".8")
        sent = []
        self.assertEqual(venvs.check(self.root, notify=lambda *a: sent.append(a)), ["tts"])
        self.assertEqual(venvs.check(self.root, notify=lambda *a: sent.append(a)), ["tts"])
        self.assertEqual(len(sent), 1)
        self.assertIn("rebuild --stale", sent[0][-1])
        os.remove(venvs.state_file())

    def test_quiet_when_nothing_is_stale(self):
        fake_venv(self.root, "tts", self.now + ".0")
        self.assertEqual(venvs.check(self.root, notify=lambda *a: self.fail("notified")), [])


class Rebuild(Base):
    def test_failure_puts_the_old_venv_back(self):
        venv = fake_venv(self.root, "tts", self.old + ".8")

        def run(cmd, check=False):
            if "venv" in cmd:      # the new venv gets made, then pip fails
                os.makedirs(os.path.join(venv, "bin"), exist_ok=True)
                return types.SimpleNamespace(returncode=0)
            return types.SimpleNamespace(returncode=1)
        self.assertFalse(venvs.rebuild("tts", self.root, run=run, log=lambda *a: None))
        self.assertEqual(venvs.built_for(venv), self.old)
        self.assertFalse(os.path.exists(venv + ".old"))

    def test_success_drops_the_old_venv(self):
        venv = fake_venv(self.root, "presence", self.old + ".8")
        calls = []

        def run(cmd, check=False):
            calls.append(cmd)
            if "venv" in cmd:
                fake_venv(self.root, "presence", self.now + ".0")
            return types.SimpleNamespace(returncode=0)
        self.assertTrue(venvs.rebuild("presence", self.root, run=run, log=lambda *a: None))
        self.assertEqual(venvs.state("presence", self.root)[0], "ok")
        self.assertFalse(os.path.exists(venv + ".old"))
        self.assertIn("--system-site-packages", calls[0])
        self.assertIn("opencv-python-headless", calls[1])


if __name__ == "__main__":
    unittest.main()
