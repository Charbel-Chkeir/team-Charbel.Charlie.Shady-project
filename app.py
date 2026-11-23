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
from validators import (validate_signup, validate_login, validate_place,
                        validate_search, validate_coords, is_valid_xid)

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
    """Variables every template can use: the logged-in user, the ids of their
    favorite places, and the category list (for search forms and filters)."""
    favorite_ids = set()
    if g.user:
        favorite_ids = {f.place_xid for f in g.user.favorites}
    return {"current_user": g.user, "favorite_ids": favorite_ids,
            "categories": api_client.CATEGORIES}


def login_required(view):
    """Decorator: send visitors to the login page, then back where they were."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in first.")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.template_global()
def back_url():
    """URL for a "← Back" link: the previous page if it was on OUR site
    (and is not this same page), otherwise the home page."""
    ref = request.referrer or ""
    if ref.startswith(request.host_url) and ref != request.url:
        return ref
    return url_for("home")


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


# ===================================================================
# CONTENT  (search, place details, weather -- data from api_client.py)
# ===================================================================
def api_error_page(error):
    """External API failed (slow, down, rate-limited): friendly page, HTTP 503."""
    return render_template("error.html", code=503, title="Service unavailable",
                           message=str(error)), 503


@app.route("/")
def home():
    return render_template("home.html", errors={}, form={"city": "", "kind": "all"})


@app.route("/search")
def search():
    """/search?city=Rome&kind=historic&page=2"""
    errors, form = validate_search(request.args, api_client.CATEGORIES)
    if errors:
        return render_template("home.html", errors=errors, form=form), 400

    try:
        city = api_client.find_city(form["city"])
        if city is None:
            errors["city"] = f"We could not find a city called \"{form['city']}\"."
            return render_template("home.html", errors=errors, form=form), 404
        result = api_client.list_places(city["lat"], city["lon"],
                                        form["kind"], form["page"])
    except api_client.ApiError as e:
        return render_template("home.html", form=form,
                               errors={"form": str(e)}), 503

    # Weather is a bonus: if it fails, the attractions are still shown.
    try:
        forecast = api_client.get_forecast(city["lat"], city["lon"])
    except api_client.ApiError:
        forecast = None

    return render_template("results.html", city=city, form=form,
                           result=result, forecast=forecast)


@app.route("/place/<xid>")
def place(xid):
    if not is_valid_xid(xid):
        abort(404)
    try:
        data = api_client.get_place(xid)
    except api_client.ApiError as e:
        return api_error_page(e)
    if data is None:
        abort(404)
    return render_template("place.html", place=data)


@app.route("/weather")
def weather():
    """/weather?lat=33.89&lon=35.50&name=Beirut"""
    errors, form = validate_coords(request.args)
    if errors:
        return render_template("error.html", code=400, title="Invalid location",
                               message=" ".join(errors.values())), 400
    try:
        forecast = api_client.get_forecast(form["lat"], form["lon"])
    except api_client.ApiError as e:
        return api_error_page(e)
    label = form["name"] or f"{form['lat']:.2f}, {form['lon']:.2f}"
    return render_template("weather.html", forecast=forecast, label=label)


# ---------- error pages ----------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, title="Page not found",
                           message="The page or place you asked for does not exist."), 404


@app.errorhandler(500)
def server_error(e):
    db.session.rollback()       # a failed DB operation must not break the next request
    return render_template("error.html", code=500, title="Something went wrong",
                           message="An unexpected error happened. Please try again."), 500


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
