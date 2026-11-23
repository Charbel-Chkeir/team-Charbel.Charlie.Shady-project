"""Server-side validation (the Week 8 skill).

Every function takes the submitted form (request.form) and returns
(errors, cleaned_value). `errors` is a dict {field_name: message}; an empty dict
means the input is valid. The browser's own checks (type="email", required...)
can be bypassed with curl / Thunder Client, so the SERVER always re-checks.
"""
import re

# something@domain.tld  (simple on purpose: the real test is the user logging in)
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")

EMAIL_MAX = 255        # matches User.email = db.String(255) in models.py
PASSWORD_MIN = 8
PASSWORD_MAX = 128     # very long inputs make hashing slow -> cap them


def validate_signup(form):
    errors = {}
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    confirm = form.get("confirm", "")

    # 1. Email: required, max length, valid format
    if email == "":
        errors["email"] = "Email is required."
    elif len(email) > EMAIL_MAX:
        errors["email"] = "Email is too long."
    elif not EMAIL.match(email):
        errors["email"] = "Enter a valid email address."

    # 2. Password: required, length range, at least one letter and one digit
    if password == "":
        errors["password"] = "Password is required."
    elif len(password) < PASSWORD_MIN:
        errors["password"] = f"Password must be at least {PASSWORD_MIN} characters."
    elif len(password) > PASSWORD_MAX:
        errors["password"] = f"Password must be at most {PASSWORD_MAX} characters."
    elif not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        errors["password"] = "Password must contain at least one letter and one number."

    # 3. Confirmation: required and must match
    if confirm == "":
        errors["confirm"] = "Please confirm your password."
    elif confirm != password:
        errors["confirm"] = "Passwords do not match."

    return errors, email


def validate_login(form):
    errors = {}
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    if email == "":
        errors["email"] = "Email is required."
    if password == "":
        errors["password"] = "Password is required."
    return errors, email


# ---------- places (favorites, and trip items later) ---------------
# OpenTripMap xids are letters/digits, e.g. "N2451418410", "W123456", "Q90".
XID = re.compile(r"^[A-Za-z0-9]{1,50}$")
HTTPS_URL = re.compile(r"^https://[^\s\"'<>]{1,490}$")
PLACE_NAME_MAX = 255


def validate_place(form):
    """Check the place fields sent by a 'Save' form (hidden inputs).

    Hidden inputs are NOT safe: anyone can change them with DevTools or curl,
    so every value is checked here before it reaches the database.
    """
    errors = {}
    xid = form.get("place_xid", "").strip()
    name = form.get("place_name", "").strip()
    image = form.get("place_image", "").strip()

    if not XID.match(xid):
        errors["place_xid"] = "Invalid place id."

    if name == "":
        errors["place_name"] = "Place name is missing."
    elif len(name) > PLACE_NAME_MAX:
        name = name[:PLACE_NAME_MAX]          # very long API names: shorten

    if image != "" and not HTTPS_URL.match(image):
        image = ""                            # bad image URL: just drop it

    return errors, {"place_xid": xid, "place_name": name, "place_image": image}


# ---------- search / weather (query-string input: GET ?city=...&kind=...) ----------
CITY_MIN, CITY_MAX = 2, 80
CITY_CHARS = " -'.,"        # besides letters: "Rio de Janeiro", "Saint-Malo", "Ta' Xbiex"
PAGE_MAX = 100


def validate_search(args, categories):
    """Check /search?city=...&kind=...&page=...

    `categories` = api_client.CATEGORIES (the only allowed kind values).
    Returns (errors, {"city", "kind", "page"}).
    """
    errors = {}
    city = " ".join(args.get("city", "").split())      # trim + collapse spaces
    kind = args.get("kind", "all").strip() or "all"
    page_text = args.get("page", "1").strip() or "1"

    # City: required, length range, only letters (any language) + a few symbols
    if city == "":
        errors["city"] = "Please enter a city."
    elif not CITY_MIN <= len(city) <= CITY_MAX:
        errors["city"] = f"City name must be {CITY_MIN} to {CITY_MAX} characters."
    elif not all(ch.isalpha() or ch in CITY_CHARS for ch in city):
        errors["city"] = "City name can only contain letters, spaces and - ' . ,"

    # Category: must be one of OUR keys (never sent to the API unchecked)
    if kind not in categories:
        errors["kind"] = "Unknown category."

    # Page: whole number between 1 and PAGE_MAX
    page = 1
    # isdecimal(), not isdigit(): "²".isdigit() is True but int("²") crashes
    if not page_text.isdecimal() or not 1 <= int(page_text) <= PAGE_MAX:
        errors["page"] = "Invalid page number."
    else:
        page = int(page_text)

    return errors, {"city": city, "kind": kind, "page": page}


def _number(text, low, high):
    """'33.89' -> 33.89 if it is a real number in [low, high], else None."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value != value or not low <= value <= high:      # value != value -> NaN
        return None
    return value


def validate_coords(args):
    """Check ?lat=...&lon=...(&name=...) for the weather page."""
    errors = {}
    lat = _number(args.get("lat"), -90, 90)
    lon = _number(args.get("lon"), -180, 180)
    if lat is None:
        errors["lat"] = "Latitude must be a number between -90 and 90."
    if lon is None:
        errors["lon"] = "Longitude must be a number between -180 and 180."
    name = " ".join(args.get("name", "").split())[:80]  # optional label, shortened
    return errors, {"lat": lat, "lon": lon, "name": name}


def is_valid_xid(xid):
    """OpenTripMap place id in a URL like /place/<xid>."""
    return bool(XID.match(xid or ""))
