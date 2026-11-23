# WanderWise – Testing

## 1. Automated tests (79)

Run from the project folder, with the virtual environment active:

```
python3 -m unittest -v
```

No internet and no API key are needed: the external APIs are replaced by
fake answers (`unittest.mock`), and the tests use a temporary in-memory
database (never `app.db` and never Render's database).

| File | Tests | What it checks |
|---|---|---|
| `tests/test_api_client.py` | 20 | OpenTripMap / Open-Meteo client: data cleaning, sorting, pagination, cache, Wikimedia image sizes, and **9 failure cases** (timeout, unreachable, 401/403/404/429/500, bad JSON, missing key) |
| `tests/test_validators.py` | 11 | Server-side validation: city, category, page, coordinates, place id, sign-up, trip and itinerary rules |
| `tests/test_routes.py` | 15 | Search, place, weather and error pages; bad input never reaches the API; API down → 503; weather down → places still shown; XSS in API data is escaped |
| `tests/test_trips.py` | 14 | Trips and itinerary CRUD, validation, ownership (**403 for another user on all 8 actions**), cascade delete, CSRF on POST |
| `tests/test_ui.py` | 5 | Map data, static files, **no inline JavaScript** in templates (needed for the CSP) |
| `tests/test_security.py` | 14 | Security headers + CSP, rate limits (login, sign-up, search), open redirect, account enumeration, logging without passwords, cookie flags, debug off, no secrets in code, Render mode (ProxyFix, HSTS, Secure cookie, refuses to start without `SECRET_KEY`) |

The tests also ran against **PostgreSQL 16** (the database Render uses) with
the same result.

## 2. Dependency audit

```
pip install pip-audit
pip-audit -r requirements.txt
```
Result on 23 Nov 2026: **No known vulnerabilities found**.

## 3. Manual checklist (browser)

| # | Action | Expected |
|---|---|---|
| 1 | Search `Beirut` | Weather row, 8 categories, 12 cards, numbered map, page numbers |
| 2 | Click *Historic sites*, then page 2 | Filter highlighted, "page 2 of …" |
| 3 | Search `Qwertyzzz` | "We could not find a city called …" |
| 4 | Search `<script>` | "City name can only contain letters …" (shown as text) |
| 5 | Open a place without a photo | "Image unavailable" box |
| 6 | Sign up with `abc` / short password | Error messages, email kept, password not |
| 7 | Log in with a wrong password 6 times | 6th attempt → "Too many requests" (429) |
| 8 | Create a trip, add 3 places, use ↑ ↓ ✕ and *Edit day & notes* | Order, days and notes update; numbers match the map |
| 9 | Delete a trip → *Cancel* | Nothing deleted |
| 10 | Second account (private window) opens `/trips/1` | **403 Not allowed** |
| 11 | Narrow window (phone size) | ☰ Menu, no sideways scrolling, weather row scrolls by itself |

## 4. Manual checks with curl (or Thunder Client)

Replace `URL` with `http://127.0.0.1:5000` or your Render URL.

```
# Security headers (CSP, nosniff, frame options; HSTS on Render)
curl -sI URL/ | grep -i -E "content-security|x-frame|x-content|strict-transport"

# Validation: bad input -> 400, invalid place id -> 404 (rejected before calling the API),
# bad coordinates -> 400
curl -s -o /dev/null -w "%{http_code}\n" "URL/search?city=%3Cscript%3E"
curl -s -o /dev/null -w "%{http_code}\n" "URL/place/bad-id"
curl -s -o /dev/null -w "%{http_code}\n" "URL/weather?lat=999&lon=0"

# Private pages need login -> 302 redirect to /login
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" URL/trips

# Changing data needs POST + CSRF token: GET is refused (405), POST without token is rejected
curl -s -o /dev/null -w "%{http_code}\n" URL/logout
curl -s -o /dev/null -w "%{http_code}\n" -X POST URL/trips/1/delete

# Brute force: the 6th login POST in a minute -> 429
for i in 1 2 3 4 5 6; do curl -s -o /dev/null -w "%{http_code} " -X POST -d "email=a@b.com&password=x" URL/login; done; echo
```

Expected: `400`, `404`, `400`, `302 …/login?next=/trips`, `405`, `302`, and
for the last loop the CSRF check answers first (`302` each time). To see the
`429`, use the browser (check 7 above), which sends a valid CSRF token.
