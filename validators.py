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
