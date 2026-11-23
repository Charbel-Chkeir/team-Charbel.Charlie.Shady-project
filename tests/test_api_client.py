"""
Automated tests for api_client.py -- NO internet and NO API key needed.

`requests.get` is replaced by a fake (unittest.mock) that returns prepared
answers, so we can also simulate timeouts, rate limits and broken JSON.

Run from the project root:
    python3 -m unittest -v
"""
import logging
import os
import unittest
from unittest import mock

import requests

import api_client
from api_client import ApiError

# The client logs a warning for every simulated failure; hide them during tests.
logging.disable(logging.CRITICAL)


def fake_response(status=200, json_data=None, bad_json=False):
    r = mock.Mock()
    r.status_code = status
    r.text = str(json_data)
    if bad_json:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = json_data
    return r


CITY_OK = {"name": "Beirut", "country": "LB", "lat": 33.89, "lon": 35.50,
           "population": 1916100, "timezone": "Asia/Beirut", "status": "OK"}

PLACES = [  # shape of /places/radius?format=json
    {"xid": "N1", "name": "Small statue", "dist": 900, "rate": 1,
     "kinds": "monuments,interesting_places", "point": {"lon": 35.5, "lat": 33.9}},
    {"xid": "W2", "name": "National Museum", "dist": 2500, "rate": "3h",
     "kinds": "museums,cultural,other_museums,interesting_places", "point": {"lon": 35.51, "lat": 33.87}},
    {"xid": "Q3", "name": "national museum", "dist": 2600, "rate": 3,   # duplicate name
     "kinds": "museums", "point": {"lon": 35.51, "lat": 33.87}},
    {"xid": "N4", "name": "", "dist": 100, "rate": 2,                    # unnamed
     "kinds": "other", "point": {"lon": 35.5, "lat": 33.9}},
]

DETAIL = {  # shape of /places/xid/{xid}
    "xid": "W2", "name": "National Museum", "kinds": "museums,cultural,interesting_places",
    "address": {"road": "Damascus Street", "city": "Beirut", "country": "Lebanon"},
    "preview": {"source": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Museum.jpg/400px-Museum.jpg",
                "width": 400, "height": 300},
    "wikipedia_extracts": {"title": "en:National Museum", "text": "The main museum."},
    "wikipedia": "https://en.wikipedia.org/wiki/National_Museum_of_Beirut",
    "point": {"lon": 35.51, "lat": 33.87},
}

FORECAST = {"daily": {
    "time": ["2026-11-23", "2026-11-24"],
    "temperature_2m_max": [22.6, 19.2], "temperature_2m_min": [15.4, 13.0],
    "precipitation_probability_max": [10, 80], "weather_code": [0, 63]}}


@mock.patch.dict(os.environ, {"OPENTRIPMAP_API_KEY": "test-key"})
class ApiClientTests(unittest.TestCase):

    def setUp(self):
        api_client.clear_cache()          # every test starts with an empty cache

    # ---------- find_city ----------
    @mock.patch("api_client.requests.get")
    def test_find_city_ok(self, get):
        get.return_value = fake_response(json_data=CITY_OK)
        city = api_client.find_city("Beirut")
        self.assertEqual(city, {"name": "Beirut", "country": "LB", "lat": 33.89, "lon": 35.50})
        # the key is sent, and a timeout is always used
        self.assertEqual(get.call_args.kwargs["params"]["apikey"], "test-key")
        self.assertEqual(get.call_args.kwargs["timeout"], api_client.TIMEOUT)

    @mock.patch("api_client.requests.get")
    def test_find_city_not_found(self, get):
        get.return_value = fake_response(json_data={"status": "NOT_FOUND"})
        self.assertIsNone(api_client.find_city("Xyzzzz"))

    @mock.patch("api_client.requests.get")
    def test_cache_avoids_second_request(self, get):
        get.return_value = fake_response(json_data=CITY_OK)
        api_client.find_city("Beirut")
        api_client.find_city("  beirut ")          # same city, different spacing/case
        self.assertEqual(get.call_count, 1)

    # ---------- failures -> ApiError ----------
    @mock.patch("api_client.requests.get")
    def test_missing_key(self, get):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ApiError):
                api_client.find_city("Beirut")
        get.assert_not_called()

    @mock.patch("api_client.requests.get", side_effect=requests.Timeout)
    def test_timeout(self, get):
        with self.assertRaisesRegex(ApiError, "too long"):
            api_client.find_city("Beirut")

    @mock.patch("api_client.requests.get", side_effect=requests.ConnectionError)
    def test_unreachable(self, get):
        with self.assertRaisesRegex(ApiError, "unreachable"):
            api_client.find_city("Beirut")

    @mock.patch("api_client.requests.get")
    def test_http_errors(self, get):
        for status, words in [(429, "too many"), (401, "configuration"),
                              (403, "configuration"), (500, "error")]:
            api_client.clear_cache()
            get.return_value = fake_response(status=status, json_data={})
            with self.assertRaisesRegex(ApiError, words):
                api_client.find_city("Beirut")

    @mock.patch("api_client.requests.get")
    def test_bad_json(self, get):
        get.return_value = fake_response(bad_json=True)
        with self.assertRaisesRegex(ApiError, "unreadable"):
            api_client.find_city("Beirut")

    @mock.patch("api_client.requests.get")
    def test_errors_are_not_cached(self, get):
        get.side_effect = [requests.Timeout, fake_response(json_data=CITY_OK)]
        with self.assertRaises(ApiError):
            api_client.find_city("Beirut")
        self.assertEqual(api_client.find_city("Beirut")["name"], "Beirut")

    # ---------- list_places ----------
    @mock.patch("api_client.requests.get")
    def test_places_cleaned_and_sorted(self, get):
        get.return_value = fake_response(json_data=PLACES)
        result = api_client.list_places(33.89, 35.50, "all", 1)
        names = [p["name"] for p in result["places"]]
        self.assertEqual(names, ["National Museum", "Small statue"])  # popular first
        self.assertEqual(result["total"], 2)                           # dup + unnamed removed
        museum = result["places"][0]
        self.assertEqual(museum["rate"], 3)                            # "3h" -> 3
        self.assertEqual(museum["dist_km"], 2.5)
        self.assertEqual(museum["kinds"], ["Museums", "Cultural"])
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["limit"], api_client.MAX_PLACES)
        self.assertEqual(params["kinds"], "interesting_places")

    @mock.patch("api_client.requests.get")
    def test_pagination(self, get):
        many = [{"xid": f"N{i}", "name": f"Place {i}", "dist": i * 100, "rate": 1,
                 "kinds": "museums", "point": {"lon": 35.5, "lat": 33.9}} for i in range(30)]
        get.return_value = fake_response(json_data=many)
        p1 = api_client.list_places(33.9, 35.5, "cultural", 1)
        p3 = api_client.list_places(33.9, 35.5, "cultural", 3)
        p99 = api_client.list_places(33.9, 35.5, "cultural", 99)
        self.assertEqual((len(p1["places"]), p1["pages"]), (12, 3))
        self.assertEqual(len(p3["places"]), 6)
        self.assertEqual(p99["page"], 3)                   # page clamped to the last one
        self.assertEqual(get.call_count, 1)                # pages come from the cache

    @mock.patch("api_client.requests.get")
    def test_no_places(self, get):
        get.return_value = fake_response(json_data=[])
        result = api_client.list_places(0.0, 0.0, "all", 1)
        self.assertEqual((result["places"], result["total"], result["pages"]), ([], 0, 1))

    def test_unknown_category(self):
        with self.assertRaises(ValueError):
            api_client.list_places(33.9, 35.5, "weapons", 1)

    # ---------- get_place ----------
    @mock.patch("api_client.requests.get")
    def test_place_details(self, get):
        get.return_value = fake_response(json_data=DETAIL)
        p = api_client.get_place("W2")
        self.assertEqual(p["address"], "Damascus Street, Beirut, Lebanon")
        self.assertEqual(p["description"], "The main museum.")
        # 400px is not a Wikimedia standard width -> rewritten to 500px
        self.assertEqual(p["image"], "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Museum.jpg/500px-Museum.jpg")
        self.assertEqual((p["lat"], p["lon"]), (33.87, 35.51))

    @mock.patch("api_client.requests.get")
    def test_place_with_missing_fields(self, get):
        get.return_value = fake_response(json_data={
            "xid": "N9", "name": "", "point": {"lon": 1, "lat": 2},
            "preview": {"source": "http://insecure/x.jpg"}})
        p = api_client.get_place("N9")
        self.assertEqual(p["name"], "Unnamed place")
        self.assertEqual((p["description"], p["address"]), ("", ""))
        self.assertIsNone(p["image"])                     # http image dropped

    @mock.patch("api_client.requests.get")
    def test_place_not_found(self, get):
        get.return_value = fake_response(status=404, json_data={"error": "not found"})
        self.assertIsNone(api_client.get_place("N000"))

    @mock.patch("api_client.requests.get")
    def test_bad_xid_never_calls_api(self, get):
        for bad in ["../geoname", "N1?x=1", "", "a" * 51]:
            self.assertIsNone(api_client.get_place(bad))
        get.assert_not_called()

    # ---------- get_forecast ----------
    @mock.patch("api_client.requests.get")
    def test_forecast(self, get):
        get.return_value = fake_response(json_data=FORECAST)
        days = api_client.get_forecast(33.89, 35.50)
        self.assertEqual(len(days), 2)
        self.assertEqual((days[0]["t_max"], days[0]["t_min"], days[0]["label"]), (23, 15, "Clear sky"))
        self.assertEqual((days[1]["rain"], days[1]["label"]), (80, "Rain"))
        self.assertEqual(days[0]["day"], "Mon")
        self.assertNotIn("apikey", get.call_args.kwargs["params"])   # Open-Meteo: no key

    @mock.patch("api_client.requests.get")
    def test_forecast_error(self, get):
        get.return_value = fake_response(status=400, json_data={"error": True, "reason": "bad lat"})
        with self.assertRaisesRegex(ApiError, "weather"):
            api_client.get_forecast(999, 999)


if __name__ == "__main__":
    unittest.main()
