"""
api_client.py  --  ALL calls to the external APIs live here (one place).

    OpenTripMap  (https://dev.opentripmap.org)  -> cities, attractions, details
    Open-Meteo   (https://open-meteo.com)       -> 7-day weather forecast

The rest of the app never sees raw API JSON: every function returns simple
dicts/lists with the fields the templates need.

Public functions
    find_city(name)                    -> dict or None (city not found)
    list_places(lat, lon, kind, page)  -> dict {places, page, pages, total}
    get_place(xid)                     -> dict or None (place not found)
    get_forecast(lat, lon)             -> list of 7 day dicts

Errors
    "Not found" is a normal answer -> the function returns None.
    "The API is broken/slow/limited" -> the function raises ApiError, whose
    message is safe to show to the user. Routes catch it and show the message.

Try it on your machine (key in the terminal only, never in a file):
    OPENTRIPMAP_API_KEY="your-key" python3 api_client.py Beirut
"""
import logging
import os
import re
import time
from datetime import date

import requests

log = logging.getLogger(__name__)

OTM_URL = "https://api.opentripmap.com/0.1/en/places"
METEO_URL = "https://api.open-meteo.com/v1/forecast"

TIMEOUT = 6              # seconds: give up instead of freezing the page
CACHE_SECONDS = 600      # keep answers 10 minutes (saves the 5000 req/day quota)
CACHE_MAX_ENTRIES = 300  # never let the cache grow without limit
SEARCH_RADIUS_M = 10000  # look for attractions within 10 km of the city centre
MAX_PLACES = 150         # ask the API for at most this many per search
PAGE_SIZE = 12           # attractions per results page

# Categories offered to the user.  key (in the URL) -> (label, OpenTripMap kinds)
# Only these keys are accepted: validators.py checks ?kind= against this dict.
CATEGORIES = {
    "all":          ("All attractions",     "interesting_places"),
    "cultural":     ("Culture & museums",   "cultural"),
    "historic":     ("Historic sites",      "historic"),
    "architecture": ("Architecture",        "architecture"),
    "natural":      ("Nature & parks",      "natural"),
    "religion":     ("Religious sites",     "religion"),
    "amusements":   ("Fun & entertainment", "amusements"),
    "foods":        ("Food & drink",        "foods"),
}


class ApiError(Exception):
    """The external service failed. str(error) is a user-friendly message."""


# ===================================================================
# Small in-memory cache
# ===================================================================
_cache = {}   # key -> (expires_at, value)


def _cached(key, fetch):
    """Return the cached value for `key`, or call fetch() and remember it.

    Only SUCCESSFUL answers are cached (if fetch() raises ApiError, nothing is
    stored, so the next request tries the API again).
    Note: each Gunicorn worker has its own cache; that is fine for this app.
    """
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]

    value = fetch()
    if len(_cache) >= CACHE_MAX_ENTRIES:        # full: drop expired, then oldest
        for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
            del _cache[k]
        while len(_cache) >= CACHE_MAX_ENTRIES:
            del _cache[next(iter(_cache))]
    _cache[key] = (now + CACHE_SECONDS, value)
    return value


def clear_cache():
    _cache.clear()


# ===================================================================
# One place that performs HTTP requests and turns failures into ApiError
# ===================================================================
def _get_json(url, params, service):
    """GET url and return the decoded JSON, or None for HTTP 404.

    Raises ApiError (with a friendly message) for every other problem.
    """
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
    except requests.Timeout:
        log.warning("%s timed out: %s", service, url)
        raise ApiError(f"{service} is taking too long to answer. Please try again.")
    except requests.RequestException as e:
        log.warning("%s unreachable: %s", service, e)
        raise ApiError(f"{service} is unreachable right now. Please try again later.")

    if r.status_code == 404:
        return None
    if r.status_code == 429:
        log.warning("%s rate limit reached", service)
        raise ApiError(f"{service} is receiving too many requests. Wait a minute and retry.")
    if r.status_code in (401, 403):
        log.error("%s rejected our API key (HTTP %s)", service, r.status_code)
        raise ApiError(f"{service} is not available (configuration problem).")
    if r.status_code != 200:
        log.warning("%s returned HTTP %s: %s", service, r.status_code, r.text[:200])
        raise ApiError(f"{service} returned an error. Please try again later.")

    try:
        return r.json()
    except ValueError:
        log.warning("%s sent invalid JSON", service)
        raise ApiError(f"{service} sent an unreadable answer. Please try again later.")


def _otm(path, **params):
    """Call OpenTripMap: adds the API key (read from the environment)."""
    key = os.environ.get("OPENTRIPMAP_API_KEY")
    if not key:
        log.error("OPENTRIPMAP_API_KEY is not set")
        raise ApiError("Attraction search is not configured on this server.")
    params["apikey"] = key
    return _get_json(f"{OTM_URL}/{path}", params, "The attractions service")


# ===================================================================
# Helpers that clean API data
# ===================================================================
def _pretty_kinds(kinds):
    """'museums,cultural,interesting_places' -> ['Museums', 'Cultural']"""
    skip = {"interesting_places", "other", "unclassified_objects", "tourist_object"}
    out = []
    for k in (kinds or "").split(","):
        k = k.strip()
        # "other_churches", "other_hotels"... add nothing useful -> skip them
        if k and k not in skip and not k.startswith("other"):
            label = k.replace("_", " ").capitalize()
            if label not in out:
                out.append(label)
    return out[:4]


def _rate(value):
    """OpenTripMap popularity: 3, "3", "3h" (h = heritage) or missing -> 0..3"""
    m = re.match(r"\d", str(value or ""))
    return int(m.group()) if m else 0


def _https_or_none(url):
    """Only keep secure links (http images are blocked on an https site)."""
    if isinstance(url, str) and url.startswith("https://"):
        return url
    return None


# Wikimedia only serves thumbnails at these widths; any other width
# (OpenTripMap often sends 400px) is refused with HTTP 429/400.
WIKIMEDIA_WIDTHS = (20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840)
_THUMB_WIDTH = re.compile(r"(/thumb/.+/)(\d+)px-([^/]+)$")


def _image_url(url, width=500):
    """Secure image URL; Wikimedia thumbnails rewritten to a standard width.

    .../thumb/9/9c/File.jpg/400px-File.jpg -> .../thumb/9/9c/File.jpg/500px-File.jpg
    """
    url = _https_or_none(url)
    if url and "upload.wikimedia.org" in url:
        url = _THUMB_WIDTH.sub(lambda m: f"{m.group(1)}{width}px-{m.group(3)}", url)
    return url


def _address(addr):
    """OpenTripMap address dict -> 'Road 12, Beirut, Lebanon' (or '')."""
    if not isinstance(addr, dict):
        return ""
    street = " ".join(p for p in [addr.get("road"), addr.get("house_number")] if p)
    town = addr.get("city") or addr.get("town") or addr.get("village") or ""
    parts = [street, addr.get("suburb"), town, addr.get("state"), addr.get("country")]
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return ", ".join(out)


# ===================================================================
# 1. City -> coordinates
# ===================================================================
def find_city(name):
    """Return {"name", "country", "lat", "lon"} or None if the city is unknown."""
    name = name.strip()
    key = ("city", name.lower())

    def fetch():
        data = _otm("geoname", name=name)
        if not data or data.get("status") != "OK":
            return None                      # OpenTripMap: {"status": "NOT_FOUND"}
        return {"name": data.get("name", name),
                "country": data.get("country", ""),
                "lat": float(data["lat"]),
                "lon": float(data["lon"])}

    return _cached(key, fetch)


# ===================================================================
# 2. Attractions around a point (one category), paginated
# ===================================================================
def _all_places(lat, lon, kind):
    """The full, cleaned list for one search (cached). At most MAX_PLACES."""
    lat, lon = round(lat, 4), round(lon, 4)  # nearby clicks share the cache
    key = ("places", lat, lon, kind)

    def fetch():
        data = _otm("radius", radius=SEARCH_RADIUS_M, lat=lat, lon=lon,
                    kinds=CATEGORIES[kind][1], rate=1, format="json",
                    limit=MAX_PLACES)
        if not isinstance(data, list):
            return []
        places, seen_names = [], set()
        for p in data:
            name = (p.get("name") or "").strip()
            point = p.get("point") or {}
            # Skip unnamed objects and duplicates (OSM + Wikidata copies).
            if not name or name.lower() in seen_names or "lat" not in point:
                continue
            seen_names.add(name.lower())
            places.append({
                "xid": p["xid"],
                "name": name,
                "kinds": _pretty_kinds(p.get("kinds")),
                "rate": _rate(p.get("rate")),
                "dist_km": round((p.get("dist") or 0) / 1000, 1),
                "lat": point["lat"],
                "lon": point["lon"],
            })
        # Most popular first, then closest first.
        places.sort(key=lambda x: (-x["rate"], x["dist_km"]))
        return places

    return _cached(key, fetch)


def list_places(lat, lon, kind="all", page=1):
    """Return one page of attractions:
        {"places": [...], "page": 2, "pages": 5, "total": 57}
    `kind` must be a key of CATEGORIES (validated before calling this).
    """
    if kind not in CATEGORIES:
        raise ValueError(f"unknown category {kind!r}")
    places = _all_places(lat, lon, kind)
    total = len(places)
    pages = max(1, -(-total // PAGE_SIZE))   # ceiling division
    page = min(max(1, page), pages)          # keep page inside 1..pages
    start = (page - 1) * PAGE_SIZE
    return {"places": places[start:start + PAGE_SIZE],
            "page": page, "pages": pages, "total": total}


# ===================================================================
# 3. One attraction's details
# ===================================================================
def get_place(xid):
    """Return full details, or None if OpenTripMap does not know this xid.

    Image, description, address and links are often missing: they are then
    None / "" and the template shows a placeholder.
    """
    # The xid goes INTO the URL path, so only letters/digits are allowed
    # (blocks things like "../" even if a route forgot to validate it).
    if not re.fullmatch(r"[A-Za-z0-9]{1,50}", str(xid)):
        return None

    def fetch():
        data = _otm(f"xid/{xid}")
        if not data or "xid" not in data or "point" not in data:
            return None
        extracts = data.get("wikipedia_extracts") or {}
        info = data.get("info") or {}
        preview = data.get("preview") or {}
        return {
            "xid": data["xid"],
            "name": (data.get("name") or "").strip() or "Unnamed place",
            "kinds": _pretty_kinds(data.get("kinds")),
            "address": _address(data.get("address")),
            "description": (extracts.get("text") or info.get("descr") or "").strip(),
            "image": _image_url(preview.get("source")),
            "wikipedia": _https_or_none(data.get("wikipedia")),
            "website": data.get("url") if str(data.get("url", "")).startswith(("http://", "https://")) else None,
            "lat": data["point"]["lat"],
            "lon": data["point"]["lon"],
        }

    return _cached(("place", xid), fetch)


# ===================================================================
# 4. Weather (Open-Meteo, no key needed)
# ===================================================================
# WMO weather codes used by Open-Meteo -> (label, icon)
WEATHER_CODES = {
    0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"), 45: ("Fog", "🌫️"), 48: ("Fog", "🌫️"),
    51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌧️"),
    56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"), 73: ("Snow", "🌨️"), 75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"), 80: ("Rain showers", "🌦️"), 81: ("Rain showers", "🌧️"),
    82: ("Violent showers", "⛈️"), 85: ("Snow showers", "🌨️"), 86: ("Snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm, hail", "⛈️"), 99: ("Thunderstorm, hail", "⛈️"),
}


def get_forecast(lat, lon):
    """Return 7 days: [{"date", "day", "t_max", "t_min", "rain", "label", "icon"}]"""
    lat, lon = round(lat, 2), round(lon, 2)  # ~1 km: same city -> same cache entry

    def fetch():
        data = _get_json(METEO_URL, {
            "latitude": lat, "longitude": lon, "timezone": "auto",
            "forecast_days": 7,
            "daily": "temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max,weather_code",
        }, "The weather service")
        daily = (data or {}).get("daily")
        if not daily or not daily.get("time"):
            raise ApiError("The weather service sent no forecast.")
        days = []
        for i, day in enumerate(daily["time"]):
            code = daily["weather_code"][i]
            label, icon = WEATHER_CODES.get(code, ("Unknown", "❔"))
            d = date.fromisoformat(day)
            t_max, t_min = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
            rain = daily["precipitation_probability_max"][i]
            days.append({
                "date": d,
                "day": d.strftime("%a"),                      # Mon, Tue ...
                "t_max": round(t_max) if t_max is not None else None,
                "t_min": round(t_min) if t_min is not None else None,
                "rain": rain,                                 # % or None
                "label": label, "icon": icon,
            })
        return days

    return _cached(("weather", lat, lon), fetch)


# ===================================================================
# Temporary adapters for the STARTER routes (/search?q=, /item/<id>).
# Step 4 replaces those routes; then these two functions are deleted.
# ===================================================================
def search(query):
    city = find_city(query)
    if not city:
        return []
    return [{"id": p["xid"], "title": p["name"], "image": None}
            for p in list_places(city["lat"], city["lon"])["places"]]


def get_item(item_id):
    p = get_place(item_id)
    if not p:
        return None
    return {"id": p["xid"], "title": p["name"], "image": p["image"],
            "description": p["description"] or "No description available."}


# ===================================================================
# Manual test:  OPENTRIPMAP_API_KEY="..." python3 api_client.py Beirut
# ===================================================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    city_name = sys.argv[1] if len(sys.argv) > 1 else "Beirut"
    try:
        city = find_city(city_name)
        if city is None:
            sys.exit(f"City not found: {city_name}")
        print(f"\nCITY: {city}")

        result = list_places(city["lat"], city["lon"], "all", 1)
        print(f"\nPLACES: {result['total']} found, page {result['page']}/{result['pages']}")
        for p in result["places"]:
            print(f"  - {p['name']:<40} {p['dist_km']:>5} km  rate {p['rate']}  {', '.join(p['kinds'])}")

        if result["places"]:
            detail = get_place(result["places"][0]["xid"])
            print(f"\nDETAIL of first place:")
            for k, v in (detail or {}).items():
                print(f"  {k:<12} {str(v)[:90]}")

        print("\nFORECAST:")
        for d in get_forecast(city["lat"], city["lon"]):
            print(f"  {d['day']} {d['date']}  {d['icon']} {d['label']:<18} "
                  f"{d['t_min']}°/{d['t_max']}°C  rain {d['rain']}%")

        t = time.monotonic(); find_city(city_name)
        print(f"\nSecond find_city call took {1000 * (time.monotonic() - t):.2f} ms (cache works)")
    except ApiError as e:
        sys.exit(f"API ERROR: {e}")
