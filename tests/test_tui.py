"""Smoke tests for Phase 5 TUI / umbrella CLI (no Docker pulls, no VM destroy)."""

from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from vmtools.cli import SIBLINGS, build_parser, cmd_status
from vmtools.menu import confirm, menu, prompt


class TestUmbrellaParser(unittest.TestCase):
    def test_subcommands(self):
        p = build_parser()
        for cmd in ("tui", "doctor", "list", "status", "help", "windowsvm", "linuxvm", "androidvm"):
            args = p.parse_args([cmd] if cmd != "windowsvm" else [cmd, "doctor"])
            self.assertEqual(args.command, cmd)
            self.assertTrue(callable(getattr(args, "handler", None)))

    def test_siblings(self):
        self.assertEqual([s[0] for s in SIBLINGS], ["windowsvm", "linuxvm", "androidvm"])


class TestMenuStdlib(unittest.TestCase):
    def test_quit_immediately(self):
        buf = io.StringIO()
        with mock.patch("builtins.input", side_effect=["q"]), redirect_stdout(buf):
            menu("Test", [("1", "Nope", lambda: None)])
        self.assertIn("Test", buf.getvalue())

    def test_prompt_default(self):
        with mock.patch("builtins.input", return_value=""):
            self.assertEqual(prompt("x", "fallback"), "fallback")

    def test_confirm_default_no(self):
        with mock.patch("builtins.input", return_value=""):
            self.assertFalse(confirm("sure?", default=False))


class TestStatus(unittest.TestCase):
    def test_status_runs(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_status(argparse.Namespace(json=False))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("windowsvm", out)
        self.assertIn("linuxvm", out)
        self.assertIn("androidvm", out)


class TestPerToolTuiFlag(unittest.TestCase):
    def test_windowsvm_has_tui(self):
        from windowsvm.cli import build_parser
        p = build_parser()
        args = p.parse_args(["tui"])
        self.assertEqual(args.command, "tui")

    def test_linuxvm_has_tui(self):
        from linuxvm.cli import build_parser
        p = build_parser()
        args = p.parse_args(["tui"])
        self.assertEqual(args.command, "tui")

    def test_androidvm_has_tui(self):
        from androidvm.cli import build_parser
        p = build_parser()
        args = p.parse_args(["tui"])
        self.assertEqual(args.command, "tui")


if __name__ == "__main__":
    unittest.main()
