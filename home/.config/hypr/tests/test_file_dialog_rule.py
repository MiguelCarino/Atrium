"""lua/rules.lua's float-file-dialogs pattern (FILE_DIALOG): the dialogs'
own titles, whole, with at most a trailing ellipsis -- not any window whose
title merely starts with "Save As" or "Open File". Read out of the Lua
source and tried with Python's re, which agrees with Hyprland's RE2 on
everything this pattern uses."""
import os
import re
import unittest

import helpers

RULES = os.path.join(os.path.dirname(helpers.SCRIPTS), "lua", "rules.lua")


def pattern():
    with open(RULES) as handle:
        m = re.search(r'^local FILE_DIALOG = "((?:[^"\\]|\\.)*)"', handle.read(), re.M)
    assert m, "FILE_DIALOG not found in lua/rules.lua"
    return re.compile(m.group(1).replace("\\\\", "\\"))


class FileDialogRule(unittest.TestCase):
    def test_dialogs_float(self):
        rx = pattern()
        for title in ("Open File", "Open Files", "Save As", "Save As…", "Save File...", "Save Image",
                      "File Upload", "Choose File", "Choose Files", "Select a File",
                      "Enter name of file to save to…", "Open Folder"):
            self.assertRegex(title, rx)

    def test_documents_named_like_one_do_not(self):
        rx = pattern()
        for title in ("Save As notes.txt - gedit", "Open File formats explained - Mozilla Firefox",
                      "Save Asylum", "Save As… - LibreOffice Writer", "Open Files.odt"):
            self.assertIsNone(rx.search(title), title)

    def test_qt_dialogs_with_the_app_name_float(self):
        # Qt appends " — <application name>" to every title on Wayland.
        rx = pattern()
        for title in ("Open File — Okular", "Save As — Kate", "Open Folder — Dolphin"):
            self.assertRegex(title, rx)
        for title in ("Save As notes.txt — Kate", "Open File formats — Okular", "Save As — a — b"):
            self.assertIsNone(rx.search(title), title)

    def test_rule_also_checks_the_initial_title(self):
        with open(RULES) as handle:
            text = handle.read()
        self.assertIn("match  = { title = FILE_DIALOG, initial_title = FILE_DIALOG }", text)


if __name__ == "__main__":
    unittest.main()
