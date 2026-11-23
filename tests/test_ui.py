"""
UI tests: maps get their data safely, static files are served, and the
templates contain no inline JavaScript (ready for a strict CSP, Week 11).

Run from the project root:   python3 -m unittest -v
"""
import html
import json
import logging
import os
import pathlib
import re
import unittest
from unittest import mock

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OPENTRIPMAP_API_KEY"] = "test-key"

import api_client                                   # noqa: E402
from app import app, limiter                        # noqa: E402
from tests.test_api_client import DETAIL, fake_response          # noqa: E402
from tests.test_routes import fake_api              # noqa: E402

logging.disable(logging.CRITICAL)
limiter.enabled = False   # many users from one test IP; limits are tested in test_security.py
TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"


def map_data(page_html):
    """Read back the JSON that map.js will receive from data-map='...'."""
    raw = re.search(r"data-map='([^']*)'", page_html).group(1)
    return json.loads(html.unescape(raw))


class UiTests(unittest.TestCase):

    def setUp(self):
        api_client.clear_cache()
        patcher = mock.patch("api_client.requests.get", side_effect=fake_api)
        self.get_mock = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app.test_client()

    def test_results_page_has_numbered_map(self):
        page = self.client.get("/search?city=Beirut").get_data(as_text=True)
        data = map_data(page)
        self.assertEqual([m["label"] for m in data["markers"]], ["1", "2"])
        self.assertEqual(data["markers"][0]["url"], "/place/W2")
        self.assertIn("vendor/leaflet/leaflet.js", page)
        self.assertIn("js/map.js", page)

    def test_place_page_has_map(self):
        data = map_data(self.client.get("/place/W2").get_data(as_text=True))
        self.assertEqual((data["markers"][0]["lat"], data["markers"][0]["lon"]), (33.87, 35.51))

    def test_map_data_cannot_break_out_of_the_attribute(self):
        """A place name with quotes and tags stays DATA (no XSS)."""
        evil_name = "Museum' onmouseover='alert(1)' x='<script>alert(2)</script>"
        def evil(url, params=None, timeout=None):
            if "/xid/" in url:
                return fake_response(json_data=dict(DETAIL, name=evil_name))
            return fake_api(url, params, timeout)
        self.get_mock.side_effect = evil
        page = self.client.get("/place/W2").get_data(as_text=True)
        self.assertNotIn("onmouseover='alert", page)         # quote did not end the attribute
        self.assertNotIn("<script>alert(2)", page)
        self.assertEqual(map_data(page)["markers"][0]["title"], evil_name)   # still the exact text

    def test_static_files(self):
        for path in ["/static/js/app.js", "/static/js/map.js", "/static/vendor/leaflet/leaflet.js",
                     "/static/vendor/leaflet/leaflet.css", "/static/favicon.svg", "/static/style.css"]:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            r.close()

    def test_no_inline_javascript_in_templates(self):
        """No on...="" handlers, javascript: links or inline <script> code."""
        for file in TEMPLATES.glob("*.html"):
            text = file.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\son[a-z]+\s*=", text), f"inline handler in {file.name}")
            self.assertNotIn("javascript:", text, file.name)
            for script in re.findall(r"<script[^>]*>", text):
                self.assertIn("src=", script, f"inline <script> in {file.name}")


if __name__ == "__main__":
    unittest.main()
