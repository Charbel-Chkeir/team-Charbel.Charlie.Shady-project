"""
check_api.py -- quick health check of the external APIs WanderWise depends on.

Usage (inside the activated venv):
    Windows (PowerShell):  $env:OPENTRIPMAP_API_KEY="your-key";  python check_api.py
    macOS / Linux:         OPENTRIPMAP_API_KEY="your-key" python3 check_api.py

The key is read from an environment variable on purpose: it must never be
written in a file that goes to GitHub.
"""
import os
import sys

import requests

KEY = os.environ.get("OPENTRIPMAP_API_KEY", "")
OTM = "https://api.opentripmap.com/0.1/en/places"
TIMEOUT = 8


def show(title, r):
    print(f"\n=== {title}\n    HTTP {r.status_code}  ({r.elapsed.total_seconds():.2f}s)")
    print("   ", r.text[:300].replace("\n", " "))
    return r.status_code == 200


def main():
    if not KEY:
        sys.exit("OPENTRIPMAP_API_KEY is not set. See the usage at the top of this file.")

    # 1. City -> coordinates
    r = requests.get(f"{OTM}/geoname", params={"name": "Beirut", "apikey": KEY}, timeout=TIMEOUT)
    if not show("1. geoname (Beirut)", r) or r.json().get("status") != "OK":
        sys.exit("\nFAILED at step 1: the key is wrong/inactive or the API is down.")
    city = r.json()
    lat, lon = city["lat"], city["lon"]

    # 2. Attractions around the city
    r = requests.get(f"{OTM}/radius", timeout=TIMEOUT, params={
        "radius": 3000, "lat": lat, "lon": lon, "kinds": "interesting_places",
        "rate": 2, "limit": 5, "format": "json", "apikey": KEY})
    if not show("2. radius (5 attractions within 3 km)", r) or not r.json():
        sys.exit("\nFAILED at step 2.")
    first = r.json()[0]
    print("    first place:", first.get("name"), "| xid:", first.get("xid"))

    # 3. Details of one attraction
    r = requests.get(f"{OTM}/xid/{first['xid']}", params={"apikey": KEY}, timeout=TIMEOUT)
    if not show(f"3. xid details ({first['xid']})", r):
        sys.exit("\nFAILED at step 3.")
    d = r.json()
    print("    has image:", bool(d.get("preview")),
          "| has description:", bool(d.get("wikipedia_extracts")))

    # 4. Weather (Open-Meteo, no key)
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=TIMEOUT, params={
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"})
    if not show("4. open-meteo forecast", r):
        sys.exit("\nFAILED at step 4.")

    print("\nALL CHECKS PASSED - both APIs work with this key.")


if __name__ == "__main__":
    main()
