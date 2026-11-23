"""
Route tests: the real Flask app, a temporary in-memory database, and FAKE
API answers (so no internet and no API key are needed).

Run from the project root:   python3 -m unittest -v
"""
import logging
import os
import unittest
from unittest import mock

import requests

# Must be set BEFORE importing app: use a throw-away in-memory database.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OPENTRIPMAP_API_KEY"] = "test-key"

import api_client                                   # noqa: E402
from app import app                                 # noqa: E402
from tests.test_api_client import (CITY_OK, PLACES, DETAIL, FORECAST,  # noqa: E402
                                   fake_response)

logging.disable(logging.CRITICAL)


def fake_api(url, params=None, timeout=None):
    """Answers like the real APIs, chosen by URL."""
    if url.endswith("/geoname"):
        if params["name"].lower() == "beirut":
            return fake_response(json_data=CITY_OK)
        return fake_response(json_data={"status": "NOT_FOUND"})
    if url.endswith("/radius"):
        return fake_response(json_data=PLACES)
    if url.endswith("/xid/W2"):
        return fake_response(json_data=DETAIL)
    if "/xid/" in url:
        return fake_response(status=404, json_data={})
    if "open-meteo" in url:
        return fake_response(json_data=FORECAST)
    raise AssertionError(f"unexpected URL {url}")


class RouteTests(unittest.TestCase):

    def setUp(self):
        api_client.clear_cache()
        self.client = app.test_client()
        patcher = mock.patch("api_client.requests.get", side_effect=fake_api)
        self.get_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def html(self, url):
        r = self.client.get(url)
        return r.status_code, r.get_data(as_text=True)

    # ---------- home & search ----------
    def test_home(self):
        code, html = self.html("/")
        self.assertEqual(code, 200)
        self.assertIn('name="city"', html)
        self.assertIn("Historic sites", html)               # category list

    def test_search_ok(self):
        code, html = self.html("/search?city=Beirut")
        self.assertEqual(code, 200)
        self.assertIn("Things to do in Beirut", html)
        self.assertIn("National Museum", html)
        self.assertIn("/place/W2", html)                    # card links to detail page
        self.assertIn("Today", html)                        # weather strip
        self.assertIn('class="chip active"', html)

    def test_search_validation_errors(self):
        for url in ["/search", "/search?city=", "/search?city=%3Cscript%3E",
                    "/search?city=Beirut&kind=weapons", "/search?city=Beirut&page=abc"]:
            code, html = self.html(url)
            self.assertEqual(code, 400, url)
            self.assertIn('class="error"', html, url)
        self.get_mock.assert_not_called()                   # bad input never reaches the API

    def test_unknown_city(self):
        code, html = self.html("/search?city=Atlantis")
        self.assertEqual(code, 404)
        self.assertIn("could not find a city", html)

    def test_api_down_during_search(self):
        self.get_mock.side_effect = requests.Timeout
        code, html = self.html("/search?city=Beirut")
        self.assertEqual(code, 503)
        self.assertIn("taking too long", html)

    def test_weather_failure_still_shows_places(self):
        def no_weather(url, params=None, timeout=None):
            if "open-meteo" in url:
                raise requests.ConnectionError
            return fake_api(url, params, timeout)
        self.get_mock.side_effect = no_weather
        code, html = self.html("/search?city=Beirut")
        self.assertEqual(code, 200)
        self.assertIn("National Museum", html)
        self.assertIn("Weather is unavailable", html)

    def test_pagination(self):
        many = [{"xid": f"N{i}", "name": f"Place {i}", "dist": i * 10, "rate": 1,
                 "kinds": "museums", "point": {"lon": 35.5, "lat": 33.9}} for i in range(30)]
        def big(url, params=None, timeout=None):
            if url.endswith("/radius"):
                return fake_response(json_data=many)
            return fake_api(url, params, timeout)
        self.get_mock.side_effect = big
        code, html = self.html("/search?city=Beirut&page=2")
        self.assertEqual(code, 200)
        self.assertIn("page 2 of 3", html)
        self.assertIn("Previous", html)
        self.assertIn("Next", html)

    def test_empty_category(self):
        def nothing(url, params=None, timeout=None):
            if url.endswith("/radius"):
                return fake_response(json_data=[])
            return fake_api(url, params, timeout)
        self.get_mock.side_effect = nothing
        code, html = self.html("/search?city=Beirut&kind=historic")
        self.assertEqual(code, 200)
        self.assertIn("No historic sites found", html)

    # ---------- place ----------
    def test_place_ok(self):
        code, html = self.html("/place/W2")
        self.assertEqual(code, 200)
        self.assertIn("The main museum.", html)
        self.assertIn("Damascus Street, Beirut, Lebanon", html)
        self.assertIn('rel="noopener noreferrer"', html)      # safe external links
        self.assertIn("/weather?lat=", html)

    def test_place_not_found(self):
        self.assertEqual(self.client.get("/place/N404").status_code, 404)
        self.assertEqual(self.client.get("/place/bad%20id").status_code, 404)

    def test_place_api_down(self):
        self.get_mock.side_effect = requests.ConnectionError
        code, html = self.html("/place/W2")
        self.assertEqual(code, 503)
        self.assertIn("unreachable", html)

    def test_api_text_is_escaped(self):
        """Names/descriptions from the API must never run as HTML (XSS)."""
        evil = dict(DETAIL, name="<script>alert(1)</script>",
                    wikipedia_extracts={"text": "<img src=x onerror=alert(1)>"})
        def xss(url, params=None, timeout=None):
            if "/xid/" in url:
                return fake_response(json_data=evil)
            return fake_api(url, params, timeout)
        self.get_mock.side_effect = xss
        code, html = self.html("/place/W2")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<img src=x", html)

    # ---------- weather ----------
    def test_weather_ok(self):
        code, html = self.html("/weather?lat=33.89&lon=35.5&name=Beirut")
        self.assertEqual(code, 200)
        self.assertIn("7-day weather · Beirut", html)
        self.assertIn("Clear sky", html)

    def test_weather_invalid(self):
        for url in ["/weather", "/weather?lat=100&lon=0", "/weather?lat=nan&lon=0"]:
            self.assertEqual(self.client.get(url).status_code, 400, url)

    # ---------- errors ----------
    def test_custom_404_page(self):
        code, html = self.html("/does-not-exist")
        self.assertEqual(code, 404)
        self.assertIn("Page not found", html)


if __name__ == "__main__":
    unittest.main()
