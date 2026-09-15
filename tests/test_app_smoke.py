"""Smoke tests Streamlit AppTest das páginas principais."""

from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AppSmokeTests(unittest.TestCase):
    def test_pages_run_without_exception(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=40)
        at.run()
        self.assertFalse(at.exception, at.exception)
        for value in at.sidebar.radio[0].options:
            at.sidebar.radio[0].set_value(value)
            at.run()
            self.assertFalse(at.exception, (value, at.exception))
