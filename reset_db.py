"""
reset_db.py  --  drop and recreate ALL tables from models.py.

WARNING: every row is deleted (accounts, favorites, trips). Fine during
development, never on data you want to keep.

LOCAL (SQLite app.db):
    python reset_db.py

RENDER (PostgreSQL), run once from your laptop after a model change:
    1. Render dashboard -> team-db -> Connections -> copy the EXTERNAL Database URL
    2. macOS:   DATABASE_URL="<external url>" python3 reset_db.py
       Windows: $env:DATABASE_URL="<external url>"; python reset_db.py
       (the URL contains the DB password: type it in the terminal only,
        never in a file that goes to GitHub)
    3. Restart / redeploy the web service on Render.
"""
from app import app
from models import db

with app.app_context():
    target = app.config["SQLALCHEMY_DATABASE_URI"].split("@")[-1]  # hide password
    answer = input(f"This deletes ALL data in: {target}\nType 'yes' to continue: ")
    if answer.strip().lower() != "yes":
        raise SystemExit("Cancelled - nothing was changed.")
    db.drop_all()
    db.create_all()
    print("Database reset: tables user, favorite, trip, trip_item created from models.py.")
