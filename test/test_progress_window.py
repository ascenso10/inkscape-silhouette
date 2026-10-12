#!/usr/bin/env python3
# coding=utf-8

import io
import os
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from sendto_silhouette import SendtoSilhouette
from silhouette.ProgressWindow import ProgressWindow
from inkex.tester import TestCase

try:
    import tkinter
except ImportError:
    tkinter = None

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_SVG = os.path.join(REPO_DIR, "examples", "testcut_square_triangle.svg")
INX_FILE = os.path.join(REPO_DIR, "sendto_silhouette.inx")


class SendtoProgressWindowTest(TestCase):
    """The progress window is opened and updated by Send to Silhouette"""

    def dry_run(self, *args):
        e = SendtoSilhouette()
        e.run(["--dry_run=true", "--preview=false",
               "--logfile=" + os.path.join(self.tempdir, "silhouette.log"),
               *args, EXAMPLE_SVG], output=io.BytesIO())

    @mock.patch("sendto_silhouette.ProgressWindow")
    def test_no_window_by_default(self, window):
        self.dry_run()
        window.assert_not_called()

    @mock.patch("sendto_silhouette.ProgressWindow")
    def test_window_shows_steps_and_closes(self, window):
        self.dry_run("--progress_window=true")
        window.assert_called_once_with()
        statuses = [c.args[0] for c in window.return_value.set_status.call_args_list]
        self.assertIn("Reading document...", statuses)
        self.assertIn("Optimizing cut paths...", statuses)
        self.assertIn("Connecting to cutter...", statuses)
        window.return_value.close.assert_called()


class ProgressWindowTest(TestCase):
    """The window never raises when Tk is unusable"""

    def assert_noop(self, window):
        self.assertIsNone(window.root)
        window.set_status("Reading document...")
        window.set_progress(50)
        window.close()
        window.close()

    @unittest.skipIf(tkinter is None, "tkinter is not installed")
    def test_tcl_error_makes_window_a_noop(self):
        with mock.patch("tkinter.Tk",
                        side_effect=tkinter.TclError("no display")) as tk:
            window = ProgressWindow()
            tk.assert_called_once_with()
            self.assert_noop(window)

    def test_missing_tkinter_makes_window_a_noop(self):
        with mock.patch.dict(sys.modules, {"tkinter": None}):
            self.assert_noop(ProgressWindow())


class InxTest(TestCase):
    """Inkscape runs pass the hidden progress_window param"""

    def test_hidden_param_outside_notebook(self):
        ns = "{http://www.inkscape.org/namespace/inkscape/extension}"
        root = ET.parse(INX_FILE).getroot()
        params = [p for p in root.findall(ns + "param")
                  if p.get("name") == "progress_window"]
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0].get("type"), "bool")
        self.assertEqual(params[0].get("gui-hidden"), "true")
        self.assertEqual(params[0].text, "true")
        notebook = root.find(ns + "param[@name='active-tab']")
        self.assertIsNone(notebook.find(".//" + ns + "param[@name='progress_window']"))
