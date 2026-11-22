"""
WanderWise -- travel guide & trip planner (GIN446 team project).

Content comes from external APIs (see api_client.py). The only data stored is
user accounts and their saved data (see models.py). Authentication is
email + password with Flask sessions.

Run locally:   flask run --debug    ->   http://127.0.0.1:5000
"""
import os
from datetime import timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, abort, g)
from flask_wtf.csrf import CSRFProtect, CSRFError
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, Favorite
import api_client
from validators import validate_signup, validate_login, validate_place

app = Flask(__name__)

# ---------- configuration ------------------------------------------
# Render sets the RENDER environment variable on every service, so we use it
# to know whether we are live (HTTPS) or on a laptop (plain HTTP).
ON_RENDER = "RENDER" in os.environ

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if ON_RENDER:
        # Never run in production with a guessable key: anyone could forge a
        # session cookie and log in as any user.
        raise RuntimeError("SECRET_KEY environment variable is not set.")
    SECRET_KEY = "dev-only-change-me"

app.config.update(
    SECRET_KEY=SECRET_KEY,                 # signs the session cookie + CSRF tokens
    SESSION_COOKIE_HTTPONLY=True,          # JavaScript cannot read the cookie
    SESSION_COOKIE_SAMESITE="Lax",         # not sent on cross-site POSTs
    SESSION_COOKIE_SECURE=ON_RENDER,       # HTTPS only when live (local is HTTP)
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),  # auto-logout after 2h idle
)


def database_uri():
    """PostgreSQL on Render (DATABASE_URL), else a local SQLite file."""
    url = os.environ.get("DATABASE_URL")
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url
    return "sqlite:///" + os.path.abspath("app.db")


app.config["SQLALCHEMY_DATABASE_URI"] = database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
with app.app_context():
    db.create_all()

# CSRF protection: every POST must carry a valid csrf_token (see templates).
csrf = CSRFProtect(app)


# ---------- current user & helpers ---------------------------------
@app.before_request
def load_current_user():
    """Runs before every request: put the logged-in user (or None) in g.user."""
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        user = db.session.get(User, user_id)
        if user is None:          # account was deleted -> drop the stale session
            session.clear()
        else:
            g.user = user


@app.context_processor
def inject_globals():
    """Make the logged-in user (and their favorite ids) available in templates."""
    favorite_ids = set()
    if g.user:
        favorite_ids = {f.place_xid for f in g.user.favorites}
    return {"current_user": g.user, "favorite_ids": favorite_ids}


def login_required(view):
    """Decorator: send visitors to the login page, then back where they were."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in first.")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_next(default_endpoint):
    """Return the 'next' URL only if it is a path on OUR site.

    Without this check, a link like /login?next=https://evil.com would send
    the user to another website after logging in (an "open redirect").
    """
    target = request.values.get("next", "")
    if target.startswith("/") and not target.startswith("//"):
        return target
    return url_for(default_endpoint)


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Missing/expired CSRF token: show a friendly message instead of a raw 400."""
    flash("Your form expired. Please try again.")
    return redirect(request.referrer or url_for("home"))


# ---------- content (from your API) --------------------------------
@app.route("/")
def home():
    return render_template("home.html")


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    items = api_client.search(query) if query else []
    return render_template("results.html", items=items, query=query)


@app.route("/item/<item_id>")
def item(item_id):
    data = api_client.get_item(item_id)
    if not data:
        abort(404)
    return render_template("detail.html", item=data)


# ===================================================================
# AUTHENTICATION  (sign-up, log-in, log-out, sessions)
# ===================================================================
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:                                   # already logged in
        return redirect(url_for("home"))

    if request.method == "POST":
        errors, email = validate_signup(request.form)

        # Reject an email that is already registered.
        if not errors and User.query.filter_by(email=email).first():
            errors["email"] = "An account with this email already exists."

        if errors:
            # Re-show the form with the messages; keep the email, never the password.
            return render_template("signup.html", errors=errors,
                                   data={"email": email}), 400

        user = User(email=email,
                    password_hash=generate_password_hash(request.form["password"]))
        try:
            db.session.add(user)
            db.session.commit()
        except IntegrityError:
            # Two sign-ups with the same email at the same moment: the UNIQUE
            # constraint on User.email catches it. Undo and report it.
            db.session.rollback()
            errors["email"] = "An account with this email already exists."
            return render_template("signup.html", errors=errors,
                                   data={"email": email}), 400

        session.clear()                          # start a fresh session
        session["user_id"] = user.id
        session.permanent = True                 # use PERMANENT_SESSION_LIFETIME
        flash("Welcome to WanderWise! Your account was created.")
        return redirect(url_for("home"))

    return render_template("signup.html", errors={}, data={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("home"))

    if request.method == "POST":
        errors, email = validate_login(request.form)
        if errors:
            return render_template("login.html", errors=errors,
                                   data={"email": email}), 400

        user = User.query.filter_by(email=email).first()
        # Same message whether the email is unknown or the password is wrong,
        # so an attacker cannot learn which emails have accounts.
        if user is None or not check_password_hash(user.password_hash,
                                                   request.form["password"]):
            return render_template(
                "login.html", data={"email": email},
                errors={"form": "Email or password is incorrect."}), 401

        session.clear()                          # prevents session fixation
        session["user_id"] = user.id
        session.permanent = True
        flash("Logged in successfully.")
        return redirect(safe_next("home"))

    return render_template("login.html", errors={}, data={})


@app.route("/logout", methods=["POST"])          # POST + CSRF token (Week 9)
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("home"))


# ---------- favorites (login required) -----------------------------
@app.route("/favorites")
@login_required
def favorites():
    items = (Favorite.query.filter_by(user_id=g.user.id)
             .order_by(Favorite.created_at.desc())      # newest first
             .all())
    return render_template("favorites.html", favorites=items)


@app.route("/favorites/add", methods=["POST"])
@login_required
def favorites_add():
    errors, place = validate_place(request.form)
    if errors:
        flash("Could not save this place: " + " ".join(errors.values()))
        return redirect(safe_next("favorites"))

    try:
        db.session.add(Favorite(user_id=g.user.id,
                                place_xid=place["place_xid"],
                                place_name=place["place_name"],
                                place_image=place["place_image"]))
        db.session.commit()
        flash(f"Saved \"{place['place_name']}\" to favorites.")
    except IntegrityError:
        # UNIQUE (user_id, place_xid) -> it is already saved.
        db.session.rollback()
        flash("Already in your favorites.")
    return redirect(safe_next("favorites"))


@app.route("/favorites/remove", methods=["POST"])
@login_required
def favorites_remove():
    xid = request.form.get("place_xid", "").strip()
    # Filtering by user_id too = ownership check: you can only remove YOUR rows.
    fav = Favorite.query.filter_by(user_id=g.user.id, place_xid=xid).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        flash("Removed from favorites.")
    else:
        flash("That place is not in your favorites.")
    return redirect(safe_next("favorites"))


if __name__ == "__main__":
    app.run(debug=True)
