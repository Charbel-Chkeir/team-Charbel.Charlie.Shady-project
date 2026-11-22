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
