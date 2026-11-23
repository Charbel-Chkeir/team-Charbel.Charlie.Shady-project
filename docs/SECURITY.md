# WanderWise – Security

How WanderWise handles each item of the OWASP Top 10 covered in Week 11.
Every line points to the code that does it and, where possible, to the
automated test that proves it (`python3 -m unittest -v`).

| OWASP item | What could go wrong | What WanderWise does | Where | Tested in |
|---|---|---|---|---|
| **A01 Broken Access Control** | A user changes `/trips/7` to `/trips/8` and sees or edits someone else's trip (IDOR). | `get_own_trip()`: `db.get_or_404` (no such row → 404), then `trip.user_id != g.user.id` → **403**. Items are also checked against their trip. Favorites are always filtered by `user_id`. `@login_required` on every private route. | `app.py` | `test_trips`: other user gets 403 on all 8 trip actions |
| | Open redirect: `/login?next=https://evil.com` | `safe_next()` only accepts paths starting with `/` (not `//`). | `app.py` | `test_security`: `https://evil.com`, `//evil.com`, `javascript:` → sent home |
| **A02 Security Misconfiguration** | Debug console in production; weak secret key; missing headers. | Debug only if `FLASK_DEBUG=1` (Render uses gunicorn, never debug). On Render the app **refuses to start** without `SECRET_KEY`. Security headers on every response (below). | `app.py` | `test_security`: debug off, refuses to start, headers |
| **A03 Supply Chain** | A vulnerable or malicious dependency. | Exact versions pinned in `requirements.txt`; `pip-audit -r requirements.txt` → *No known vulnerabilities found* (23 Nov 2026). Leaflet is self-hosted: files identical to the official release (SHA-256 checked, see `static/vendor/leaflet/README.txt`). Only 7 direct dependencies. | `requirements.txt` | `pip-audit` |
| **A04 Cryptographic Failures** | Passwords readable in the DB or on the network. | Passwords hashed with Werkzeug (`scrypt`, salted). HTTPS on Render + **HSTS** header. Session cookie `Secure` on Render. Secrets only in environment variables. | `app.py` | `test_security`: Secure cookie + HSTS in Render mode |
| **A05 Injection (SQLi, XSS)** | `' OR 1=1 --` in a form; `<script>` in a place name from the API. | SQLAlchemy ORM only (parameterised queries, no SQL strings). Jinja auto-escaping everywhere; map data via `\|tojson` and `textContent` in JS. Strict **Content-Security-Policy** `script-src 'self'` as a backstop. Server-side validation of every input. | `app.py`, `validators.py`, `templates/`, `static/js/map.js` | `test_routes`: API text escaped; `test_ui`: map data cannot break out; no inline JS |
| **A06 Insecure Design** | No limits: brute force, API quota abuse. | **Rate limits** (Flask-Limiter): login 5/min, sign-up 10/hour, search 30/min, place & weather 60/min. API: timeouts (6 s), 10-min cache, max 150 places per search. Trips max 60 days, notes max 500 chars. | `app.py`, `api_client.py` | `test_security`: 6th login → 429, 11th sign-up → 429, 31st search → 429 |
| **A07 Authentication Failures** | Brute force; session fixation; account enumeration. | Rate limit on login; `session.clear()` before storing `user_id`; same message for unknown email and wrong password, and **the same work** (a dummy hash check) so timing does not reveal accounts; 2-hour session lifetime; logout is POST + CSRF. | `app.py` | `test_security`: dummy hash used, same message |
| **A08 Integrity Failures** | Untrusted data executed as code. | Only JSON is parsed from outside (API answers, map data); no `pickle`, no `eval`. CSRF tokens on every form (Flask-WTF). | `api_client.py`, `app.py` | `test_trips`: POST without CSRF token rejected |
| **A09 Logging & Alerting** | An attack leaves no trace. | Logged (Render → Logs): failed logins (email + IP, **never the password**), 403 access denied, CSRF failures, rate-limit hits, 500 errors, API failures. | `app.py`, `api_client.py` | `test_security`: failed login logged without password; 403 logged |
| **A10 Exceptional Conditions** | A stack trace shown to users; a crash when the API is down. | Custom 400/403/404/429/500/503 pages; 500 handler rolls back the DB session and logs; `try/except IntegrityError` + `rollback()` on writes; API errors become friendly messages (`ApiError`), weather failures degrade gracefully. | `app.py`, `api_client.py` | `test_routes`: API down → 503 page; `test_api_client`: 9 failure cases |

## Security headers (every response)

```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self';
    img-src 'self' data: https:; connect-src 'self'; object-src 'none';
    base-uri 'self'; form-action 'self'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
Strict-Transport-Security: max-age=31536000; includeSubDomains     (Render / HTTPS only)
```

`img-src https:` allows photos from Wikimedia and map tiles from OpenStreetMap;
images cannot run code, so this does not weaken the script protection. There
is **no inline JavaScript** in the templates (all in `static/js/`), which is
what makes `script-src 'self'` possible (checked by `test_ui`).

## Running behind Render's proxy

Render forwards requests through a proxy. `ProxyFix` (only when `RENDER` is
set) makes Flask use the visitor's real IP (`X-Forwarded-For`) and `https`
(`X-Forwarded-Proto`). Without it, the rate limiter would see every visitor as
the same IP, so one attacker could lock everyone out of the login page.

## Known limits (accepted for this project)

- **Sign-up reveals that an email is registered** ("An account with this email
  already exists"). Fully hiding it needs email verification, which the app
  cannot send. Sign-up is rate-limited (10/hour per IP) to slow down scanning.
- **Rate-limit counters are kept in memory**, per gunicorn worker, and reset
  on restart. Enough for one small Render instance; a shared store (Redis)
  would be needed for several servers.
- **No password reset** is implemented (no email sending).
